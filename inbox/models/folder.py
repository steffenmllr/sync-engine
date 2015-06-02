from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship, backref
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm.collections import attribute_mapped_collection

from inbox.models.base import MailSyncBase
from inbox.models.mixins import HasRevisions, Category
from inbox.models.constants import MAX_FOLDER_NAME_LENGTH
from inbox.log import get_logger
log = get_logger()


class Folder(MailSyncBase, HasRevisions, Category):
    """ Folders and labels from the remote account backend (IMAP/Exchange). """
    API_OBJECT_NAME = 'category'

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

    # We use an additional identifier for certain providers,
    # for e.g. EAS uses it to store the eas_folder_id
    # DEPRECATED
    identifier = Column(String(MAX_FOLDER_NAME_LENGTH), nullable=True)

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
