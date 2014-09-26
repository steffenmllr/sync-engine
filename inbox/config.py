import os
import json
import yaml
from urllib import quote_plus as urlquote


__all__ = ['config', 'db_uri', 'master_db_uri', 'shard_uri',
           'default_shard_uri']


class ConfigError(Exception):
    def __init__(self, error=None, help=None):
        self.error = error or ''
        self.help = help or \
            'Run `sudo cp etc/config-dev.json /etc/inboxapp/config.json` and '\
            'retry.'

    def __str__(self):
        return '{0} {1}'.format(self.error, self.help)


class Configuration(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)

    def get_required(self, key):
        if key not in self:
            raise ConfigError('Missing config value for {0}.'.format(key))

        return self[key]


if 'INBOX_ENV' in os.environ:
    assert os.environ['INBOX_ENV'] in ('dev', 'test', 'prod'), \
        "INBOX_ENV must be either 'dev', 'test', or 'prod'"
    env = os.environ['INBOX_ENV']
else:
    env = 'prod'


if env == 'prod':
    config_path = '/etc/inboxapp/config.json'
    sharding_path = '/etc/inboxapp/sharding.json'
    secrets_path = '/etc/inboxapp/secrets.yml'
else:
    root = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..')

    config_path = os.path.join(root, 'etc', 'config-{0}.json'.format(env))
    sharding_path = os.path.join(root, 'etc', 'sharding-{0}.json'.format(env))
    secrets_path = os.path.join(root, 'etc', 'secrets-{0}.yml'.format(env))


try:
    with open(config_path) as f:
        config = Configuration(json.load(f))

    with open(secrets_path) as f:
        config.update(yaml.safe_load(f))

    with open(sharding_path) as f:
        config.update(json.load(f))
except IOError:
    raise Exception('Missing config file.')


def db_uri(username, password, host, port, database):
    uri_template = 'mysql+pymysql://{username}:{password}@{host}' +\
                   ':{port}/{database}?charset=utf8mb4'

    return uri_template.format(
        username=username,
        # http://stackoverflow.com/a/15728440 (also applicable to '+' sign)
        password=urlquote(password),
        host=host,
        port=port,
        database=database)


def master_db_uri():
    username = config.get_required('MASTER_USER')
    password = config.get_required('MASTER_PASSWORD')
    host = config.get_required('MASTER_HOSTNAME')
    port = config.get_required('MASTER_PORT')
    database = config.get_required('MASTER_DATABASE')
    return db_uri(username, password, host, port, database)


def shard_uri(shard_key):
    shard_data = config.get_required('SHARD_MAP')[shard_key]
    username = shard_data['USERNAME']
    password = shard_data['PASSWORD']
    host = shard_data['HOSTNAME']
    port = shard_data['PORT']
    database = shard_data['DATABASE']
    return db_uri(username, password, host, port, database)


def default_shard_uri():
    default_shard_key = config.get_required('DEFAULT_SHARD_KEY')
    return shard_uri(default_shard_key)
