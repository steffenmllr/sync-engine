from sqlalchemy import Column, String, Integer, ForeignKey
from sqlalchemy.orm import relationship, backref
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm.collections import attribute_mapped_collection
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from inbox.models.base import MailSyncBase
from inbox.models.mixins import HasRevisions
from inbox.models.constants import MAX_INDEXABLE_LENGTH
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

    name = Column(String(MAX_INDEXABLE_LENGTH), nullable=True)
    display_name = Column(String(MAX_INDEXABLE_LENGTH,
                                 collation='utf8mb4_bin'), nullable=False)

    @classmethod
    def find_or_create(cls, session, namespace_id, name, display_name):
        try:
            obj = session.query(cls).filter(
                cls.namespace_id == namespace_id,
                cls.name == name,
                cls.display_name == display_name).one()
        except NoResultFound:
            obj = cls(namespace_id=namespace_id, name=name,
                      display_name=display_name)
            session.add(obj)
        except MultipleResultsFound:
            log.error('Duplicate category rows for namespace_id {}, '
                      'name {}, display_name: {}'.
                      format(namespace_id, name, display_name))
            raise

        return obj

    @property
    def account(self):
        return self.namespace.account

    @property
    def type(self):
        return self.account.category_type

    __table_args__ = (UniqueConstraint('namespace_id', 'name', 'display_name'),
                      UniqueConstraint('namespace_id', 'public_id'))
