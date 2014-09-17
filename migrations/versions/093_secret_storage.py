"""Secret storage

Revision ID: 1683790906cf
Revises: 4e3e8abea884
Create Date: 2014-08-20 00:42:10.269746

"""

# revision identifiers, used by Alembic.
revision = '1683790906cf'
down_revision = '159607944f52'

from alembic import op
import sqlalchemy as sa
import nacl.secret
import nacl.utils


def upgrade():
    # SECRETS TABLE:
    # Can just drop this, was't really used before
    op.drop_column('secret', 'acl_id')

    op.alter_column('secret', 'type', type_=sa.Enum('password', 'token'),
                    existing_server_default=None,
                    existing_nullable=False)

    op.add_column('secret', sa.Column('encryption_scheme', sa.Integer(),
                  server_default='0', nullable=False))
    op.add_column('secret', sa.Column('_secret', sa.BLOB(),
                                      nullable=False))

    # GENERIC, OAUTH ACCOUNTS tables:
    # Don't need to change column types for password_id, refresh_token_id;
    # only add foreign key indices.
    op.create_foreign_key('genericaccount_ibfk_2', 'genericaccount', 'secret',
                          ['password_id'], ['id'])
    op.create_foreign_key('gmailaccount_ibfk_2', 'gmailaccount', 'secret',
                          ['refresh_token_id'], ['id'])
    op.create_foreign_key('outlookaccount_ibfk_2', 'outlookaccount', 'secret',
                          ['refresh_token_id'], ['id'])

    # Data migration here is okay because we have ~100 prod accounts only.
    from inbox.ignition import main_engine
    from inbox.models.session import session_scope
    from inbox.config import config
    from inbox.models.util import EncryptionScheme

    engine = main_engine(pool_size=1, max_overflow=0)
    Base = sa.ext.declarative.declarative_base()
    Base.metadata.reflect(engine)

    class Secret(Base):
        __table__ = Base.metadata.tables['secret']

    class GenericAccount(Base):
        __table__ = Base.metadata.tables['genericaccount']

    with session_scope(ignore_soft_deletes=False, versioned=False) as \
            db_session:
        secrets = db_session.query(Secret).filter(
            Secret.secret.isnot(None)).all()

        # Only password secrets correspond to GenericAccount;
        # Gmail, Outlook are OAuth and EAS does not use the Secrets table yet.
        password_secrets = [id_ for id_, in db_session.query(Secret.id).join(
            GenericAccount).filter(Secret.id == GenericAccount.password_id)]

        for s in secrets:
            plain = s.secret.encode('utf-8') if isinstance(s.secret, unicode) \
                else s.secret

            s._secret = nacl.secret.SecretBox(
                key=config.get_required('SECRET_ENCRYPTION_KEY'),
                encoder=nacl.encoding.HexEncoder
            ).encrypt(
                plaintext=plain,
                nonce=nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE))

            s.encryption_scheme = EncryptionScheme.SECRETBOX_WITH_STATIC_KEY

            if s.id in password_secrets:
                s.type = 'password'
            else:
                s.type = 'token'

            db_session.add(s)

        db_session.commit()

    # NOTE: Maybe don't do this yet?
    op.drop_column('secret', 'secret')


def downgrade():
    raise Exception('No.')
