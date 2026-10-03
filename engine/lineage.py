"""Twin identity and version lineage.

A twin has one permanent, random identity (registry/identities.json), assigned at its
first registration. Identity says WHO the twin is; it is never derived from what the
twin contains. Each version of a twin is a lineage node: a content fingerprint over
everything that determines the twin's behaviour, the owner's version label, and a
pointer to the version it was derived from (none for the first). Every node is sealed
in the evidence ledger as its own ``twin_version_registered`` entry before any evidence
about it, and every later entry cites the exact (identity, version, fingerprint) it is
about.

* A product twin's fingerprint covers its declared formula identifier, its parameters,
  and every channel's direction, unit, assured range and tolerance. The code commit the
  formula identifier refers to is sealed beside the fingerprint in the same entry, not
  inside it, so an unrelated code change never produces a new version.
* A system twin's fingerprint covers each constituent's identity and fingerprint, the
  connections between them, and which constituents produce the system's outputs. A
  constituent changing version gives the system a new version and a fresh composition
  record.

Design and operational stages share a twin's identity and versions: the operational twin
is a version deployed on an asset. A recalibrated twin is registered when its owner
submits it, with the version it was derived from as parent, whether or not it then passes.

Checking a running twin against its registered fingerprint (runtime swap detection) is
not done here: see docs/twin-lineage.md.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

from engine.ledger import GENESIS_HASH, EvidenceLedger, _entry_hash, sha256_hex
from engine.registry import ProductTwin, Registry, SystemTwin

ROOT = Path(__file__).resolve().parent.parent
IDENTITIES = ROOT / "registry" / "identities.json"
PRODUCT_METHOD = "twin-fingerprint/1"
SYSTEM_METHOD = "system-fingerprint/1"
REGISTERED = "twin_version_registered"
# Payload keys lineage adds to entry types that existed before it.
CITATION_KEYS = frozenset({"twin_ref", "previous_ref", "candidate_ref", "system_ref", "constituent_refs",
                           "constituent_ref", "version_refs", "final_refs"})
REF_FIELDS = ("identity", "version", "fingerprint")
_ALPHABET = "abcdefghijkmnpqrstuvwxyz23456789"


class LineageError(ValueError):
    pass


# -- identities --------------------------------------------------------------

def new_identity(prefix: str) -> str:
    return f"{prefix}_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


def load_identities(path: Path = IDENTITIES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["twins"]


def product_identity(identities: list[dict], vendor: str, design_twin_id: str) -> str | None:
    return next((r["identity"] for r in identities if r.get("composition") == "product"
                 and r.get("vendor") == vendor and r.get("design_twin_id") == design_twin_id), None)


def system_identity(identities: list[dict], project_id: str) -> str | None:
    return next((r["identity"] for r in identities if r.get("composition") == "system"
                 and r.get("project_id") == project_id), None)


def assign_identities(registry: Registry, project_id: str, identities: list[dict],
                      today: str | None = None) -> list[dict]:
    """First registration: a new random identity for every twin of the project that has
    none yet. Returns only the new records; existing identities are never changed."""
    today = today or date.today().isoformat()
    new = []
    for p in registry.products.values():
        if product_identity(identities + new, p.vendor, p.design_twin_id) is None:
            new.append({"identity": new_identity("twn"), "composition": "product", "vendor": p.vendor,
                        "design_twin_id": p.design_twin_id, "registered": today})
    if system_identity(identities + new, project_id) is None:
        new.append({"identity": new_identity("sys"), "composition": "system", "project_id": project_id,
                    "design_system_twin_id": registry.system.design_system_twin_id, "registered": today})
    return new


def register_identities(registry: Registry, project_id: str, path: Path = IDENTITIES) -> list[dict]:
    """``assign_identities``, appended to the identity file."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    new = assign_identities(registry, project_id, doc["twins"])
    if new:
        doc["twins"].extend(new)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return new


# -- fingerprints ------------------------------------------------------------

def product_fingerprint_inputs(product: ProductTwin, model) -> dict:
    """Everything that determines a product twin's behaviour. ``model`` declares its formula."""
    return {
        "method": PRODUCT_METHOD,
        "formula_id": model.formula_id,
        "params": dict(model.params),
        "channels": [{"channel_id": c.channel_id, "direction": c.direction, "unit": c.unit,
                      "assured_range": {"min": c.env_min, "max": c.env_max}, "tolerance_pct": c.tolerance_pct}
                     for c in sorted(product.channels, key=lambda c: c.channel_id)],
    }


def system_fingerprint_inputs(constituents: list[dict], system: SystemTwin) -> dict:
    """``constituents``: each constituent's twin type with its identity and fingerprint."""
    return {
        "method": SYSTEM_METHOD,
        "constituents": sorted(({"twin_type": c["twin_type"], "identity": c["identity"], "fingerprint": c["fingerprint"]}
                                for c in constituents), key=lambda c: c["twin_type"]),
        "connections": sorted(({k: c[k] for k in ("from_twin", "from_channel", "to_twin", "to_channel")}
                               for c in system.connections), key=lambda c: json.dumps(c, sort_keys=True)),
        "output_constituents": sorted(system.output_constituents),
    }


def _envelope(inputs: dict) -> dict:
    """A product fingerprint's channels, in the shape ``ProductTwin.envelope_snapshot`` records."""
    return {c["channel_id"]: {"direction": c["direction"], "min": c["assured_range"]["min"],
                              "max": c["assured_range"]["max"], "tolerance_pct": c["tolerance_pct"], "unit": c["unit"]}
            for c in inputs["channels"]}


# -- the lineage of one run --------------------------------------------------

@dataclass(frozen=True)
class Node:
    identity: str
    version: str
    fingerprint: str
    parent: str | None
    seq: int

    def ref(self) -> dict:
        return {"identity": self.identity, "version": self.version, "fingerprint": self.fingerprint}


class Lineage:
    """The versions registered in one run's ledger, and which version of each twin is in operation."""

    def __init__(self, ledger: EvidenceLedger, registry: Registry, project_id: str,
                 identities: list[dict] | None = None, code_commit: str | None = None):
        identities = load_identities() if identities is None else identities
        self.ledger, self.registry, self.project_id, self.code_commit = ledger, registry, project_id, code_commit
        self.identity: dict[str, str] = {}
        for t, p in registry.products.items():
            self.identity[t] = product_identity(identities, p.vendor, p.design_twin_id)
        missing = [registry.products[t].design_twin_id for t, i in self.identity.items() if i is None]
        self.system_identity = system_identity(identities, project_id)
        if self.system_identity is None:
            missing.append(registry.system.design_system_twin_id)
        if missing:
            raise LineageError(f"no permanent identity registered for {', '.join(missing)}; "
                               "register the twins first (python -m engine register-twins)")
        self._type_of = {i: t for t, p in registry.products.items() for i in (p.design_twin_id, p.operational_twin_id)}
        sys = registry.system
        self._system_ids = {sys.design_system_twin_id, sys.operational_system_twin_id}
        self.nodes: list[Node] = []
        self.current: dict[str, Node] = {}  # twin type -> the version in operation
        self.system: Node | None = None

    def register_product(self, twin_type: str, product: ProductTwin, model, ts: str, registered_by: str,
                         tick: int | None = None) -> Node:
        """Seal a version of a product twin. The parent is the version in operation, if any.
        Raises LineageError if the owner reuses a version label for different content."""
        identity = self.identity[twin_type]
        inputs = product_fingerprint_inputs(product, model)
        fp = sha256_hex(inputs)
        for n in self.nodes:
            if n.identity == identity and n.version == model.version:
                if n.fingerprint == fp:
                    return n
                raise LineageError(f"version {model.version} of {product.design_twin_id} is already registered "
                                   "with different content; a changed twin needs a new version label")
        parent = self.current.get(twin_type)
        e = self.ledger.append(REGISTERED, ts, {
            "twin": {"identity": identity, "version": model.version, "fingerprint": fp},
            "parent_fingerprint": parent.fingerprint if parent else None,
            "composition": "product", "twin_type": twin_type, "vendor": product.vendor,
            "design_twin_id": product.design_twin_id, "operational_twin_id": product.operational_twin_id,
            "asset_id": product.asset_id, "registered_by": registered_by,
            **({"tick": tick} if tick is not None else {}),
            "fingerprint_inputs": inputs, "code_commit": self.code_commit,
        })
        node = Node(identity, model.version, fp, parent.fingerprint if parent else None, e["seq"])
        self.nodes.append(node)
        return node

    def adopt(self, twin_type: str, node: Node) -> None:
        """``node`` is now the version of this twin in operation."""
        self.current[twin_type] = node

    def register_system(self, ts: str, registered_by: str, tick: int | None = None) -> Node:
        """Seal the system twin's version for the constituent versions now in operation."""
        sys = self.registry.system
        constituents = [{"twin_type": t, **self.current[t].ref()} for t in sys.constituents]
        inputs = system_fingerprint_inputs(constituents, sys)
        fp = sha256_hex(inputs)
        parent = self.system
        if parent and parent.fingerprint == fp:
            return parent
        version = "1" if parent is None else str(int(parent.version) + 1)
        e = self.ledger.append(REGISTERED, ts, {
            "twin": {"identity": self.system_identity, "version": version, "fingerprint": fp},
            "parent_fingerprint": parent.fingerprint if parent else None,
            "composition": "system", "project_id": self.project_id,
            "design_system_twin_id": sys.design_system_twin_id,
            "operational_system_twin_id": sys.operational_system_twin_id,
            "registered_by": registered_by, **({"tick": tick} if tick is not None else {}),
            "constituents": constituents, "fingerprint_inputs": inputs, "code_commit": self.code_commit,
        })
        self.system = Node(self.system_identity, version, fp, parent.fingerprint if parent else None, e["seq"])
        self.nodes.append(self.system)
        return self.system

    # -- citations --

    def ref(self, twin_id: str) -> dict:
        """The version in operation of a product or system twin, by any of its twin ids."""
        if twin_id in self._system_ids:
            return self.system.ref()
        return self.current[self._type_of[twin_id]].ref()

    def final_refs(self) -> dict:
        """The version in operation of every twin registered so far, by operational twin id."""
        refs = {self.registry.products[t].operational_twin_id: n.ref() for t, n in self.current.items()}
        if self.system:
            refs[self.registry.system.operational_system_twin_id] = self.system.ref()
        return refs

    def constituent_refs(self, assurance_ids: dict[str, str], stage: str = "operational") -> list[dict]:
        """Each constituent of the system twin, by role and by exact version."""
        out = []
        for t in self.registry.system.constituents:
            p = self.registry.products[t]
            out.append({"twin_type": t, "twin_id": p.design_twin_id if stage == "design" else p.operational_twin_id,
                        "assurance_id": assurance_ids[t], **self.current[t].ref()})
        return out

    def version_refs(self, readings: list[dict]) -> list[dict]:
        """For a batch of readings: each (twin, declared version label) and the registered
        version it resolves to, with the ticks it covers. An unregistered label is recorded
        as such, never guessed."""
        spans: dict[tuple[str, str], list[int]] = {}
        for r in readings:
            span = spans.setdefault((r["twin_id"], r["twin_version"]), [r["tick"], r["tick"]])
            span[0], span[1] = min(span[0], r["tick"]), max(span[1], r["tick"])
        out = []
        for (twin_id, label), (lo, hi) in spans.items():
            identity = self.identity.get(self._type_of.get(twin_id))
            node = next((n for n in self.nodes if n.identity == identity and n.version == label), None)
            ref = node.ref() if node else {"version": label, "registered": False}
            out.append({"twin_id": twin_id, **ref, "from_tick": lo, "to_tick": hi})
        return out


# -- checking a ledger's lineage ----------------------------------------------

@dataclass(frozen=True)
class LineageCheck:
    recorded: bool  # False: evidence recorded before twin lineage existed
    valid: bool
    versions: int = 0
    citations: int = 0
    reason: str | None = None


def _refs(obj) -> Iterator[dict]:
    """Every version citation anywhere inside ``obj``."""
    if isinstance(obj, dict):
        if all(k in obj for k in REF_FIELDS):
            yield obj
        for v in obj.values():
            yield from _refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _refs(v)


def verify_lineage(core: list[dict], readings: list[dict]) -> LineageCheck:
    """Check, from the ledger alone, that every registered version's fingerprint matches its
    sealed inputs, every parent is an earlier version of the same twin, no version label is
    reused for different content, every entry cites a version registered before it (of the
    twin it is about), what was tested is what was fingerprinted, and every reading resolves
    to a registered version."""
    regs = [e for e in core if e["entry_type"] == REGISTERED]
    if not regs:
        if any(True for e in core for _ in _refs(e["payload"])):
            return LineageCheck(False, False, reason="cites twin versions but registers none")
        return LineageCheck(False, True)

    nodes: dict[str, dict] = {}  # fingerprint -> node
    labels: dict[tuple[str, str], str] = {}
    owner: dict[str, str] = {}  # twin id -> identity
    checkpoints: list[dict] = []
    citations = 0

    def fail(seq: int, why: str) -> LineageCheck:
        return LineageCheck(True, False, len(nodes), citations, f"entry {seq}: {why}")

    def known(r: dict) -> bool:
        n = nodes.get(r["fingerprint"])
        return n is not None and n["identity"] == r["identity"] and n["version"] == r["version"]

    for e in core:
        p, seq, kind = e["payload"], e["seq"], e["entry_type"]
        if kind == REGISTERED:
            twin, inputs = p["twin"], p["fingerprint_inputs"]
            method = PRODUCT_METHOD if p["composition"] == "product" else SYSTEM_METHOD
            if inputs.get("method") != method:
                return fail(seq, f"unknown fingerprint method {inputs.get('method')!r}")
            if sha256_hex(inputs) != twin["fingerprint"]:
                return fail(seq, "fingerprint does not match the inputs sealed with it")
            parent = p["parent_fingerprint"]
            if parent is None:
                if any(n["identity"] == twin["identity"] for n in nodes.values()):
                    return fail(seq, "a later version of a twin has no parent")
            elif parent not in nodes or nodes[parent]["identity"] != twin["identity"]:
                return fail(seq, "parent is not an earlier version of the same twin")
            key = (twin["identity"], twin["version"])
            if labels.get(key, twin["fingerprint"]) != twin["fingerprint"]:
                return fail(seq, f"version label {twin['version']} reused for different content")
            if p["composition"] == "system":
                cited = sorted(({k: c[k] for k in ("twin_type", "identity", "fingerprint")} for c in p["constituents"]),
                               key=lambda c: c["twin_type"])
                if cited != inputs["constituents"] or not all(known(c) for c in p["constituents"]):
                    return fail(seq, "system version's constituents are not the registered versions it cites")
            for k in ("design_twin_id", "operational_twin_id", "design_system_twin_id", "operational_system_twin_id"):
                if k in p:
                    if owner.setdefault(p[k], twin["identity"]) != twin["identity"]:
                        return fail(seq, f"{p[k]} is registered under two identities")
            nodes[twin["fingerprint"]] = {**twin, "inputs": inputs}
            labels[key] = twin["fingerprint"]
            continue

        refs = list(_refs(p))
        if not refs and kind != "run_started":
            return fail(seq, f"{kind} does not cite the twin version it is about")
        for r in refs:
            if not known(r):
                return fail(seq, "cites a twin version not registered before it")
            citations += 1
        own = p.get("twin_ref")
        if own and owner.get(p.get("twin_id"), own["identity"]) != own["identity"]:
            return fail(seq, f"cites another twin's version for {p['twin_id']}")
        if own and (kind == "verification" or (kind == "assurance_issued" and "envelope" in p)):
            inputs = nodes[own["fingerprint"]]["inputs"]
            if kind == "verification" and p["twin_params"] != inputs["params"]:
                return fail(seq, "tested parameters differ from the fingerprinted version")
            if p["envelope"] != _envelope(inputs):
                return fail(seq, "assured ranges differ from the fingerprinted version")
        if kind == "readings_checkpoint":
            for v in p["version_refs"]:
                if "identity" in v and owner.get(v["twin_id"]) != v["identity"]:
                    return fail(seq, f"cites another twin's version for {v['twin_id']}")
            checkpoints.append(p)

    for r in readings:
        cp = next((c for c in checkpoints if c["from_tick"] <= r["tick"] <= c["to_tick"]), None)
        if cp is None or not any(v["twin_id"] == r["twin_id"] and v["version"] == r["twin_version"]
                                 and v.get("fingerprint") for v in cp["version_refs"]):
            return LineageCheck(True, False, len(nodes), citations,
                                f"reading at tick {r['tick']} ({r['twin_id']} {r['twin_version']}) "
                                "does not resolve to a registered version")
    return LineageCheck(True, True, len(nodes), citations)


def registered_versions(entries: list[dict]) -> list[dict]:
    """The lineage nodes registered in ``entries``, flattened for display."""
    keep = ("composition", "twin_type", "vendor", "design_twin_id", "operational_twin_id", "asset_id", "project_id",
            "design_system_twin_id", "operational_system_twin_id", "registered_by", "constituents", "code_commit")
    return [{"seq": e["seq"], "timestamp": e["timestamp"], **e["payload"]["twin"],
             "parent_fingerprint": e["payload"]["parent_fingerprint"],
             "formula_id": e["payload"]["fingerprint_inputs"].get("formula_id"),
             **{k: e["payload"][k] for k in keep if k in e["payload"]}}
            for e in entries if e["entry_type"] == REGISTERED]


# -- the same ledger without lineage -------------------------------------------

def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in CITATION_KEYS}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def legacy_projection(entries: list[dict]) -> list[dict]:
    """The ledger with everything lineage added taken out: registration entries dropped,
    citations removed, sequence numbers and hash references re-pointed, and the chain
    rebuilt in the pre-lineage format. Lineage is purely additive exactly when this
    reproduces, hash for hash, the ledger the same run produced before lineage existed."""
    out: list[dict] = []
    seqs: dict[int, int] = {}
    hashes: dict[str, str] = {}
    for e in entries:
        if e["entry_type"] == REGISTERED:
            continue
        payload = _strip(e["payload"])
        if "evidence_seq" in payload:
            payload["evidence_seq"] = [seqs[s] for s in payload["evidence_seq"]]
        if "recommendation_seq" in payload:
            payload["recommendation_seq"] = seqs[payload["recommendation_seq"]]
        if "recommendation_entry_hash" in payload:
            payload["recommendation_entry_hash"] = hashes[payload["recommendation_entry_hash"]]
        legacy = {"ledger_format_version": 1, "seq": len(out), "entry_type": e["entry_type"],
                  "timestamp": e["timestamp"], "prev_hash": out[-1]["entry_hash"] if out else GENESIS_HASH,
                  "payload": payload}
        legacy["entry_hash"] = _entry_hash(legacy)
        seqs[e["seq"]], hashes[e["entry_hash"]] = legacy["seq"], legacy["entry_hash"]
        out.append(legacy)
    return out
