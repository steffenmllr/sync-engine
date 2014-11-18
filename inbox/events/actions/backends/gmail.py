""" Operations for syncing back local Calendar changes to Gmail. """

from inbox.events.google import GoogleEventsProvider

PROVIDER = 'gmail'

__all__ = ['remote_create', 'remote_update', 'remote_delete']


def remote_create(account, event, db_session):
    provider = GoogleEventsProvider(account.id, account.namespace.id)
    dump = provider.dump_event(event)
    service = provider._get_google_service()
    result = service.events().insert(calendarId=event.calendar.name,
                                     body=dump).execute()
    # The events crud API assigns a random uid to an event when creating it.
    # We need to update it to the value returned by the Google calendar API.
    event.uid = result['id']
    db_session.commit()


def remote_update(account, event, db_session):
    provider = GoogleEventsProvider(account.id, account.namespace.id)
    dump = provider.dump_event(event)
    service = provider._get_google_service()
    service.events().update(calendarId=event.calendar.name,
                            eventId=event.uid, body=dump).execute()


def remote_delete(account, event, db_session):
    provider = GoogleEventsProvider(account.id, account.namespace.id)
    service = provider._get_google_service()
    service.events().delete(calendarId=event.calendar.name,
                            eventId=event.uid).execute()
