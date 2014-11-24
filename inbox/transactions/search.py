from collections import defaultdict

from gevent import Greenlet, sleep

from inbox.log import get_logger
log = get_logger()
from inbox.api.kellogs import APIEncoder

from inbox.models.session import session_scope
from inbox.models.util import transaction_objects
from inbox.models.search import SearchIndexCursor
from inbox.search.adaptor import NamespaceSearchEngine
from inbox.transactions.delta_sync import format_transactions_after_pointer


class SearchIndexService(Greenlet):
    """
    Poll the transaction log for message, thread operations
    (inserts, updates, deletes) for all namespaces and perform the
    corresponding Elasticsearch index operations.

    """
    def __init__(self, poll_interval=30, chunk_size=100):
        self.poll_interval = poll_interval
        self.chunk_size = chunk_size

        self.encoder = APIEncoder()

        self.transaction_pointer = None

        self.log = log.new(component='search-index')
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

        with session_scope() as db_session:
            pointer, = db_session.query(SearchIndexCursor.cursor).first()

        self.transaction_pointer = pointer or '0'

        while True:
            with session_scope() as db_session:
                deltas, new_pointer = format_transactions_after_pointer(
                    namespace_id, self.transaction_pointer, db_session,
                    self.chunk_size, exclude_types)

            # TODO[k]: We ideally want to index chunk_size at a time.
            # This currently indexes <= chunk_size, and it varies each time.
            if new_pointer is not None and \
                    new_pointer != self.transaction_pointer:
                self.index(deltas)
                self.update_pointer(new_pointer)
            else:
                sleep(self.poll_interval)

    def index(self, objects):
        """
        Translate database operations to Elasticsearch index operations
        and perform them.

        """
        namespace_map = defaultdict(lambda: defaultdict(list))

        for obj in objects:
            namespace_id = obj['namespace_id']
            type_ = obj['object']
            operation = obj['event']
            if operation in ['create', 'modify']:
                # In order for Elasticsearch to do the right thing w.r.t
                # creating v/s. updating an index, the op_type must be set to
                # 'index'.
                operation = 'index'
                api_repr = obj['attributes']
            else:
                api_repr = dict(id=obj['id'])

            namespace_map[namespace_id][type_].append((operation, api_repr))

        self.log.info('namespaces to index count', count=len(namespace_map))

        for namespace_id in namespace_map:
            engine = NamespaceSearchEngine(namespace_id)

            messages = namespace_map[namespace_id]['message']
            if messages:
                message_count = engine.messages.bulk_index(messages)

            threads = namespace_map[namespace_id]['thread']
            if threads:
                thread_count = engine.threads.bulk_index(threads)

            self.log.info('per-namespace index counts',
                          namespace_id=namespace_id,
                          message_count=message_count,
                          thread_count=thread_count)

    def update_pointer(self, new_pointer):
        """
        Persist transaction pointer to support restarts, update
        self.transaction_pointer.

        """
        with session_scope() as db_session:
            cursor = db_session.query(SearchIndexCursor).first()
            if cursor is None:
                cursor = SearchIndexCursor()
                db_session.add(cursor)

            cursor.cursor = new_pointer
            db_session.commit()

        self.transaction_pointer = new_pointer
