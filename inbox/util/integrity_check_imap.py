"""
Integrity check debugging tool for IMAP accounts.

Run as:

    unset LC_ALL
    python -m inbox.util.integrity_check_imap --help

"""

from __future__ import absolute_import, division, print_function
import argparse
import httplib2
from apiclient.discovery import build
from oauth2client.client import OAuth2Credentials
from inbox.log import configure_logging, get_logger
from imapclient import IMAPClient
from inbox.models import Account, Message, Namespace
from inbox.models.session import session_scope
from inbox.models.backends.gmail import GmailAccount
from inbox.models.backends.imap import ImapThread
from inbox.providers import provider_info
from inbox.sqlalchemy_ext.util import b36_to_bin, int128_to_b36 as bin_to_b36
from inbox.auth.gmail import (OAUTH_CLIENT_ID,
                              OAUTH_CLIENT_SECRET,
                              OAUTH_ACCESS_TOKEN_URL)
import sqlalchemy as sa
from sqlalchemy.orm import object_session
import sqlite3

SOURCE_APP_NAME = 'Testing the Gmail API'


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

    # XXX: We might need to spill these to disk.
#    db_local = sqlite3.connect(':memory:')
    db_imap = sqlite3.connect(':memory:')
    db_imap.row_factory = sqlite3.Row
    db_imap.executescript("""
        CREATE TABLE messages (
            id INTEGER NOT NULL PRIMARY KEY,
            subject TEXT
        );

        CREATE TABLE folders (
            id INTEGER NOT NULL PRIMARY KEY,
            folder_name TEXT NOT NULL,
            imap_uidvalidity INTEGER
        );

        CREATE TABLE folder_messages (
            message_id INTEGER NOT NULL,
            folder_id INTEGER NOT NULL,
            imap_uid INTEGER,
            PRIMARY KEY(message_id, folder_id)
        );

        CREATE TABLE folder_flags (
            id INTEGER NOT NULL PRIMARY KEY,
            folder_id INTEGER NOT NULL,
            flag TEXT NOT NULL
        );
        """)



#    slurp_local_namespace(namespace, account, db=db_local)

    slurp_imap_namespace(namespace, account, db=db_imap)
#    dump_imap_namespace(namespace, account)   #  DEBUG FIXME(dlitz)   



    # TODO:
    # get local list of threads
    # get local list of tags (?)
    # get remote list of folders
    # get remote list of threads
    #db_session.query(


def slurp_imap_namespace(namespace, account, db):
    info = provider_info(account.provider)

    conn = IMAPClient(info['imap'], use_uid=True, ssl=True)
    #conn.debug = True       #  DEBUG FIXME(dlitz)   
    if info['auth'] == 'oauth2':
        conn.oauth2_login(account.email_address, account.access_token)
    elif info['auth'] == 'password':
        conn.login(account.email_address, account.password)
    else:
        raise NotImplementedError(
            "auth mechanism {0!r} not implemented for provider {1!r}".format(
                info['auth'], account.provider))

    if account.provider == 'gmail':
        slurp_imap_namespace_gmail(conn, namespace=namespace, account=account, db=db)
    else:
        raise NotImplementedError(
            "only gmail-style accounts currently supported")


#def dump_imap_namespace(namespace, account):
#    info = provider_info(account.provider)
#
#    conn = IMAPClient(info['imap'], use_uid=True, ssl=True)
#    #conn.debug = True       #  DEBUG FIXME(dlitz)   
#    if info['auth'] == 'oauth2':
#        conn.oauth2_login(account.email_address, account.access_token)
#    elif info['auth'] == 'password':
#        conn.login(account.email_address, account.password)
#    else:
#        raise NotImplementedError(
#            "auth mechanism {0!r} not implemented for provider {1!r}".format(
#                info['auth'], account.provider))
#
#    if account.provider == 'gmail':
#        dump_imap_namespace_gmail(conn, namespace=namespace, account=account)
#    else:
#        raise NotImplementedError(
#            "only gmail-style accounts currently supported")


def slurp_imap_namespace_gmail(conn, db, namespace=None, account=None):
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
    folders_fdn = conn.list_folders()

    # Compute set of folders for each flag
    folders_by_flag = {}
    for flags, delimiter, name in folders_fdn:
        for flag in flags:
            folders_by_flag.setdefault(flag, set())
            folders_by_flag[flag].add(name)

    # Output the folder names for each special folder.
    folder_attrs = sorted(list(singleton_flags) + ['inbox_folder'])
    for folder_attr in folder_attrs:
        if folder_attr == 'inbox_folder':
            folder_names = list(name for flags, delimiter, name in folders_fdn)
            if u'INBOX' not in folder_names:
                print("** warning: no INBOX folder")
            else:
                print('account.{0}.name: {1}'.format(folder_attr, u'INBOX'))
        else:
            flag = singleton_flags[folder_attr]
            folders = folders_by_flag.get(flag, ())
            if len(folders) > 1:
                print("** warning: Multiple folders for flag {0}: {1!r}".format(
                    flag, sorted(folders_by_flag[flag])))
            elif len(folders) == 0:
                print("account.{0}: {1}".format(folder_attr, None))
            for folder in folders:
                print("account.{0}.name: {1}".format(folder_attr, folder))

    # TODO Open the "Trash" folder and slurp the list of messages
    # TODO Open the "All Mail" folder and slurp the list of messages

    dbc = db.cursor()

    for folder in folders_by_flag[u'\\All'] + folders_by_flag[u'\\Trash']:
        select_response = conn.select_folder(folder)
        uids = conn.search()
        dbc.execute(
            "INSERT INTO folders (folder_name, imap_uidvalidity) VALUES (?, ?)"
            (folder, select_response[u'UIDVALIDITY']))




    import IPython; IPython.embed() #  DEBUG FIXME(dlitz)   



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
