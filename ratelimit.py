"""Tiny in-memory limits that protect the free Gemini quota on a public demo."""

import time
from collections import defaultdict, deque


class Limiter:
    def __init__(self, per_ip=6, per_ip_window=60, per_day=200):
        self.per_ip = per_ip
        self.per_ip_window = per_ip_window
        self.per_day = per_day
        self.hits = defaultdict(deque)
        self.day = []  # timestamps in the last 24 hours

    def check(self, ip, now=None):
        """Return None if allowed (and count it), else a message to show the user."""
        now = time.time() if now is None else now
        self.day = [t for t in self.day if now - t < 86400]
        if len(self.day) >= self.per_day:
            return "The free demo has reached its daily question limit. Please try again tomorrow."
        q = self.hits[ip]
        while q and now - q[0] > self.per_ip_window:
            q.popleft()
        if len(q) >= self.per_ip:
            return f"Too many questions. Please wait a minute (limit {self.per_ip} per minute)."
        q.append(now)
        self.day.append(now)
        return None
