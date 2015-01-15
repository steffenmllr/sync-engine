"""fix_cascades

Revision ID: 284227d72f51
Revises: 581e91bd7141
Create Date: 2015-01-15 14:03:36.379402

"""

# revision identifiers, used by Alembic.
revision = '284227d72f51'
down_revision = '581e91bd7141'

from alembic import op
import sqlalchemy as sa


def upgrade():
    connection = op.get_bind()
    connection.execute(
        '''
        ALTER TABLE actionlog DROP FOREIGN KEY actionlog_ibfk_1;
        ALTER TABLE actionlog ADD CONSTRAINT actionlog_ibfk_1 FOREIGN KEY (namespace_id) REFERENCES namespace(id) ON DELETE CASCADE;
        ALTER TABLE easfoldersyncstatus DROP FOREIGN KEY easfoldersyncstatus_ibfk_3;
        ALTER TABLE easfoldersyncstatus ADD CONSTRAINT easfoldersyncstatus_ibfk_3 FOREIGN KEY (folder_id) REFERENCES folder(id) ON DELETE CASCADE;
        ALTER TABLE message DROP FOREIGN KEY full_body_id_fk;
        ALTER TABLE message ADD CONSTRAINT full_body_id_fk FOREIGN KEY (full_body_id) REFERENCES block(id) ON DELETE CASCADE;
        '''
    )


def downgrade():
    connection = op.get_bind()
    connection.execute(
        '''
        ALTER TABLE actionlog DROP FOREIGN KEY actionlog_ibfk_1;
        ALTER TABLE actionlog ADD CONSTRAINT actionlog_ibfk_1 FOREIGN KEY (namespace_id) REFERENCES namespace(id);
        ALTER TABLE easfoldersyncstatus DROP FOREIGN KEY easfoldersyncstatus_ibfk_3;
        ALTER TABLE easfoldersyncstatus ADD CONSTRAINT easfoldersyncstatus_ibfk_3 FOREIGN KEY (folder_id) REFERENCES folder(id);
        ALTER TABLE message DROP FOREIGN KEY full_body_id_fk;
        ALTER TABLE message ADD CONSTRAINT full_body_id_fk FOREIGN KEY (full_body_id) REFERENCES block(id); 
        '''
    )
