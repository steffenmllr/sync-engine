import arrow
from datetime import timedelta

from inbox.models.when import Time, TimeSpan, Date, DateSpan, parse_as_when


def test_when_time():
    start_time = arrow.get('2014-09-30T15:34:00.000-07:00')
    time = {'time': start_time.timestamp}
    ts = parse_as_when(time)
    assert isinstance(ts, Time)
    assert ts.start == start_time.to('utc')
    assert ts.end == start_time.to('utc')
    assert not ts.spanning
    assert not ts.all_day
    assert ts.is_time
    assert not ts.is_date
    assert ts.delta == timedelta(hours=0)


def test_when_timespan():
    start_time = arrow.get('2014-09-30T15:34:00.000-07:00')
    end_time = arrow.get('2014-09-30T16:34:00.000-07:00')
    timespan = {'start_time': start_time.timestamp,
                'end_time': end_time.timestamp}
    ts = parse_as_when(timespan)
    assert isinstance(ts, TimeSpan)
    assert ts.start == start_time.to('utc')
    assert ts.end == end_time.to('utc')
    assert ts.spanning
    assert not ts.all_day
    assert ts.is_time
    assert not ts.is_date
    assert ts.delta == timedelta(hours=1)


def test_when_date():
    start_date = arrow.get('2014-09-30')
    date = {'date': start_date.format('YYYY-MM-DD')}
    ts = parse_as_when(date)
    assert isinstance(ts, Date)
    assert ts.start == start_date.date()
    assert ts.end == start_date.date()
    assert not ts.spanning
    assert ts.all_day
    assert not ts.is_time
    assert ts.is_date
    assert ts.delta == timedelta(days=0)


def test_when_datespan():
    start_date = arrow.get('2014-09-30')
    end_date = arrow.get('2014-10-01')
    datespan = {'start_date': start_date.format('YYYY-MM-DD'),
                'end_date': end_date.format('YYYY-MM-DD')}
    ts = parse_as_when(datespan)
    assert isinstance(ts, DateSpan)
    assert ts.start == start_date.date()
    assert ts.end == end_date.date()
    assert ts.spanning
    assert ts.all_day
    assert not ts.is_time
    assert ts.is_date
    assert ts.delta == timedelta(days=1)


def test_when_spans_arent_spans():
    # If start and end are the same, don't create a Span object
    start_date = arrow.get('2014-09-30')
    end_date = arrow.get('2014-09-30')
    datespan = {'start_date': start_date.format('YYYY-MM-DD'),
                'end_date': end_date.format('YYYY-MM-DD')}
    ts = parse_as_when(datespan)
    assert isinstance(ts, Date)

    start_time = arrow.get('2014-09-30T15:34:00.000-07:00')
    end_time = arrow.get('2014-09-30T15:34:00.000-07:00')
    timespan = {'start_time': start_time.timestamp,
                'end_time': end_time.timestamp}
    ts = parse_as_when(timespan)
    assert isinstance(ts, Time)
