"""Restore filename field.

Oops, shouldn't have broken that.


Revision ID: 331a3cf84d2
Revises: 66e904fb4aa
Create Date: 2013-09-10 20:41:15.929415

"""

# revision identifiers, used by Alembic.
revision = '331a3cf84d2'
down_revision = '66e904fb4aa'

from alembic import op
import sqlalchemy as sa


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.add_column('messagepart', sa.Column('filename', sa.String(length=255), nullable=True))
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('messagepart', 'filename')
    ### end Alembic commands ###
