from sqlalchemy import Column, String, Boolean, Integer, ForeignKey
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql.expression import false
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm.collections import attribute_mapped_collection

from inbox.models.base import MailSyncBase
from inbox.models.mixins import HasRevisions
from inbox.models.constants import MAX_INDEXABLE_LENGTH
from inbox.sqlalchemy_ext.util import generate_public_id
from inbox.log import get_logger
log = get_logger()


class Category(MailSyncBase, HasRevisions):
    API_OBJECT_NAME = 'category'

    # `use_alter` required here to avoid circular dependency w/Account
    account_id = Column(Integer,
                        ForeignKey('account.id', use_alter=True,
                                   name='category_fk1',
                                   ondelete='CASCADE'), nullable=False)

    # TOFIX this causes an import error due to circular dependencies
    # from inbox.models.account import Account
    account = relationship(
        'Account',
        backref=backref(
            'categories',
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
    name = Column(String(MAX_INDEXABLE_LENGTH, collation='utf8mb4_bin'),
                  nullable=False)
    canonical_name = Column(String(MAX_INDEXABLE_LENGTH), nullable=True)

    user_created = Column(Boolean, server_default=false(), nullable=False)

    CANONICAL_NAMES = ['inbox', 'archive', 'drafts', 'sent', 'spam',
                       'starred', 'trash', 'important', 'all']
    RESERVED_NAMES = ['all', 'sending', 'replied', 'file', 'attachment']

    @property
    def user_removable(self):
        return self.user_created

    @property
    def user_addable(self):
        return self.user_created

    @property
    def readonly(self):
        return not self.user_created

    @property
    def lowercase_name(self):
        return self.name.lower()

    @property
    def namespace(self):
        return self.account.namespace

    @classmethod
    def name_available(cls, name, account_id, db_session):
        name = name.lower()
        if name in cls.CANONICAL_NAMES or name in cls.RESERVED_NAMES:
            return False

        if (name,) in db_session.query(cls.name).filter(
                cls.account_id == account_id).all():
            return False

        return True

    @classmethod
    def find_or_create(cls, session, account, name, canonical_name=None):
        raise NotImplementedError

    discriminator = Column('type', String(16))

    __mapper_args__ = {'polymorphic_on': discriminator,
                       'polymorphic_identity': 'category'}

    __table_args__ = (UniqueConstraint('account_id', 'name'),
                      UniqueConstraint('account_id', 'public_id'))
