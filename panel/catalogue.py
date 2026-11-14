"""Shared, short-lived output scans for the compact status protocol."""
import hashlib
import json
import threading
import time


class CatalogueCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._value = None
        self._expires = 0

    def invalidate(self):
        with self._lock:
            self._expires = 0

    def get(self, build, *, active=False):
        with self._lock:
            now = time.monotonic()
            if self._value is None or now >= self._expires:
                data, films = build()
                revision = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
                self._value = data, films, revision
                self._expires = now + (2 if active else 10)
            return self._value
