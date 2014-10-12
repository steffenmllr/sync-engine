"""
-----------------
GMAIL SYNC ENGINE
-----------------

Gmail is theoretically an IMAP backend, but it differs enough from standard
IMAP that we handle it differently. The state-machine rigamarole noted in
.imap.py applies, but we change a lot of the internal algorithms to fit Gmail's
structure.

Gmail has server-side threading, labels, and all messages are a subset of
either the 'All Mail', 'Spam' and 'Trash' folders. We only sync those three
folders, and use X-GM-LABELS to determine whether a message in All Mail is also
in the inbox or not.

The only way to delete messages permanently on Gmail is to move a message to
the trash folder and then EXPUNGE.

We use Gmail's thread IDs locally, and expand threads when downloading so the
user always gets the full thread when they look at mail.

"""
from __future__ import division

from gevent import spawn
from gevent.queue import JoinableQueue

from inbox.util.itert import chunk, partition
from inbox.util.misc import timed

from inbox.crispin import GmailSettingError
from inbox.log import get_logger
from inbox.models import Message
from inbox.models.backends.imap import ImapUid, ImapThread
from inbox.mailsync.backends.base import mailsync_session_scope
from inbox.mailsync.backends.imap.condstore import CondstoreFolderSyncEngine
from inbox.mailsync.backends.imap.monitor import ImapSyncMonitor
from inbox.mailsync.backends.imap import common

PROVIDER = 'gmail'
SYNC_MONITOR_CLS = 'GmailSyncMonitor'


class GmailSyncMonitor(ImapSyncMonitor):
    def __init__(self, *args, **kwargs):
        kwargs['retry_fail_classes'] = [GmailSettingError]
        ImapSyncMonitor.__init__(self, *args, **kwargs)
        self.sync_engine_class = GmailFolderSyncEngine

log = get_logger()


class GmailFolderSyncEngine(CondstoreFolderSyncEngine):
    def should_idle(self, crispin_client):
        if not hasattr(self, '_should_idle'):
            self._should_idle = (self.folder_name ==
                                 crispin_client.folder_names()['all'])
        return self._should_idle

    def initial_sync_impl(self, crispin_client):
        assert crispin_client.selected_folder_name == self.folder_name
        self.save_initial_folder_info(crispin_client)
        download_stack = self.refresh_uids(crispin_client)
        remote_g_metadata = crispin_client.g_metadata(download_stack)
        changed_uid_channel = JoinableQueue()
        change_poller = spawn(self.poll_for_changes, changed_uid_channel)
        try:
            while download_stack:
                self.__process_updates_in_initial_sync(
                    crispin_client, changed_uid_channel, download_stack,
                    remote_g_metadata)
                self.__process_top_stack_entry(
                    crispin_client, download_stack, remote_g_metadata)
                self.sleep_if_throttled()
        finally:
            change_poller.kill()

    def __process_updates_in_initial_sync(self, crispin_client,
                                          changed_uid_channel, download_stack,
                                          remote_g_metadata):
        if not changed_uid_channel.empty():
            changed_uids = changed_uid_channel.get()
            new_g_metadata = crispin_client.g_metadata(changed_uids)
            changed_g_thrids = {m.thrid for m in new_g_metadata.values()}
            self.handle_changes(crispin_client, changed_uids)
            for uid in download_stack:
                if remote_g_metadata[uid].thrid in changed_g_thrids:
                    download_stack.remove(uid)
            changed_uid_channel.task_done()

    def __process_top_stack_entry(self, crispin_client, download_stack,
                                  remote_g_metadata):
        uid = download_stack[-1]
        thrid = remote_g_metadata[uid].thrid
        self.__download_thread(crispin_client, thrid)
        thread_uids = [u for u in download_stack
                       if remote_g_metadata[u].thrid == thrid]
        for u in thread_uids:
            download_stack.remove(u)

    def handle_changes(self, crispin_client, changed_uids):
        with mailsync_session_scope() as db_session:
            local_uids = self.local_uids(db_session)
        changed_uids = set(changed_uids)
        new_uids = changed_uids - local_uids
        g_metadata = crispin_client.g_metadata(new_uids)
        thrids_with_adds = {m.thrid for m in g_metadata.values()}
        for thrid in thrids_with_adds:
            self.__download_thread(crispin_client, thrid)
        updated_uids = changed_uids & local_uids
        self.update_metadata(crispin_client, updated_uids)
        remote_uids = crispin_client.all_uids()
        with mailsync_session_scope() as db_session:
            self.remove_deleted_uids(db_session, local_uids, remote_uids)

    # TODO(emfree): remove after profiling.
    @timed
    def __deduplicate_message_download(self, crispin_client, remote_g_metadata,
                                       uids):
        """
        Deduplicate message download using X-GM-MSGID.

        Returns
        -------
        list
            Deduplicated UIDs.

        """
        with mailsync_session_scope() as db_session:
            local_g_msgids = g_msgids(self.namespace_id, db_session,
                                      in_={remote_g_metadata[uid].msgid
                                           for uid in uids if uid in
                                           remote_g_metadata})

        full_download, imapuid_only = partition(
            lambda uid: uid in remote_g_metadata and
            remote_g_metadata[uid].msgid in local_g_msgids,
            sorted(uids, key=int))
        if imapuid_only:
            self.__add_new_imapuids(imapuid_only, remote_g_metadata,
                                    crispin_client)
        return full_download

    def add_message_attrs(self, db_session, new_uid, msg, folder):
        """ Gmail-specific post-create-message bits. """
        # Disable autoflush so we don't try to flush a message with null
        # thread_id, causing a crash, and so that we don't flush on each
        # added/removed label.
        with db_session.no_autoflush:
            new_uid.message.g_msgid = msg.g_msgid
            # NOTE: g_thrid == g_msgid on the first message in the thread :)
            new_uid.message.g_thrid = msg.g_thrid

            # we rely on Gmail's threading instead of our threading algorithm.
            new_uid.message.thread_order = 0
            new_uid.update_imap_flags(msg.flags, msg.g_labels)

            thread = new_uid.message.thread = ImapThread.from_gmail_message(
                db_session, new_uid.account.namespace, new_uid.message)

            # make sure this thread has all the correct labels
            common.update_thread_labels(thread, folder.name, msg.g_labels,
                                        db_session)
            return new_uid

    def __download_thread(self, crispin_client, g_thrid):
        """
        Download all messages in thread identified by `g_thrid`.

        Messages are downloaded oldest-first via All Mail, which allows us
        to get the entire thread regardless of which folders it's in. We do
        oldest-first so that if the thread started with a message sent from the
        Inbox API, we can reconcile this thread appropriately with the existing
        message/thread.
        """
        thread_uids = crispin_client.expand_thread(g_thrid)
        thread_g_metadata = crispin_client.g_metadata(thread_uids)
        log.debug('downloading thread',
                  g_thrid=g_thrid, message_count=len(thread_uids))
        to_download = self.__deduplicate_message_download(
            crispin_client, thread_g_metadata, thread_uids)
        log.debug(deduplicated_message_count=len(to_download))
        for uids in chunk(to_download, crispin_client.CHUNK_SIZE):
            self.download_and_commit_uids(
                crispin_client, crispin_client.selected_folder_name, uids)

    def __add_new_imapuids(self, uids, g_metadata, crispin_client):
        """
        Add ImapUid entries only for (already-downloaded) messages.

        If a message has already been downloaded via another folder, we only
        need to add `ImapUid` accounting for the current folder. `Message`
        objects etc. have already been created.

        """
        with mailsync_session_scope() as db_session:
            # Since we prioritize download for messages in certain threads, we
            # may already have ImapUid entries despite calling this method.
            local_folder_uids = {uid for uid, in
                                 db_session.query(ImapUid.msg_uid)
                                 .filter(
                                     ImapUid.account_id == self.account_id,
                                     ImapUid.folder_id == self.folder_id,
                                     ImapUid.msg_uid.in_(uids))}
            uids = [uid for uid in uids if uid not in local_folder_uids]

            if not uids:
                return

            flags = crispin_client.flags(uids)

            g_msgids = [g_metadata[uid].g_msgid for uid in uids]
            g_msgid_to_id = dict(
                db_session.query(Message.g_msgid, Message.id).
                filter(Message.namespace_id == self.namespace_id,
                       Message.g_msgid.in_(g_msgids)))

            for uid in uids:
                g_msgid = g_metadata[uid].g_msgid
                if g_msgid in g_msgid_to_id:
                    message_id = g_msgid_to_id[g_msgid]
                    new_imapuid = ImapUid(
                        account_id=self.account_id,
                        folder_id=self.folder_id,
                        msg_uid=uid,
                        message_id=message_id)
                    db_session.add(new_imapuid)
                    if uid in flags:
                        new_imapuid.update_imap_flags(flags[uid].flags,
                                                      flags[uid].labels)
            db_session.commit()


def uid_download_folders(crispin_client):
    """ Folders that don't get thread-expanded. """
    return [crispin_client.folder_names()[tag] for tag in
            ('trash', 'spam') if tag in crispin_client.folder_names()]


def thread_expand_folders(crispin_client):
    """Folders that *do* get thread-expanded. """
    return [crispin_client.folder_names()[tag] for tag in ('all')]


def g_msgids(namespace_id, session, in_):
    if not in_:
        return []
    # Easiest way to account-filter Messages is to namespace-filter from
    # the associated thread. (Messages may not necessarily have associated
    # ImapUids.)
    in_ = {long(i) for i in in_}  # in case they are strings
    if len(in_) > 1000:
        # If in_ is really large, passing all the values to MySQL can get
        # deadly slow. (Approximate threshold empirically determined)
        query = session.query(Message.g_msgid). \
            filter(Message.namespace_id == namespace_id).all()
        return sorted(g_msgid for g_msgid, in query if g_msgid in in_)
    # But in the normal case that in_ only has a few elements, it's way better
    # to not fetch a bunch of values from MySQL only to return a few of them.
    query = session.query(Message.g_msgid). \
        filter(Message.namespace_id == namespace_id,
               Message.g_msgid.in_(in_)).all()
    return {g_msgid for g_msgid, in query}
