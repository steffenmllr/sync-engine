from gevent import sleep
from gevent.pool import Group
from gevent.coros import BoundedSemaphore
from sqlalchemy.orm.exc import NoResultFound
from inbox.log import get_logger
from inbox.crispin import retry_crispin, connection_pool
from inbox.models import Account, Folder
from inbox.mailsync.backends.base import BaseMailSyncMonitor
from inbox.mailsync.backends.base import (MailsyncError,
                                          mailsync_session_scope,
                                          thread_polling, thread_finished)
from inbox.mailsync.backends.imap.generic import FolderSyncEngine
from inbox.mailsync.backends.imap.condstore import CondstoreFolderSyncEngine
from inbox.heartbeat.status import clear_heartbeat_status
from inbox.mailsync.gc import DeleteHandler
log = get_logger()


class ImapSyncMonitor(BaseMailSyncMonitor):
    """
    Top-level controller for an account's mail sync. Spawns individual
    FolderSync greenlets for each folder.

    Parameters
    ----------
    heartbeat: Integer
        Seconds to wait between checking on folder sync threads.
    refresh_frequency: Integer
        Seconds to wait between checking for new folders to sync.
    poll_frequency: Integer
        Seconds to wait between polling for the greenlets spawned
    refresh_flags_max: Integer
        the maximum number of UIDs for which we'll check flags
        periodically.

    """
    def __init__(self, account,
                 heartbeat=1, refresh_frequency=30, poll_frequency=30,
                 retry_fail_classes=[], refresh_flags_max=2000):
        self.refresh_frequency = refresh_frequency
        self.poll_frequency = poll_frequency
        self.syncmanager_lock = BoundedSemaphore(1)
        self.refresh_flags_max = refresh_flags_max

        provider_supports_condstore = account.provider_info.get('condstore',
                                                                False)
        account_supports_condstore = getattr(account, 'supports_condstore',
                                             False)
        if provider_supports_condstore or account_supports_condstore:
            self.sync_engine_class = CondstoreFolderSyncEngine
        else:
            self.sync_engine_class = FolderSyncEngine

        self.folder_monitors = Group()

        BaseMailSyncMonitor.__init__(self, account, heartbeat,
                                     retry_fail_classes)

    @retry_crispin
    def prepare_sync(self):
        """
        Gets and save Folder objects for folders on the IMAP backend. Returns a
        list of tuples (folder_name, folder_id) for each folder we want to sync
        (in order).
        """
        with mailsync_session_scope() as db_session:
            with connection_pool(self.account_id).get() as crispin_client:
                # Get a fresh list of the folder names from the remote
                remote_folders = crispin_client.folders()
                self.save_folder_names(db_session, self.account_id,
                                       remote_folders)
                # The folders we should be syncing
                sync_folders = crispin_client.sync_folders()

            sync_folder_names_ids = []
            for folder_name in sync_folders:
                try:
                    id_, = db_session.query(Folder.id). \
                        filter(Folder.name == folder_name,
                               Folder.account_id == self.account_id).one()
                    sync_folder_names_ids.append((folder_name, id_))
                except NoResultFound:
                    log.error('Missing Folder object when starting sync',
                              folder_name=folder_name)
                    raise MailsyncError("Missing Folder '{}' on account {}"
                                        .format(folder_name, self.account_id))
            return sync_folder_names_ids

    def save_folder_names(self, db_session, account_id, raw_folders):
        """
        Save the folders/labels present on the remote backend for an account.

        * Create Folder, Label objects.
        Map special folders, namely the Inbox canonical folders, on Account
        objects too.

        * DELETE Folders, Labels that no longer exist in `folder_names`.

        Notes
        -----
        Generic IMAP uses folders (not labels). Inbox canonical and other
        folders are created as Folder objects only accordingly.

        Gmail uses IMAP folders and labels. Inbox canonical folders are
        therefore mapped to both Folder and Label objects, everything else is
        created as a Label only.

        We don't canonicalize folder names to lowercase when saving because
        different backends may be case-sensitive or otherwise - code that
        references saved folder names should canonicalize if needed when doing
        comparisons.

        """
        account = db_session.query(Account).get(account_id)

        remote_canonical_folders = [f.canonical_name for f in raw_folders
                                    if f.canonical_name is not None]
        remote_folders = [f.name for f in raw_folders if not f.canonical_name]

        assert 'inbox' in remote_canonical_folders, \
            'Account {} has no detected inbox folder'.\
            format(account.email_address)

        folders = db_session.query(Folder).filter(
            Folder.account_id == account_id).all()
        local_canonical_folders = {f.canonical_name: f for f in folders
                                   if f.canonical_name}
        local_folders = {f.name: f for f in folders if not f.canonical_name}

        # Delete canonical folders no longer present on the remote.

        discard = \
            set(local_canonical_folders.iterkeys()) - \
            set(remote_canonical_folders)
        for name in discard:
            folder = local_canonical_folders[name]
            log.warn('Canonical folder deleted from remote',
                     account_id=account_id, canonical_name=name,
                     name=folder.name)
            db_session.delete(folder)

        # Delete other folders no longer present on the remote.

        discard = set(local_folders.iterkeys()) - set(remote_folders)
        for name in discard:
            log.info('Folder deleted from remote', account_id=account_id,
                     name=name)
            db_session.delete(local_folders[name])

        # Create new Folders

        for raw_folder in raw_folders:
            name, canonical_name, category = \
                raw_folder.name, raw_folder.canonical_name, raw_folder.category

            folder = Folder.find_or_create(db_session, account, name,
                                           canonical_name, category)

            if canonical_name:
                if folder.name != name:
                    log.warn('Canonical folder name changed on remote',
                             account_id=account_id,
                             canonical_name=canonical_name,
                             new_name=name, name=folder.name)
                folder.name = name

                attr_name = '{}_folder'.format(canonical_name)
                id_attr_name = '{}_folder_id'.format(canonical_name)
                if getattr(account, id_attr_name) != folder.id:
                    # NOTE: Updating the relationship (i.e., attr_name) also
                    # updates the associated foreign key (i.e., id_attr_name)
                    setattr(account, attr_name, folder)

        db_session.commit()

    def start_new_folder_sync_engines(self, folders=set()):
        new_folders = [f for f in self.prepare_sync() if f not in folders]
        for folder_name, folder_id in new_folders:
            log.info('Folder sync engine started',
                     account_id=self.account_id,
                     folder_id=folder_id,
                     folder_name=folder_name)
            thread = self.sync_engine_class(self.account_id,
                                            folder_name,
                                            folder_id,
                                            self.email_address,
                                            self.provider_name,
                                            self.poll_frequency,
                                            self.syncmanager_lock,
                                            self.refresh_flags_max,
                                            self.retry_fail_classes)
            self.folder_monitors.start(thread)
            while not thread_polling(thread) and \
                    not thread_finished(thread) and \
                    not thread.ready():
                sleep(self.heartbeat)

            # allow individual folder sync monitors to shut themselves down
            # after completing the initial sync
            if thread_finished(thread) or thread.ready():
                if thread.exception:
                    # Exceptions causing the folder sync to exit should not
                    # clear the heartbeat.
                    log.info('Folder sync engine exited with error',
                             account_id=self.account_id,
                             folder_id=folder_id,
                             folder_name=folder_name,
                             error=thread.exception)
                else:
                    log.info('Folder sync engine finished',
                             account_id=self.account_id,
                             folder_id=folder_id,
                             folder_name=folder_name)
                    # clear the heartbeat for this folder-thread since it
                    # exited cleanly.
                    clear_heartbeat_status(self.account_id, folder_id)

                # note: thread is automatically removed from
                # self.folder_monitors
            else:
                folders.add((folder_name, folder_id))

    def start_delete_handler(self):
        self.delete_handler = DeleteHandler(account_id=self.account_id,
                                            namespace_id=self.namespace_id,
                                            uid_accessor=lambda m: m.imapuids)
        self.delete_handler.start()

    def sync(self):
        self.start_delete_handler()
        folders = set()
        self.start_new_folder_sync_engines(folders)
        while True:
            sleep(self.refresh_frequency)
            self.start_new_folder_sync_engines(folders)
