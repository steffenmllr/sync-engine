from sqlalchemy import Column, String, Boolean, Integer, ForeignKey
from sqlalchemy.orm import relationship, backref
from sqlalchemy.sql.expression import false
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm.collections import attribute_mapped_collection
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from inbox.models.base import MailSyncBase
from inbox.models.mixins import HasRevisions
from inbox.models.constants import (MAX_INDEXABLE_LENGTH, CATEGORY_NAMES,
                                    RESERVED_NAMES)
from inbox.sqlalchemy_ext.util import generate_public_id
from inbox.log import get_logger
log = get_logger()


class Category(MailSyncBase, HasRevisions):
    API_OBJECT_NAME = 'category'

    # Need `use_alter` here to avoid circular dependencies
    namespace_id = Column(Integer,
                          ForeignKey('namespace.id', use_alter=True,
                                     name='category_fk1',
                                     ondelete='CASCADE'), nullable=False)
    namespace = relationship(
        'Namespace',
        backref=backref(
            'categories',
            collection_class=attribute_mapped_collection('public_id'),
            passive_deletes=True),
        load_on_pending=True)

    public_id = Column(String(MAX_INDEXABLE_LENGTH), nullable=False,
                       default=generate_public_id)

    category = Column(String(MAX_INDEXABLE_LENGTH, collation='utf8mb4_bin'),
                      nullable=True)
    display_name = Column(String(MAX_INDEXABLE_LENGTH), nullable=False)

    user_created = Column(Boolean, server_default=false(), nullable=False)

    @property
    def user_removable(self):
        return self.user_created

    @property
    def user_addable(self):
        return self.user_created

    @classmethod
    def name_available(cls, name, account_id, db_session):
        name = name.lower()

        if name in CATEGORY_NAMES or name in RESERVED_NAMES:
            return False

        if (name,) in db_session.query(cls.display_name).filter(
                cls.account_id == account_id).all():
            return False

        return True

    @classmethod
    def find_or_create(cls, session, namespace_id, category, display_name,
                       user_created=False):

        try:
            obj = session.query(cls).filter(
                cls.namespace_id == namespace_id,
                cls.category == category,
                cls.display_name == display_name).one()
        except NoResultFound:
            obj = cls(namespace_id=namespace_id, category=category,
                      display_name=display_name, user_created=user_created)
            session.add(obj)
        except MultipleResultsFound:
            log.error('Duplicate category rows for namespace_id {}, '
                      'category_name {}, display_name: {}'.
                      format(namespace_id, category, display_name))
            raise

        return obj

    @property
    def account(self):
        return self.namespace.account

    @property
    def name(self):
        return self.category

    @property
    def type(self):
        return self.account.category_type

    __table_args__ = (UniqueConstraint('namespace_id', 'category'),
                      UniqueConstraint('namespace_id', 'public_id'))
