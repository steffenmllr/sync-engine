import arrow
from datetime import timedelta


def parse_as_when(raw):
    """Tries to parse a dictionary into a corresponding Date, DateSpan,
    Time, or TimeSpan instance.

    Raises
    -------
    ValueError
    """
    keys_for_type = {
        ('start_time', 'end_time'): TimeSpan,
        ('time', ): Time,
        ('start_date', 'end_date'): DateSpan,
        ('date', ): Date
    }
    given_keys = tuple(set(raw.keys()) - set('object'))
    when_type = keys_for_type.get(given_keys)
    if when_type is None:
        raise ValueError("When object had invalid keys.")
    return when_type.parse(raw)


def get_property_or_default(obj, prefix):
    # If any of the properties defined on this object match the prefix, return
    # the value of that property.
    for key, value in obj.__dict__.iteritems():
        if key.startswith(prefix):
            return value
    # Otherwise, we check that there is exactly one property, and return that
    assert len(obj.__dict__) == 1
    return value


def parse_utc(datetime):
    # Arrow can handle epoch timestamps as well as most ISO-8601 strings
    return arrow.get(datetime).to('utc')


class When(object):

    @property
    def all_day(self):
        return isinstance(self, AllDayWhen)

    @property
    def spanning(self):
        return isinstance(self, SpanningWhen)

    @property
    def is_time(self):
        return isinstance(self, Time) or isinstance(self, TimeSpan)

    @property
    def is_date(self):
        return isinstance(self, Date) or isinstance(self, DateSpan)

    @property
    def start(self):
        # Do we have a start_ property? Return that, or our only property.
        return get_property_or_default(self, 'start_')

    @property
    def end(self):
        # Do we have a start_ property? Return that, or our only property.
        return get_property_or_default(self, 'end_')


class AllDayWhen(When):
    pass


class SpanningWhen(When):
    pass


class Time(When):
    @classmethod
    def parse(cls, raw):
        try:
            time = parse_utc(raw['time'])
        except (ValueError, TypeError):
            raise ValueError("'time' parameter invalid.")
        return cls(time)

    def __init__(self, time):
        self.time = time

    @property
    def delta(self):
        return timedelta(minutes=0)


class TimeSpan(SpanningWhen):
    @classmethod
    def parse(cls, raw):
        try:
            start_time = parse_utc(raw['start_time'])
            end_time = parse_utc(raw['end_time'])
        except (ValueError, TypeError):
            raise ValueError("'start_time' or 'end_time' invalid.")
        if start_time > end_time:
            raise ValueError("'start_date' must be < 'end_date'.")
        if start_time == end_time:
            return Time(start_time)
        return cls(start_time, end_time)

    def __init__(self, start, end):
        self.start_time = start
        self.end_time = end

    @property
    def delta(self):
        return self.end_time - self.start_time


class Date(AllDayWhen):
    @classmethod
    def parse(cls, raw):
        try:
            date = parse_utc(raw['date']).date()
        except (AttributeError, ValueError, TypeError):
            raise ValueError("'date' parameter invalid.")
        return cls(date)

    def __init__(self, date):
        self.date = date

    @property
    def delta(self):
        return timedelta(days=0)


class DateSpan(AllDayWhen, SpanningWhen):
    @classmethod
    def parse(cls, raw):
        try:
            start_date = parse_utc(raw['start_date']).date()
            end_date = parse_utc(raw['end_date']).date()
        except (AttributeError, ValueError, TypeError):
            raise ValueError("'start_date' or 'end_date' invalid.")
        if start_date > end_date:
            raise ValueError("'start_date' must be < 'end_date'.")
        if start_date == end_date:
            return Date(start_date)
        return cls(start_date, end_date)

    def __init__(self, start, end):
        self.start_date = start
        self.end_date = end

    @property
    def delta(self):
        return self.end_date - self.start_date
