"""Move legacy SQLite data and private initialization inputs into PostgreSQL (NAS only).

Run inside the application image by update.sh, with the project folder mounted at /bootstrap
and the data folder at /data. Every step is idempotent and skips what is already stored.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("APP_DIR", "/app"))

import database  # noqa: E402
import enrichment  # noqa: E402

project = Path(sys.argv[1] if len(sys.argv) > 1 else "/bootstrap")
data = Path(sys.argv[2] if len(sys.argv) > 2 else "/data")

database.wait_for_database()
with database.connect() as db:
    database.create_schema(db)
    counts = database.import_legacy_sqlite(db, data / "statements.sqlite")
    if counts is not None:
        print("Imported legacy SQLite database into PostgreSQL:", counts)
    for name, key, field in [
        ("account.json", "account_hash", "sha256"),
        ("location.json", "weather_location", None),
    ]:
        source = project / "app" / name
        if (
            source.exists()
            and not db.execute("SELECT 1 FROM metadata WHERE key=%s", (key,)).fetchone()
        ):
            value = json.loads(source.read_text())
            enrichment.set_meta(db, key, value[field] if field else value)
            print("Retained local setting:", key)
    seed = project / "app/seed.json"
    if seed.exists():
        rows = json.loads(seed.read_text())
        if not db.execute("SELECT 1 FROM metadata WHERE key='initialized'").fetchone():
            for row in rows:
                db.execute(
                    "INSERT INTO statements (period_end, period_start, row_json)"
                    " VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (row["end"], row["start"], json.dumps(row)),
                )
            enrichment.set_meta(db, "initialized", 1)
            print("Retained local seed records")
        # Backfill service days only from matching local statement evidence.
        for row in rows:
            old = db.execute(
                "SELECT row_json FROM statements WHERE period_end=%s", (row["end"],)
            ).fetchone()
            saved = old["row_json"] if old else None
            if (
                saved
                and "prior_year_days" not in saved
                and saved.get("prior_year_kwh") == row.get("prior_year_kwh")
            ):
                saved["prior_year_days"] = row.get("prior_year_days", 0)
                db.execute(
                    "UPDATE statements SET row_json=%s WHERE period_end=%s",
                    (json.dumps(saved), row["end"]),
                )
