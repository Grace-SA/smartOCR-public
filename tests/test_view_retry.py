import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from ocr_view_retry import prepare_readable_focus


class ReadableFocusTests(unittest.TestCase):
    def fixture(self, directory, size=(220, 1000)):
        path = Path(directory) / 'source.png'
        Image.new('RGB', size, (220, 210, 180)).save(path)
        def line(text, y):
            return {'text': text, 'polygon': [[20, y], [195, y], [195, y+12], [20, y+12]]}
        rows = [('STORE', 15), ('ADDRESS', 40), ('CITY', 65), ('ABN', 90),
                ('TAX INVOICE', 115), ('DATE 23/01/2024', 140), ('ITEM', 400),
                ('TOTAL $42.00', 800), ('GST $3.00', 824), ('EFT $42.00', 848)]
        return path, {'image_size': list(size), 'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                      'lines': [line(text, y) for text, y in rows]}

    def test_geometry_hashes_padding_and_source_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            source, record = self.fixture(directory)
            original = source.read_bytes()
            target = Path(directory) / 'focus_enlarged/retry.png'
            result = prepare_readable_focus(source, record, target)
            self.assertEqual(result['source_sha256'], hashlib.sha256(original).hexdigest())
            self.assertEqual(result['output_sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(json.loads(target.with_suffix('.focus.json').read_text()), result)
            self.assertEqual(result['scale'], 3)
            self.assertGreaterEqual(len(result['regions']), 2)
            with Image.open(target) as output:
                self.assertEqual(list(output.size), result['image_size'])
                self.assertEqual(result['image_size'], [v*3+64 for v in result['base_focus_size']])
                self.assertEqual(output.getpixel((0, 0)), (255, 255, 255))
                self.assertEqual(output.getpixel((output.width-1, output.height-1)), (255, 255, 255))
                for region in result['regions']:
                    self.assertEqual(region['focus_bbox'], [v*3+32 for v in region['base_focus_bbox']])
                    sx0, sy0, sx1, sy1 = region['source_bbox']
                    fx0, fy0, fx1, fy1 = region['focus_bbox']
                    self.assertEqual(fx1-fx0, (sx1-sx0)*3)
                    self.assertEqual(fy1-fy0, (sy1-sy0)*3)
                    affine = region['source_to_focus_affine']
                    inverse = region['focus_to_source_affine']
                    for sx, sy, fx, fy in [(sx0, sy0, fx0, fy0), (sx1, sy1, fx1, fy1)]:
                        self.assertEqual(sx*affine[0]+affine[2], fx)
                        self.assertEqual(sy*affine[4]+affine[5], fy)
                        self.assertAlmostEqual(fx*inverse[0]+inverse[2], sx)
                        self.assertAlmostEqual(fy*inverse[4]+inverse[5], sy)
            self.assertTrue(result['derived_view'])
            self.assertFalse(result['independent_sample'])

    def test_large_sparse_image_uses_twice_scale_and_full_image(self):
        with tempfile.TemporaryDirectory() as directory:
            source, record = self.fixture(directory, (350, 1200))
            record['lines'] = []
            result = prepare_readable_focus(source, record, Path(directory)/'retry.png')
            self.assertEqual(result['scale'], 2)
            self.assertEqual(result['regions'][0]['source_bbox'], [0, 0, 350, 1200])
            self.assertEqual(result['regions'][0]['focus_bbox'], [32, 32, 732, 2432])

    def test_invalid_paddle_evidence_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source, record = self.fixture(directory)
            target = Path(directory)/'retry.png'
            record['input_sha256'] = 'wrong'
            with self.assertRaises(ValueError):
                prepare_readable_focus(source, record, target)
            self.assertFalse(target.exists())

    def test_source_and_ordinary_focus_cache_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source, record = self.fixture(directory)
            with self.assertRaises(ValueError):
                prepare_readable_focus(source, record, source)
            protected = Path(directory)/'data/ensemble/focus'
            protected.mkdir(parents=True)
            existing = protected/'source.png'
            existing.write_bytes(b'existing cache')
            with patch('ocr_view_retry._ORIGINAL_FOCUS_DIR', protected):
                with self.assertRaises(ValueError):
                    prepare_readable_focus(source, record, existing)
                alias = Path(directory)/'alias'
                alias.symlink_to(protected, target_is_directory=True)
                with self.assertRaises(ValueError):
                    prepare_readable_focus(source, record, alias/'source.png')
            self.assertEqual(existing.read_bytes(), b'existing cache')


if __name__ == '__main__':
    unittest.main()
