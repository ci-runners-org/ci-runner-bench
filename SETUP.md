# Setup runbook

Deadline: verdict table ready Monday 2026-09-07 at 09:00 IST.
Times are IST.

## Status as of Sunday 2026-09-06, 16:15 IST

The Saturday window was lost, so the cadence is compressed. `arm-a` now runs
every 30 minutes and `arm-b` every hour. Sixteen slots need an eight-hour
window, so collection must open by about 18:00 IST.

| Component | State |
| --- | --- |
| Repository, workflows, collector | Done and pushed |
| GitHub baseline runner | Verified, 20 of 20 jobs green |
| Blacksmith runners | App installed org-wide, **no runner claims jobs** |
| WarpBuild runners | App installed org-wide, **no runner claims jobs** |
| Namespace runners | **App not installed** |

A label probe claimed nine candidate labels. Only `ubuntu-24.04` started. All
three Blacksmith variants and both WarpBuild variants stayed queued, so the
cause is vendor activation, not a wrong label.

## Blocking step: activate the three vendors

Run `probe.yml` after each fix. A label that starts is live. A label that stays
queued is not.

```bash
gh workflow run probe.yml --repo ci-runners-org/ci-runner-bench
sleep 90
RID=$(gh run list --repo ci-runners-org/ci-runner-bench --workflow probe.yml \
        --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view "$RID" --repo ci-runners-org/ci-runner-bench --json jobs \
  --jq '.jobs[] | "\(.status)  \(.name)"' | sort
gh run cancel "$RID" --repo ci-runners-org/ci-runner-bench
```

Always cancel the probe. Queued jobs otherwise sit for 24 hours and can start
at random later, which pollutes the timings.

| Vendor | What to check |
| --- | --- |
| Blacksmith | Open the dashboard, confirm `ci-runners-org` appears and is active. Select the free plan if prompted. Installing the app alone does not start the runner fleet. |
| WarpBuild | Open the dashboard, confirm the org is connected and a Linux x64 runner is enabled. Confirm the exact label string offered for 4 vCPU. |
| Namespace | The app is not installed. Install it on `ci-runners-org`, then create a runner profile named exactly `bench-4x16` with 4 vCPU, 16 GB, Linux amd64. |

If a vendor offers a different label, change it everywhere at once:

```bash
grep -rl 'OLD-LABEL' .github/ | xargs sed -i '' 's/OLD-LABEL/NEW-LABEL/g'
```

## Revised timeline

| Time IST | Step | Notes |
| --- | --- | --- |
| now to 18:00 | Activate the three vendors, re-run `probe.yml` until all labels start | Blocking |
| +15 min | `gh workflow run seed.yml` | About 45 min wall clock |
| +60 min | Enable `arm-a` and `arm-b`, dispatch one slot of each | Every warm job must hit its cache |
| then to 01:30 | Cron collects unattended | 30-minute cadence |
| 01:30 | `gh workflow run burst.yml`, cancel after 3 min | Queue-time samples |
| 02:00 | Run the collector and the analysis | |

Drop-dead time is 22:00 IST. Opening collection later than that gives fewer
than six slots per cell, which cannot resolve any ratio below about 2.0. If
that happens, report the GitHub baseline and the vendor gap as indicative
only, and say so plainly.

## Part 1: what only you can do

These five items need your accounts. Nothing else in the harness works until
they are done.

| # | Task | Where | Time |
| --- | --- | --- | --- |
| 1 | ~~Create a GitHub organization~~ Done: `ci-runners-org` | GitHub | done |
| 2 | ~~Create a public repository~~ Done: `ci-runners-org/ci-runner-bench`, public, harness pushed | GitHub | done |
| 3 | Sign up for Blacksmith with the evaluation mailbox, install its GitHub App on the org, grant access to the repository | blacksmith.sh | 10 min |
| 4 | Sign up for Namespace, install its GitHub App, create a runner profile named `bench-4x16` with 4 vCPU and 16 GB Linux amd64 | namespace.so | 15 min |
| 5 | Sign up for WarpBuild, install its GitHub App, confirm the `warp-ubuntu-latest-x64-4x` runner is offered | warpbuild.com | 10 min |

The collector needs a token with `actions: read`. Your existing `gh` login
already carries the `repo` scope, which covers it:

```bash
export GITHUB_TOKEN=$(gh auth token)
```

RunsOn is out of scope for the weekend. Its trial takes payment details and it
bills EC2 in your own AWS account, so it cannot be run on a free tier.

## Part 2: state of the repository

The harness is already pushed to `ci-runners-org/ci-runner-bench` on `main`.
Actions is enabled and all four workflows are registered.

`arm-a` and `arm-b` are **disabled on purpose**. Their crons would otherwise
fire before the vendor accounts exist, queue 27 jobs against labels that do not
resolve and pollute the first data. Enable them in Part 8, after the dry run
passes.

```bash
gh workflow list --repo ci-runners-org/ci-runner-bench --all
```

The organization disables write permissions for the workflow token, so the
harness never writes through `GITHUB_TOKEN`. Nothing needs changing. If you
later want the cache-usage report to also prune entries, an owner must set
Organization settings, Actions, General, Workflow permissions to read and
write. That is optional.

## Part 3: confirm the runner labels

The three vendor labels in the workflows are the documented defaults. Two are
worth confirming before the dry run, because a wrong label leaves the job
queued forever rather than failing fast.

| Vendor | Label in the workflows | Confirm here |
| --- | --- | --- |
| Blacksmith | `blacksmith-4vcpu-ubuntu-2404` | Blacksmith docs, runner overview |
| Namespace | `namespace-profile-bench-4x16` | Must match the profile name you created in step 4 |
| WarpBuild | `warp-ubuntu-latest-x64-4x` | WarpBuild dashboard, runners page |

If a label differs, change it in all four workflow files at once:

```bash
grep -rl 'namespace-profile-bench-4x16' .github/ | xargs sed -i '' \
  's/namespace-profile-bench-4x16/<actual-label>/g'
```

## Part 4: pin the image digest

`workloads.lock` names `node:22-bookworm` by tag for the image-pull test. A tag
can move during the window. Pin it once:

```bash
docker buildx imagetools inspect node:22-bookworm --format '{{.Manifest.Digest}}'
# then set PULL_IMAGE=node:22-bookworm@sha256:<digest> in workloads.lock
```

## Part 5: smoke test, Friday about 20:00

Run the cheapest job on every runner first. This proves the labels, the images
and the checkout path without spending the budget.

```bash
gh workflow run burst.yml --repo ci-runners-org/ci-runner-bench
gh run watch --repo ci-runners-org/ci-runner-bench
```

Expected: 80 jobs, all green, under 3 minutes of billable time per vendor.

Failure modes and what they mean:

| Symptom | Cause | Fix |
| --- | --- | --- |
| Job stuck on "Waiting for a runner" | Label is wrong, or the vendor app has no access to the repository | Fix the label, or re-check the app installation scope |
| `Resource not accessible by integration` | A step is trying to write through `GITHUB_TOKEN`, which this organization forbids | Report it. The harness is designed to need read access only, so this means a step regressed |
| Vendor job fails at checkout | Vendor image lacks git or the runner has no network egress | Raise with the vendor, or drop that vendor |

## Part 6: seed the warm caches, Friday about 21:00

```bash
gh workflow run seed.yml --repo ci-runners-org/ci-runner-bench
```

This does three things on all four runners. It runs W1 and W2 cold and saves
`~/.bench-cache` under the stable keys that `arm-a.yml` restores. It populates
the W4 Docker layer cache. It builds the 512 MB cache-throughput payload under
the fixed key `t2-<vendor>-v1`.

Budget about 45 minutes of wall-clock and roughly 65 billable minutes per
vendor. Re-running `seed.yml` is safe. The payload job restores before it
saves, so it never duplicates the entry.

Check the reported cache size in each job log. Expected totals:

| Workload | Cached path | Expected size |
| --- | --- | --- |
| W1 | yarn cache folder | 0.7 to 1.2 GB |
| W2 | `CARGO_HOME` only | 0.4 to 0.6 GB |

The Rust target directory is deliberately not cached. See "Cache budget" below.

## Part 7: read the free-tier meters, Friday about 22:00

This is the decision gate for the whole weekend. Open each vendor dashboard,
record the minutes consumed by the smoke test and the seed run, then save a
screenshot to `results/quota/`.

The critical unknown is how Blacksmith counts a 4 vCPU minute against its
3,000 free minutes.

| What the dashboard shows after seeding | Meaning | Action |
| --- | --- | --- |
| About 60 minutes used | 1 unit per job-minute | Proceed with `0 */3 * * *`. Budget about 820 of 3,000. |
| About 120 minutes used | 2 units per job-minute | Proceed. Budget about 1,640 of 3,000. |
| About 240 minutes used | 4 units per job-minute | Change `arm-a.yml` cron to `0 */6 * * *`. Budget about 1,750 of 3,000 with 9 slots. |

Namespace and WarpBuild do not publish their free amounts. Read the remaining
credit in their dashboards. If either shows less than 900 minutes of headroom,
apply the same cron change for everyone, so all runners keep an equal number
of samples.

Never thin the schedule for one vendor only. Unequal slot counts break the
same-wall-clock control that the whole design rests on.

## Part 8: open the collection window, Friday about 23:00

Enable the two cron workflows, then trigger one full slot of each by hand and
watch it finish.

```bash
gh workflow enable arm-a --repo ci-runners-org/ci-runner-bench
gh workflow enable arm-b --repo ci-runners-org/ci-runner-bench
gh workflow run arm-a.yml --repo ci-runners-org/ci-runner-bench
gh workflow run arm-b.yml --repo ci-runners-org/ci-runner-bench
```

All warm jobs must report a cache hit. If a warm job fails with "No warm cache
for ...", re-run `seed.yml` for that runner. That guard is deliberate. A silent
cache miss would corrupt the warm arm.

After this succeeds, the cron takes over. Nothing more is needed until Sunday.

## Part 9: burst tests, Saturday and Sunday about 11:00

```bash
gh workflow run burst.yml --repo ci-runners-org/ci-runner-bench
```

Run it twice, once each day, so the queue-time claims get two independent
samples per runner. Do not run it while an arm A slot is in flight, because a
busy vendor pool would inflate the queue times.

## Part 10: analysis, Sunday 20:00 and Monday 02:00

```bash
export GITHUB_TOKEN=$(gh auth token)
export BENCH_REPO=ci-runners-org/ci-runner-bench
python3 collector/pull_jobs.py
python3 collector/analyze.py
cat results/tables/verdicts.md
cat results/tables/durations.md
```

Both scripts use the Python standard library only. No virtual environment and
no dependency install.

Run this on Sunday evening against partial data. It surfaces schema problems
while there is still time to fix them. Run it again on Monday morning after the
last slot.

## Cache budget

GitHub allows 10 GB of Actions cache per repository and evicts the least
recently used entry beyond that. Three of the four runners write to GitHub's
cache store, because only Blacksmith intercepts `actions/cache` and redirects
it to its own backend. The organization also blocks write permissions for the
workflow token, so nothing can be deleted at runtime. The harness therefore
keeps a fixed, bounded footprint.

| Entry | Per runner | GitHub-store runners | Total |
| --- | --- | --- | --- |
| W1 warm seed, yarn cache | 0.7 to 1.2 GB | 3 | up to 3.6 GB |
| W2 warm seed, `CARGO_HOME` only | 0.4 to 0.6 GB | 3 | up to 1.8 GB |
| W4 Docker layer cache | about 0.4 GB | 3 | about 1.2 GB |
| Cache-throughput payload, fixed key | 0.5 GB | 3 | 1.5 GB |
| Steady-state total | | | about 7 to 8 GB |

Four choices hold that line.

1. The Rust target directory lives in `RUNNER_TEMP`, not in the cached tree.
   Compile work is then identical across the cold and warm arms, which isolates
   CPU for the speed claims.
2. The W4 dependency set is trimmed to about 400 MB.
3. The throughput payload uses one fixed key per runner, seeded once, restored
   read-only by every slot. A per-slot key would have added 0.5 GB every three
   hours and evicted the warm seeds within a day.
4. The warm arm never saves. It only restores, so the payload it measures stays
   byte-identical across all 17 slots.

Every `cache-restore` job prints the repository cache usage. If it approaches
10 GB, prune by hand from your laptop:

```bash
gh cache list --repo ci-runners-org/ci-runner-bench --limit 100
gh cache delete <key> --repo ci-runners-org/ci-runner-bench
```

## What each workload measures

| ID | Workload | Command | Claims |
| --- | --- | --- | --- |
| W1 | excalidraw, pinned SHA | `yarn install --frozen-lockfile`, `yarn test:typecheck`, `yarn test:app` | B1, N3, W1c |
| W2 | ripgrep, pinned SHA | `cargo build --release --locked`, `cargo test --release --locked` | B1b, W1d |
| W4 | Multi-stage Docker build with a churn layer | `docker buildx build` with a GitHub Actions layer cache | B3, N2 |
| W5 | Short Python job, no network | `python3 run.py`, about 60 to 90 s | X1 |
| T1 to T5 | sysbench, fio, 500 MB download, 1 GB cache round trip | `scripts/synthetic.sh` | B2, N1, R3 equivalent |
| T3 | 20 simultaneous trivial jobs per runner | `burst.yml` | B4, W3c |

## Known limits to state in the write-up

1. Two days of data, not two weeks. Seventeen samples per cell resolve ratios
   of about 1.3 and above. Differences under 20% are not resolvable.
2. Only 4 vCPU Linux x64. No 16 vCPU tier, no Windows, no macOS, no arm64.
3. RunsOn is untested, so its 7x to 12x cost claim is unverified here.
4. `RUST_TOOLCHAIN` is `stable`, which can move. Every job logs `cargo
   --version`. Check that all runners logged the same version.
5. GitHub prices are a counterfactual. The baseline runs on a public repository
   at zero cost, so the enterprise cost view uses list prices rather than
   observed spend.
6. Blacksmith Docker layer caching and WarpBuild Docker builders are paid
   add-ons. W4 uses the GitHub Actions cache backend on every runner, so B3 is
   tested on the free path only.
7. Cache restore throughput is measured every slot. Save throughput has only
   one sample per runner, from the seed run, because saving every slot would
   breach the cache budget. Treat save numbers as indicative.
8. The payload is 512 MB, not the 4 GB that RunsOn publishes its cache figures
   against. Compare the ratio to GitHub, not the absolute seconds.
