from werkzeug.contrib.cache import RedisCache
from sqlalchemy import event


class NylasORMCache(RedisCache):
    '''
    Wrapper around werkzeug's RedisCache.
    '''
    CACHE_CACHE = {}

    @classmethod
    def cache_for_model(cls, model_cls):
        key = model_cls.API_OBJECT_NAME
        if key not in cls.CACHE_CACHE:
            cls.CACHE_CACHE[key] = NylasORMCache(model_cls)
        return cls.CACHE_CACHE[key]

    def __init__(self, model_cls, *args, **kwargs):
        kwargs['key_prefix'] = model_cls.__tablename__

        @event.listens_for(model_cls, 'after_update')
        def invalidate_cache(mapper, connection, target):
            self.delete(target.public_id)

        super(NylasORMCache, self).__init__(*args, **kwargs)
