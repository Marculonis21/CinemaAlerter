#!/usr/bin/env python3
"""
Cinema City Flora (1052) - IMAX 70mm Screening Alerter / Monitor
Tracks state in `state.json` to detect:
1. New screening dates for target film (e.g. past August 12)
2. New showtimes added to existing dates
3. Status changes (e.g. Sold Out -> Available)
"""

import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime
from typing import Dict, List, Any

from pathlib import Path

# Configuration
CINEMA_ID = "1052"             # Cinema City Flora (Prague)
FILM_ID = "7268s2r"            # Movie: Odyssea
TARGET_ATTR = "70-mm"          # Attribute filter: IMAX 70mm
UNTIL_DATE = "2027-12-31"      # Search boundary date
STATE_FILE = Path(__file__).parent / "state.json"      # Persistent memory file

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def fetch_json(url: str) -> Dict[str, Any]:
    """Helper function to perform GET requests and parse JSON responses."""
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP Error {resp.status} for URL: {url}")
        return json.loads(resp.read().decode("utf-8"))


def get_cinema_dates(cinema_id: str, until_date: str) -> List[str]:
    """Fetch all available dates for a given cinema."""
    url = (
        f"https://www.cinemacity.cz/cz/data-api-service/v1/quickbook/10101"
        f"/dates/in-cinema/{cinema_id}/until/{until_date}?attr=&lang=cs_CZ"
    )
    data = fetch_json(url)
    return sorted(data.get("body", {}).get("dates", []))


def get_events_for_date(cinema_id: str, date_str: str) -> List[Dict[str, Any]]:
    """Fetch all events/screenings for a cinema on a specific date."""
    url = (
        f"https://www.cinemacity.cz/cz/data-api-service/v1/quickbook/10101"
        f"/film-events/in-cinema/{cinema_id}/at-date/{date_str}?attr=&lang=cs_CZ"
    )
    data = fetch_json(url)
    return data.get("body", {}).get("events", [])


def load_state() -> Dict[str, Any]:
    """Load persistent state from state.json if it exists."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Could not load state file ({e}), starting with fresh state.")
    return {"last_check": None, "known_dates": [], "known_events": {}}


def save_state(state: Dict[str, Any]) -> None:
    """Save persistent state to state.json."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 70)
    print(f"🎬 CINEMA CITY MONITOR - {now_str}")
    print("=" * 70)

    # 1. Load previous state
    previous_state = load_state()
    is_initial_run = previous_state.get("last_check") is None

    if is_initial_run:
        print("ℹ️ First run detected. Initializing state baseline...")
    else:
        print(f"ℹ️ Loaded baseline from last check: {previous_state['last_check']}")

    # 2. Fetch overall cinema dates
    print("\n1️⃣ Fetching scheduled dates for Cinema Flora...")
    try:
        all_cinema_dates = get_cinema_dates(CINEMA_ID, UNTIL_DATE)
    except Exception as e:
        print(f"❌ Failed to fetch cinema dates: {e}")
        sys.exit(1)

    print(f"   Found {len(all_cinema_dates)} total date(s) with any screenings at cinema.")

    # 3. Fetch current IMAX 70mm events specifically for Odyssea
    print("2️⃣ Probing dates specifically for Odyssea (IMAX 70mm)...")
    current_events: Dict[str, Dict[str, Any]] = {}

    for d in all_cinema_dates:
        try:
            events = get_events_for_date(CINEMA_ID, d)
        except Exception as e:
            print(f"   ⚠️ Could not fetch events for {d}: {e}")
            continue

        for ev in events:
            if ev.get("filmId") == FILM_ID and TARGET_ATTR in ev.get("attributeIds", []):
                event_id = str(ev.get("id"))
                current_events[event_id] = {
                    "id": event_id,
                    "date": d,
                    "time": ev.get("eventDateTime"),
                    "auditorium": ev.get("auditorium"),
                    "soldOut": ev.get("soldOut", False),
                    "bookingLink": ev.get("bookingLink"),
                }

    # Derive active dates specifically for Odyssea IMAX 70mm
    target_dates = sorted(list(set(ev["date"] for ev in current_events.values())))

    print(f"   Found {len(current_events)} IMAX 70mm screening(s) across {len(target_dates)} date(s).")

    # 4. Compare with previous state
    prev_dates_set = set(previous_state.get("known_dates", []))
    curr_dates_set = set(target_dates)
    prev_events = previous_state.get("known_events", {})

    new_dates = sorted(list(curr_dates_set - prev_dates_set))
    new_events = [ev for eid, ev in current_events.items() if eid not in prev_events]
    restocked_events = [
        ev for eid, ev in current_events.items()
        if eid in prev_events and prev_events[eid].get("soldOut") is True and ev.get("soldOut") is False
    ]

    print("\n" + "=" * 70)
    print("📊 COMPARISON REPORT (Odyssea IMAX 70mm)")
    print("=" * 70)

    if is_initial_run:
        print(f"✅ Baseline saved! Tracking {len(target_dates)} screening dates and {len(current_events)} showtimes.")
        print(f"📅 Latest scheduled Odyssea 70mm date: {target_dates[-1] if target_dates else 'N/A'}")
    else:
        has_alerts = False

        # Alert: New Dates
        if new_dates:
            has_alerts = True
            print(f"\n🎉 NEW ODYSSEA 70mm DATE(S) ADDED ({len(new_dates)}):")
            for d in new_dates:
                print(f"   🗓️ {d}")

        # Alert: New Screenings
        if new_events:
            has_alerts = True
            print(f"\n🎟️ NEW SHOWTIME(S) ADDED ({len(new_events)}):")
            for ev in new_events:
                status = "🔴 SOLD OUT" if ev["soldOut"] else "🟢 AVAILABLE"
                print(f"   🕒 {ev['time'].replace('T', ' ')} | {ev['auditorium']} | {status}")
                print(f"      🔗 {ev['bookingLink']}")

        # Alert: Restocked Screenings (previously sold out -> now available)
        if restocked_events:
            has_alerts = True
            print(f"\n🔔 TICKETS BECOME AVAILABLE ({len(restocked_events)}):")
            for ev in restocked_events:
                print(f"   🕒 {ev['time'].replace('T', ' ')} | {ev['auditorium']}")
                print(f"      🔗 {ev['bookingLink']}")

        if not has_alerts:
            print("ℹ️ No new dates or showtimes detected for Odyssea IMAX 70mm since last check.")
            print(f"📅 Latest scheduled date currently: {target_dates[-1] if target_dates else 'N/A'}")

    # 5. Update state.json with target film dates only
    new_state = {
        "last_check": now_str,
        "film_id": FILM_ID,
        "attribute": TARGET_ATTR,
        "known_dates": target_dates,
        "known_events": current_events,
    }
    save_state(new_state)

    print("\n💾 State saved to state.json.")
    print("=" * 70)


if __name__ == "__main__":
    main()
