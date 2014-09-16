import os
import binascii
from hashlib import sha256

import nacl.secret
import nacl.utils
from sqlalchemy import Column, Integer, String, Index
from sqlalchemy.ext.declarative import declared_attr

from inbox.config import config
from inbox.log import get_logger
log = get_logger()
from inbox.models.util import EncryptionScheme

STORE_MSG_ON_S3 = config.get('STORE_MESSAGES_ON_S3', None)
if STORE_MSG_ON_S3:
    from boto.s3.connection import S3Connection
    from boto.s3.key import Key
else:
    from inbox.util.file import mkdirp

RESERVED = b'\x00\x00\x00\x00'
KEY_VERSION = b'\x00\x00\x00\x00'


class Blob(object):
    """ A blob of data that can be saved to local or remote (S3) disk. """
    size = Column(Integer, default=0)
    data_sha256 = Column(String(64))

    # Unencrypted=0, WithStaticKey=1
    encryption_scheme = Column(Integer, server_default='0')

    # The lookup_key where data is stored at on s3/disk
    stored_name = Column(String(255))

    @property
    def data(self):
        # GET DATA:
        # On initial download we temporarily store data unencrypted
        # in memory
        if hasattr(self, '_data'):
            value = self._data
        # For backward-compatability with our no-encryption scheme
        elif self.encryption_scheme == EncryptionScheme.NULL:
            value = self.unencrypted_data_getter()
        # Unencrypt and return plaintext data
        else:
            value = self.encrypted_data_getter()

        # CHECK DATA:
        if value is None:
            log.error("Couldn't find data!")
            return value

        assert self.data_sha256 == sha256(value).hexdigest(), \
            "Returned data doesn't match stored hash!"

        return value

    def set_data(self, db_session, value):
        # Cache value in memory unencrypted. Otherwise message-parsing incurs
        # a s3/disk roundtrip.
        self._data = value

        assert value is not None, \
            "Blob can't have NoneType data (can be zero-length, though!)"
        assert type(value) is not unicode, 'Blob bytes must be encoded'

        self.size = len(value)
        self.data_sha256 = sha256(value).hexdigest()

        # DEDUPLICATE:
        # If we have another Blob row for the same data blob
        # (as determined by its sha256 hash), do not re-save; merely point
        # to the existing saved object.
        # NOTE: We only de-dupe with existing *encrypted* blobs.
        cls = self.__class__

        existing = db_session.query(cls).filter(
            cls.data_sha256 == self.data_sha256,
            cls.encryption_scheme ==
            EncryptionScheme.SECRETBOX_WITH_STATIC_KEY).first()
        lookup_key = existing.stored_name if existing else None

        if lookup_key is not None:
            self.encryption_scheme = EncryptionScheme.SECRETBOX_WITH_STATIC_KEY
            self.stored_name = lookup_key
            return

        # STORE:
        # Otherwise, encrypt and store in our storage backend (s3/disk)
        self.encryption_scheme = EncryptionScheme.SECRETBOX_WITH_STATIC_KEY

        # We generate a random key rather than using the data_sha256 which
        # leaks information about the data contents.
        identifier = binascii.hexlify(os.urandom(32))
        lookup_key = '{0}/{1}'.format(self.encryption_scheme, identifier)

        encrypted_value = nacl.secret.SecretBox(
            key=config.get_required('BLOCK_ENCRYPTION_KEY'),
            encoder=nacl.encoding.HexEncoder
        ).encrypt(
            plaintext=value,
            nonce=nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE),
            encoder=nacl.encoding.HexEncoder)

        stored_value = b''.join([RESERVED, KEY_VERSION, encrypted_value])

        if STORE_MSG_ON_S3:
            self._save_to_s3(stored_value, lookup_key)
        else:
            self._save_to_disk(stored_value, lookup_key)

    @data.deleter
    def data(self):
        if STORE_MSG_ON_S3:
            self._delete_from_s3()
        else:
            self._delete_from_disk()

        self.size = None
        self.data_sha256 = None
        self.encryption_scheme = None
        self.stored_name = None

    @declared_attr
    def __table_args__(cls):
        return (Index('ix_%s_datasha256' % cls.__tablename__, 'data_sha256'),)

    # Helpers
    def encrypted_data_getter(self):
        assert self.encryption_scheme == \
            EncryptionScheme.SECRETBOX_WITH_STATIC_KEY and self.stored_name

        lookup_key = self.stored_name

        if STORE_MSG_ON_S3:
            value = self._get_from_s3(lookup_key)
        else:
            modified_lookup_key = ''.join(lookup_key.split('/'))
            value = self._get_from_disk(modified_lookup_key)

        if value is None:
            return value

        ciphertext = value[len(RESERVED) + len(KEY_VERSION):]

        value = nacl.secret.SecretBox(
            key=config.get_required('BLOCK_ENCRYPTION_KEY'),
            encoder=nacl.encoding.HexEncoder
        ).decrypt(
            ciphertext,
            encoder=nacl.encoding.HexEncoder)

        return value

    def unencrypted_data_getter(self):
        assert self.encryption_scheme == \
            EncryptionScheme.NULL and self.data_sha256

        lookup_key = self.data_sha256

        if STORE_MSG_ON_S3:
            value = self._get_from_s3(lookup_key)
        else:
            value = self._get_from_disk(lookup_key)

        return value

    def _get_from_s3(self, lookup_key):
        access_key = config.get_required('AWS_ACCESS_KEY_ID')
        secret_key = config.get_required('AWS_SECRET_ACCESS_KEY')
        bucket_name = config.get_required('MESSAGE_STORE_BUCKET_NAME')

        conn = S3Connection(access_key, secret_key)
        bucket = conn.get_bucket(bucket_name, validate=False)

        data_obj = bucket.get_key(lookup_key)
        assert data_obj, 'No data for key: {0}'.format(lookup_key)

        return data_obj.get_contents_as_string()

    def _get_from_disk(self, lookup_key):
        # We store at a path derived from the lookup_key
        filename = self.filepath(lookup_key)

        try:
            with open(filename, 'rb') as f:
                return f.read()
        except Exception:
            log.error('No data for key: {0}'.format(lookup_key))
            # XXX should this instead be empty bytes?
            return None

    def _save_to_s3(self, data, lookup_key):
        assert self.encryption_scheme == \
            EncryptionScheme.SECRETBOX_WITH_STATIC_KEY and data

        access_key = config.get_required('AWS_ACCESS_KEY_ID')
        secret_key = config.get_required('AWS_SECRET_ACCESS_KEY')
        bucket_name = config.get_required('MESSAGE_STORE_BUCKET_NAME')

        conn = S3Connection(access_key, secret_key)
        bucket = conn.get_bucket(bucket_name, validate=False)

        data_obj = Key(bucket)

        data_obj.key = lookup_key
        data_obj.set_contents_from_string(data)

        self.stored_name = lookup_key

    def _save_to_disk(self, data, lookup_key):
        assert self.encryption_scheme == \
            EncryptionScheme.SECRETBOX_WITH_STATIC_KEY and data

        # We store at a path derived from the lookup_key
        modified_lookup_key = ''.join(lookup_key.split('/'))
        filepath = self.filepath(modified_lookup_key)

        # Create dir if reqd., check filename
        directory, _ = os.path.split(filepath)
        mkdirp(directory)

        with open(filepath, 'wb') as f:
            f.write(data)

        self.stored_name = lookup_key

    # TODO
    def _delete_from_s3(self):
        pass

    # TODO
    def _delete_from_disk(self):
        pass

    def filepath(self, lookup_key):
        root = config.get_required('MSG_PARTS_DIRECTORY')

        # Nest it 6 items deep so we don't have folders with too many files.
        k = lookup_key
        directory = os.path.join(root, k[0], k[1], k[2], k[3], k[4], k[5])

        return os.path.join(directory, lookup_key)
