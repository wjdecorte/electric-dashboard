import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOCK = """#!/usr/bin/env python3
import json,os,pathlib,sys
args=sys.argv[1:];root=pathlib.Path(os.environ['MOCK_ROOT']);mode=os.environ['MOCK_MODE'];state=root/'running';rollback=bool(os.environ.get('ELECTRIC_IMAGE')=='electric-dashboard:rollback')
with (root/'calls').open('a') as f:f.write(json.dumps({'args':args,'rollback':rollback})+'\\n')
if args[0]=='compose':
 command=args[5:]
 if command[:2]==['config','--images']:print('ghcr.io/example/dashboard:latest')
 elif command[:1]==['ps']:print('db-id' if command[-1]=='db' else 'new' if state.exists() else 'old')
 elif command[:1]==['up'] and command[-1]!='db':state.write_text('rollback' if rollback else 'new')
 elif command[:1]==['exec']:
  if mode=='backup-failure':sys.exit(1)
  print('PGDMP-fake')
 elif command[:1]==['run'] and mode=='prepare-failure':sys.exit(1)
 elif command[:1]==['pull'] and mode=='pull-failure':sys.exit(1)
elif args[:2]==['image','inspect']:print('old-id' if mode=='unchanged' else 'new-id')
elif args[:1]==['inspect']:
 if args[2]=='{{.Image}}':print('old-id')
 elif args[3]=='db-id':print('healthy')
 else:print('unhealthy' if state.exists() and state.read_text()!='rollback' and mode=='unhealthy' else 'healthy')
"""


class Deployment(unittest.TestCase):
    def run_update(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            docker = root / "bin/docker"
            docker.write_text(MOCK)
            docker.chmod(0o755)
            shutil.copy2(ROOT / "update.sh", root / "update.sh")
            shutil.copy2(ROOT / "docker-compose.yml", root / "docker-compose.yml")
            environment = dict(
                os.environ,
                PATH=str(root / "bin") + os.pathsep + os.environ["PATH"],
                MOCK_ROOT=str(root),
                MOCK_MODE=mode,
            )
            result = subprocess.run(
                ["sh", str(root / "update.sh")],
                env=environment,
                text=True,
                capture_output=True,
                timeout=10,
            )
            calls = [json.loads(line) for line in (root / "calls").read_text().splitlines()]
            self.assertFalse((root / "data/.update-lock").exists())
            return result, calls

    def test_unchanged_healthy_image_does_not_restart(self):
        result, calls = self.run_update("unchanged")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("stop" in call["args"] for call in calls))

    def test_successful_pull_recreates_without_build(self):
        result, calls = self.run_update("healthy")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("--force-recreate" in call["args"] for call in calls))
        self.assertFalse(any("build" in call["args"] for call in calls))

    def test_pull_failure_leaves_running_container_alone(self):
        result, calls = self.run_update("pull-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any("stop" in call["args"] for call in calls))

    def test_preparation_failure_restarts_previous_container(self):
        result, calls = self.run_update("prepare-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("start" in call["args"] for call in calls))

    def test_unhealthy_update_rolls_back(self):
        result, calls = self.run_update("unhealthy")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any(call["rollback"] and "up" in call["args"] for call in calls))

    def test_backup_failure_restarts_previous_container_before_preparing_data(self):
        result, calls = self.run_update("backup-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("start" in call["args"] for call in calls))
        self.assertFalse(any("run" in call["args"] for call in calls))

    def test_database_is_backed_up_after_the_app_stops_and_before_recreation(self):
        result, calls = self.run_update("healthy")
        self.assertEqual(result.returncode, 0, result.stderr)
        verbs = [call["args"][5] for call in calls if call["args"][0] == "compose"]
        self.assertLess(verbs.index("stop"), verbs.index("exec"))
        self.assertLess(verbs.index("exec"), verbs.index("run"))
        self.assertLess(verbs.index("run"), len(verbs) - 1 - verbs[::-1].index("up"))


if __name__ == "__main__":
    unittest.main()
