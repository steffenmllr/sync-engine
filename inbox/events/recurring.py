from datetime import datetime
from dateutil.parser import parse as date_parse
from dateutil import tz
from dateutil.rrule import rrulestr, rrule, rruleset, MO, TU, WE, TH, FR, SA, SU

from inbox.models.event import (RecurringEvent, RecurringEventOverride,
                                InflatedEvent)

# How far in the future to unfold recurring events
FUTURE_RECURRENCE_YEARS = 1


def link_events(db_session, event):
    if isinstance(event, RecurringEvent):
        # Attempt to find my overrides
        return link_overrides(db_session, event)
    elif isinstance(event, RecurringEventOverride):
        # Attempt to find my master
        return link_master(db_session, event)


def link_overrides(db_session, event):
    # Find event instances which override this specific
    # RecurringEvent instance.
    overrides = db_session.query(RecurringEventOverride).\
        filter_by(namespace_id=event.namespace_id,
                  master_event_uid=event.uid).all()
    for o in overrides:
        if not o.master:
            o.master = event
    return overrides  # TODO check this is the dirty set


def link_master(db_session, event):
    # Find the master RecurringEvent that spawned this
    # RecurringEventOverride (may not exist if it hasn't
    # been synced yet)
    if not event.master:
        if event.master_event_uid:
            print 'looking for master at {}'.format(event.master_event_uid)
            master = db_session.query(RecurringEvent).\
                filter_by(namespace_id=event.namespace_id,
                          uid=event.master_event_uid).first()
            if master:
                event.master = master
    # Check that master has a EXDATE
    return event.master  # This may be None.


def parse_rrule(event):
    # Parse the RRULE string and return a dateutil.rrule.rrule object
    if event.rrule is not None:
        start = event.start.replace(tzinfo=tz.gettz('UTC'))
        # TODO: Deal with things that don't parse here.
        rrule = rrulestr(event.rrule, dtstart=start, compatible=True)
        return rrule
    else:
        print 'Warning tried to parse null RRULE for event {}'.format(event.id)


def parse_exdate(event):
    # Parse the EXDATE string and return a list of datetimes
    excl_dates = []
    if event.exdate:
        name, values = event.exdate.split(':', 1)
        tzinfo = tz.gettz('UTC')
        for p in name.split(';'):
            # Handle TZID in EXDATE (TODO: submit PR to python-dateutil)
            if p.startswith('TZID'):
                tzinfo = tz.gettz(p[5:])
        for v in values.split(','):
            # convert to timezone-aware dates
            t = date_parse(v).replace(tzinfo=tzinfo)
            excl_dates.append(t)
    return excl_dates


def get_start_times(event, start=None, end=None):
    # Note that rrule expansion returns timezone-aware datetimes.
    if isinstance(event, RecurringEvent):
        if not start:
            start = event.start
        start = start.replace(tzinfo=tz.gettz('UTC'))

        if not end:
            end = datetime.utcnow()
            # Check this works with Feb 29
            end = end.replace(year=end.year + FUTURE_RECURRENCE_YEARS)
        end = end.replace(tzinfo=tz.gettz('UTC'))

        excl_dates = parse_exdate(event)
        rrules = parse_rrule(event)

        if len(excl_dates) > 0:
            if not isinstance(rrules, rruleset):
                rrules = rruleset().rrule(rrules)
            map(rrules.exdate, excl_dates)

        # Needs more timezone testing
        # Return all start times between start and end, including start and
        # end themselves if they obey the rule.
        return rrules.between(start, end, inc=True)

    return [event.start]


# rrule constant values
freq_map = ('YEARLY',
            'MONTHLY',
            'WEEKLY',
            'DAILY',
            'HOURLY',
            'MINUTELY',
            'SECONDLY')

weekday_map = (MO, TU, WE, TH, FR, SA, SU)


def rrule_to_json(r):
    if not isinstance(r, rrule):
        r = parse_rrule(r)
    info = vars(r)
    j = {}
    for field, value in info.iteritems():
        if isinstance(value, tuple) and len(value) == 1:
            value = value[0]
        if field[0] == '_':
            fieldname = field[1:]
        else:
            continue
        if fieldname.startswith('by') and value is not None:
            if isinstance(value, tuple) and len(value) > 0:
                value = int(''.join([str(v) for v in value]))
            if fieldname == 'byweekday':
                value = str(weekday_map[value])
            j[fieldname] = value
        elif fieldname == 'freq':
            j[fieldname] = freq_map[value]
        elif fieldname in ['dtstart', 'interval', 'wkst',
                           'count', 'until']:  # tzinfo?
            j[fieldname] = value
    return j


# helpers to parse from the original recurring string
