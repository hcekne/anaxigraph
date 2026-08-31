from __future__ import annotations

import pytest

from anaxigraph.index_authority import IndexWriteAuthority


def test_index_write_authority_is_exclusive_and_released(tmp_path):
    index = tmp_path / "anaxi-index.db"
    first = IndexWriteAuthority(index)
    second = IndexWriteAuthority(index)

    with first.claim("service"):
        assert first.status()["claimed"] is True
        assert first.status()["owner"] == "service"
        with pytest.raises(RuntimeError, match="already owns this AnaxiIndex"):
            with second.claim("standalone-watch"):
                raise AssertionError("a second writer must not acquire the index")

    assert first.status()["claimed"] is False
    with second.claim("standalone-watch"):
        assert second.status()["owner"] == "standalone-watch"
