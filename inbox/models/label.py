from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship, backref
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.orm.collections import attribute_mapped_collection

from inbox.models.base import MailSyncBase
from inbox.models.mixins import HasRevisions, Category
from inbox.models.constants import MAX_LABEL_NAME_LENGTH
from inbox.log import get_logger
log = get_logger()


class Label(MailSyncBase, HasRevisions, Category):
    """ Labels from the remote account backend (Gmail). """
    API_OBJECT_NAME = 'category'

    account_id = Column(Integer, ForeignKey(
        'account.id', ondelete='CASCADE', name='label_fk1'), nullable=False)
    account = relationship(
        'Account',
        backref=backref(
            'labels',
            collection_class=attribute_mapped_collection('public_id'),
            # Don't load labels if the namespace is deleted,
            # (the labels will be deleted by the foreign key delete casade).
            passive_deletes=True),
        load_on_pending=True)

    @classmethod
    def find_or_create(cls, session, account, name, canonical_name=None):
        # g_label may not have unicode type (in particular for a numeric label,
        # e.g., '42'), so coerce to unicode.
        name = unicode(name)

        if name.lstrip('\\').lower() in cls.CANONICAL_NAMES:
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
                cls.account_id == account.id,
                cls.name == name).one()
        except NoResultFound:
            obj = cls(account_id=account.id, name=name)
            session.add(obj)
        except MultipleResultsFound:
            log.error('Duplicate label rows for name {}, account_id {}'
                      .format(name, account.id))
            raise

        return obj

    __table_args__ = (UniqueConstraint('account_id', 'name',
                                       name='account_id_3'),
                      UniqueConstraint('account_id', 'public_id'))
