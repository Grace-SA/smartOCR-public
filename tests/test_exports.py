import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from copy import deepcopy
from unittest.mock import patch
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exports import create_export, _totals


FIXTURES = [
    {"id": "TEST-ONLY-001", "merchant": "测试商家 Coles", "date": "2026-01-03", "total": 12.34, "currency": "AUD", "category": "食品杂货", "purpose": "unknown", "status": "review", "tags": ["测试数据"], "notes": "导出测试，不是真实票据", "field_evidence":{"category":{"method":"ai_suggestion","text":"测试分类说明"}}, "source": {"page_url": "https://example.com/test-only/one", "license": "Synthetic test fixture"}},
    {"id": "TEST-ONLY-002", "merchant": "=HYPERLINK(\"https://example.com\")", "date": None, "total": None, "currency": "AUD", "category": "待分类", "purpose": "work", "status": "review", "tags": ["测试数据"], "source": {}},
    {"id": "TEST-ONLY-003", "merchant": "Refund test", "date": "2026-01-04", "total": -2.34, "currency": "AUD", "category": "食品杂货", "purpose": "personal", "status": "confirmed", "field_evidence":{"category":{"method":"merchant_rule","text":"根据有票面依据的商家类型建议；混合购买可手动调整"}}, "source": {}},
    {"id": "TEST-ONLY-004", "merchant": "Foreign currency test", "date": "2026-01-05", "total": 100, "currency": "USD", "category": "其他", "purpose": "unknown", "status": "review", "source": {}},
    {"id": "TEST-ONLY-005", "merchant": "Zero test", "date": "2026-01-06", "total": 0, "currency": "AUD", "category": "其他", "purpose": "unknown", "status": "auto_confirmed", "confidence":{"score":98,"reasons":[]}, "source": {}},
]


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="receipt-export-test-")
        self.directory = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_totals_do_not_mix_currency_or_missing_with_zero(self):
        totals = _totals(FIXTURES)
        self.assertEqual(str(totals["AUD"]), "10.00")
        self.assertEqual(str(totals["USD"]), "100.0")

    def test_csv_subset_and_formula_injection(self):
        path = create_export(FIXTURES[1:3], "csv", self.directory / "subset.csv")
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.reader(file))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][0], "TEST-ONLY-002")
        self.assertTrue(rows[1][1].startswith("'="))
        self.assertEqual(rows[1][3], "")
        self.assertEqual(rows[2][3], "-2.34")
        self.assertEqual(rows[2][14], "Suggestion based on the merchant shown on the receipt; mixed purchases can be recategorised.")

    def test_default_exports_are_scoped_statistics_without_original_images(self):
        from pypdf import PdfReader
        rows=FIXTURES[2:]
        data=json.loads(create_export(rows,'json',self.directory/'statistics.json').read_text())
        self.assertEqual(data['summary']['count'],3)
        self.assertEqual([r['id'] for r in data['receipts']],[r['id'] for r in rows])
        self.assertNotIn('source',data['receipts'][0])
        pdf=PdfReader(create_export(rows,'pdf',self.directory/'statistics.pdf'))
        self.assertFalse(any(len(page.images) for page in pdf.pages))
        self.assertIn('By category',' '.join(page.extract_text() for page in pdf.pages))

    def test_json_is_lossless_and_subset_only(self):
        path = create_export(FIXTURES[:1], "json", self.directory / "subset.json", include_evidence=True)
        self.assertEqual(json.loads(path.read_text()), FIXTURES[:1])

    def test_unknown_system_placeholder_is_english_without_changing_raw_record(self):
        from openpyxl import load_workbook
        from pypdf import PdfReader
        record = {**FIXTURES[4], 'merchant': '待识别商家'}
        original = deepcopy(record)
        csv_path = create_export([record], 'csv', self.directory / 'unknown.csv')
        with csv_path.open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(list(csv.reader(stream))[1][1], 'Unknown merchant')
        workbook = load_workbook(create_export([record], 'xlsx', self.directory / 'unknown.xlsx'))
        self.assertEqual(workbook['Receipts']['B2'].value, 'Unknown merchant')
        pdf = PdfReader(create_export([record], 'pdf', self.directory / 'unknown.pdf'))
        text = '\n'.join(page.extract_text() for page in pdf.pages)
        self.assertIn('Unknown merchant', text)
        self.assertNotIn('待识别商家', text)
        raw = create_export([record], 'json', self.directory / 'unknown.json', include_evidence=True)
        self.assertEqual(json.loads(raw.read_text()), [original])
        self.assertEqual(record, original)

    def test_pdf_english_labels_preserve_unicode_source_evidence(self):
        from pypdf import PdfReader
        path = create_export(FIXTURES[:2], "pdf", self.directory / "subset.pdf", include_originals=True)
        text = "\n".join(page.extract_text() for page in PdfReader(path).pages)
        self.assertIn("TEST-ONLY-001", text)
        self.assertIn("TEST-ONLY-002", text)
        self.assertNotIn("TEST-ONLY-003", text)
        self.assertIn("Receipt export", text)
        self.assertIn("12.34", text)
        self.assertIn("AI suggestion", text)
        self.assertIn("测试分类说明", text)

    def test_pdf_attaches_only_selected_local_images_at_original_resolution(self):
        from PIL import Image
        from pypdf import PdfReader
        folder=self.directory/'data';folder.mkdir()
        image=folder/'receipt.png'
        Image.new('RGB',(240,900),(20,140,80)).save(image)
        outside=self.directory/'outside.png'
        Image.new('RGB',(50,50),(230,30,30)).save(outside)
        records=deepcopy(FIXTURES[:2])
        records[0]['source']['local_path']='data/receipt.png'
        records[1]['source']['local_path']='outside.png'
        with patch('exports.ROOT',self.directory.resolve()):
            output=create_export(records,'pdf',self.directory/'with-originals.pdf',include_originals=True)
        pages=PdfReader(output).pages
        original,unavailable=pages[-2:]
        self.assertIn('Original receipt 1 of 2',original.extract_text())
        self.assertIn('TEST-ONLY-001',original.extract_text())
        self.assertEqual(len(original.images),1)
        self.assertEqual(original.images[0].image.size,(240,900))
        self.assertIn('TEST-ONLY-002',unavailable.extract_text())
        self.assertIn('Original image is not available',unavailable.extract_text())
        self.assertEqual(len(unavailable.images),0)
        self.assertNotIn('TEST-ONLY-003','\n'.join(p.extract_text() for p in pages))

    def test_workbook_typed_values_formulas_and_missing_amount(self):
        from openpyxl import load_workbook
        path = create_export(FIXTURES, "xlsx", self.directory / "all.xlsx")
        formula_book = load_workbook(path, data_only=False)
        data_book = load_workbook(path, data_only=True)
        self.assertEqual(formula_book.sheetnames, ["Overview", "Receipts"])
        source = data_book["Receipts"]
        self.assertEqual(source.max_row, len(FIXTURES) + 1)
        self.assertEqual(source["F2"].value, 12.34)
        self.assertIsNone(source["F3"].value)
        self.assertEqual(source["F6"].value, 0)
        self.assertEqual(source["C2"].value.year, 2026)
        self.assertEqual(source["O2"].value, "AI suggestion")
        self.assertEqual(source["P2"].value, "测试分类说明")
        self.assertEqual(source["P4"].value, "Suggestion based on the merchant shown on the receipt; mixed purchases can be recategorised.")
        self.assertEqual(formula_book["Receipts"].tables["ReceiptRecords"].ref, "A1:S6")
        self.assertEqual(source["D2"].value, "Groceries & food")
        self.assertEqual(source["H6"].value, "Auto-confirmed")
        self.assertEqual(source["R6"].value, 98)
        self.assertEqual(source["R1"].value, "Confidence index")
        self.assertEqual(formula_book["Receipts"]["B3"].data_type, "s")
        self.assertEqual(formula_book["Overview"]["C4"].data_type, "f")
        self.assertEqual(data_book["Overview"]["C4"].value, 5)
        self.assertEqual(data_book["Overview"]["C5"].value, 1)
        self.assertEqual(data_book["Overview"]["C6"].value, 3)
        self.assertEqual(data_book["Overview"]["F4"].value, 1)
        self.assertEqual(data_book["Overview"]["F5"].value, 1)
        self.assertEqual(data_book["Overview"]["F6"].value, 2)
        self.assertEqual(data_book["Overview"]["C10"].value, 10)
        self.assertEqual(data_book["Overview"]["C11"].value, 100)

    def test_empty_exports(self):
        for fmt in ["csv", "json", "pdf", "xlsx"]:
            path = create_export([], fmt, self.directory / ("empty." + fmt))
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)

    def test_workbook_all_missing_is_not_zero(self):
        from openpyxl import load_workbook
        path = create_export([FIXTURES[1]], "xlsx", self.directory / "missing.xlsx")
        book = load_workbook(path, data_only=True)
        self.assertEqual(book["Overview"]["C10"].value, "Not recorded")

    def test_csv_exposes_confirmation_and_confidence_without_losing_zero(self):
        path=create_export(FIXTURES[2:], 'csv', self.directory/'statuses.csv')
        with path.open(encoding='utf-8-sig',newline='') as file:rows=list(csv.DictReader(file))
        self.assertEqual(rows[0]['Status'],'Human confirmed')
        self.assertEqual(rows[2]['Status'],'Auto-confirmed')
        self.assertEqual(rows[2]['Amount'],'0.0')
        self.assertEqual(rows[2]['Confidence index'],'98.0')


if __name__ == "__main__":
    unittest.main()
