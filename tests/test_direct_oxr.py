import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image

from ocr_ensemble import normalized_output
from ocr_view_retry import prepare_readable_focus
from scripts.run_direct_oxr import (MODEL_REVISION, SOURCE_REVISION, input_provenance,
                                   load_upstream_prompt, recognize_image, sha, write_record)


class DirectOxrTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root/'receipt.png'
        Image.new('RGB', (220, 900), (230, 220, 210)).save(self.source)
        self.generate = Mock(return_value=SimpleNamespace(text='STORE\nTOTAL $21.00\n', generation_tokens=19, prompt_tokens=100))
        self.template = Mock(return_value='formatted model prompt')
        self.mx = SimpleNamespace(reset_peak_memory=Mock(), get_peak_memory=Mock(return_value=123456))

    def infer(self, path=None, **kwargs):
        return recognize_image(path or self.source, model=SimpleNamespace(config={}), processor=object(),
                               generate=self.generate, apply_chat_template=self.template, mx=self.mx,
                               prompt='Recognize the content of the image.', **kwargs)

    def make_focus(self):
        paddle = {'input_sha256': sha(self.source), 'image_size': [220, 900], 'lines': []}
        output = self.root/'focus_enlarged/receipt.png'
        meta = prepare_readable_focus(self.source, paddle, output)
        return output, meta

    def test_one_real_call_parameters_and_verbatim_output_compatible_with_normalizer(self):
        source_bytes = self.source.read_bytes()
        result = self.infer()
        self.generate.assert_called_once()
        args, options = self.generate.call_args
        self.assertEqual(args[2], 'formatted model prompt')
        self.assertEqual(options['image'][0].size, (220, 900))
        self.assertEqual(options['image'][0].tobytes(), Image.open(self.source).convert('RGB').tobytes())
        self.assertEqual(options['temperature'], 0.0)
        self.assertEqual(options['top_p'], 1.0)
        self.assertEqual(options['repetition_penalty'], 1.0)
        self.assertEqual(result['raw'], self.generate.return_value.text)
        self.assertEqual(result['blocks'][0]['content'], result['raw'])
        self.assertEqual(result['blocks'][0]['bbox'], [0, 0, 220, 900])
        self.assertEqual(result['geometry_scope'], 'whole_input')
        self.assertEqual(result['tokens'], 19)
        self.assertEqual(result['calls'][0]['tokens'], 19)
        self.assertEqual(len(result['calls']), 1)
        self.assertEqual(result['source_revision'], SOURCE_REVISION)
        self.assertEqual(result['model_revision'], MODEL_REVISION)
        self.assertEqual(result['input_sha256'], sha(self.source))
        self.assertEqual(result['source_input_sha256'], result['input_sha256'])
        self.assertEqual(result['variant'], 'full')
        self.assertFalse(result['independent_model_vote'])
        self.assertTrue(result['layout_bypassed'])
        self.assertEqual(normalized_output('oxr', result)['text'], result['raw'])
        self.assertEqual(self.source.read_bytes(), source_bytes)

    def test_readable_focus_keeps_original_source_hash_and_view_metadata(self):
        output, meta = self.make_focus()
        result = self.infer(output)
        self.assertEqual(result['variant'], 'focus')
        self.assertEqual(result['preprocessing_variant'], 'readable_focus')
        self.assertEqual(result['recognition_variant'], 'direct_text')
        self.assertEqual(result['engine'], 'SoMark-OXR-1.0-MLX-BF16')
        self.assertEqual(result['focus'], meta)
        self.assertEqual(result['input_sha256'], sha(output))
        self.assertEqual(result['source_input_sha256'], sha(self.source))
        self.assertEqual(result['image_size'], meta['image_size'])

    def test_stale_source_or_view_rejected_before_generation(self):
        output, _ = self.make_focus()
        Image.new('RGB', (220, 900), 'black').save(self.source)
        with self.assertRaisesRegex(ValueError, 'source image'):
            self.infer(output)
        self.generate.assert_not_called()
        output, _ = self.make_focus()
        Image.new('RGB', (220, 900), 'black').save(output)
        with self.assertRaisesRegex(ValueError, 'hash'):
            self.infer(output)
        self.generate.assert_not_called()

    def test_actual_token_cap_and_empty_response_stay_visible(self):
        self.generate.return_value = SimpleNamespace(text='', generation_tokens=64)
        result = self.infer(max_tokens=64)
        self.assertEqual(result['blocks'], [])
        self.assertEqual(result['raw'], '')
        self.assertTrue(result['capped'])
        self.assertTrue(result['calls'][0]['capped'])
        self.assertEqual(result['calls'][0]['finish_reason'], 'length')
        self.assertEqual(result['tokens'], 64)
        self.assertEqual(len(result['calls']), 1)

    def test_table_html_is_not_rewritten_or_converted_into_invented_rows(self):
        html = '<table>\n<tr><td>Total</td><td>21.00</td></tr>\n</table>'
        self.generate.return_value = SimpleNamespace(text=html, generation_tokens=27)
        result = self.infer(task='table')
        self.assertEqual(result['blocks'], [{'label': 'table', 'content': html,
                                            'bbox': [0, 0, 220, 900], 'page': 1,
                                            'geometry_scope': 'whole_input'}])
        self.assertEqual(result['raw'], html)

    def test_prompts_read_exactly_without_executing_upstream_module(self):
        prompt_file = self.root/'upstream/oxr/model/prompts.py'
        prompt_file.parent.mkdir(parents=True)
        prompt_file.write_text('raise RuntimeError("must not execute")\n'
                               'PROMPT_TEXT_RECOGNITION = "Recognize the content of the image."\n'
                               'PROMPT_TABLE_RECOGNITION = "Recognize the table of the image into html format."\n'
                               'PROMPT_WHOLE_PAGE_RECOGNITION = "Recognize the whole page content of the image."\n')
        source = self.root/'upstream'
        self.assertEqual(load_upstream_prompt(source, 'text'), 'Recognize the content of the image.')
        self.assertEqual(load_upstream_prompt(source, 'table'), 'Recognize the table of the image into html format.')
        self.assertEqual(load_upstream_prompt(source, 'whole_page'), 'Recognize the whole page content of the image.')

    def test_output_replacement_archives_exact_old_bytes(self):
        target = self.root/'out/receipt.json'
        target.parent.mkdir()
        original = b'{"engine":"old OXR","blocks":[],"capped":false}\n'
        target.write_bytes(original)
        record = self.infer()
        write_record(target, record)
        digest = hashlib.sha256(original).hexdigest()
        self.assertEqual((target.parent/'attempts/receipt'/f'{digest}.json').read_bytes(), original)
        self.assertEqual(json.loads(target.read_text()), record)

    def test_missing_generation_accounting_cannot_claim_a_success(self):
        self.generate.return_value = SimpleNamespace(text='TEXT', generation_tokens=None)
        with self.assertRaisesRegex(ValueError, 'generation-token accounting'):
            self.infer()


if __name__ == '__main__':
    unittest.main()
