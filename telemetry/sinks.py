"""Where generated readings go.

Every destination implements the same small ``Sink`` interface, so the
generator never knows or cares where its data ends up. Adding a cloud
destination later (e.g. a Pub/Sub sink feeding BigQuery or Firestore) means
writing one new class here -- nothing in the generator changes.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from telemetry.generator import Reading


class Sink(ABC):
    @abstractmethod
    def write_manifest(self, manifest: dict) -> None:
        """Called once per run, before any readings, describing the run."""

    @abstractmethod
    def write(self, readings: Iterable[Reading]) -> None:
        """Called with each batch of readings (one tick, or one test point)."""

    def close(self) -> None:
        pass


class JsonlFileSink(Sink):
    """One JSON object per line -- easy to read, append, and load later."""

    def __init__(self, readings_path: Path, manifest_path: Path):
        readings_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path = manifest_path
        self._file = readings_path.open("w", encoding="utf-8")

    def write_manifest(self, manifest: dict) -> None:
        self.manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def write(self, readings: Iterable[Reading]) -> None:
        for r in readings:
            self._file.write(json.dumps(asdict(r)) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class InMemorySink(Sink):
    """Keeps the most recent readings in memory, e.g. for a live view."""

    def __init__(self, max_readings: int | None = None):
        self.manifest: dict | None = None
        self.readings: deque[Reading] = deque(maxlen=max_readings)

    def write_manifest(self, manifest: dict) -> None:
        self.manifest = manifest

    def write(self, readings: Iterable[Reading]) -> None:
        self.readings.extend(readings)


class MultiSink(Sink):
    """Sends the same data to several sinks at once."""

    def __init__(self, *sinks: Sink):
        self.sinks = sinks

    def write_manifest(self, manifest: dict) -> None:
        for s in self.sinks:
            s.write_manifest(manifest)

    def write(self, readings: Iterable[Reading]) -> None:
        batch = list(readings)
        for s in self.sinks:
            s.write(batch)

    def close(self) -> None:
        for s in self.sinks:
            s.close()
