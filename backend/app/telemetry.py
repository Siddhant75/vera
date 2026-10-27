import threading


class Telemetry:
    """Process-wide sponsor-usage counters. Singleton `telemetry` below."""

    def __init__(self):
        self._lock = threading.Lock()
        self.tf_calls = 0
        self.tf_tokens = 0
        self.tavily_queries = 0
        self.claims_verified = 0

    def add(self, tf_calls: int = 0, tf_tokens: int = 0, tavily_queries: int = 0,
            claims_verified: int = 0) -> None:
        with self._lock:
            self.tf_calls += tf_calls
            self.tf_tokens += tf_tokens
            self.tavily_queries += tavily_queries
            self.claims_verified += claims_verified

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "tf_calls": self.tf_calls,
                "tf_tokens": self.tf_tokens,
                "tavily_queries": self.tavily_queries,
                "claims_verified": self.claims_verified,
            }

    def reset(self) -> None:
        with self._lock:
            self.tf_calls = 0
            self.tf_tokens = 0
            self.tavily_queries = 0
            self.claims_verified = 0


telemetry = Telemetry()
