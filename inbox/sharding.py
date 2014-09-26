"""
We implement stupid sharding as follows.

There's a global 'master' database which keeps track of all namespaces. It
contains only a 'NamespaceShard' table, which has one record for every
namespace. This is basically just the id, public id and shard key.

Each shard is identified by a unique string key. Database parameters for each
shard are defined in a 'sharding.json' file distributed to instances. This has
the advantage that (1) it's very simple, and (2) you can tell each sync engine
instance only about the shard(s) it needs to know about.

Each namespace also has a mirroring `Namespace` record in its own shard, mostly
so as not to have to mess too much with the existing relational model.  This
record's id is the same as that of the NamespaceShard. In other words,
whenever you see a namespace_id, it's unique across a deployment, and not
merely within a shard.

For the moment, we impose the simplifying requirement that each sync instance
operate only on a single shard, identified via "DEFAULT_SHARD_KEY" in
/etc/inboxapp/sharding.json and accessible via
inbox.config.default_shard_uri().

For developer installations, we still use this scheme, but we just make the
master database and the default shard database be the same old 'inbox'
database, which means that existing installations can be upgraded via a simple
`alembic upgrade head`.
"""
from contextlib import contextmanager
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import as_declarative, declared_attr
from sqlalchemy.orm.session import Session
from sqlalchemy.pool import NullPool
from inbox.config import master_db_uri, shard_uri, default_shard_uri
from inbox.ignition import make_engine
from inbox.models.base import MailSyncBase
from inbox.models import Namespace
from inbox.models.mixins import HasPublicID
from inbox.sqlalchemy_ext.util import session_wrapper
from inbox.util.misc import cache


# Models for the master database.


@as_declarative()
class Base(object):
    id = Column(Integer, primary_key=True, autoincrement=True)

    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()


class NamespaceShard(Base, HasPublicID):
    shard_key = Column(String(64), nullable=False)


# Engines for the master and default shard databases.


@cache
def master_engine():
    """Returns an engine for the master database. The engine is initialized
    when this function is first called, and cached for re-use."""
    return make_engine(master_db_uri())


@cache
def default_shard_engine():
    """Returns an engine for the default shard database. The engine is
    initialized when this function is first called, and cached for re-use."""
    return make_engine(default_shard_uri())


class EngineMap(object):
    """"Cache mapping namespace_ids to the corresponding, lazily-initialized
    engines."""
    def __init__(self):
        self.namespace_map = {}
        self.engine_map = {}

    def get(self, namespace_id):
        if namespace_id not in self.namespace_map:
            session = Session(bind=master_engine())
            try:
                ns_shard = session.query(NamespaceShard).get(namespace_id)
                if ns_shard is None:
                    raise ValueError('No shard found')
                db_uri = shard_uri(ns_shard.shard_key)
                self.namespace_map[namespace_id] = db_uri
                session.close()
            except:
                session.close()
                raise

        db_uri = self.namespace_map[namespace_id]
        if db_uri not in self.engine_map:
            self.engine_map[db_uri] = make_engine(db_uri)

        return self.engine_map[db_uri]

engine_map = EngineMap()


@contextmanager
def namespace_managing_session(shard_key):
    db_uri = shard_uri(shard_key)
    shard_engine = create_engine(db_uri,
                                 isolation_level='READ COMMITTED',
                                 poolclass=NullPool,
                                 connect_args={'charset': 'utf8mb4'})
    # Configure a session with the tables inheriting from MailSyncBase bound to
    # the shard engine, and the NamespaceShard table bound to the master
    # engine.
    binds = dict.fromkeys(MailSyncBase.metadata.sorted_tables, shard_engine)
    binds[NamespaceShard] = master_engine()
    # Use two-phase commit so that the insert happens in both the master
    # and the shard, or not at all.
    raw_session = Session(binds=binds, twophase=True)
    with session_wrapper(raw_session) as s:
        s.shard_key = shard_key
        yield s


def add_namespace(ns_manager_session):
    """Add a new NamespaceShard to the master database, and a new Namespace to
    the shard database"""
    assert hasattr(ns_manager_session, 'shard_key'), \
        "Can't add namespace without shard key"
    ns_shard = NamespaceShard(shard_key=ns_manager_session.shard_key)
    ns_manager_session.add(ns_shard)
    ns_manager_session.flush()
    namespace = Namespace(id=ns_shard.id,
                          public_id=ns_shard.public_id)
    ns_manager_session.add(namespace)
    return namespace
