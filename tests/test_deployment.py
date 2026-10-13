import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
MOCK='''#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:];root=pathlib.Path(os.environ['MOCK_ROOT']);mode=os.environ['MOCK_MODE'];state=root/'running';rollback=bool(os.environ.get('ELECTRIC_IMAGE')=='electric-dashboard:rollback')
with (root/'calls').open('a') as f:f.write(json.dumps({'args':args,'rollback':rollback})+'\\n')
if args[0]=='compose':
 command=args[5:]
 if command[:2]==['config','--images']:print('ghcr.io/example/dashboard:latest')
 elif command[:1]==['ps']:print('new' if state.exists() else 'old')
 elif command[:1]==['up']:state.write_text('rollback' if rollback else 'new')
 elif command[:1]==['pull'] and mode=='pull-failure':sys.exit(1)
elif args[:2]==['image','inspect']:print('old-id' if mode=='unchanged' else 'new-id')
elif args[:1]==['inspect']:
 if args[2]=='{{.Image}}':print('old-id')
 else:print('unhealthy' if state.exists() and state.read_text()!='rollback' and mode=='unhealthy' else 'healthy')
elif args[:1]==['run'] and mode=='prepare-failure':sys.exit(1)
'''

class Deployment(unittest.TestCase):
    def run_update(self,mode):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'bin').mkdir();docker=root/'bin/docker';docker.write_text(MOCK);docker.chmod(0o755)
            shutil.copy2(ROOT/'update.sh',root/'update.sh');shutil.copy2(ROOT/'docker-compose.yml',root/'docker-compose.yml')
            environment=dict(os.environ,PATH=str(root/'bin')+os.pathsep+os.environ['PATH'],MOCK_ROOT=str(root),MOCK_MODE=mode)
            result=subprocess.run(['sh',str(root/'update.sh')],env=environment,text=True,capture_output=True,timeout=10)
            calls=[json.loads(line) for line in (root/'calls').read_text().splitlines()]
            self.assertFalse((root/'data/.update-lock').exists())
            return result,calls

    def test_unchanged_healthy_image_does_not_restart(self):
        result,calls=self.run_update('unchanged');self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(any('stop' in call['args'] for call in calls))

    def test_successful_pull_recreates_without_build(self):
        result,calls=self.run_update('healthy');self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(any('--force-recreate' in call['args'] for call in calls))
        self.assertFalse(any('build' in call['args'] for call in calls))

    def test_pull_failure_leaves_running_container_alone(self):
        result,calls=self.run_update('pull-failure');self.assertNotEqual(result.returncode,0)
        self.assertFalse(any('stop' in call['args'] for call in calls))

    def test_preparation_failure_restarts_previous_container(self):
        result,calls=self.run_update('prepare-failure');self.assertNotEqual(result.returncode,0)
        self.assertTrue(any('start' in call['args'] for call in calls))

    def test_unhealthy_update_rolls_back(self):
        result,calls=self.run_update('unhealthy');self.assertNotEqual(result.returncode,0)
        self.assertTrue(any(call['rollback'] and 'up' in call['args'] for call in calls))

    def test_private_bootstrap_and_backup_are_local_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';data=root/'data';(project/'app').mkdir(parents=True);data.mkdir()
            (project/'app/account.json').write_text(json.dumps({'sha256':'synthetic-hash'}));(project/'app/location.json').write_text(json.dumps({'name':'Synthetic city'}))
            with sqlite3.connect(data/'statements.sqlite') as db:
                db.execute('CREATE TABLE evidence (value TEXT)');db.execute("INSERT INTO evidence VALUES ('preserve')")
            subprocess.run(['python3',str(ROOT/'scripts/prepare_data.py'),str(project),str(data)],check=True,capture_output=True)
            with sqlite3.connect(data/'statements.sqlite') as db:
                self.assertEqual(db.execute('SELECT value FROM evidence').fetchone()[0],'preserve')
                self.assertEqual(json.loads(db.execute("SELECT value FROM metadata WHERE key='account_hash'").fetchone()[0]),'synthetic-hash')
            self.assertEqual(len(list((data/'backups').glob('*.sqlite'))),1)

if __name__=='__main__':unittest.main()
