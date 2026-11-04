import sys
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from material_research import validate, batches

class ResearchValidationTest(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 11, 4)
        self.items = [{'id':'copper', 'period':'2026-10', 'value':100, 'unit':'元', 'freq':'月'}]
        self.source = {'url':'https://example.com/news?id=1', 'title':'銅價消息'}
        self.response = {'output':[{'type':'web_search_call','action':{'sources':[self.source]}}]}
        self.row = {'id':'copper','direction':'uncertain','reason':'銅的最新供應消息影響市場，但未來價格仍有不確定性。','risk':'需求變化可能改變方向。',
                    'sources':[{'url':self.source['url'],'title':'銅價消息','published':'2026-11-03','fact':'近期銅市場供應情況發生變化。'}]}
    def check(self):
        return validate({'items':[self.row]}, self.response, self.items, self.day)
    def test_accepts_traced_fresh_source(self):
        self.assertEqual(self.check()['copper']['baseline_value'], 100)
    def test_rejects_uncited_old_or_future_sources(self):
        self.row['sources'][0]['url'] = 'https://unseen.example/fiction'
        self.assertFalse(self.check())
        self.row['sources'][0]['url'] = self.source['url']
        for published in ('2026-08-01', '2026-11-05', 'unknown'):
            self.row['sources'][0]['published'] = published
            self.assertFalse(self.check())
    def test_rejects_unsupported_or_stale(self):
        self.row['direction'] = 'certain'
        self.assertFalse(self.check())
        self.row['direction'] = 'up'
        self.items[0]['stale'] = True
        self.assertFalse(self.check())
    def test_batches_preserve_all_groups_and_exclude_stale(self):
        items = [{'id':str(i),'group':'a' if i<9 else 'b','stale':i==1} for i in range(12)]
        batches_out = batches(items, size=4)
        self.assertEqual(sum(map(len, batches_out)), 11)
        self.assertTrue(all(len({x['group'] for x in batch}) == 1 for batch in batches_out))

if __name__ == '__main__': unittest.main()
