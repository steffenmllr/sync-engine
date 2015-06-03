from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from inbox.models.category import Category
from inbox.models.constants import MAX_FOLDER_NAME_LENGTH
from inbox.log import get_logger
log = get_logger()


class Folder(Category):
    """ Folders and labels from the remote account backend (IMAP/Exchange). """
    id = Column(Integer, ForeignKey(Category.id, ondelete='CASCADE'),
                primary_key=True)

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

    __mapper_args__ = {'polymorphic_identity': 'folder'}
    __table_args__ = {'extend_existing': True}
