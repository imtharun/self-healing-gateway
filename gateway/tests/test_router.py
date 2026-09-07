# local
from gateway.router import get_upstream, load_config, route_matches


def test_load_config_reads_gateway_config():
    load_config.cache_clear()

    config = load_config()

    assert config["gateway"]["port"] == 8000
    assert config["routes"] == []
    assert get_upstream("/api/payments/charge") is None
    assert get_upstream("/unknown") is None


def test_route_matching_respects_path_boundaries():
    assert route_matches("/api/payments", "/api/payments") is True
    assert route_matches("/api/payments", "/api/payments/charge") is True
    assert route_matches("/api/payments", "/api/payments-v2") is False
