"""Pluggable clock so deterministic demos are byte-reproducible.

The runtime depends on the abstract `Clock` interface; production wires a
`WallClock`, tests wire a `FixedClock` so `created_at`/`updated_at` are
predictable. Without this, two runs of the same input would produce
different on-disk artifacts and snapshot tests would be impossible.
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from typing import Iterator


class Clock(ABC):
    @abstractmethod
    def now(self) -> dt.datetime: ...


class WallClock(Clock):
    def now(self) -> dt.datetime:
        return dt.datetime.now(tz=dt.timezone.utc)


class FixedClock(Clock):
    """Returns one of a fixed sequence of timestamps, advancing on each call.

    If the sequence is exhausted, the last value is reused.
    """

    def __init__(self, timestamps: list[dt.datetime] | dt.datetime) -> None:
        if isinstance(timestamps, dt.datetime):
            timestamps = [timestamps]
        if not timestamps:
            raise ValueError("FixedClock needs at least one timestamp")
        self._values: list[dt.datetime] = list(timestamps)
        self._iter: Iterator[dt.datetime] = iter(self._values)
        self._last: dt.datetime = self._values[-1]

    def now(self) -> dt.datetime:
        try:
            ts = next(self._iter)
            self._last = ts
            return ts
        except StopIteration:
            return self._last


__all__ = ["Clock", "FixedClock", "WallClock"]
