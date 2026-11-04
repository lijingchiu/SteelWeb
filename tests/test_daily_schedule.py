import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import daily_schedule as schedule
import notify


class ScheduleTest(unittest.TestCase):
    def test_weekday_window_and_completed_research(self):
        tw = timezone(timedelta(hours=8))
        pending = {'analysis': False, 'research': False, 'report': False, 'notifications': False}
        complete = dict.fromkeys(pending, True)
        for hour in range(8):
            self.assertTrue(schedule.allow_scheduled(datetime(2026, 11, 9, hour, tzinfo=tw), pending))
            self.assertFalse(schedule.allow_scheduled(datetime(2026, 11, 9, hour, tzinfo=tw), complete))
        self.assertFalse(schedule.allow_scheduled(datetime(2026, 11, 9, 8, tzinfo=tw), pending))
        self.assertFalse(schedule.allow_scheduled(datetime(2026, 11, 8, 0, tzinfo=tw), pending))
        self.assertFalse(schedule.allow_scheduled(datetime(2026, 11, 14, 7, tzinfo=tw), pending))

    def test_delivery_is_never_early(self):
        tw = timezone(timedelta(hours=8))
        for minute in (0, 58, 59):
            now = datetime(2026, 11, 9, 6, minute, tzinfo=tw)
            self.assertEqual(notify.delivery_at(now, '07:00'), datetime(2026, 11, 9, 7, tzinfo=tw))
        self.assertIsNone(notify.delivery_at(datetime(2026, 11, 9, 7, tzinfo=tw), '07:00'))

    def test_state_requires_today_valid_files_and_both_notifications(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'data/history').mkdir(parents=True)
            (root/'reports').mkdir()
            today = '2026-11-09'
            def write(name, obj):
                (root/name).write_text(json.dumps(obj))
            write('data/latest.json', {'date': today})
            write(f'data/history/{today}.json', {'date': today})
            write('data/materials.json', {'items': [{'id': 'a'}]})
            write('data/material-outlooks.json', {'generated_at': today+'T01:00:00+08:00', 'failed_batches': 0, 'total_items': 1, 'covered_items': 1})
            stem = f'reports/steel-daily-{today}'
            for ext in ('.pptx', '.pdf'):
                (root/(stem+ext)).write_bytes(b'report')
            digest = hashlib.sha256(b'report').hexdigest()
            write('data/report.json', {'date': today, 'file': stem+'.pptx', 'pdf_file': stem+'.pdf', 'content': {'sha256': digest}, 'pdf_sha256': digest})
            write('data/notify-state.json', {'push': {'date': today}, 'email': {'date': today}})
            self.assertTrue(all(schedule.status(root, today).values()))
            write('data/notify-state.json', {'push': {'date': today}})
            self.assertFalse(schedule.status(root, today)['notifications'])
            write('data/material-outlooks.json', {'generated_at': today+'T01:00:00+08:00', 'failed_batches': 1, 'total_items': 1, 'covered_items': 1})
            self.assertFalse(schedule.status(root, today)['research'])
            (root/(stem+'.pdf')).write_bytes(b'broken')
            self.assertFalse(schedule.status(root, today)['report'])

if __name__ == '__main__':
    unittest.main()
