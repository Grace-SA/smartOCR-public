import unittest
from receipt_extraction_v2 import collect_candidates, reconcile


class ExtractionV2Tests(unittest.TestCase):
    def result(self,text): return reconcile(collect_candidates(text,'test'))

    def test_priced_brand_products_do_not_replace_merchant_header(self):
        for product in ['BP GIFT CARD 20.00', 'Coles Milk $4.00', 'Woolworths Bag 0.25']:
            text='COAST GARDEN SHOP\n12 Example Street\n'+product+'\nTOTAL 20.00'
            result=reconcile([collect_candidates(text,e) for e in ['paddle','oxr','unlimited']])
            self.assertEqual(result['merchant'],'COAST GARDEN SHOP',product)

    def test_brand_in_street_address_does_not_replace_merchant_header(self):
        text='COAST GARDEN SHOP\n12 Coles Street\nNSW 2000\nTOTAL 20.00'
        result=reconcile([collect_candidates(text,e) for e in ['paddle','oxr','unlimited']])
        self.assertEqual(result['merchant'],'COAST GARDEN SHOP')

    def test_real_brand_header_remains_eligible_with_store_number(self):
        text='BP 1234\n12 Example Street\nTOTAL 20.00'
        self.assertEqual(self.result(text)['merchant'],'BP')

    def test_company_suffix_and_address_locality_are_not_merchant_names(self):
        rows='PTY LTD\n12 Example Street\nTEST BAY\nNSW 2000\nABN 12345678901'
        values=[c['value'] for c in collect_candidates(rows,'paddle')['merchant']]
        self.assertNotIn('PTY LTD',values)
        self.assertNotIn('TEST BAY',values)

    def test_large_top_word_with_business_context_is_a_merchant_candidate(self):
        text='CEDAR\n12 Example Street\nNSW 2000\nABN 12345678901\nTAX INVOICE\nCoffee 4.00\nTOTAL 4.00'
        lines=[{'text':line,'bbox':[10,10+i*30,200,10+i*30+(25 if i==0 else 10)]} for i,line in enumerate(text.splitlines())]
        candidates=collect_candidates(text,'paddle',lines)['merchant']
        cedar=next(c for c in candidates if c['value']=='CEDAR')
        self.assertGreaterEqual(cedar['score'],90)
        self.assertNotIn('generic_or_single_word_header',cedar['flags'])

    def test_date_formats_and_month_before_day(self):
        for text,value in [('August 27, 2020 10:16:10','2020-08-27'),('Mar 92019 3:26PM','2019-03-09'),('Date 09 / 12 / 2025','2025-12-09'),('23.JAN.24','2024-01-23'),('2024-10-09','2024-10-09')]:
            self.assertEqual(self.result(text)['date'],value,text)

    def test_expiry_date_not_transaction_date(self):
        r=self.result('Expiry date: 01/10/2025\nSale date: 01/09/2025')
        self.assertEqual(r['date'],'2025-09-01')
        self.assertEqual(self.result('28 Mar 2025 1:59PM')['date'],'2025-03-28')
        self.assertIsNone(self.result('3.25\n-1.00')['date'])
        self.assertEqual(self.result('DATE 23/01/2019\nBEST BEFORE\n27/01/19')['date'],'2019-01-23')
        self.assertIsNone(self.result('USE BY\n27/01/19')['date'])

    def test_conflicting_transaction_dates_abstain(self):
        r=self.result('Date 01/10/2025\nDate 02/10/2025')
        self.assertIsNone(r['date']); self.assertTrue(r['fields']['date']['disagreement'])

    def test_labeled_transaction_date_beats_unlabeled_duplicate(self):
        text='Date: 25/02/2020 Time 12:30\n5/02/20 12:30\nBEST BEFORE\n28/02/20'
        r=reconcile([collect_candidates(text,e) for e in ['paddle','oxr']])
        self.assertEqual(r['date'],'2020-02-25')
        self.assertTrue(r['fields']['date']['disagreement'])
        conflict='Date: 25/02/2020\nDate: 26/02/2020'
        self.assertIsNone(reconcile([collect_candidates(conflict,e) for e in ['paddle','oxr']])['date'])
        for label in ['Due date','Delivery date','Collection date','Dispatch date']:
            text='25/02/2020 12:30\n'+label+': 28/02/2020'
            self.assertEqual(reconcile([collect_candidates(text,e) for e in ['paddle','oxr']])['date'],'2020-02-25')

    def test_terminal_split_payment_needs_context_and_boundary(self):
        for label in ['PURCHASE','SALE']:
            text='MERCHANT ID 123\nACCOUNT TYPE SAVINGS\n'+label+'\nAPPROVED\nAUD\n$42.00'
            self.assertEqual(self.result(text)['total'],42)
            self.assertIsNone(self.result(label+'\nAUD\n$42.00')['total'])
            self.assertIsNone(self.result('MERCHANT ID 123\nAPPROVED\n'+label+'\nCASH OUT\n$42.00')['total'])
            self.assertIsNone(self.result('MERCHANT ID 123\nAPPROVED\nGST\n$2.00\n'+label)['total'])
            self.assertIsNone(self.result('MERCHANT ID 123\nAPPROVED\nGST\nAUD $2.00\n'+label)['total'])

    def test_cash_receipt_closing_brand_and_terminal_merchant(self):
        text='A friendly slogan\n'+'\n'.join(['Product $1.00']*14)+'\nTOTAL $14.00\nCASH $14.00\nTHANK YOU FOR SHOPPING WITH\n7-ELEVEN 4321B'
        self.assertEqual(self.result(text)['merchant'],'7-Eleven')
        text='EXAMPLE BANK\nCOAST GARDEN SHOP\nRYDE NSW 2112\nMERCH ID 123\nAPPROVED\nSALE\nAUD\n$42.00'
        self.assertEqual(self.result(text)['merchant'],'COAST GARDEN SHOP')

    def test_printed_refund_total_is_not_adjacent_zero_payment(self):
        texts=['*** RETURN RECEIPT ***\nTotal:\nEFT Refund: $0.00','*** RETURN RECEIPT ***\nTotal: -$8.50']
        r=reconcile([collect_candidates(t,e) for t,e in zip(texts,['paddle','oxr'])])
        self.assertEqual(r['total'],-8.5)
        self.assertTrue(r['fields']['total']['disagreement'])
        self.assertIsNone(self.result('COT TNCLUOED IN TOTAL $0.00')['total'])
        self.assertEqual(self.result('*** RETURN RECEIPT ***\nTotal: $0.00')['total'],0)

    def test_bank_settlement_is_separate_from_printed_retail_total(self):
        text='TOTAL $3.75\nEFT $3.75\nTerminal ID T123\nAPPROVED\nPURCHASE $3.70\nTOTAL AUD $3.70'
        r=reconcile([collect_candidates(text,e) for e in ['paddle','unlimited']])
        self.assertEqual(r['total'],3.75)
        support=collect_candidates(text,'paddle')['supporting_amounts']
        self.assertIn(('settlement',3.7),[(c['kind'],c['value']) for c in support])
        self.assertEqual(self.result('Terminal ID T123\nAPPROVED\nPURCHASE $3.70\nTOTAL AUD $3.70')['total'],3.7)
        split='Terminal ID T123\nAPPROVED\nTOTAL AUD $11.55\nCARD PAYMENT $10.00\nCASH $1.55'
        candidates=collect_candidates(split,'paddle')
        self.assertIn(('printed_total',11.55),[(c['kind'],c['value']) for c in candidates['total']])
        self.assertEqual(reconcile([candidates,collect_candidates(split,'oxr')])['total'],11.55)

    def test_unpaid_table_balance_corroborates_existing_total(self):
        texts=['TABLE ACCOUNT 12\nTotal $365.00\nBalance $365.00',
               'TABLE ACCOUNT 12\nTotal 8365.00\nBalance $365.00',
               'TABLE ACCOUNT 12\nTotal 1365.00\nBalance 1365.00']
        r=reconcile([collect_candidates(t,e) for t,e in zip(texts,['unlimited','paddle','oxr'])])
        self.assertEqual(r['total'],365)
        self.assertTrue(r['fields']['total']['disagreement'])
        self.assertEqual(len({c['engine'] for c in r['fields']['total']['invoice_balance_checks']}),2)
        # A balance after a deposit does not establish the original invoice total.
        partial=[collect_candidates(t+'\nDeposit paid $100.00',e) for t,e in zip(texts,['unlimited','paddle','oxr'])]
        self.assertIsNone(reconcile(partial)['total'])
        no_total=[collect_candidates('TABLE ACCOUNT 12\nBalance $365.00',e) for e in ['paddle','oxr']]
        self.assertIsNone(reconcile(no_total)['total'])
        asymmetric=['TABLE ACCOUNT 12\nTotal $100.00\nBalance $40.00\nCARD PAYMENT $60.00',
                    'TABLE ACCOUNT 12\nTotal $100.00\nBalance $40.00',
                    'TABLE ACCOUNT 12\nTotal $40.00\nBalance $40.00']
        result=reconcile([collect_candidates(t,e) for t,e in zip(asymmetric,['paddle','oxr','unlimited'])])
        self.assertNotEqual(result['total'],40)
        self.assertNotIn('invoice_balance_checks',result['fields']['total'])

    def test_money_spacing_and_decimal_comma(self):
        self.assertEqual(self.result('Invoice Total $36. 02')['total'],36.02)
        self.assertEqual(self.result('TOTAL $1,832.55')['total'],1832.55)
        self.assertEqual(self.result('TOTAL 5,85')['total'],5.85)

    def test_accounting_amount_signs_are_preserved(self):
        for amount in ['($12.50)', '(12.50)', '($ 12.50)', '-$12.50',
                       '$-12.50', '$12.50-', '$12.50 CR', 'AUD -$12.50', '-$\u00a012.50']:
            self.assertEqual(self.result('TOTAL '+amount)['total'],-12.50,amount)
        self.assertEqual(self.result('TOTAL $12.50')['total'],12.50)
        for amount in ['($12.50', '$12.50)']:
            self.assertIsNone(self.result('TOTAL '+amount)['total'],amount)

    def test_grouped_amounts_cannot_silently_lose_leading_digits(self):
        from receipt_extraction_v2 import _money
        for separator in [' ', '\u00a0', '\u202f']:
            self.assertEqual(self.result('TOTAL 1'+separator+'234.56')['total'],1234.56)
        for amount in ['12 34.56', '1,23.45', '1,234.567', '1.234,56']:
            self.assertEqual(_money('TOTAL '+amount,permit_noisy=True),[],amount)
            self.assertIsNone(self.result('TOTAL '+amount)['total'],amount)

    def test_separate_money_fields_remain_separate(self):
        from receipt_extraction_v2 import _money
        for text in ['TOTAL $10.00 $20.00', 'TOTAL 10.00 20.00']:
            self.assertEqual([m['value'] for m in _money(text)],[10.0,20.0],text)
            self.assertEqual(self.result(text)['total'],20.0,text)
        text='Total\n(Includes GST:) $0.00 $7.68'
        self.assertEqual(self.result(text)['total'],7.68)
        self.assertEqual([m['value'] for m in _money('GST 1.00 TOTAL 11.00')],[1.0,11.0])
        self.assertEqual([m['value'] for m in _money('TOTAL 10.00 1,23.45')],[10.0])

    def test_adjacent_payment_after_total(self):
        self.assertEqual(self.result('Total\nVISA $84.77\nGST Included $1.32')['total'],84.77)

    def test_tax_composite_row(self):
        self.assertEqual(self.result('Total\n(Includes GST:) $0.00 $7.68\nDEBIT CARD $7.68')['total'],7.68)
        self.assertIsNone(self.result('Total\nGST INCLUDED IN TOTAL $3.20')['total'])

    def test_subtotal_change_and_tendered_never_fill_total(self):
        self.assertIsNone(self.result('SUBTOTAL 50.00\nCASH $100.00\nTOTAL CHANGE 50.00')['total'])
        self.assertEqual(self.result('TOTAL for 6 items: $37.62\nCASH $50.00\nCHANGE $12.38')['total'],37.62)
        self.assertEqual(self.result('TOTAL SURCHARGE 0.50%\nPURCHASE AUD $25.15')['total'],25.15)
        self.assertIsNone(self.result('eST INCLUDED IN TOTAL\n$50.00')['total'])

    def test_zero_and_negative_totals(self):
        self.assertEqual(self.result('TOTAL $0.00')['total'],0)
        self.assertEqual(self.result('TOTAL -$12.50')['total'],-12.50)
        self.assertEqual(self.result('REFUND\nEFTPOS -$12.50')['total'],-12.50)

    def test_signed_payment_is_not_automatically_a_refund(self):
        result=self.result('SUBTOTAL 50.00\nTOTAL 50.00\nEFTPOS -50.00\nBALANCE DUE 0.00')
        self.assertEqual(result['total'],50)
        self.assertEqual(self.result('SUBTOTAL 50.00\nEFTPOS -50.00\nBALANCE 0.00')['total'],50)
        self.assertIsNone(self.result('SUBTOTAL 100.00\nEFTPOS -50.00\nBALANCE 50.00')['total'])
        self.assertIsNone(self.result('EFTPOS -50.00')['total'])

    def test_smaller_payment_does_not_displace_agreed_printed_total(self):
        texts=['TOTAI for 12 items: $80.25\nEFT $2.45\nGST INCLUDED IN TOTAL','TOTAL for 12 items: $80.25\nEFT $2.45\nGST INCLUDED IN TOTAL']
        result=reconcile([collect_candidates(t,e) for t,e in zip(texts,['paddle','unlimited'])])
        self.assertEqual(result['total'],80.25)
        rejected=next(c for c in result['fields']['total']['candidates'] if c['value']==2.45)
        self.assertIn('smaller_payment_not_transaction_total',rejected['flags'])
        self.assertNotIn('corroborated_by_payment_or_subtotal',rejected['flags'])
        self.assertTrue(result['fields']['total']['disagreement'])
        larger='TOTAL 50.00\nEFT 55.00'
        self.assertIsNone(reconcile([collect_candidates(larger,e) for e in ['paddle','oxr']])['total'])
        fallback=self.result('EFT 15.00')
        self.assertEqual(fallback['total'],15)
        self.assertNotIn('corroborated_by_payment_or_subtotal',fallback['fields']['total']['flags'])

    def test_cashout_is_separate_from_consumption_total(self):
        text='TOTAL 7.25\nPURCHASE AUD$ 7.25\nCASH OUT AUD$ 50.00\nTOTAL EFT AUD$ 57.25\nCHANGE 50.00'
        result=reconcile([collect_candidates(text,e) for e in ['paddle','oxr','unlimited']])
        self.assertEqual(result['total'],7.25)
        self.assertNotIn(57.25,[c['value'] for c in result['fields']['total']['candidates']])
        support=collect_candidates(text,'paddle')['supporting_amounts']
        self.assertIn(('cashout',50.0),[(c['kind'],c['value']) for c in support])
        self.assertIn(('settlement',57.25),[(c['kind'],c['value']) for c in support])
        self.assertEqual(self.result('PURCHASE 7.25\nCASH OUT 50.00\nTOTAL EFT 57.25')['total'],7.25)
        self.assertIsNone(self.result('CASH OUT 50.00\nTOTAL EFT 57.25')['total'])
        self.assertEqual(self.result('TOTAL EFT 7.25')['total'],7.25)

    def test_clipped_total_needs_edge_geometry_tax_context_and_consensus(self):
        def candidate(engine,x=0,tax='T Included in Total',label='TAL'):
            lines=[{'text':label,'x':x,'y':.3,'width':.08,'height':.05},
                   {'text':'$80.00','x':.72,'y':.3,'width':.18,'height':.05},
                   {'text':tax,'x':0,'y':.2,'width':.5,'height':.04},
                   {'text':'$7.27','x':.72,'y':.2,'width':.18,'height':.04}]
            return collect_candidates(label+'\n$80.00\n'+tax+'\n$7.27',engine,lines)
        self.assertIsNone(reconcile(candidate('paddle'))['total'])
        result=reconcile([candidate('paddle'),candidate('oxr')])
        self.assertEqual(result['total'],80.0)
        self.assertIn('clipped_total_label',result['fields']['total']['flags'])
        for kwargs in [{'x':.2},{'tax':'Item price'},{'label':'TAL TOOL'}]:
            self.assertIsNone(reconcile([candidate('paddle',**kwargs),candidate('oxr',**kwargs)])['total'])
        text='TAL $80.00\nT Included in Total $7.27'
        self.assertIsNone(reconcile([collect_candidates(text,e) for e in ['paddle','oxr']])['total'])

    def test_no_silent_extra_decimal_truncation(self):
        first=collect_candidates('TOTAL $542.565','vision')
        self.assertIsNone(reconcile(first)['total'])
        self.assertEqual(reconcile([first,collect_candidates('TOTAL $542.56','paddle')])['total'],542.56)

    def test_complete_item_sum_can_check_existing_total_against_ocr_majority(self):
        rows='Description $\nApples 6.00\n2 @ $3.00 EACH\nTomatoes 4.50\n0.500 kg NET @ $9.00/kg\nMilk 2.00\n2 @ $1.00 EACH\nTotal for 5 items: $12.50\nEFT $12.50\nGST INCLUDED IN TOTAL $0.45'
        correct=collect_candidates(rows,'paddle')
        self.assertEqual(correct['arithmetic_checks'][0]['value'],12.50)
        self.assertEqual(correct['arithmetic_checks'][0]['item_count'],5)
        self.assertEqual(len(correct['arithmetic_checks'][0]['excluded_unit_price_rows']),3)
        result=reconcile([correct,collect_candidates('TOTAL $18.50','oxr'),collect_candidates('TOTAL $18.50','unlimited')])
        self.assertEqual(result['total'],12.50)
        self.assertEqual(result['fields']['total']['independent_engine_count'],1)
        self.assertIn('complete_item_sum_supports_printed_total',result['fields']['total']['flags'])
        self.assertTrue(result['fields']['total']['disagreement'])
        rejected=next(c for c in result['fields']['total']['candidates'] if c['value']==18.5)
        self.assertIn('contradicted_by_complete_item_sum',rejected['flags'])

    def test_item_arithmetic_never_creates_missing_total_or_uses_partial_items(self):
        body='Description $\nApples 6.00\n2 @ $3.00 EACH\nTomatoes 4.50\n0.500 kg NET @ $9.00/kg\nMilk 2.00\n2 @ $1.00 EACH\nTotal for 5 items:'
        result=reconcile(collect_candidates(body,'paddle'))
        self.assertIsNone(result['total'])
        for text in [body.replace('5 items','6 items'),body.replace('2 @ $3.00','2 @ $2.00'),body.replace('Description $\n',''),body.replace('Milk 2.00','Milk 1.00 2.00'),body.replace('Milk 2.00','Discount -2.00'),body.replace('Milk 2.00','Milk 2 FOR $2.00')]:
            self.assertEqual(collect_candidates(text,'paddle')['arithmetic_checks'],[],text)
        mismatched=collect_candidates(body+' $18.50','paddle')
        self.assertIsNone(reconcile(mismatched)['total'])
        self.assertEqual(collect_candidates(body+' $12.50\nSurcharge 0.50\nTOTAL EFT 13.00','paddle')['arithmetic_checks'],[])

    def test_conflicting_complete_item_sums_do_not_follow_vote_count(self):
        template='Description $\nApples 6.00\nTomatoes 4.50\nMilk {milk}\nTotal for 3 items: ${total}'
        a=collect_candidates(template.format(milk='2.00',total='12.50'),'paddle')
        b=collect_candidates(template.format(milk='3.00',total='13.50'),'oxr')
        c=collect_candidates(template.format(milk='3.00',total='13.50'),'unlimited')
        result=reconcile([a,b,c])
        self.assertIsNone(result['total'])
        self.assertEqual(result['fields']['total']['status'],'conflict')
        self.assertIn('complete_item_sums_disagree',result['fields']['total']['flags'])

    def test_model_disagreement_not_majority_of_same_engine_variants(self):
        candidates=[collect_candidates('TOTAL $25.00','vision:original'),collect_candidates('TOTAL $25.00','vision:rotate'),collect_candidates('TOTAL $26.00','paddle')]
        self.assertIsNone(reconcile(candidates)['total'])
        result=reconcile([collect_candidates('TOTAL $25.00','vision'),collect_candidates('TOTAL $25.00','paddle'),collect_candidates('TOTAL $26.00','unlimited')])
        self.assertEqual(result['total'],25)
        self.assertEqual(result['fields']['total']['support'],'multi_engine_consensus')
        self.assertTrue(result['fields']['total']['disagreement'])

    def test_html_table_rows_keep_total_separate_from_subtotal(self):
        result=self.result('<table><tr><td>SUBTOTAL</td><td>50.00</td></tr><tr><td>Discount</td><td>5.00</td></tr><tr><td>TOTAL</td><td>45.00</td></tr></table>')
        self.assertEqual(result['total'],45)

    def test_larger_digits_align_with_smaller_total_label(self):
        lines=[{'text':'Total','x':.08,'y':.19,'width':.14,'height':.02}, {'text':'$84.77','x':.52,'y':.168,'width':.19,'height':.036}, {'text':'VISA','x':.08,'y':.17,'width':.06,'height':.019}, {'text':'$84.77','x':.62,'y':.146,'width':.1,'height':.023}]
        result=reconcile(collect_candidates('Total\nVISA\n$84.77\n$84.77','vision',lines))
        self.assertEqual(result['total'],84.77)

    def test_specific_fuel_brand_before_loyalty_brand(self):
        self.assertEqual(self.result('Woolworths Rewards\nWW PETROL 1980\nTOTAL 39.46')['merchant'],'Woolworths Petrol')
        self.assertIsNone(self.result('Comments: price match with Officeworks\nTOTAL 599.00')['merchant'])

    def test_generic_business_header_skips_watermarks(self):
        text='DUPLICATE\nDUPLICATE\nLOCAL SHOP NAME\n12 Example Road\nPh: 02 0000 0000\nTAX INVOICE'
        result=reconcile([collect_candidates(text,'paddle'),collect_candidates(text,'oxr')])
        self.assertEqual(result['merchant'],'LOCAL SHOP NAME')

    def test_invoice_title_does_not_hide_business_name(self):
        text='TAX INVOICE\nHarbour Supply Company\n24 Example Road\nPhone: 02 0000 0000\nABN 12 345 678 901\nITEM QTY PRICE\nOther Cafe 4.00'
        result=reconcile([collect_candidates(text,e) for e in ['paddle','oxr']])
        self.assertEqual(result['merchant'],'Harbour Supply Company')
        self.assertIsNone(self.result('TAX INVOICE\n24 Example Road\nPhone: 02 0000 0000')['merchant'])

    def test_registered_short_brand_and_official_domains(self):
        for text,name in [('BWS\nTAX INVOICE\nTOTAL 10.00','BWS'),('TOTAL 15.00\nVisit us online at www.rebelsport.com.au','Rebel Sport'),('branch@intersport.com.au\nABN 12 345 678 901','Intersport')]:
            result=self.result(text)
            self.assertEqual(result['merchant'],name)
            self.assertIn('registry_reference',result['fields']['merchant']['evidence'][0])
        self.assertIsNone(self.result('Comments: price match with BWS\nTOTAL 10.00')['merchant'])

    def test_printed_retail_brand_precedes_shared_legal_entity_abn(self):
        text='BIGW\nBIG W EXAMPLE STORE\nTAX INVOICE - ABN 88 000 014 675\nTOTAL 12.00'
        result=self.result(text)
        self.assertEqual(result['merchant'],'BIG W')
        self.assertEqual(result['fields']['merchant']['evidence'][0]['evidence'],'BIGW')
        footer='TAX INVOICE - ABN 88 000 014 675\n'+'\n'.join(['Item 2.00']*15)+'\nTOTAL 30.00\nBIG W\nDEBIT CARD\nAPPROVED'
        self.assertEqual(self.result(footer)['merchant'],'BIG W')
        for brand,name in [('BWS','BWS'),('WW PETROL','Woolworths Petrol'),('Woolworths','Woolworths')]:
            self.assertEqual(self.result(brand+'\nTAX INVOICE - ABN 88 000 014 675\nTOTAL 12.00')['merchant'],name)
        domain='TAX INVOICE - ABN 88 000 014 675\n'+'\n'.join(['Item 2.00']*15)+'\nTOTAL 30.00\nwww.bws.com.au'
        self.assertEqual(self.result(domain)['merchant'],'BWS')
        tax_header='TAX INVOICE - ABN 88 000 014 675\nTOTAL 12.00'
        mixed=reconcile([collect_candidates(tax_header,'paddle'),collect_candidates(tax_header,'unlimited'),collect_candidates('BWS\n'+tax_header,'oxr')])
        self.assertEqual(mixed['merchant'],'BWS')
        self.assertEqual(mixed['fields']['merchant']['independent_engine_count'],1)
        legal_candidate=next(c for c in mixed['fields']['merchant']['candidates'] if c['value']=='Woolworths')
        self.assertIn('legal_entity_secondary_to_printed_brand',legal_candidate['flags'])
        abn_only=reconcile([collect_candidates(tax_header,e) for e in ['paddle','oxr','unlimited']])
        self.assertIsNone(abn_only['merchant'])
        self.assertIn('shared_legal_entity_abn',abn_only['fields']['merchant']['flags'])

    def test_generic_logo_fragment_does_not_become_merchant_by_voting(self):
        for header in ['local','Thank You','Welcome','Low prices for life']:
            text=header+'\nPh: 02 0000 0000\nTAX INVOICE'
            result=reconcile([collect_candidates(text,'paddle'),collect_candidates(text,'oxr'),collect_candidates(text,'unlimited')])
            self.assertIsNone(result['merchant'])

    def test_full_business_name_after_logo_fragments(self):
        text='XYOAS\nRIVER FRUIT\nRiver Coast Fruit Market\nFairy Meadow\nPhone: 02 0000 0000\nITEM QTY PRICE\nOther Cafe 4.00'
        result=self.result(text)
        self.assertEqual(result['merchant'],'River Coast Fruit Market')
        self.assertEqual(result['fields']['merchant']['evidence'][0]['evidence'],'River Coast Fruit Market')
        candidates=collect_candidates(text,'test')['merchant']
        self.assertNotIn('Other Cafe 4.00',[c['value'] for c in candidates])
        self.assertIn('RIVER FRUIT',[c['value'] for c in candidates])

    def test_merchant_typography_agrees_but_spelling_remains_distinct(self):
        texts=['River Coast Fruit Market','RIVER COAST FRUIT MARKET','Rivet Coast Fruit Market']
        result=reconcile([collect_candidates(t+'\nPhone: 02 0000 0000',e) for t,e in zip(texts,['paddle','oxr','unlimited'])])
        self.assertEqual(result['merchant'],'River Coast Fruit Market')
        self.assertEqual(result['fields']['merchant']['independent_engine_count'],2)
        self.assertTrue(result['fields']['merchant']['disagreement'])
        self.assertEqual(len(result['fields']['merchant']['candidates']),2)

    def test_merchant_ampersand_and_word_agree_across_models(self):
        texts=['River Bar & Grill','River Bar and Grill','Rivet Bar and Grill']
        result=reconcile([collect_candidates(t+'\nPhone: 02 0000 0000',e) for t,e in zip(texts,['paddle','oxr','unlimited'])])
        self.assertEqual(result['merchant'],'River Bar & Grill')
        self.assertEqual(result['fields']['merchant']['independent_engine_count'],2)
        self.assertEqual(len(result['fields']['merchant']['candidates']),2)
        quotes={c['evidence'] for c in result['fields']['merchant']['evidence']}
        self.assertEqual(quotes,{'River Bar & Grill','River Bar and Grill'})

    def logo_candidates(self,engine,name,logo=None,height=.07,prefix=''):
        lines=[{'text':name,'x':.2,'y':.65,'width':.6,'height':.04},
               {'text':'Phone: 02 0000 0000','x':.2,'y':.57,'width':.5,'height':.04}]
        text=prefix+(logo+'\n' if logo else '')+name+'\nPhone: 02 0000 0000'
        if logo:lines.insert(0,{'text':logo,'x':.2,'y':.8,'width':.4,'height':height})
        return collect_candidates(text,engine,lines)

    def test_logo_disambiguates_only_an_existing_full_name(self):
        correct='Riverdale Coast Fruit Market';alternate='Riverdalo Coast Fruit Market'
        result=reconcile([self.logo_candidates('paddle',alternate,'RIVERDALE'),
                          self.logo_candidates('oxr',correct,'RIVERDALE FRUIT'),
                          self.logo_candidates('unlimited',alternate)])
        self.assertEqual(result['merchant'],correct)
        self.assertEqual(result['fields']['merchant']['independent_engine_count'],1)
        resolution=result['fields']['merchant']['logo_disambiguation']
        self.assertEqual(resolution['independent_logo_engines'],['oxr','paddle'])
        self.assertEqual(resolution['full_name_engines'],['oxr'])
        self.assertIn(alternate,[e['body_evidence'] for e in resolution['evidence']])
        self.assertEqual(result['fields']['merchant']['evidence'][0]['evidence'],correct)
        no_full_name=reconcile([self.logo_candidates(e,alternate,'RIVERDALE') for e in ['paddle','oxr']])
        self.assertEqual(no_full_name['merchant'],alternate)
        self.assertNotIn('logo_disambiguation',no_full_name['fields']['merchant'])

    def test_logo_views_are_not_independent_models(self):
        correct='Riverdale Coast Fruit Market';alternate='Riverdalo Coast Fruit Market'
        result=reconcile([self.logo_candidates('paddle',alternate,'RIVERDALE'),
                          self.logo_candidates('paddle:detail',alternate,'RIVERDALE'),
                          self.logo_candidates('oxr',correct),self.logo_candidates('unlimited',alternate)])
        self.assertEqual(result['merchant'],alternate)
        self.assertNotIn('logo_disambiguation',result['fields']['merchant'])

    def test_logo_requires_specific_large_uncontested_brand_text(self):
        cases=[('Local','Locam','LOCAL',.07,''),('Riverdale','Rivertone','RIVERDALE',.07,''),
               ('Riverdale','Riverdalo','RIVERDALE',.03,''),('Riverdale','Riverdalo','RIVERDALE',.07,'Coupon redeem at\n')]
        for correct,alternate,logo,height,prefix in cases:
            a=correct+' Coast Fruit Market';b=alternate+' Coast Fruit Market'
            result=reconcile([self.logo_candidates('paddle',b,logo,height,prefix),self.logo_candidates('oxr',a,logo,height,prefix),self.logo_candidates('unlimited',b)])
            self.assertNotIn('logo_disambiguation',result['fields']['merchant'],cases)
        result=reconcile([self.logo_candidates('paddle','Riverdalo Coast Fruit Market','RIVERDALE'),
                          self.logo_candidates('oxr','Riverdale Coast Fruit Market','RIVERDALE'),
                          self.logo_candidates('unlimited','Riverdalo Coast Fruit Market','RIVERDALO')])
        self.assertNotIn('logo_disambiguation',result['fields']['merchant'])

    def test_payment_footer_brand_identifies_merchant(self):
        text='Store: 123 - SHOP\nDescription\n'+ '\n'.join(['Food item 2.00']*15)+'\nTOTAL 30.00\nEFT 30.00\nColes\n09/02/21 11:21\nNSW AU\nDEBIT CARD\nAPPROVED'
        result=self.result(text)
        self.assertEqual(result['merchant'],'Coles')
        self.assertEqual(result['fields']['merchant']['evidence'][0]['kind'],'merchant_payment_footer')

    def test_payment_footer_brand_alias_overrides_loyalty_mention(self):
        text='Woolworths Rewards\n'+'\n'.join(['Fuel item']*13)+'\nSUBTOTAL\n39.46\nWW PETROL 1234\nNSW\nMERCH ID: 1234567\nCARD\nTOTAL 39.46'
        result=self.result(text)
        self.assertEqual(result['merchant'],'Woolworths Petrol')
        self.assertEqual(result['fields']['merchant']['evidence'][0]['evidence'],'WW PETROL 1234')
        self.assertIsNone(self.result('Woolworths Rewards\nTOTAL 5.00')['merchant'])

    def test_footer_competitor_coupon_and_product_are_not_merchant(self):
        for middle in ['Coupon redeem at\nColes','Price match with\nColes','Coles French Comte 9.44']:
            text='\n'.join(['Food item 2.00']*15)+'\nTOTAL 30.00\n'+middle+'\nDEBIT CARD\nAPPROVED'
            self.assertIsNone(self.result(text)['merchant'])

    def test_official_domain_and_verified_slogan_need_receipt_context(self):
        text='\n'.join(['Product 2.00']*15)+'\nTOTAL 30.00\nwww.officeworks.com.au'
        self.assertEqual(self.result(text)['merchant'],'Officeworks')
        self.assertIsNone(self.result('Coupon redeem at www.officeworks.com.au')['merchant'])
        self.assertEqual(self.result('Value the Australian way\nStore: 839\nServed By: Assisted Checkout\nRegister: 125')['merchant'],'Coles')
        self.assertIsNone(self.result('Article about Value the Australian way')['merchant'])


if __name__=='__main__': unittest.main()

