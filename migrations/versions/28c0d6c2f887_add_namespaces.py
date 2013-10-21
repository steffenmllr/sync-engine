"""Add namespaces

Revision ID: 28c0d6c2f887
Revises: 4323056c0b78
Create Date: 2013-10-14 22:18:29.705865

"""

# revision identifiers, used by Alembic.
revision = '28c0d6c2f887'
down_revision = '4323056c0b78'

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
#   op.create_table('namespaces',
#   sa.Column('id', sa.Integer(), nullable=False),
#   sa.Column('user_id', sa.Integer(), nullable=False),
#   sa.PrimaryKeyConstraint('id')
#   )
    op.alter_column(u'foldermeta', u'user_id', new_column_name='namespace_id',
	existing_type=mysql.INTEGER(display_width=11))
    op.alter_column(u'foldermeta', 'folder_name',
               existing_type=mysql.VARCHAR(length=255),
               nullable=False)
    op.alter_column(u'foldermeta', 'msg_uid',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)
    op.alter_column(u'messagemeta', u'user_id', new_column_name='namespace_id',
	existing_type=mysql.INTEGER(display_width=11))
    op.alter_column(u'rawmessage', u'user_id', new_column_name='namespace_id',
	existing_type=mysql.INTEGER(display_width=11))
    op.alter_column(u'uidvalidity', u'user_id', new_column_name='namespace_id',
	existing_type=mysql.INTEGER(display_width=11))
    op.add_column(u'users', sa.Column('root_namespace', sa.Integer(), nullable=False))
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column(u'users', 'root_namespace')
    op.add_column(u'uidvalidity', sa.Column(u'user_id', mysql.INTEGER(display_width=11), nullable=False))
    op.drop_column(u'uidvalidity', 'namespace_id')
    op.add_column(u'rawmessage', sa.Column(u'user_id', mysql.INTEGER(display_width=11), nullable=False))
    op.drop_column(u'rawmessage', 'namespace_id')
    op.add_column(u'messagemeta', sa.Column(u'user_id', mysql.INTEGER(display_width=11), nullable=False))
    op.drop_column(u'messagemeta', 'namespace_id')
    op.alter_column(u'foldermeta', 'msg_uid',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    op.alter_column(u'foldermeta', 'folder_name',
               existing_type=mysql.VARCHAR(length=255),
               nullable=True)
    op.add_column(u'foldermeta', sa.Column(u'user_id', mysql.INTEGER(display_width=11), nullable=False))
    op.drop_column(u'foldermeta', 'namespace_id')
    op.drop_table('namespaces')
    ### end Alembic commands ###
