from gevent import Greenlet, joinall, sleep, GreenletExit, event
from sqlalchemy.exc import DataError

from inbox.log import get_logger
log = get_logger()
from inbox.util.debug import bind_context
from inbox.util.concurrency import retry_and_report_killed
from inbox.util.itert import partition
from inbox.models import Account, Folder, Label
from inbox.models.constants import CANONICAL_NAMES
from inbox.models.session import session_scope
from inbox.mailsync.exc import SyncException
from inbox.heartbeat.status import clear_heartbeat_status

THROTTLE_WAIT = 60

mailsync_session_scope = session_scope


class MailsyncError(Exception):
    pass


class MailsyncDone(GreenletExit):
    pass


def save_folder_names(log, account_id, folder_names, db_session):
    """
    Save the folders/labels present on the remote backend for an account.

    * Create Folder, Label objects.
    Map special folders, namely the Inbox canonical folders, on Account
    objects too.

    * DELETE Folders, Labels that no longer exist in `folder_names`.

    Notes
    -----
    Generic IMAP uses folders (not labels). Inbox canonical and other folders
    are created as Folder objects only accordingly.

    Gmail uses IMAP folders and labels. Inbox canonical folders are therefore
    mapped to both Folder and Label objects, everything else is created as a
    Label only.

    We don't canonicalize folder names to lowercase when saving because
    different backends may be case-sensitive or otherwise - code that
    references saved folder names should canonicalize if needed when doing
    comparisons.

    """
    account = db_session.query(Account).get(account_id)
    assert 'inbox' in folder_names, 'Account {} has no detected inbox folder'\
        .format(account.email_address)

    folders = db_session.query(Folder).filter(
        Folder.account_id == account.id).all()
    local_canonical_folders = {f.canonical_name: f for f in folders
                               if f.canonical_name}
    local_folders = {f.name: f for f in folders if not f.canonical_name}
    local_labels = {l.name: l for l in db_session.query(Label).filter(
                    Label.account_id == account.id).all()}

    # Delete canonical folders no longer present on the remote.
    # In the case of Gmail, delete the matching label too.

    remote_canonical_folders = [name for name in folder_names if name not in
                                ('extra', 'labels')]
    discard = \
        set(local_canonical_folders.iterkeys()) - set(remote_canonical_folders)
    for name in discard:
        folder = local_canonical_folders[name]
        label = local_labels.get(name, None)

        log.warn('Canonical folder deleted from remote', account_id=account_id,
                 canonical_name=name, name=folder.name, label=label)

        db_session.delete(folder)
        if label:
            db_session.delete(label)

    # Delete other folders no longer present on the remote.
    # Not applicable to Gmail
    remote_folders = folder_names.get('extra', [])
    discard = set(local_folders.iterkeys()) - set(remote_folders)
    for name in discard:
        log.info('Folder deleted from remote', account_id=account_id,
                 name=name)
        db_session.delete(local_folders[name])

    # Delete labels no longer present on the remote.
    # Only applicable to Gmail
    remote_labels = folder_names.get('labels', [])
    discard = set(local_labels.iterkeys()) - set(remote_labels)
    for name in discard:
        log.info('Label deleted from remote', account_id=account_id, name=name)
        db_session.delete(local_labels[name])

    # Create new Folders and Labels
    for canonical_name in folder_names:
        if canonical_name in CANONICAL_NAMES:
            folder = Folder.find_or_create(db_session, account, None,
                                           canonical_name)
            if folder.name != folder_names[canonical_name]:
                log.warn('Canonical folder name changed on remote',
                         account_id=account_id,
                         canonical_name=canonical_name,
                         new_name=folder_names[canonical_name],
                         name=folder.name)
            folder.name = folder_names[canonical_name]

            attr_name = '{}_folder'.format(canonical_name)
            id_attr_name = '{}_folder_id'.format(canonical_name)
            if getattr(account, id_attr_name) != folder.id:
                # NOTE: Updating the relationship (i.e., attr_name) also
                # updates the associated foreign key (i.e., id_attr_name)
                setattr(account, attr_name, folder)

            if account.discriminator == 'gmailaccount':
                label = Label.find_or_create(db_session, account, None,
                                             canonical_name)
                label.name = folder_names[canonical_name]

        elif canonical_name == 'extra':
            for name in folder_names['extra']:
                Folder.find_or_create(db_session, account, name)

        elif canonical_name == 'labels':
            for name in folder_names['labels']:
                Label.find_or_create(db_session, account, name)

        else:
            raise Exception('Unrecognized folder')

    db_session.commit()


def gevent_check_join(log, threads, errmsg):
    """ Block until all threads have completed and throw an error if threads
        are not successful.
    """
    joinall(threads)
    errors = [thread.exception for thread in threads
              if not thread.successful()]
    if errors:
        log.error(errmsg)
        for error in errors:
            log.error(error)
        raise SyncException("Fatal error encountered")


def create_db_objects(account_id, db_session, log, folder_name, raw_messages,
                      msg_create_fn, canonical_name=None):
    new_uids = []
    # TODO: Detect which namespace to add message to. (shared folders)
    # Look up message thread,
    acc = db_session.query(Account).get(account_id)

    folder = Folder.find_or_create(db_session, acc, folder_name,
                                   canonical_name)

    for msg in raw_messages:
        uid = msg_create_fn(db_session, acc, folder, msg)
        # Must ensure message objects are flushed because they reference
        # threads, which may be new, and later messages may need to belong to
        # the same thread. If we don't flush here and disable autoflush within
        # the message creation to avoid flushing incomplete messages, we can't
        # query for the (uncommitted) new thread id.
        #
        # We should probably refactor this later to use provider-specific
        # Message constructors to avoid creating incomplete objects in the
        # first place.
        if uid is not None:
            db_session.add(uid)
            db_session.flush()
            new_uids.append(uid)

    # imapuid, message, thread, labels
    return new_uids


def commit_uids(db_session, new_uids, provider):
    try:
        msg = u'count: {}'.format(len(new_uids))
        log.info('Commit new UIDs', message=msg,
                 new_committed_message_count=len(new_uids), provider=provider)

        db_session.add_all(new_uids)
        db_session.commit()
    except DataError as e:
        db_session.rollback()
        log.error("Issue inserting new UIDs into database. "
                  "This probably means that an object's property is "
                  "malformed or way too long, etc.")

        for uid in new_uids:
            log.error(uid)
            import inspect
            from pprint import pformat
            log.error(inspect.getmembers(uid))
            try:
                log.error(pformat(uid.__dict__, indent=2))
            except AttributeError:
                pass

            for part in uid.message.parts:
                log.error(inspect.getmembers(part))
                try:
                    log.error(pformat(part.__dict__, indent=2))
                except AttributeError:
                    pass

        raise e


def new_or_updated(uids, local_uids):
    """ HIGHESTMODSEQ queries return a list of messages that are *either*
        new *or* updated. We do different things with each, so we need to
        sort out which is which.
    """
    return partition(lambda x: x in local_uids, uids)


class BaseMailSyncMonitor(Greenlet):
    """
    The SYNC_MONITOR_CLS for all mail sync providers should subclass this.

    Parameters
    ----------
    account_id : int
        Which account to sync.
    email_address : str
        Email address for `account_id`.
    provider : str
        Provider for `account_id`.
    heartbeat : int
        How often to check for commands.
    retry_fail_classes : list
        Exceptions to *not* retry on.
    """
    def __init__(self, account, heartbeat=1, retry_fail_classes=[]):
        bind_context(self, 'mailsyncmonitor', account.id)
        self.shutdown = event.Event()
        # how often to check inbox, in seconds
        self.heartbeat = heartbeat
        self.log = log.new(component='mail sync', account_id=account.id)
        self.account_id = account.id
        self.namespace_id = account.namespace.id
        self.email_address = account.email_address
        self.provider_name = account.provider
        self.retry_fail_classes = retry_fail_classes

        # Stuff that might be updated later and we want to keep a shared
        # reference on child greenlets.
        if not hasattr(self, 'shared_state'):
            self.shared_state = dict()

        Greenlet.__init__(self)

    def _run(self):
        return retry_and_report_killed(self._run_impl,
                                       account_id=self.account_id,
                                       logger=self.log,
                                       fail_classes=self.retry_fail_classes)

    def _run_impl(self):
        sync = Greenlet(retry_and_report_killed, self.sync,
                        account_id=self.account_id, logger=self.log,
                        fail_classes=self.retry_fail_classes)
        sync.start()

        while not sync.ready():
            if self.shutdown.is_set():
                # Ctrl-c, basically!
                self.log.info('Stopping sync', email=self.email_address,
                              account_id=self.account_id)
                # Make sure the parent can't start/stop any folder monitors
                # first
                sync.kill(block=True)

                return self._cleanup()
            else:
                sleep(self.heartbeat)

        if sync.successful():
            return self._cleanup()

        # We just want the name of the exception so don't bother with
        # sys.exc_info()
        self.log.error('mail sync should run forever',
                       provider=self.provider_name,
                       account_id=self.account_id,
                       exception=type(sync.exception).__name__)
        raise sync.exception

    def process_command(self, cmd):
        """ Returns True if successful, or False if process should abort. """
        self.log.info('processing command', cmd=cmd)
        return cmd != 'shutdown'

    def sync(self):
        raise NotImplementedError

    def _cleanup(self):
        with session_scope() as mailsync_db_session:
            map(lambda x: x.set_stopped(mailsync_db_session),
                self.folder_monitors)
        self.folder_monitors.kill()
        clear_heartbeat_status(self.account_id)


def _check_thread_state(thread, is_state):
    state = getattr(thread, 'state')
    return state == is_state or (state and state.startswith(is_state))


def thread_finished(thread):
    return _check_thread_state(thread, 'finish')


def thread_polling(thread):
    return _check_thread_state(thread, 'poll')
