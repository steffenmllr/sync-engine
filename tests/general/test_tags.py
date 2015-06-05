from tests.util.base import gmail_account

from inbox.mailsync.backends.base import save_folder_names
from inbox.models import Folder, Label, Category


def test_folders_labels_creation(empty_db):
    account = gmail_account(empty_db)

    assert account.discriminator == 'gmailaccount'

    folder_names = {'all': 'All', 'inbox': 'INBOX', 'trash': 'myTra$h',
                    'labels': ['roundwego', 'carousel', 'circusfades']}

    save_folder_names(account.id, folder_names, empty_db.session)

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

    assert labels.count() == 6
    for l in labels.all():
        if l.name in ['All', 'INBOX', 'myTra$h']:
            assert l.canonical_name in ['all', 'inbox', 'trash']
        else:
            assert l.name in folder_names['labels']

    categories = empty_db.session.query(Category).filter(
        Category.namespace_id == account.namespace.id)

    assert categories.count() == 6
    for c in categories.all():
        if c.name in ['all', 'inbox', 'trash']:
            assert c.canonical_name in ['all', 'inbox', 'trash']
            assert c._name in ['All', 'INBOX', 'myTra$h'] and \
                c.localized_name in ['All', 'INBOX', 'myTra$h']
        else:
            assert c.name in folder_names['labels']
            assert c._name in folder_names['labels'] and \
                c.localized_name in folder_names['labels']
            assert c.canonical_name is None
