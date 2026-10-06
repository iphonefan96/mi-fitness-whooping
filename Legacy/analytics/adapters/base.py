from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Iterator

from analytics.models import DeviceCapability, Signal


class SourceAdapter(ABC):
    @abstractmethod
    def generation(self) -> str: ...

    @abstractmethod
    def capabilities(self) -> tuple[DeviceCapability, ...]: ...

    @abstractmethod
    def read(self, signal_kind: str, start: datetime | date, end: datetime | date) -> Iterator[Signal]: ...
