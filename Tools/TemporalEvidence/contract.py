"""Strict, local temporal evidence contracts; no document-authenticity policy."""
import hashlib
import json
import math
import os
import stat
import uuid


def require(condition, message):
    if not condition:
        raise ValueError(message)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def number(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number')
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_float=number,
                      parse_constant=lambda value: number(value))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def identifier(value):
    require(isinstance(value, str) and str(uuid.UUID(value)).upper() == value.upper(), 'Invalid UUID')
    return value


def integer(value, minimum=0):
    require(type(value) is int and value >= minimum, 'Invalid integer')
    return value


def finite(value):
    require(type(value) in (int, float) and math.isfinite(value), 'Missing/nonfinite measurement')
    return value


def read_regular(path):
    # Open once and use the very bytes checked, not a second pathname read.
    require(not path.parent.is_symlink(), 'Symlink directory')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'Expected regular file')
        return stream.read()


def timestamp(value):
    integer(value['timescale'], 1)
    flags = integer(value['flags'])
    require(flags & 1 and not flags & 28, 'Non-numeric timestamp')
    require(type(value['value']) is int and type(value['epoch']) is int, 'Invalid timestamp')
    require(value['clock'] == 'captureSessionSynchronizationClock', 'Unsupported frame clock')
