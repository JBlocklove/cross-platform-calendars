# src/sync.py

import os
import json
import logging
from datetime import datetime, timezone
from icalendar import Calendar as ICalendar, Event
from caldav.lib.error import PutError

from .caldav_client import CaldavClient, CaldavEvent

logger = logging.getLogger(__name__)


def _parse_ical_metadata(ical_bytes):
    """
    Parse out the UID and a `datetime` for LAST-MODIFIED (or DTSTAMP if no LAST-MODIFIED).
    Returns (uid: str, last_mod: datetime).
    """
    cal = ICalendar.from_ical(ical_bytes)
    for comp in cal.walk():
        if comp.name == "VEVENT":
            uid = str(comp.get("UID"))
            lm = comp.get("LAST-MODIFIED") or comp.get("DTSTAMP")
            last_mod = lm.dt if hasattr(lm, "dt") else lm
            if not isinstance(last_mod, datetime):
                raise ValueError(f"Could not parse timestamp for UID={uid}")
            return uid, last_mod
    raise ValueError("No VEVENT found in ical data")


def sync_caldav_caldav(
    client_a: CaldavClient,
    cal_name_a: str,
    client_b: CaldavClient,
    cal_name_b: str,
    state_path: str = "sync_state.json",
):
    """
    Two-way sync between two CalDAV calendars.
    - Creates new events on the other side.
    - Updates older copies based on LAST-MODIFIED/DTSTAMP.
    - Deletes events if they were removed on one side since last sync.
    """

    # 1) Load previous state if present
    if os.path.exists(state_path):
        with open(state_path, "r") as f:
            old_state = json.load(f)
            old_state = {
                uid: datetime.fromisoformat(ts) for uid, ts in old_state.items()
            }
    else:
        old_state = {}

    # 2) Look up the calendars
    cal_a = client_a.get_calendar_by_name(cal_name_a)
    cal_b = client_b.get_calendar_by_name(cal_name_b)
    if not cal_a or not cal_b:
        raise ValueError(f"One of the calendars not found: {cal_name_a}, {cal_name_b}")

    # 3) Fetch events
    evts_a = client_a.fetch_events(cal_a)
    evts_b = client_b.fetch_events(cal_b)

    meta_a = { }
    for e in evts_a:
        uid, lm = _parse_ical_metadata(e.to_ical())
        meta_a[uid] = (lm, e)

    meta_b = { }
    for e in evts_b:
        uid, lm = _parse_ical_metadata(e.to_ical())
        meta_b[uid] = (lm, e)

    # 4) Reconcile
    all_uids = set(old_state) | set(meta_a) | set(meta_b)
    new_state = {}

    for uid in all_uids:
        in_a, in_b = uid in meta_a, uid in meta_b
        prev = uid in old_state

        # a) Deleted on one side
        if prev and in_a and not in_b:
            logger.info(f"UID={uid} deleted from B → deleting in A")
            client_a.delete_event(cal_a, meta_a[uid][1].url)
            continue
        if prev and in_b and not in_a:
            logger.info(f"UID={uid} deleted from A → deleting in B")
            client_b.delete_event(cal_b, meta_b[uid][1].url)
            continue

        # b) New on one side
        if not prev and in_a and not in_b:
            logger.info(f"UID={uid} new in A → creating in B")
            ical = meta_a[uid][1].to_ical()
            client_b.create_event(cal_b, ical)
            new_state[uid] = meta_a[uid][0].isoformat()
            continue
        if not prev and in_b and not in_a:
            logger.info(f"UID={uid} new in B → creating in A")
            ical = meta_b[uid][1].to_ical()
            client_a.create_event(cal_a, ical)
            new_state[uid] = meta_b[uid][0].isoformat()
            continue

        # c) Present on both → pick the newer
        if in_a and in_b:
            lm_a, evt_a = meta_a[uid]
            lm_b, evt_b = meta_b[uid]
            if lm_a > lm_b:
                logger.info(f"UID={uid} newer in A ({lm_a}) → updating B ({lm_b})")
                client_b.update_event(cal_b, evt_b.url, evt_a.to_ical())
                new_state[uid] = lm_a.isoformat()
            elif lm_b > lm_a:
                logger.info(f"UID={uid} newer in B ({lm_b}) → updating A ({lm_a})")
                client_a.update_event(cal_a, evt_a.url, evt_b.to_ical())
                new_state[uid] = lm_b.isoformat()
            else:
                new_state[uid] = lm_a.isoformat()
            continue

        # d) If it’s gone from both, drop it

    # 5) Persist state
    with open(state_path, "w") as f:
        json.dump(new_state, f, indent=2)

    logger.info("Full two‐way sync complete")


def _parse_dt_range(ical_bytes):
    cal = ICalendar.from_ical(ical_bytes)
    for comp in cal.walk():
        if comp.name == "VEVENT":
            return comp.get("DTSTART").dt, comp.get("DTEND").dt
    raise ValueError("No VEVENT for dt parsing")


def _build_busy_ical(uid: str, dtstart, dtend) -> bytes:
    cal = ICalendar()
    cal.add("prodid", "-//busy-sync//")
    cal.add("version", "2.0")
    evt = Event()
    evt.add("uid", uid)
    evt.add("dtstamp", datetime.now(timezone.utc))
    evt.add("dtstart", dtstart)
    evt.add("dtend", dtend)
    evt.add("summary", "Busy")
    cal.add_component(evt)
    return cal.to_ical()

def sync_caldav_busy(
    client_source: CaldavClient,
    cal_name_source: str,
    client_target: CaldavClient,
    cal_name_target: str,
    state_path: str = "busy_sync_state.json",
):
    """
    One-way “busy-only” sync A→B, plus:
      • two-way time-patching of Busy placeholders
      • delete‐on‐B and delete‐on‐A both propagate correctly
    """

    # 1) LOAD previous state
    if os.path.exists(state_path):
        with open(state_path, "r") as f:
            data = json.load(f)
        old_synced     = {uid: datetime.fromisoformat(ts)
                          for uid, ts in data.get("synced", {}).items()}
        old_busy       = set(data.get("busy_uids", []))
        tombstones     = set(data.get("tombstones", []))
        old_real_uids  = set(data.get("real_uids", []))
    else:
        old_synced = {}
        old_busy = set()
        tombstones = set()
        old_real_uids = set()

    # 2) LOOK UP calendars
    cal_src = client_source.get_calendar_by_name(cal_name_source)
    cal_tgt = client_target.get_calendar_by_name(cal_name_target)
    if not cal_src or not cal_tgt:
        raise ValueError(f"Calendars not found: {cal_name_source}, {cal_name_target}")

    # 3) FETCH all events
    src_events = client_source.fetch_events(cal_src)
    tgt_events = client_target.fetch_events(cal_tgt)

    # 4a) BUILD src_meta: A → uid → (event_obj, raw_ical, last_mod)
    src_meta = {}
    for e in src_events:
        raw = e.to_ical()
        uid, lm = _parse_ical_metadata(raw)
        src_meta[uid] = (e, raw, lm)

    # 4b) BUILD real_meta + busy_meta + current real_uids
    real_meta = {}
    busy_meta = {}
    real_uids = set()
    for e in tgt_events:
        raw = e.to_ical()
        uid, lm = _parse_ical_metadata(raw)
        if _get_summary(raw) != "Busy":
            real_uids.add(uid)
            real_meta[uid] = (e, raw, lm)
        else:
            busy_meta[uid] = (e, raw, lm)

    # ─── NEW BLOCK ─── propagate deletions _on A_ for real B-events ─────────────
    # If a UID was a real B-event last run, but no longer in A, delete it in B.
    deleted_on_a = old_real_uids - set(src_meta.keys())
    for uid in deleted_on_a:
        if uid in real_meta:
            e_tgt, _, _ = real_meta[uid]
            client_target.delete_event(cal_tgt, e_tgt.url)
        tombstones.add(uid)
    # ────────────────────────────────────────────────────────────────────────────

    # 5) PROPAGATE deletions _on B_ of real events → delete in A + tombstone
    deleted_real = old_real_uids - real_uids
    for uid in deleted_real:
        if uid in src_meta:
            e_src, _, _ = src_meta.pop(uid)
            client_source.delete_event(cal_src, e_src.url)
        tombstones.add(uid)

    # 6) RECORD tombstones for deleted Busy placeholders in B → delete in A
    deleted_busy = old_busy - set(busy_meta.keys())
    for uid in deleted_busy:
        if uid in src_meta:
            e_src, _, _ = src_meta.pop(uid)
            client_source.delete_event(cal_src, e_src.url)
        tombstones.add(uid)

    # 7) RECONCILE A→B busy placeholders
    all_uids   = set(old_synced) | set(src_meta) | set(busy_meta)
    new_synced = {}
    new_busy   = set()

    for uid in sorted(all_uids):
        in_src  = uid in src_meta
        in_busy = uid in busy_meta

        # never touch real events in B
        if uid in real_uids:
            continue

        # deletion upstream in A → delete Busy placeholder in B
        if uid in old_synced and not in_src and in_busy:
            e_tgt, _, _ = busy_meta[uid]
            client_target.delete_event(cal_tgt, e_tgt.url)
            tombstones.discard(uid)
            continue

        # new in A → create Busy, unless tombstoned
        if in_src and not in_busy:
            if uid in tombstones:
                continue
            _, raw_src, lm_src = src_meta[uid]
            dtstart, dtend = _parse_dt_range(raw_src)
            busy_ical = _build_busy_ical(uid, dtstart, dtend)
            try:
                client_target.create_event(cal_tgt, busy_ical)
            except PutError:
                # collision → fallback
                for e in tgt_events:
                    if _parse_ical_metadata(e.to_ical())[0] == uid:
                        client_target.update_event(cal_tgt, e.url, busy_ical)
                        break
            new_synced[uid] = lm_src.isoformat()
            new_busy.add(uid)
            continue

        # both exist → two-way timestamp compare
        if in_src and in_busy:
            e_src, raw_src, lm_src = src_meta[uid]
            e_tgt, raw_tgt, lm_tgt = busy_meta[uid]

            if lm_src > lm_tgt:
                # A moved/rescheduled → update Busy in B
                dtstart, dtend = _parse_dt_range(raw_src)
                busy_ical = _build_busy_ical(uid, dtstart, dtend)
                client_target.update_event(cal_tgt, e_tgt.url, busy_ical)
                new_synced[uid] = lm_src.isoformat()
                new_busy.add(uid)

            elif lm_tgt > lm_src:
                # Busy moved on B → patch A event
                dtstart, dtend = _parse_dt_range(raw_tgt)
                updated = _update_src_ical(raw_src, dtstart, dtend)
                client_source.update_event(cal_src, e_src.url, updated)
                new_synced[uid] = lm_tgt.isoformat()
                new_busy.add(uid)

            else:
                # unchanged
                new_synced[uid] = lm_src.isoformat()
                new_busy.add(uid)

            continue

        # else: fully gone → drop

    # 8) PERSIST new state
    with open(state_path, "w") as f:
        json.dump({
            "synced":    new_synced,
            "busy_uids": list(new_busy),
            "tombstones": list(tombstones),
            "real_uids": list(real_uids),
        }, f, indent=2)

    logger.info("Busy-sync complete")

# — Helpers for SUMMARY & in-place patch of DTSTART/DTEND —

def _get_summary(raw_ical: bytes) -> str:
    cal = ICalendar.from_ical(raw_ical)
    for comp in cal.walk():
        if comp.name == "VEVENT":
            return comp.get("SUMMARY")
    return ""

def _update_src_ical(raw: bytes, new_start: datetime, new_end: datetime) -> bytes:
    cal = ICalendar.from_ical(raw)
    for comp in cal.walk():
        if comp.name == "VEVENT":
            comp["DTSTART"].dt = new_start
            comp["DTEND"].dt   = new_end
    return cal.to_ical()

def sync_caldav_full_oneway(
    client_source: CaldavClient,
    cal_name_source: str,
    client_target: CaldavClient,
    cal_name_target: str,
    state_path: str = "full_sync_state.json",
):
    """
    One-way full sync from source → target, skipping SUMMARY="Busy" and
    never deleting A-only events that it didn’t create.

    Internally versioned: if state_path exists but isn’t marked for
    'full_oneway', it will be ignored (treat as first run).
    """
    # 1) Load previous state *only* if it was created by full_oneway
    old_state = {}
    if os.path.exists(state_path):
        try:
            data = json.load(open(state_path, "r"))
            if data.get("__mode") == "full_oneway":
                for uid, ts in data.items():
                    if uid == "__mode":
                        continue
                    old_state[uid] = datetime.fromisoformat(ts)
            else:
                logger.info("Ignoring mismatched state file (not full_oneway mode)")
        except Exception as e:
            logger.warning(f"Could not read full_oneway state, starting fresh: {e}")

    # 2) Lookup calendars
    cal_src = client_source.get_calendar_by_name(cal_name_source)
    cal_tgt = client_target.get_calendar_by_name(cal_name_target)
    if not cal_src or not cal_tgt:
        raise ValueError(f"Calendars not found: {cal_name_source}, {cal_name_target}")

    # 3) Fetch events
    src_events = client_source.fetch_events(cal_src)
    tgt_events = client_target.fetch_events(cal_tgt)

    # 4) Build metadata (skip Busy)
    meta_src = {}
    for e in src_events:
        raw = e.to_ical()
        cal = ICalendar.from_ical(raw)
        summ = next((c.get("SUMMARY") for c in cal.walk() if c.name=="VEVENT"), None)
        if summ == "Busy":
            continue
        uid, lm = _parse_ical_metadata(raw)
        meta_src[uid] = (lm, raw)

    meta_tgt = {}
    for e in tgt_events:
        raw = e.to_ical()
        uid, lm = _parse_ical_metadata(raw)
        meta_tgt[uid] = (lm, e)

    # 5) Reconcile one-way: create/update from src → tgt, and only delete
    #    events that we *know* we created (i.e. those in old_state).
    new_state = {}
    all_uids = set(old_state) | set(meta_src) | set(meta_tgt)

    for uid in all_uids:
        in_src = uid in meta_src
        in_tgt = uid in meta_tgt
        prev   = uid in old_state

        # a) deletion only if we previously synced it (prev) but now it's gone from src
        if prev and not in_src and in_tgt:
            _, te = meta_tgt[uid]
            logger.info(f"[full_oneway] Deleting {uid} from target (deleted upstream)")
            client_target.delete_event(cal_tgt, te.url)
            continue

        # b) new in src → create in tgt
        if in_src and not in_tgt:
            lm, raw = meta_src[uid]
            logger.info(f"[full_oneway] Creating {uid} in target")
            client_target.create_event(cal_tgt, raw)
            new_state[uid] = lm.isoformat()
            continue

        # c) update in src → overwrite in tgt
        if in_src and in_tgt:
            lm_src, raw = meta_src[uid]
            lm_tgt, te = meta_tgt[uid]
            if lm_src > lm_tgt:
                logger.info(f"[full_oneway] Updating {uid} in target")
                client_target.update_event(cal_tgt, te.url, raw)
                new_state[uid] = lm_src.isoformat()
            else:
                new_state[uid] = lm_tgt.isoformat()
            continue

        # any uid only in tgt and not prev: we skip it entirely (i.e. we don't delete)
        # and we don't include it in new_state

    # 6) Persist versioned state
    to_save = {"__mode": "full_oneway"}
    to_save.update(new_state)
    with open(state_path, "w") as f:
        json.dump(to_save, f, indent=2)

    logger.info("Full one‐way sync complete (skipped Busy, preserved A‐only)")
