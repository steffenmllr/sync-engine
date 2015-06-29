import sys
import pytz
import arrow
import traceback
from datetime import datetime, date
import icalendar
from icalendar import Calendar as iCalendar

from inbox.models.event import Event, EVENT_STATUSES
from inbox.events.util import MalformedEventError
from inbox.util.addr import canonicalize_address
from flanker import mime
from util import serialize_datetime
from timezones import timezones_table

from inbox.log import get_logger
log = get_logger()


STATUS_MAP = {'NEEDS-ACTION': 'noreply',
              'ACCEPTED': 'yes',
              'DECLINED': 'no',
              'TENTATIVE': 'maybe'}
INVERTED_STATUS_MAP = {value: key for key, value in STATUS_MAP.iteritems()}


def events_from_ics(namespace, calendar, ics_str):
    try:
        cal = iCalendar.from_ical(ics_str)
    except (ValueError, IndexError, KeyError):
        raise MalformedEventError()

    events = []

    # See: https://tools.ietf.org/html/rfc5546#section-3.2
    calendar_method = None

    for component in cal.walk():
        if component.name == "VCALENDAR":
            calendar_method = component.get('method')

        if component.name == "VTIMEZONE":
            tzname = component.get('TZID')
            assert tzname in timezones_table,\
                "Non-UTC timezone should be in table"

        if component.name == "VEVENT":
            # Make sure the times are in UTC.
            try:
                original_start = component.get('dtstart').dt
                original_end = component.get('dtend').dt
            except AttributeError:
                raise MalformedEventError("Event lacks start and/or end time")

            start = original_start
            end = original_end
            original_start_tz = None

            if isinstance(start, datetime) and isinstance(end, datetime):
                all_day = False
                original_start_tz = str(original_start.tzinfo)

                # icalendar doesn't parse Windows timezones yet
                # (see: https://github.com/collective/icalendar/issues/44)
                # so we look if the timezone isn't in our Windows-TZ
                # to Olson-TZ table.
                if original_start.tzinfo is None:
                    tzid = component.get('dtstart').params.get('TZID', None)
                    assert tzid in timezones_table,\
                        "Non-UTC timezone should be in table"

                    corresponding_tz = timezones_table[tzid]
                    original_start_tz = corresponding_tz

                    local_timezone = pytz.timezone(corresponding_tz)
                    start = local_timezone.localize(original_start)

                if original_end.tzinfo is None:
                    tzid = component.get('dtend').params.get('TZID', None)
                    assert tzid in timezones_table,\
                        "Non-UTC timezone should be in table"

                    corresponding_tz = timezones_table[tzid]
                    local_timezone = pytz.timezone(corresponding_tz)
                    end = local_timezone.localize(original_end)

            elif isinstance(start, date) and isinstance(end, date):
                all_day = True
                start = arrow.get(start)
                end = arrow.get(end)

            # Get the last modification date.
            # Exchange uses DtStamp, iCloud and Gmail LAST-MODIFIED.
            last_modified_tstamp = component.get('dtstamp')
            last_modified = None
            if last_modified_tstamp is not None:
                # This is one surprising instance of Exchange doing
                # the right thing by giving us an UTC timestamp. Also note that
                # Google calendar also include the DtStamp field, probably to
                # be a good citizen.
                if last_modified_tstamp.dt.tzinfo is not None:
                    last_modified = last_modified_tstamp.dt
                else:
                    raise NotImplementedError("We don't support arcane Windows"
                                              " timezones in timestamps yet")
            else:
                # Try to look for a LAST-MODIFIED element instead.
                # Note: LAST-MODIFIED is always in UTC.
                # http://www.kanzaki.com/docs/ical/lastModified.html
                last_modified = component.get('last-modified').dt
                assert last_modified is not None, \
                    "Event should have a DtStamp or LAST-MODIFIED timestamp"

            title = None
            summaries = component.get('summary', [])
            if not isinstance(summaries, list):
                summaries = [summaries]

            if summaries != []:
                title = " - ".join(summaries)

            description = component.get('description')
            if description is not None:
                description = unicode(description)

            event_status = component.get('status')
            if event_status is not None:
                event_status = event_status.lower()
            else:
                # Some providers (e.g: iCloud) don't use the status field.
                # Instead they use the METHOD field to signal cancellations.
                method = component.get('method')
                if method and method.lower() == 'cancel':
                    event_status = 'cancelled'
                elif calendar_method and calendar_method.lower() == 'cancel':
                    # So, this particular event was not cancelled. Maybe the
                    # whole calendar was.
                    event_status = 'cancelled'
                else:
                    # Otherwise assume the event has been confirmed.
                    event_status = 'confirmed'

            assert event_status in EVENT_STATUSES

            recur = component.get('rrule')
            if recur:
                recur = "RRULE:{}".format(recur.to_ical())

            participants = []

            organizer = component.get('organizer')
            if organizer:
                # Here's the problem. Gmail and Exchange define the organizer
                # field like this:
                #
                # ORGANIZER;CN="User";EMAIL="user@email.com":mailto:user@email.com
                # but iCloud does it like this:
                # ORGANIZER;CN=User;EMAIL=user@icloud.com:mailto:
                # random_alphanumeric_string@imip.me.com
                # so what we first try to get the EMAIL field, and only if
                # it's not present we use the MAILTO: link.
                if 'EMAIL' in organizer.params:
                    organizer = organizer.params['EMAIL']
                else:
                    organizer = unicode(organizer)
                    if organizer.startswith('mailto:'):
                        organizer = organizer[7:]

            if (namespace.account.email_address ==
                    canonicalize_address(organizer)):
                is_owner = True
            else:
                is_owner = False

            attendees = component.get('attendee', [])

            # the iCalendar python module doesn't return a list when
            # there's only one attendee. Go figure.
            if not isinstance(attendees, list):
                attendees = [attendees]

            for attendee in attendees:
                email = unicode(attendee)
                # strip mailto: if it exists
                if email.lower().startswith('mailto:'):
                    email = email[7:]
                try:
                    name = attendee.params['CN']
                except KeyError:
                    name = None

                status_map = {'NEEDS-ACTION': 'noreply',
                              'ACCEPTED': 'yes',
                              'DECLINED': 'no',
                              'TENTATIVE': 'maybe'}
                status = 'noreply'
                try:
                    a_status = attendee.params['PARTSTAT']
                    status = status_map[a_status]
                except KeyError:
                    pass

                notes = None
                try:
                    guests = attendee.params['X-NUM-GUESTS']
                    notes = "Guests: {}".format(guests)
                except KeyError:
                    pass

                participants.append({'email': email,
                                     'name': name,
                                     'status': status,
                                     'notes': notes,
                                     'guests': []})

            location = component.get('location')
            uid = str(component.get('uid'))

            event = Event(
                namespace=namespace,
                calendar=calendar,
                uid=uid,
                provider_name='ics',
                raw_data=component.to_ical(),
                title=title,
                description=description,
                location=location,
                reminders=str([]),
                recurrence=recur,
                start=start,
                end=end,
                busy=True,
                all_day=all_day,
                read_only=False,
                is_owner=is_owner,
                last_modified=last_modified,
                original_start_tz=original_start_tz,
                source='local',
                status=event_status,
                participants=participants)

            events.append(event)
    return events


def import_attached_events(db_session, account, message):
    """Import events from a file into the 'Emailed events' calendar."""

    assert account is not None
    from_addr = message.from_addr[0][1]

    # FIXME @karim - Don't import iCalendar events from messages we've sent.
    # This is only a stopgap measure -- what we need to have instead is
    # smarter event merging (i.e: looking at whether the sender is the
    # event organizer or not, and if the sequence number got incremented).
    if from_addr == account.email_address:
        return

    for part in message.attached_event_files:
        try:
            new_events = events_from_ics(account.namespace,
                                         account.emailed_events_calendar,
                                         part.block.data)
        except MalformedEventError:
            log.error('Attached event parsing error',
                      account_id=account.id, message_id=message.id)
            continue
        except (AssertionError, TypeError, RuntimeError,
                AttributeError, ValueError):
            # Kind of ugly but we don't want to derail message
            # creation because of an error in the attached calendar.
            log.error('Unhandled exception during message parsing',
                      message_id=message.id,
                      traceback=traceback.format_exception(
                                    sys.exc_info()[0],
                                    sys.exc_info()[1],
                                    sys.exc_info()[2]))
            continue

        new_uids = [event.uid for event in new_events]

        # Get the list of events which share a uid with those we received.
        existing_events = db_session.query(Event).filter(
            Event.namespace_id == account.namespace.id,
            Event.uid.in_(new_uids)).all()

        existing_events_table = {event.uid: event for event in existing_events}

        for event in new_events:
            if event.uid not in existing_events_table:
                # This is some SQLAlchemy trickery -- the events returned
                # by events_from_ics aren't bound to a session. Because of
                # this, we don't care if they get garbage-collected.
                # By associating the event to the message we make sure it
                # will be flushed to the db.
                event.message = message
            else:
                # This is an event we already have in the db.
                # Let's see if the version we have is older or newer.
                existing_event = existing_events_table[event.uid]

                if event.last_modified > existing_event.last_modified:
                    # Most RSVP replies only contain the status of the person
                    # replying. We need to merge the reply with the data we
                    # already have otherwise we'd be losing information.
                    merged_participants = existing_event.\
                        _partial_participants_merge(event)

                    # FIXME: What we really should do here is distinguish
                    # between the case where we're organizing an event and
                    # receiving RSVP messages and the case where we're just an
                    # attendant getting updates from the organizer.
                    #
                    # We don't store (yet) information about the organizer so
                    # we assume we're the creator of the event. We'll do soon
                    # though.
                    existing_event.update(event)
                    existing_event.message = message

                    # We have to do this mumbo-jumbo because MutableList does
                    # not register changes to nested elements.
                    # We could probably change MutableList to handle it (see:
                    # https://groups.google.com/d/msg/sqlalchemy/i2SIkLwVYRA/mp2WJFaQxnQJ)
                    # but this sounds a very brittle.
                    existing_event.participants = []
                    for participant in merged_participants:
                        existing_event.participants.append(participant)
                else:
                    # This is an older message but it still may contain
                    # valuable RSVP information --- remember that when someone
                    # RSVPs, the event's participant list often only
                    # contains the RSVPing person.
                    merged_participants = existing_event.\
                        _partial_participants_merge(event)

                    existing_event.participants = []
                    for participant in merged_participants:
                        existing_event.participants.append(participant)


def _generate_individual_rsvp(status, account_email, account_name,
                              ical_str):
    cal = iCalendar.from_ical(ical_str)

    # It seems that Google Calendar requires us to copy a number of fields
    # in the RVSP reply. I suppose it's for reconciling the reply with the
    # invite. - karim
    uid = None
    organizer = None
    dtstamp = serialize_datetime(datetime.utcnow())
    start = None
    end = None
    created = None
    description = None
    location = None
    summary = None
    transp = None
    timezone = None
    sequence = None

    number_of_vevent_sections = 0
    for component in cal.walk():
        if component.name == "VCALENDAR":
            calendar_method = component.get('method')

            # Is this an invite? If not we can't RSVP to it.
            if calendar_method != 'REQUEST':
                return None

        if component.name == "VTIMEZONE":
            timezone = component

        if component.name == "VEVENT":
            uid = component.get('uid')
            organizer = component.get('organizer')
            start = component.get('dtstart')
            end = component.get('dtend')
            created = component.get('created')
            description = component.get('description')
            location = component.get('location')
            summary = component.get('summary')
            transp = component.get('transp')
            sequence = component.get('sequence')

            number_of_vevent_sections += 1

    # This is a sanity check. We shouldn't receive an empty event or
    # multiple events.
    if number_of_vevent_sections != 1:
        log.error('number_of_vevent_sections != 1',
                  number=number_of_vevent_sections, email=account_email,
                  ical_str=ical_str)
        return None

    if organizer is None or uid is None:
        return None

    cal = iCalendar()
    cal.add('PRODID', '-//Nylas sync engine//nylas.com//')
    cal.add('METHOD', 'REPLY')
    cal.add('VERSION', '2.0')
    cal.add('CALSCALE', 'GREGORIAN')

    if timezone is not None:
        cal.add_component(timezone)

    event = icalendar.Event()
    event['uid'] = str(uid)
    event['organizer'] = organizer

    event['sequence'] = sequence 
    event['X-MICROSOFT-CDO-APPT-SEQUENCE'] = event['sequence']

    event['status'] = 'CONFIRMED'
    event['last-modified'] = dtstamp
    event['dtstamp'] = dtstamp
    event['created'] = created
    event['dtstart'] = start
    event['dtend'] = end
    event['description'] = description
    event['location'] = location
    event['summary'] = summary
    event['transp'] = transp

    attendee = icalendar.vCalAddress('MAILTO:{}'.format(account_email))
    attendee.params['cn'] = account_name
    attendee.params['partstat'] = status
    event.add('attendee', attendee, encode=0)
    cal.add_component(event)

    organizer_email = unicode(organizer)
    if 'MAILTO:' in organizer_email or 'mailto:' in organizer_email:
        organizer_email = organizer_email[7:]

    ret = {}
    ret["cal"] = cal
    ret["organizer_email"] = organizer_email

    return ret


def generate_rsvp(message, participant, account_email, account_name):
    # Generates an iCalendar file to RSVP to an invite.
    status = INVERTED_STATUS_MAP.get(participant["status"])
    for part in message.attached_event_files:
        # Note: we return as soon as we've found an iCalendar file because
        # most invite emails contain multiple copies of the same file, in the
        # body and as an attachment.
        rsvp = _generate_individual_rsvp(status, account_email,
                                         account_name, part.block.data)
        if rsvp is not None:
            return rsvp


def send_rsvp(ical_data, event, body_text, account):
    from inbox.sendmail.base import get_sendmail_client
    ical_file = ical_data["cal"]
    rsvp_to = ical_data["organizer_email"]
    ical_txt = ical_file.to_ical()

    sendmail_client = get_sendmail_client(account)

    msg = mime.create.multipart('mixed')

    body = mime.create.multipart('alternative')
    body.append(
        mime.create.text('html', body_text),
        mime.create.text('calendar;method=REPLY', ical_txt))

    attachment = mime.create.attachment(
                     'text/calendar',
                     ical_txt,
                     'invite.ics',
                     disposition='attachment')

    msg.append(body)
    msg.append(attachment)

    msg.headers['To'] = rsvp_to
    msg.headers['Reply-To'] = account.email_address
    msg.headers['From'] = account.email_address
    msg.headers['Subject'] = 'RSVP to "{}"'.format(event.title)

    final_message = msg.to_string()
    sendmail_client._send([rsvp_to], final_message)
