from datetime import datetime, timedelta
from inbox.models import Event, Account
from inbox.models.event import RecurringEvent, RecurringEventOverride

ACCOUNT_ID = 1
NAMESPACE_ID = 1
START = datetime.utcnow()
END = START + timedelta(0, 1)


def default_calendar(db_session):
    account = db_session.query(Account).filter(
        Account.id == ACCOUNT_ID).one()
    return account.default_calendar


def default_event(db_session):
    cal = default_calendar(db_session)
    ev = Event(namespace_id=NAMESPACE_ID,
               calendar=cal,
               title='title',
               description='',
               location='',
               busy=False,
               read_only=False,
               reminders='',
               recurrence='',
               start=START,
               end=END,
               all_day=False,
               provider_name='inbox',
               raw_data='',
               source='local')

    db_session.add(ev)
    db_session.commit()
    return ev


def recurring_event(db_session, rrule):
    ev = db_session.query(RecurringEvent).filter_by(uid='myuid').first()
    if ev:
        return ev
    cal = default_calendar(db_session)
    ev = RecurringEvent(namespace_id=NAMESPACE_ID,
                        calendar=cal,
                        title='recurring',
                        description='',
                        uid='myuid',
                        location='',
                        busy=False,
                        read_only=False,
                        reminders='',
                        recurrence=str(rrule),
                        start=datetime(2014, 8, 7, 20, 30, 00),
                        end=datetime(2014, 8, 7, 21, 30, 00),
                        all_day=False,
                        provider_name='inbox',
                        raw_data='',
                        source='local')
    db_session.add(ev)
    db_session.commit()
    return ev


def recurring_override(db_session, master, original_start, start, end):
    ev = db_session.query(RecurringEventOverride).\
        filter_by(uid='recuid').first()
    if ev:
        return ev
    ev = RecurringEventOverride(original_start_time=original_start,
                                master_event_uid=master.uid)
    ev.copy_from(master)
    ev.uid = 'recuid'
    # This is populated from the {recurringEventId, original_start_time} data
    # TODO - maybe use that + linking logic here
    ev.start = start
    ev.end = end
    ev.master = master
    ev.master_event_uid = master.uid
    db_session.add(ev)
    db_session.commit()
    return ev
