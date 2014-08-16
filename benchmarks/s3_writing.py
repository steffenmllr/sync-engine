import sys
import random
import time
from sqlalchemy import func
from inbox.models import *
from inbox.models.session import session_scope
from inbox.config import config
from inbox.util.debug import profile

store_on_s3 = config.get('STORE_MESSAGES_ON_S3')
if store_on_s3:
    from boto.s3.connection import S3Connection
    from boto.s3.key import Key

conn = S3Connection(config.get('AWS_ACCESS_KEY_ID'), config.get('AWS_SECRET_ACCESS_KEY'))
bucket = conn.get_bucket(config.get('MESSAGE_STORE_BUCKET_NAME'))

@profile
def timed_save_part(part):
    data = part.data
    start_time = time.time()
    try:
        if store_on_s3:
            part._save_to_s3(data)
        else:
            part._save_to_disk(data)
    except AssertionError as e:
        print e
        pass
    end_time = time.time()
    print "elapsed time {}".format(end_time - start_time)
    return end_time - start_time


def get_write_throughput(count):
    with session_scope() as db_session:
        times = []
        max_id, = db_session.query(func.count(Part.id)).one()
        for _ in range(count):
            id = random.randrange(1, max_id)
            part = db_session.query(Part).get(id)
            times.append(timed_save_part(part))
        return times


if __name__ == '__main__':
    output_filename = sys.argv[1]
    times = get_write_throughput(500)
    with open(output_filename, 'w') as f:
        f.write(str(times))
