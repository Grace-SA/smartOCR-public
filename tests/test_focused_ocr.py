import hashlib
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from focused_ocr import prepare_focus


class FocusTests(unittest.TestCase):
    def fixture(self, directory):
        path=Path(directory)/'source.png'
        image=Image.new('RGB',(200,1000),'white')
        # Every row has distinct pixels so the crop mapping can be checked exactly.
        for y in range(1000):
            for x in range(200): image.putpixel((x,y),(x%256,y%256,(x+y)%256))
        image.save(path)
        def line(text,y): return {'text':text,'confidence':.99,'polygon':[[15,y],[185,y],[185,y+12],[15,y+12]]}
        texts=[('SHOP NAME',25),('ABN 123',48),('STORE STREET',70),('CITY',92),('TAX INVOICE',114),('DATE 23/01/2024',136),('item',400),('item',500),('item',600),('TOTAL $42.00',800),('GST $3.00',824),('VISA $42.00',848),('THANK YOU',900)]
        return path,{'image_size':[200,1000],'input_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'lines':[line(t,y) for t,y in texts]}

    def test_crops_retain_exact_pixels_and_financial_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path,record=self.fixture(directory)
            output=Path(directory)/'focus.png'
            result=prepare_focus(path,record,output)
            self.assertLess(result['retained_pixel_fraction'],.7)
            with Image.open(path) as source, Image.open(output) as focus:
                for region in result['regions']:
                    self.assertEqual(source.crop(region['source_bbox']).tobytes(),focus.crop(region['focus_bbox']).tobytes())
            for y in [25,136,800,824,848]:
                self.assertTrue(any(r['source_bbox'][1]<=y and r['source_bbox'][3]>=y+12 for r in result['regions']))

    def test_wrong_image_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path,record=self.fixture(directory)
            record['input_sha256']='wrong'
            with self.assertRaises(ValueError): prepare_focus(path,record,Path(directory)/'out.png')

    def test_missing_date_keeps_tail_and_no_reference_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path,record=self.fixture(directory)
            record['lines']=[line for line in record['lines'] if not line['text'].startswith('DATE')]
            result=prepare_focus(path,record,Path(directory)/'out.png')
            self.assertEqual(result['regions'][-1]['source_bbox'][3],1000)
            self.assertTrue(any('tail_fallback' in r['reasons'] for r in result['regions']))

    def test_sparse_ocr_preserves_full_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path,record=self.fixture(directory)
            record['lines']=[]
            result=prepare_focus(path,record,Path(directory)/'out.png')
            self.assertEqual(result['regions'][0]['source_bbox'],[0,0,200,1000])

if __name__=='__main__': unittest.main()
