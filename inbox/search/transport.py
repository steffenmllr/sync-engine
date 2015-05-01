from elasticsearch.transport import Transport
from elasticsearch.connection import Urllib3HttpConnection
import statsd

from inbox.config import config

STATSD_HOST = config.get("STATSD_HOST", "localhost")
STATSD_PORT = config.get("STATSD_PORT", 8125)
STATSD_PREFIX = config.get("STATSD_PREFIX", None)

statsd_client = statsd.StatsClient(STATSD_HOST, STATSD_PORT, STATSD_PREFIX)


class ElasticsearchStatsdConnection(Urllib3HttpConnection):
    def log_request_success(self, method, full_url, path, body, status_code,
                            response, duration):
        super(ElasticsearchStatsdConnection, self).log_request_success(
            method, full_url, path, body, status_code, response, duration)

        metric_name= "elasticsearch.request_success.%s" % status_code
        statsd_client.incr(metric_name)
        statsd_client.timing(metric_name, duration)

    def log_request_fail(self, method, full_url, body, duration, status_code=None, exception=None):
        super(ElasticsearchStatsdConnection, self).log_request_fail(
            method, full_url, body, duration, status_code=None, exception=None)

        if status_code:
            metric_name = "elasticsearch.request_file.%s" % status_code
        elif exception:
            metric_name = "elasticsearch.exceptions.%s" % exception.__name__
        else:
            return #do nothing

        statsd_client.incr(metric_name)
        statsd_client.timing(metric_name, duration)

class StatsdLoggedTransport(Transport):
    def __init__(self, *args, **kwargs):
        kwargs['connection_class'] = ElasticsearchStatsdConnection
        return super(StatsdLoggedTransport, self).__init__(*args, **kwargs)
