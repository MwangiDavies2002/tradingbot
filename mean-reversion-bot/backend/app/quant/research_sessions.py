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


def market_is_open(timestamp, calendar):
    """Apply an asset's timezone, weekly schedule, holidays and date overrides."""
    local = datetime.fromtimestamp(timestamp, ZoneInfo(calendar.timezone))
    day = local.date()
    minute = local.hour * 60 + local.minute
    if local.weekday() not in calendar.weekdays or day in calendar.holidays:
        return False
    special = calendar.special_hours.get(day)
    opening = special.open_minute if special else calendar.open_minute
    if special:
        closing = special.close_minute
    else:
        closing = calendar.early_closes.get(day, calendar.close_minute)
    return opening <= minute < closing


def effective_bounds(timestamp, session, calendar):
    """Intersect a named session with the asset calendar, including date-specific opens."""
    start, end = bounds(timestamp, session)
    zone = ZoneInfo(calendar.timezone)
    local_day = datetime.fromtimestamp(start, zone).date()
    if local_day.weekday() not in calendar.weekdays or local_day in calendar.holidays:
        return start, start
    special = calendar.special_hours.get(local_day)
    opening = special.open_minute if special else calendar.open_minute
    closing = special.close_minute if special else calendar.early_closes.get(local_day, calendar.close_minute)
    market_open = datetime.combine(local_day, time(opening // 60, opening % 60), zone).timestamp()
    close_day = local_day if closing < 1440 else local_day + timedelta(days=1)
    close_minute = 0 if closing == 1440 else closing
    market_close = datetime.combine(close_day, time(close_minute // 60, close_minute % 60), zone).timestamp()
    return max(start, int(market_open)), min(end, int(market_close))
