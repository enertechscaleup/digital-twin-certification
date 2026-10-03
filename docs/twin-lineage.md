# Twin identity and version lineage

Status: built (`engine/lineage.py`), October 2026. Runtime swap detection is
designed below but **not built**.

## Why

A label such as "Motor · twin 1.1.0" is declared by the twin's owner. On its own
it proves nothing: the twin behind it could change while the label stays the
same. To say which vendor's twin diverged, the evidence has to name a specific
twin, and a specific version of it, by content.

## The model

**Identity** says *who* a twin is. It is random (`twn_…`, `sys_…`), assigned
once when the twin is first registered (`python -m engine register-twins`), and
kept for the twin's whole life in `registry/identities.json`. It is never
derived from the twin's content, its vendor or its first fingerprint.

**Version** says *what* the twin is. Each version is a lineage node:

| Field | Meaning |
|---|---|
| `identity` | The twin it belongs to |
| `version` | The owner's label (`1.0.0`, `1.1.0`); the platform numbers system twin versions `1`, `2`, … |
| `fingerprint` | SHA-256 over everything that determines the twin's behaviour (below) |
| `parent_fingerprint` | The version it was derived from; none for the first |
| `code_commit` | The commit the formula identifier refers to, sealed **beside** the fingerprint |

A product twin's fingerprint (`twin-fingerprint/1`) covers its declared formula
identifier (`telemetry/models.py` `FORMULA_IDS`), its parameters, and every
channel's direction, unit, assured range and tolerance. Display names, vendor and
asset do not change behaviour and are not included. The code commit is kept out
of the hash so an unrelated commit never creates a new version; changing what a
formula computes means declaring a new formula identifier.

A system twin's fingerprint (`system-fingerprint/1`) covers each constituent's
identity and fingerprint, the connections, and which constituents produce the
system's outputs. If any constituent changes version, the system twin gets a new
version.

Design and operational stages share one identity and its versions: the
operational twin is a version deployed on an asset. If two assets recalibrate
differently, the lineage branches; parent pointers already allow that.

## Through the lifecycle

Every version is sealed as its own `twin_version_registered` entry **before** any
evidence about it, in the same hash chain as everything else.

1. **Testing.** Verification, bench validation, assurance, status changes,
   anomalies, adjustments and run completion each cite the exact version
   (`twin_ref`). Readings checkpoints resolve every version label in the readings
   they seal to its registered version (`version_refs`).
2. **Composition.** Each composition record cites the system twin's version
   (`system_ref`) and every constituent by role, assurance and exact version
   (`constituent_refs`). Cascade reasons name the constituent's version
   (`constituent_ref`).
3. **Recalibration.** The owner's submission is registered as a new version on
   arrival, with the version in operation as its parent. Its re-verification and
   held-out validation cite it. If it passes, it goes into operation, the system
   twin is registered as a new version, and a fresh composition record follows.
   If it fails, it stays in the lineage as a rejected version and never goes into
   operation. A submission that reuses a version label for different content is
   rejected before testing. Earlier entries are never changed.

## Checks

On every load (`app/evidence.py`), `verify_lineage` checks from the ledger alone:

- every fingerprint matches the inputs sealed with it;
- every parent is an earlier version of the same twin, and only a twin's first version has none;
- no version label is reused for different content, and no twin id belongs to two identities;
- every entry cites a version registered before it, of the twin it is about;
- the parameters and ranges a twin was tested with are exactly the ones fingerprinted;
- each system version's constituents are the registered versions it cites;
- every reading resolves to a registered version.

## Evidence recorded before lineage

Runs recorded before lineage existed have no version entries. They still pass
every other check and are labelled **pre-fingerprint evidence**: twins named by
role and an owner-declared label, with no content fingerprints. They are not
rewritten.

Lineage is purely additive. `legacy_projection` takes it back out: it drops the
registration entries and citations, re-points sequence numbers and hash
references, and rebuilds the chain in the old format. For the same run, that
reproduces the pre-lineage ledger hash for hash. `tests/test_lineage.py` proves
this against the pinned head of each locked run.

## Runtime swap detection (designed, not built)

**What it would catch:** a twin that is running something other than the
version it was assured as, behind an unchanged identity and label.

**Why it is not built:** in this prototype, the twins run inside the platform
and the data is synthetic. There is no externally hosted vendor twin to check
against, so a runtime check would only be checking itself.

**The extension point:** the fingerprint in the ledger is the reference a live
check compares against. Nothing in the lineage model would need to change.

1. *Attestation.* With each batch, an externally hosted twin reports the
   fingerprint of what it is running. It computes this with the same method
   (`twin-fingerprint/1`) over its formula identifier, parameters and channels.
   Alternatively, a signed attestation from the vendor's runtime would serve.
2. *Comparison.* At ingest, the engine compares the reported fingerprint with
   the version in operation (`Lineage.current`). The natural place is next to
   `version_refs`, which already resolves the version label in each reading.
3. *Escalation.* A mismatch would be a new reason, for example
   `cause: version_mismatch`, citing both the registered and the reported
   fingerprint. It would flag or nullify the twin under the same sticky status
   rules, and cascade to the system twin as any other reason does.
4. *Optional challenge.* The platform replays sealed inputs through the twin and
   compares its outputs with what the registered version predicts. This catches
   a twin that reports the right fingerprint but runs something else.

A reported fingerprint is only as trustworthy as the runtime that reports it.
Step 4, or attestation from trusted hardware, is what moves that trust off the
vendor.
