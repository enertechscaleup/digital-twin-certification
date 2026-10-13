# Deploy plan: Fulfilment cell release

A plan, not a record: nothing here has been run. Each step waits for its
approval:
- **DEPLOY APPROVED** for the build and the tagged no-traffic revision;
- **TRAFFIC APPROVED** for moving traffic;
- **PUSH APPROVED** for GitHub.

Read-only facts below were checked on 13 Oct 2026. Their raw outputs are in
`deck-assets/measurements/` (git-ignored).

## Target

| | |
|---|---|
| Project | `project-46053a8a-6324-40f0-ba8` |
| Service | **`digital-twin-certification`**, region **us-central1** |
| Not touched | `digital-twin-certification-preview` (a separate service; no command below names it) |
| Serving today | `digital-twin-certification-00008-f4q`, 100 % (traffic set to "latest revision"), image `…/cloud-run-source-deploy/digital-twin-certification@sha256:65982bb1…`, built from `b6065e4` |
| Rollback target | `digital-twin-certification-00008-f4q`. Its image is still in Artifact Registry, which has no cleanup policy. |
| Source | the tip of branch `fulfilment-cell`, from a clean working tree |

**History.** `591ebd8` (the v4 demo video source) is an ancestor of the branch
tip: `git merge-base --is-ancestor 591ebd8 HEAD` succeeds. So the release
contains it. It changes only `video/`, which `.gcloudignore` excludes from the
upload.

## What the new image contains

The Dockerfile copies the following:
- `projects/`;
- `scenarios/` (each run's one-line label is read from it);
- `registry/`, `telemetry/`, `engine/`, `explain/`, `app/`;
- the built web app.

`app/config/runs.json` now pins **six** runs: the three compressor pins
(unchanged) and the three Fulfilment-cell pins.

The image carries **no evidence**. It reads the evidence bucket and verifies
every run on load.

Checked locally with exactly those folders (`2026-10-13-container-fileset.txt`):
- both projects are served;
- all six runs pass 11/11;
- the cell runs show their labels;
- the `vendor/` package is never imported (it is not in the image).

**Source upload.** `gcloud run deploy --source .` uploads the source to the
Cloud Run source bucket (`run-sources-…`), not to the evidence bucket.
- `.gcloudignore` now also excludes `deck-assets`, `.pytest_cache` and
  `.DS_Store`. Before this, a deploy would have uploaded 211 files from
  `deck-assets/`.
- The upload set is now 104 files, every one of them tracked by git
  (`2026-10-13-source-upload-file-list.txt`).

## Before deploying

1. The working tree is clean, on `fulfilment-cell`. Record `git rev-parse HEAD`.
2. `python -m unittest discover -s tests` passes (currently 208 tests).
3. The six head checks pass: each run re-runs to its pinned head and verifies
   11/11 from local files.

## Build and deploy (on DEPLOY APPROVED)

```bash
SHA=$(git rev-parse --short=7 HEAD)
gcloud run deploy digital-twin-certification --source . \
  --project project-46053a8a-6324-40f0-ba8 --region us-central1 \
  --no-traffic --tag cell --revision-suffix "cell-$SHA" \
  --allow-unauthenticated \
  --service-account=dtc-runtime@project-46053a8a-6324-40f0-ba8.iam.gserviceaccount.com \
  --build-service-account=projects/project-46053a8a-6324-40f0-ba8/serviceAccounts/dtc-builder@project-46053a8a-6324-40f0-ba8.iam.gserviceaccount.com \
  --set-env-vars=EVIDENCE_BUCKET=dtc-evidence-ledger-46053a8a,GOOGLE_CLOUD_PROJECT=project-46053a8a-6324-40f0-ba8 \
  --memory=512Mi --cpu=1 --max-instances=3
```

- **`--no-traffic`.** The new revision gets no traffic. Today traffic follows
  "latest revision", so gcloud first pins it to the current revision,
  `00008-f4q`. The public URL keeps serving `00008-f4q` throughout.
- **`--tag cell`.** This gives the new revision its own test URL:
  `https://cell---digital-twin-certification-eqxy2ooxuq-uc.a.run.app`.
- **`--revision-suffix`.** This names the revision after the commit, e.g.
  `digital-twin-certification-cell-<sha>`.
- **Settings unchanged:** every other setting stays as it is today:
  - memory, CPU, max instances, concurrency 80, timeout 300 s;
  - startup CPU boost;
  - service accounts and environment.

Then confirm the result:

```bash
gcloud run services describe digital-twin-certification --region us-central1 \
  --project project-46053a8a-6324-40f0-ba8 --format="yaml(status.traffic)"
```

Expected: `00008-f4q` at 100 %, and the new revision at 0 % with tag `cell`.

## Memory: keep 512 MiB

| Measurement | Value |
|---|---|
| Live revision `00008-f4q` (3 runs), daily p99 memory on Cloud Run, 512 MiB limit | 106.4–127.8 MiB (20.8–25.0 %) over the days with data, 5–13 Oct |
| Local process, all six runs verified and replayed from the bucket, peak RSS | 111.1 MiB |
| Local process, from local files | 72.1 MiB |

**Recommendation: keep 512 MiB.** The measured peaks leave roughly four times
headroom. The local figure is from macOS, not the Cloud Run container, so the
real figure for six runs is checked on the tagged revision (Cloud Monitoring,
`container/memory/utilizations`) before any traffic moves. Raise to 1 GiB only
if that check shows a p99 above 50 %.

## IAM: no changes needed

Checked read-only on 13 Oct (`2026-10-13-cloud-readonly.txt`):
- **`dtc-runtime`:**
  - `roles/storage.objectViewer` on `gs://dtc-evidence-ledger-46053a8a` only, to
    read the six runs' evidence;
  - `roles/aiplatform.user` on the project, for Gemini (explanations are sealed;
    the assistant is live).
  - It has no write role on the evidence bucket.
- **`dtc-builder`:** `roles/cloudbuild.builds.builder`, to build from source.

No grant is added or removed.

## Checks on the tagged revision (before any traffic moves)

Run against `https://cell---digital-twin-certification-eqxy2ooxuq-uc.a.run.app`:

1. **All six runs pass 11/11** from the bucket, via `/api/runs/{run}/meta`.
   Record each run's verification time as reported by the revision.
2. **Projects page** lists both projects with their final statuses.
3. **The cell opens in the whole-system view; the compressor opens on the
   motor.**
4. **Sealed explanations appear** with their cited ledger entries, for both
   projects.
5. **One assistant question per project.** The cell question must cite ledger
   entries. A request to change a status must be refused. Record seconds,
   model calls and tool rounds.
6. **No console errors** in the browser.
7. **Cold-start time:** the first request to an idle revision, with time to
   first byte measured.
8. **Memory:** the revision's p99 in Cloud Monitoring after the checks above.

Then STOP and report. Traffic moves only on TRAFFIC APPROVED.

## Shift traffic (on TRAFFIC APPROVED)

```bash
gcloud run services update-traffic digital-twin-certification \
  --project project-46053a8a-6324-40f0-ba8 --region us-central1 \
  --to-tags cell=100
```

## After the shift

1. On the public URL, signed out: both projects, all six runs 11/11, one
   explanation and one assistant answer.
2. `gcloud run services describe …`: the new revision is at 100 %, and
   `00008-f4q` is still listed and Ready, at 0 %.
3. The Cloud Run logs for the new revision show no errors.
4. Screenshots for the deck are taken from the live public URL.

## Rollback

```bash
gcloud run services update-traffic digital-twin-certification \
  --project project-46053a8a-6324-40f0-ba8 --region us-central1 \
  --to-revisions digital-twin-certification-00008-f4q=100
```

- **What rollback does:** it only changes routing to a revision that is already
  built and Ready. There is no build and no upload. The evidence bucket is not
  involved, and the compressor's pinned evidence is unchanged by this release.
  `00008-f4q` would therefore serve the compressor train exactly as today.
- **How long it takes:** **not measured yet.** The same kind of operation (a
  traffic update) is timed when traffic is shifted forward, and that figure
  will be reported as the rollback time. After a rollback, the first request may
  meet a cold start, because the service has no minimum instances.

## Not in this plan

- No change to the evidence bucket.
- No change to the -preview service.
- No IAM change.
- No push to GitHub until PUSH APPROVED. Then `main` is fast-forwarded
  (`git merge --ff-only`, never squash or rebase), so `4025058`, the commit
  sealed in the cell runs, stays reachable.
