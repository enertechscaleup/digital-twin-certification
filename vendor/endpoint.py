"""A twin owner's endpoint: the owner's side of the platform boundary (engine/boundary.py).

The endpoint keeps the twin's formula, parameters and every version it has
published inside the owner's environment. It answers JSON requests only:
``describe``, ``predict``, ``recalibrate`` and ``advise``. A recalibration's
public submission carries the new version label, the owner's declared ranges
and method, and a fingerprint the owner declares over its own content. It never
carries the parameters.

``simulated_vendors`` builds one endpoint per twin of a project, in process.
``python -m vendor.serve`` serves the same endpoints over HTTP. They stand in
for owners' environments: no real vendor is connected in this prototype.
"""

from __future__ import annotations

import json
from typing import Callable

from engine.boundary import InProcessConnection
from engine.ledger import sha256_hex
from projects import Project, load_project
from telemetry.models import TwinModel
from vendor.advise import recommend
from vendor.recalibrate import owner_for_platform

DECLARED_METHOD = "twin-fingerprint/1"


def declared_fingerprint(model: TwinModel, channels: list[dict]) -> str:
    """The owner's own fingerprint over what it says the twin contains. The platform
    cannot check it: it never sees the formula or the parameters."""
    return sha256_hex({
        "method": DECLARED_METHOD, "formula_id": model.formula_id, "params": dict(model.params),
        "channels": sorted(({"channel_id": c["channel_id"], "direction": c["direction"], "unit": c["unit"],
                             "assured_range": dict(c["envelope"]), "tolerance_pct": c.get("tolerance_pct")}
                            for c in channels), key=lambda c: c["channel_id"]),
    })


class VendorEndpoint:
    """One owner's twin: every published version, behind a JSON-only interface."""

    def __init__(self, twin_type: str, config: dict, model: TwinModel,
                 recalibrator: Callable = owner_for_platform, advisor: Callable = recommend):
        self.twin_type, self.recalibrator, self.advisor = twin_type, recalibrator, advisor
        self.versions: dict[str, tuple[TwinModel, list[dict]]] = {model.version: (model, config["channels"])}
        self.current = model.version

    def handle(self, message: str) -> str:
        try:
            req = json.loads(message)
            reply = getattr(self, f"_op_{req['op']}")(req)
        except (KeyError, AttributeError, TypeError, ValueError) as exc:
            reply = {"error": f"{type(exc).__name__}: {exc}"}
        return json.dumps(reply)

    def _version(self, req: dict) -> tuple[TwinModel, list[dict]]:
        label = req.get("version") or self.current
        if label not in self.versions:
            raise KeyError(f"no published version {label!r}")
        return self.versions[label]

    def _op_describe(self, req: dict) -> dict:
        model, channels = self._version(req)
        return {"twin_type": self.twin_type, "version": model.version, "current_version": self.current,
                "declared_fingerprint": declared_fingerprint(model, channels), "declared_method": DECLARED_METHOD}

    def _op_predict(self, req: dict) -> dict:
        model, _ = self._version(req)
        return {"outputs": model.predict(req["inputs"])}

    def _op_recalibrate(self, req: dict) -> dict:
        if self.recalibrator is None:
            raise ValueError("this twin's owner offers no recalibration")
        current, channels = self._version(req)
        envelopes = {k: tuple(v) for k, v in req["envelopes"].items()}
        sub = self.recalibrator(self.twin_type, current, req["released"], envelopes)
        model = TwinModel(self.twin_type, sub["params"], sub["twin_version"])
        restated = [{**c, "envelope": sub["declared_output_ranges"][c["channel_id"]]}
                    if c["direction"] == "output" and c["channel_id"] in sub["declared_output_ranges"] else c
                    for c in channels]
        # Publishing under a label that already exists replaces what that label serves:
        # exactly the change behind an unchanged label the platform must catch.
        self.versions[model.version] = (model, restated)
        self.current = model.version
        return {k: v for k, v in sub.items() if k != "params"} | {
            "declared_fingerprint": declared_fingerprint(model, restated), "declared_method": DECLARED_METHOD}

    def _op_advise(self, req: dict) -> dict:
        model, _ = self._version(req)
        return self.advisor(self.twin_type, model, req["pre_inputs"], req["control_channel"],
                            tuple(req["control_range"]), req["target_output"], req["target_min"])


def simulated_endpoints(project: Project | None = None, twins: dict[str, TwinModel] | None = None,
                        recalibrator: Callable = owner_for_platform, advisor: Callable = recommend) -> dict[str, VendorEndpoint]:
    project = project or load_project()
    twins = twins or {}
    return {t: VendorEndpoint(t, project.config(t), twins.get(t) or TwinModel(t), recalibrator, advisor)
            for t in project.processing_order}


def simulated_vendors(project: Project | None = None, twins: dict[str, TwinModel] | None = None,
                      recalibrator: Callable = owner_for_platform, advisor: Callable = recommend) -> dict:
    """One in-process connection per twin of the project: simulated vendor endpoints."""
    return {t: InProcessConnection(e.handle)
            for t, e in simulated_endpoints(project, twins, recalibrator, advisor).items()}
