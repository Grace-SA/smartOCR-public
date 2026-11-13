import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from receipt_detail_views import prepare_detail
from scripts import run_detail_reviews as detail


class DetailOxrRetryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.cache = self.root/'data/ensemble'
        self.cache.mkdir(parents=True)
        self.addCleanup(patch.stopall)
        patch.object(detail, 'ROOT', self.root).start()
        patch.object(detail, 'CACHE', self.cache).start()
        self.process = patch.object(detail.subprocess, 'run').start()
        self.source = self.cache/'receipt.png'
        Image.new('RGB', (220, 600), (230, 220, 200)).save(self.source)
        self.image = self.cache/'detail/total/images/receipt.png'
        paddle = {'input_sha256': detail.sha(self.source), 'image_size': [220, 600], 'lines': []}
        self.meta = prepare_detail(self.source, paddle, 'total', self.image)
        self.request = {'id': 'receipt', 'field': 'total', 'path': str(self.image), 'sha256': detail.sha(self.image)}
        self.target = self.cache/'detail/total/oxr/receipt.json'
        self.target.parent.mkdir(parents=True)

    def raw(self, *, empty=False, capped=False, direct=False):
        raw = {'engine': 'TEST-ONLY-OXR', 'input_sha256': detail.sha(self.image),
               'image_size': self.meta['output_size'], 'coordinate_space': 'pixels', 'capped': capped,
               'blocks': [{'label': 'image' if empty else 'text', 'content': 'photo' if empty else 'TOTAL $21.00',
                           'bbox': [0, 0, *self.meta['output_size']]}]}
        if direct:
            task = 'table' if self.request['field'] == 'total' else 'text'
            raw.update(recognition_variant='direct_'+task, layout_bypassed=True,
                       calls=[{'tokens': 4096 if capped else 15, 'capped': capped}])
        return raw

    def save(self, raw):
        self.target.write_text(json.dumps(raw))
        return self.target.read_bytes()

    def run_details(self):
        with redirect_stdout(io.StringIO()):
            return detail.run_engine_details('oxr', [self.request])[0]

    def assert_archived(self, previous):
        digest = hashlib.sha256(previous).hexdigest()
        path = self.target.parent/'attempts/receipt'/f'{digest}.json'
        self.assertEqual(path.read_bytes(), previous)

    def test_complete_cache_recovers_detail_metadata_without_inference(self):
        original = self.save(self.raw())
        info = self.run_details()
        self.process.assert_not_called()
        self.assertEqual(info['processed'], 0)
        self.assertEqual(info['status'], 'complete')
        result = json.loads(self.target.read_text())
        self.assertEqual(result['variant'], 'detail')
        self.assertEqual(result['field'], 'total')
        self.assertEqual(result['source_input_sha256'], detail.sha(self.source))
        self.assertEqual(result['detail'], self.meta)
        self.assert_archived(original)

    def test_cached_empty_or_capped_layout_goes_direct_once_and_keeps_one_engine(self):
        for empty, capped in ((True, False), (False, True)):
            with self.subTest(empty=empty, capped=capped):
                self.process.reset_mock()
                original_source = self.source.read_bytes()
                original_view = self.image.read_bytes()
                old = self.save(self.raw(empty=empty, capped=capped))
                def successful(command, **kwargs):
                    self.assertEqual(Path(command[1]).name, 'run_direct_oxr.py')
                    self.assertEqual(command[command.index('--repetition-penalty')+1], '1.05')
                    self.assertEqual(command[command.index('--task')+1], 'table')
                    self.assertEqual(command[-1], str(self.image))
                    self.save(self.raw(direct=True))
                    return SimpleNamespace(returncode=0)
                self.process.side_effect = successful
                info = self.run_details()
                self.process.assert_called_once()
                self.assertEqual((info['layout_processed'], info['direct_processed']), (0, 1))
                self.assertEqual(info['status'], 'complete')
                self.assertTrue(info['output_complete'])
                result = json.loads(self.target.read_text())
                self.assertEqual(result['engine'], 'TEST-ONLY-OXR')
                self.assertEqual(result['variant'], 'detail')
                self.assertEqual(result['recognition_variant'], 'direct_table')
                self.assertEqual(result['input_sha256'], result['detail']['output_sha256'])
                self.assertEqual(result['source_input_sha256'], detail.sha(self.source))
                self.assert_archived(old)
                self.assertEqual(self.source.read_bytes(), original_source)
                self.assertEqual(self.image.read_bytes(), original_view)
                self.process.reset_mock()
                self.assertEqual(self.run_details()['processed'], 0)
                self.process.assert_not_called()

    def test_fresh_detail_has_two_attempt_limit_and_failed_direct_is_cached(self):
        produced = []
        def failed(command, **kwargs):
            direct = Path(command[1]).name == 'run_direct_oxr.py'
            produced.append(self.save(self.raw(empty=True, capped=True, direct=direct)))
            return SimpleNamespace(returncode=0)
        self.process.side_effect = failed
        info = self.run_details()
        self.assertEqual(self.process.call_count, 2)
        self.assertEqual((info['layout_processed'], info['direct_processed']), (1, 1))
        self.assertEqual(info['status'], 'incomplete')
        self.assertEqual(info['retry_exhausted'], 1)
        self.assertFalse(info['output_complete'])
        for old in produced:
            self.assert_archived(old)
        self.process.reset_mock()
        self.assertEqual(self.run_details()['processed'], 0)
        self.process.assert_not_called()

    def test_request_hash_mismatch_is_rejected_before_model_call(self):
        self.request['sha256'] = 'wrong image'
        with self.assertRaisesRegex(ValueError, 'verified field/image provenance'):
            self.run_details()
        self.process.assert_not_called()

    def test_direct_result_hash_must_match_detail_view(self):
        old = self.save(self.raw(empty=True))
        def mismatched(command, **kwargs):
            raw = self.raw(direct=True)
            raw['input_sha256'] = 'wrong image'
            self.save(raw)
            return SimpleNamespace(returncode=0)
        self.process.side_effect = mismatched
        with self.assertRaisesRegex(RuntimeError, 'direct-table returned missing or mismatched'):
            self.run_details()
        self.assert_archived(old)

    def test_direct_run_cannot_reuse_stale_layout_as_a_success(self):
        self.save(self.raw(empty=True))
        self.process.return_value = SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(RuntimeError, 'direct-table returned missing or mismatched'):
            self.run_details()

    def test_merchant_and_date_direct_fallback_keep_text_task(self):
        for field in ('merchant', 'date'):
            with self.subTest(field=field):
                self.process.reset_mock()
                self.image = self.cache/'detail'/field/'images/receipt.png'
                paddle = {'input_sha256': detail.sha(self.source), 'image_size': [220, 600], 'lines': []}
                self.meta = prepare_detail(self.source, paddle, field, self.image)
                self.request = {'id': 'receipt', 'field': field, 'path': str(self.image), 'sha256': detail.sha(self.image)}
                self.target = self.cache/'detail'/field/'oxr/receipt.json'
                self.target.parent.mkdir(parents=True, exist_ok=True)
                self.save(self.raw(empty=True))
                def successful(command, **kwargs):
                    self.assertEqual(command[command.index('--task')+1], 'text')
                    self.save(self.raw(direct=True))
                    return SimpleNamespace(returncode=0)
                self.process.side_effect = successful
                self.assertEqual(self.run_details()['status'], 'complete')
                self.process.assert_called_once()
                result = json.loads(self.target.read_text())
                self.assertEqual(result['recognition_variant'], 'direct_text')
                self.assertEqual(result['field'], field)


if __name__ == '__main__':
    unittest.main()
