import logging

log = logging.getLogger(__name__)


def check_password(user, raw: str) -> bool:
    return user.verify_password(raw)


def login(user, raw_password: str) -> bool:
    log.info("login attempt user=%s password=%s", user.email, raw_password)
    ok = check_password(user, raw_password)
    if not ok:
        log.warning("failed login for %s", user.email)
    return ok
