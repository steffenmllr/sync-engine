from sqlalchemy import Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import relationship, backref
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.schema import UniqueConstraint
from inbox.sqlalchemy_ext.util import generate_public_id
from sqlalchemy.sql.expression import false
from sqlalchemy.orm.collections import attribute_mapped_collection

from inbox.models.base import MailSyncBase
from inbox.models.mixins import HasRevisions
from inbox.models.constants import MAX_LABEL_NAME_LENGTH, MAX_INDEXABLE_LENGTH
from inbox.log import get_logger
log = get_logger()

# FIXFIXFIX [k]: Move this to a common location - Tag mixin for Folder, Label?
canonical_folders = ['inbox', 'sent', 'draft', 'starred', 'important', 'trash']


class Label(MailSyncBase, HasRevisions):
    """ Labels from the remote account backend (Gmail). """
    API_OBJECT_NAME = 'label'

    namespace_id = Column(Integer, ForeignKey(
        'namespace.id', ondelete='CASCADE', name='label_fk1'), nullable=False)
    namespace = relationship(
        'Namespace',
        backref=backref(
            'labels',
            collection_class=attribute_mapped_collection('public_id'),
            # Don't load labels if the namespace is deleted,
            # (the labels will be deleted by the foreign key delete casade).
            passive_deletes=True),
        load_on_pending=True)

    public_id = Column(String(MAX_INDEXABLE_LENGTH), nullable=False,
                       default=generate_public_id)

    name = Column(String(MAX_LABEL_NAME_LENGTH), nullable=True)
    user_created = Column(Boolean, server_default=false(), nullable=False)

    @property
    def lowercase_name(self):
        return self.name.lower()

    @property
    def account(self):
        return self.namespace.account

    @classmethod
    def find_or_create(cls, session, account, name):
        # g_label may not have unicode type (in particular for a numeric label,
        # e.g., '42'), so coerce to unicode.
        name = unicode(name)

        if name.lstrip('\\').lower() in canonical_folders:
            # For Inbox-canonical names, save the canonicalized form.
            name = name.lstrip('\\').lower()
        else:
            # Remove trailing whitespace, truncate (due to MySQL limitations).
            name = name.rstrip()
            if len(name) > MAX_LABEL_NAME_LENGTH:
                log.warning("Truncating label name for account {}; "
                            "original name was '{}'" .format(account.id, name))
                name = name[:MAX_LABEL_NAME_LENGTH]

        try:
            obj = session.query(cls).filter(
                cls.namespace_id == account.namespace.id,
                cls.name == name).one()
        except NoResultFound:
            obj = cls(namespace_id=account.namespace.id, name=name)
            session.add(obj)
        except MultipleResultsFound:
            log.error('Duplicate label rows for name {}, account_id {}'
                      .format(name, account.id))
            raise

        return obj

    __table_args__ = (UniqueConstraint('namespace_id', 'name',
                                       name='namespace_id_2'),
                      UniqueConstraint('namespace_id', 'public_id'))
