# -*- coding: utf-8 -*-
""" Operations for syncing back local datastore changes to
    generic IMAP providers.
"""
from collections import defaultdict
from inbox.crispin import writable_connection_pool, retry_crispin
from inbox.log import get_logger
from inbox.mailsync.backends.imap.generic import uidvalidity_cb
from inbox.models.backends.imap import ImapUid
from inbox.models.folder import Folder

log = get_logger()

PROVIDER = 'generic'

__all__ = ['set_remote_starred', 'set_remote_unread', 'remote_move',
           'remote_save_draft', 'remote_delete_draft']


def uids_by_folder(message_id, db_session):
    results = db_session.query(ImapUid.msg_uid, Folder.name).join(Folder). \
        filter(ImapUid.message_id == message_id).all()
    mapping = defaultdict(list)
    for uid, folder_name in results:
        mapping[folder_name].append(uid)
    return mapping


def _set_flag(account, message_id, flag_name, db_session, is_add):
    uids_for_message = uids_by_folder(message_id, db_session)
    if not uids_for_message:
        log.warning('No UIDs found for message', message_id=message_id)
        return

    with writable_connection_pool(account.id).get() as crispin_client:
        for folder_name, uids in uids_for_message.items():
            crispin_client.select_folder(folder_name, uidvalidity_cb)
            if is_add:
                crispin_client.conn.add_flags(uids, [flag_name])
            else:
                crispin_client.conn.remove_flags(uids, [flag_name])


def set_remote_starred(account, message_id, starred, db_session):
    _set_flag(account, message_id, '\\Flagged', db_session, starred)


def set_remote_unread(account, message_id, unread, db_session):
    _set_flag(account, message_id, '\\Seen', db_session, not unread)


@retry_crispin
def remote_move(account, message_id, from_folder, to_folder, db_session):
    # STOPSHIP(emfree): implement
    pass


@retry_crispin
def remote_save_draft(account, folder_name, message, db_session, date=None):
    with writable_connection_pool(account.id).get() as crispin_client:
        # Create drafts folder on the backend if it doesn't exist.
        if 'drafts' not in crispin_client.folder_names():
            # STOPSHIP(emfree): log and continue :/
            crispin_client.create_folder('Drafts')

        assert folder_name == crispin_client.folder_names()['drafts']
        crispin_client.select_folder(folder_name, uidvalidity_cb)
        crispin_client.save_draft(message, date)


@retry_crispin
def remote_delete_draft(account, inbox_uid, message_id_header, db_session):
    with writable_connection_pool(account.id).get() as crispin_client:
        crispin_client.delete_draft(inbox_uid, message_id_header)


def remote_save_sent(account, folder_name, message, db_session, date=None,
                     create_backend_sent_folder=False):
    def fn(account, db_session, crispin_client):
        if create_backend_sent_folder:
            if 'sent' not in crispin_client.folder_names():
                crispin_client.create_folder('Sent')

        crispin_client.select_folder(folder_name, uidvalidity_cb)
        crispin_client.create_message(message, date)

    # STOPSHIP(emfree): fix
    return syncback_action(fn, account, folder_name, db_session,
                           select_folder=False)
