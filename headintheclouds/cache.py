import os
import errno
import sqlite3
import cPickle
import time
from functools import wraps

FILENAME = '~/.hitc/sqlite_cache.db'
MEMORY_CACHE = True

_cursor = None
_cache = {}

python_set = set

def get(key):
    if MEMORY_CACHE:
        if key in _cache:
            value, expire = _cache[key]
            if not expire or expire > time.time():
                return cPickle.loads(str(value))
            del _cache[key]

    _db().execute('''
        SELECT value, expire
        FROM cache
        WHERE key = ?
    ''', (key,))
    ret = _db().fetchone()
    if ret:
        value, expire = ret
        if not expire or expire > time.time():
            if MEMORY_CACHE:
                _cache[key] = value, expire
            return cPickle.loads(str(value))
        # avoid race conditions by deleting
        # just this expiration timestamp
        delete(key, expire)
    return None

def set(key, value, ttl=None):
    if ttl is None:
        expire = 0
    else:
        expire = time.time() + ttl

    if MEMORY_CACHE:
        _cache[key] = cPickle.dumps(value), expire

    _db().execute('''
        REPLACE INTO cache
        VALUES (?, ?, ?)
    ''', (key, cPickle.dumps(value), expire))

def delete(key, expire=None):
    if MEMORY_CACHE:
        if key in _cache:
            del _cache[key]

    if expire:
        if not isinstance(expire, (float, int)):
            raise ValueError('expire must be a number')
        _db().execute('''
            DELETE FROM cache
            WHERE key = ? AND expire = ?
        ''', (key, expire))
    else:
        _db().execute('''
            DELETE FROM cache
            WHERE key = ?
        ''', (key,))

def flush():
    global _cursor, _cache

    if MEMORY_CACHE:
        _cache = {}

    try:
        os.unlink(_filename())
    except OSError, e:
        if e.errno != errno.ENOENT:
            raise
    _cursor = None

def size():
    if MEMORY_CACHE:
        return len(_cache)

    _db().execute('''
        SELECT COUNT(*)
        FROM cache
    ''')
    return int(_db().fetchone()[0])

def cached(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        recache = kwargs.get('_recache')
        if recache:
            del kwargs['_recache']
        uncache = kwargs.get('_uncache')
        if uncache:
            del kwargs['_uncache']

        cache_key = func.__module__ + '.' + func.__name__
        if args or kwargs:
            cache_key += cPickle.dumps((args, kwargs))

        if uncache:
            delete(cache_key)

        if recache:
            ret = func(*args, **kwargs)
            set(cache_key, ret)
        else:
            ret = get(cache_key)
            if ret is None:
                ret = func(*args, **kwargs)
                set(cache_key, ret)
        return ret
    wrapper._cached = True
    return wrapper

def recache(fn, *args, **kwargs):
    if not hasattr(fn, '__call__'):
        raise Exception('%s is not a function' % str(fn))
    if not hasattr(fn, '_cached'):
        raise Exception('Function is not decorated with @cached')
    kwargs['_recache'] = True
    return fn(*args, **kwargs)

def uncache(fn, *args, **kwargs):
    if not hasattr(fn, '__call__'):
        raise Exception('%s is not a function' % str(fn))
    if not hasattr(fn, '_cached'):
        raise Exception('Function is not decorated with @cached')
    kwargs['_uncache'] = True
    fn(*args, **kwargs)

def _db():
    global _cursor
    if not _cursor:
        try:
            os.makedirs(os.path.dirname(_filename()))
        except OSError, e:
            if e.errno != errno.EEXIST:
                raise
        conn = sqlite3.connect(_filename(), isolation_level=None)
        _cursor = conn.cursor()
        _cursor.execute('''
            CREATE TABLE IF NOT EXISTS cache (
                key     TEXT    PRIMARY KEY,
                value   BLOB,
                expire  FLOAT
            )
        ''')
    return _cursor

def _filename():
    return os.path.abspath(os.path.expanduser(FILENAME))
