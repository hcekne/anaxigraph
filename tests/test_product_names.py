from __future__ import annotations

from importlib.util import find_spec

import anaxigraph
from anaxigraph.storage import AnaxiIndex


def test_public_package_and_index_use_anaxigraph_names():
    assert anaxigraph.__version__
    assert AnaxiIndex.__name__ == "AnaxiIndex"
    assert find_spec("code" + "intel") is None
