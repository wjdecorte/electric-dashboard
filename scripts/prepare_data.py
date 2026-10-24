"""Back up local data and migrate private initialization inputs on the NAS only."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

project = Path(sys.argv[1] if len(sys.argv) > 1 else "/bootstrap")
data = Path(sys.argv[2] if len(sys.argv) > 2 else "/data")
data.mkdir(parents=True, exist_ok=True)
path = data / "statements.sqlite"
if path.exists():
    backups = data / "backups"
    backups.mkdir(exist_ok=True)
    backup_path = backups / (
        "pre-update-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".sqlite"
    )
    with sqlite3.connect(path) as source, sqlite3.connect(backup_path) as destination:
        source.backup(destination)
    for old in sorted(backups.glob("pre-update-*.sqlite"))[:-5]:
        old.unlink()
    print("Created local database backup:", backup_path.name)
with sqlite3.connect(path) as db:
    db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
    for name, key, field in [
        ("account.json", "account_hash", "sha256"),
        ("location.json", "weather_location", None),
    ]:
        source = project / "app" / name
        if (
            source.exists()
            and not db.execute("SELECT 1 FROM metadata WHERE key=?", (key,)).fetchone()
        ):
            value = json.loads(source.read_text())
            value = value[field] if field else value
            db.execute("INSERT INTO metadata VALUES (?,?)", (key, json.dumps(value)))
            print("Retained local setting:", key)
    seed = project / "app/seed.json"
    if (
        seed.exists()
        and not db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone()
    ):
        db.execute(
            "CREATE TABLE IF NOT EXISTS statements (end TEXT PRIMARY KEY,start TEXT NOT NULL,row_json TEXT NOT NULL,pdf BLOB,sha256 TEXT UNIQUE)"
        )
        for row in json.loads(seed.read_text()):
            db.execute(
                "INSERT OR IGNORE INTO statements VALUES (?,?,?,?,?)",
                (row["end"], row["start"], json.dumps(row), None, None),
            )
        db.execute("INSERT INTO metadata VALUES ('initialized','1')")
        print("Retained local seed records")

# Backfill service days only from matching local statement evidence.
seed = project / "app/seed.json"
if seed.exists():
    with sqlite3.connect(path) as db:
        for row in json.loads(seed.read_text()):
            old = db.execute(
                "SELECT row_json FROM statements WHERE end=?", (row["end"],)
            ).fetchone()
            if old:
                saved = json.loads(old[0])
                if "prior_year_days" not in saved and saved.get("prior_year_kwh") == row.get(
                    "prior_year_kwh"
                ):
                    saved["prior_year_days"] = row.get("prior_year_days", 0)
                    db.execute(
                        "UPDATE statements SET row_json=? WHERE end=?",
                        (json.dumps(saved), row["end"]),
                    )
