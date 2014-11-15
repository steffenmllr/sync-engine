import dateutil.parser
import gevent
from sqlalchemy.orm import joinedload, subqueryload

from inbox.log import get_logger
log = get_logger()
from inbox.models.session import session_scope
from inbox.models import Namespace, Thread, Message, Part, Block
from inbox.api.kellogs import encode
from inbox.search.adaptor import NamespaceSearchEngine
from inbox.search.util.misc import es_format_address_list, es_format_tags_list
from inbox.sqlalchemy_ext.util import safer_yield_per

CHUNK_SIZE = 1000

def force_int(n):
    try:
        int(n)
        return n
    except ValueError:
        return 0
    except TypeError:
        return 0


class NamespaceIndexer(object):
    def __init__(self):
        self.pool = []

    def index(self, namespace_public_id=None, updated_since=None):
        """
        Create an Elasticsearch index for a namespace and index its threads and
        messages. If `namespace_public_id` is None, all namespaces are indexed.
        Else, the specified one is.

        """
        with session_scope() as db_session:
            q = db_session.query(Namespace.id, Namespace.public_id)
            
            if namespace_public_id is not None:
                namespaces = [q.filter(
                    Namespace.public_id == namespace_public_id).one()]
            else:
                namespaces = q.all()

        for ns in namespaces:
            self.pool.append(gevent.spawn(index_threads, ns, updated_since))
            #index messages returns attachments if "include_attachments" is set to true
            self.pool.append(gevent.spawn(index_messages, ns, updated_since, True))
            

            #if efficiency comes up with regards to this script, it might be worth 
            #looking at utilizing the parent child relationships of these objects to 
            #cut down on lookups


        gevent.joinall(self.pool)
        
        return sum([force_int(g.value) for g in self.pool])

    def delete(self, namespace_public_id=None):
        """
        Delete an Elasticsearch index for a namespace.
        If `namespace_public_id` is None, all namespaces are indexed. Else,
        the specified one is.

        """
        with session_scope() as db_session:
            q = db_session.query(Namespace.id, Namespace.public_id)

            if namespace_public_id is not None:
                namespaces = [q.filter(
                    Namespace.public_id == namespace_public_id).one()]
            else:
                namespaces = q.all()

        for ns in namespaces:
            self.pool.append(gevent.spawn(delete_index, ns))

        gevent.joinall(self.pool)


def index_namespace(namespace_public_id=None, updated_since=None):
    count = NamespaceIndexer().index(namespace_public_id, updated_since)
    return count


def delete_namespace_index(namespace_public_id=None):
    NamespaceIndexer().delete(namespace_public_id)


def index_threads(namespace, updated_since=None):
    """ Index the threads of a namespace. """
    namespace_id, namespace_public_id = namespace

    if updated_since is not None:
        updated_since = dateutil.parser.parse(updated_since)

    indexed_count = 0
    search_engine = NamespaceSearchEngine(namespace_public_id)

    with session_scope() as db_session:
        query = db_session.query(Thread).filter(
            Thread.namespace_id == namespace.id)

        if updated_since is not None:
            query = query.filter(Thread.updated_at > updated_since)

        query = query.options(
            subqueryload(Thread.messages).
            load_only('public_id', 'is_draft', 'from_addr', 'to_addr',
                      'cc_addr', 'bcc_addr'),
            subqueryload('tagitems').joinedload('tag').
            load_only('public_id', 'name'))

        encoded = []
        for obj in safer_yield_per(query, Thread.id, 0, CHUNK_SIZE):
            encoded_obj = encode(
                obj, namespace_public_id=namespace_public_id,
                format_address_fn=es_format_address_list,
                format_tags_fn=es_format_tags_list)

            encoded.append(encoded_obj)

    indexed_count += search_engine.threads.bulk_index(encoded)

    log.info('Indexed threads', namespace_id=namespace_id,
             namespace_public_id=namespace_public_id,
             thread_count=indexed_count)

    return indexed_count


def index_messages(namespace, updated_since=None, include_attachments = True):
    """ Index the messages of a namespace. """
    namespace_id, namespace_public_id = namespace

    if updated_since is not None:
        updated_since = dateutil.parser.parse(updated_since)

    indexed_count = 0
    search_engine = NamespaceSearchEngine(namespace_public_id)

    with session_scope() as db_session:
        #Generate query for message
        query = db_session.query(Message).filter(
            Message.namespace_id == namespace.id)

        if updated_since is not None:
            query = query.filter(Message.updated_at > updated_since)

        #query = query.options(joinedload(Message.parts))

        #print("query is: ================" + str(query))

        encoded = []
        msg_list = []
        #Add messages to index serialize
        for obj in safer_yield_per(query, Message.id, 0, CHUNK_SIZE):
            encoded_obj = encode(
                obj, namespace_public_id=namespace_public_id,
                format_address_fn=es_format_address_list,
                format_tags_fn=es_format_tags_list)
            encoded.append(encoded_obj)
            msg_list.append(obj.id)
            if (include_attachments):
                indexed_count += index_attachments(
                    Message, obj.id, namespace_public_id, updated_since)             
          
    indexed_count += search_engine.messages.bulk_index(encoded)
  
    
    
    log.info('Indexed messages', namespace_id=namespace_id,
             namespace_public_id=namespace_public_id,
             message_count=indexed_count)
    
  
        
    
    
    return indexed_count

def index_attachments(message, msg_id, namespace_public_id, updated_since=None):
    
    message_id = msg_id
    print("attachments on message with id " + str(message_id))
    
    if updated_since is not None:
        updated_since = dateutil.parser.parse(updated_since)
        
    encoded = []
    indexed_count = 0
    search_engine = NamespaceSearchEngine(namespace_public_id)

    with session_scope() as db_session:
        msg_query = db_session.query(Message).get(msg_id)
        #blocks = db_session.query(Block).filter(Block.id == msg_query.attachments.block_id)
        for att in msg_query.attachments:
            blocks = db_session.query(Block).filter(Block.id == att.block_id)
            for block in blocks:
                encoded_obj = encode(
                    block, namespace_public_id=namespace_public_id,
                    format_address_fn=es_format_address_list,
                    format_tags_fn=es_format_tags_list)
                if encoded_obj is not None:
                    encoded.append(encoded_obj)
                    print("encoded an attachment -------------------- supposedly" + str(encoded_obj))
    #if updated_since is not None:
    #    query = query.filter(Part.updated_at > updated_since)

 
    
    
    #for block_obj in safer_yield_per(query, Part.id , 0, CHUNK_SIZE):
    #for block_obj in query:
    #    print (str(block_obj))
    #    print (block_obj.id)
    #    encoded_obj = encode(
    #        block_obj, namespace_public_id=namespace_public_id,
    #        format_address_fn=es_format_address_list,
    #        format_tags_fn=es_format_tags_list)
    #    print(str(encoded_obj))
    #    print(encoded_obj)
    #    if encoded_obj is not None:
    #        encoded.append(encoded_obj)
    #        print("----------------------yay------------------------")

    indexed_count += search_engine.blocks.bulk_index(encoded)
    
    return indexed_count


def delete_index(namespace):
    """ Delete a namespace index. """

    namespace_id, namespace_public_id = namespace
    search_engine = NamespaceSearchEngine(namespace_public_id)
    search_engine.delete_index()

    log.info('Deleted namespace index', namespace_id=namespace_id,
             namespace_public_id=namespace_public_id)
