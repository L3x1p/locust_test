import httpx
import pytest

from config import settings


@pytest.fixture
def client():
    """
    Клиент ходит по реальному HTTP к запущенному серверу.
    URL задаётся в config (api_base_url) или .env (api_base_url).
    По умолчанию: http://localhost:8000 (uvicorn без --port).
    """
    base_url = settings.api_base_url.rstrip("/")
    return httpx.Client(base_url=base_url, timeout=60.0)
