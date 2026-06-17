# built-in
from pathlib import Path
from functools import lru_cache

# third-party
import yaml


@lru_cache
def load_config():
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r") as f:
        configs = yaml.safe_load(f)

    return configs


def get_upstream(request_path: str) -> str | None:
    config = load_config()
    for route in config["routes"]:
        if request_path.startswith(route["path"]):
            return route["upstream"]

    return None
