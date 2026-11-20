"""Ephemeral engine memoization scoped to one integrated replay/search invocation."""

from copy import deepcopy
from vnai.contracts import canonical_digest


class EngineCache:
    def __init__(self):
        self._values = {}
        self.hits = 0
        self.misses = 0

    def run(self, engine, value, compute):
        key = (engine, canonical_digest(value))
        if key not in self._values:
            self._values[key] = deepcopy(compute())
            self.misses += 1
        else:
            self.hits += 1
        return deepcopy(self._values[key])
