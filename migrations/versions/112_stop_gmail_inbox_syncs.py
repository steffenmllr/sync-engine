"""stop gmail inbox syncs

Revision ID: c79eb28fd4c
Revises: 22d076f48b88
Create Date: 2014-10-15 02:19:38.043103

"""

# revision identifiers, used by Alembic.
revision = 'c79eb28fd4c'
down_revision = '22d076f48b88'

from alembic import op


def upgrade():
    conn = op.get_bind()
    conn.execute("""
        UPDATE imapfoldersyncstatus JOIN folder ON folder.id =
        imapfoldersyncstatus.folder_id JOIN gmailaccount
        ON imapfoldersyncstatus.account_id = gmailaccount.id
        SET imapfoldersyncstatus.state='finish'
        WHERE folder.canonical_name = 'inbox'""")


def downgrade():
    pass
