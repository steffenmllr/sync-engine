"""
Integrity check debugging tool for IMAP accounts.

Run as:

    python -m inbox.util.integrity_check_imap --help

"""

from __future__ import absolute_import, division, print_function
import argparse
import httplib2
from apiclient.discovery import build
from oauth2client.client import OAuth2Credentials
from inbox.log import configure_logging, get_logger
#configure_logging(is_prod=False)
from inbox.models import Account, Namespace
from inbox.models.session import session_scope
from inbox.models.backends.gmail import GmailAccount
from inbox.models.backends.imap import ImapThread
from inbox.sqlalchemy_ext.util import b36_to_bin, int128_to_b36 as bin_to_b36
from inbox.auth.gmail import (OAUTH_CLIENT_ID,
                              OAUTH_CLIENT_SECRET,
                              OAUTH_ACCESS_TOKEN_URL)
from sqlalchemy.orm import object_session

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


def dump_account(account):
    print("account class:", account.__class__.__name__)
    print("account table:", account.__tablename__)
    print("account.id:", account.id)
    print("account.public_id:", account.public_id)
    print("account.provider:", account.provider)
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
        print("namespace table:", namespace.__tablename__)
        print("namespace.type:", namespace.type)
        print("namespace.id:", namespace.id)
        print("namespace.public_id:", namespace.public_id)
        print("namespace.account_id:", namespace.account_id)


def main():
    parser = argparse.ArgumentParser(
        description="""
        Output differences between the inbox database and its associated IMAP
        account.  Useful for debugging.
        """)
    parser.add_argument("account_public_ids", nargs='*', metavar="PUBLIC_ID",
        type=lambda x: bin_to_b36(b36_to_bin(x)),
        help="account(s) to check")
    args = parser.parse_args()

    configure_logging(is_prod=False)
    log = get_logger()

    for public_id in args.account_public_ids:
        with session_scope() as db_session:
            accounts = db_session.query(Account).filter(Account.public_id==public_id).all()
            if len(accounts) == 0:
                raise AssertionError("No such account: %s" % public_id)
            elif len(accounts) > 1:
                raise AssertionError(
                    "Multiple accounts with the same public_id: %r" %
                        list(acct.id for acct in accounts))
            account = accounts[0]

            assert account.public_id == public_id

            dump_account(account)

            # TODO:
            # get local list of threads
            # get local list of tags (?)
            # get remote list of folders
            # get remote list of threads
            #db_session.query(



if __name__ == '__main__':
    main()
