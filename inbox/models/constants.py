# Size constants, set in this file to avoid annoying circular import
# errors
MAX_INDEXABLE_LENGTH = 191
MAX_FOLDER_NAME_LENGTH = MAX_INDEXABLE_LENGTH
MAX_LABEL_NAME_LENGTH = MAX_INDEXABLE_LENGTH

CATEGORY_NAMES = ['inbox', 'all', 'trash', 'archive', 'drafts', 'sent', 'spam',
                  'starred', 'important']
IMAP_CATEGORY_CANONICAL_MAP = {
    'inbox': 'inbox'
}
GMAIL_CATEGORY_CANONICAL_MAP = {
    'inbox': 'inbox',
    'all': 'all',
    'trash': 'trash',
    'spam': 'spam'
}
RESERVED_NAMES = ['sending', 'replied', 'file', 'attachment']
