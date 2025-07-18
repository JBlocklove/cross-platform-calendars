from typing import List, Dict
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import datetime

class GoogleCalendarClient:
    def __init__(self, creds_path: str, token_path: str):
        """Initialize Google Calendar API client using OAuth2 credentials."""
        pass

    def list_calendars(self) -> List[Dict]:
        """List all calendars visible to the user."""
        pass

    def get_events(self, calendar_id: str, time_min: datetime.datetime, time_max: datetime.datetime) -> List[Dict]:
        """Fetch events from Google Calendar."""
        pass

    def clear_events(self, calendar_id: str, time_min: datetime.datetime):
        """Delete all future events in the given Google calendar."""
        pass

    def upsert_event(self, calendar_id: str, event_body: Dict) -> Dict:
        """Create or update a single event."""
        pass

    def delete_event(self, calendar_id: str, event_id: str):
        """Delete a specific event."""
        pass
