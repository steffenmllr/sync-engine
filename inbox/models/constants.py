# Size constants, set in this file to avoid annoying circular import
# errors
MAX_INDEXABLE_LENGTH = 191
MAX_FOLDER_NAME_LENGTH = MAX_INDEXABLE_LENGTH
MAX_LABEL_NAME_LENGTH = MAX_INDEXABLE_LENGTH

CANONICAL_NAMES = ['inbox', 'archive', 'drafts', 'sent', 'spam',
                   'starred', 'trash', 'important', 'all']
RESERVED_NAMES = ['all', 'sending', 'replied', 'file', 'attachment']
