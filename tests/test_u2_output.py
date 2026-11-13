import unittest
from u2_output import parse_output,has_text


class U2OutputTests(unittest.TestCase):
    def test_bad_box_does_not_discard_other_text_or_invent_coordinates(self):
        raw='<PAGE><BLOCK>title[2, 2, 400, 90]<FORK>TEST SHOP<BLOCK>text[800, 200, 200, 300]<FORK>TOTAL $12.50'
        blocks,warnings=parse_output(raw)
        self.assertTrue(warnings)
        self.assertEqual(blocks[0]['content'],'TEST SHOP')
        self.assertEqual(blocks[1]['content'],'TOTAL $12.50')
        self.assertIsNone(blocks[1]['bbox'])
        self.assertEqual(blocks[1]['invalid_bbox'],[800,200,200,300])
        self.assertTrue(has_text({'blocks':blocks}))

    def test_image_only_output_never_counts_as_text(self):
        for raw in ['<PAGE><BLOCK>image[0, 0, 999, 999]<FORK>','<PAGE><BLOCK>image[0, 0, 999, 999]']:
            blocks,_=parse_output(raw)
            self.assertFalse(has_text({'blocks':blocks}))


if __name__=='__main__':unittest.main()
