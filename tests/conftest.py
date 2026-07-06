import pytest

from hedgefund.config import Config
from hedgefund.data.offline_provider import OfflineProvider


@pytest.fixture
def config(tmp_path):
    return Config(
        data_provider="offline",
        llm_mode="off",
        state_dir=tmp_path / ".hedgefund",
    )


@pytest.fixture
def provider():
    return OfflineProvider()


@pytest.fixture
def snapshot(provider):
    return provider.snapshot("NVDA")
