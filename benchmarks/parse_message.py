import sys
import random
import time
from sqlalchemy import func
from inbox.log import configure_logging
configure_logging(False)
from inbox.models import Message
from inbox.models.session import session_scope

def timed_calc_body(msg):
    # Fetch parts into memory
    msg.calculate_sanitized_body()
    start_time = time.time()
    msg.calculate_sanitized_body()
    end_time = time.time()
    return end_time - start_time


def get_calculate_body_throughput(count):
    with session_scope() as db_session:
        times = []
        max_id, = db_session.query(func.count(Message.id)).one()
        for _ in range(count):
            id = random.randrange(1, max_id)
            msg = db_session.query(Message).get(id)
            t = timed_calc_body(msg)
	    print t
	    times.append(t)
        return times


if __name__ == '__main__':
    output_filename = sys.argv[1]
    times = get_calculate_body_throughput(500)
    with open(output_filename, 'w') as f:
        f.write(str(times))
