# src/caldav_client.py

from caldav import DAVClient as _DAVClient


class CaldavEvent:
    """
    Lightweight wrapper around a python-caldav Event, exposing:
      - .url        → the event’s unique URL on the server
      - .to_ical()  → the raw iCalendar data (bytes or str)
    """
    def __init__(self, event):
        self._event = event
        # real caldav.Event has a .url attribute for its href :contentReference[oaicite:0]{index=0}
        self.url = getattr(event, 'url', None)

    def to_ical(self):
        """
        Return the underlying iCalendar data for this event.
        We first try ._raw, then .data, then fall back to serializing the vobject.
        """
        # 1) Many Events store raw bytes in ._raw
        if hasattr(self._event, '_raw') and self._event._raw:
            return self._event._raw

        # 2) The Event constructor stores initial data in .data :contentReference[oaicite:1]{index=1}
        if hasattr(self._event, 'data') and self._event.data:
            d = self._event.data
            # could be bytes or str
            return d if isinstance(d, (bytes, str)) else d.decode()

        # 3) Fallback: serialize the vobject instance
        try:
            # .instance is the vobject.Calendar object
            ser = self._event.instance.serialize()
            return ser.encode() if isinstance(ser, str) else ser
        except Exception as e:
            raise AttributeError(f"Cannot extract iCal data: {e}")


class CaldavClient:
    """
    A simple CalDAV client wrapper supporting:
      - listing calendars
      - lookup by name
      - fetching wrapped events (with .to_ical())
      - creating, updating, and deleting events by URL
    """

    def __init__(self, url: str, username: str, password: str, principal_url: str = None):
        """
        :param url: Base CalDAV URL (e.g. https://your-nextcloud/remote.php/dav/)
        :param principal_url: Optional explicit principal path
        """
        client_args = {"url": url, "username": username, "password": password}
        if principal_url:
            client_args["principal_url"] = principal_url
        self.client = _DAVClient(**client_args)

    def list_calendars(self) -> list[tuple[str, str]]:
        """
        :returns: List of (calendar_name, calendar_url)
        """
        principal = self.client.principal()
        return [(cal.name, cal.url) for cal in principal.calendars()]

    def get_calendar_by_name(self, name: str):
        """
        :returns: The calendar object for the given name, or None.
        """
        principal = self.client.principal()
        for cal in principal.calendars():
            if cal.name == name:
                return cal
        return None

    def fetch_events(self, calendar, start: str = None, end: str = None) -> list:
        """
        :returns: List of CaldavEvent wrappers for all events in the calendar.
        If start/end are provided, does a date-based search; otherwise fetches all events.
        """
        # use the unified .search() API rather than the deprecated .date_search()
        if start or end:
            raw = calendar.search(start=start, end=end)
        else:
            raw = calendar.search()
        return [CaldavEvent(evt) for evt in raw]

    def create_event(self, calendar, ical: str) -> None:
        """
        Create a new event from a raw iCalendar string.
        """
        calendar.add_event(ical)

    def update_event(self, calendar, event_url: str, ical: str) -> None:
        """
        Overwrite an existing event’s data and save it.
        """
        evt = calendar.event_by_url(event_url)
        data = ical.encode() if isinstance(ical, str) else ical
        # depending on caldav version, raw bytes may live in _raw or data
        if hasattr(evt, "_raw"):
            evt._raw = data
        else:
            evt.data = data
        evt.save()

    def delete_event(self, calendar, event_url: str) -> None:
        """
        Delete an event by its URL.
        """
        evt = calendar.event_by_url(event_url)
        evt.delete()

