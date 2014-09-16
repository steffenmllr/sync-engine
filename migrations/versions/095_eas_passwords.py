"""EAS passwords

Revision ID: 427812c1e849
Revises: 43e5867a6ef1
Create Date: 2014-09-14 22:15:51.225342

"""

# revision identifiers, used by Alembic.
revision = '427812c1e849'
down_revision = '43e5867a6ef1'

from alembic import op
import sqlalchemy as sa


def upgrade():
    from inbox.ignition import main_engine
    engine = main_engine(pool_size=1, max_overflow=0)
    Base = sa.ext.declarative.declarative_base()
    Base.metadata.reflect(engine)
    from inbox.models.session import session_scope

    if 'easaccount' in Base.metadata.tables:
        op.add_column('easaccount', sa.Column('password_id', sa.Integer()))

        class EASAccount(Base):
            __table__ = Base.metadata.tables['easaccount']

        with session_scope(ignore_soft_deletes=False, versioned=False) as \
                db_session:
            accounts = db_session.query(EASAccount).all()
            print '# EAS accounts: ', len(accounts)

            for a in accounts:
                value = a.password

                if isinstance(value, unicode):
                    value = value.encode('utf-8')

                if b'\x00' in value:
                    print 'Invalid password for account_id: {0}, skipping'.\
                        format(a.id)
                    continue

                a.password = value

                db_session.add(a)

                assert a.password_id
                assert a.password == value

        db_session.commit()

        # NOTE: Maybe don't do this yet?
        op.drop_column('easaccount', 'password')


def downgrade():
    raise Exception('Nope.')
