import pytest
from dateutil import tz
from dateutil.rrule import rrulestr
from datetime import datetime, timedelta

from inbox.events.recurring import (link_events, get_start_times,
                                    parse_exdate, rrule_to_json)
from inbox.models.event import Event, RecurringEvent, RecurringEventOverride
from inbox.models.when import Date, Time, DateSpan, TimeSpan


TEST_RRULE = ["RRULE:FREQ=WEEKLY;UNTIL=20140918T203000Z;BYDAY=TH"]
TEST_EXDATE = ["EXDATE;TZID=America/Los_Angeles:20140904T133000"]
TEST_EXDATE_RULE = TEST_RRULE[:]
TEST_EXDATE_RULE.extend(TEST_EXDATE)


def recurring_event(db, account, rrule, start=datetime(2014, 8, 7, 20, 30, 00),
                    end=datetime(2014, 8, 7, 21, 30, 00)):
    ev = db.session.query(Event).filter_by(uid='myuid').first()
    if ev:
        db.session.delete(ev)
    cal = account.default_calendar
    ev = Event(namespace_id=account.namespace.id,
               calendar=cal,
               title='recurring',
               description='',
               uid='myuid',
               location='',
               busy=False,
               read_only=False,
               reminders='',
               recurrence=rrule,
               start=start,
               end=end,
               all_day=False,
               provider_name='inbox',
               raw_data='',
               original_start_tz='America/Los_Angeles',
               original_start_time=None,
               master_event_uid=None,
               source='local')
    db.session.add(ev)
    db.session.commit()
    return ev


def recurring_override(db, master, original_start, start, end):
    override_uid = '{}_{}'.format(master.uid,
                                  original_start.strftime("%Y%m%dT%H%M%SZ"))
    ev = db.session.query(Event).filter_by(uid=override_uid).first()
    if ev:
        db.session.delete(ev)
    db.session.commit()
    ev = Event(original_start_time=original_start,
               master_event_uid=master.uid,
               namespace_id=master.namespace_id,
               calendar_id=master.calendar_id)
    ev.update(master)
    ev.uid = override_uid
    # This is populated from the {recurringEventId, original_start_time} data
    # TODO - maybe use that + linking logic here
    ev.start = start
    ev.end = end
    ev.master = master
    ev.master_event_uid = master.uid
    db.session.add(ev)
    db.session.commit()
    return ev


def utcdate(*args):
    return datetime(*args, tzinfo=tz.gettz('UTC'))


def test_create_recurrence(db, default_account):
    # TODO update with emfree's new tests
    event = recurring_event(db, default_account, TEST_EXDATE_RULE)
    assert isinstance(event, RecurringEvent)
    assert event.rrule is not None
    assert event.exdate is not None
    assert event.until is not None


def test_link_events(db, default_account):
    # Test that by creating a recurring event and override separately, we
    # can link them together based on UID and namespace_id
    master = recurring_event(db, default_account, TEST_EXDATE_RULE)
    original_start = parse_exdate(master)[0]
    override = Event(original_start_time=original_start,
                     master_event_uid=master.uid,
                     namespace_id=master.namespace_id,
                     source='local')
    assert isinstance(override, RecurringEventOverride)
    link_events(db.session, override)
    assert override.master == master


def test_rrule_parsing(db, default_account):
    # This test event starts on Aug 7 and recurs every Thursday at 20:30
    # until Sept 18.
    # There should be 7 total occurrences including Aug 7 and Sept 18.
    event = recurring_event(db, default_account, TEST_RRULE)
    g = get_start_times(event)
    print g
    assert len(g) == 7


def test_rrule_exceptions(db, default_account):
    # This test event starts on Aug 7 and recurs every Thursday at 20:30
    # until Sept 18, except on September 4.
    event = recurring_event(db, default_account, TEST_EXDATE_RULE)
    g = get_start_times(event)
    print g
    assert len(g) == 6
    assert utcdate(2014, 9, 4, 13, 30, 00) not in g


def test_inflation(db, default_account):
    event = recurring_event(db, default_account, TEST_RRULE)
    infl = event.inflate()
    for i in infl:
        print 'Event {}: {} - {}'.format(i.uid, i.start, i.end)
        assert i.title == event.title
        assert (i.end - i.start) == (event.end - event.start)


def test_inflation_exceptions(db, default_account):
    event = recurring_event(db, default_account, TEST_RRULE)
    infl = event.inflate()
    for i in infl:
        print 'Event {}: {} - {}'.format(i.uid, i.start, i.end)
        assert i.title == event.title
        assert (i.end - i.start) == (event.end - event.start)
        assert i.start != datetime(2014, 9, 4, 13, 30, 00)


def test_inflate_across_DST(db, default_account):
    # If we inflate a RRULE that covers a change to/from Daylight Savings Time,
    # adjust the base time accordingly to account for the new UTC offset.
    # Daylight Savings for US/PST: March 8, 2015 - Nov 1, 2015
    dst_rrule = ["RRULE:FREQ=WEEKLY;BYDAY=TU"]
    dst_event = recurring_event(db, default_account, dst_rrule,
                                start=datetime(2015, 03, 03, 03, 03, 03),
                                end=datetime(2015, 03, 03, 04, 03, 03))
    g = get_start_times(dst_event, end=datetime(2015, 03, 21))
    # In order for this event to occur at the same local time, the recurrence
    # rule should be expanded to 03:03:03 before March 8, and 02:03:03 after,
    # keeping the local time of the event consistent at 19:03.
    # This is consistent with how Google returns recurring event instances.
    local_tz = tz.gettz(dst_event.start_timezone)

    for time in g:
        if time < datetime(2015, 3, 8, tzinfo=tz.tzutc()):
            assert time.hour == 3
        else:
            assert time.hour == 2
        # Test that localizing these times is consistent
        assert time.astimezone(local_tz).hour == 19

    # Test an event that starts during local daylight savings time
    dst_event = recurring_event(db, default_account, dst_rrule,
                                start=datetime(2015, 10, 27, 02, 03, 03),
                                end=datetime(2015, 10, 27, 03, 03, 03))
    g = get_start_times(dst_event, end=datetime(2015, 11, 11))
    for time in g:
        if time > datetime(2015, 11, 1, tzinfo=tz.tzutc()):
            assert time.hour == 3
        else:
            assert time.hour == 2
        assert time.astimezone(local_tz).hour == 19

# def test_nonstandard_rrule_entry(db, default_account):
#     pass


# def test_cant_inflate_non_recurring(db, default_account):
#     pass


# def test_parent_appears_in_recurrences(db, default_account):
#     pass


# def test_timezones_with_rrules(db, default_account):
#     pass


# def test_ids_for_inflated_events(db, default_account):
#     pass


def test_inflated_events_cant_persist(db, default_account):
    event = recurring_event(db, default_account, TEST_RRULE)
    infl = event.inflate()
    for i in infl:
        db.session.add(i)
    with pytest.raises(Exception) as excinfo:
        # FIXME "No handlers could be found for logger" - ensure this is only
        # a test issue or fix.
        db.session.commit()
        assert 'should not be committed' in str(excinfo.value)


# def test_all_day_recurrences(db, default_account):
#     pass


def test_override_instantiated(db, default_account):
    # Test that when a recurring event has overrides, they show up as
    # RecurringEventOverrides, have links back to the parent, and don't
    # appear twice in the event list.
    event = recurring_event(db, default_account, TEST_EXDATE_RULE)
    override = recurring_override(db, event,
                                  datetime(2014, 9, 4, 20, 30, 00),
                                  datetime(2014, 9, 4, 21, 30, 00),
                                  datetime(2014, 9, 4, 22, 30, 00))
    # TODO - We should also test the creation process (init populates)
    all_events = event.all_events()
    assert len(all_events) == 7
    assert override in all_events


def test_override_same_start(db, default_account):
    # Test that when a recurring event has an override without a modified
    # start date (ie. the RRULE has no EXDATE for that event), it doesn't
    # appear twice in the all_events list.
    event = recurring_event(db, default_account, TEST_RRULE)
    override = recurring_override(db, event,
                                  datetime(2014, 9, 4, 20, 30, 00),
                                  datetime(2014, 9, 4, 20, 30, 00),
                                  datetime(2014, 9, 4, 21, 30, 00))
    all_events = event.all_events()
    assert len(all_events) == 7
    unique_starts = list(set([e.start for e in all_events]))
    assert len(unique_starts) == 7
    assert override in all_events


def test_override_updated(db, default_account):
    # Test that when a recurring event override is created remotely, we
    # update our EXDATE and links appropriately.
    event = recurring_event(db, default_account, TEST_RRULE)
    assert event is not None   # TODO: To be continued

# def test_modify_inflated_recurrence(db, default_account):
#     pass


# def test_rsvp_all_recurrences(db, default_account):
#     pass


# def test_rsvp_single_recurrence(db, default_account):
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


# def test_paging_with_recurrences(db, default_account):
#     pass


# def test_before_after_recurrence(db, default_account):
#     pass


# def test_count_with_recurrence(db, default_account):
#     pass


# def test_ids_with_recurrence(db, default_account):
#     pass
