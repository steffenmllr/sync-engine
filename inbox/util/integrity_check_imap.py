"""
Integrity check debugging tool for IMAP accounts.

Run as:

    unset LC_ALL
    python -m inbox.util.integrity_check_imap --help

"""

from __future__ import absolute_import, division, print_function
import argparse
import errno
import httplib2
import itertools
import os
from apiclient.discovery import build
from oauth2client.client import OAuth2Credentials
from inbox.log import configure_logging, get_logger
from imapclient import IMAPClient
from inbox.models import Account, Folder, FolderItem, Message, Namespace, Thread
from inbox.models.session import session_scope
from inbox.models.backends.gmail import GmailAccount
from inbox.models.backends.imap import ImapThread
from inbox.providers import provider_info
from inbox.sqlalchemy_ext.util import b36_to_bin, int128_to_b36 as bin_to_b36
from inbox.auth.gmail import (OAUTH_CLIENT_ID,
                              OAUTH_CLIENT_SECRET,
                              OAUTH_ACCESS_TOKEN_URL)
from inbox.util.addr import parse_email_address_list
import sqlalchemy as sa
from sqlalchemy.orm import object_session
import sqlite3

SOURCE_APP_NAME = 'Testing the Gmail API'


SQLITE3_INIT_SCRIPT = r"""
    CREATE TABLE messages (
        id INTEGER NOT NULL PRIMARY KEY,
        date TEXT,
        subject TEXT,
        size INTEGER,
        in_reply_to TEXT,
        message_id_header TEXT,
        x_gm_msgid TEXT UNIQUE,
        x_gm_thrid TEXT
    );
    CREATE INDEX ix_messages_message_id_header ON messages(message_id_header);
    CREATE INDEX ix_messages_x_gm_thrid ON messages(x_gm_thrid);
    CREATE INDEX ix_messages_x_gm_msgid ON messages(x_gm_msgid);

    -- TODO
    -- -- Info attached to messages where there are multiple values
    -- -- (e.g. To, Cc, & other headers)
    -- CREATE TABLE message_info (
    --     id INTEGER NOT NULL PRIMARY KEY,
    --     message_id INTEGER NOT NULL,
    --     name TEXT NOT NULL,
    --     value TEXT
    -- );

    CREATE TABLE threads (
        id INTEGER NOT NULL PRIMARY KEY,
        x_gm_thrid TEXT UNIQUE
    );

    CREATE TABLE thread_messages (
        thread_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        PRIMARY KEY(thread_id, message_id)
    );

    CREATE TABLE folders (
        folder_name TEXT NOT NULL PRIMARY KEY,
        imap_delimiter TEXT,
        imap_uidvalidity INTEGER,
        imap_uidnext INTEGER,
        imap_noselect BOOLEAN
    );

    CREATE TABLE folder_messages (
        folder_name TEXT NOT NULL,
        imap_uid INTEGER NOT NULL,
        message_id INTEGER,
        PRIMARY KEY(folder_name, imap_uid)
    );

    -- Raw gmail labels are different per-message.
    CREATE TABLE folder_message_gm_labels (
        folder_name TEXT NOT NULL,
        message_id INTEGER NOT NULL,
        label TEXT NOT NULL,
        PRIMARY KEY(folder_name, message_id, label)
    );

    CREATE TABLE folder_flags (
        folder_name TEXT NOT NULL,
        flag TEXT NOT NULL,
        PRIMARY KEY(folder_name, flag)
    );

    CREATE TABLE special_folders (
        attr_name TEXT NOT NULL PRIMARY KEY,
        folder_name TEXT NOT NULL UNIQUE
    );
"""


class GmailThread(object):
    def __init__(self, hex_thrid, labels=None):
        self.hex_thrid = hex_thrid
        self.labels = labels or []

    def __repr__(self):
        return 'hex_thrid: {}, labels: {}'.format(self.hex_thrid, self.labels)


class Diff(object):
    def __init__(self, local, remote):
        self.local = local
        self.remote = remote

    def __repr__(self):
        return 'local: {}, remote: {}'.format(self.local, self.remote)


class GmailAPIClient(object):
    def __init__(self, account_id):
        self.account_id = account_id
        with session_scope() as db_session:
            account = db_session.query(GmailAccount).get(account_id)
            client_id = account.client_id or OAUTH_CLIENT_ID
            client_secret = account.client_secret or OAUTH_CLIENT_SECRET
            access_token = account.access_token
            refresh_token = account.refresh_token
            expiry = account.access_expiry

        credentials = OAuth2Credentials(access_token, client_id, client_secret,
                                        refresh_token, expiry,
                                        OAUTH_ACCESS_TOKEN_URL,
                                        SOURCE_APP_NAME)

        http = httplib2.Http()
        http = credentials.authorize(http)

        self.service = build(serviceName='gmail', version='v1', http=http)
        self._label_cache = {}

    def get_g_thrids(self):
        all_threads = []
        page_token = None
        while True:
            partial_results = self.service.users().threads(). \
                list(userId='me', pageToken=page_token).execute()
            threads = [GmailThread(item['id']) for item in
                       partial_results['threads']]
            all_threads.extend(threads)
            if 'nextPageToken' in partial_results:
                page_token = partial_results['nextPageToken']
            else:
                print('fetched {} thrids'.format(len(all_threads)))
                return all_threads

    def get_thread_labels(self, hex_thrid):
        labels = []
        thread = self.service.users().threads(). \
            get(userId='me', id=hex_thrid).execute()
        for msg in thread['messages']:
            label_ids = msg.get('labelIds') or []
            for id in label_ids:
                if id in self._label_cache:
                    label = self._label_cache[id]
                else:
                    label = self.service.users().labels(). \
                        get(userId='me', id=id).execute()['name']
                    self._label_cache[id] = label
                labels.append(label)
        return labels

    def get_all_labels(self):
        threads = self.get_g_thrids()
        for thread in threads:
            labels = self.get_thread_labels(thread.hex_thrid)
            thread.labels = labels
        return threads

    def diff_with_local(self):
        remote_threads = self.get_all_labels()
        diffs = {}
        with session_scope() as db_session:
            for remote_thread in remote_threads:
                remote_labels = {l.lower() for l in remote_thread.labels}
                if 'inbox' not in remote_labels:
                    remote_labels.add('archive')
                int_thrid = int(remote_thread.hex_thrid, 16)
                local_thread = db_session.query(ImapThread).filter(
                    ImapThread.namespace_id == self.account_id,
                    ImapThread.g_thrid == int_thrid).first()
                if local_thread is None:
                    diffs[remote_thread.hex_thrid] = Diff(None, remote_labels)
                else:
                    local_labels = {t.name.lower() for t in local_thread.tags}
                    # Don't get these from the Gmail API.
                    local_labels.discard('all')
                    local_labels.discard('important')
                    if local_labels != remote_labels:
                        diffs[remote_thread.hex_thrid] = Diff(local_labels,
                                                              remote_labels)
        return diffs


def dump_list():
    """
    Print a tab-separated list of accounts
    """
    with session_scope() as db_session:
        accounts = db_session.query(Account).order_by(Account.id).all()
        for account in accounts:
            print("\t".join([
                str(account.id),
                account.public_id,
                account.email_address,
                account.provider,
                account.__tablename__,
            ]))


def dump_accounts(public_ids):
    for public_id in public_ids:
        with session_scope() as db_session:
            accounts = db_session.query(Account).filter(
                Account.public_id==public_id).order_by(Account.id).all()
            if len(accounts) == 0:
                raise AssertionError("No such account: %s" % public_id)
            elif len(accounts) > 1:
                raise AssertionError(
                    "Multiple accounts with the same public_id: %r" %
                        list(acct.id for acct in accounts))
            account = accounts[0]

            assert account.public_id == public_id

            dump_account(account)


def dump_account(account):
    print("account class:", account.__class__.__name__)
    print("account table:", account.__tablename__)
    print("account.id:", account.id)
    print("account.public_id:", account.public_id)
    print("account.provider:", account.provider)

    # grep bait
    expected_folder_attrs = [
        'all_folder',
        'archive_folder',
        'drafts_folder',
        'important_folder',
        'inbox_folder',
        'sent_folder',
        'spam_folder',
        'starred_folder',
        'trash_folder',
    ]

    folder_attrs = sorted(a for a in dir(account) if a.endswith('_folder'))

    if folder_attrs != expected_folder_attrs:
        print("** warning: folder_attrs not what was expected:", folder_attrs)

    for folder_attr in folder_attrs:
        folder = getattr(account, folder_attr)
        if folder is None:
            print("account.{0}: {1}".format(folder_attr, folder))
        else:
            print("account.{0}.name: {1}".format(folder_attr, folder.name))

    # account.state?
    # account.sync_status?

    namespaces = (object_session(account).query(Namespace)
        .filter(Namespace.account_id == account.id)
        .order_by(Namespace.id)
        .all())

    if len(namespaces) == 0:
        print("** warning: no namespace for account!")
    elif len(namespaces) != 1:
        print("** warning: multiple namespaces for account!")

    for namespace in namespaces:
        dump_namespace(namespace, account)


def dump_namespace(namespace, account):
    print("namespace table:", namespace.__tablename__)
    print("namespace.type:", namespace.type)
    print("namespace.id:", namespace.id)
    print("namespace.public_id:", namespace.public_id)
    print("namespace.account_id:", namespace.account_id)

#    for tag in sorted(namespace.tags.keys()):
#        print("tag:", tag)

#    for thread in sorted(namespace.threads):
#        print("thread subject:", thread.subject)
#        for tag in sorted(thread.tags, key=lambda tag: tag.name):
#            print("thread tag:", tag.name)

    # XXX: We might need to stream this using a raw DB connection.
#    all_messages = object_session(namespace).query(Message).order_by(Message.subject).all()
#
#    for thread in namespace.threads:
#        for message in thread.messages:
#            print("message.subject:", message.subject)
#            for imapuid in message.imapuids:
#                print("message uid: {0} in folder: {1}".format(
#                    imapuid.msg_uid, imapuid.folder.name))
# TODO

    try:
        os.unlink('local.db')
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
#    db_local = sqlite3.connect(':memory:')
    db_local = sqlite3.connect('local.db')
    db_local.row_factory = sqlite3.Row
    db_local.executescript(SQLITE3_INIT_SCRIPT)
    slurp_local_namespace(namespace, account, db=db_local)

    try:
        os.unlink('imap.db')
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise
#    db_imap = sqlite3.connect(':memory:')
    db_imap = sqlite3.connect('imap.db')
    db_imap.row_factory = sqlite3.Row
    db_imap.executescript(SQLITE3_INIT_SCRIPT)
    slurp_imap_namespace(namespace, account, db=db_imap)

def slurp_local_namespace(namespace, account, db):
    info = provider_info(account.provider)

    if account.provider == 'gmail':
        slurp_local_namespace_gmail(namespace=namespace, account=account, db=db)
    else:
        raise NotImplementedError(
            "only gmail-style accounts currently supported")



def slurp_imap_namespace(namespace, account, db):
    info = provider_info(account.provider)

    imap = IMAPClient(info['imap'], use_uid=True, ssl=True)
    imap.debug = True       #  DEBUG FIXME(dlitz)   
    if info['auth'] == 'oauth2':
        imap.oauth2_login(account.email_address, account.access_token)
    elif info['auth'] == 'password':
        imap.login(account.email_address, account.password)
    else:
        raise NotImplementedError(
            "auth mechanism {0!r} not implemented for provider {1!r}".format(
                info['auth'], account.provider))

    if account.provider == 'gmail':
        slurp_imap_namespace_gmail(imap, namespace=namespace, account=account, db=db)
    else:
        raise NotImplementedError(
            "only gmail-style accounts currently supported")


def slurp_imap_namespace_gmail(imap, db, namespace=None, account=None):
    # folder attrs -> RFC 6154 Special-Use mailbox flags
    singleton_flags = {
        'all_folder': u'\\All',
        'archive_folder': u'\\Archive',
        'drafts_folder': u'\\Drafts',
        'starred_folder': u'\\Flagged',
        'spam_folder': u'\\Junk',
        'sent_folder': u'\\Sent',
        'trash_folder': u'\\Trash',
    }

    # List folders -- Returns sequence of (flags, delimiter, name)
    folders_fdn = imap.list_folders()
    with db:
        # Folder names & delimiters
        db.executemany(
            "INSERT INTO folders (folder_name, imap_delimiter) VALUES (?, ?)",
            ((name, delimiter) for flags, delimiter, name in folders_fdn))

        # Folder flags
        db.executemany("""
            INSERT INTO folder_flags (folder_name, flag) VALUES (?, ?)
            """, ((name, flag)
                  for flags, delimiter, name in folders_fdn
                  for flag in flags))

        # Set imap_noselect = 1 on folders that have the \Noselect flag;
        # Set imap_noselect = 0 on folders that don't.
        db.execute("""
            UPDATE folders SET imap_noselect = (
                SELECT folder_flags.flag IS NOT NULL
                FROM folders AS a LEFT JOIN folder_flags ON (
                    a.folder_name = folder_flags.folder_name AND
                    folder_flags.flag = '\Noselect'
                )
                WHERE folders.folder_name = a.folder_name
            )
            """)

        # Insert 'inbox_folder' -> 'INBOX' if there is an INBOX folder, which
        # there should always be, I think.
        db.execute("""
            INSERT INTO special_folders (attr_name, folder_name)
            SELECT ?, folder_name FROM folders WHERE folder_name = ?
            """, ['inbox_folder', 'INBOX'])

        # Insert other special folder names
        db.executemany("""
            INSERT INTO special_folders (attr_name, folder_name)
            SELECT ?, folder_name FROM folder_flags WHERE flag = ?
            """, singleton_flags.items())

    # Fetch all messages from each folder
    with db:
        folder_names = [row[0] for row in db.execute(
            "SELECT folder_name FROM folders WHERE NOT imap_noselect")]

        for folder_name in folder_names:
            # EXAMINE the folder
            examine_response = imap.select_folder(folder_name, readonly=True)

            # Update imap_uidvalidity
            db.execute("""
                UPDATE folders
                SET imap_uidvalidity = ?, imap_uidnext = ?
                WHERE folder_name = ?
                """, [examine_response[u'UIDVALIDITY'],
                      examine_response[u'UIDNEXT'],
                      folder_name])

            # Get uids of the messages in the folder
            imap_uids = imap.search()

            # Result should match the stated number of messages in the folder.
            if len(imap_uids) != examine_response[u'EXISTS']:
                raise AssertionError("len(imap_uids)={0}, EXISTS={1!r}".format(
                    len(imap_uids), examine_response[u'EXISTS']))

            # Create folder_messages entries
            db.executemany("""
                INSERT INTO folder_messages (folder_name, imap_uid, message_id)
                VALUES (?, ?, NULL)
                """, ((folder_name, imap_uid) for imap_uid in imap_uids))

            # Get the folder flags
            folder_flags = set(row[0] for row in db.execute(
                "SELECT flag FROM folder_flags WHERE folder_name = ?",
                [folder_name]))

            # This is Gmail, so only actually fetch messages from the 'All
            # Mail' and 'Trash' folders.  This *should* give us all of the
            # messages.
            #if not folder_flags & {u'\\All', u'\\Trash', u'\\Sent'}:
            #    continue

            # Get folder messages
            batch_size = 1000
            fetch_data = ['RFC822.SIZE', 'ENVELOPE', 'FLAGS',
                          'X-GM-MSGID', 'X-GM-THRID', 'X-GM-LABELS']
            for i in range(0, len(imap_uids), batch_size):
                imap_uids_batch = imap_uids[i:i+batch_size]

                # Fetch message info from the IMAP server
                fetch_response = imap.fetch(imap_uids_batch, fetch_data)

                # Fetch message info and insert it into the messages table.
                # Don't bother deduplicating at this point.
                for uid, data in fetch_response.items():
                    msg_data = dict(
                        date=data['ENVELOPE'].date,
                        subject=data['ENVELOPE'].subject,
                        in_reply_to=data['ENVELOPE'].in_reply_to,
                        size=data['RFC822.SIZE'],
                        message_id_header=data['ENVELOPE'].message_id,
                        x_gm_thrid=unicode(data['X-GM-THRID']),
                        x_gm_msgid=unicode(data['X-GM-MSGID']),
                    )

                    # TODO
                    #msg_info_data = list(itertools.chain(
                    #    [('from', a) for a in data['ENVELOPE'].from_ or ()],
                    #    [('sender', a) for a in data['ENVELOPE'].sender or ()],
                    #    [('reply_to', a) for a in data['ENVELOPE'].reply_to or ()],
                    #    [('to', a) for a in data['ENVELOPE'].to or ()],
                    #    [('cc', a) for a in data['ENVELOPE'].cc or ()],
                    #    [('bcc', a) for a in data['ENVELOPE'].bcc or ()],
                    #))

                    # Check if we've already stored the message
                    cur = db.execute("""
                        SELECT id, x_gm_msgid FROM messages
                        WHERE x_gm_msgid = :x_gm_msgid
                        """, msg_data)
                    row = next(iter(cur.fetchall()), None)    # returns 0 or 1 rows
                    message_id = row['id'] if row is not None else None

                    # If we've never stored the message, store it now.
                    if message_id is None:
                        cur = db.execute("""
                            INSERT INTO messages (
                                date, subject, in_reply_to, size,
                                message_id_header, x_gm_msgid, x_gm_thrid
                            ) VALUES (
                                :date, :subject, :in_reply_to, :size,
                                :message_id_header, :x_gm_msgid, :x_gm_thrid
                            )
                            """, msg_data)
                        message_id = cur.lastrowid

                        # TODO
                        #db.executemany("""
                        #    INSERT INTO message_info (message_id, name, value)
                        #    VALUES (?, ?, ?)
                        #    """,
                        #    [(message_id, name, value)
                        #     for name, value in msg_info_data])

                    # Store the Gmail labels (these can be different in
                    # different folders; e.g. messages in the 'Sent' folder are
                    # missing the u'\\Sent' label)
                    db.executemany("""
                        INSERT INTO folder_message_gm_labels
                            (folder_name, message_id, label)
                        VALUES (?, ?, ?)
                        """,
                        ((folder_name, message_id, label)
                         for label in data['X-GM-LABELS']))

                    # Mark the message as being in the current folder.
                    db.execute("""
                        UPDATE folder_messages
                        SET message_id = ?
                        WHERE folder_name = ? AND imap_uid = ?
                        """, (message_id, folder_name, uid))

        # Construct threads (assuming gmail for now)
        db.execute("""
            INSERT INTO threads (x_gm_thrid)
            SELECT DISTINCT x_gm_thrid FROM messages
            """)
        db.execute("""
            INSERT INTO thread_messages (thread_id, message_id)
            SELECT threads.id, messages.id
            FROM threads, messages
            WHERE threads.x_gm_thrid = messages.x_gm_thrid
            """)


def slurp_local_namespace_gmail(db, namespace=None, account=None):
    db_session = object_session(namespace)

    with db:
        # Insert folders
        db.executemany("""
            INSERT INTO folders (folder_name, imap_uidvalidity)
            VALUES (?, ?)
            """,
            ((f.name,
              f.imapfolderinfo[0].uidvalidity if f.imapfolderinfo else None)
             for f in account.folders))

        # Fetch threads
        #threads = (db_session.query(ImapThread.id, ImapThread.g_thrid)
        #    .filter_by(namespace_id=namespace.id)
        #    .all())
        threads = namespace.threads

        # Insert threads
        db.executemany("""
            INSERT INTO threads (id, x_gm_thrid) VALUES (?, ?)
            """, ((thread.id, thread.g_thrid) for thread in threads))

        # Keep thread ids
        thread_ids = [thread.id for thread in threads]
        del threads

        # Slurp messages in batches
        batch_size = 1000
        for i in range(0, len(thread_ids), batch_size):
            thread_ids_batch = thread_ids[i:i+batch_size]
            rows = (
                db_session.query(Message.id, Message.g_thrid, Message.g_msgid,
                    Message.received_date, Message.subject, Message.size)
                .filter(Message.thread_id.in_(thread_ids_batch))
                .all())
            db.executemany("""
                INSERT INTO messages (id, x_gm_thrid, x_gm_msgid, date, subject, size)
                VALUES (?, ?, ?, ?, ?, ?)
                """, rows)


def main():
    parser = argparse.ArgumentParser(
        description="""
        Output differences between the inbox database and its associated IMAP
        account.  Useful for debugging.
        """)
    parser.add_argument("--list", action='store_true',
        help="output a tab-separated list of accounts")
    parser.add_argument("--all", action='store_true',
        help="all accounts")
    parser.add_argument("account_public_ids", nargs='*', metavar="PUBLIC_ID",
        type=lambda x: bin_to_b36(b36_to_bin(x)),
        help="account(s) to check")
    args = parser.parse_args()

    if not args.all:
        public_ids = args.account_public_ids
    else:
        with session_scope() as db_session:
            accounts = db_session.query(Account.public_id).all()
            public_ids = [account.public_id for account in accounts]

    if args.list:
        #dump_list(public_ids)    #  TODO(dlitz)
        if not args.all:
            parser.error("--all must be specified with --list")
        dump_list()
    else:
        dump_accounts(public_ids)


if __name__ == '__main__':
    main()
