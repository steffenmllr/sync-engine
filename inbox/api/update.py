from sqlalchemy.orm.exc import NoResultFound
from inbox.api.err import InputError
from inbox.models.action_log import schedule_action
from inbox.models import Category
# STOPSHIP(emfree): better naming/structure for this module


def update_message(message, request_data, db_session):
    accept_labels = message.namespace.account.provider == 'gmail'
    unread, starred, label_public_ids, folder_public_id = parse(
        request_data, accept_labels)
    update_message_flags(message, db_session, unread, starred)
    if label_public_ids is not None:
        update_message_labels(message, db_session, label_public_ids)
    elif folder_public_id is not None:
        update_message_labels(message, db_session, folder_public_id)


def update_thread(thread, request_data, db_session):
    accept_labels = thread.namespace.account.provider == 'gmail'
    unread, starred, label_public_ids, folder_public_id = parse(
        request_data, accept_labels)
    for message in thread.messages:
        if message.is_draft:
            continue
        update_message_flags(message, db_session, unread, starred)
        if label_public_ids is not None:
            update_message_labels(message, db_session, label_public_ids)
        elif folder_public_id is not None:
            update_message_labels(message, db_session, folder_public_id)


def parse(request_data, accept_labels):
    unread = request_data.pop('unread', None)
    if unread is not None and not isinstance(unread, bool):
        raise InputError('"unread" must be true or false')

    starred = request_data.pop('starred', None)
    if starred is not None and not isinstance(starred, bool):
        raise InputError('"starred" must be true or false')

    label_public_ids = None
    folder_public_id = None

    if accept_labels:
        label_public_ids = request_data.pop('labels', None)
        if (label_public_ids is not None and
                not isinstance(label_public_ids, list)):
            # STOPSHIP(emfree): should also check that labels is an array of
            # /strings/
            raise InputError('"labels" must be a list of strings')
        if request_data:
            raise InputError('Only the "unread", "starred" and "labels" '
                             'attributes can be changed')

    else:
        folder_public_id = request_data.pop('folder', None)
        if (folder_public_id is not None and
                not isinstance(folder_public_id, basestring)):
            raise InputError('"folder" must be a list of strings')
        if request_data:
            raise InputError('Only the "unread", "starred" and "folder" '
                             'attributes can be changed')
    return (unread, starred, label_public_ids, folder_public_id)


def update_message_flags(message, db_session, unread=None, starred=None):
    if unread is not None and unread == message.is_read:
        message.is_read = not unread
        schedule_action('mark_unread', message, message.namespace_id,
                        db_session, unread=unread)

    if starred is not None and starred != message.is_starred:
        message.is_starred = starred
        schedule_action('mark_starred', message, message.namespace_id,
                        db_session, starred=starred)


def update_message_labels(message, db_session, label_public_ids):
    categories = set()
    for id_ in label_public_ids:
        try:
            cat = db_session.query(Category).filter(
                Category.namespace_id == message.namespace_id,
                Category.public_id == id_).one()
            categories.add(cat)
        except NoResultFound:
            raise InputError(u'Label {} does not exist'.format(id_))
    added_categories = categories - set(message.categories)
    removed_categories = set(message.categories) - categories

    added_labels = []
    removed_labels = []
    special_label_map = {
        'inbox': '\\Inbox',
        'important': '\\Important',
        'all': '\\All',  # STOPSHIP(emfree): verify
        'trash': '\\Trash',
        'spam': '\\Spam'
    }
    for cat in added_categories:
        if cat.name in special_label_map:
            added_labels.append(special_label_map[cat.name])
        elif cat.name == 'drafts':
            raise InputError('The "drafts" label cannot be changed')
        elif cat.name == 'sent':
            raise InputError('The "sent" label cannot be changed')
        else:
            added_labels.append(cat.display_name)
    for cat in removed_categories:
        if cat.name in special_label_map:
            removed_labels.append(special_label_map[cat.name])
        elif cat.name == 'drafts':
            raise InputError('The "drafts" label cannot be changed')
        elif cat.name == 'sent':
            raise InputError('The "sent" label cannot be changed')
        else:
            removed_labels.append(cat.display_name)

    # Optimistically update message state.
    message.categories = categories
    if removed_labels or added_labels:
        schedule_action('change_labels', message, message.namespace_id,
                        removed_labels=removed_labels,
                        added_labels=added_labels,
                        db_session=db_session)


def update_message_folder(message, db_session, folder_public_id):
    try:
        cat = db_session.query(Category).filter(
            Category.namespace_id == message.namespace_id,
            Category.public_id == folder_public_id).one()
    except NoResultFound:
        raise InputError(u'Folder {} does not exist'.
                         format(folder_public_id))

    # STOPSHIP(emfree): what about sent/inbox duality?
    if cat not in message.categories:
        message.categories = [cat]
        schedule_action('move', message, message.namespace_id, db_session,
                        destination=cat.display_name)
