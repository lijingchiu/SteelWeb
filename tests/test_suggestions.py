import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from suggestions import make_suggestions, FALLBACK

class SuggestionsTests(unittest.TestCase):
    def test_real_price_and_forecast_are_kept_distinct(self):
        d = {'date': '2026-11-04', 'taiwan_prices': {
            'fengxing_rebar_price': {'value': 18500, 'mom_change': 200, 'unit': '元/公噸', 'month': '2026-10'},
            'north_scrap_price': {'value': 10, 'mom_change': 0, 'unit': '元/公斤', 'month': '2026-10'},
        }, 'price_forecast': {'items': {'fengxing_rebar_price': {'next_month': {'direction': 'down'}}},
                             'targets': {'fengxing_rebar_price': {'target_month': '2026-11'}}}}
        s = make_suggestions(d)
        self.assertEqual(len(s), 4)
        self.assertIn('2026年10月', s[0])
        self.assertIn('上漲200元/公噸', s[0])
        self.assertIn('網站預測2026年11月', s[1])
        self.assertIn('偏跌', s[1])

    def test_missing_stale_and_invalid_data_do_not_imply_a_move(self):
        self.assertEqual(make_suggestions(None), FALLBACK)
        d = {'date': '2026-11-04', 'taiwan_prices': {'h_beam_price': {
            'value': 38000, 'mom_change': 1000, 'unit': '元/公噸', 'month': '2026-10', 'stale': True}}}
        self.assertFalse(any('上漲' in q or '下跌' in q for q in make_suggestions(d)))
        d['taiwan_prices']['h_beam_price']['stale'] = False
        d['taiwan_prices']['h_beam_price']['month'] = '2026-99'
        self.assertFalse(any('上漲' in q or '下跌' in q for q in make_suggestions(d)))

    def test_day_changes_rotation(self):
        a = make_suggestions({'date': '2026-11-04'})
        b = make_suggestions({'date': '2026-11-05'})
        self.assertNotEqual(a, b)

if __name__ == '__main__':
    unittest.main()
