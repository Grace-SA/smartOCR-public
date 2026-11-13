import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ocr_ensemble


class EngineBudgetTests(unittest.TestCase):
    def test_timeout_is_unavailable_evidence_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); image=root/'oriented.png';image.write_bytes(b'synthetic input')
            with patch.object(ocr_ensemble,'ROOT',root), patch.object(ocr_ensemble,'CACHE',root/'cache'), \
                 patch.dict('os.environ',{'SMARTOCR_RESIDENT':'0'}), \
                 patch.object(ocr_ensemble.subprocess,'run',side_effect=subprocess.TimeoutExpired('ocr',180)) as run:
                with self.assertRaisesRegex(RuntimeError,'exceeded 180s budget'):
                    ocr_ensemble.run_engine('oxr',[{'id':'synthetic','prepared_path':'oriented.png'}])
                self.assertEqual(run.call_args.kwargs['timeout'],180)
                self.assertFalse((root/'cache/oxr/synthetic.json').exists())


if __name__=='__main__':unittest.main()
