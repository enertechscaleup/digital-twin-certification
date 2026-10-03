"""Twin identity and version lineage.

A twin has one permanent, random identity (registry/identities.json), assigned at its
first registration. Identity says WHO the twin is; it is never derived from what the
twin contains. Each version of a twin is a lineage node: the owner's version label, a
fingerprint, and a pointer to the version it was derived from (none for the first).
Every node is sealed in the evidence ledger as its own ``twin_version_registered``
entry before any evidence about it, and every later entry cites the exact
(identity, version, fingerprint) it is about.

A product twin runs inside its owner's environment (engine/boundary.py), so each
version carries two fingerprints that are NOT equally authoritative:

* **Measured** (the evidence): the platform seals a probe set of inputs across the
  twin's assured input ranges, queries the version with it, and fingerprints the
  declared interface (channels, assured ranges, tolerances) together with the
  responses. The probe exchange is kept in the exchange file, so anyone can recompute
  it. This is the fingerprint every citation uses.
* **Declared** (a claim): the owner's own fingerprint over the formula and parameters it
  says the twin contains. The platform records it but cannot check it.

A system twin's fingerprint covers each constituent's identity and measured
fingerprint, the connections, and which constituents produce the system's outputs; any
constituent changing version gives the system a new version.

Design and operational stages share a twin's identity and versions: the operational twin
is a version deployed on an asset. A recalibrated twin is registered when its owner
submits it, with the version it was derived from as parent, whether or not it then passes.

Checking a running twin against its registered fingerprint (runtime swap detection) is
not done here: see docs/twin-lineage.md. The probe mechanism is its groundwork.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import random
import secrets
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator

from engine.boundary import ExchangeLog, RemoteTwin, batch_sha256
from engine.ledger import EvidenceLedger, canonical_json, sha256_hex
from engine.registry import ProductTwin, Registry, SystemTwin

ROOT = Path(__file__).resolve().parent.parent
IDENTITIES = ROOT / "registry" / "identities.json"
PROBE_METHOD = "probe-set/1"
MEASURED_METHOD = "probe-response/1"
SYSTEM_METHOD = "system-fingerprint/1"
REGISTERED = "twin_version_registered"
PROBES_SEALED = "probe_set_sealed"
REF_FIELDS = ("identity", "version", "fingerprint")
PROBE_LEVELS = 5  # the same grid verification uses, so what is tested can be matched to what is fingerprinted
PROBE_RANDOM = 16
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

def interface(product: ProductTwin) -> list[dict]:
    """The twin's declared interface: what it takes and gives, and what is assured."""
    return [{"channel_id": c.channel_id, "direction": c.direction, "unit": c.unit,
             "assured_range": {"min": c.env_min, "max": c.env_max}, "tolerance_pct": c.tolerance_pct}
            for c in sorted(product.channels, key=lambda c: c.channel_id)]


def probe_set(product: ProductTwin, identity: str) -> list[dict]:
    """Inputs the platform queries every version of a twin with: the verification grid
    across each input's assured range, plus seeded points inside it. The same for every
    version of the twin, so their responses are comparable."""
    axes = [[c.env_min + i * (c.env_max - c.env_min) / (PROBE_LEVELS - 1) for i in range(PROBE_LEVELS)]
            for c in product.inputs]
    ids = [c.channel_id for c in product.inputs]
    grid = [dict(zip(ids, combo)) for combo in itertools.product(*axes)]
    rng = random.Random(hashlib.sha256(f"{identity}|{PROBE_METHOD}".encode()).hexdigest())
    extra = [{c.channel_id: round(rng.uniform(c.env_min, c.env_max), 4) for c in product.inputs}
             for _ in range(PROBE_RANDOM)]
    return grid + extra


def measured_inputs(product: ProductTwin, probes: list[dict], responses: list[dict]) -> dict:
    return {"method": MEASURED_METHOD, "interface": interface(product),
            "probe_set_sha256": sha256_hex(probes), "responses_sha256": sha256_hex(responses)}


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


def _envelope(channels: list[dict]) -> dict:
    """An interface, in the shape ``ProductTwin.envelope_snapshot`` records."""
    return {c["channel_id"]: {"direction": c["direction"], "min": c["assured_range"]["min"],
                              "max": c["assured_range"]["max"], "tolerance_pct": c["tolerance_pct"], "unit": c["unit"]}
            for c in channels}


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

    def __init__(self, ledger: EvidenceLedger, registry: Registry, project_id: str, exchange: ExchangeLog,
                 identities: list[dict] | None = None, code_commit: str | None = None):
        identities = load_identities() if identities is None else identities
        self.ledger, self.registry, self.project_id, self.exchange = ledger, registry, project_id, exchange
        self.code_commit = code_commit
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
        self._probes: dict[str, list[dict]] = {}
        self.nodes: list[Node] = []
        self.current: dict[str, Node] = {}  # twin type -> the version in operation
        self.system: Node | None = None

    def evidence_twin(self, twin_type: str, remote: RemoteTwin) -> RemoteTwin:
        """``remote``, with every query recorded in the exchange log under its identity."""
        return remote.with_log(self.exchange, self.identity[twin_type])

    def _probe_set(self, twin_type: str, product: ProductTwin, ts: str) -> list[dict]:
        """The twin's probe set, sealed in the ledger before it is first used."""
        if twin_type not in self._probes:
            probes = probe_set(product, self.identity[twin_type])
            self.ledger.append(PROBES_SEALED, ts, {
                "identity": self.identity[twin_type], "twin_type": twin_type, "method": PROBE_METHOD,
                "probes": len(probes), "probe_set_sha256": sha256_hex(probes),
                "note": "sealed before any version of this twin is queried with it",
            })
            self._probes[twin_type] = probes
        return self._probes[twin_type]

    def register_product(self, twin_type: str, product: ProductTwin, remote: RemoteTwin, ts: str,
                         registered_by: str, tick: int | None = None) -> Node:
        """Measure and seal a version of a product twin. The parent is the version in operation,
        if any. Raises LineageError if the owner reuses a version label for different behaviour."""
        identity = self.identity[twin_type]
        probes = self._probe_set(twin_type, product, ts)
        twin = self.evidence_twin(twin_type, remote)
        with self.exchange.batch("probe") as seal:
            responses = [twin.predict(p) for p in probes]
        inputs = measured_inputs(product, probes, responses)
        fp = sha256_hex(inputs)
        for n in self.nodes:
            if n.identity == identity and n.version == remote.version:
                self.exchange.discard(seal)
                if n.fingerprint == fp:
                    return n
                raise LineageError(f"version {remote.version} of {product.design_twin_id} is already registered "
                                   "and now behaves differently; a changed twin needs a new version label")
        declared = remote.describe()
        parent = self.current.get(twin_type)
        e = self.ledger.append(REGISTERED, ts, {
            "twin": {"identity": identity, "version": remote.version, "fingerprint": fp},
            "parent_fingerprint": parent.fingerprint if parent else None,
            "composition": "product", "twin_type": twin_type, "vendor": product.vendor,
            "design_twin_id": product.design_twin_id, "operational_twin_id": product.operational_twin_id,
            "asset_id": product.asset_id, "registered_by": registered_by,
            **({"tick": tick} if tick is not None else {}),
            "measured": {"authority": "evidence: measured by the platform from sealed probe inputs",
                         "fingerprint": fp, "inputs": inputs, "exchange": seal},
            "declared": {"authority": "claim: declared by the twin owner; the platform cannot check it",
                         "fingerprint": declared["declared_fingerprint"], "method": declared["declared_method"]},
            "code_commit": self.code_commit,
        })
        node = Node(identity, remote.version, fp, parent.fingerprint if parent else None, e["seq"])
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
            "constituents": constituents,
            "measured": {"authority": "evidence: computed by the platform from the constituents' measured fingerprints",
                         "fingerprint": fp, "inputs": inputs},
            "code_commit": self.code_commit,
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
    exchanges: int = 0
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


def _seals(obj) -> Iterator[dict]:
    """Every exchange batch seal anywhere inside ``obj``."""
    if isinstance(obj, dict):
        if "batch" in obj and "sha256" in obj and "calls" in obj:
            yield obj
        for v in obj.values():
            yield from _seals(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _seals(v)


def verify_lineage(core: list[dict], readings: list[dict], exchange: list[dict] | None = None) -> LineageCheck:
    """Check, from the ledger and the exchange file alone, that:

    * every exchange batch matches its seal, and every exchange is sealed;
    * every measured fingerprint matches its sealed inputs, and those inputs match the
      sealed probe set and the recorded responses;
    * every parent is an earlier version of the same twin, and no version label is
      reused for a different fingerprint;
    * every entry cites a version registered before it, of the twin it is about;
    * what was tested is what was fingerprinted: same assured ranges, and every
      verification answer equals the probe answer to the same inputs;
    * every reading resolves to a registered version.

    The owner-declared fingerprints are claims and are not checked."""
    regs = [e for e in core if e["entry_type"] == REGISTERED]
    if not regs:
        if any(True for e in core for _ in _refs(e["payload"])):
            return LineageCheck(False, False, reason="cites twin versions but registers none")
        return LineageCheck(False, True)
    exchange = exchange or []

    nodes: dict[str, dict] = {}  # fingerprint -> node
    labels: dict[tuple[str, str], str] = {}
    owner: dict[str, str] = {}  # twin id -> identity
    probe_sets: dict[str, str] = {}  # identity -> sealed probe set hash
    answers: dict[tuple[str, str, str], object] = {}  # (identity, version, inputs) -> probe outputs
    batches: dict[str, list[dict]] = {}
    for r in exchange:
        batches.setdefault(r["batch"], []).append(r)
    sealed: set[str] = set()
    checkpoints: list[dict] = []
    citations = 0

    def fail(seq: int, why: str) -> LineageCheck:
        return LineageCheck(True, False, len(nodes), citations, len(exchange), f"entry {seq}: {why}")

    def known(r: dict) -> bool:
        n = nodes.get(r["fingerprint"])
        return n is not None and n["identity"] == r["identity"] and n["version"] == r["version"]

    for e in core:
        p, seq, kind = e["payload"], e["seq"], e["entry_type"]
        for s in _seals(p):
            rows = batches.get(s["batch"], [])
            if s["batch"] in sealed or len(rows) != s["calls"] or sha256_hex(rows) != s["sha256"]:
                return fail(seq, f"exchange batch {s['batch']} does not match its seal")
            sealed.add(s["batch"])
        if kind == PROBES_SEALED:
            probe_sets[p["identity"]] = p["probe_set_sha256"]
            continue
        if kind == REGISTERED:
            twin, m = p["twin"], p["measured"]
            if sha256_hex(m["inputs"]) != twin["fingerprint"] or m["fingerprint"] != twin["fingerprint"]:
                return fail(seq, "fingerprint does not match the inputs sealed with it")
            if p["composition"] == "product":
                rows = batches.get(m["exchange"]["batch"], [])
                probes = [r["inputs"] for r in rows]
                if m["inputs"].get("method") != MEASURED_METHOD:
                    return fail(seq, f"unknown fingerprint method {m['inputs'].get('method')!r}")
                if probe_sets.get(twin["identity"]) != m["inputs"]["probe_set_sha256"] or sha256_hex(probes) != m["inputs"]["probe_set_sha256"]:
                    return fail(seq, "probe inputs are not the probe set sealed for this twin")
                if sha256_hex([r["outputs"] for r in rows]) != m["inputs"]["responses_sha256"]:
                    return fail(seq, "measured fingerprint does not match the recorded probe responses")
                if any(r["identity"] != twin["identity"] or r["version"] != twin["version"] for r in rows):
                    return fail(seq, "probe exchange was with another twin or version")
                for r in rows:
                    answers[(twin["identity"], twin["version"], canonical_json(r["inputs"]))] = r["outputs"]
            else:
                if m["inputs"].get("method") != SYSTEM_METHOD:
                    return fail(seq, f"unknown fingerprint method {m['inputs'].get('method')!r}")
                cited = sorted(({k: c[k] for k in ("twin_type", "identity", "fingerprint")} for c in p["constituents"]),
                               key=lambda c: c["twin_type"])
                if cited != m["inputs"]["constituents"] or not all(known(c) for c in p["constituents"]):
                    return fail(seq, "system version's constituents are not the registered versions it cites")
            parent = p["parent_fingerprint"]
            if parent is None:
                if any(n["identity"] == twin["identity"] for n in nodes.values()):
                    return fail(seq, "a later version of a twin has no parent")
            elif parent not in nodes or nodes[parent]["identity"] != twin["identity"]:
                return fail(seq, "parent is not an earlier version of the same twin")
            key = (twin["identity"], twin["version"])
            if labels.get(key, twin["fingerprint"]) != twin["fingerprint"]:
                return fail(seq, f"version label {twin['version']} reused for a different fingerprint")
            for k in ("design_twin_id", "operational_twin_id", "design_system_twin_id", "operational_system_twin_id"):
                if k in p and owner.setdefault(p[k], twin["identity"]) != twin["identity"]:
                    return fail(seq, f"{p[k]} is registered under two identities")
            nodes[twin["fingerprint"]] = {**twin, "inputs": m["inputs"]}
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
        if own and "envelope" in p and kind in ("verification", "assurance_issued"):
            if p["envelope"] != _envelope(nodes[own["fingerprint"]]["inputs"]["interface"]):
                return fail(seq, "assured ranges differ from the fingerprinted version")
        if own and kind == "verification":
            for r in batches.get(p["exchange"]["batch"], []):
                if (r["identity"], r["version"]) != (own["identity"], own["version"]) or \
                        canonical_json(answers.get((own["identity"], own["version"], canonical_json(r["inputs"])))) != canonical_json(r["outputs"]):
                    return fail(seq, "the twin tested answered differently from the twin fingerprinted")
        if kind == "readings_checkpoint":
            for v in p["version_refs"]:
                if "identity" in v and owner.get(v["twin_id"]) != v["identity"]:
                    return fail(seq, f"cites another twin's version for {v['twin_id']}")
            checkpoints.append(p)

    unsealed = set(batches) - sealed
    if unsealed:
        return LineageCheck(True, False, len(nodes), citations, len(exchange),
                            f"exchange batch {sorted(unsealed)[0]} is not sealed in the ledger")
    for r in exchange:
        if (r["identity"], r["version"]) not in labels:
            return LineageCheck(True, False, len(nodes), citations, len(exchange),
                                f"exchange batch {r['batch']} was with an unregistered version")
    for r in readings:
        cp = next((c for c in checkpoints if c["from_tick"] <= r["tick"] <= c["to_tick"]), None)
        if cp is None or not any(v["twin_id"] == r["twin_id"] and v["version"] == r["twin_version"]
                                 and v.get("fingerprint") for v in cp["version_refs"]):
            return LineageCheck(True, False, len(nodes), citations, len(exchange),
                                f"reading at tick {r['tick']} ({r['twin_id']} {r['twin_version']}) "
                                "does not resolve to a registered version")
    return LineageCheck(True, True, len(nodes), citations, len(exchange))


def registered_versions(entries: list[dict]) -> list[dict]:
    """The lineage nodes registered in ``entries``, flattened for display."""
    keep = ("composition", "twin_type", "vendor", "design_twin_id", "operational_twin_id", "asset_id", "project_id",
            "design_system_twin_id", "operational_system_twin_id", "registered_by", "constituents", "code_commit")
    out = []
    for e in entries:
        if e["entry_type"] != REGISTERED:
            continue
        p = e["payload"]
        out.append({"seq": e["seq"], "timestamp": e["timestamp"], **p["twin"],
                    "parent_fingerprint": p["parent_fingerprint"],
                    "measured": {"fingerprint": p["measured"]["fingerprint"], "authority": p["measured"]["authority"],
                                 **({"probes": p["measured"]["exchange"]["calls"]} if "exchange" in p["measured"] else {})},
                    "declared": p.get("declared"),
                    **{k: p[k] for k in keep if k in p}})
    return out
