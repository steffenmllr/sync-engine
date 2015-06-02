from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship, backref
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.schema import UniqueConstraint
from inbox.sqlalchemy_ext.util import generate_public_id
from sqlalchemy.sql.expression import false
from sqlalchemy.orm.collections import attribute_mapped_collection

from inbox.models.base import MailSyncBase
from inbox.models.mixins import HasRevisions
from inbox.models.constants import MAX_FOLDER_NAME_LENGTH, MAX_INDEXABLE_LENGTH
from inbox.log import get_logger
log = get_logger()


class Folder(MailSyncBase, HasRevisions):
    """ Folders and labels from the remote account backend (IMAP/Exchange). """
    API_OBJECT_NAME = 'folder'

    # `use_alter` required here to avoid circular dependency w/Account
    account_id = Column(Integer,
                        ForeignKey('account.id', use_alter=True,
                                   name='folder_fk1',
                                   ondelete='CASCADE'), nullable=False)

    # TOFIX this causes an import error due to circular dependencies
    # from inbox.models.account import Account
    account = relationship(
        'Account',
        backref=backref(
            'folders',
            collection_class=attribute_mapped_collection('public_id'),
            # Don't load folders if the account is deleted,
            # (the folders will be deleted by the foreign key delete casade).
            passive_deletes=True),
        foreign_keys=[account_id],
        load_on_pending=True)

    public_id = Column(String(MAX_INDEXABLE_LENGTH), nullable=False,
                       default=generate_public_id)

    # Set the name column to be case sensitive, which isn't the default for
    # MySQL. This is a requirement since IMAP allows users to create both a
    # 'Test' and a 'test' (or a 'tEST' for what we care) folders.
    # NOTE: this doesn't hold for EAS, which is case insensitive for non-Inbox
    # folders as per
    # https://msdn.microsoft.com/en-us/library/ee624913(v=exchg.80).aspx
    name = Column(String(MAX_FOLDER_NAME_LENGTH,
                         collation='utf8mb4_bin'), nullable=True)
    canonical_name = Column(String(MAX_FOLDER_NAME_LENGTH), nullable=True)
    # We use an additional identifier for certain providers,
    # for e.g. EAS uses it to store the eas_folder_id
    # DEPRECATED
    identifier = Column(String(MAX_FOLDER_NAME_LENGTH), nullable=True)

    user_created = Column(Boolean, server_default=false(), nullable=False)

    @property
    def lowercase_name(self):
        return self.name.lower() if self.name else None

    @property
    def namespace(self):
        return self.account.namespace

    @classmethod
    def find_or_create(cls, session, account, name, canonical_name=None):
        q = session.query(cls).filter_by(account_id=account.id)
        if name is not None:
            # Remove trailing whitespace, truncate to max folder name length.
            # Not ideal but necessary to work around MySQL limitations.
            name = name.rstrip()
            if len(name) > MAX_FOLDER_NAME_LENGTH:
                log.warning("Truncating long folder name for account {}; "
                            "original name was '{}'" .format(account.id, name))
                name = name[:MAX_FOLDER_NAME_LENGTH]
            q = q.filter_by(name=name)
        if canonical_name is not None:
            q = q.filter_by(canonical_name=canonical_name)
        try:
            obj = q.one()
        except NoResultFound:
            obj = cls(account=account, name=name,
                      canonical_name=canonical_name)
            session.add(obj)
        except MultipleResultsFound:
            log.info('Duplicate folder rows for folder {} for account {}'
                     .format(name, account.id))
            raise
        return obj

    __table_args__ = (UniqueConstraint('account_id', 'name',
                                       name='account_id_2'),
                      UniqueConstraint('account_id', 'public_id'))
