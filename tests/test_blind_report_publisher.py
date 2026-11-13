"""Presentation safety checks using invented 100-row data in temporary files."""
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'scripts/publish_blind_report.py'
SPEC = importlib.util.spec_from_file_location('blind_publisher', MODULE)
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-blind-publisher-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = {key: self.root / name for key, name in {
            'evaluation': 'synthetic-evaluation.json', 'diagnosis': 'synthetic-diagnosis.json',
            'manifest': 'synthetic-manifest.json', 'workbook': 'synthetic.xlsx',
            'primary': 'synthetic.html', 'strict': 'synthetic-strict.html',
            'sources': 'synthetic-sources.json', 'audit': 'synthetic-audit.json',
        }.items()}
        self.rows = [{
            'id': f'synthetic_{i:03}',
            'expected': {'merchant': 'Example Merchant', 'date': '2020-01-01', 'total': '1.00'},
            'actual': {'merchant': 'Example Merchant', 'date': '2020-01-01', 'total': 1.0},
            'field_matches': {'merchant': True, 'date': True, 'total': True},
            'auto_confirmed': False,
        } for i in range(100)]
        self.rows[0]['actual']['merchant'] = 'Example Merchant Pty Ltd'
        self.rows[0]['field_matches']['merchant'] = False
        self.rows[0]['auto_confirmed'] = True
        self.manifest = [{'id': r['id'], 'source': {'url': 'https://example.invalid/synthetic'},
                          'sha256': 'synthetic-only'} for r in self.rows]
        self.save('manifest', self.manifest)
        self.ev = {'complete': True, 'tested_count': 100, 'selected_count': 100, 'target_count': 100,
                   'results': self.rows, 'manifest_sha256': self.hash('manifest'),
                   'automatic': {'false_confirmations': ['synthetic_000'], 'unverified_confirmations': []}}
        self.save('evaluation', self.ev)
        self.dg = {'evaluation_source_sha256': self.hash('evaluation'),
                   'scope_ids': [r['id'] for r in self.rows],
                   'records': [{'id': r['id']} for r in self.rows],
                   'rules_references_predictions_unchanged': True,
                   'important_findings': [{'groups': {'same_brand_or_full_legal_name_variants': ['synthetic_000']}}],
                   'visual_auto_adjudications': [{'id': 'synthetic_000', 'original_reopened': True,
                       'strict_score_unchanged': True, 'actual_is_literal_printed_name': True,
                       'same_merchant_entity_observed': True, 'date_matches_original': True,
                       'total_matches_original': True, 'notes': 'Synthetic legal-name example <not HTML>.'}]}
        self.save('diagnosis', self.dg)
        self.original = (b'<!doctype html><title>SYNTHETIC TEST ONLY</title><main>'
                         b'<p>100 tested / 100 requested - Complete</p><div class="cards">'
                         b'<p>Original strict score: synthetic placeholder</p></div></main>')
        self.paths['primary'].write_bytes(self.original)
        # Signature-only placeholder: the publisher requires an existing XLSX,
        # but workbook format verification belongs to the workbook exporter.
        self.paths['workbook'].write_bytes(b'PK synthetic workbook test placeholder')

    def save(self, key, obj):
        self.paths[key].write_text(json.dumps(obj))

    def hash(self, key):
        return hashlib.sha256(self.paths[key].read_bytes()).hexdigest()

    def run_publisher(self):
        return publisher.publish(**self.paths)

    def test_preserves_raw_scores_manifest_and_inputs_and_is_idempotent(self):
        original_inputs = {k: self.paths[k].read_bytes() for k in ('evaluation', 'diagnosis', 'manifest')}
        report = self.run_publisher()
        self.assertEqual(self.paths['strict'].read_bytes(), self.original)
        self.assertEqual(self.paths['sources'].read_bytes(), original_inputs['manifest'])
        html = self.paths['primary'].read_text()
        start, end = html.index(publisher.START), html.index(publisher.END) + len(publisher.END) + 1
        self.assertEqual((html[:start] + html[end:]).encode(), self.original)
        self.assertIn('1 same-brand or full legal-name variants', html)
        self.assertIn('synthetic_000', html)
        self.assertIn('&lt;not HTML&gt;', html)
        self.assertIn('73%', html)
        self.assertIn('not independent human gold', html)
        self.assertIn('before their OCR predictions were inspected', html)
        self.assertIn('synthetic-strict.html', html)
        self.assertIn('synthetic-sources.json', html)
        self.assertIn('synthetic.xlsx', html)
        self.assertFalse(report['semantic_metric_computed'])
        snapshots = {key: (path.read_bytes(), path.stat().st_mtime_ns) for key, path in self.paths.items()}
        self.assertEqual(self.run_publisher(), report)
        for key, path in self.paths.items():
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), snapshots[key])
        for key, raw in original_inputs.items():
            self.assertEqual(self.paths[key].read_bytes(), raw)

    def test_partial_or_short_cohort_rejected_without_outputs(self):
        for change in ({'complete': False}, {'tested_count': 99}, {'selected_count': 99}):
            with self.subTest(change=change):
                self.save('evaluation', dict(self.ev, **change))
                with self.assertRaises(ValueError):
                    self.run_publisher()
                self.assertFalse(self.paths['strict'].exists())
                self.assertEqual(self.paths['primary'].read_bytes(), self.original)

    def test_stale_diagnosis_and_missing_auto_review_rejected(self):
        for alteration in ('hash', 'review', 'scope', 'groups'):
            with self.subTest(alteration=alteration):
                d = copy.deepcopy(self.dg)
                if alteration == 'hash': d['evaluation_source_sha256'] = 'stale'
                if alteration == 'review': d['visual_auto_adjudications'] = []
                if alteration == 'scope': d['scope_ids'] = d['scope_ids'][:-1]
                if alteration == 'groups': d['important_findings'][0]['groups']['extra'] = ['synthetic_000']
                self.save('diagnosis', d)
                with self.assertRaises(ValueError): self.run_publisher()
                self.assertFalse(self.paths['strict'].exists())

    def test_manifest_hash_and_workbook_required(self):
        self.paths['manifest'].write_bytes(self.paths['manifest'].read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'Manifest bytes'): self.run_publisher()
        self.save('manifest', self.manifest)
        self.paths['workbook'].unlink()
        with self.assertRaisesRegex(ValueError, 'XLSX'): self.run_publisher()
        self.assertFalse(self.paths['strict'].exists())

    def test_prior_original_and_modified_published_report_are_protected(self):
        self.paths['strict'].write_bytes(b'previous original')
        with self.assertRaisesRegex(ValueError, 'Existing strict report differs'): self.run_publisher()
        self.paths['strict'].unlink()
        self.run_publisher()
        self.paths['primary'].write_bytes(self.paths['primary'].read_bytes() + b'<!-- external edit -->')
        with self.assertRaisesRegex(ValueError, 'changed externally'): self.run_publisher()
        self.assertEqual(self.paths['strict'].read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
