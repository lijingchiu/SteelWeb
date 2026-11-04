import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from report_pdf import convert_report_pdf
from report_text import extract_report


class ReportPdfTest(unittest.TestCase):
    def test_published_formats_match_and_convert(self):
        report=json.loads((ROOT/'data/report.json').read_text(encoding='utf-8'))
        pptx=ROOT/report['file']; pdf=ROOT/report['pdf_file']
        self.assertEqual(extract_report(pptx,report['date'],report['file']),report['content'])
        self.assertEqual(len(PdfReader(pdf).pages),report['slides'])
        output=os.environ.get('TEST_PDF_OUTPUT')
        with tempfile.TemporaryDirectory() as d:
            rendered=Path(output) if output else Path(d)/'converted.pdf'
            convert_report_pdf(pptx,rendered,report['slides'],report['title'])
            cover=''.join(PdfReader(rendered).pages[0].extract_text().split())
            self.assertIn(''.join(report['title'].split()),cover)
            self.assertIn('鋼市每日快報',cover)

    def test_invalid_pdf_is_not_published(self):
        report=json.loads((ROOT/'data/report.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as d:
            target=Path(d)/'report.pdf';target.write_bytes(b'original')
            with self.assertRaisesRegex(RuntimeError,'PDF 驗證失敗'):
                convert_report_pdf(ROOT/report['file'],target,report['slides']+1,report['title'])
            self.assertEqual(target.read_bytes(),b'original')

if __name__=='__main__': unittest.main()
