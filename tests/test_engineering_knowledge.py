import json
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prompts

class EngineeringKnowledgeTests(unittest.TestCase):
    def test_sources_and_connections(self):
        data = json.loads((ROOT / 'data/engineering-knowledge/index.json').read_text(encoding='utf-8'))
        cards = data['cards']
        ids = {card['id'] for card in cards}
        self.assertEqual(len(ids), len(cards))
        self.assertGreaterEqual(len(cards), 20)
        self.assertTrue({'水土保持', '大地工程', '土木結構', '鋼結構與鋼材'} <= {c['field'] for c in cards})
        for card in cards:
            self.assertEqual(urlparse(card['url']).scheme, 'https')
            for field in ('title', 'organization', 'summary', 'reviewed', 'keywords'):
                self.assertTrue(card[field], (card['id'], field))
        for edge in data['connections']:
            self.assertIn(edge['from'], ids)
            self.assertIn(edge['to'], ids)
            self.assertTrue(edge['relationship'])

    def test_research_requires_verification(self):
        prompt = prompts.research_prompt(date_str='2026-11-04', week_label='下週', week_range='test',
            official_prices='', fx='', base_rates='', links='', materials='', news='',
            professional_sources='土木｜測試來源｜https://example.gov.tw/')
        self.assertIn('<professional_sources>', prompt)
        self.assertIn('https://example.gov.tw/', prompt)
        self.assertIn('不是已查證的當日事實', prompt)
        self.assertIn('須實際查閱來源', prompt)

if __name__ == '__main__':
    unittest.main()
