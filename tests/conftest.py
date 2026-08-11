import pytest

from isomap.testviz import build_debug_page


@pytest.fixture(scope="session", autouse=True)
def debug_page():
    """Rebuild the artifact index page after the test session."""
    yield
    build_debug_page()
