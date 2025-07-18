# Cross-Platform Calendar Sync

---
### Note: This whole program so far has been vibe coded. I just wanted to see if it would actually be any quicker or easier than figuring it out myself. Maybe quicker, but it was still a good chunk of time, but definitely not any easier. Debugging this code was a nightmare and ChatGPT's solution is usually to make the code **more** complicated when the solution is often to remove superfluous logic. So yeah, fun experiment but I'm gonna go back to writing my own stuff.
---

A small Python toolkit to synchronise events between any two CalDAV calendars (e.g. Nextcloud, other CalDAV services) with two modes:

1. **Full two-way sync**
   Mirror every non-“Busy” event both directions (A ↔ B), creating, updating or deleting by UID & timestamp.

2. **Busy-only one-way sync**
   Push only opaque “Busy” placeholders from **A → B** (so your “busy/free” blocks show up in Google or another calendar) while leaving real B events untouched.

---

## 🚀 Installation

1. Clone this repo:

   ```bash
   git clone https://github.com/JBlocklove/cross-platform-calendars.git
   cd cross-platform-calendars
   ```

2. (Optional) Create a virtualenv:

   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

---

## ⚙️ Configuration

Create a YAML file in `$XDG_CONFIG_HOME/cal-sync/config.yaml` with your CalDAV credentials and calendar names. A simple example is given in [the config directory](./config/config.yaml).

---

## 📂 Directory Structure

```
.
├── src/
│   ├── caldav_client.py      # CalDAV wrapper (list, fetch, create, update, delete)
│   └── sync.py               # sync_caldav_caldav, sync_caldav_busy, sync_caldav_full_oneway
├── main.py
├── requirements.txt
└── README.md
```

---

## 📖 How it works

### 1. `CaldavClient` (`src/caldav_client.py`)

A thin wrapper around `caldav.DAVClient` that exposes:

- **`list_calendars() → List[(name, url)]`**
- **`get_calendar_by_name(name) → CalendarObject | None`**
- **`fetch_events(calendar) → List[CaldavEvent]`**
- **`create_event(calendar, ical_str: bytes|str)`**
- **`update_event(calendar, event_url, ical_str)`**
- **`delete_event(calendar, event_url)`**

`CaldavEvent` wraps the raw event and exposes:
```python
event.url       # unique href
event.to_ical() # raw iCalendar bytes/str
```

---

### 2. Full two-way sync (`sync_caldav_caldav` in `src/sync.py`)

```python
sync_caldav_caldav(
    client_a: CaldavClient,
    cal_name_a: str,
    client_b: CaldavClient,
    cal_name_b: str,
    state_path: str = "full_sync_state.json",
)
```

- **Creates** new events on the other side.
- **Updates** the older copy by comparing LAST-MODIFIED (or DTSTAMP).
- **Deletes** events that were removed upstream.

It keeps a JSON state file mapping UID → last-mod timestamp to track deltas.

---

### 3. Busy-only one-way sync (`sync_caldav_busy` in `src/sync.py`)

```python
sync_caldav_busy(
    client_source: CaldavClient,
    cal_name_source: str,
    client_target: CaldavClient,
    cal_name_target: str,
    state_path: str = "busy_sync_state.json",
)
```

- **Scans** every event in **source** (A), and for each UID creates or updates an opaque “Busy” VEVENT in **target** (B) with identical start/end.
- **Deletes** placeholders if the source event was removed.
- **Leaves** any real (non-“Busy”) events in B untouched.

Also tracks state by UID → last-mod in its own JSON file.

---

### 4. Full one-way sync ignoring “Busy” (`sync_caldav_full_oneway` in `src/sync.py`)

```python
sync_caldav_full_oneway(
    client_source: CaldavClient,
    cal_name_source: str,
    client_target: CaldavClient,
    cal_name_target: str,
    state_path: str = "full_sync_state.json",
)
```

Like the two-way version but:

- **Skips** any event with SUMMARY == “Busy” in the source.
- **Only** creates/updates/deletes events it has itself synced before (by looking at its state).
- **Never** deletes A-only events that originated elsewhere.

