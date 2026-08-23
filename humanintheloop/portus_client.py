"""Retrying HTTP client and raw JSON cache helpers for Portus."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests


def build_session():
    session = requests.Session()
    return session


def cache_payload(cache_dir, cache_key, payload):
    if cache_dir is None:
        return None

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    path = cache_path / f"{cache_key}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def stable_cache_key(url, params=None, suffix=None):
    digest = hashlib.sha1()
    digest.update(url.encode("utf-8"))
    if params:
        digest.update(json.dumps(params, sort_keys=True, default=str).encode("utf-8"))
    if suffix:
        digest.update(str(suffix).encode("utf-8"))
    return digest.hexdigest()


def fetch_json(
    url,
    *,
    params=None,
    timeout=60,
    max_retries=3,
    backoff_seconds=2,
    cache_dir=None,
    cache_key=None,
    sleep=time.sleep,
    session=None,
):
    session = session or build_session()
    last_error = None
    attempts = max(1, max_retries)
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            cache_path = None
            if cache_dir:
                key = cache_key or stable_cache_key(url, params=params)
                cache_path = cache_payload(cache_dir, key, payload)
            return payload, cache_path
        except requests.exceptions.RequestException as error:
            last_error = error
            if attempt >= attempts:
                raise
            sleep(backoff_seconds * (2 ** (attempt - 1)))
    raise last_error
