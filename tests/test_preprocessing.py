import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import ocr_ensemble


class PreprocessingTests(unittest.TestCase):
    def test_malformed_exif_keeps_pixels_and_records_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); original=root/'input.png'
            Image.new('RGB',(30,40),(20,80,120)).save(original,exif=b'\x00\x08\x00\x04\x01\x1a\x00\x05')
            with patch.object(ocr_ensemble,'ROOT',root), patch.object(ocr_ensemble,'CACHE',root/'cache'), patch.object(ocr_ensemble.subprocess,'run') as runner:
                ocr_ensemble.prepare_images([{'id':'test','local_path':'input.png'}])
            normalized=root/'cache/normalized/test.png'
            with Image.open(original) as before, Image.open(normalized) as after:
                self.assertEqual(before.convert('RGB').tobytes(),after.tobytes())
                self.assertFalse(after.getexif())
            metadata=json.loads(normalized.with_suffix('.source.json').read_text())
            self.assertTrue(metadata['normalization_warnings'])
            self.assertEqual(metadata['source_sha256'],ocr_ensemble.sha(original))
            self.assertEqual(metadata['normalized_sha256'],ocr_ensemble.sha(normalized))
            runner.assert_called_once()

    def test_corrupted_normalized_cache_is_rebuilt_from_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); original=root/'input.png'
            Image.new('RGB',(20,20),'white').save(original)
            with patch.object(ocr_ensemble,'ROOT',root), patch.object(ocr_ensemble,'CACHE',root/'cache'), patch.object(ocr_ensemble.subprocess,'run'):
                manifest=[{'id':'test','local_path':'input.png'}]
                ocr_ensemble.prepare_images(manifest)
                normalized=root/'cache/normalized/test.png'; expected=normalized.read_bytes()
                Image.new('RGB',(20,20),'black').save(normalized)
                ocr_ensemble.prepare_images(manifest)
                self.assertEqual(normalized.read_bytes(),expected)


if __name__=='__main__': unittest.main()
