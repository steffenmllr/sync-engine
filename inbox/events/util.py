import arrow
from collections import namedtuple
from inbox.models.when import parse_as_when


# TODO(emfree) remove (currently used in other repos)
class MalformedEventError(Exception):
    pass


def parse_datetime(datetime):
    # returns a UTC-aware datetime
    # TODO: does it have to be made naive?
    return arrow.get(datetime).to('utc')

EventTime = namedtuple('EventTime', ['start', 'end', 'all_day',
                                     'original_start'])


def when_to_event_time(raw):
    when = parse_as_when(raw)
    return EventTime(when.start, when.end, when.all_day, None)


def google_time(d):
    # google dictionaries contain either 'date' or 'dateTime'
    # along with 'timeZone': the datetime is in ISO format so is aware of
    # its UTC offset, but we want the timezone so we can handle DST, etc.
    for key, dt in d.iteritems():
        if key != 'timeZone':
            return arrow.get(dt)


def google_to_event_time(start_raw, end_raw, original_start=None):
    start = google_time(start_raw)
    end = google_time(end_raw)
    if 'date' in start_raw:
        # Google all-day events end a 'day' later than they should
        end = end.replace(days=-1)
        d = {'start_date': start.date(), 'end_date': end.date()}
    else:
        d = {'start_time': start, 'end_time': end}

    event_time = when_to_event_time(d)

    if original_start:
        event_time.original_start = google_time(original_start)

    return event_time
