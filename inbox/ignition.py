from sqlalchemy import create_engine

from inbox.sqlalchemy_ext.util import ForceStrictMode
from inbox.config import config

DB_POOL_SIZE = config.get_required('DB_POOL_SIZE')


def make_engine(db_uri, pool_size=DB_POOL_SIZE, max_overflow=5):
    """Initialize an engine with some default configuration."""
    return create_engine(db_uri,
                         listeners=[ForceStrictMode()],
                         isolation_level='READ COMMITTED',
                         echo=False,
                         pool_size=pool_size,
                         pool_recycle=3600,
                         max_overflow=max_overflow,
                         connect_args={'charset': 'utf8mb4'})


def init_mailsync_db(engine):
    """
    Make the tables for the mailsync database.

    This is called only from bin/create-db, which is run during setup.
    Previously we allowed this to run everytime on startup, which broke some
    alembic revisions by creating new tables before a migration was run.  From
    now on, we should ony be creating tables+columns via SQLalchemy *once* and
    all subsequent changes done via migration scripts.
    """
    from inbox.models.base import MailSyncBase

    MailSyncBase.metadata.create_all(engine)


def init_master_db(engine):
    """
    Make the tables for the master database.
    """
    from inbox.sharding import Base
    Base.metadata.create_all(engine)
