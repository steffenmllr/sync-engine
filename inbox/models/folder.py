from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship, backref
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from inbox.models.base import MailSyncBase
from inbox.models.category import Category
from inbox.models.constants import MAX_FOLDER_NAME_LENGTH
from inbox.log import get_logger
log = get_logger()


class Folder(MailSyncBase):
    """ Folders from the remote account backend (Generic IMAP/ Gmail). """
    # TOFIX this causes an import error due to circular dependencies
    # from inbox.models.account import Account
    # `use_alter` required here to avoid circular dependency w/Account
    account_id = Column(Integer,
                        ForeignKey('account.id', use_alter=True,
                                   name='folder_fk1',
                                   ondelete='CASCADE'), nullable=False)
    account = relationship(
        'Account',
        backref=backref(
            'folders',
            # Don't load folders if the account is deleted,
            # (the folders will be deleted by the foreign key delete casade).
            passive_deletes=True),
        foreign_keys=[account_id],
        load_on_pending=True)

    # Set the name column to be case sensitive, which isn't the default for
    # MySQL. This is a requirement since IMAP allows users to create both a
    # 'Test' and a 'test' (or a 'tEST' for what we care) folders.
    # NOTE: this doesn't hold for EAS, which is case insensitive for non-Inbox
    # folders as per
    # https://msdn.microsoft.com/en-us/library/ee624913(v=exchg.80).aspx
    name = Column(String(MAX_FOLDER_NAME_LENGTH, collation='utf8mb4_bin'),
                  nullable=False)
    canonical_name = Column(String(MAX_FOLDER_NAME_LENGTH), nullable=True)
    # We use an additional identifier for certain providers,
    # for e.g. EAS uses it to store the eas_folder_id
    # DEPRECATED
    identifier = Column(String(MAX_FOLDER_NAME_LENGTH), nullable=True)

    # TODO[k]: What if Category deleted via API?
    # Should we allow a delete-cascade here?
    category_id = Column(Integer, ForeignKey(Category.id))
    category = relationship(
        Category,
        backref=backref('folders',
                        cascade='all, delete-orphan'))

    @classmethod
    def find_or_create(cls, session, account, name, canonical_name=None,
                       category=None):
        q = session.query(cls).filter(cls.account_id == account.id)

        if canonical_name is not None:
            q = q.filter(cls.canonical_name == canonical_name)
        else:
            # Remove trailing whitespace, truncate to max folder name length.
            # Not ideal but necessary to work around MySQL limitations.
            name = name.rstrip()
            if len(name) > MAX_FOLDER_NAME_LENGTH:
                log.warning("Truncating long folder name for account {}; "
                            "original name was '{}'" .format(account.id, name))
                name = name[:MAX_FOLDER_NAME_LENGTH]
            q = q.filter_by(name=name)

        try:
            obj = q.one()
        except NoResultFound:
            obj = cls(account=account, name=name,
                      canonical_name=canonical_name)
            obj.category = Category.find_or_create(
                session, namespace_id=account.namespace.id, category=category,
                display_name=name)
            session.add(obj)
        except MultipleResultsFound:
            log.info('Duplicate folder rows for folder {} for account {}'
                     .format(name, account.id))
            raise

        return obj

    __table_args__ = (UniqueConstraint('account_id', 'name'),)
