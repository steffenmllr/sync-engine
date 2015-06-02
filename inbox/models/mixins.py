import abc
from datetime import datetime
from sqlalchemy import Column, DateTime, String, inspect, Boolean, sql
from sqlalchemy.ext.hybrid import hybrid_property, Comparator
from sqlalchemy.sql.expression import false

from inbox.sqlalchemy_ext.util import Base36UID, generate_public_id, ABCMixin
from inbox.models.constants import MAX_INDEXABLE_LENGTH
from inbox.util.addr import canonicalize_address


class HasRevisions(ABCMixin):
    """Mixin for tables that should be versioned in the transaction log."""
    @property
    def versioned_relationships(self):
        """May be overriden by subclasses. This should be the list of
        relationship attribute names that should trigger an update revision
        when changed. (We want to version changes to some, but not all,
        relationship attributes.)"""
        return []

    @property
    def should_suppress_transaction_creation(self):
        """May be overridden by subclasses. We don't want to version certain
        specific objects -- for example, Block instances that are just raw
        message parts and not real attachments. Use this property to suppress
        revisions of such objects. (The need for this is really an artifact of
        current deficiencies in our models. We should be able to get rid of it
        eventually.)"""
        return False

    # Must be defined by subclasses
    API_OBJECT_NAME = abc.abstractproperty()

    def has_versioned_changes(self):
        """Return True if the object has changes on column properties, or on
        any relationship attributes named in self.versioned_relationships."""
        obj_state = inspect(self)
        versioned_attribute_names = list(self.versioned_relationships)
        for mapper in obj_state.mapper.iterate_to_root():
            for attr in mapper.column_attrs:
                versioned_attribute_names.append(attr.key)

        for attr_name in versioned_attribute_names:
            if getattr(obj_state.attrs, attr_name).history.has_changes():
                return True
        return False


class HasPublicID(object):
    public_id = Column(Base36UID, nullable=False,
                       index=True, default=generate_public_id)


class AddressComparator(Comparator):
    def __eq__(self, other):
        return self.__clause_element__() == canonicalize_address(other)

    def like(self, term, escape=None):
        return self.__clause_element__().like(term, escape=escape)


class HasEmailAddress(object):
    """Provides an email_address attribute, which returns as value whatever you
    set it to, but uses a canonicalized form for comparisons. So e.g.
    >>> db_session.query(Account).filter_by(
    ...    email_address='ben.bitdiddle@gmail.com').all()
    [...]
    and
    >>> db_session.query(Account).filter_by(
    ...    email_address='ben.bitdiddle@gmail.com').all()
    [...]
    will return the same results, because the two Gmail addresses are
    equivalent."""
    _raw_address = Column(String(MAX_INDEXABLE_LENGTH),
                          nullable=True, index=True)
    _canonicalized_address = Column(String(MAX_INDEXABLE_LENGTH),
                                    nullable=True, index=True)

    @hybrid_property
    def email_address(self):
        return self._raw_address

    @email_address.comparator
    def email_address(cls):
        return AddressComparator(cls._canonicalized_address)

    @email_address.setter
    def email_address(self, value):
        if value is not None:
            # Silently truncate if necessary. In practice, this may be too
            # long if somebody put a super-long email into their contacts by
            # mistake or something.
            value = value[:MAX_INDEXABLE_LENGTH]
        self._raw_address = value
        self._canonicalized_address = canonicalize_address(value)


class AutoTimestampMixin(object):
    # We do all default/update in Python not SQL for these because MySQL
    # < 5.6 doesn't support multiple TIMESTAMP cols per table, and can't
    # do function defaults or update triggers on DATETIME rows.
    created_at = Column(DateTime, default=datetime.utcnow,
                        nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow,
                        onupdate=datetime.utcnow, nullable=False, index=True)
    # MOSTLY DEPRECATED (but currently used for async deletion of Message
    # objects).
    deleted_at = Column(DateTime, nullable=True, index=True)


class HasRunState(ABCMixin):
    # Track whether this object (e.g. folder, account) should be running
    # or not. Used to compare against reported data points to see if all is
    # well.

    # Is sync enabled for this object? The sync_enabled property should be
    # a Boolean that reflects whether the object should be reporting
    # a heartbeat. For folder-level objects, this property can be used to
    # combine local run state with the parent account's state, so we don't
    # need to cascade account-level start/stop status updates down to folders.
    sync_enabled = abc.abstractproperty()

    # Database-level tracking of whether the sync should be running.
    sync_should_run = Column(Boolean, default=True, nullable=False,
                             server_default=sql.expression.true())


class Category(object):
    # TODO[k]: Can both Folder, Label have the same API_OBJECT_NAME?

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
                       'starred', 'trash', 'important']
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
