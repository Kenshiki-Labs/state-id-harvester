"""Canonical scene task definitions and admission of task-model metadata."""
import hashlib
import json
from pathlib import Path

CONTRACT_PATH = Path(__file__).with_name('task-classes.json')


def load_contract():
    return json.loads(CONTRACT_PATH.read_text())


def contract_hash():
    return hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()


def validate_task_model(metadata):
    """Material-model outputs cannot be presented as task predictions."""
    contract = load_contract()
    if metadata.get('task_schema') != contract['schema']:
        raise ValueError('Model is not trained for the credential scene task')
    if metadata.get('task_contract_sha256') != contract_hash():
        raise ValueError('Task definition differs from model training contract')
    keys = [c['key'] for c in contract['classes']]
    if metadata.get('class_keys') != keys:
        raise ValueError('Model output channels do not match task class order')
    for field in ('weights_sha256', 'training_manifest_sha256', 'evaluation_manifest_sha256'):
        value = metadata.get(field, '')
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError(f'Missing or invalid {field}')
    return metadata
