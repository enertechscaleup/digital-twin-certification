# Fulfilment cell: the evidence

The second project on the platform, built to the same standard as the
compressor train and served through the same loading and verification path.
**All data is synthetic.** The robots, the dispatcher, the pick station, their
vendors and every reading are simulated; no real equipment is connected. Faults
are introduced deliberately by scenario files to test how the engine classifies
them. Every figure below is read from the sealed evidence.

## What the cell is

A fleet dispatcher assigns tasks to two autonomous mobile robots (AMRs), which
carry totes to one pick station. Each of the four machines has its own twin,
owned by a (simulated) vendor behind its own endpoint. The platform composes them
into one system twin.

| Twin | Operational twin | Role | Vendor (synthetic) | Mode | Identity |
|---|---|---|---|---|---|
| Fleet dispatcher | `dispatcher-op-001` | controller | `synthetic-vendor-c` | observational | `twn_zvm2nv2imwzbpvuk36ub` |
| AMR 1 | `amr1-op-001` | product | `synthetic-vendor-d` | semi-autonomous | `twn_565h88fwapa4j4gqgnqe` |
| AMR 2 | `amr2-op-001` | product | `synthetic-vendor-d` | semi-autonomous | `twn_vn2uadrxy5tzy4ity5nb` |
| Pick station | `pick-op-001` | product | `synthetic-vendor-e` | observational | `twn_ez4ndx8ny8ssyedw585c` |
| Fulfilment cell (system twin) | `fulfilment-system-op-001` | system | composed by the platform | — | `sys_r44376hchyw9euufqf4g` |

Both robots use the same twin model (catalogue entry `vendor-d/robot-r2`), each
with its own identity and fingerprint. The project file is
`projects/fulfilment_cell.json`; the channel definitions are in
`telemetry/config/{dispatcher,amr1,amr2,pick_station}.json`.

### The 17 channels

Every channel has a 5 % tolerance. The ranges below are the assured ranges.

| Twin | Channel | Direction | Assured range |
|---|---|---|---|
| Dispatcher | `order_rate` (order lines) | input | 300–900 lines/h |
| Dispatcher | `tasks_1` (tasks to AMR 1) | output | 40–110 tasks/h |
| Dispatcher | `tasks_2` (tasks to AMR 2) | output | 40–110 tasks/h |
| AMR 1, AMR 2 (each) | `task_rate` (assigned tasks) | input | 38–110 tasks/h |
| AMR 1, AMR 2 (each) | `battery` (battery voltage) | input | 44–52 V |
| AMR 1, AMR 2 (each) | `speed_setpoint` | input | 1.2–2.0 m/s |
| AMR 1, AMR 2 (each) | `speed` (travel speed, from wheel odometry) | output | 1.0–2.1 m/s |
| AMR 1, AMR 2 (each) | `deliveries` (tote deliveries) | output | 30–140 totes/h |
| Pick station | `arrivals_1` (tote arrivals from AMR 1) | input | 33.5–125 totes/h |
| Pick station | `arrivals_2` (tote arrivals from AMR 2) | input | 33.5–125 totes/h |
| Pick station | `pick_rate` | output | 300–1,160 picks/h |
| Pick station | `cycle_time` | output | 4.4–10.1 s |

That is 3 + 5 + 5 + 4 = 17 channels.

### Composition

Four connections join the twins: `tasks_1 → AMR 1 task_rate`,
`tasks_2 → AMR 2 task_rate`, `AMR 1 deliveries → arrivals_1` and
`AMR 2 deliveries → arrivals_2`. The system's own outputs are the pick station's
outputs, so the pick station is the output constituent.

The same rules as the compressor train apply, unchanged:
- a nullified constituent flags the system twin;
- the system twin takes the status of its output constituent;
- statuses are sticky.

The dispatcher is a controller, but no controller-specific cascade rule exists.

**Joint composition test: 3 levels, 243 points.** The system has five external
inputs (inputs no connection feeds): the dispatcher's order rate, and each
robot's battery voltage and speed setpoint. The grid uses 3 levels per input
(`composition.test_levels: 3`; the platform default, used by the compressor
train, is 5). That gives 3⁵ = **243 test points**. With 5 levels it would be
3,125. Each test runs the four twins together through their owners' endpoints
and seals every exchange (`docs/twin-lineage.md`).

## The three runs

All three use seed 42, a simulated clock (2 s per tick from
2026-10-01T00:00:00Z) and engine code commit `4025058`. They are pinned in
`app/config/runs.json` and stored in
`gs://dtc-evidence-ledger-46053a8a/runs/<run>/<first 16 of head>/`.

| Run | Scenario | Ticks | Core ledger entries | AI ledger entries | Core ledger head hash |
|---|---|---|---|---|---|
| Full assurance cycle | `amr_full_cycle` | 80 (0–79) | 77 | 15 (1 start + 14 explanations) | `466d5d1f9634378c7aea52b5e17ebb7d70f532e6225509a2b05db65817fb3a11` |
| Wear to nullified | `amr_wear_to_nullified` | 60 (0–59) | 51 | 9 (1 + 8) | `8b0c335b3c3677d99c6879eac649e6300f7f3eaddeb2aeaa30c5872b11ecc843` |
| Fault types showcase | `amr_faults_showcase` | 45 (0–44) | 44 | 6 (1 + 5) | `59952ac5a0d853bb7c5f9454824aee53538eba6eac8dee36f3ba236ef87dd125` |

Each run passes all 11 integrity checks. Re-running the engine with the same
scenario, seed and code commit reproduces each head hash exactly.

**Final status (last tick):**

| Run | Dispatcher | AMR 1 | AMR 2 | Pick station | System |
|---|---|---|---|---|---|
| Full cycle (tick 79) | Assured | Assured (v1.1.0) | Assured | Flagged | Flagged |
| Wear to nullified (tick 59) | Assured | Nullified | Assured | Flagged | Flagged |
| Fault showcase (tick 44) | Flagged | Assured | Assured | Assured | Assured |

## Full assurance cycle: event table

Ledger entries #0–#29 are the build: the probe sets and version registrations,
the verification and bench validation of each design twin, the issuing of
assurance, the joint composition test cmp-0001 (#26, passed), and the system's
composition (#27–#28). The field events follow.

| Ledger # | Tick | Twin | Change | Reason (as sealed) |
|---|---|---|---|---|
| #30–#35 | 12–17 | AMR 1 | three short gap exceedances on `deliveries` (anm-0001 to anm-0003), each closed within 1–2 readings | gaps 6.5708 %, 6.5213 %, 5.1081 %: fewer than 3 in a row, so no status change |
| #36, #37 | 19 | AMR 1 | gap exceedances opened on `speed` (anm-0004) and `deliveries` (anm-0005) | gaps 5.3221 % and 5.1415 % |
| #39 | 21 | AMR 1 | assured → **flagged** | `speed` and `deliveries`: 3 consecutive readings beyond 5 % |
| #41 | 36 | AMR 1 | flagged → **nullified** | `deliveries`: 10 consecutive readings beyond 10 % |
| #42 | 36 | System | assured → **flagged** | cascade: constituent `amr1-op-001` is nullified (root cause: `deliveries`, 10 consecutive beyond 10 %) |
| #44 | 41 | AMR 1 | reason added (still nullified) | `speed`: 10 consecutive readings beyond 10 % |
| #45, #46 | 46–47 | AMR 2 | data-quality anomaly anm-0006, closed at tick 48 | `speed` dropout: no physical reading for 2 ticks; not counted as twin error |
| #48 | 59 | Pick station | envelope violation opened on `arrivals_1` (anm-0007), closed at tick 61 (#65) | arrivals from AMR 1 33.0228 totes/h, below the assured 33.5 |
| #50–#58 | 60 | AMR 1 | **recalibration**: requested, data sealed, earlier part released, v1.1.0 submitted, verified, held-out validation **passed**, re-assured as `asr-amr1-op-001-v2` (#57) | see "Recalibration" below |
| #60, #61 | 60 | AMR 1 | anm-0004 and anm-0005 closed | 41 readings each; worst gaps 13.4072 % (speed) and 15.3761 % (deliveries) |
| #62 | 60 | System | joint composition test **cmp-0002 failed** (interface) | see "Joint composition tests" below |
| #63 | 60 | System | reason added (still flagged) | `interface_invalid`: AMR 1 predicted deliveries 29.3953–107.046 totes/h leave `arrivals_1`'s assured 33.5–125 totes/h at 27 of 243 test points |
| #64 | 60 | System | composition reassessment: **not re-assured** | blocked by the cmp-0002 interface failure |
| #66 | 62 | Pick station | envelope violation opened on `arrivals_1` (anm-0008), closed at tick 66 (#72) | arrivals 32.0749 totes/h, below 33.5 |
| #67 | 64 | Pick station | assured → **flagged** | `arrivals_1`: 3 consecutive readings outside [33.5, 125] totes/h |
| #68 | 64 | System | reason added (still flagged) | `own_output`: output constituent `pick-op-001` is flagged |
| #69 | 64 | AMR 1 | adjustment **recommended** (adj-0001) | see "The adjustment" below |
| #70 | 65 | AMR 1 | adjustment **approved** by a human | approver recorded as "Operator (demo)" |
| #71 | 66 | AMR 1 | adjustment **executed** | speed setpoint set to 1.38 m/s, once |
| #74 | 71 | AMR 1 | **post-state check** passed | objective met at 5 of 5 ticks; Sim2Real passed |
| #76 | — | — | run completed | |

Readings checkpoints (#29, #38, #40, #43, #47, #49, #73, #75) seal the raw
readings' SHA-256 into the chain every 10 ticks.

### Recalibration (Real2Sim) of AMR 1

- **Request** (#50, tick 60): AMR 1 has been flagged since tick 21. The window
  is ticks 21–59, split by time with a hold-out fraction of 0.3: ticks 21–47 are
  released to the twin's owner and ticks 48–59 are held out.
- **Sealing** (#51): both parts are sealed before anything is released. The
  released part has 135 readings; the held-out part has 60.
- **Release** (#52): only the earlier part goes to the owner
  (`synthetic-vendor-d`). The held-out readings are never released.
- **Submission** (#54): the owner submits **v1.1.0**, a per-output
  multiplicative correction fitted to the last 10 released ticks (38–47), with
  coupled terms referenced to as-designed upstream behaviour. Declared output
  ranges: speed 0.82–1.85 m/s and deliveries 21.14–124.13 totes/h. The
  correction coefficients stay with the owner; the platform seals the version's
  measured fingerprint (`d8f131448e51…`, #53) beside the owner's declared one.
- **Re-verification** (#55): deterministic, complete, finite and within the
  declared output ranges, with 0 failures.
- **Held-out validation** (#56): **passed.** 12 held-out ticks (48–59) were
  evaluated, with 0 readings over the 5 % tolerance. The worst gaps were
  1.4974 % on speed and 3.2802 % on deliveries.
- **Re-assurance** (#57–#58): AMR 1 is assured as `asr-amr1-op-001-v2` from tick
  60. The nullified v1 assurance and its evidence stay in the ledger unchanged.
- **After recalibration** (ticks 60–79, 20 readings each): the worst gap is
  2.4718 % on speed (mean 0.68 %) and 2.9761 % on deliveries (mean 1.0545 %).

### Joint composition tests

| Test | When | Interface | Interaction |
|---|---|---|---|
| **cmp-0001** (#26) | build | **passed**: all 4 connections inside the downstream assured ranges (for example AMR 1 deliveries predicted 33.584–122.3 totes/h against 33.5–125) | **passed** on all 243 points: cycle time within 3.5931 %, pick rate within 3.3994 % of the combined test bench (tolerance 5 %) |
| **cmp-0002** (#62) | tick 60, after recalibration | **failed** on `amr1/deliveries → pick_station/arrivals_1`: predicted 29.3953–107.046 totes/h against 33.5–125, outside at **27 of 243** points. The other three connections pass. | **passed** on the 216 points where every interface holds (27 not evaluated): cycle time within 4.187 %, pick rate within 3.4831 % |

The recalibrated AMR 1 twin now predicts the worn robot faithfully, and that
worn robot can deliver fewer totes than the pick station is assured for. The
system is not re-assured, and the reason is named.

### The adjustment (adj-0001)

AMR 1 is a semi-autonomous twin: it may recommend one setpoint change, and a
human must approve it before it is executed.

- **Pre-state** (tick 64): the pick station's arrivals from AMR 1 are 33.0205
  totes/h, below the assured minimum of 33.5. AMR 1's inputs are all inside their
  assured ranges: battery 49.488 V, task rate 41.3282 tasks/h, speed setpoint
  1.2984 m/s.
- **Recommendation** (#69): raise the speed setpoint from **1.2984 to 1.38 m/s**.
  The method is the lowest setpoint predicted to give 2 % above the objective,
  kept at least 0.1 below the assured maximum. Predicted end-state: deliveries
  34.3368 totes/h (+0.8368 above the minimum) and speed 1.1749 m/s. The new
  setpoint is inside its assured range of 1.2–2.0 m/s.
- **Approval** (#70, tick 65): human approval, recorded against the
  recommendation entry's hash.
- **Execution** (#71, tick 66): executed once; the system then returns to
  passive monitoring.
- **Post-state check** (#74, ticks 67–71):
  - **objective met** at 5 of 5 ticks (lowest 33.9331 totes/h);
  - **Sim2Real passed**: deliveries within 2.5861 % and speed within 2.0172 %
    of the predicted end-state.

  Statuses do not change. The pick station stays flagged, because assurance is
  sticky: bringing an input back into range does not by itself re-assure a twin.

## Wear to nullified

AMR 1 wears from tick 5 at the same rate as in the full cycle, but without the
12 % cap and with no recalibration.

| Ledger # | Tick | Twin | Change | Reason |
|---|---|---|---|---|
| #26 | build | System | cmp-0001 passed | |
| #39 | 21 | AMR 1 | assured → **flagged** | `speed` and `deliveries`: 3 consecutive beyond 5 % |
| #41 | 36 | AMR 1 | flagged → **nullified** | `deliveries`: 10 consecutive beyond 10 % |
| #42 | 36 | System | assured → **flagged** | cascade: `amr1-op-001` is nullified |
| #44 | 41 | AMR 1 | reason added | `speed`: 10 consecutive beyond 10 % |
| #45 | 49 | Pick station | envelope violation opened on `arrivals_1` (anm-0006) | |
| #47 | 51 | Pick station | assured → **flagged** | `arrivals_1`: 3 consecutive outside [33.5, 125] totes/h |
| #48 | 51 | System | reason added | `own_output`: `pick-op-001` is flagged |

AMR 1's worst gaps over ticks 0–59 are 25.6968 % on speed and 25.7536 % on
deliveries.

## Fault types showcase: data-quality and envelope events

Every fault here is introduced deliberately to test classification. Sensor
faults are classified as data quality and are not counted as twin error.

| Ledger # | Ticks | Twin / channel | Class | Effect |
|---|---|---|---|---|
| #30–#32 | 10–14 (closed at 15) | Dispatcher / `order_rate` | envelope violation (order surge to 930 lines/h, above 900) | Dispatcher **flagged** at tick 12 (#31): 3 consecutive readings outside [300, 900]. Envelope violations never nullify. |
| #34, #35 | 20 | Pick station / `cycle_time` | data quality: **spike** | not counted as twin error |
| #36, #37 | 25–26 (closed at 27) | AMR 2 / `speed` | data quality: **dropout** (wheel odometry) | not counted as twin error |
| #39, #40 | 31–35 (closed at 36) | AMR 1 / `battery` | data quality: **stuck** | the robot's outputs are not evaluated while an input is bad |

The dispatcher is a controller, not the output constituent, and it is flagged
rather than nullified. So the system twin stays assured.

The full cycle has one data-quality event: the AMR 2 speed dropout at ticks 46–47
(#45–#46).

## Gemini explanations

Gemini (`gemini-3.8-flash`, Vertex AI) wrote 27 sealed explanations for the
three runs: 14, 8 and 5. Each was checked before it was sealed:
- its citations, figures and status claims must match the facts it was given,
  and it may cite only ledger entries in those facts;
- each artifact records the hashes of the entries it cites.

None was rejected and none needed a retry. The explanations sit in a separate
supplementary ledger bound to the core ledger's head. Gemini never sets or
changes a status: the deterministic engine decides, and the app reads status only
from the core ledger.

## Disclosed: two tuning changes made while building the scenarios

The cell was designed first, then the scenarios were tuned so that each event
happens for its stated reason. Two changes went beyond the approved design. Both
were reviewed and accepted before the runs were sealed:

1. **The robots' assured task-rate range was widened to 38–110 tasks/h.** At the
   slowest point of the order flow, the dispatcher's predicted tasks dipped just
   under 40, which would have flagged the robots for an input reason the scenario
   did not intend. The dispatcher's own output range stays 40–110 tasks/h.
2. **The order trough was moved under the adjustment window.** The order profile
   now has a slow cycle whose low point (tick 66) falls inside the adjustment.
   Otherwise the adjustment's 5-tick outcome check failed because the robot's
   task load was changing, not because the twin was wrong.

Neither change touches the engine's rules or thresholds. Both are visible in the
committed configuration (`telemetry/config/amr{1,2}.json`,
`telemetry/config/dispatcher.json`). The robots' assured ranges are also part of
each version's measured fingerprint.
