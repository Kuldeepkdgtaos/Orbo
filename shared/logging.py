import logging
import sys
from pythonjsonlogger import jsonlogger
from .config import settings


def setup_logging() -> logging.Logger:
    root = logging.getLogger()
    if root.handlers:
        return root
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    return root
