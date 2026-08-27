import pytest

def test_sanity():
    """A simple test to verify that pytest is correctly configured."""
    assert True

def test_imports():
    """Verify that the application modules can be imported."""
    try:
        from app.main import app
        from app.config import settings
        assert app is not None
        assert settings is not None
    except ImportError as e:
        pytest.fail(f"Import failed: {e}")
