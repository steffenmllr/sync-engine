from datetime import datetime, timedelta
import elasticsearch
from inbox.models.session import session_scope


class LogSearcher(object):
    def __init__(self, es_host, es_port):
        self._client = elasticsearch.Elasticsearch([{'host': es_host,
                                                     'port': es_port}])

    def _build_query(self, start_time, end_time, terms, fields):
        timerange = {
            '@timestamp': {
                'from': start_time.isoformat(),
                'to': end_time.isoformat()
            }
        }
        filters = [{'range': timerange}]
        for k, v in terms.items():
            filters.append({'term': {k: v}})

        for k in fields:
            filters.append({'exists': {'field': k}})

        query = {
            'query': {
                'filtered': {
                    'query': {
                        'match_all': {}
                    },
                    'filter': {
                        'and': filters
                    }
                }
            }
        }

        return query

    def _indices_to_search(self, start_time, end_time):
        index_names = []
        delta = end_time - start_time
        for i in range(delta.days + 1):
            dt = start_time + timedelta(days=i)
            index_names.append('logstash-{}.{}.{}'.
                               format(dt.year, dt.month, dt.day))
        return ','.join(index_names)

    def get_account_sync_logs(self, window_size):
        end_time = datetime.utcnow()
        # TODO(emfree): this obviously breaks if window_size is > 86400 seconds
        start_time = end_time - timedelta(seconds=window_size)

        _indices_to_search = self._indices_to_search(start_time, end_time)
        q = self._build_query(start_time, end_time,
                              terms={'program': 'mailsync'},
                              fields=['account_id', 'folder'])
        num_results = self._client.count(body=q,
                                         index=_indices_to_search)['count']
        from_ = 0
        results = []
        while from_ < num_results:
            raw_results_page = self._client.search(body=q,
                                                   index=_indices_to_search,
                                                   from_=from_, size=300)
            from_ += 500
            results.extend([h['_source'] for h in
                            raw_results_page['hits']['hits']])
        return results


def _get_syncing_folders():
    from inbox.models.backends.imap import ImapFolderSyncStatus
    from inbox.models.backends.eas import EASFolderSyncStatus
    with session_scope() as db_session:
        imap_folder_syncs = db_session.query(ImapFolderSyncStatus)
        eas_folder_syncs = db_session.query(EASFolderSyncStatus)
        keys = [(foldersync.account_id, foldersync.folder.name) for foldersync
                in imap_folder_syncs]
        keys.extend([(foldersync.account_id, foldersync.folder.name) for
                     foldersync in eas_folder_syncs])
    return keys


def get_foldersync_health(searcher, window_size):
    syncing_folders = _get_syncing_folders()
    health_map = dict.fromkeys(syncing_folders, 'silent')
    logs = searcher.get_account_sync_logs(window_size)
    for log in logs:
        key = (log['account_id'], log['folder'])
        if log['level'] == 'error':
            health_map[key] = 'error'
        else:
            if health_map.get(key) != 'error':
                health_map[key] = 'healthy'
    return health_map


if __name__ == '__main__':
    searcher = LogSearcher('10.77.212.131', 9200)
    health_map = get_foldersync_health(searcher, 300)
    healthy = len([k for k, v in health_map.items() if v == 'healthy'])
    erring = len([k for k, v in health_map.items() if v == 'error'])
    silent = len([k for k, v in health_map.items() if v == 'silent'])
    healthy_fraction = round(100 * float(healthy) / len(health_map))
    erring_fraction = round(100 * float(erring) / len(health_map))
    silent_fraction = round(100 * float(silent) / len(health_map))

    print "Inbox sync is {} percent healthy, {} percent erring, " \
          "{} percent silent".format(healthy_fraction, erring_fraction, silent_fraction)
