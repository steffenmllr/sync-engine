#!/usr/bin/env python
""" Encrypt unencrypted disk/s3 blocks. """
from collections import defaultdict

from gevent import monkey
monkey.patch_all()

import gevent
from gevent.pool import Group
from gevent.queue import JoinableQueue

from sqlalchemy.sql import text

from inbox.util.startup import preflight
from inbox.ignition import main_engine
from inbox.models.session import session_scope
from inbox.models import Block
from inbox.models.util import EncryptionScheme


class EncryptionManager(object):
    def __init__(self, pool_size=50):
        self.pool_size = pool_size
        self.worker_pool = Group()

    def run(self):
        query = """
        SELECT id, data_sha256 from block WHERE encryption_scheme=0
        """

        hashes = defaultdict(list)

        with engine.connect() as dbconn:
            for id_, sha256 in dbconn.execute(text(query)):
                hashes[sha256].append(id_)

        self.queue = JoinableQueue(items=hashes.items())
        print '\n[Manager] len(queue): ', self.queue.qsize()

        for i in range(self.pool_size):
            worker = EncryptionWorker(i, self.queue)

            self.worker_pool.add(worker)
            worker.start()

        self.queue.join()


class EncryptionWorker(gevent.Greenlet):
    """A greenlet spawned to encrypt a subset of s3 hashes."""
    def __init__(self, worker_id, queue):
        self.worker_id = worker_id
        self.queue = queue

        gevent.Greenlet.__init__(self)

    def _run(self):
        while True:
            sha256, block_ids = self.queue.get()
            print '[Worker {0}] STARTING hash: {1}', self.worker_id, sha256

            # If an *encrypted* version of this block (i.e. same data_sha256)
            # exists on s3 (created by the mailsync process),
            # simply update the Block rows to point at this key +
            # set encryption_scheme=1.
            with session_scope(ignore_soft_deletes=False) as db_session:
                encrypted_block = db_session.query(Block).filter(
                    Block.data_sha256 == sha256,
                    Block.encryption_scheme == 1).first()

                key = encrypted_block.stored_name if encrypted_block else None

            if key is not None:
                with engine.connect() as dbconn:
                    dbconn.execute(text("""
                    UPDATE block
                    SET block.stored_name=:key, block.encryption_scheme=1
                    WHERE block.id IN :block_ids
                    """), key=key, block_ids=block_ids)

            # Otherwise get the block from s3, encrypt, store it under
            # new key.
            else:
                with session_scope(ignore_soft_deletes=False) as db_session:
                    blocks = db_session.query(Block).filter(
                        Block.id.in_(block_ids)).all()

                    # STEP 1: Do one
                    first = blocks[0]

                    # Get unencrypted_data from s3 with integrity check
                    raw_data = first.data
                    assert raw_data is not None

                    # Setting .data encrypts and resaves it to s3
                    # Also sets encryption_scheme, stored_name
                    first.set_data(db_session, raw_data)
                    assert first.encryption_scheme != EncryptionScheme.NULL

                    # STEP 2: Deduped blocks can be updated directly
                    for b in blocks:
                        b.encryption_scheme = first.encryption_scheme
                        b.stored_name = first.stored_name

                    db_session.commit()

            print '[Worker {0}] DONE hash: {1}', self.worker_id, sha256
            self.q.task_done()


if __name__ == '__main__':
    global engine

    preflight()
    engine = main_engine()

    e = EncryptionManager()
    e.run()
