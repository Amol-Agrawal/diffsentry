import time

import httpx


def fetch_with_retry(url: str) -> httpx.Response:
    while True:
        try:
            resp = httpx.get(url, timeout=5)
            resp.raise_for_status()
            return resp
        except httpx.HTTPError:
            time.sleep(1)
