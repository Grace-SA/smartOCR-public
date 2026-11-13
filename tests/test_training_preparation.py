import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from scripts.prepare_receipt_training import prepare


class TrainingPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        self.rows = []
        for i, split in enumerate(('train', 'train', 'validation', 'validation', 'holdout')):
            path = self.root / 'data' / f'image{i}.png'
            Image.new('RGB', (12, 12), (i * 40, 10, 10)).save(path)
            row = {'id': f'r{i}', 'split': split, 'local_path': str(path.relative_to(self.root)),
                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                   'group_review': 'human_verified', 'merchant_group': f'm{i}',
                   'template_group': f't{i}', 'transaction_group': f'x{i}'}
            if split != 'holdout':
                row.update(label_review='human_verified',
                           labels={'merchant': '测试店铺', 'date': '2026-01-01', 'total': '-12.50'},
                           evidence={'merchant': '测试店铺', 'date': '01/01/2026', 'total': 'REFUND 12.50'})
                if i in (1, 3):
                    row['labels']['total'] = row['evidence']['total'] = None
            self.rows.append(row)

    def run_prepare(self, rows=None, out='data/prepared'):
        path = self.root / 'data' / 'manifest.json'
        path.write_text(json.dumps({'schema_version': 1, 'records': self.rows if rows is None else rows}))
        return prepare(path, out, self.root)

    def rejects(self, change):
        rows = copy.deepcopy(self.rows)
        change(rows)
        with self.assertRaises((ValueError, KeyError)):
            self.run_prepare(rows)
        self.assertFalse((self.root / 'data/prepared').exists())

    def test_private_exports_and_holdout_exclusion(self):
        report = self.run_prepare()
        self.assertFalse(report['training_executed'])
        self.assertFalse(report['accuracy_measured'])
        out = self.root / 'data/prepared'
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['preparation.json', 'train.jsonl', 'validation.jsonl'])
        training = [json.loads(line) for line in (out / 'train.jsonl').read_text().splitlines()]
        self.assertEqual([r['id'] for r in training], ['r0', 'r1'])
        self.assertNotIn('r4', (out / 'train.jsonl').read_text())
        target = json.loads(training[0]['messages'][1]['content'])
        self.assertEqual(target['merchant'], '测试店铺')
        self.assertEqual(target['total'], '-12.50')

    def test_no_overwrite_and_deterministic_exports(self):
        first = self.run_prepare()
        with self.assertRaises(FileExistsError):
            self.run_prepare()
        second = self.run_prepare(out='data/second')
        self.assertEqual(first, second)

    def test_rejects_cross_split_groups(self):
        for field in ('merchant_group', 'template_group', 'transaction_group'):
            with self.subTest(field=field):
                self.rejects(lambda rows: rows[4].update({field: ' ' + rows[0][field].upper() + ' '}))

    def test_rejects_unreviewed_groups_and_labels(self):
        self.rejects(lambda rows: rows[0].update(group_review='provisional'))
        self.rejects(lambda rows: rows[0].update(label_review='assistant_verified'))

    def test_rejects_changed_image_hash(self):
        self.rejects(lambda rows: rows[0].update(sha256='0' * 64))

    def test_rejects_duplicate_pixels_even_in_train(self):
        self.rejects(lambda rows: rows[1].update(local_path=rows[0]['local_path'], sha256=rows[0]['sha256']))

    def test_holdout_labels_never_enter_preparation(self):
        self.rejects(lambda rows: rows[4].update(labels={'merchant': 'secret answer'}))

    def test_requires_nonempty_split_and_controls(self):
        self.rejects(lambda rows: rows.pop())
        def remove_training_control(rows):
            rows[1]['labels']['total'] = '12.50'
            rows[1]['evidence']['total'] = 'TOTAL 12.50'
        self.rejects(remove_training_control)
        with self.assertRaises(ValueError):
            self.run_prepare([])

    def test_requires_evidence_and_exact_label_schema(self):
        self.rejects(lambda rows: rows[0]['evidence'].update(total=None))
        self.rejects(lambda rows: rows[0]['labels'].update(account_number='never export'))
        self.rejects(lambda rows: rows[0]['labels'].update(date='2026-02-30'))
        self.rejects(lambda rows: rows[0]['labels'].update(total=12.50))
        self.rejects(lambda rows: rows[0]['labels'].update(total='NaN'))

    def test_rejects_path_escape_and_tracked_outputs(self):
        self.rejects(lambda rows: rows[0].update(local_path='../outside.png'))
        with self.assertRaises(ValueError):
            self.run_prepare(out='exports')

    def test_rejects_duplicate_ids(self):
        self.rejects(lambda rows: rows[1].update(id=rows[0]['id']))

    def test_symlink_escape(self):
        external = self.root / 'external'
        external.mkdir()
        (self.root / 'data/link').symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_prepare(out='data/link/prepared')

    def test_decodes_verified_bytes_without_reopening_source(self):
        original_open = Image.open
        def require_buffer(source, *args, **kwargs):
            self.assertTrue(hasattr(source, 'read'))
            return original_open(source, *args, **kwargs)
        with patch('scripts.prepare_receipt_training.Image.open', side_effect=require_buffer):
            self.run_prepare()


if __name__ == '__main__':
    unittest.main()
