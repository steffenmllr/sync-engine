import pytest
from dateutil.rrule import rrulestr
from datetime import datetime, timedelta

from inbox.events.recurring import (link_events, get_rrule, get_exdate,
                                    inflate, get_occurrences,
                                    parse_exdate, get_until, rrule_to_json)
from inbox.models.event import (Event, RecurringEvent, RecurringEventOverride)
from inbox.models.when import Date, Time, DateSpan, TimeSpan

# FIXME -> Fixture
from default_event import recurring_event


def test_rrule_parsing(db):
    (event, exception) = recurring_event(db.session)

    g = get_occurrences(event)
    print g
    assert len(g) == 5


def test_rrule_exceptions(db):
    pass


def test_inflation(db):
    (event, exception) = recurring_event(db.session)
    infl = inflate(event)
    for i in infl:
        print 'Event {}: {} - {}'.format(i.uid, i.start, i.end)
        assert i.title == event.title
        assert (i.end - i.start) == (event.end - event.start)
        assert i.start != exception.start


def test_rrule_to_json():
    # Generate more test cases!
    # http://jakubroztocil.github.io/rrule/
    r = 'RRULE:FREQ=WEEKLY;UNTIL=20140918T203000Z;BYDAY=TH'
    r = rrulestr(r, dtstart=None)
    j = rrule_to_json(r)
    assert j.get('freq') == 'WEEKLY'
    assert j.get('byweekday') == 'TH'

    r = 'FREQ=HOURLY;COUNT=30;WKST=MO;BYMONTH=1;BYMINUTE=4,2;BYSECOND=4,2'
    j = rrule_to_json(r)
    print j
    assert j.get('until') is None
    assert j.get('byminute') is 42

# def test_nonstandard_rrule_entry(db):
#     pass


# def test_cant_inflate_non_recurring(db):
#     pass


# def test_parent_appears_in_recurrences(db):
#     pass


# def test_timezones_with_rrules(db):
#     pass


# def test_ids_for_inflated_events(db):
#     pass


def test_inflated_events_cant_persist(db):
    (event, exception) = recurring_event(db.session)
    infl = inflate(event)
    for i in infl:
        db.session.add(i)
    with pytest.raises(Exception) as excinfo:
        # FIXME "No handlers could be found for logger"
        db.session.commit()
        assert 'should not be committed' in str(excinfo.value)


# def test_all_day_recurrences(db):
#     pass


# def test_modify_single_recurrence(db):
#     pass


# def test_rsvp_all_recurrences(db):
#     pass


# def test_rsvp_single_recurrence(db):
#     pass


def test_when_delta():
    # Test that the event length is calculated correctly
    ev = Event(namespace_id=0)
    # Time: minutes is 0 if start/end at same time
    ev.start = datetime(2015, 01, 01, 10, 00, 00)
    ev.end = datetime(2015, 01, 01, 10, 00, 00)
    when = ev.when
    assert isinstance(when, Time)
    assert ev.length == timedelta(minutes=0)

    # TimeSpan
    ev.start = datetime(2015, 01, 01, 10, 00, 00)
    ev.end = datetime(2015, 01, 01, 10, 30, 00)
    when = ev.when
    assert isinstance(when, TimeSpan)
    assert ev.length == timedelta(minutes=30)

    # Date: notice days is 0 if starts/ends on same day
    ev.all_day = True
    ev.start = datetime(2015, 01, 01, 00, 00, 00)
    ev.end = datetime(2015, 01, 01, 00, 00, 00)
    when = ev.when
    assert isinstance(when, Date)
    assert ev.length == timedelta(days=0)

    # DateSpan
    ev.all_day = True
    ev.start = datetime(2015, 01, 01, 10, 00, 00)
    ev.end = datetime(2015, 01, 02, 10, 00, 00)
    when = ev.when
    assert isinstance(when, DateSpan)
    assert ev.length == timedelta(days=1)


# API tests


# def test_paging_with_recurrences(db):
#     pass


# def test_before_after_recurrence(db):
#     pass


# def test_count_with_recurrence(db):
#     pass


# def test_ids_with_recurrence(db):
#     pass
