import json
import os
from pathlib import Path

import pytest

# Unit tests never connect. Integration tests use GA_TEST_DATABASE_URL, which must win over
# any GA_DATABASE_URL in the environment because those tests wipe the target database.
if os.environ.get("GA_TEST_DATABASE_URL"):
    os.environ["GA_DATABASE_URL"] = os.environ["GA_TEST_DATABASE_URL"]
else:
    os.environ.setdefault("GA_DATABASE_URL", "postgresql+psycopg://unused@localhost/unused")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixture_json():
    return lambda name: json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fixture_text():
    return lambda name: (FIXTURES / name).read_text(encoding="utf-8")
