import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
import notify
from wait_report_public import public_files_match


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self.report=json.loads((ROOT/'data/report.json').read_text(encoding='utf-8'))
        self.data=json.loads((ROOT/'data/latest.json').read_text(encoding='utf-8'))
        self.base='https://lijingchiu.github.io/SteelWeb/'

    def test_email_has_two_matching_download_links(self):
        body=notify.build_email(self.data,{},self.base,self.report)['body']
        self.assertIn(self.base+self.report['file'],body)
        self.assertIn(self.base+self.report['pdf_file'],body)
        self.assertIn('下載 PPTX',body); self.assertIn('下載 PDF',body)
        old=dict(self.report,date='2000-01-01')
        self.assertNotIn('下載 PPTX',notify.build_email(self.data,{},self.base,old)['body'])
        unsafe=dict(self.report,pdf_file='reports/../other.pdf')
        self.assertNotIn('下載 PDF',notify.build_email(self.data,{},self.base,unsafe)['body'])

    def test_exact_public_file_hash_required(self):
        expected=[('reports/test.pdf',hashlib.sha256(b'correct').hexdigest())]
        class Response:
            ok=True
            def __init__(self,body): self.content=body
        self.assertTrue(public_files_match(self.base,expected,lambda *a,**k:Response(b'correct')))
        self.assertFalse(public_files_match(self.base,expected,lambda *a,**k:Response(b'old')))

    def test_email_waits_for_public_files(self):
        date=self.data['date']; tz=timezone(timedelta(hours=8))
        now=datetime.fromisoformat(date+'T10:00:00').replace(tzinfo=tz)
        with tempfile.TemporaryDirectory() as d:
            tmp=Path(d); config=tmp/'config.json'; latest=tmp/'latest.json'; state=tmp/'state.json'; report=tmp/'report.json'
            config.write_text(json.dumps({'site_url':self.base,'buttondown_username':'test'}))
            latest.write_text(json.dumps(self.data,ensure_ascii=False)); report.write_text(json.dumps(self.report,ensure_ascii=False));state.write_text('{}')
            with patch.object(notify,'CONFIG_PATH',config),patch.object(notify,'LATEST_PATH',latest),patch.object(notify,'STATE_PATH',state),patch.object(notify,'REPORT_PATH',report),patch.dict(os.environ,{'BUTTONDOWN_API_KEY':'test','REPORT_PUBLIC_READY':'false'}),patch.object(notify,'send_email') as send:
                self.assertEqual(notify.main(now),1);send.assert_not_called()
            with patch.object(notify,'CONFIG_PATH',config),patch.object(notify,'LATEST_PATH',latest),patch.object(notify,'STATE_PATH',state),patch.object(notify,'REPORT_PATH',report),patch.dict(os.environ,{'BUTTONDOWN_API_KEY':'test','REPORT_PUBLIC_READY':'true'}),patch.object(notify,'send_email',return_value={'id':'example','scheduled':None}) as send:
                self.assertEqual(notify.main(now),0); self.assertEqual(send.call_count,1)
                self.assertIn('下載 PDF',send.call_args.args[1]['body'])

if __name__=='__main__': unittest.main()
