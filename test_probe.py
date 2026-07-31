#!/usr/bin/env python3
"""
Cinema City Flora (1052) - IMAX 70mm Probe Script
Fetches available dates and screenings for IMAX 70mm movies (e.g. Odyssea).
"""

import json
import ssl
import sys
import urllib.request
from typing import Dict, List, Any

# Configuration
CINEMA_ID = "1052"             # Cinema City Flora (Prague)
FILM_ID = "7268s2r"            # Movie: Odyssea
TARGET_ATTR = "70-mm"          # Attribute filter: IMAX 70mm
UNTIL_DATE = "2027-12-31"      # Search boundary date

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


def get_available_dates(cinema_id: str, until_date: str) -> List[str]:
    """Fetch all available dates for a given cinema."""
    url = (
        f"https://www.cinemacity.cz/cz/data-api-service/v1/quickbook/10101"
        f"/dates/in-cinema/{cinema_id}/until/{until_date}?attr=&lang=cs_CZ"
    )
    data = fetch_json(url)
    return data.get("body", {}).get("dates", [])


def get_events_for_date(cinema_id: str, date_str: str) -> List[Dict[str, Any]]:
    """Fetch all events/screenings for a cinema on a specific date."""
    url = (
        f"https://www.cinemacity.cz/cz/data-api-service/v1/quickbook/10101"
        f"/film-events/in-cinema/{cinema_id}/at-date/{date_str}?attr=&lang=cs_CZ"
    )
    data = fetch_json(url)
    return data.get("body", {}).get("events", [])


def main():
    print("=" * 70)
    print("🎬 CINEMA CITY FLORA - IMAX 70mm PROBE")
    print("=" * 70)
    print(f"Cinema ID: {CINEMA_ID}")
    print(f"Target Film ID: {FILM_ID}")
    print(f"Target Attribute: {TARGET_ATTR}\n")

    # Step 1: Get available dates
    print("Fetching available dates from Cinema City API...")
    try:
        dates = get_available_dates(CINEMA_ID, UNTIL_DATE)
    except Exception as e:
        print(f"❌ Failed to fetch dates: {e}")
        sys.exit(1)

    print(f"✅ Found {len(dates)} dates with scheduled screenings.\n")

    if not dates:
        print("No available dates found.")
        return

    # Step 2: Probe each date for target screenings
    total_screenings = 0
    date_screenings_map = {}

    print("Probing showtimes for IMAX 70mm screenings...")
    print("-" * 70)

    for d in dates:
        try:
            events = get_events_for_date(CINEMA_ID, d)
        except Exception as e:
            print(f"⚠️ Warning: Could not fetch events for {d}: {e}")
            continue

        # Filter events for film ID and 70-mm attribute
        matches = [
            ev for ev in events
            if ev.get("filmId") == FILM_ID and TARGET_ATTR in ev.get("attributeIds", [])
        ]

        if matches:
            date_screenings_map[d] = matches
            total_screenings += len(matches)

    # Step 3: Output results
    if not date_screenings_map:
        print(f"❌ No {TARGET_ATTR} screenings found for film {FILM_ID}.")
        return

    print(f"\n🎉 Found {total_screenings} matching IMAX 70mm screening(s) across {len(date_screenings_map)} date(s):\n")

    for date_str, screenings in date_screenings_map.items():
        print(f"📅 Date: {date_str} ({len(screenings)} screening(s))")
        for s in screenings:
            time_str = s.get("eventDateTime", "").replace("T", " ")
            sold_out = s.get("soldOut", False)
            auditorium = s.get("auditorium", "Unknown Hall")
            booking_link = s.get("bookingLink", "N/A")
            status = "🔴 SOLD OUT" if sold_out else "🟢 AVAILABLE"

            print(f"   🕒 {time_str} | {auditorium} | {status}")
            print(f"      🔗 Booking Link: {booking_link}")
        print()

    print("=" * 70)


if __name__ == "__main__":
    main()
