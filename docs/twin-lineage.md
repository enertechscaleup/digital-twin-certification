# Twin identity, lineage and joint composition

Status: built (`engine/boundary.py`, `engine/lineage.py`, `engine/composition.py`),
October 2026. Two extension points are designed below but **not built**:
runtime swap detection and continuous joint monitoring.

## Why

A label such as "Motor · twin 1.1.0" is declared by the twin's owner. It proves
nothing on its own: the twin behind it could change while the label stays the
same. And each twin's own evidence cannot show that twins still predict well
once they feed each other, because their errors are not independent. To say
which vendor's twin diverged, and whether a composed system was ever valid, the
evidence has to name each twin's exact version by what it does, and test the
twins together.

## The vendor boundary

Each twin and its simulation engine stay in the owner's environment. The platform
reaches a twin only through the owner's endpoint, and only JSON crosses
(`engine/boundary.py`):

| Request | Reply |
|---|---|
| `describe` | Current version label, and the owner's declared fingerprint |
| `predict` (version, inputs) | Outputs |
| `recalibrate` (version, released data) | The owner's public submission: new label, declared ranges, method, declared fingerprint. Never parameters. |
| `advise` (version, request) | The owner's recommendation |

Every query the platform relies on as evidence is recorded in the exchange file
(`<run>.exchange.jsonl`). Queries are grouped in batches, and each batch's
SHA-256 is sealed in the ledger entry that relies on it. The engine never
imports the vendor side.

**In this prototype the endpoints are simulated.** `vendor/endpoint.py` runs them
in process, and `python -m vendor.serve` serves them over HTTP. A run over HTTP
produces the same ledger, hash for hash. No real vendor is connected. The honest
wording is: *orchestrated through a vendor interface, demonstrated with simulated
vendor endpoints.*

## Identity and versions

**Identity** says *who* a twin is. It is random (`twn_…`, `sys_…`), assigned once
at first registration (`python -m engine register-twins`), and kept in
`registry/identities.json` for the twin's whole life. It is never derived from
the twin's content, vendor or fingerprint.

**Version** says *what* the twin is. Each version is a lineage node, sealed as its
own `twin_version_registered` entry before any evidence about it. It has the
owner's label, a parent pointer (none for the first version), and two
fingerprints that are **not equally authoritative**:

- **Measured** (`probe-response/1`), the evidence. Before a twin is first queried,
  the platform seals a probe set in the ledger (`probe_set_sealed`): the 5-level
  grid across each input's assured range, plus 16 seeded points inside it. Each
  version is queried with that set. The fingerprint covers the declared interface
  (directions, units, assured ranges, tolerances) and the probe answers. Anyone
  can recompute it from the exchange file. Every citation uses it.
- **Declared** (`twin-fingerprint/1`), a claim. This is the owner's own
  fingerprint over the formula and parameters it says the twin contains. It is
  recorded beside the measured one, labelled unverified, and shown that way on
  screen. The platform cannot check it.

The platform commit is sealed beside each version, outside the fingerprint.

A **system twin's** version fingerprint covers each constituent's identity and
measured fingerprint, the connections, and the output constituents. Any
constituent changing version gives the system a new version.

Design and operational stages share one identity and its versions. If two assets
recalibrate differently, the lineage branches.

## Through the lifecycle

1. **Testing.** Every evidence entry cites the exact version (`twin_ref`).
   Verification queries the twin, and its answers must equal the probe answers for
   the same inputs: *what was tested is what was fingerprinted*. Readings
   checkpoints resolve each reading's version label to a registered version.
2. **Composition.** The system version is sealed, then the twins run jointly (see
   below). The system is assured only if the joint test passes. Composition
   records cite every constituent by role, assurance and exact version.
3. **Recalibration.** The owner's new version is probed and registered on arrival,
   with the version in operation as its parent. A label already registered that
   now answers differently is rejected before any test. If the new version passes
   re-verification and held-out validation, it goes into operation. The system
   then gets a new version, and the twins run jointly again. A rejected version
   stays in the lineage, marked rejected. Earlier entries are never changed.

## The joint composition test

This runs at the initial build and after every accepted recalibration
(`engine/composition.py`).

1. **Test points.** A grid across the assured ranges of the system's external
   inputs, meaning the inputs no connection feeds. The number of levels per input
   is a project setting (`composition.test_levels`, default 5). For the compressor
   train that is 5 levels over motor volt and current and compressor flow: 5³ =
   125 points. The Fulfilment cell has five external inputs (order rate, and each
   robot's battery voltage and speed setpoint) and uses 3 levels: 3⁵ = 243 points.
2. **Joint run.** The twins are queried in processing order. A connected input
   gets the upstream twin's *predicted* output, never a measurement. Every
   exchange is sealed.
3. **Interface check.** Every upstream predicted output must land inside the
   downstream twin's assured input range. A failure is the specific reason
   `interface_invalid`, naming the connection, the predicted span and the number
   of points outside.
4. **Interaction check.** At the points where every interface holds, the joint
   prediction of each system output must stay within its output twin's tolerance
   against the combined test bench: the physical machines run together at the same
   inputs, in their condition at that moment. A failure is the specific reason
   `interaction_invalid`, naming the output and the largest gap. Points where an
   interface fails are not evaluated for interaction, as field monitoring does
   not evaluate outputs when an input is out of range.

The `composition_test` entry seals the test points, the exchange, the bench
readings' hash, both results, and its own fingerprint.

- **At build,** a failure refuses the composition (`composition_refused`), and no
  field monitoring starts.
- **After a recalibration,** each failure becomes a reason on the system twin.
  Status stays sticky, and the failure blocks the system's re-assurance.

In the full-cycle scenario, the build test passes. After the motor is
recalibrated to its worn condition, the interface check fails: the motor's
predicted speed, 1125–1346 rpm, leaves the compressor's assured 1250–1600 rpm
at 75 of 125 points. The interaction check passes on the 50 points where the
interface holds. So the system is not re-assured, for a specific and named
reason. The Fulfilment cell shows the same pattern: after AMR 1 is recalibrated,
its predicted deliveries, 29.40–107.05 totes/h, leave the pick station's assured
33.5–125 totes/h at 27 of 243 points (`docs/fulfilment-cell.md`).

## Checks

On every load (`app/evidence.py`), `verify_lineage` checks, from the ledger and
the exchange file alone, that:

- every exchange batch matches its seal, and every exchange is sealed;
- every measured fingerprint matches its sealed inputs, the sealed probe set and
  the recorded answers;
- every parent is an earlier version of the same twin, and no label is reused for
  a different fingerprint;
- every entry cites a version registered before it, of the twin it concerns;
- verification answers equal probe answers, and assured ranges equal the
  fingerprinted interface;
- every reading resolves to a registered version.

## Evidence recorded before lineage

All six runs the app serves today, three per project, were recorded with
lineage: they carry version entries and an exchange file, and pass the lineage
check.

The compressor train's first three runs were recorded before lineage existed.
They have no version entries and no exchange file, and remain in the evidence
bucket under their original head hashes, unchanged. They are no longer pinned.
The app still accepts evidence of that kind: it passes every other check and is
labelled **pre-fingerprint evidence**.

`tests/test_lineage.py` proves that, for each of those scenarios, the current
engine produces byte-identical readings and per-tick status timelines. That holds
with the vendor boundary, lineage and joint tests in place. The record grew; no
decision changed.

## Extension point: runtime swap detection (designed, not built)

**What it would catch:** a twin in operation answering as something other than
the version it was assured as, behind an unchanged identity and label.

**Why it is not built:** this prototype connects no externally hosted twin, so
there is nothing live to check.

**Groundwork already in place:** the measured fingerprint. It is computed only
from what crosses the boundary, so the same mechanism works on a live twin.

1. Periodically, or on a trigger, query the version in operation with the sealed
   probe set (or a fresh set sealed first), and recompute its measured
   fingerprint.
2. Compare it with the registered fingerprint (`Lineage.current`). A mismatch is
   a new reason, for example `cause: version_mismatch`, citing both fingerprints.
   It escalates under the same sticky rules and cascades to the system twin.
3. A twin that recognises probes could answer them correctly and behave
   differently otherwise. The verification cross-check already catches this
   within a run: answers to verification must equal answers to probes. For live
   use, add a fresh probe set from a secret seed that is revealed only after
   probing, or replay sealed field inputs.

## Extension point: continuous joint monitoring (designed, not built)

The joint test runs at build and after recalibration only. A continuous version
would do the following, tick by tick:

1. Each tick, chain the twins' predictions from the measured external inputs: the
   motor twin from measured volt and current, then the compressor twin from the
   motor twin's predicted speed and the measured flow.
2. Compare the chained prediction of each system output with the measured system
   output, using the same gap metric and tolerance as product twins. Keep the
   interface check per tick: is the upstream prediction inside the downstream
   assured range?
3. Escalate on consecutive misses under the protocol's flag and nullify rules, as
   reasons `interface_invalid` or `interaction_invalid` on the system twin, with
   the joint exchanges sealed in readings-style checkpoints.

Nothing in the composition test or the lineage model would need to change. The
cost is one extra query per twin per tick through each owner's endpoint.
