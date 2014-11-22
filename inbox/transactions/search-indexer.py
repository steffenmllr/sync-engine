from collections import defaultdict

import gevent

from inbox.api.kellogs import APIEncoder
from inbox.models.session import session_scope
from inbox.models.util import transaction_objects
from inbox.transactions.delta_sync import format_transactions_after_pointer


class Indexer(object):
    def __init__(self, poll_interval, chunk_size):
        self.poll_interval = poll_interval
        self.chunk_size = chunk_size

        self.encoder = APIEncoder()

        # Get persisted
        self.transaction_pointer = None

    def streaming_index(self):
        """

        """
        # Indexing is namespace agnostic.
        namespace_id = None

        # Only index messages, threads.
        object_types = transaction_objects()
        exclude_types = [api_name for model_name, api_name in
                         object_types.iteritems() if model_name not in
                         ['message', 'thread']]
        while True:
            with session_scope() as db_session:
                deltas, new_pointer = format_transactions_after_pointer(
                    namespace_id, self.transaction_pointer, db_session,
                    self.chunk_size, exclude_types)

            if new_pointer is not None and \
                    new_pointer != self.transaction_pointer:

                self.index(deltas)
                self.transaction_pointer = new_pointer
                # Persist txn ptr.
            else:
                gevent.sleep(self.poll_interval)

    def index(self, objects):
        namespace_map = defaultdict(lambda: defaultdict(list))

        for obj in objects:
            encoded_obj = self.encoder.cereal(obj)
            namespace_map[obj.namespace_id][obj.object_type].append(
                encoded_obj)

        for namespace_id in namespace_map:
            engine = NamespaceSearchEngine(namespace_id)

            messages = namespace_map[namespace_id]['message']
            if messages:
                engine.messages.index(messages)

            threads = namespace_map[namespace_id]['thread']
            if threads:
                engine.threads.index(threads)
