from tests.util.base import gmail_account, generic_account

from inbox.crispin import RawFolder
from inbox.models import Folder, Label, Category


def test_gmail_folder_label_creation(empty_db):
    from inbox.mailsync.backends.gmail import GmailSyncMonitor

    account = gmail_account(empty_db)
    assert account.discriminator == 'gmailaccount'

    raw_folders = [
        # Gmail 'canonical folders'
        RawFolder(name='All', canonical_name='all', category='all'),
        RawFolder(name='INBOX', canonical_name='inbox', category='inbox'),
        RawFolder(name='myTra$h', canonical_name='trash', category='trash'),
        # Recognized categories
        RawFolder(name='ma envoyes', canonical_name=None, category='sent'),
        RawFolder(name='icecreampop', canonical_name=None, category='junk'),
        # Others
        RawFolder(name='roundwego', canonical_name=None, category=None),
        RawFolder(name='carousel', canonical_name=None, category=None),
        RawFolder(name='circusfades', canonical_name=None, category=None)]

    GmailSyncMonitor(account).save_folder_names(empty_db.session,
                                                account.id, raw_folders)

    # For Gmail, /only/ Inbox-canonical folders are created as Folders.
    folders = empty_db.session.query(Folder).filter(
        Folder.account_id == account.id)

    assert folders.count() == 3
    for f in folders.all():
        assert f.name in ['All', 'INBOX', 'myTra$h']
        assert f.canonical_name in ['all', 'inbox', 'trash']

    # For Gmail, Inbox-canonical folders have labels associated with them too
    # and everything else is a Label too.
    labels = empty_db.session.query(Label).filter(
        Label.account_id == account.id)

    assert labels.count() == 8
    for l in labels.all():
        if l.name in ['All', 'INBOX', 'myTra$h']:
            assert l.canonical_name in ['all', 'inbox', 'trash']
        else:
            assert l.name in ['ma envoyes', 'icecreampop',
                              'roundwego', 'carousel', 'circusfades']
            assert l.canonical_name is None

    categories = empty_db.session.query(Category).filter(
        Category.namespace_id == account.namespace.id)

    assert categories.count() == 8
    for c in categories.all():
        if c.name in ['all', 'inbox', 'trash']:
            assert c.name == c.category
            assert c.display_name in ['All', 'INBOX', 'myTra$h']
        elif c.name in ['sent', 'junk']:
            assert c.name == c.category
            assert c.display_name in ['ma envoyes', 'icecreampop']
        else:
            assert c.name is None
            assert c.category is None
            assert c.display_name in ['roundwego', 'carousel', 'circusfades']


def test_imap_folder_label_creation(empty_db):
    from inbox.mailsync.backends.imap import ImapSyncMonitor

    account = generic_account(empty_db)
    assert account.discriminator == 'genericaccount'

    raw_folders = [
        # Imap 'canonical folders'
        RawFolder(name='INBOX', canonical_name='inbox', category='inbox'),
        # Recognized categories
        RawFolder(name='myTra$h', canonical_name=None, category='trash'),
        RawFolder(name='ma envoyes', canonical_name=None, category='sent'),
        RawFolder(name='icecreampop', canonical_name=None, category='junk'),
        # Others
        RawFolder(name='roundwego', canonical_name=None, category=None),
        RawFolder(name='carousel', canonical_name=None, category=None),
        RawFolder(name='circusfades', canonical_name=None, category=None)]

    ImapSyncMonitor(account).save_folder_names(empty_db.session,
                                               account.id, raw_folders)

    # For generic Imap, all folders are created as Folders.
    folders = empty_db.session.query(Folder).filter(
        Folder.account_id == account.id)

    assert folders.count() == 7
    for f in folders.all():
        if f.canonical_name in ['inbox']:
            assert f.name in ['INBOX']
        else:
            assert f.name in ['myTra$h', 'ma envoyes', 'icecreampop',
                              'roundwego', 'carousel', 'circusfades']
            assert f.canonical_name is None

    # For generic Imap, there are no Labels created
    labels = empty_db.session.query(Label).filter(
        Label.account_id == account.id)

    assert labels.count() == 0

    categories = empty_db.session.query(Category).filter(
        Category.namespace_id == account.namespace.id)

    assert categories.count() == 7
    for c in categories.all():
        if c.name in ['inbox']:
            assert c.name == c.category
            assert c.display_name in ['INBOX']
        elif c.name in ['trash', 'sent', 'junk']:
            assert c.name == c.category
            assert c.display_name in ['myTra$h', 'ma envoyes', 'icecreampop']
        else:
            assert c.name is None
            assert c.category is None
            assert c.display_name in ['roundwego', 'carousel', 'circusfades']
