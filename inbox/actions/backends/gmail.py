""" Operations for syncing back local datastore changes to Gmail. """

from inbox.crispin import writable_connection_pool, retry_crispin
from inbox.actions.backends.generic import (set_remote_starred,
                                            set_remote_unread,
                                            uids_by_folder)
from inbox.mailsync.backends.imap.generic import uidvalidity_cb

PROVIDER = 'gmail'

__all__ = ['set_remote_starred', 'set_remote_unread', 'remote_save_draft',
           'remote_change_labels', 'remote_delete_draft']


def remote_change_labels(account, message_id, db_session, removed_labels,
                         added_labels):
    # STOPSHIP(emfree): handle canonical labels!
    uids_for_message = uids_by_folder(message_id, db_session)
    with writable_connection_pool(account.id).get() as crispin_client:
        for folder_name, uids in uids_for_message.items():
            crispin_client.select_folder(folder_name, uidvalidity_cb)
            crispin_client.conn.add_gmail_labels(uids, added_labels)
            crispin_client.conn.remove_gmail_labels(uids, removed_labels)


def remote_save_draft(account, mimemsg, db_session, date=None):
    with writable_connection_pool(account.id).get() as crispin_client:
        crispin_client.conn.select_folder(
            crispin_client.folder_names()['drafts'])
        crispin_client.save_draft(mimemsg, date)


@retry_crispin
def remote_delete_draft(account, inbox_uid, message_id_header, db_session):
    with writable_connection_pool(account.id).get() as crispin_client:
        crispin_client.delete_draft(inbox_uid, message_id_header)
