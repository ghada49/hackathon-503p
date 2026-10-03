"""Person 2 integration tests use exact, isolated snapshots from commit 65c10fe."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

SNAPSHOT = Path(__file__).parent / 'fixtures' / 'person2_65c10fe'


@pytest.fixture(scope='session')
def authoritative_model():
    spec = importlib.util.spec_from_file_location('person2_65c10fe_models', SNAPSHOT / 'models.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.PaperMechanismIR


@pytest.fixture
def authoritative_candidate():
    return json.loads((SNAPSHOT / 'generic_ir.json').read_text(encoding='utf-8'))


@pytest.fixture(scope='session')
def authoritative_schema():
    return json.loads((SNAPSHOT / 'schema.json').read_text(encoding='utf-8'))
