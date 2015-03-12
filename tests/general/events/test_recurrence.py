import pytest
from dateutil import tz
from dateutil.rrule import rrulestr
from datetime import datetime, timedelta

from inbox.events.recurring import (link_events, get_start_times,
                                    parse_exdate, rrule_to_json)
from inbox.models.event import (Event, RecurringEvent, RecurringEventOverride)
from inbox.models.when import Date, Time, DateSpan, TimeSpan

# FIXME -> Fixture
from default_event import recurring_event, recurring_override


TEST_RRULE = ["RRULE:FREQ=WEEKLY;UNTIL=20140918T203000Z;BYDAY=TH"]
TEST_EXDATE = ["EXDATE;TZID=America/Los_Angeles:20140904T133000"]
TEST_EXDATE_RULE = TEST_RRULE[:]
TEST_EXDATE_RULE.extend(TEST_EXDATE)


def utcdate(*args):
    return datetime(*args, tzinfo=tz.gettz('UTC'))


def test_create_recurrence(db):
    # TODO update with emfree's new tests
    event = recurring_event(db.session, TEST_EXDATE_RULE)
    assert event.rrule is not None
    assert event.exdate is not None
    assert event.until is not None


def test_link_events(db):
    # Test that by creating a recurring event and override separately, we
    # can link them together based on UID and namespace_id
    master = recurring_event(db.session, TEST_EXDATE_RULE)
    original_start = parse_exdate(master)[0]
    override = RecurringEventOverride(original_start_time=original_start,
                                      master_event_uid=master.uid,
                                      namespace_id=master.namespace_id)
    link_events(db.session, override)
    assert override.master == master


def test_rrule_parsing(db):
    # This test event starts on Aug 7 and recurs every Thursday at 20:30
    # until Sept 18.
    # There should be 7 total occurrences including Aug 7 and Sept 18.
    event = recurring_event(db.session, TEST_RRULE)
    g = get_start_times(event)
    print g
    assert len(g) == 7


def test_rrule_exceptions(db):
    # This test event starts on Aug 7 and recurs every Thursday at 20:30
    # until Sept 18, except on September 4.
    event = recurring_event(db.session, TEST_EXDATE_RULE)
    g = get_start_times(event)
    print g
    assert len(g) == 6
    assert utcdate(2014, 9, 4, 13, 30, 00) not in g


def test_inflation(db):
    event = recurring_event(db.session, TEST_RRULE)
    infl = event.inflate()
    for i in infl:
        print 'Event {}: {} - {}'.format(i.uid, i.start, i.end)
        assert i.title == event.title
        assert (i.end - i.start) == (event.end - event.start)


def test_inflation_exceptions(db):
    event = recurring_event(db.session, TEST_RRULE)
    infl = event.inflate()
    for i in infl:
        print 'Event {}: {} - {}'.format(i.uid, i.start, i.end)
        assert i.title == event.title
        assert (i.end - i.start) == (event.end - event.start)
        assert i.start != datetime(2014, 9, 4, 13, 30, 00)


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
    event = recurring_event(db.session, TEST_RRULE)
    infl = event.inflate()
    for i in infl:
        db.session.add(i)
    with pytest.raises(Exception) as excinfo:
        # FIXME "No handlers could be found for logger" - ensure this is only
        # a test issue or fix.
        db.session.commit()
        assert 'should not be committed' in str(excinfo.value)


# def test_all_day_recurrences(db):
#     pass


def test_override_instantiated(db):
    # Test that when a recurring event has overrides, they show up as
    # RecurringEventOverrides, have links back to the parent, and don't
    # appear twice in the event list.
    event = recurring_event(db.session, TEST_EXDATE_RULE)
    override = recurring_override(db.session, event,
                                  datetime(2014, 9, 4, 20, 30, 00),
                                  datetime(2014, 9, 4, 21, 30, 00),
                                  datetime(2014, 9, 4, 22, 30, 00))
    # TODO - We should also test the creation process (init populates)
    all_events = event.all_events()
    print [e.start for e in all_events]
    assert len(all_events) == 7
    assert override in all_events


def test_override_updated(db):
    # Test that when a recurring event override is created remotely, we
    # update our EXDATE and links appropriately.
    event = recurring_event(db.session, TEST_RRULE)
    assert False

# def test_modify_inflated_recurrence(db):
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


def test_rrule_to_json():
    # Generate more test cases!
    # http://jakubroztocil.github.io/rrule/
    r = 'RRULE:FREQ=WEEKLY;UNTIL=20140918T203000Z;BYDAY=TH'
    r = rrulestr(r, dtstart=None)
    j = rrule_to_json(r)
    assert j.get('freq') == 'WEEKLY'
    assert j.get('byweekday') == 'TH'

    r = 'FREQ=HOURLY;COUNT=30;WKST=MO;BYMONTH=1;BYMINUTE=4,2;BYSECOND=4,2'
    r = rrulestr(r, dtstart=None)
    j = rrule_to_json(r)
    assert j.get('until') is None
    assert j.get('byminute') is 42


# API tests


# def test_paging_with_recurrences(db):
#     pass


# def test_before_after_recurrence(db):
#     pass


# def test_count_with_recurrence(db):
#     pass


# def test_ids_with_recurrence(db):
#     pass
