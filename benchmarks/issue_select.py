"""Measure the time it takes to retrieve a single row by ID from MySQL."""
import sys
import time
import random
from sqlalchemy import func
from inbox.models import Account, Namespace, Message, Thread
from inbox.models.session import session_scope


def timed_fetch_item(cls, id):
    start_time = time.time()
    with session_scope() as db_session:
        db_session.query(cls).get(id)
    end_time = time.time()
    return end_time - start_time


def get_fetch_throughput(count, cls):
    with session_scope() as db_session:
        max_id, = db_session.query(func.count(cls.id)).one()
    times = []
    for _ in range(count):
        id = random.randrange(1, max_id)
        t = timed_fetch_item(cls, id)
	print t
        times.append(t)
    return times


if __name__ == '__main__':
    output_filename = sys.argv[1]
    # TODO(emfree): do this for more object classes
    times = get_fetch_throughput(1000, Account)
    with open(output_filename, 'w') as f:
        f.write(str(times))
