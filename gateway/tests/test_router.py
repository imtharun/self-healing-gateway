# local
from gateway.router import get_upstream, load_config


def test_load_config_reads_gateway_config():
    load_config.cache_clear()

    config = load_config()

    assert config["gateway"]["port"] == 8000
    assert get_upstream("/api/payments/charge") == "http://localhost:9001"
    assert get_upstream("/unknown") is None


def test_load_config_allows_upstream_env_override(monkeypatch):
    monkeypatch.setenv("PAYMENTS_UPSTREAM_URL", "http://payments:9001")
    load_config.cache_clear()

    assert get_upstream("/api/payments/charge") == "http://payments:9001"
    load_config.cache_clear()
