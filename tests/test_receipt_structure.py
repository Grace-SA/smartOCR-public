import unittest
from receipt_extraction_v2 import collect_candidates, reconcile


class ReceiptStructureTests(unittest.TestCase):
    def extract(self, text):
        return reconcile([collect_candidates(text, name) for name in ('paddle', 'unlimited', 'oxr')])

    def test_combined_document_title_does_not_hide_selling_business(self):
        for title in ('TAX INVOICE / RECEIPT', 'TAX INVOICE & RECEIPT', '* TAX INVOICE *'):
            r=self.extract(title+'\nMaple by River\n28 Example St\nSydney NSW 2000\nTOTAL $21.00')
            self.assertEqual(r['merchant'],'Maple by River')

    def test_tax_component_is_not_the_tax_inclusive_total(self):
        text='TOTAL: $220.00\nTotal includes Tax of $20.00\nEFT $220.00'
        self.assertEqual(self.extract(text)['total'],220)
        self.assertIsNone(self.extract('Total includes Tax of $20.00')['total'])
        for label in ('Total Inc Tax', 'Total incl. tax', 'Total including GST'):
            self.assertEqual(self.extract(label+' $220.00')['total'],220)
        self.assertIsNone(self.extract('Total ex tax $200.00')['total'])

    def test_terminal_sale_currency_and_amount_have_a_payment_role(self):
        context='MERCHANT ID: 1234\nACCOUNT TYPE CREDIT\nAPPROVED\n'
        for body in ('SALE AUD $62.40', 'SALE AUD\n$62.40', '$62.40\nAUD\nSALE'):
            self.assertEqual(self.extract(context+body)['total'],62.4)
            self.assertIsNone(self.extract(body)['total'])
        self.assertIsNone(self.extract(context+'GST\n$2.00\nAUD\nSALE')['total'])
        self.assertIsNone(self.extract(context+'SALE AUD\nCASH OUT\n$62.40')['total'])
        self.assertIsNone(self.extract(context+'SALE AUD $12.00\nSALE AUD $19.00')['total'])

    def test_invoice_identity_can_follow_terminal_metadata(self):
        text='EXAMPLE BANK EFTPOS\n'+'\n'.join(['MID 1234','APPROVED','CUSTOMER COPY']*8)
        text+='\nMAPLE INDUSTRIAL SUPPLIES\nPTY LTD\nTax Invoice\nDate 10/05/2023\nTOTAL $220.00'
        self.assertEqual(self.extract(text)['merchant'],'MAPLE INDUSTRIAL SUPPLIES PTY LTD')

    def test_customer_name_and_unanchored_suffix_are_not_supplier_identity(self):
        for text in ('Customer:\nMAPLE INDUSTRIAL SUPPLIES\nPTY LTD\nTax Invoice',
                     'MAPLE INDUSTRIAL SUPPLIES\nPTY LTD\nSome unrelated text'):
            candidates=collect_candidates(text,'paddle')['merchant']
            self.assertFalse(any('printed_legal_name_before_invoice_title' in c['flags'] for c in candidates))

    def test_settled_invoice_balance_and_joined_item_total_are_not_gross(self):
        text='TOTAL INCLUDING GST: $220.00\nTotal amount due on this invoice 0.00'
        self.assertEqual(self.extract(text)['total'],220)
        self.assertIsNone(self.extract('Product Code: EXCLUDECAREItem Total: $0.00')['total'])
        self.assertIsNone(self.extract('Remaining Inv Amount $12.00')['total'])

    def test_accounting_columns_preserve_rowspan_alignment(self):
        text='<table><tr><td rowspan="2">Bank Details</td><td>Total Weight</td><td>Total Ex GST</td><td>GST</td><td>Total Incl GST</td></tr><tr><td>0.00</td><td>200.00</td><td>20.00</td><td>220.00</td></tr></table>\nTotal amount due on this invoice 0.00'
        self.assertEqual(self.extract(text)['total'],220)
        self.assertIsNone(self.extract('<table><tr><td>Description</td><td>Total</td></tr><tr><td>Widget</td><td>220.00</td></tr></table>')['total'])

    def test_corner_address_does_not_compete_with_repeated_supplier_name(self):
        text='Maple Auto Centre\nMaple Auto Centre\nCnr Gladstone & Perry Sts\nPH: 02 5555 5555\nTAX INVOICE\nTOTAL $12.00'
        self.assertEqual(self.extract(text)['merchant'],'Maple Auto Centre')

    def test_table_transaction_date_is_distinct_from_service_and_warranty_dates(self):
        text='<table><tr><td>Customer</td><td>DATE</td><td>TIME IN</td></tr><tr><td>Example</td><td>24/01/2024</td><td>9:00 AM</td></tr></table>\nNext service due: 24/07/2024\nWarranty expiry: 09/12/2027'
        self.assertEqual(self.extract(text)['date'],'2024-01-24')

    def test_supplier_form_does_not_select_recipient(self):
        text='Original\nTAX INVOICE / STATEMENT\nTO Customer Industries Pty Ltd\nABN (of Recipient) 11111111111\nFROM MAPLE & RIVER\nABN (of Supplier) 22222222222\nTOTAL $22.00'
        self.assertEqual(self.extract(text)['merchant'],'MAPLE & RIVER')
        self.assertIsNone(self.extract('Main Outlet\nCustomer: Example\nCustomer Industries Pty Ltd\nABN 11111111111')['merchant'])

    def test_verified_brand_requires_printed_identity_not_competitor_mention(self):
        self.assertEqual(self.extract('SUPERCHEAP\nAUTO\nTAX INVOICE\nTOTAL $12.00')['merchant'],'Supercheap Auto')
        for brand in ('Harvey Norman','Auto One','Supercheap Auto'):
            candidates=collect_candidates('Price match competitor: '+brand+'\nTOTAL $12.00','paddle')['merchant']
            self.assertFalse(any(c['kind']=='merchant_registry' for c in candidates))

    def test_promotional_slogan_is_not_supplier_identity(self):
        text='WHERE GREAT QUALITY COSTS LESS\nPO Box 42 Sydney NSW 2000\nTax Invoice\nTOTAL $20.00'
        self.assertIsNone(self.extract(text)['merchant'])

    def test_payment_credit_is_not_a_negative_document_total(self):
        text='Tax Invoice\nTotal $220.00\nAmount Paid -$220.00\nBalance Due $0.00'
        self.assertEqual(self.extract(text)['total'],220)
        self.assertEqual(self.extract('Total $220.00\nAmount Paid $80.00\nBalance Due $140.00')['total'],220)

    def test_terminal_business_is_distinct_from_retail_header_locality(self):
        text='North Shore\n18 Example Road\nNorth Shore NSW 2000\nTOTAL $22.00\nEXAMPLE BANK EFTPOS\nMAPLE DRIVE NEWSAG\nNORTH SHORE AU\nMID: 12345\nTID: ABC123\nAPPROVED\nSALE AUD $22.00'
        self.assertEqual(self.extract(text)['merchant'],'MAPLE DRIVE NEWSAG')
        without_name=text.replace('MAPLE DRIVE NEWSAG\n','')
        self.assertFalse(any(c['kind']=='merchant_terminal_header' for c in collect_candidates(without_name,'paddle')['merchant']))


if __name__=='__main__':unittest.main()
