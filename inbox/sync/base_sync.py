from datetime import datetime
from collections import Counter

import gevent
import gevent.event

from inbox.log import get_logger
logger = get_logger()
from inbox.basicauth import ConnectionError, ValidationError
from inbox.models.session import session_scope
from inbox.models import Account
from inbox.util.concurrency import retry_with_logging
from inbox.heartbeat.status import HeartbeatStatusProxy, clear_heartbeat_status


class BaseSync(gevent.Greenlet):
    def __init__(self, account_id, namespace_id, poll_frequency, folder_id,
                 folder_name, provider_name):
        """
        Base class for syncing non-mail resources from the remote backend,
        like contacts and calendar events.

        Subclasses must implement:
        * the `provider` property -
            returns an instantiable interface to the remote item data provider,
        * the `poll` method -
            implements the query and persistence logic.

        """
        self.account_id = account_id
        self.namespace_id = namespace_id
        self.poll_frequency = poll_frequency
        self.folder_id = folder_id
        self.folder_name = folder_name
        self.provider_name = provider_name

        self.shutdown = gevent.event.Event()

        self.log = logger.new(account_id=account_id)
        self.heartbeat_status = HeartbeatStatusProxy(self.account_id,
                                                     self.folder_id)
        self.heartbeat_status.publish(provider_name=self.provider_name,
                                      folder_name=self.folder_name)

        gevent.Greenlet.__init__(self)

    def _run(self):
        return retry_with_logging(self._run_impl, self.log,
                                  account_id=self.account_id)

    def _run_impl(self):
        try:
            self.provider_instance = self.provider(self.account_id,
                                                   self.namespace_id)
            while True:
                # Check to see if this greenlet should exit
                if self.shutdown.is_set():
                    clear_heartbeat_status(self.account_id, self.folder_id)
                    return False

                try:
                    self.poll()
                    self.heartbeat_status.publish(state='poll')

                # If we get a connection or API permissions error, then sleep
                # 2x poll frequency.
                except ConnectionError:
                    self.log.error('Error while polling', exc_info=True)
                    self.heartbeat_status.publish(state='poll error')
                    gevent.sleep(self.poll_frequency)

                gevent.sleep(self.poll_frequency)
        except ValidationError:
            # Bad account credentials; exit.
            self.log.error('Error while establishing the connection',
                           exc_info=True)
            return False

    @property
    def provider(self):
        raise NotImplementedError

    def poll(self):
        raise NotImplementedError

    def last_sync(self, account):
        raise NotImplementedError


def base_poll(account_id, get_items_fn, target_obj, last_sync_fn,
              set_last_sync_fn, log, remote_args=None, target_filters=None,
              **create_kwargs):
    """
    Query a remote provider for target_obj adds, updates and deletes and
    persist them to the database.

    Parameters
    ----------
    account_id: int
        ID for the account whose items should be queried.

    get_items_fn: function
        Returns items from the remote data provider.

    target_obj: database model

    last_sync_fn:

    set_last_sync_fn:

    log:


    Returns
    -------
    ids_: list of dicts
        Each dict maps the unique remote id (uid) of an item to
        the record id of the local object (id).
        Only items that were added or updated are included.

    """
    # Get a timestamp before polling, so that we don't subsequently miss remote
    # updates that happen while the poll loop is executing.
    sync_timestamp = datetime.utcnow()

    last_sync = None
    with session_scope() as db_session:
        account = db_session.query(Account).get(account_id)
        if last_sync_fn(account) is not None:
            # Note explicit offset is required by e.g. Google calendar API.
            last_sync = datetime.isoformat(last_sync_fn(account)) + 'Z'

    remote_args = remote_args or {}
    remote_args.update(dict(sync_from_time=last_sync))

    items = get_items_fn(remote_args)

    ids_ = []
    change_counter = Counter()
    with session_scope() as db_session:
        account = db_session.query(Account).get(account_id)
        namespace_id = account.namespace.id

        for item in items:
            uid = item.uid

            assert uid is not None, 'Got remote item with null uid'
            assert isinstance(uid, basestring)

            filters = target_filters or []
            filters += [target_obj.namespace_id == namespace_id,
                        target_obj.uid == uid]

            local = db_session.query(target_obj).filter(
                *filters).first()

            # Update or delete
            if local:
                if item.deleted:
                    db_session.delete(local)
                    change_counter['deleted'] += 1
                else:
                    local.update(db_session, item)
                    ids_.append(dict(uid=uid, id=local.id))
                    change_counter['updated'] += 1
            # Add
            else:
                local = target_obj(namespace_id=namespace_id,
                                   uid=uid,
                                   **create_kwargs)
                local.update(db_session, item)
                db_session.add(local)
                db_session.flush()
                ids_.append(dict(uid=uid, id=local.id))
                change_counter['added'] += 1

        set_last_sync_fn(account, sync_timestamp)

        log.info('{} sync'.format(target_obj.__tablename__),
                 added=change_counter['added'],
                 updated=change_counter['updated'],
                 deleted=change_counter['deleted'])

        db_session.commit()

    return ids_
