# local
from gateway.resilience.circuit_breaker import CircuitBreaker


def build_registry(config) -> dict[str, CircuitBreaker]:
    cb_registry = {}
    for route in config["routes"]:
        cb_registry[route["upstream"]] = CircuitBreaker(
            name=route["path"].rsplit("/", 1)[1]
        )

    return cb_registry
