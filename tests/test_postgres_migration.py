import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import database  # noqa: E402

STATEMENT = dict(start="2025-08-10", end="2025-09-09", days=30, kwh=1042, total=190.5)


def build_legacy(path):
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE statements (end TEXT PRIMARY KEY, start TEXT NOT NULL, row_json TEXT NOT NULL,"
            " pdf BLOB, sha256 TEXT UNIQUE)"
        )
        db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        db.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, start TEXT NOT NULL, end TEXT NOT NULL,"
            " title TEXT NOT NULL, category TEXT NOT NULL, notes TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE weather (location_key TEXT NOT NULL, day TEXT NOT NULL, mean REAL NOT NULL,"
            " low REAL NOT NULL, high REAL NOT NULL, fetched_at TEXT NOT NULL,"
            " PRIMARY KEY(location_key, day))"
        )
        db.execute(
            "INSERT INTO statements VALUES (?,?,?,?,?)",
            ("2025-09-09", "2025-08-10", json.dumps(STATEMENT), b"%PDF-legacy", "abc123"),
        )
        db.execute("INSERT INTO metadata VALUES ('initialized', '1')")
        db.execute("INSERT INTO metadata VALUES ('account_hash', ?)", (json.dumps("hash-1"),))
        db.execute(
            "INSERT INTO events VALUES (7, '2025-08-20', '2025-08-27', 'Trip', 'Vacation', 'Away',"
            " '2025-08-28T12:00:00+00:00')"
        )
        db.execute(
            "INSERT INTO weather VALUES ('1,2,UTC', '2025-08-10', 70.5, 60, 80,"
            " '2025-08-11T00:00:00+00:00')"
        )


class LegacyImport(unittest.TestCase):
    def setUp(self):
        pg.reset_database()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.legacy = Path(self.temp.name) / "statements.sqlite"
        build_legacy(self.legacy)
        with database.connect() as db:
            database.create_schema(db)

    def test_copies_every_table_and_keeps_pdf_bytes(self):
        with database.connect() as db:
            counts = database.import_legacy_sqlite(db, self.legacy)
        self.assertEqual(counts, dict(metadata=2, statements=1, events=1, weather=1))
        with database.connect() as db:
            statement = db.execute("SELECT * FROM statements").fetchone()
            self.assertEqual(statement["row_json"], STATEMENT)
            self.assertEqual(bytes(statement["pdf"]), b"%PDF-legacy")
            self.assertEqual(str(statement["period_end"]), "2025-09-09")
            event = db.execute("SELECT * FROM events").fetchone()
            self.assertEqual((event["id"], event["title"]), (7, "Trip"))
            self.assertEqual(db.execute("SELECT mean FROM weather").fetchone()["mean"], 70.5)
            self.assertEqual(
                db.execute("SELECT value FROM metadata WHERE key='account_hash'").fetchone()[
                    "value"
                ],
                "hash-1",
            )

    def test_new_events_continue_after_imported_ids(self):
        with database.connect() as db:
            database.import_legacy_sqlite(db, self.legacy)
            new_id = db.execute(
                "INSERT INTO events (start_date, end_date, title, category, notes, updated_at)"
                " VALUES ('2025-10-01', '2025-10-01', 'Guests', 'Guests', '', now()) RETURNING id"
            ).fetchone()["id"]
        self.assertEqual(new_id, 8)

    def test_runs_once_and_leaves_source_untouched(self):
        before = self.legacy.read_bytes()
        with database.connect() as db:
            self.assertIsNotNone(database.import_legacy_sqlite(db, self.legacy))
        with database.connect() as db:
            db.execute("DELETE FROM events")
            self.assertIsNone(database.import_legacy_sqlite(db, self.legacy))
            self.assertEqual(db.execute("SELECT count(*) AS n FROM events").fetchone()["n"], 0)
        self.assertEqual(self.legacy.read_bytes(), before)

    def test_missing_file_is_ignored(self):
        with database.connect() as db:
            self.assertIsNone(
                database.import_legacy_sqlite(db, Path(self.temp.name) / "none.sqlite")
            )

    def test_prepare_script_retains_private_inputs_in_postgres(self):
        project = Path(self.temp.name) / "project"
        (project / "app").mkdir(parents=True)
        (project / "app/account.json").write_text(json.dumps({"sha256": "synthetic-hash"}))
        (project / "app/location.json").write_text(json.dumps({"name": "Synthetic city"}))
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/prepare_data.py"),
                str(project),
                self.temp.name,
            ],
            check=True,
            capture_output=True,
            env={**os.environ, "APP_DIR": str(ROOT / "app")},
        )
        with database.connect() as db:
            meta = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM metadata")}
            self.assertEqual(meta["account_hash"], "hash-1")  # legacy value wins
            self.assertEqual(meta["weather_location"], {"name": "Synthetic city"})
            self.assertEqual(db.execute("SELECT count(*) AS n FROM statements").fetchone()["n"], 1)


if __name__ == "__main__":
    unittest.main()
