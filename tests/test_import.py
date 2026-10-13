import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from types import SimpleNamespace
import hashlib

os.environ['DATA_DIR']=tempfile.mkdtemp()
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('server',root/'app/server.py')
server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)

class Imports(unittest.TestCase):
    def setUp(self):
        server.DATA=Path(tempfile.mkdtemp());server.initialize()
        self.row=dict(json.loads((root/'app/seed.json').read_text())[-1])
        self.row.update(start='2026-09-09',end='2026-10-09',previous_reading=83259,present_reading=84567,source='new.pdf')

    def test_import_persistence_and_duplicate(self):
        with patch.object(server,'parse_pdf',return_value=self.row):
            self.assertEqual(server.import_pdf(b'new','new.pdf')['status'],'ready')
            self.assertEqual(len(server.rows()),14)
            self.assertEqual(server.import_pdf(b'new','new.pdf',True)['status'],'imported')
            server.initialize()
            self.assertEqual(len(server.rows()),15)
            self.assertEqual(server.import_pdf(b'new','new.pdf',True)['status'],'duplicate')
            with server.connect() as db:
                self.assertEqual(db.execute('SELECT pdf FROM statements WHERE end=?',(self.row['end'],)).fetchone()['pdf'],b'new')

    def test_conflict_and_overlap_keep_data(self):
        conflict=dict(self.row,end='2026-09-09')
        with patch.object(server,'parse_pdf',return_value=conflict):
            with self.assertRaises(server.ImportErrorValue):server.import_pdf(b'conflict','x.pdf',True)
        overlap=dict(self.row,start='2026-09-08')
        with patch.object(server,'parse_pdf',return_value=overlap):
            with self.assertRaises(server.ImportErrorValue):server.import_pdf(b'overlap','x.pdf',True)
        self.assertEqual(len(server.rows()),14)

    def test_parser_checks_account_meter_and_bill(self):
        text='\n'.join(['Amicalola Electric Membership Corporation','ACCOUNTNUMBER ACCOUNTNAME','1234567890 TEST','09/09/26 10/09/26 30 83259 84567 1 1308 187.01','LOCAL TAX 5.61','FRANCHISE TAX 7.48','STATE TAX 7.48','TOTAL CURRENT BILL 207.58','PREVIOUS BILLING PERIOD 30 1308 44','SAME PERIOD LAST YEAR 29 903 31'])
        def parse(value):
            pdf=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda:value)])
            with patch.object(server.pdfplumber,'open',return_value=nullcontext(pdf)):
                return server.parse_pdf(b'%PDF-test','test.pdf')
        with patch.object(server,'ACCOUNT_HASH',hashlib.sha256(b'1234567890').hexdigest()):
            row=parse(text)
            self.assertEqual(row['kwh'],1308)
            self.assertEqual(row['prior_year_kwh'],903)
            for altered in [text.replace('207.58','208.58'),text.replace('84567','84568'),text.replace('1234567890','1234567891'),text.replace('30 83259','29 83259')]:
                with self.assertRaises(server.ImportErrorValue):parse(altered)

    def test_invalid_pdf_rejected(self):
        with self.assertRaises(server.ImportErrorValue):server.import_pdf(b'not a PDF','x.pdf',True)
        self.assertEqual(len(server.rows()),14)

if __name__=='__main__':unittest.main()
