import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import ocr_ensemble as ensemble
from focused_ocr import prepare_focus
from ocr_view_retry import prepare_readable_focus


class OxrFocusRetryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.cache = self.root/'data/ensemble'
        for name in ('oriented', 'paddle', 'oxr_focus'):
            (self.cache/name).mkdir(parents=True)
        self.addCleanup(patch.stopall)
        patch.object(ensemble, 'ROOT', self.root).start()
        patch.object(ensemble, 'CACHE', self.cache).start()
        self.subprocess = patch.object(ensemble.subprocess, 'run').start()

    def fixture(self, rid='test_receipt'):
        source = self.cache/'oriented'/f'{rid}.png'
        Image.new('RGB', (220, 1000), (210, 200, 180)).save(source)
        rows = [('STORE', 20), ('ADDRESS', 50), ('CITY', 80), ('ABN', 110),
                ('DATE 01/02/2024', 140), ('ITEM', 400), ('TOTAL $21.00', 800), ('EFT $21.00', 830)]
        paddle = {'input_sha256': ensemble.sha(source), 'image_size': [220, 1000],
                  'lines': [{'text': text, 'polygon': [[15,y],[205,y],[205,y+12],[15,y+12]]} for text,y in rows]}
        (self.cache/'paddle'/f'{rid}.json').write_text(json.dumps(paddle))
        meta = prepare_focus(source, paddle, self.cache/'focus'/f'{rid}.png')
        return {'id': rid, 'prepared_path': str(source.relative_to(self.root))}, source, paddle, meta

    def raw(self, image, *, empty=False, capped=False):
        with Image.open(image) as source:
            size = list(source.size)
        return {'engine': 'TEST-ONLY-OXR', 'input_sha256': ensemble.sha(image),
                'image_size': size, 'coordinate_space': 'pixels', 'capped': capped,
                'blocks': [{'label': 'image' if empty else 'text',
                            'content': 'photo asset' if empty else 'STORE\n01/02/2024\nTOTAL $21.00',
                            'bbox': [0, 0, *size]}]}

    def cache_raw(self, rid, raw):
        path = self.cache/'oxr_focus'/f'{rid}.json'
        path.write_text(json.dumps(raw))
        return path

    def runner(self, command, **kwargs):
        out_index = command.index('--out') + 1
        out = Path(command[out_index])
        images = command[command.index('--images')+1:] if '--images' in command else command[out_index+1:]
        for image in map(Path, images):
            raw = self.raw(image)
            if Path(command[1]).name == 'run_direct_oxr.py':
                raw.update(recognition_variant='direct_text', layout_bypassed=True, calls=[{'tokens': 20, 'capped': False}])
            (out/f'{image.stem}.json').write_text(json.dumps(raw))
        return SimpleNamespace(returncode=0)

    def assert_archived(self, rid, original):
        digest = hashlib.sha256(original).hexdigest()
        self.assertEqual((self.cache/'oxr_focus_attempts'/rid/f'{digest}.json').read_bytes(), original)

    def test_valid_raw_cache_gets_missing_metadata_without_model_run(self):
        item, source, _, meta = self.fixture()
        raw = self.raw(Path(meta['output_path']))
        target = self.cache_raw(item['id'], raw)
        original = target.read_bytes()
        result = ensemble.run_focused_oxr([item])
        self.subprocess.assert_not_called()
        self.assertEqual(result['processed'], 0)
        cached = json.loads(target.read_text())
        self.assertEqual(cached['blocks'], raw['blocks'])
        self.assertEqual(cached['source_input_sha256'], ensemble.sha(source))
        self.assertEqual(cached['focus'], meta)
        self.assertEqual(cached['variant'], 'focus')
        self.assertEqual(cached['engine'], 'TEST-ONLY-OXR')
        self.assert_archived(item['id'], original)

    def test_empty_or_capped_cache_uses_readable_retry_preserving_old_evidence(self):
        for empty, capped in ((True, False), (False, True)):
            with self.subTest(empty=empty, capped=capped):
                self.subprocess.reset_mock()
                rid = 'empty' if empty else 'capped'
                item, source, _, meta = self.fixture(rid)
                source_bytes = source.read_bytes()
                focus = Path(meta['output_path']); focus_bytes = focus.read_bytes()
                target = self.cache_raw(rid, self.raw(focus, empty=empty, capped=capped))
                original = target.read_bytes()
                self.subprocess.side_effect = self.runner
                result = ensemble.run_focused_oxr([item])
                self.assertEqual(result['focus_processed'], 0)
                self.assertEqual(result['readable_processed'], 1)
                self.assertEqual(result['retry_exhausted'], 0)
                self.subprocess.assert_called_once()
                cached = json.loads(target.read_text())
                self.assertEqual(cached['variant'], 'focus')
                self.assertEqual(cached['preprocessing_variant'], 'readable_focus')
                self.assertEqual(cached['source_input_sha256'], ensemble.sha(source))
                self.assertEqual(cached['input_sha256'], cached['focus']['output_sha256'])
                self.assertEqual(cached['input_sha256'], ensemble.sha(cached['focus']['output_path']))
                self.assertEqual(cached['image_size'], cached['focus']['image_size'])
                self.assertEqual(Path(cached['focus']['output_path']).parent, self.cache/'focus_enlarged')
                self.assert_archived(rid, original)
                self.assertEqual(source.read_bytes(), source_bytes)
                self.assertEqual(focus.read_bytes(), focus_bytes)
                self.subprocess.reset_mock()
                self.assertEqual(ensemble.run_focused_oxr([item])['processed'], 0)
                self.subprocess.assert_not_called()

    def test_fresh_empty_first_attempt_runs_second_stage_once(self):
        item, _, _, _ = self.fixture()
        def runner(command, **kwargs):
            image = Path(command[-1])
            raw = self.raw(image, empty=image.parent.name=='focus')
            self.cache_raw(image.stem, raw)
            return SimpleNamespace(returncode=0)
        self.subprocess.side_effect = runner
        result = ensemble.run_focused_oxr([item])
        self.assertEqual(self.subprocess.call_count, 2)
        self.assertEqual((result['focus_processed'], result['readable_processed']), (1, 1))
        self.assertEqual(result['retry_exhausted'], 0)

    def test_raw_readable_cache_recovers_metadata_without_duplicate_model_vote(self):
        item, source, paddle, _ = self.fixture()
        meta = prepare_readable_focus(source, paddle, self.cache/'focus_enlarged'/f"{item['id']}.png")
        target = self.cache_raw(item['id'], self.raw(Path(meta['output_path'])))
        result = ensemble.run_focused_oxr([item])
        self.subprocess.assert_not_called()
        self.assertEqual(result['processed'], 0)
        cached = json.loads(target.read_text())
        self.assertEqual(cached['focus'], meta)
        self.assertEqual(cached['variant'], 'focus')
        self.assertEqual(cached['preprocessing_variant'], 'readable_focus')
        self.assertEqual(cached['engine'], 'TEST-ONLY-OXR')

    def test_matching_failed_second_level_cache_runs_direct_once(self):
        item, source, paddle, _ = self.fixture()
        meta = prepare_readable_focus(source, paddle, self.cache/'focus_enlarged'/f"{item['id']}.png")
        self.cache_raw(item['id'], self.raw(Path(meta['output_path']), empty=True, capped=True))
        self.subprocess.side_effect = self.runner
        result = ensemble.run_focused_oxr([item])
        self.subprocess.assert_called_once()
        command = self.subprocess.call_args.args[0]
        self.assertEqual(Path(command[1]).name, 'run_direct_oxr.py')
        self.assertEqual(command[command.index('--task')+1], 'text')
        self.assertEqual(command[command.index('--repetition-penalty')+1], '1.05')
        self.assertEqual(result['direct_processed'], 1)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['retry_exhausted'], 0)
        self.subprocess.reset_mock()
        self.assertEqual(ensemble.run_focused_oxr([item])['processed'], 0)
        self.subprocess.assert_not_called()

    def test_three_stage_limit_preserves_failed_direct_cache_and_all_attempts(self):
        item, source, _, _ = self.fixture()
        original_source = source.read_bytes()
        produced = []
        def empty(command, **kwargs):
            image = Path(command[-1])
            raw = self.raw(image, empty=True, capped=True)
            if Path(command[1]).name == 'run_direct_oxr.py':
                raw.update(recognition_variant='direct_text', layout_bypassed=True, calls=[{'tokens': 4096, 'capped': True}])
            path = self.cache_raw(image.stem, raw)
            produced.append(path.read_bytes())
            return SimpleNamespace(returncode=0)
        self.subprocess.side_effect = empty
        result = ensemble.run_focused_oxr([item])
        self.assertEqual(self.subprocess.call_count, 3)
        self.assertEqual((result['focus_processed'], result['readable_processed'], result['direct_processed']), (1, 1, 1))
        self.assertEqual(result['processed'], 3)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['retry_exhausted'], 1)
        self.assertEqual(source.read_bytes(), original_source)
        for previous in produced:
            self.assert_archived(item['id'], previous)
        cached = json.loads((self.cache/'oxr_focus'/f"{item['id']}.json").read_text())
        self.assertEqual(cached['variant'], 'focus')
        self.assertEqual(cached['engine'], 'TEST-ONLY-OXR')
        self.assertEqual(cached['recognition_variant'], 'direct_text')
        self.assertEqual(cached['input_sha256'], cached['focus']['output_sha256'])
        self.assertEqual(cached['source_input_sha256'], ensemble.sha(source))
        self.subprocess.reset_mock()
        again = ensemble.run_focused_oxr([item])
        self.subprocess.assert_not_called()
        self.assertEqual(again['processed'], 0)
        self.assertEqual(again['status'], 'incomplete')

    def test_direct_output_with_wrong_hash_is_rejected(self):
        item, source, paddle, _ = self.fixture()
        meta = prepare_readable_focus(source, paddle, self.cache/'focus_enlarged'/f"{item['id']}.png")
        self.cache_raw(item['id'], self.raw(Path(meta['output_path']), empty=True))
        def mismatched(command, **kwargs):
            raw = self.raw(Path(command[-1]))
            raw.update(input_sha256='wrong-image', recognition_variant='direct_text', layout_bypassed=True, calls=[{'tokens': 20}])
            self.cache_raw(item['id'], raw)
            return SimpleNamespace(returncode=0)
        self.subprocess.side_effect = mismatched
        with self.assertRaisesRegex(RuntimeError, 'direct-text returned missing or mismatched'):
            ensemble.run_focused_oxr([item])

    def test_direct_process_cannot_succeed_using_old_layout_output(self):
        item, source, paddle, _ = self.fixture()
        meta = prepare_readable_focus(source, paddle, self.cache/'focus_enlarged'/f"{item['id']}.png")
        self.cache_raw(item['id'], self.raw(Path(meta['output_path']), empty=True))
        self.subprocess.return_value = SimpleNamespace(returncode=0)
        with self.assertRaisesRegex(RuntimeError, 'direct-text returned missing or mismatched'):
            ensemble.run_focused_oxr([item])

    def test_partial_batch_failure_keeps_completed_provenance(self):
        first, _, _, _ = self.fixture('first')
        second, _, _, _ = self.fixture('second')
        def partial(command, **kwargs):
            image = Path(command[-2])
            self.cache_raw(image.stem, self.raw(image))
            return SimpleNamespace(returncode=1)
        self.subprocess.side_effect = partial
        with self.assertRaisesRegex(RuntimeError, 'focus retry failed'):
            ensemble.run_focused_oxr([first, second])
        saved = json.loads((self.cache/'oxr_focus/first.json').read_text())
        self.assertEqual(saved['variant'], 'focus')
        self.assertEqual(saved['input_sha256'], saved['focus']['output_sha256'])
        self.assertEqual(saved['source_input_sha256'], saved['focus']['source_sha256'])
        self.assertFalse((self.cache/'oxr_focus/second.json').exists())


if __name__ == '__main__':
    unittest.main()
