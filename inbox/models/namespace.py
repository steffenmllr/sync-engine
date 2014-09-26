from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy.orm import relationship, backref

from inbox.models.base import MailSyncBase
from inbox.models.mixins import HasPublicID


class Namespace(MailSyncBase, HasPublicID):
    """ A way to do grouping / permissions, basically. """
    # Namespace ids are NOT autoincrementing at the shard level.
    id = Column(Integer, primary_key=True, autoincrement=False)
    account_id = Column(Integer,
                        ForeignKey('account.id', ondelete='CASCADE'),
                        nullable=True)
    # really the root_namespace
    account = relationship('Account',
                           lazy='joined',
                           single_parent=True,
                           backref=backref('namespace', uselist=False,
                                           lazy='joined',
                                           primaryjoin='and_('
                                           'Account.id==Namespace.account_id, '
                                           'Namespace.deleted_at.is_(None))'),
                           uselist=False,
                           primaryjoin='and_('
                           'Namespace.account_id == Account.id, '
                           'Account.deleted_at.is_(None))')

    @property
    def email_address(self):
        if self.account is not None:
            return self.account.email_address
