# Setup runbook

Target: first scheduled slot runs Saturday 2026-09-05 at 02:30 IST.
Deadline: verdict table ready Monday 2026-09-07 at 09:00 IST.

Times are IST. GitHub cron is UTC, so `0 */3 * * *` fires at 05:30, 08:30,
11:30 IST and so on.

## Part 1: what only you can do

These five items need your accounts. Nothing else in the harness works until
they are done.

| # | Task | Where | Time |
| --- | --- | --- | --- |
| 1 | Create a GitHub organization with a name that does not reference BrowserStack | github.com/organizations/plan | 5 min |
| 2 | Create a **public** repository `ci-runner-bench` in that organization | GitHub | 2 min |
| 3 | Sign up for Blacksmith with the evaluation mailbox, install its GitHub App on the org, grant access to the repository | blacksmith.sh | 10 min |
| 4 | Sign up for Namespace, install its GitHub App, create a runner profile named `bench-4x16` with 4 vCPU and 16 GB Linux amd64 | namespace.so | 15 min |
| 5 | Sign up for WarpBuild, install its GitHub App, confirm the `warp-ubuntu-latest-x64-4x` runner is offered | warpbuild.com | 10 min |

Also create a fine-grained personal access token with `actions: read` and
`contents: read` on the new repository. The collector needs it.

RunsOn is out of scope for the weekend. Its trial takes payment details and it
bills EC2 in your own AWS account, so it cannot be run on a free tier.

## Part 2: push the harness

```bash
cd harness
git init -b main
git add .
git commit -m "chore: add CI runner benchmark harness"
git remote add origin git@github.com:<YOUR-ORG>/ci-runner-bench.git
git push -u origin main
```

Then in the repository settings enable Actions and set workflow permissions to
read and write, because `arm-a.yml` deletes its own transient cache entries.

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
gh workflow run burst.yml --repo <ORG>/ci-runner-bench
gh run watch --repo <ORG>/ci-runner-bench
```

Expected: 80 jobs, all green, under 3 minutes of billable time per vendor.

Failure modes and what they mean:

| Symptom | Cause | Fix |
| --- | --- | --- |
| Job stuck on "Waiting for a runner" | Label is wrong, or the vendor app has no access to the repository | Fix the label, or re-check the app installation scope |
| `Resource not accessible by integration` | Workflow permissions are read-only | Settings, Actions, General, set read and write |
| Vendor job fails at checkout | Vendor image lacks git or the runner has no network egress | Raise with the vendor, or drop that vendor |

## Part 6: seed the warm caches, Friday about 21:00

```bash
gh workflow run seed.yml --repo <ORG>/ci-runner-bench
```

This runs W1 and W2 cold on all four runners, then saves `~/.bench-cache`
under the stable keys that `arm-a.yml` restores. It also populates the W4
Docker layer cache. Budget about 45 minutes of wall-clock and roughly 60
billable minutes per vendor.

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

Trigger one full arm A and arm B slot by hand and watch it finish.

```bash
gh workflow run arm-a.yml --repo <ORG>/ci-runner-bench
gh workflow run arm-b.yml --repo <ORG>/ci-runner-bench
```

All warm jobs must report a cache hit. If a warm job fails with "No warm cache
for ...", re-run `seed.yml` for that runner. That guard is deliberate. A silent
cache miss would corrupt the warm arm.

After this succeeds, the cron takes over. Nothing more is needed until Sunday.

## Part 9: burst tests, Saturday and Sunday about 11:00

```bash
gh workflow run burst.yml --repo <ORG>/ci-runner-bench
```

Run it twice, once each day, so the queue-time claims get two independent
samples per runner. Do not run it while an arm A slot is in flight, because a
busy vendor pool would inflate the queue times.

## Part 10: analysis, Sunday 20:00 and Monday 02:00

```bash
export GITHUB_TOKEN=<your PAT>
export BENCH_REPO=<ORG>/ci-runner-bench
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
it to its own backend. The harness therefore holds the footprint down in three
ways.

1. The Rust target directory lives in `RUNNER_TEMP`, not in the cached tree.
   Compile work is then identical across the cold and warm arms, which isolates
   CPU for the speed claims.
2. The W4 dependency set is trimmed to about 400 MB, so the Docker layer cache
   stays small.
3. The 1 GB cache-throughput payload is deleted at the end of every
   `cache-restore` job.

Expected steady state is 5 to 7 GB. Every `cache-restore` job prints the
repository cache usage. If it approaches 10 GB, delete the Docker scopes:

```bash
gh cache list --repo <ORG>/ci-runner-bench --limit 100
gh cache delete <key> --repo <ORG>/ci-runner-bench
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
