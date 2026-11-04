import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from report_text import extract_report


class ReportTextTest(unittest.TestCase):
    def test_published_manifest_matches_deck(self):
        manifest = json.loads((ROOT / 'data/report.json').read_text(encoding='utf-8'))
        content = extract_report(ROOT / manifest['file'], manifest['date'], manifest['file'])
        self.assertEqual(content, manifest['content'])
        self.assertEqual(len(content['pages']), manifest['slides'])
        self.assertIn(manifest['title'], content['pages'][0]['text'])
        self.assertTrue(all(page['text'] for page in content['pages']))
        self.assertTrue(any(series['points'] for page in content['pages'] for series in page['charts']))

    def test_bad_deck_is_rejected(self):
        with self.assertRaises(FileNotFoundError):
            extract_report(ROOT / 'missing.pptx', '2026-01-01', 'missing.pptx')

if __name__ == '__main__':
    unittest.main()
