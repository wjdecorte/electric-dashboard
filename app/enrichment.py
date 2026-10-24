"""Persistent household events and cached, date-aligned historical weather."""

import json
import math
import os
import threading
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlencode
from urllib.request import urlopen
from zoneinfo import ZoneInfo

VERSION = "2.2.0"
_lock = threading.Lock()
connect = None
statement_rows = None


def configure(db_connect, get_rows):
    global connect, statement_rows
    connect, statement_rows = db_connect, get_rows


def migrate(db, location=None):
    if (
        location
        and not db.execute("SELECT 1 FROM metadata WHERE key='weather_location'").fetchone()
    ):
        set_meta(db, "weather_location", location)
    set_meta(db, "schema_version", 3)


def now():
    return datetime.now(UTC).isoformat()


def set_meta(db, key, value):
    db.execute(
        "INSERT INTO metadata (key, value) VALUES (%s, %s)"
        " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        (key, json.dumps(value)),
    )


def meta(key, default=None):
    with connect() as db:
        item = db.execute("SELECT value FROM metadata WHERE key=%s", (key,)).fetchone()
        return item["value"] if item else default


def location_key(location):
    return f"{location['latitude']:.5f},{location['longitude']:.5f},{location['timezone']}"


def settings():
    return dict(
        location=meta("weather_location"),
        weather_status=meta("weather_status", {}),
        version=VERSION,
        base_temperature_f=65,
        revision=os.environ.get("APP_REVISION", "development"),
    )


def fetch_json(url):
    with urlopen(url, timeout=25) as response:
        return json.load(response)


def search_location(query):
    query = str(query).strip()
    if not 2 <= len(query) <= 100:
        raise ValueError("Enter a city or ZIP code (2–100 characters).")
    payload = fetch_json(
        "https://geocoding-api.open-meteo.com/v1/search?"
        + urlencode(dict(name=query, count=8, language="en", format="json"))
    )
    return [
        dict(
            id=r["id"],
            name=r["name"],
            region=r.get("admin1", ""),
            country=r.get("country", ""),
            latitude=r["latitude"],
            longitude=r["longitude"],
            timezone=r.get("timezone", "UTC"),
        )
        for r in payload.get("results", [])
    ]


def save_location(location):
    if not isinstance(location, dict):
        raise ValueError("Select a weather location from the search results.")
    try:
        lat = float(location["latitude"])
        lon = float(location["longitude"])
        tz = str(location["timezone"])
        if (
            not math.isfinite(lat)
            or not math.isfinite(lon)
            or not -90 <= lat <= 90
            or not -180 <= lon <= 180
        ):
            raise ValueError()
        ZoneInfo(tz)
    except Exception:
        raise ValueError("The location coordinates or timezone are invalid.") from None
    name = str(location.get("name", "")).strip()
    if not name or len(name) > 100:
        raise ValueError("Choose a named location.")
    result = dict(
        name=name,
        region=str(location.get("region", ""))[:100],
        country=str(location.get("country", ""))[:100],
        latitude=lat,
        longitude=lon,
        timezone=tz,
    )
    with connect() as db:
        set_meta(db, "weather_location", result)
    return result


CATEGORIES = (
    "Vacation",
    "Guests",
    "Appliance",
    "HVAC",
    "Home improvement",
    "Routine change",
    "Other",
)


def events():
    with connect() as db:
        return [
            dict(
                id=r["id"],
                start=r["start_date"].isoformat(),
                end=r["end_date"].isoformat(),
                title=r["title"],
                category=r["category"],
                notes=r["notes"],
                updated_at=r["updated_at"].isoformat(),
            )
            for r in db.execute(
                "SELECT id, start_date, end_date, title, category, notes, updated_at"
                " FROM events ORDER BY start_date DESC, id DESC"
            )
        ]


def save_event(payload):
    if not isinstance(payload, dict):
        raise ValueError("Enter the event details.")
    title = str(payload.get("title", "")).strip()
    notes = str(payload.get("notes", "")).strip()
    category = payload.get("category", "Other")
    if not title or len(title) > 120:
        raise ValueError("Enter a title of 1–120 characters.")
    if len(notes) > 2000:
        raise ValueError("Notes must be 2,000 characters or fewer.")
    if category not in CATEGORIES:
        raise ValueError("Select an event category.")
    try:
        start = date.fromisoformat(payload["start"])
        end = date.fromisoformat(payload.get("end") or payload["start"])
    except Exception:
        raise ValueError("Enter valid start and end dates.") from None
    if end < start:
        raise ValueError("End date must be on or after the start date.")
    event_id = payload.get("id")
    with connect() as db:
        if event_id is not None:
            if not isinstance(event_id, int) or event_id < 1:
                raise ValueError("The event ID is invalid.")
            updated = db.execute(
                "UPDATE events SET start_date=%s, end_date=%s, title=%s, category=%s, notes=%s,"
                " updated_at=%s WHERE id=%s",
                (start.isoformat(), end.isoformat(), title, category, notes, now(), event_id),
            )
            if updated.rowcount != 1:
                raise ValueError("This event no longer exists. Refresh and try again.")
        else:
            event_id = db.execute(
                "INSERT INTO events (start_date, end_date, title, category, notes, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (start.isoformat(), end.isoformat(), title, category, notes, now()),
            ).fetchone()["id"]
    return event_id


def delete_event(event_id):
    if not isinstance(event_id, int) or event_id < 1:
        raise ValueError("The event ID is invalid.")
    with connect() as db:
        db.execute("DELETE FROM events WHERE id=%s", (event_id,))


def prior_window(row, statements):
    current_end = date.fromisoformat(row["end"])
    if not row.get("prior_year_kwh") or not row.get("prior_year_days"):

        def year_ago(value):
            original = date.fromisoformat(value)
            try:
                return original.replace(year=original.year - 1)
            except ValueError:
                return original.replace(year=original.year - 1, day=28)

        return dict(
            start=year_ago(row["start"]).isoformat(),
            end=year_ago(row["end"]).isoformat(),
            estimated=False,
            calendar_window=True,
        )
    candidates = [
        r
        for r in statements
        if date.fromisoformat(r["end"]).year == current_end.year - 1
        and date.fromisoformat(r["end"]).month == current_end.month
        and r["kwh"] == row["prior_year_kwh"]
        and r["days"] == row["prior_year_days"]
    ]
    if len(candidates) == 1:
        return dict(start=candidates[0]["start"], end=candidates[0]["end"], estimated=False)
    try:
        prior_end = current_end.replace(year=current_end.year - 1)
    except ValueError:
        prior_end = current_end.replace(year=current_end.year - 1, day=28)
    return dict(
        start=(prior_end - timedelta(days=row["prior_year_days"])).isoformat(),
        end=prior_end.isoformat(),
        estimated=True,
    )


def period_weather(start, end, records):
    # Start-inclusive/end-exclusive avoids counting meter-reading boundaries twice.
    begin = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    days = [(begin + timedelta(days=i)).isoformat() for i in range((stop - begin).days)]
    valid = [records[d] for d in days if d in records]
    complete = len(valid) == len(days) and bool(days)
    return dict(
        start=start,
        end=end,
        expected_days=len(days),
        available_days=len(valid),
        complete=complete,
        mean_f=round(sum(r["mean"] for r in valid) / len(valid), 1) if valid else None,
        heating_degree_days=round(sum(max(0, 65 - r["mean"]) for r in valid), 1)
        if complete
        else None,
        cooling_degree_days=round(sum(max(0, r["mean"] - 65) for r in valid), 1)
        if complete
        else None,
        daily=[
            dict(
                day=d, mean_f=records[d]["mean"], low_f=records[d]["low"], high_f=records[d]["high"]
            )
            for d in days
            if d in records
        ],
    )


def weather_context(statements):
    location = meta("weather_location")
    if not location:
        return {}
    with connect() as db:
        records = {
            r["day"]: r
            for r in db.execute(
                "SELECT day::text AS day, mean, low, high FROM weather WHERE location_key=%s",
                (location_key(location),),
            )
        }
    result = {}
    for row in statements:
        current = period_weather(row["start"], row["end"], records)
        window = prior_window(row, statements)
        prior = period_weather(window["start"], window["end"], records) if window else None
        if prior:
            prior["estimated_window"] = window["estimated"]
            prior["calendar_window"] = window.get("calendar_window", False)
        result[row["end"]] = dict(current=current, prior=prior)
    return result


def refresh_weather():
    if not _lock.acquire(blocking=False):
        return False
    with connect() as db:
        set_meta(db, "weather_status", dict(running=True, started_at=now(), error=None))

    def worker():
        fetched = 0
        try:
            location = meta("weather_location")
            if not location:
                raise ValueError("Choose a weather location in Settings first.")
            key = location_key(location)
            statements = statement_rows()
            with connect() as db:
                set_meta(db, "weather_status", dict(running=True, started_at=now(), error=None))
            needed = set()
            cutoff = datetime.now(ZoneInfo(location["timezone"])).date() - timedelta(days=2)
            for row in statements:
                windows = [dict(start=row["start"], end=row["end"])]
                prior = prior_window(row, statements)
                if prior:
                    windows.append(prior)
                for w in windows:
                    start = date.fromisoformat(w["start"])
                    end = min(date.fromisoformat(w["end"]), cutoff + timedelta(days=1))
                    for i in range(max(0, (end - start).days)):
                        needed.add((start + timedelta(days=i)).isoformat())
            with connect() as db:
                cached = {
                    r["day"]
                    for r in db.execute(
                        "SELECT day::text AS day FROM weather WHERE location_key=%s", (key,)
                    )
                }
            missing = sorted(needed - cached)
            # Merge adjoining days into bounded requests; each successful batch survives failures.
            ranges = []
            for day in missing:
                d = date.fromisoformat(day)
                if (
                    ranges
                    and d == ranges[-1][1] + timedelta(days=1)
                    and (d - ranges[-1][0]).days < 365
                ):
                    ranges[-1][1] = d
                else:
                    ranges.append([d, d])
            for start, end in ranges:
                params = dict(
                    latitude=location["latitude"],
                    longitude=location["longitude"],
                    start_date=start.isoformat(),
                    end_date=end.isoformat(),
                    daily="temperature_2m_mean,temperature_2m_min,temperature_2m_max",
                    temperature_unit="fahrenheit",
                    timezone=location["timezone"],
                )
                payload = fetch_json(
                    "https://archive-api.open-meteo.com/v1/archive?" + urlencode(params)
                )
                daily = payload.get("daily", {})
                dates = daily.get("time", [])
                means = daily.get("temperature_2m_mean", [])
                lows = daily.get("temperature_2m_min", [])
                highs = daily.get("temperature_2m_max", [])
                if not (len(dates) == len(means) == len(lows) == len(highs)):
                    raise ValueError(
                        "Weather provider returned incomplete arrays. Try refreshing later."
                    )
                with connect() as db:
                    for day, mean, low, high in zip(dates, means, lows, highs, strict=True):
                        if day not in needed or any(
                            v is None or not isinstance(v, (int, float)) or not math.isfinite(v)
                            for v in (mean, low, high)
                        ):
                            continue
                        db.execute(
                            "INSERT INTO weather (location_key, day, mean, low, high, fetched_at)"
                            " VALUES (%s, %s, %s, %s, %s, %s)"
                            " ON CONFLICT (location_key, day) DO UPDATE SET mean = EXCLUDED.mean,"
                            " low = EXCLUDED.low, high = EXCLUDED.high, fetched_at = EXCLUDED.fetched_at",
                            (key, day, mean, low, high, now()),
                        )
                        fetched += 1
            with connect() as db:
                remaining = needed - {
                    r["day"]
                    for r in db.execute(
                        "SELECT day::text AS day FROM weather WHERE location_key=%s", (key,)
                    )
                }
                set_meta(
                    db,
                    "weather_status",
                    dict(
                        running=False,
                        updated_at=now(),
                        fetched_days=fetched,
                        error="Some historical weather days are unavailable. Cached days remain usable."
                        if remaining
                        else None,
                    ),
                )
        except Exception:
            with connect() as db:
                set_meta(
                    db,
                    "weather_status",
                    dict(
                        running=False,
                        updated_at=now(),
                        error="Weather refresh failed. Check NAS internet access and retry. Cached weather is retained.",
                    ),
                )
        finally:
            _lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return True


def dashboard():
    statements = statement_rows()
    return dict(
        statements=statements,
        events=events(),
        settings=settings(),
        weather=weather_context(statements),
    )
