from typing import TYPE_CHECKING

import pytest

from transport_matters.session.testing import TestDb

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def test_db() -> Iterator[TestDb]:
    db = TestDb.create()
    try:
        yield db
    finally:
        db.drop()
