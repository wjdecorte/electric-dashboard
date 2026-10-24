import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pg

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "app"))
os.environ["DATA_DIR"] = tempfile.mkdtemp()
spec = importlib.util.spec_from_file_location("server", root / "app/server.py")
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)
import enrichment  # noqa: E402

ACCOUNT = hashlib.sha256(b"1234567890").hexdigest()
BASE = dict(
    source="fixture.pdf",
    start="2026-08-10",
    end="2026-09-09",
    days=30,
    previous_reading=81951,
    present_reading=83259,
    multiplier=1,
    kwh=1308,
    electric_charge=187.01,
    local_tax=5.61,
    franchise_tax=7.48,
    state_tax=7.48,
    membership_fee=0.0,
    service_charge=0.0,
    total=207.58,
    previous_period_kwh=1341,
    prior_year_kwh=1042,
    prior_year_days=32,
)


class Imports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = Path(self.temp.name) / "app"
        self.fixture.mkdir()
        self.original_root = server.ROOT
        self.original_hash = server.ACCOUNT_HASH
        self.addCleanup(setattr, server, "ROOT", self.original_root)
        self.addCleanup(setattr, server, "ACCOUNT_HASH", self.original_hash)
        server.ROOT = self.fixture
        server.ACCOUNT_HASH = ACCOUNT
        server.DATA = Path(self.temp.name) / "data"
        (self.fixture / "seed.json").write_text(json.dumps([BASE]))
        pg.reset_database()
        server.initialize()
        self.row = dict(
            BASE,
            start="2026-09-09",
            end="2026-10-09",
            previous_reading=83259,
            present_reading=84567,
            source="new.pdf",
        )

    def test_import_persistence_and_duplicate(self):
        with patch.object(server, "parse_pdf", return_value=self.row):
            self.assertEqual(server.import_pdf(b"new", "new.pdf")["status"], "ready")
            self.assertEqual(len(server.rows()), 1)
            self.assertEqual(server.import_pdf(b"new", "new.pdf", True)["status"], "imported")
            server.initialize()
            self.assertEqual(len(server.rows()), 2)
            self.assertEqual(server.import_pdf(b"new", "new.pdf", True)["status"], "duplicate")
            with server.connect() as db:
                self.assertEqual(
                    db.execute(
                        "SELECT pdf FROM statements WHERE period_end=%s", (self.row["end"],)
                    ).fetchone()["pdf"],
                    b"new",
                )

    def test_conflict_and_overlap_keep_data(self):
        for bad in [dict(self.row, end="2026-09-09"), dict(self.row, start="2026-09-08")]:
            with (
                patch.object(server, "parse_pdf", return_value=bad),
                self.assertRaises(server.ImportErrorValue),
            ):
                server.import_pdf(b"conflict", "x.pdf", True)
        self.assertEqual(len(server.rows()), 1)

    def test_parser_checks_account_meter_and_bill(self):
        text = "\n".join(
            [
                "Amicalola Electric Membership Corporation",
                "ACCOUNTNUMBER ACCOUNTNAME",
                "1234567890 TEST",
                "09/09/26 10/09/26 30 83259 84567 1 1308 187.01",
                "LOCAL TAX 5.61",
                "FRANCHISE TAX 7.48",
                "STATE TAX 7.48",
                "TOTAL CURRENT BILL 207.58",
                "PREVIOUS BILLING PERIOD 30 1308 44",
                "SAME PERIOD LAST YEAR 29 903 31",
            ]
        )

        def parse(value):
            pdf = SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: value)])
            with patch.object(server.pdfplumber, "open", return_value=nullcontext(pdf)):
                return server.parse_pdf(b"%PDF-test", "test.pdf")

        row = parse(text)
        self.assertEqual(row["kwh"], 1308)
        self.assertEqual(row["prior_year_kwh"], 903)
        self.assertEqual(row["prior_year_days"], 29)
        for altered in [
            text.replace("207.58", "208.58"),
            text.replace("84567", "84568"),
            text.replace("1234567890", "1234567891"),
            text.replace("30 83259", "29 83259"),
        ]:
            with self.assertRaises(server.ImportErrorValue):
                parse(altered)

    def test_invalid_pdf_rejected(self):
        with self.assertRaises(server.ImportErrorValue):
            server.import_pdf(b"not a PDF", "x.pdf", True)
        self.assertEqual(len(server.rows()), 1)

    def test_clean_install_and_account_survives_without_private_files(self):
        (self.fixture / "seed.json").unlink()
        pg.reset_database()
        server.ACCOUNT_HASH = None
        server.initialize()
        self.assertEqual(server.rows(), [])
        with patch.object(server, "parse_pdf", return_value=dict(self.row, _account_hash=ACCOUNT)):
            server.import_pdf(b"first", "x.pdf", True)
        server.initialize()
        self.assertEqual(enrichment.meta("account_hash"), ACCOUNT)
        with (
            patch.object(server, "parse_pdf", return_value=dict(BASE, _account_hash="different")),
            self.assertRaises(server.ImportErrorValue),
        ):
            server.import_pdf(b"other", "y.pdf", True)

    def test_events_validation_edit_delete_and_persistence(self):
        payload = dict(
            title="Vacation",
            category="Vacation",
            start="2026-08-20",
            end="2026-08-27",
            notes="Away",
        )
        event_id = enrichment.save_event(payload)
        server.initialize()
        self.assertEqual(len(enrichment.events()), 1)
        enrichment.save_event(dict(payload, id=event_id, title="Trip"))
        self.assertEqual(enrichment.events()[0]["title"], "Trip")
        with self.assertRaises(ValueError):
            enrichment.save_event(dict(payload, end="2026-08-19"))
        enrichment.delete_event(event_id)
        self.assertEqual(enrichment.events(), [])

    def test_weather_boundaries_and_incomplete_coverage(self):
        records = {
            "2026-08-10": dict(mean=60, low=50, high=70),
            "2026-08-11": dict(mean=75, low=65, high=85),
            "2026-08-12": dict(mean=100, low=90, high=110),
        }
        weather = enrichment.period_weather("2026-08-10", "2026-08-12", records)
        self.assertEqual(weather["available_days"], 2)
        self.assertEqual(weather["mean_f"], 67.5)
        self.assertEqual(weather["heating_degree_days"], 5)
        self.assertEqual(weather["cooling_degree_days"], 10)
        missing = enrichment.period_weather("2026-08-09", "2026-08-12", records)
        self.assertFalse(missing["complete"])
        self.assertIsNone(missing["cooling_degree_days"])

    def test_prior_weather_uses_evidence_or_marks_estimate(self):
        prior = dict(BASE, end="2025-09-09", start="2025-08-08", kwh=1042, days=32)
        self.assertFalse(enrichment.prior_window(BASE, [prior])["estimated"])
        self.assertTrue(enrichment.prior_window(BASE, [])["estimated"])
        self.assertEqual(enrichment.prior_window(BASE, [])["start"], "2025-08-08")

    def test_migration_retains_existing_data_and_adds_comparison_days(self):
        with server.connect() as db:
            old = dict(BASE)
            old.pop("prior_year_days")
            db.execute("UPDATE statements SET row_json=%s", (json.dumps(old),))
        server.initialize()
        self.assertEqual(server.rows()[0]["prior_year_days"], 32)

    def test_cached_weather_survives_refresh_failure(self):
        location = dict(
            name="Test city",
            region="Test",
            country="United States",
            latitude=40,
            longitude=-75,
            timezone="America/New_York",
        )
        enrichment.save_location(location)
        with server.connect() as db:
            db.execute(
                "INSERT INTO weather (location_key, day, mean, low, high, fetched_at)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (enrichment.location_key(location), "2026-08-10", 70, 60, 80, enrichment.now()),
            )
        with patch.object(enrichment, "fetch_json", side_effect=OSError("offline")):
            self.assertTrue(enrichment.refresh_weather())
            self.assertTrue(enrichment._lock.acquire(timeout=5))
            enrichment._lock.release()
        weather = enrichment.weather_context([BASE])[BASE["end"]]["current"]
        self.assertEqual(weather["available_days"], 1)
        self.assertIn("retained", enrichment.meta("weather_status")["error"])
        self.assertFalse(enrichment.meta("weather_status")["running"])

    def test_weather_refresh_is_cached_and_fetches_only_missing_days(self):
        location = dict(
            name="Test city",
            region="Test",
            country="United States",
            latitude=40,
            longitude=-75,
            timezone="America/New_York",
        )
        enrichment.save_location(location)
        small = dict(
            BASE, start="2026-08-10", end="2026-08-12", prior_year_kwh=0, prior_year_days=0
        )
        payload = dict(
            daily=dict(
                time=["2026-08-10", "2026-08-11"],
                temperature_2m_mean=[60, 75],
                temperature_2m_min=[50, 65],
                temperature_2m_max=[70, 85],
            )
        )
        with (
            patch.object(enrichment, "prior_window", return_value=None),
            patch.object(enrichment, "statement_rows", return_value=[small]),
            patch.object(enrichment, "fetch_json", return_value=payload) as fetch,
        ):
            enrichment.refresh_weather()
            self.assertTrue(enrichment._lock.acquire(timeout=5))
            enrichment._lock.release()
            self.assertEqual(fetch.call_count, 1)
            enrichment.refresh_weather()
            self.assertTrue(enrichment._lock.acquire(timeout=5))
            enrichment._lock.release()
            self.assertEqual(fetch.call_count, 1)
        self.assertTrue(enrichment.weather_context([small])[small["end"]]["current"]["complete"])

    def test_weather_year_ago_does_not_require_prior_usage(self):
        row = dict(BASE, start="2024-02-29", end="2024-03-30", prior_year_kwh=0, prior_year_days=0)
        window = enrichment.prior_window(row, [])
        self.assertEqual(window["start"], "2023-02-28")
        self.assertEqual(window["end"], "2023-03-30")
        self.assertTrue(window["calendar_window"])

    def test_settings_reject_invalid_coordinates(self):
        with self.assertRaises(ValueError):
            enrichment.save_location(
                dict(name="Test", latitude=float("nan"), longitude=0, timezone="UTC")
            )


if __name__ == "__main__":
    unittest.main()
