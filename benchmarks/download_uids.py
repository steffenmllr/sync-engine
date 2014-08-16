import sys
import random
import time
<<<<<<< HEAD
from inbox.log import get_logger, configure_logging
from inbox.crispin import connection_pool
from inbox.models.session import session_scope
from inbox.models.backends.imap import ImapUid
from inbox.mailsync.backends.imap import safe_download
<<<<<<< HEAD
configure_logging(False)
log = get_logger()

ACCOUNT_ID = 2
SHUFFLE = False


def timed(func):
    def wrapper(*args, **kwargs):
        start_time = time.time()
        func(*args, **kwargs)
        end_time = time.time()
        return end_time - start_time
    return wrapper

with session_scope() as db_session:
    uids = [u for u, in db_session.query(ImapUid.msg_uid).filter_by(
        account_id=ACCOUNT_ID).all()]
    if SHUFFLE:
	    random.shuffle(uids)
pool = connection_pool(ACCOUNT_ID, pool_size=1)


@timed
def timed_uid_download(crispin_client, uid):
    print "downloading uid {}".format(uid)
    start_time = time.time()
    r = safe_download(crispin_client, log, [uid])
    if not r:
        return None
    end_time = time.time()
    print "elapsed time {}".format(end_time-start_time)
    return end_time - start_time


def get_download_throughput(uid_count):
    def null_cb(*args, **kwargs):
        pass

    times = []
    with pool.get() as crispin_client:
        crispin_client.select_folder('[Gmail]/All Mail', null_cb)
        for uid in uids[:uid_count]:
            t = timed_uid_download(crispin_client, uid)
            if t is not None:
                times.append(t)
    return times


if __name__ == '__main__':
    output_filename = sys.argv[1]
    times = get_download_throughput(500)
    with open(output_filename, 'w') as f:
        f.write(str(times))
