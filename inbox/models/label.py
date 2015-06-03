from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from inbox.models.category import Category
from inbox.models.constants import MAX_LABEL_NAME_LENGTH
from inbox.log import get_logger
log = get_logger()


class Label(Category):
    """ Labels from the remote account backend (Gmail). """
    id = Column(Integer, ForeignKey(Category.id, ondelete='CASCADE'),
                primary_key=True)

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

    __mapper_args__ = {'polymorphic_identity': 'label'}
    __table_args__ = {'extend_existing': True}
