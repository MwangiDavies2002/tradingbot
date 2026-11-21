"""Named research windows. These are transparent presets, not exchange calendars."""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


WINDOWS = {
    'asia': ('Asia/Tokyo', time(9, 0), time(15, 0)),
    'london': ('Europe/London', time(8, 0), time(16, 30)),
    'new_york': ('America/New_York', time(9, 30), time(16, 0)),
}


def bounds(timestamp, session):
    zone_name, opening, closing = WINDOWS[session]
    zone = ZoneInfo(zone_name)
    day = datetime.fromtimestamp(timestamp, zone).date()
    start = datetime.combine(day, opening, zone)
    end = datetime.combine(day, closing, zone)
    return int(start.timestamp()), int(end.timestamp())


def in_window(timestamp, session):
    start, end = bounds(timestamp, session)
    return start <= timestamp < end and datetime.fromtimestamp(timestamp, ZoneInfo(WINDOWS[session][0])).weekday() < 5


def active_sessions(timestamp):
    return [name for name in WINDOWS if in_window(timestamp, name)]


def _session_intervals(day, calendar):
    if day in calendar.holidays:
        return []
    special = calendar.special_hours.get(day)
    if special:
        return [(special.open_minute, special.close_minute)]
    if calendar.weekly_hours:
        windows = calendar.weekly_hours.get(day.weekday(), [])
        early_close = calendar.early_closes.get(day)
        return [(window.open_minute, min(window.close_minute, early_close) if early_close else window.close_minute)
                for window in windows
                if early_close is None or window.open_minute < early_close]
    if day.weekday() not in calendar.weekdays:
        return []
    return [(calendar.open_minute, calendar.early_closes.get(day, calendar.close_minute))]


def market_is_open(timestamp, calendar):
    """Apply an asset's timezone, weekly schedule, holidays and date overrides."""
    if not calendar.confirmed and not calendar.weekly_hours and not calendar.weekdays:
        # Keep observed candles available for exploratory analysis, but the
        # completeness audit will not infer an instrument calendar.
        return True
    local = datetime.fromtimestamp(timestamp, ZoneInfo(calendar.timezone))
    minute = local.hour * 60 + local.minute
    return any(opening <= minute < closing for opening, closing in _session_intervals(local.date(), calendar))


def effective_bounds(timestamp, session, calendar):
    """Intersect a named session with the asset calendar, including date-specific opens."""
    start, end = bounds(timestamp, session)
    zone = ZoneInfo(calendar.timezone)
    local_day = datetime.fromtimestamp(start, zone).date()
    intersections = []
    for opening, closing in _session_intervals(local_day, calendar):
        open_at = datetime.combine(local_day, time(opening // 60, opening % 60), zone).timestamp()
        close_day = local_day if closing < 1440 else local_day + timedelta(days=1)
        close_minute = 0 if closing == 1440 else closing
        close_at = datetime.combine(close_day, time(close_minute // 60, close_minute % 60), zone).timestamp()
        if max(start, open_at) < min(end, close_at):
            intersections.append((max(start, int(open_at)), min(end, int(close_at))))
    return intersections[0] if intersections else (start, start)
