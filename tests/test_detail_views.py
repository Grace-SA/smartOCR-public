import hashlib
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from receipt_detail_views import prepare_detail


class DetailViewTests(unittest.TestCase):
    def fixture(self,directory):
        image=Path(directory)/'receipt.png'
        Image.new('RGB',(400,1200),'white').save(image)
        def line(text,y,x1=30,x2=370): return {'text':text,'confidence':.99,'polygon':[[x1,y],[x2,y],[x2,y+20],[x1,y+20]]}
        lines=[line('MERCHANT NAME',30),line('STREET',70),line('CITY',110),line('ABN 1234',150),line('Date: 23/01/2024',190),line('ITEM PRICE TOTAL',260),line('Product 12.00',300),line('Product 20.00',450),line('TOTAL 32.00',850),line('GST 2.00',885),line('EFT 32.00',920),line('CHANGE 0.00',955),line('23/01/24 10:10',1100)]
        return image,{'input_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'image_size':[400,1200],'lines':lines}

    def test_financial_view_is_one_rect_and_keeps_total_tax_payment(self):
        with tempfile.TemporaryDirectory() as directory:
            image,record=self.fixture(directory)
            result=prepare_detail(image,record,'total',Path(directory)/'total.png')
            box=result['source_bbox']
            self.assertGreater(box[1],700) # Item-table TOTAL header is not the transaction amount.
            self.assertLessEqual(box[1],850)
            self.assertGreaterEqual(box[3],975)
            self.assertEqual(box[0],0)
            self.assertEqual(box[2],400)
            self.assertFalse(result['independent_sample'])

    def test_date_region_preserves_label_and_maps_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            image,record=self.fixture(directory)
            result=prepare_detail(image,record,'date',Path(directory)/'date.png')
            self.assertLessEqual(result['source_bbox'][1],190)
            self.assertGreaterEqual(result['source_bbox'][3],210)
            x,y=200,200
            a,b,c,d,e,f=result['source_to_output_affine']
            ox,oy=a*x+b*y+c,d*x+e*y+f
            a,b,c,d,e,f=result['output_to_source_affine']
            self.assertAlmostEqual(a*ox+b*oy+c,x)
            self.assertAlmostEqual(d*ox+e*oy+f,y)

    def test_header_keeps_full_width_for_undetected_logo(self):
        with tempfile.TemporaryDirectory() as directory:
            image,record=self.fixture(directory)
            result=prepare_detail(image,record,'merchant',Path(directory)/'merchant.png')
            self.assertEqual(result['source_bbox'][:3],[0,0,400])
            self.assertGreaterEqual(result['source_bbox'][3],210)
            self.assertLess(result['source_bbox'][3],300)

    def test_boundary_expansion_does_not_chain_through_dense_item_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            image,record=self.fixture(directory)
            record['lines']=[{'text':'row text','confidence':.99,'polygon':[[10,y],[390,y],[390,y+24],[10,y+24]]} for y in range(10,1150,20)]
            result=prepare_detail(image,record,'merchant',Path(directory)/'merchant.png')
            self.assertLess(result['source_bbox'][3],350)

    def test_rejects_other_image_geometry_and_unknown_field(self):
        with tempfile.TemporaryDirectory() as directory:
            image,record=self.fixture(directory)
            with self.assertRaises(ValueError): prepare_detail(image,record,'tax',Path(directory)/'out.png')
            record['input_sha256']='wrong'
            with self.assertRaises(ValueError): prepare_detail(image,record,'date',Path(directory)/'out.png')

    def test_absent_date_fallback_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            image,record=self.fixture(directory)
            record['lines']=[r for r in record['lines'] if '23/01' not in r['text']]
            result=prepare_detail(image,record,'date',Path(directory)/'out.png')
            self.assertTrue(result['warnings'])
            self.assertEqual(result['source_bbox'][3],1200)

if __name__=='__main__': unittest.main()
