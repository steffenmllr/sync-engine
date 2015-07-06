
from inbox.mailsync.backends.imap.generic import uidvalidity_cb
from inbox.crispin import writable_connection_pool, GmailCrispinClient
from inbox.models.session import session_scope
from inbox.models import Message, Account, Folder, Namespace
from inbox.models.backends.imap import ImapUid

from inbox.log import get_logger
log = get_logger()

def search(db_session, namespace_id, search_query):
    """ Does an IMAP search on a generic IMAP backend """

    account = db_session.query(Account).join(Namespace) \
              .filter(Namespace.id == namespace_id).one()

    with writable_connection_pool(account.id).get() as crispin_client:
        # crispin_client.conn.debug = 4

        log.debug('Searching {} for `{}`'
                  .format(account.email_address, search_query))
        if isinstance(crispin_client, GmailCrispinClient):

            folder = account.all_folder
            crispin_client.select_folder(folder.name, uidvalidity_cb)
            matching_uids = crispin_client.conn.gmail_search(search_query)

            all_messages = db_session.query(Message.id) \
                .join(ImapUid) \
                .join(Folder).filter(
                        Folder.id == folder.id,
                        ImapUid.account_id == account.id,
                        ImapUid.msg_uid.in_(matching_uids)).all()
            log.debug('Found {} for folder {}. We have synced {} of them.'
                      .format(len(matching_uids), folder.name,
                              len(all_messages)))

        else:
            criteria = 'TEXT "{}"'.format(search_query)
            folders = db_session.query(Folder).filter(
                Folder.account_id == account.id).all()

            # Because the SEARCH command only works on the selected mailbox
            # we will need to loop over folders for search here or
            # Maybe with the new labels/folders API, we can allow devs to
            # pick folder when executing a search in order to scope it.
            # Otherwise this function will take a long time.
            all_messages = set()
            for folder in folders:
                crispin_client.select_folder(folder.name, uidvalidity_cb)
                matching_uids = crispin_client.conn.search(criteria=criteria)
                if not matching_uids:
                    continue

                messages = db_session.query(Message.id) \
                    .join(ImapUid) \
                    .join(Folder) \
                    .filter(Folder.id == folder.id,
                            ImapUid.account_id == account.id,
                            ImapUid.msg_uid.in_(matching_uids)).all()

                all_messages = all_messages.union(set(messages))

                log.debug('Found {} for folder {}. We have synced {} of them.'
                          .format(len(matching_uids), folder.name,
                                  len(messages)))

            return sorted(all_messages, key=lambda x: x.received_date)
