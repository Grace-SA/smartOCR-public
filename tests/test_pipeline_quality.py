"""Regression tests using isolated, explicitly synthetic OCR cache fixtures.

The tiny blank PNG supplies cache identity only; these are not accuracy samples.
No fixture is added to a sample manifest, real database, or project cache.
"""
import copy
import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import receipt_pipeline as pipeline


class PipelineQualityTests(unittest.TestCase):
    RECORD_ID = 'TEST-ONLY-PIPELINE-001'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='receipt-pipeline-test-only-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.cache = self.root / 'data/ensemble'
        self.image = self.root / 'test-only-images' / (self.RECORD_ID + '.png')
        self.image.parent.mkdir(parents=True)
        Image.new('RGB', (16, 16), 'white').save(self.image)
        digest = hashlib.sha256(self.image.read_bytes()).hexdigest()

        for directory in ('normalized', 'oriented'):
            target = self.cache / directory / (self.RECORD_ID + '.png')
            target.parent.mkdir(parents=True)
            target.write_bytes(self.image.read_bytes())
        self.write_json(self.cache / 'normalized' / (self.RECORD_ID + '.source.json'), {
            'source_path': str(self.image.relative_to(self.root)),
            'source_sha256': digest,
            'normalized_sha256': digest,
        })
        self.write_json(self.cache / 'oriented' / (self.RECORD_ID + '.orientation.json'), {
            'input_sha256': digest,
            'output_sha256': digest,
            'angle': 0,
        })

        # These transcripts are deliberately authored test data, not OCR output
        # produced from the blank image and not part of the 100-receipt corpus.
        texts = ['Coles', 'Date 03/01/2025', 'TOTAL $12.34', 'AUD']
        paddle_lines, oxr_blocks = [], []
        for index, text in enumerate(texts):
            top = 1 + index * 3
            paddle_lines.append({
                'text': text, 'confidence': 1.0,
                'polygon': [[1, top], [15, top], [15, top + 2], [1, top + 2]],
            })
            oxr_blocks.append({'label': 'text', 'content': text, 'bbox': [1, top, 15, top + 2]})
        common = {'input_sha256': digest, 'image_size': [16, 16], 'capped': False, 'seconds': 0.0}
        self.write_json(self.engine_path('paddle'), {
            **common, 'engine': 'TEST-ONLY-PADDLE', 'lines': paddle_lines,
        })
        self.write_json(self.engine_path('oxr'), {
            **common, 'engine': 'TEST-ONLY-OXR', 'coordinate_space': 'pixels', 'blocks': oxr_blocks,
        })
        self.write_json(self.engine_path('unlimited'), {
            **common, 'engine': 'TEST-ONLY-U2', 'coordinate_space': 'pixels',
            'blocks': [{'label': 'image', 'content': '', 'bbox': [0, 0, 16, 16]}],
            'raw': '<PAGE><BLOCK>image[0, 0, 16, 16]<FORK>',
        })

        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(pipeline, 'ROOT', self.root))
        stack.enter_context(patch.object(pipeline, 'CACHE', self.cache))
        self.model_calls = {}
        for name in ('prepare_images', 'run_engine', 'run_focused_unlimited',
                     'run_focused_oxr', 'run_detail_review', 'local_ai'):
            self.model_calls[name] = stack.enter_context(patch.object(
                pipeline, name, side_effect=AssertionError(f'{name} must not run in cache-only tests')))
        self.model_calls['subprocess.run'] = stack.enter_context(patch.object(
            pipeline.subprocess, 'run', side_effect=AssertionError('No model or other subprocess may start')))
        self.addCleanup(self.assert_no_model_calls)

    @staticmethod
    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')

    def engine_path(self, name):
        return self.cache / name / (self.RECORD_ID + '.json')

    def extract(self):
        return pipeline.extract_ensemble_record(
            self.image, source={'kind': 'test_only', 'license': 'Synthetic test fixture'},
            record_id=self.RECORD_ID, run_models=False)

    def extract_live(self):
        # Live routing is exercised against the same isolated cache fixtures.
        # Image preparation and classification are outside this routing test;
        # all OCR runners remain forbidden unless a test explicitly mocks one.
        with patch.object(pipeline, 'prepare_images', return_value=[]) as prepare:
            with patch.object(pipeline, '_apply_classification',
                              side_effect=lambda record, allow_model: record):
                result = pipeline.extract_ensemble_record(
                    self.image, source={'kind': 'test_only'},
                    record_id=self.RECORD_ID, run_models=True)
        prepare.assert_called_once()
        return result

    def assert_no_model_calls(self):
        for name, mocked in self.model_calls.items():
            with self.subTest(model_entry=name):
                mocked.assert_not_called()

    def enable_three_full_text_outputs(self):
        u2 = json.loads(self.engine_path('oxr').read_text())
        u2['engine'] = 'TEST-ONLY-U2'
        self.write_json(self.engine_path('unlimited'), u2)

    def write_oxr_focus(self, raw):
        prepared = self.cache / 'oriented' / (self.RECORD_ID + '.png')
        focus_image = self.cache / 'focus' / (self.RECORD_ID + '.png')
        focus_image.parent.mkdir(parents=True, exist_ok=True)
        focus_image.write_bytes(prepared.read_bytes())
        digest = hashlib.sha256(focus_image.read_bytes()).hexdigest()
        focus = copy.deepcopy(raw)
        focus.update({'capped': False, 'variant': 'focus', 'source_input_sha256': digest,
                      'focus': {'source_sha256': digest, 'output_sha256': digest,
                                'output_path': str(focus_image),
                                'regions': [{'source_bbox': [0, 0, 16, 16], 'focus_bbox': [0, 0, 16, 16]}]}})
        self.write_json(self.engine_path('oxr_focus'), focus)

    def write_detail(self, field, engine, texts, capped=False):
        directory = self.cache / 'detail' / field
        image_path = directory / 'images' / (self.RECORD_ID + '.png')
        image_path.parent.mkdir(parents=True, exist_ok=True)
        source = self.cache / 'oriented' / (self.RECORD_ID + '.png')
        with Image.open(source) as image:
            image.crop((0, 0, 16, 16)).resize((32, 32), Image.Resampling.LANCZOS).save(image_path)
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        metadata = {
            'field': field, 'source_path': str(source),
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'output_path': str(image_path), 'output_sha256': digest,
            'source_bbox': [0, 0, 16, 16], 'scale': 2,
        }
        metadata_path = image_path.with_suffix('.detail.json')
        self.write_json(metadata_path, metadata)
        raw = {'engine': 'TEST-ONLY-DETAIL-' + engine, 'input_sha256': digest,
               'image_size': [32, 32], 'capped': capped, 'seconds': 0.0}
        if engine == 'paddle':
            raw['lines'] = [{'text': text, 'confidence': 1.0,
                             'polygon': [[2, 2+i*5], [30, 2+i*5], [30, 4+i*5], [2, 4+i*5]]}
                            for i, text in enumerate(texts)]
        else:
            raw['coordinate_space'] = 'pixels'
            raw['blocks'] = [{'label': 'text', 'content': text, 'bbox': [2, 2+i*5, 30, 4+i*5]}
                             for i, text in enumerate(texts)]
        path = directory / engine / (self.RECORD_ID + '.json')
        self.write_json(path, raw)
        return metadata_path, path

    def test_image_only_u2_preserves_other_evidence_but_is_not_complete(self):
        result = self.extract()
        self.assertEqual((result['merchant'], result['date'], result['total']),
                         ('Coles', '2025-01-03', 12.34))
        self.assertEqual(result['status'], 'review')
        self.assertEqual(result['purpose'], 'unknown')
        self.assertEqual(result['ensemble_status'], 'partial')
        self.assertEqual(result['ensemble_quality']['inference_completed_count'], 3)
        self.assertEqual(result['ensemble_quality']['text_engine_count'], 2)
        self.assertEqual(result['ensemble_quality']['complete_text_engine_count'], 2)
        u2 = result['ocr_engines']['unlimited']
        self.assertTrue(u2['inference_completed'])
        self.assertFalse(u2['has_text'])
        self.assertFalse(u2['recognition_complete'])
        self.assertEqual(u2['status'], 'empty')
        self.assertEqual(u2['variants'][0]['evidence_text'], '')
        for field in ('merchant', 'date', 'total'):
            with self.subTest(field=field):
                self.assertEqual(u2['variants'][0]['candidates'][field], [])
                self.assertEqual(set(result['field_evidence'][field]['engines']), {'paddle', 'oxr'})
                self.assertEqual(result['field_evidence'][field]['independent_engine_count'], 2)

    def test_cache_only_starts_no_models_and_rejects_wrong_image_hash(self):
        result = self.extract()
        self.assertTrue(result['processing']['cache_only'])
        self.assertEqual(result['processing']['runs'], [])
        paddle = json.loads(self.engine_path('paddle').read_text())
        paddle['input_sha256'] = '0' * 64
        self.write_json(self.engine_path('paddle'), paddle)
        with self.assertRaisesRegex(RuntimeError, '缓存不属于当前照片'):
            self.extract()

    def test_classification_cannot_overwrite_core_fields_or_their_evidence(self):
        baseline = self.extract()
        core = {key: baseline[key] for key in ('merchant', 'date', 'total')}
        evidence = {key: copy.deepcopy(baseline['field_evidence'][key]) for key in core}
        self.write_json(self.cache / 'classification' / (self.RECORD_ID + '.json'), {
            'text_sha256': hashlib.sha256(baseline['ocr_text'].encode()).hexdigest(),
            'suggestion': {
                'category': 'grocery', 'tags': ['TEST-ONLY-CLASSIFICATION'],
                'reasoning': 'Synthetic classification regression fixture.',
                'merchant': 'MALICIOUS OVERRIDE', 'date': '2099-12-31', 'total': 999999,
                'purpose': 'work', 'status': 'confirmed',
            },
        })
        result = self.extract()
        self.assertEqual(result['tags'], ['TEST-ONLY-CLASSIFICATION'])
        self.assertEqual({key: result[key] for key in core}, core)
        self.assertEqual({key: result['field_evidence'][key] for key in core}, evidence)
        self.assertEqual(result['purpose'], 'unknown')
        self.assertEqual(result['status'], 'review')

    def test_two_detail_models_can_correct_old_majority_without_leaking_other_fields(self):
        self.enable_three_full_text_outputs()
        baseline = self.extract()
        self.assertEqual(baseline['total'], 12.34)
        self.assertEqual(baseline['field_evidence']['total']['independent_engine_count'], 3)
        # Wrong full-view majority versus two clear target-field detail readings.
        # Non-target merchant/date text must not change those receipt fields.
        detail_text = ['Bunnings', 'Date 04/02/2024', 'TOTAL $56.78']
        for engine in ('paddle', 'oxr'):
            self.write_detail('total', engine, detail_text)
        result = self.extract()
        self.assertEqual(result['total'], 56.78)
        self.assertEqual(result['merchant'], 'Coles')
        self.assertEqual(result['date'], '2025-01-03')
        self.assertEqual(result['ocr_engines'], baseline['ocr_engines'])
        self.assertEqual(result['base_reconciliation'], baseline['reconciliation'])
        review = result['detail_evidence']['total']
        self.assertEqual(review['status'], 'overrode_base')
        self.assertTrue(review['applied'])
        self.assertTrue(review['base_detail_disagreement'])
        self.assertEqual(review['accepted_engine_count'], 2)
        field = result['field_evidence']['total']
        self.assertEqual(field['review_source'], 'detail_consensus')
        self.assertEqual(field['independent_engine_count'], 2)
        self.assertEqual({option['value'] for option in field['candidates']}, {12.34, 56.78})
        self.assertTrue(all(len(option['engines']) <= 3 for option in field['candidates']))
        for view in review['views'].values():
            self.assertEqual(view['decision']['value'], 56.78)
            self.assertEqual(view['candidates']['merchant'], [])
            self.assertEqual(view['candidates']['date'], [])

    def test_single_or_disagreeing_detail_models_cannot_override_full_result(self):
        self.enable_three_full_text_outputs()
        baseline = self.extract()
        self.write_detail('total', 'paddle', ['TOTAL $56.78'])
        single = self.extract()
        self.assertEqual(single['total'], 12.34)
        self.assertFalse(single['detail_evidence']['total']['applied'])
        self.assertTrue(single['detail_evidence']['total']['base_detail_disagreement'])
        self.assertEqual(single['detail_evidence']['total']['status'], 'insufficient_detail_consensus')
        self.assertEqual(single['field_evidence']['total']['evidence'], baseline['field_evidence']['total']['evidence'])
        self.write_detail('total', 'oxr', ['TOTAL $56.78'], capped=True)
        capped = self.extract()
        self.assertEqual(capped['total'], 12.34)
        self.assertEqual(capped['detail_evidence']['total']['accepted_engine_count'], 1)
        self.write_detail('total', 'oxr', ['TOTAL $77.89'])
        conflict = self.extract()
        self.assertEqual(conflict['total'], 12.34)
        self.assertFalse(conflict['detail_evidence']['total']['applied'])
        self.assertEqual(conflict['detail_evidence']['total']['status'], 'detail_conflict')
        self.assertEqual({option['value'] for option in conflict['field_evidence']['total']['candidates']},
                         {12.34, 56.78, 77.89})
        self.write_detail('total', 'unlimited', ['TOTAL $56.78'])
        divided_majority = self.extract()
        self.assertEqual(divided_majority['total'], 12.34)
        self.assertEqual(divided_majority['detail_evidence']['total']['status'], 'detail_conflict')

    def test_detail_hash_chain_rejects_stale_views_without_discarding_base(self):
        self.enable_three_full_text_outputs()
        self.write_detail('total', 'paddle', ['TOTAL $56.78'])
        metadata_path, raw_path = self.write_detail('total', 'oxr', ['TOTAL $56.78'])
        original_metadata = json.loads(metadata_path.read_text())
        original_raw = json.loads(raw_path.read_text())
        for layer in ('source', 'detail_image', 'raw_ocr'):
            with self.subTest(hash_layer=layer):
                metadata, raw = copy.deepcopy(original_metadata), copy.deepcopy(original_raw)
                if layer == 'source':
                    metadata['source_sha256'] = '0' * 64
                elif layer == 'detail_image':
                    metadata['output_sha256'] = '0' * 64
                else:
                    raw['input_sha256'] = '0' * 64
                self.write_json(metadata_path, metadata)
                self.write_json(raw_path, raw)
                result = self.extract()
                self.assertEqual(result['total'], 12.34)
                review = result['detail_evidence']['total']
                self.assertFalse(review['applied'])
                self.assertNotIn('oxr', review['views'])
                self.assertTrue(any(error['engine'] == 'oxr' for error in review['errors']))
                self.assertTrue(result['ocr_engines']['oxr']['recognition_complete'])

    def test_detail_consensus_cannot_defeat_full_arithmetic_or_payment_semantics(self):
        complete_table = ('Description $\nApples 5.00\nBread 4.00\nMilk 3.34\n'
                          'Total for 3 items: $12.34')
        arithmetic_base = pipeline.reconcile([
            pipeline.collect_candidates(complete_table, 'paddle'),
            pipeline.collect_candidates('TOTAL $56.78', 'oxr'),
            pipeline.collect_candidates('TOTAL $56.78', 'unlimited'),
        ])
        self.assertEqual(arithmetic_base['total'], 12.34)
        self.assertIn('arithmetic_reconciled_ocr_disagreement', arithmetic_base['fields']['total']['flags'])
        for engine in ('paddle', 'oxr'):
            self.write_detail('total', engine, ['TOTAL $56.78'])
        prepared = self.cache / 'oriented' / (self.RECORD_ID + '.png')
        views = pipeline.load_detail_evidence(self.RECORD_ID, prepared)
        merged, reviews = pipeline.merge_detail_evidence(arithmetic_base, views)
        self.assertEqual(merged['total'], 12.34)
        self.assertEqual(reviews['total']['status'], 'semantic_conflict')
        self.assertEqual(reviews['total']['semantic_guard']['code'], 'contradicts_complete_item_sum')
        self.assertEqual(merged['fields']['total']['arithmetic_checks'], arithmetic_base['fields']['total']['arithmetic_checks'])

        printed_base = pipeline.reconcile([
            pipeline.collect_candidates('TOTAL $88.25\nEFT $2.95', engine)
            for engine in ('paddle', 'oxr')
        ])
        self.assertEqual(printed_base['total'], 88.25)
        for engine in ('paddle', 'oxr'):
            self.write_detail('total', engine, ['EFT $2.95'])
        views = pipeline.load_detail_evidence(self.RECORD_ID, prepared)
        merged, reviews = pipeline.merge_detail_evidence(printed_base, views)
        self.assertEqual(merged['total'], 88.25)
        self.assertEqual(reviews['total']['accepted_engine_count'], 2)
        self.assertEqual(reviews['total']['semantic_guard']['code'], 'payment_cannot_replace_printed_total')

    def test_independent_detail_print_requires_complete_arithmetic_for_single_model_resolution(self):
        complete='Description $\nApples 5.00\nBread 4.00\nMilk 3.34\nTotal for 3 items: $56.78'
        base=pipeline.reconcile([pipeline.collect_candidates(complete,'paddle'),
                                 pipeline.collect_candidates('TOTAL $56.78','unlimited')])
        self.assertIsNone(base['total'])
        prepared=self.cache/'oriented'/(self.RECORD_ID+'.png')
        # A sum alone never supplies a missing printed value.
        merged,_=pipeline.merge_detail_evidence(base,{})
        self.assertIsNone(merged['total'])
        self.write_detail('total','paddle',['TOTAL $12.34'])
        merged,_=pipeline.merge_detail_evidence(base,pipeline.load_detail_evidence(self.RECORD_ID,prepared))
        self.assertIsNone(merged['total'])  # same model is not independent proof
        self.write_detail('total','oxr',['TOTAL $12.34'])
        (self.cache/'detail'/'total'/'paddle'/(self.RECORD_ID+'.json')).unlink()
        merged,reviews=pipeline.merge_detail_evidence(base,pipeline.load_detail_evidence(self.RECORD_ID,prepared))
        self.assertEqual(merged['total'],12.34)
        self.assertEqual(merged['fields']['total']['review_source'],'detail_with_full_arithmetic')
        self.assertEqual(merged['fields']['total']['independent_engine_count'],1)
        self.assertEqual(merged['fields']['total']['independent_evidence_engines'],['oxr','paddle'])
        self.assertTrue(reviews['total']['arithmetic_cross_check'])
        self.write_detail('total','oxr',['TOTAL $12.34'],capped=True)
        merged,_=pipeline.merge_detail_evidence(base,pipeline.load_detail_evidence(self.RECORD_ID,prepared))
        self.assertIsNone(merged['total'])

    def test_capped_full_output_cannot_certify_complete_item_arithmetic(self):
        raw=json.loads(self.engine_path('oxr').read_text())
        raw.update(capped=True,blocks=[{'label':'text','content':'Description $\nApples 5.00\nBread 4.00\nMilk 3.34\nTotal for 3 items: $12.34','bbox':[0,0,16,16]}])
        self.write_json(self.engine_path('oxr'),raw)
        view=pipeline._load_variant('oxr',self.RECORD_ID,raw['input_sha256'])
        self.assertEqual(view['candidates']['arithmetic_checks'],[])
        self.assertTrue(view['candidates']['rejected_arithmetic_checks'])
        self.assertTrue(view['evidence_text'])

    def test_arithmetic_resolution_retains_detail_disagreement_without_base_total(self):
        base=pipeline.reconcile(pipeline.collect_candidates('Apples 10.00\nBread 20.52\n2 SUBTOTAL $30.52','paddle'))
        self.assertIsNone(base['total'])
        self.assertFalse(base['fields']['total']['disagreement'])
        self.write_detail('total','oxr',['TOTAL $30.52'])
        self.write_detail('total','unlimited',['TOTAL $80.52'])
        views=pipeline.load_detail_evidence(self.RECORD_ID,self.cache/'oriented'/(self.RECORD_ID+'.png'))
        merged,_=pipeline.merge_detail_evidence(base,views)
        self.assertEqual(merged['total'],30.52)
        self.assertTrue(merged['fields']['total']['disagreement'])
        self.assertEqual(merged['fields']['total']['independent_engine_count'],1)

    def test_valid_oxr_focus_completes_capped_engine_without_an_extra_vote(self):
        self.enable_three_full_text_outputs()
        full = json.loads(self.engine_path('oxr').read_text())
        full['capped'] = True
        self.write_json(self.engine_path('oxr'), full)
        self.write_oxr_focus(full)
        result = self.extract()
        oxr = result['ocr_engines']['oxr']
        self.assertEqual(oxr['status'], 'complete')
        self.assertTrue(oxr['recognition_complete'])
        self.assertTrue(oxr['capped'])
        self.assertEqual(oxr['complete_variants'], ['focus'])
        self.assertEqual({view['variant'] for view in oxr['variants']}, {'full', 'focus'})
        self.assertEqual(result['ensemble_status'], 'complete')
        self.assertEqual(result['field_evidence']['total']['independent_engine_count'], 3)
        self.assertTrue(any('OXR' in warning and '长度限制' in warning for warning in result['warnings']))

    def test_live_oxr_retry_reloads_once_and_reuses_valid_focus(self):
        self.enable_three_full_text_outputs()
        valid = json.loads(self.engine_path('oxr').read_text())
        for bad_output in ('empty', 'capped'):
            with self.subTest(full_output=bad_output):
                self.engine_path('oxr_focus').unlink(missing_ok=True)
                full = copy.deepcopy(valid)
                if bad_output == 'empty':
                    full['blocks'] = [{'label': 'image', 'content': '', 'bbox': [0, 0, 16, 16]}]
                else:
                    full['capped'] = True
                self.write_json(self.engine_path('oxr'), full)

                def retry(mapping):
                    self.assertEqual(mapping[0]['id'], self.RECORD_ID)
                    self.write_oxr_focus(valid)
                    return {'engine': 'oxr', 'requested': 1, 'processed': 1, 'elapsed_s': 0.01}

                with patch.object(pipeline, 'run_focused_oxr', side_effect=retry) as mocked:
                    result = self.extract_live()
                    reused = self.extract_live()
                mocked.assert_called_once()
                self.assertEqual(result['ocr_engines']['oxr']['status'], 'complete')
                self.assertEqual(result['ocr_engines']['oxr']['variants'][0]['raw_output'], full)
                self.assertEqual(result['total'], 12.34)
                self.assertEqual(reused['processing']['runs'], [])
                run = result['processing']['runs'][0]
                self.assertEqual(run['stage'], 'oxr_focus_retry')
                self.assertEqual(run['status'], 'completed')
                self.assertTrue(run['execution_completed'])
                self.assertTrue(run['output_complete'])
                self.assertGreaterEqual(run['elapsed_s'], 0)

    def test_live_oxr_retry_failure_or_empty_result_is_not_success(self):
        self.enable_three_full_text_outputs()
        full = json.loads(self.engine_path('oxr').read_text())
        full['capped'] = True
        self.write_json(self.engine_path('oxr'), full)
        for outcome in ('failure', 'no_output'):
            with self.subTest(outcome=outcome):
                effect = RuntimeError('TEST-ONLY retry failure') if outcome == 'failure' else None
                with patch.object(pipeline, 'run_focused_oxr', side_effect=effect,
                                  return_value={'engine': 'oxr', 'processed': 0}) as mocked:
                    result = self.extract_live()
                mocked.assert_called_once()
                self.assertEqual(result['total'], 12.34)
                self.assertEqual(result['ocr_engines']['oxr']['status'], 'truncated')
                self.assertEqual(result['ocr_engines']['oxr']['variants'][0]['raw_output'], full)
                run = result['processing']['runs'][0]
                self.assertEqual(run['status'], 'failed' if outcome == 'failure' else 'incomplete')
                self.assertEqual(run['execution_completed'], outcome != 'failure')
                self.assertFalse(run['output_complete'])
                self.assertTrue(any('OXR 重点区域重试' in warning for warning in result['warnings']))

    def test_live_detail_review_triggers_for_missing_or_disagreeing_base(self):
        self.enable_three_full_text_outputs()
        originals = {engine: json.loads(self.engine_path(engine).read_text()) for engine in pipeline.ENGINES}
        for trigger in ('disagreement', 'missing'):
            with self.subTest(trigger=trigger):
                for engine, original in originals.items():
                    raw = copy.deepcopy(original)
                    rows = raw.get('lines', raw.get('blocks'))
                    key = 'text' if engine == 'paddle' else 'content'
                    if trigger == 'missing':
                        rows[:] = [row for row in rows if not row[key].startswith('TOTAL')]
                    elif engine == 'oxr':
                        for row in rows:
                            if row[key].startswith('TOTAL'):
                                row[key] = 'TOTAL $56.78'
                    self.write_json(self.engine_path(engine), raw)

                def review(mapping):
                    self.assertEqual(mapping[0]['id'], self.RECORD_ID)
                    # This mirrors the runner's recursive candidate inspection:
                    # cache-only replay must not invoke this or any other runner.
                    inspected = self.extract()
                    self.assertIn('total', inspected['processing']['detail_trigger_fields'])
                    for engine in pipeline.ENGINES:
                        self.write_detail('total', engine, ['TOTAL $12.34'])
                    return {'stage': 'detail_review', 'requested': 1, 'elapsed_s': 0.01}

                with patch.object(pipeline, 'run_detail_review', side_effect=review) as mocked:
                    result = self.extract_live()
                mocked.assert_called_once()
                self.assertEqual(result['total'], 12.34)
                self.assertEqual(result['processing']['detail_trigger_fields'], ['total'])
                self.assertTrue(result['detail_evidence']['total']['applied'])
                self.assertEqual(result['detail_evidence']['total']['status'],
                                 'filled_missing' if trigger == 'missing' else 'corroborated')
                run = result['processing']['runs'][0]
                self.assertEqual(run['stage'], 'detail_review')
                self.assertEqual(run['status'], 'completed')
                self.assertEqual(run['complete_fields'], ['total'])
                self.assertTrue(run['output_complete'])
                self.assertGreaterEqual(run['elapsed_s'], 0)

    def test_live_detail_failure_preserves_evidence_and_is_recorded(self):
        self.enable_three_full_text_outputs()
        oxr = json.loads(self.engine_path('oxr').read_text())
        oxr['blocks'][2]['content'] = 'TOTAL $56.78'
        self.write_json(self.engine_path('oxr'), oxr)
        baseline = self.extract()
        for outcome in ('failure', 'no_output'):
            with self.subTest(outcome=outcome):
                effect = RuntimeError('TEST-ONLY detail failure') if outcome == 'failure' else None
                with patch.object(pipeline, 'run_detail_review', side_effect=effect,
                                  return_value={'stage': 'detail_review', 'requested': 1}) as mocked:
                    result = self.extract_live()
                mocked.assert_called_once()
                self.assertEqual(result['total'], baseline['total'])
                self.assertEqual(result['ocr_engines'], baseline['ocr_engines'])
                self.assertEqual(result['field_evidence']['total'], baseline['field_evidence']['total'])
                run = result['processing']['runs'][0]
                self.assertEqual(run['status'], 'failed' if outcome == 'failure' else 'incomplete')
                self.assertFalse(run['output_complete'])
                self.assertTrue(any('局部复核' in warning for warning in result['warnings']))

    def test_detail_majority_cannot_overrule_independent_logo_identity(self):
        # The extraction module has already resolved an existing full-name
        # candidate using two independently read logo tokens. A crop without
        # that logo must not reinstate the alternate spelling by majority.
        base = self.extract()['base_reconciliation']
        correct, alternate = 'Leisure Coast Fruit Market', 'Leisura Coast Fruit Market'
        decision = pipeline.reconcile([
            pipeline.collect_candidates(correct + '\nABN 12 345 678 901', 'oxr')
        ])['fields']['merchant']
        self.assertEqual(decision['value'], correct)
        logo = {'selected_value': correct, 'alternative_values': [alternate],
                'supported_words': ['leisure'], 'independent_logo_engines': ['paddle', 'oxr'],
                'full_name_engines': ['oxr'],
                'evidence': [{'engine': engine, 'word': 'leisure', 'evidence': 'LEISURE',
                              'body_value': correct, 'body_evidence': correct}
                             for engine in ('paddle', 'oxr')],
                'method': 'existing_full_name_disambiguated_by_separate_logo'}
        decision.update(logo_disambiguation=logo, disagreement=True)
        decision['flags'].append('existing_name_disambiguated_by_logo')
        base['fields']['merchant'], base['merchant'] = decision, correct
        for engine in ('paddle', 'oxr'):
            self.write_detail('merchant', engine, [alternate, 'ABN 12 345 678 901'])
        prepared = self.cache / 'oriented' / (self.RECORD_ID + '.png')
        merged, reviews = pipeline.merge_detail_evidence(base, pipeline.load_detail_evidence(self.RECORD_ID, prepared))
        self.assertEqual(merged['merchant'], correct)
        self.assertEqual(reviews['merchant']['accepted_engine_count'], 2)
        self.assertEqual(reviews['merchant']['status'], 'semantic_conflict')
        self.assertEqual(reviews['merchant']['semantic_guard']['code'], 'logo_identity_conflict')
        self.assertEqual(merged['fields']['merchant']['logo_disambiguation'], logo)
        self.assertEqual(reviews['merchant']['detail_decision']['value'], alternate)


if __name__ == '__main__':
    unittest.main()
