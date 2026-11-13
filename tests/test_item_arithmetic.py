import unittest

from receipt_item_arithmetic import collect_counted_subtotal_check


class CountedSubtotalArithmeticTests(unittest.TestCase):
    def sample(self):
        return ['EXAMPLE RETAILER', 'TAX INVOICE ABN 12 345 678 901',
                'WINE COUPON 1 0.02', 'COASTAL SHIRAZ 750ML',
                'Qty 4 @ $15.25 ea 61.00', 'PROMO OFFER -30.50',
                '5 SUBTOTAL $30.52', 'TOTAL $30.52', 'EFT $30.52']

    def check(self, rows):
        return collect_counted_subtotal_check(rows, 'model-a', 'raw')

    def test_counted_quantity_and_explicit_discount_reconcile_exactly(self):
        rows = self.sample()
        result = self.check(rows)
        self.assertIsNotNone(result)
        self.assertEqual(result['value'], 30.52)
        self.assertEqual(result['item_count'], 5)
        self.assertEqual([i['quantity'] for i in result['items']], [1, 4])
        self.assertEqual(result['items'][1]['unit_price'], 15.25)
        self.assertEqual(result['discounts'][0]['evidence'], 'PROMO OFFER -30.50')
        self.assertEqual(result['subtotal_evidence'], '5 SUBTOTAL $30.52')
        self.assertEqual(result['engine'], 'model-a')
        self.assertEqual(result['source_variant'], 'raw')
        self.assertEqual(result['scope'], 'supports_existing_printed_total_only')
        self.assertNotIn('total', result)
        # The function has no access to a final-total candidate. Removing its
        # text does not invent one; callers must separately require one.
        self.assertEqual(self.check(rows[:-2])['value'], 30.52)

    def test_quantity_explanation_after_priced_item_is_not_added_twice(self):
        rows = ['Example receipt', 'SPARKLING WATER $12.00',
                'Qty 3 @ $4.00 each', 'DISCOUNT -2.00', '3 SUBTOTAL $10.00']
        result = self.check(rows)
        self.assertEqual(result['value'], 10)
        self.assertEqual(result['item_count'], 3)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(len(result['excluded_unit_price_rows']), 1)

    def test_first_quantity_extension_requires_product_description(self):
        rows = ['Invoice', 'APPLE JUICE', 'Qty 2 @ $3.00 ea 6.00', '2 SUBTOTAL $6.00']
        self.assertEqual(self.check(rows)['value'], 6)
        self.assertIsNone(self.check(rows[:1]+rows[2:]))
        rows[1] = 'STORE MANAGER'
        self.assertIsNone(self.check(rows))

    def test_missing_item_quantity_or_discount_never_produces_partial_sum(self):
        for removed in [2, 3, 4, 5]:
            with self.subTest(removed=removed):
                rows = self.sample()
                del rows[removed]
                self.assertIsNone(self.check(rows))
        for replacement in ['Qty 3 @ $15.25 ea 61.00', 'Qty 4 @ $15.20 ea 61.00',
                            'Qty 4 @ $15.25 ea 60.00', 'Qty ? @ $15.25 ea 61.00',
                            'Q1y 4 @ $15.25 ea 61.00']:
            with self.subTest(replacement=replacement):
                rows = self.sample(); rows[4] = replacement
                self.assertIsNone(self.check(rows))

    def test_count_subtotal_and_currency_format_must_be_unambiguous(self):
        for replacement in ['4 SUBTOTAL $30.52', '5 SUBTOTAL $30.53', 'SUBTOTAL $30.52',
                            '5 SUBTOTAL $30.520', '5 SUBTOTAL $30.52 $3.05',
                            '5 SUBTOTAL $30,52', '5 SUBTOTAL $30.5?', '5 SUBTOTAL $30.52-']:
            with self.subTest(replacement=replacement):
                rows = self.sample(); rows[6] = replacement
                self.assertIsNone(self.check(rows))
        self.assertIsNone(self.check(self.sample()+['5 SUBTOTAL $30.52']))
        self.assertIsNone(self.check(self.sample()+['SUBTOTAL $30.52']))

    def test_discounts_require_explicit_label_and_negative_sign(self):
        for replacement in ['PROMO OFFER 30.50', 'PROMO OFFER $30.50',
                            'PROMO OFFER (30.50)', 'PRICE -30.50', 'OFFER -30.50 -0.50',
                            'PROMO OFFER -30.500', '[Unreadable] -30.50']:
            with self.subTest(replacement=replacement):
                rows = self.sample(); rows[5] = replacement
                self.assertIsNone(self.check(rows))
        for label in ['DISCOUNT', 'DISCT', 'PROMOTION', 'OFFER']:
            rows = self.sample(); rows[5] = label+' -$30.50'
            self.assertEqual(self.check(rows)['value'], 30.52)

    def test_unknown_rows_and_loose_amounts_inside_table_are_rejected(self):
        for inserted in ['[Unreadable]', 'Extra product without price', '2 for $8.00',
                         '$0.00', 'GST $0.00', 'APPLE 4 $0.00', 'Amount unknown ?',
                         'Qty 1 @ $0.00 ea 0.00']:
            with self.subTest(inserted=inserted):
                rows = self.sample(); rows.insert(5, inserted)
                self.assertIsNone(self.check(rows))

    def test_extra_charges_cashout_and_subsequent_discounts_reject_check(self):
        for suffix in ['SURCHARGE $0.30', 'ROUNDING -$0.02', 'SERVICE FEE $1.00',
                       'DELIVERY CHARGE $5.00', 'CASH OUT $20.00', 'GST EXTRA $3.05',
                       'DISCOUNT -$2.00', 'TIP $3.00', 'All cards incur a 1% surcharge']:
            with self.subTest(suffix=suffix):
                self.assertIsNone(self.check(self.sample()+[suffix]))
        # A summary of savings is not a second discount applied after subtotal.
        self.assertEqual(self.check(self.sample()+['TOTAL SAVINGS $30.50'])['value'], 30.52)

    def test_every_penny_is_calculated_as_decimal(self):
        rows = ['SMALL ITEM $0.10', 'SECOND ITEM $0.20', 'DISCOUNT -$0.01',
                '2 SUBTOTAL $0.29']
        self.assertEqual(self.check(rows)['value'], .29)

    def test_no_currency_or_reference_inputs_are_inferred(self):
        for rows in [[], ['TOTAL $30.52'], ['5 SUBTOTAL $30.52'], None,
                     ['X', 2], ['ITEM $1.00\n1 SUBTOTAL $1.00']]:
            with self.subTest(rows=rows):
                self.assertIsNone(self.check(rows))


if __name__ == '__main__':
    unittest.main()
