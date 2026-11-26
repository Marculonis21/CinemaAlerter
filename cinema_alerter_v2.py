#!/usr/bin/env python3
"""
Cinema City Flora (1052) - IMAX 70mm Screening Alerter & Seat Auditor (v2)
Tracks state in `state_v2.json` to detect:
1. New screening dates for target film (e.g. past August 12)
2. New showtimes added to existing dates
3. Standard seat availability (excluding wheelchair & companion spots)
4. Status changes (e.g. standard seats opening up or tickets restocked)

Notifications:
- Integrated with ntfy.sh for instant push alerts to phone/browser.
"""

import base64
import json
import os
import ssl
import sys
import http.cookiejar
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Configuration
CINEMA_ID = "1052"                     # Cinema City Flora (Prague)
FILM_ID = "8105s2r"                    # Movie: Duna: část třetí (Dune: Part Three)
FILM_NAME = "Duna: část třetí"         # Movie display title
TARGET_ATTR = "70-mm"                  # Attribute filter: IMAX 70mm
UNTIL_DATE = "2027-12-31"              # Search boundary date
STATE_FILE = "state_v2.json"           # Persistent memory file for v2

# Notification Settings (ntfy.sh)
NTFY_ENABLED = True
NTFY_TOPIC = "cinemacity_odyssea_marculonis"  # Change to your desired ntfy topic if needed

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def b64_header(text: str) -> str:
    """Encodes unicode header text into RFC 2047 base64 format for HTTP headers."""
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"=?utf-8?b?{encoded}?="


def send_ntfy_alert(
    title: str,
    message: str,
    link: Optional[str] = None,
    priority: str = "high",
    tags: str = "clapper,ticket"
) -> bool:
    """Sends a real-time push notification via ntfy.sh."""
    if not NTFY_ENABLED or not NTFY_TOPIC:
        return False
    
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    headers = {
        "Title": b64_header(title),
        "Priority": priority,
        "Tags": tags,
    }
    if link:
        headers["Click"] = link

    try:
        req = urllib.request.Request(
            url,
            data=message.encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"⚠️ Failed to send ntfy alert: {e}")
        return False


def fetch_json(url: str) -> Dict[str, Any]:
    """Helper function for simple GET requests."""
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


def fetch_standard_seat_breakdown(event_id: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Probes the seating map API for a given screening ID.
    Filters out wheelchair (hc) and companion (co) seats completely.
    Returns: (available_standard, total_standard)
    """
    cj = http.cookiejar.CookieJar()
    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx)
    )

    base_headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    try:
        # Step 1: Initiate order session to receive uuid cookie
        order_url = f"https://tickets.cinemacity.cz/api/order/{event_id}"
        post_data = urllib.parse.urlencode({"lang": "cs"}).encode("utf-8")
        req_order = urllib.request.Request(order_url, data=post_data, headers=base_headers, method="POST")
        with opener.open(req_order, timeout=10):
            pass

        uuid_val = None
        for cookie in cj:
            if cookie.name == "uuid":
                uuid_val = cookie.value
                break

        api_headers = {
            "User-Agent": HEADERS["User-Agent"],
            "Accept": "application/json, text/plain, */*",
            "Referer": f"https://tickets.cinemacity.cz/order/{event_id}",
            "uuid": uuid_val or "",
        }

        # Step 2: Get presentation metadata
        pres_url = f"https://tickets.cinemacity.cz/api/presentations/{event_id}"
        req_pres = urllib.request.Request(pres_url, headers=api_headers)
        with opener.open(req_pres, timeout=10) as resp:
            pres_data = json.loads(resp.read().decode("utf-8"))
            pres = pres_data.get("presentation", {})

        venue_id = pres.get("venueId")
        seatplan_id = pres.get("seatplanId")
        venue_type_id = pres.get("venueTypeId")
        is_reserved = "1" if pres.get("isReserved") else "0"

        if not venue_id or not seatplan_id or venue_type_id is None:
            return None, None

        # Step 3: Fetch seatplan layout
        sp_url = f"https://tickets.cinemacity.cz/api/seats/seatplanV2?venueId={venue_id}&seatplanId={seatplan_id}"
        req_sp = urllib.request.Request(sp_url, data=b"{}", headers={**api_headers, "Content-Type": "application/json"}, method="POST")
        with opener.open(req_sp, timeout=10) as resp:
            sp_data = json.loads(resp.read().decode("utf-8"))

        # Step 4: Fetch seat occupancy status
        st_url = f"https://tickets.cinemacity.cz/api/seats/seats-statusV2?presentationId={event_id}&venueTypeId={venue_type_id}&isReserved={is_reserved}"
        req_st = urllib.request.Request(st_url, headers=api_headers)
        with opener.open(req_st, timeout=10) as resp:
            st_data = json.loads(resp.read().decode("utf-8"))
            seats_status = st_data.get("seats", {})

        # Tally standard seats only (excluding wheelchair 'hc' and companion 'co')
        total_std, avail_std = 0, 0

        for sec_id, sec_val in sp_data.get("S", {}).items():
            for g_id, g_val in sec_val.get("G", {}).items():
                for r_id, r_val in g_val.get("R", {}).items():
                    for seat_x, seat in r_val.get("S", {}).items():
                        is_hc = bool(seat.get("hc"))
                        is_co = bool(seat.get("co"))

                        # Skip wheelchair and companion seats completely
                        if is_hc or is_co:
                            continue

                        seat_key = f"{sec_id}_{seat_x}_{r_id}"
                        total_std += 1
                        if seat_key in seats_status:
                            avail_std += 1

        return avail_std, total_std

    except Exception:
        return None, None


def load_state() -> Dict[str, Any]:
    """Load persistent state from state_v2.json if it exists."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Could not load state file ({e}), starting with fresh state.")
    return {"last_check": None, "known_dates": [], "known_events": {}}


def save_state(state: Dict[str, Any]) -> None:
    """Save persistent state to state_v2.json."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("=" * 70)
    print(f"🎬 CINEMA CITY MONITOR & SEAT AUDITOR (V2) - {now_str}")
    print("=" * 70)

    # 1. Load previous state
    previous_state = load_state()
    is_initial_run = (
        previous_state.get("last_check") is None
        or previous_state.get("film_id") != FILM_ID
    )

    if is_initial_run:
        print(f"ℹ️ Initial run for {FILM_NAME} (ID: {FILM_ID}). Initializing state baseline...")
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

    # 3. Fetch current IMAX 70mm events specifically for the target film
    print(f"2️⃣ Probing dates specifically for {FILM_NAME} (IMAX 70mm)...")
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

                # Perform standard seat map audit
                avail_std, total_std = fetch_standard_seat_breakdown(event_id)

                current_events[event_id] = {
                    "id": event_id,
                    "date": d,
                    "time": ev.get("eventDateTime"),
                    "auditorium": ev.get("auditorium"),
                    "avail_std": avail_std,
                    "total_std": total_std,
                    "bookingLink": ev.get("bookingLink"),
                }

    target_dates = sorted(list(set(ev["date"] for ev in current_events.values())))
    print(f"   Found {len(current_events)} IMAX 70mm screening(s) across {len(target_dates)} date(s).")

    # 4. Compare with previous state
    prev_dates_set = set(previous_state.get("known_dates", []))
    curr_dates_set = set(target_dates)
    prev_events = previous_state.get("known_events", {})

    new_dates = sorted(list(curr_dates_set - prev_dates_set))
    new_events = [ev for eid, ev in current_events.items() if eid not in prev_events]
    restocked_std_events = [
        ev for eid, ev in current_events.items()
        if eid in prev_events
        and (prev_events[eid].get("avail_std") == 0)
        and (ev.get("avail_std") is not None and ev.get("avail_std") > 0)
    ]

    print("\n" + "=" * 70)
    print(f"📊 COMPARISON REPORT ({FILM_NAME} IMAX 70mm - Standard Seats Only)")
    print("=" * 70)

    if is_initial_run:
        print(f"✅ Baseline saved! Tracking {len(target_dates)} screening dates and {len(current_events)} showtimes.\n")
        for d in target_dates:
            d_screenings = [ev for ev in current_events.values() if ev["date"] == d]
            print(f"📅 Date: {d} ({len(d_screenings)} screening(s))")
            for s in d_screenings:
                t_str = s["time"].replace("T", " ")
                std_info = f"{s['avail_std']}/{s['total_std']}" if s['avail_std'] is not None else "N/A"
                
                is_std_avail = (s['avail_std'] is not None and s['avail_std'] > 0)
                status = f"🟢 {s['avail_std']} SEAT(S) AVAILABLE" if is_std_avail else "🔴 SOLD OUT"
                
                print(f"   🕒 {t_str} | 🪑 Standard Seats: {std_info} | {status}")
            print()
        print(f"📅 Latest scheduled {FILM_NAME} 70mm date: {target_dates[-1] if target_dates else 'N/A'}")

    else:
        has_alerts = False

        # Alert: New Dates
        if new_dates:
            has_alerts = True
            print(f"\n🎉 NEW {FILM_NAME} 70mm DATE(S) ADDED ({len(new_dates)}):")
            for d in new_dates:
                print(f"   🗓️ {d}")
                send_ntfy_alert(
                    title="🎉 New IMAX 70mm Date Added!",
                    message=f"Cinema City Flora added a new date for {FILM_NAME} (IMAX 70mm): {d}",
                    tags="calendar,clapper,ticket"
                )

        # Alert: New Screenings
        if new_events:
            has_alerts = True
            print(f"\n🎟️ NEW SHOWTIME(S) ADDED ({len(new_events)}):")
            for ev in new_events:
                is_std_avail = (ev['avail_std'] is not None and ev['avail_std'] > 0)
                status = f"🟢 {ev['avail_std']} SEAT(S) AVAILABLE" if is_std_avail else "🔴 SOLD OUT"
                std_info = f"{ev['avail_std']}/{ev['total_std']}" if ev['avail_std'] is not None else "N/A"
                time_str = ev['time'].replace('T', ' ')
                
                print(f"   🕒 {time_str} | 🪑 Standard Seats: {std_info} | {status}")
                booking_link = ev['bookingLink'].replace("/api", "")
                print(f"      🔗 {booking_link}")
                
                send_ntfy_alert(
                    title="🎟️ New IMAX 70mm Showtime!",
                    message=f"{FILM_NAME} (IMAX 70mm)\nDate: {time_str}\nStandard Seats: {std_info}",
                    link=booking_link,
                    tags="ticket,popcorn"
                )

        # Alert: Restocked Standard Seats
        if restocked_std_events:
            has_alerts = True
            print(f"\n🔔 STANDARD SEATS BECOME AVAILABLE ({len(restocked_std_events)}):")
            for ev in restocked_std_events:
                time_str = ev['time'].replace('T', ' ')
                print(f"   🕒 {time_str} | 🪑 Standard Seats: {ev['avail_std']}/{ev['total_std']} | 🟢 AVAILABLE")

                booking_link = ev['bookingLink'].replace("/api", "")
                print(f"      🔗 {booking_link}")
                
                send_ntfy_alert(
                    title="🔔 Standard Seats Available!",
                    message=f"{FILM_NAME} (IMAX 70mm)\nShowtime: {time_str}\n{ev['avail_std']} standard seat(s) opened up!",
                    link=booking_link,
                    tags="bell,fire,ticket"
                )

        if not has_alerts:
            print(f"ℹ️ No new dates, showtimes, or seat restocks detected for {FILM_NAME} IMAX 70mm.")
            print(f"📅 Latest scheduled date currently: {target_dates[-1] if target_dates else 'N/A'}")

    # 5. Save state to state_v2.json
    new_state = {
        "last_check": now_str,
        "film_id": FILM_ID,
        "attribute": TARGET_ATTR,
        "known_dates": target_dates,
        "known_events": current_events,
    }
    save_state(new_state)

    print("\n💾 State saved to state_v2.json.")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        err_msg = f"Alerter encountered an error at {now_str}:\n{e}"
        print(f"❌ {err_msg}", file=sys.stderr)
        send_ntfy_alert(
            title="⚠️ Cinema Alerter Error",
            message=err_msg,
            priority="high",
            tags="warning,x"
        )
        sys.exit(1)

