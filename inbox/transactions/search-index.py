from collections import defaultdict

from gevent import Greenlet, sleep

from inbox.log import get_logger
logger = get_logger()
from inbox.api.kellogs import APIEncoder
from inbox.models.session import session_scope
from inbox.models.util import transaction_objects
from inbox.search.adaptor import NamespaceSearchEngine
from inbox.transactions.delta_sync import format_transactions_after_pointer


class SearchIndexService(Greenlet):
    def __init__(self, poll_interval=30, chunk_size=100):
        self.poll_interval = poll_interval
        self.chunk_size = chunk_size

        self.encoder = APIEncoder()

        # Get persisted
        self.transaction_pointer = None

        self.log = logger.new(component='search-index')
        Greenlet.__init__(self)

    def _run(self):
        """
        Index into Elasticsearch the threads, messages of all namespaces.

        """
        # Indexing is namespace agnostic.
        # Note that although this means we do not restrict the Transaction
        # table query (via the format_transactions_after_pointer() call below)
        # to a namespace, since we pass a `result_limit` (== chunk_size)
        # argument, the query should still be performant.
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
                sleep(self.poll_interval)

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
