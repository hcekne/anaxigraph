from __future__ import annotations

from codeintel.storage import AnaxiIndex, Database


def test_anaxi_index_is_the_primary_persistence_type():
    assert Database is AnaxiIndex
