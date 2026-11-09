import logging

log = logging.getLogger(__name__)


def check_password(user, raw: str) -> bool:
    return user.verify_password(raw)
