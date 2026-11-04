import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import daily_schedule as schedule
import notify


class ScheduleTest(unittest.TestCase):
    def test_offset_schedules_target_the_next_workday(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/daily-analysis.yml').read_text()
        self.assertIn("cron: '53 15 * * 0-4'", workflow)
        self.assertIn("cron: '47 16-22 * * 0-4'", workflow)
        tw = timezone(timedelta(hours=8))
        incomplete = dict.fromkeys(('analysis', 'research', 'report', 'notifications'), False)
        complete = dict.fromkeys(incomplete, True)
        for offset in range(14):
            target = datetime(2026, 11, 9, tzinfo=tw) + timedelta(days=offset)
            first = target - timedelta(minutes=7)
            times = [first] + [target.replace(hour=hour, minute=47) for hour in range(7)]
            for moment in times:
                self.assertEqual(schedule.target_date(moment), target.date())
                self.assertEqual(schedule.allow_scheduled(moment, incomplete), target.weekday() < 5)
                self.assertFalse(schedule.allow_scheduled(moment, complete))

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

    def test_previous_evening_targets_next_workday(self):
        tw = timezone(timedelta(hours=8))
        incomplete = dict.fromkeys(('analysis', 'research', 'report', 'notifications'), False)
        sunday = datetime(2026, 11, 8, 23, 50, tzinfo=tw)
        self.assertEqual(schedule.target_date(sunday).isoformat(), '2026-11-09')
        self.assertTrue(schedule.allow_scheduled(sunday, incomplete))
        self.assertFalse(schedule.allow_scheduled(datetime(2026, 11, 13, 23, 50, tzinfo=tw), incomplete))
        self.assertFalse(schedule.allow_scheduled(datetime(2026, 11, 8, 23, 49, tzinfo=tw), incomplete))
        target = notify.delivery_at(sunday, '07:00', '2026-11-09')
        self.assertEqual(target, datetime(2026, 11, 9, 7, tzinfo=tw))

    def test_delivery_is_never_early(self):
        tw = timezone(timedelta(hours=8))
        for minute in (0, 58, 59):
            now = datetime(2026, 11, 9, 6, minute, tzinfo=tw)
            self.assertEqual(notify.delivery_at(now, '07:00'), datetime(2026, 11, 9, 7, tzinfo=tw))
        self.assertIsNone(notify.delivery_at(datetime(2026, 11, 9, 7, tzinfo=tw), '07:00'))

    def test_next_day_notifications_are_scheduled_for_seven(self):
        tw = timezone(timedelta(hours=8))
        now = datetime(2026, 11, 8, 23, 58, tzinfo=tw)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config, latest, state, report = (root / x for x in ('config', 'latest', 'state', 'report'))
            config.write_text(json.dumps({'onesignal_app_id': 'x', 'buttondown_username': 'x', 'delivery_time': '07:00'}))
            latest.write_text(json.dumps({'date': '2026-11-09'}))
            state.write_text('{}')
            report.write_text('{}')
            env = {'RESEARCH_DATE': '2026-11-09', 'ONESIGNAL_REST_API_KEY': 'x', 'BUTTONDOWN_API_KEY': 'x', 'REPORT_PUBLIC_READY': 'true'}
            with patch.object(notify, 'CONFIG_PATH', config), patch.object(notify, 'LATEST_PATH', latest), patch.object(notify, 'STATE_PATH', state), patch.object(notify, 'REPORT_PATH', report), patch.dict('os.environ', env), patch.object(notify, 'local_report_ready', return_value=True), patch.object(notify, 'send_push', return_value={'id': 'p'} ) as push, patch.object(notify, 'send_email', return_value={'id': 'e'}) as email:
                self.assertEqual(notify.main(now), 0)
                expected = datetime(2026, 11, 9, 7, tzinfo=tw)
                self.assertEqual(push.call_args.args[-1], expected)
                self.assertEqual(email.call_args.args[-1], expected)
                self.assertEqual(json.loads(state.read_text())['email']['date'], '2026-11-09')

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
            write('data/material-outlooks.json', {'generated_at': '2026-11-08T23:55:00+08:00', 'research_date': today, 'failed_batches': 0, 'total_items': 1, 'covered_items': 1})
            self.assertTrue(schedule.status(root, today)['research'])
            write('data/notify-state.json', {'push': {'date': today}})
            self.assertFalse(schedule.status(root, today)['notifications'])
            write('data/material-outlooks.json', {'generated_at': today+'T01:00:00+08:00', 'failed_batches': 1, 'total_items': 1, 'covered_items': 1})
            self.assertFalse(schedule.status(root, today)['research'])
            (root/(stem+'.pdf')).write_bytes(b'broken')
            self.assertFalse(schedule.status(root, today)['report'])

if __name__ == '__main__':
    unittest.main()
