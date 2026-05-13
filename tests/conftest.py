"""Pytest configuration for the launcher's test suite.

Defines a ``--live`` flag and the ``live`` marker for tests that hit real
Modal. Default ``pytest`` invocation skips them; pass ``--live`` to opt in.
"""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run tests marked @pytest.mark.live (live Modal sweeps).",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="needs --live to run a real Modal sweep")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
