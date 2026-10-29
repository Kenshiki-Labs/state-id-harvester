"""Shared strict JSON decoding for local evidence contracts."""
import json
import math

def require(value,message):
    if not value: raise ValueError(message)

def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Nonfinite JSON number: ' + value)
    def finite_float(value):
        result = float(value)
        require(math.isfinite(result), 'Nonfinite JSON number: ' + value)
        return result
    return json.loads(data, object_pairs_hook=pairs, parse_constant=constant, parse_float=finite_float)
