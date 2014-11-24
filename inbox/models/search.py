from sqlalchemy import Column

from inbox.models.base import MailSyncBase
from inbox.sqlalchemy_ext.util import Base36UID


class SearchIndexCursor(MailSyncBase):
    cursor = Column(Base36UID, nullable=True, index=True)
