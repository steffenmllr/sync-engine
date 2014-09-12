import os
import binascii
from hashlib import sha256

import nacl.secret
import nacl.utils
from sqlalchemy import Column, Integer
from sqlalchemy.types import BLOB

from inbox.config import config
from inbox.log import get_logger
log = get_logger()
from inbox.models.util import EncryptionScheme
from inbox.models.session import session_scope

STORE_MSG_ON_S3 = config.get('STORE_MESSAGES_ON_S3', None)
if STORE_MSG_ON_S3:
    from boto.s3.connection import S3Connection
    from boto.s3.key import Key
else:
    from inbox.util.file import mkdirp, remove_file

RESERVED = b'\x00\x00\x00\x00'
KEY_VERSION = b'\x00\x00\x00\x00'


class Blob(object):
    """ A blob of data that can be saved to local or remote (S3) disk. """

    # We allow nullable=True for deletes
    size = Column(Integer, default=0)
    data_sha256 = Column(BLOB)

    encryption_scheme = Column(Integer, server_default='0')
    stored_name = Column(BLOB)

    @property
    def data(self):
        # On initial download we temporarily store data unencrypted
        # in memory
        if hasattr(self, '_data'):
            decrypt = 0
            value = self._data

        # This is a placeholder for 'empty bytes'. If this doesn't
        # work as intended, it will trigger the hash assertion later.
        elif self.size == 0:
            log.warning('block size is 0')

            decrypt = 0
            value = ''

        else:
            # For backward-compatability with our no-encryption scheme
            decrypt = self.encryption_scheme
            key = self.stored_name if decrypt else self.data_sha256

            if STORE_MSG_ON_S3:
                value = self._get_from_s3(key)
            else:
                value = self._get_from_disk(key)

        if value is None:
            log.error("Couldn't find data!")
            return value

        # Decrypt if reqd. (we only support one encryption scheme currently)
        if decrypt:
            ciphertext = value[len(RESERVED) + len(KEY_VERSION):]

            value = nacl.secret.SecretBox(
                key=config.get_required('BLOCK_ENCRYPTION_KEY'),
                encoder=nacl.encoding.HexEncoder
            ).decrypt(
                ciphertext,
                encoder=nacl.encoding.HexEncoder)

        assert self.data_sha256 == sha256(value).hexdigest(), \
            "Returned data doesn't match stored hash!"

        return value

    @data.setter
    def data(self, value):
        # Cache value in memory unencrypted. Otherwise message-parsing incurs
        # a disk or S3 roundtrip.
        self._data = value

        assert value is not None, \
            "Blob can't have NoneType data (can be zero-length, though!)"
        assert type(value) is not unicode, 'Blob bytes must be encoded'

        self.size = len(value)
        self.data_sha256 = sha256(value).hexdigest()

        if self.size <= 0:
            log.warning('Not saving 0-length {1} {0}'.format(
                self.id, self.__class__.__name__))
            return

        # Deduplicate: if we have another Blob row for the same data blob
        # (as determined by its sha256 hash), do not re-save; merely point
        # to the existing saved object.
        # NOTE: We only de-dupe with existing *encrypted* blobs.
        with session_scope() as db_session:
            cls = self.__class__

            existing = db_session.query(cls).filter(
                cls.__dict__['data_sha256'] == self.data_sha256,
                cls.__dict__['encryption_scheme'] ==
                EncryptionScheme.SECRETBOX_WITH_STATIC_KEY).first()
            key = existing.stored_name if existing else None

        if key is not None:
            self.encryption_scheme = EncryptionScheme.SECRETBOX_WITH_STATIC_KEY
            self.stored_name = key
            return

        self.encryption_scheme = EncryptionScheme.SECRETBOX_WITH_STATIC_KEY

        encrypted_value = nacl.secret.SecretBox(
            key=config.get_required('BLOCK_ENCRYPTION_KEY'),
            encoder=nacl.encoding.HexEncoder
        ).encrypt(
            plaintext=value,
            nonce=nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE),
            encoder=nacl.encoding.HexEncoder)

        stored_value = b''.join([RESERVED, KEY_VERSION, encrypted_value])

        if STORE_MSG_ON_S3:
            self._save_to_s3(stored_value)
        else:
            self._save_to_disk(stored_value)

    def _save_to_s3(self, data):
        assert len(data) > 0, 'Need data to save!'

        access_key = config.get_required('AWS_ACCESS_KEY_ID')
        secret_key = config.get_required('AWS_SECRET_ACCESS_KEY')
        bucket_name = config.get_required('MESSAGE_STORE_BUCKET_NAME')

        conn = S3Connection(access_key, secret_key)
        bucket = conn.get_bucket(bucket_name, validate=False)

        # We generate a random key for s3 storage, rather than using the
        # data_sha256 which leaks information about the data contents.
        identifier = binascii.hexlify(os.urandom(32))
        key = '{0}/{1}'.format(self.encryption_scheme, identifier)

        data_obj = Key(bucket)

        data_obj.key = key
        data_obj.set_contents_from_string(data)

        self.stored_name = key

    def _get_from_s3(self, key):
        assert key, "Can't get data with no key!"

        access_key = config.get_required('AWS_ACCESS_KEY_ID')
        secret_key = config.get_required('AWS_SECRET_ACCESS_KEY')
        bucket_name = config.get_required('MESSAGE_STORE_BUCKET_NAME')

        conn = S3Connection(access_key, secret_key)
        bucket = conn.get_bucket(bucket_name, validate=False)

        data_obj = bucket.get_key(key)
        assert data_obj, 'No data returned!'

        return data_obj.get_contents_as_string()

    def _save_to_disk(self, data):
        mkdirp(self._data_file_directory)

        # We can simply use the data_sha256 as the key == file pathname
        # because local storage isn't designed to be secure anyway
        # i.e. we only use it in dev when the db is local too.
        key = self._data_file_path
        with open(key, 'wb') as f:
            f.write(data)

        self.stored_name = key

    def _get_from_disk(self, key):
        assert key, "Can't get data with no key!"

        try:
            with open(key, 'rb') as f:
                return f.read()
        except Exception:
            log.error('No data for key: {0}'.format(key))
            # XXX should this instead be empty bytes?
            return None

    @data.deleter
    def data(self):
        if self.size == 0:
            return

        if STORE_MSG_ON_S3:
            self._delete_from_s3()
        else:
            self._delete_from_disk()

        self.size = None
        self.data_sha256 = None
        self.encryption_scheme = None
        self.stored_name = None

    # TODO
    def _delete_from_s3(self):
        pass

    def _delete_from_disk(self):
        remove_file(self._data_file_path)

    # Helpers
    @property
    def _data_file_directory(self):
        assert self.data_sha256

        # Nest it 6 items deep so we don't have folders with too many files.
        h = self.data_sha256
        root = config.get_required('MSG_PARTS_DIRECTORY')
        return os.path.join(root,
                            h[0], h[1], h[2], h[3], h[4], h[5])

    @property
    def _data_file_path(self):
        return os.path.join(self._data_file_directory, self.data_sha256)
