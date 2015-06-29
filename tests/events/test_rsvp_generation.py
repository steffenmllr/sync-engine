# -*- coding: utf-8 -*-
import pytest
from inbox.events.ical import _generate_individual_rsvp
from tests.util.base import absolute_path


FIXTURES = './events/fixtures/'


def test_icalendar_generation(db, default_account):
    # Generate an RSVP message to one of the invites fixtures we use in the
    # iCalendar autoimport tests. We then parse back the generated file to make
    # sure the most important fields are here.

    data = None
    with open(absolute_path(FIXTURES + 'icloud_oneday_event.ics')) as fd:
        data = fd.read()

    rsvp_data = _generate_individual_rsvp("ACCEPTED", "karim@nylas.com",
                                          "Karim Hamidou", data)
    assert rsvp_data['organizer_email'] == '2_HEZDSOJZGEZTSMJZGI4TSOJRGNOIFYHPYTDQMCIAF5U2J7KGUYDTWMZSMEX4QJ23ABSXJO6RJCXDA@imip.me.com'

    for component in rsvp_data['cal'].walk():
        if component.name == "VCALENDAR":
            calendar_method = component.get('method')
            assert calendar_method == 'REPLY'

        elif component.name == "VEVENT":
            uid = component.get('uid')
            assert uid == '8153F823-B9F1-4BE0-ADFB-5FEEB01C08A9'

            summary = component.get('summary')
            assert summary == "An all-day meeting about meetings"

            location = component.get('location')
            assert location == '1, Infinite Loop'

            attendees = component.get('attendee', [])

            # the iCalendar python module doesn't return a list when
            # there's only one attendee. Go figure.
            if not isinstance(attendees, list):
                attendees = [attendees]

            assert len(attendees) == 1
            attendee = attendees[0]
            email = unicode(attendee)
            # strip mailto: if it exists
            if email.lower().startswith('mailto:'):
                email = email[7:]
            assert email == 'karim@nylas.com'

            name = attendee.params['CN']
            assert name == 'Karim Hamidou'

            assert attendee.params['PARTSTAT'] == 'ACCEPTED'

            sequence_number = component.get('SEQUENCE')
            assert sequence_number == 0
