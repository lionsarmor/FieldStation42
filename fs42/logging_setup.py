import logging
from pathlib import Path

from fs42.config import load_config


LOG_FORMAT = "%(asctime)s %(levelname)s:%(name)s:%(message)s"


def setup_logging(log_name: str, filename: str | None = None, verbose: bool = False):
    config = load_config()
    logs_dir = Path(config["logs_dir"])
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_path = logs_dir / (filename or f"{log_name}.log")
    level = logging.DEBUG if verbose else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    return log_path
