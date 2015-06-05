from tests.util.base import gmail_account

from inbox.crispin import RawFolder
from inbox.mailsync.backends.base import save_folder_names
from inbox.models import Folder, Label, Category


def test_folder_label_creation(empty_db):
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

    save_folder_names(empty_db.session, account.id, raw_folders)

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
            assert c._name in ['all', 'inbox', 'trash']
            assert c.localized_name in ['All', 'INBOX', 'myTra$h']
        elif c.name in ['sent', 'junk']:
            assert c._name in ['sent', 'junk']
            assert c.localized_name in ['ma envoyes', 'icecreampop']
        else:
            assert c.name in ['roundwego', 'carousel', 'circusfades']
            assert c._name is None
            assert c.localized_name in ['roundwego', 'carousel', 'circusfades']
