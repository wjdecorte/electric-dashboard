"""Local electricity dashboard with validated Amicalola statement imports."""
import csv
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
from datetime import datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit, parse_qs
import enrichment
import pdfplumber

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DATA_DIR', '/data'))
MAX_UPLOAD = 10 * 1024 * 1024
CATEGORIES = {'local_tax':'LOCALTAX','franchise_tax':'FRANCHISETAX','state_tax':'STATETAX',
              'membership_fee':'MEMBERSHIPFEE','service_charge':'SERVICECHARGE','total':'TOTALCURRENTBILL'}
ACCOUNT_HASH = json.loads((ROOT / 'account.json').read_text())['sha256'] if (ROOT / 'account.json').exists() else None

class ImportErrorValue(ValueError):
    pass

def connect():
    db = sqlite3.connect(DATA / 'statements.sqlite', timeout=30)
    db.row_factory = sqlite3.Row
    return db

def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    seed_rows = json.loads((ROOT / 'seed.json').read_text()) if (ROOT / 'seed.json').exists() else []
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS statements (end TEXT PRIMARY KEY, start TEXT NOT NULL, row_json TEXT NOT NULL, pdf BLOB, sha256 TEXT UNIQUE)')
        db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
        if not db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone():
            for row in seed_rows:
                db.execute('INSERT OR IGNORE INTO statements VALUES (?,?,?,?,?)', (row['end'], row['start'], json.dumps(row), None, None))
            db.execute("INSERT INTO metadata VALUES ('initialized','1')")
        if ACCOUNT_HASH and not db.execute("SELECT 1 FROM metadata WHERE key='account_hash'").fetchone():
            enrichment.set_meta(db,'account_hash',ACCOUNT_HASH)
        location = json.loads((ROOT / 'location.json').read_text()) if (ROOT / 'location.json').exists() else None
        enrichment.migrate(db,location)
        # Enrich existing installations with comparison service days from seed evidence.
        for seed in seed_rows:
            existing = db.execute('SELECT row_json FROM statements WHERE end=?', (seed['end'],)).fetchone()
            if existing:
                row = json.loads(existing['row_json'])
                if 'prior_year_days' not in row and row.get('prior_year_kwh') == seed.get('prior_year_kwh'):
                    row['prior_year_days'] = seed.get('prior_year_days', 0)
                    db.execute('UPDATE statements SET row_json=? WHERE end=?', (json.dumps(row),row['end']))


def rows():
    with connect() as db:
        return [dict(json.loads(r['row_json']), has_pdf=r['pdf'] is not None) for r in db.execute('SELECT * FROM statements ORDER BY end')]

def parse_pdf(raw, filename):
    if not raw.startswith(b'%PDF-'):
        raise ImportErrorValue('This file is not a PDF. Choose an original Amicalola EMC statement.')
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            if not 1 <= len(pdf.pages) <= 5:
                raise ImportErrorValue('Upload one statement at a time (up to 5 pages).')
            text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
    except ImportErrorValue:
        raise
    except Exception:
        raise ImportErrorValue('Cannot read this PDF. Use an unencrypted, original statement download.') from None
    if not text.strip():
        raise ImportErrorValue('This PDF has no readable text. Scanned statements need OCR before import.')
    compact = re.sub(r'\s+', '', text).upper()
    if 'AMICALOLA' not in compact:
        raise ImportErrorValue('This importer supports Amicalola EMC statements only.')
    # The account row immediately follows the statement account-heading row.
    account = re.search(r'ACCOUNTNUMBER[^\n]*\n\s*(\d{6,})\b', text.replace('ACCOUNT NUMBER','ACCOUNTNUMBER'))
    expected_hash = ACCOUNT_HASH or enrichment.meta('account_hash')
    if not account or (expected_hash and hashlib.sha256(account[1].encode()).hexdigest() != expected_hash):
        raise ImportErrorValue('This statement belongs to a different account, or its account cannot be verified.')
    pattern = r'(\d{2}/\d{2}/\d{2})\s+(\d{2}/\d{2}/\d{2})\s+(\d+)\s+([\d,]+)\s+([\d,]+)\s+(\d+)\s+([\d,]+)\s+([\d,]+\.\d{2})'
    matches = re.findall(pattern, text)
    if len(matches) != 1:
        raise ImportErrorValue('Could not identify one billing period. This statement layout is unsupported.')
    start, end, days, prev, present, multiplier, kwh, charge = matches[0]
    integer = lambda v: int(v.replace(',', ''))
    try:
        start = datetime.strptime(start, '%m/%d/%y').date()
        end = datetime.strptime(end, '%m/%d/%y').date()
    except ValueError:
        raise ImportErrorValue('The service dates could not be validated.') from None
    row = dict(source=filename, start=start.isoformat(), end=end.isoformat(), days=integer(days),
               previous_reading=integer(prev), present_reading=integer(present), multiplier=integer(multiplier),
               kwh=integer(kwh), electric_charge=float(Decimal(charge.replace(',',''))))
    if not 1 <= row['days'] <= 100 or (end-start).days != row['days']:
        raise ImportErrorValue('The service days do not match the billing period. Nothing was saved.')
    if (row['present_reading']-row['previous_reading'])*row['multiplier'] != row['kwh'] or row['kwh'] <= 0:
        raise ImportErrorValue('Meter readings do not match the stated kWh. Nothing was saved.')
    amounts = [Decimal(charge.replace(',', ''))]
    for key, label in CATEGORIES.items():
        found = re.findall(label+r'([\d,]+\.\d{2})', compact)
        if len(found) > 1 or (key in ('local_tax','franchise_tax','state_tax','total') and len(found) != 1):
            raise ImportErrorValue('The charge breakdown could not be read reliably. Nothing was saved.')
        amount = Decimal(found[0].replace(',','')) if found else Decimal(0)
        row[key] = float(amount)
        if key != 'total': amounts.append(amount)
    if sum(amounts) != Decimal(str(row['total'])):
        raise ImportErrorValue('The charge categories do not add up to the current bill. Nothing was saved.')
    for key,label in [('previous_period_kwh','PREVIOUSBILLINGPERIOD'),('prior_year_kwh','SAMEPERIODLASTYEAR')]:
        found = re.search(label+r'\s+\d+\s+([\d,]+)', re.sub(r'(?<=\w) (?=\w)', ' ', text).replace('PREVIOUS BILLING PERIOD','PREVIOUSBILLINGPERIOD').replace('SAME PERIOD LAST YEAR','SAMEPERIODLASTYEAR'))
        row[key] = integer(found[1]) if found else 0
    comparison = re.search(r'SAMEPERIODLASTYEAR\s+(\d+)\s+([\d,]+)', text.replace('SAME PERIOD LAST YEAR','SAMEPERIODLASTYEAR'))
    row['prior_year_days'] = int(comparison[1]) if comparison else 0
    row['_account_hash'] = hashlib.sha256(account[1].encode()).hexdigest()
    return row

def check_row(db, row, digest):
    if db.execute('SELECT 1 FROM statements WHERE sha256=?', (digest,)).fetchone():
        return 'duplicate'
    existing = db.execute('SELECT * FROM statements WHERE end=?', (row['end'],)).fetchone()
    if existing:
        saved = json.loads(existing['row_json'])
        fields = ['start','end','days','previous_reading','present_reading','multiplier','kwh','electric_charge',*CATEGORIES]
        if all(row[k] == saved[k] for k in fields):
            return 'duplicate'
        raise ImportErrorValue('A different statement already exists for this billing date. Existing data was kept.')
    if db.execute('SELECT 1 FROM statements WHERE start < ? AND end > ?', (row['end'], row['start'])).fetchone():
        raise ImportErrorValue('This billing period overlaps an existing statement. Existing data was kept.')
    return 'ready'

def import_pdf(raw, filename, save=False):
    filename = Path(filename.replace('\\','/')).name[:160]
    if not filename.lower().endswith('.pdf'): filename += '.pdf'
    row = parse_pdf(raw, filename)
    account_hash = row.pop('_account_hash', ACCOUNT_HASH)
    digest = hashlib.sha256(raw).hexdigest()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE' if save else 'BEGIN')
        current_account = db.execute("SELECT value FROM metadata WHERE key='account_hash'").fetchone()
        if current_account and account_hash and json.loads(current_account['value']) != account_hash:
            raise ImportErrorValue('This statement belongs to a different account. Nothing was saved.')
        status = check_row(db, row, digest)
        if save and status == 'ready':
            db.execute('INSERT INTO statements VALUES (?,?,?,?,?)', (row['end'],row['start'],json.dumps(row),raw,digest))
            if account_hash and not current_account: enrichment.set_meta(db,'account_hash',account_hash)
            status = 'imported'
        return dict(status=status,row=row)

enrichment.configure(connect, rows)

TEXT='; charset=utf-8'
ICON_CACHE='public, max-age=86400'
ASSETS={'/styles.css':('text/css'+TEXT,None),'/app.js':('text/javascript'+TEXT,None),'/charts.js':('text/javascript'+TEXT,None),
        '/manifest.webmanifest':('application/manifest+json'+TEXT,None),'/icon.svg':('image/svg+xml',ICON_CACHE),
        '/apple-touch-icon.png':('image/png',ICON_CACHE),'/icon-192.png':('image/png',ICON_CACHE),'/icon-512.png':('image/png',ICON_CACHE)}

class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def reply(self, status, payload, mime='application/json; charset=utf-8', headers=None):
        if isinstance(payload, (dict,list)): payload = json.dumps(payload).encode()
        if isinstance(payload,str): payload = payload.encode()
        self.send_response(status)
        for k,v in {'Content-Type':mime,'Content-Length':str(len(payload)), 'Cache-Control':'no-store',
                    'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'", **(headers or {})}.items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/dashboard': return self.reply(200,enrichment.dashboard())
        if path == '/api/location/search':
            try: return self.reply(200,enrichment.search_location(parse_qs(urlsplit(self.path).query).get('q',[''])[0]))
            except ValueError as error:return self.reply(422,{'error':str(error)})
            except Exception:return self.reply(502,{'error':'Location search is unavailable. Check NAS internet access and retry.'})
        if path in ASSETS:
            mime,cache=ASSETS[path]
            return self.reply(200,(ROOT/'static'/path[1:]).read_bytes(),mime,{'Cache-Control':cache} if cache else None)
        if path in ('/api/statements','/data.json'): return self.reply(200,rows())
        if path == '/health': return self.reply(200, {'status':'ok','version':enrichment.VERSION,'revision':os.environ.get('APP_REVISION','development')})
        if path == '/api/export.csv':
            values=rows(); f=io.StringIO(); keys=[k for k in values[0] if k!='has_pdf'] if values else []
            writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore'); writer.writeheader();writer.writerows({k: ("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in row.items()} for row in values)
            return self.reply(200,f.getvalue(),'text/csv; charset=utf-8',{'Content-Disposition':'attachment; filename="electric-statements.csv"'})
        if re.fullmatch(r'/api/pdf/\d{4}-\d{2}-\d{2}',path):
            with connect() as db: item=db.execute('SELECT pdf FROM statements WHERE end=?',(path.rsplit('/',1)[1],)).fetchone()
            if item and item['pdf']: return self.reply(200,item['pdf'],'application/pdf',{'Content-Disposition':'attachment; filename="statement.pdf"'})
            return self.reply(404,{'error':'Original PDF is not stored for this statement.'})
        if path == '/favicon.ico': return self.reply(200,(ROOT/'static/icon.svg').read_bytes(),'image/svg+xml')
        if path in ('/','/index.html'): return self.reply(200,(ROOT/'static/index.html').read_bytes(),'text/html; charset=utf-8')
        return self.reply(404,{'error':'Not found.'})

    def do_POST(self):
        allowed=('/api/preview','/api/import','/api/events','/api/events/delete','/api/settings','/api/weather/refresh')
        if self.path not in allowed: return self.reply(404,{'error':'Not found.'})
        origin=self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.reply(403,{'error':'Requests must come from this dashboard.'})
        is_pdf=self.path in ('/api/preview','/api/import')
        expected_type='application/pdf' if is_pdf else 'application/json'
        if self.headers.get('Content-Type','').split(';')[0] != expected_type:
            return self.reply(415,{'error':'Choose a PDF statement.' if is_pdf else 'Send valid event or settings data.'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0 < size <= (MAX_UPLOAD if is_pdf else 16384): return self.reply(413,{'error':'PDFs must be 10 MB or smaller; event details must be under 16 KB.'})
            raw=self.rfile.read(size)
            if len(raw) != size: raise ImportErrorValue('Upload was incomplete. Try again.')
            if is_pdf:
                result=import_pdf(raw,unquote(self.headers.get('X-Filename','statement.pdf')),save=self.path=='/api/import')
                if result['status']=='imported' and enrichment.meta('weather_location'):enrichment.refresh_weather()
                return self.reply(200,result)
            payload=json.loads(raw)
            if self.path=='/api/events':return self.reply(200,{'id':enrichment.save_event(payload)})
            if self.path=='/api/events/delete':
                enrichment.delete_event(payload.get('id'));return self.reply(200,{'deleted':True})
            if self.path=='/api/settings':
                location=enrichment.save_location(payload.get('location'));return self.reply(200,{'location':location})
            if self.path=='/api/weather/refresh':
                if not enrichment.meta('weather_location'):raise ValueError('Choose a weather location in Settings first.')
                return self.reply(202,{'started':enrichment.refresh_weather()})
        except (ImportErrorValue,ValueError,KeyError,TypeError,AttributeError) as error:
            self.reply(422,{'error':str(error) if isinstance(error,ValueError) else 'Check the entered fields and try again.'})
        except Exception:
            logging.exception('Request failed')
            self.reply(500,{'error':'Data could not be saved. Check NAS storage and container logs, then retry.'})

if __name__ == '__main__':
    initialize()
    if enrichment.meta('weather_location'):enrichment.refresh_weather()
    port=int(os.environ.get('PORT','8080'))
    print(f'Electric dashboard listening on {port}',flush=True)
    ThreadingHTTPServer((os.environ.get('BIND_HOST','0.0.0.0'),port),Handler).serve_forever()
