"""The boundary between the platform and each twin owner's environment.

A twin and its simulation engine stay inside the owner's environment; the
platform never sees its formula or parameters. All it can do is send a request
and read the reply, as JSON:

    {"op": "describe"}                         -> current version and the owner's declared fingerprint
    {"op": "predict", "version", "inputs"}     -> {"outputs": {...}}
    {"op": "recalibrate", "version", ...}      -> the owner's public submission (no parameters)
    {"op": "advise", "version", ...}           -> the owner's recommendation

``InProcessConnection`` passes the JSON to a handler in the same process (the
simulated vendor endpoints in vendor/endpoint.py, and tests); ``HttpConnection``
sends it to an endpoint over HTTP (python -m vendor.serve). Either way only
serialised JSON crosses, never an object.

Every query the platform makes for evidence goes through ``RemoteTwin`` with an
``ExchangeLog``: each call's inputs and outputs are recorded in a batch, and the
batch's SHA-256 is sealed in the ledger entry that relies on it. The exchange
file (<run>.exchange.jsonl) is the input/output record of every such call.
"""

from __future__ import annotations

import json
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Protocol

from engine.ledger import canonical_json, sha256_hex


class BoundaryError(RuntimeError):
    pass


class Connection(Protocol):
    def request(self, message: dict) -> dict: ...


class InProcessConnection:
    """A connection to a handler that takes and returns JSON text."""

    def __init__(self, handler: Callable[[str], str]):
        self._handler = handler

    def request(self, message: dict) -> dict:
        reply = json.loads(self._handler(json.dumps(message)))
        if "error" in reply:
            raise BoundaryError(reply["error"])
        return reply


class HttpConnection:
    """A connection to an endpoint served over HTTP (python -m vendor.serve)."""

    def __init__(self, url: str, timeout: float = 10.0):
        self.url, self.timeout = url, timeout

    def request(self, message: dict) -> dict:
        req = urllib.request.Request(self.url, data=json.dumps(message).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as res:
            reply = json.loads(res.read())
        if "error" in reply:
            raise BoundaryError(reply["error"])
        return reply


class ExchangeLog:
    """Every input/output exchange the platform relies on, grouped into sealed batches."""

    def __init__(self):
        self.records: list[dict] = []
        self._open: dict | None = None
        self._count = 0

    @contextmanager
    def batch(self, purpose: str) -> Iterator[dict]:
        """Calls made inside are recorded under one batch id. On exit the yielded dict
        holds the seal to put in the ledger: {batch, purpose, calls, sha256}."""
        if self._open is not None:
            raise BoundaryError("exchange batches do not nest")
        self._count += 1
        seal = {"batch": f"x{self._count:04d}", "purpose": purpose}
        self._open, rows = seal, []
        seal["_rows"] = rows
        try:
            yield seal
        finally:
            self._open = None
            rows = seal.pop("_rows")
            seal.update(calls=len(rows), sha256=sha256_hex(rows))
            self.records.extend(rows)

    def discard(self, seal: dict) -> None:
        """Forget a batch that turned out not to be needed (nothing was sealed from it)."""
        self.records = [r for r in self.records if r["batch"] != seal["batch"]]

    def record(self, identity: str, version: str, inputs: dict, outputs: dict) -> None:
        if self._open is None:
            raise BoundaryError("an evidence query must be made inside an exchange batch")
        rows = self._open["_rows"]
        rows.append({"batch": self._open["batch"], "call": len(rows), "identity": identity, "version": version,
                     "inputs": inputs, "outputs": outputs})

    def write(self, path: Path) -> None:
        self.write_records(self.records, path)

    @staticmethod
    def write_records(records: list[dict], path: Path) -> None:
        """The exchange file: one exchange per line, in the order made."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(canonical_json(r) + "\n" for r in records), encoding="utf-8")


def batch_sha256(records: list[dict], batch: str) -> str:
    return sha256_hex([r for r in records if r["batch"] == batch])


class RemoteTwin:
    """One version of a twin, reachable only through its owner's endpoint. With an
    ``ExchangeLog`` (and an identity), every prediction is recorded as evidence."""

    def __init__(self, connection: Connection, twin_type: str, version: str | None = None,
                 log: ExchangeLog | None = None, identity: str | None = None):
        self.connection, self.twin_type = connection, twin_type
        self.version = version or connection.request({"op": "describe"})["version"]
        self.log, self.identity = log, identity

    def with_log(self, log: ExchangeLog, identity: str) -> "RemoteTwin":
        return RemoteTwin(self.connection, self.twin_type, self.version, log, identity)

    def describe(self) -> dict:
        return self.connection.request({"op": "describe", "version": self.version})

    def predict(self, inputs: dict) -> dict:
        outputs = self.connection.request({"op": "predict", "version": self.version, "inputs": inputs})["outputs"]
        if self.log is not None:
            self.log.record(self.identity, self.version, dict(inputs), outputs)
        return outputs

    def recalibrate(self, released: list[dict], envelopes: dict) -> dict:
        return self.connection.request({"op": "recalibrate", "version": self.version, "released": released,
                                        "envelopes": {k: list(v) for k, v in envelopes.items()}})

    def advise(self, **request) -> dict:
        return self.connection.request({"op": "advise", "version": self.version, **request})
