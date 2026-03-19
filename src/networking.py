"""Shared networking helpers for HTTP sessions and OpenAI-compatible clients."""

from __future__ import annotations

from functools import lru_cache

import httpx
import requests
from openai import OpenAI
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 30.0


@lru_cache(maxsize=1)
def get_requests_session() -> requests.Session:
    """Build a shared requests session with connection pooling and retry policy."""
    session = requests.Session()
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


@lru_cache(maxsize=8)
def get_openai_compatible_client(api_key: str, base_url: str) -> OpenAI:
    """Build a cached OpenAI-compatible client with a shared httpx connection pool."""
    http_client = httpx.Client(
        base_url=base_url,
        timeout=DEFAULT_TIMEOUT,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=DEFAULT_TIMEOUT,
        http_client=http_client,
    )
