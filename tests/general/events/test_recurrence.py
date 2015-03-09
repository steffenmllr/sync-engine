from datetime import datetime

from default_event import default_event


def test_rrule_parsing(db):
    event = default_event(db.session)
    event.start = datetime(2014, 8, 7, 20, 30, 00)
    recur = ["EXDATE;TZID=America/Los_Angeles:20140904T133000",
             "RRULE:FREQ=WEEKLY;UNTIL=20140918T203000Z;BYDAY=TH"]
    event.recurrence = str(recur)

    print event.get_instances()
    assert len(event.get_instances()) == 5
