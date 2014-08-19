import pickle
from gevent.queue import LifoQueue
from inbox.crispin import connection_pool
from inbox.util.debug import profile
from inbox.mailsync.backends.gmail import download_thread, gmail_download_and_commit_uids, create_gmail_message
from inbox.log import get_logger
from inbox.models import *
from inbox.models.util import db_write_lock
from inbox.models.session import session_scope
log = get_logger()

ACCOUNT_ID = 2

syncmanager_lock = db_write_lock(ACCOUNT_ID)

with open('/home/admin/pickled_stack') as f:
    stack_list = pickle.load(f)

stack = LifoQueue()
for item in stack_list:
    stack.put(item)

pool = connection_pool(ACCOUNT_ID, pool_size=1)

@profile
def profiled_download_and_commit(uid, crispin_client):
    gmail_download_and_commit_uids(crispin_client, log, '[Gmail]/All Mail',
            [uid], create_gmail_message, syncmanager_lock)


def get_download_and_commit_throughput(count):
    def null_cb(*args, **kwargs):
        pass

    with pool.get() as crispin_client:
	crispin_client.select_folder('[Gmail]/All Mail', null_cb)

        counter = 0
        while counter < count:
	    msg = stack.get_nowait()
            thread_uids = crispin_client.expand_threads([msg.g_metadata.thrid])
            thread_g_metadata = crispin_client.g_metadata(thread_uids)
            for uid in thread_uids:
                profiled_download_and_commit(uid, crispin_client)
                counter += 1


if __name__ == '__main__':
    get_download_and_commit_throughput(100)
