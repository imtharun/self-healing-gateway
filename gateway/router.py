# built-in
import os
from functools import lru_cache
from pathlib import Path

# third-party
import yaml


@lru_cache
def load_config():
    config_path = Path(__file__).with_name("config.yaml")
    with open(config_path, "r") as f:
        configs = yaml.safe_load(f)

    for route in configs.get("routes", []):
        upstream_env = route.get("upstream_env")
        if upstream_env:
            route["upstream_url"] = os.getenv(upstream_env, route["upstream_url"])

    return configs


def route_matches(route_path: str, request_path: str) -> bool:
    route_path = route_path.rstrip("/")
    return request_path == route_path or request_path.startswith(f"{route_path}/")


def get_upstream(request_path: str) -> str | None:
    config = load_config()
    for route in sorted(
        config["routes"], key=lambda value: len(value["path"]), reverse=True
    ):
        if route_matches(route["path"], request_path):
            return route["upstream_url"]

    return None
