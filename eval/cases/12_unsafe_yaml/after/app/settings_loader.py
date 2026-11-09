import yaml


def load_settings(path: str) -> dict:
    with open(path) as f:
        return yaml.load(f, Loader=yaml.Loader)
