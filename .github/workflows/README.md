# CI

Two workflows, one fixture.

| File | Trigger | Cost | Does |
|---|---|---|---|
| [`build.yml`](build.yml) | push to `main` touching `build/**` (or itself), `workflow_dispatch` | tens of minutes cold, minutes warm | builds `build/Dockerfile`, pushes `ghcr.io/<owner>/wowserver:<sha>`, then verifies the pushed image |
| [`lint.yml`](lint.yml) | every push to `main`, every PR, `workflow_dispatch` | ~30 s | `bash -n` + `shellcheck` over the repo's shell, `docker compose config` over `deploy/`, YAML parse over everything |
| [`../ci/compose-lint.env`](../ci/compose-lint.env) | — | — | junk values so `docker compose config` can run without the gitignored `deploy/.env` |

They are two files rather than one because GitHub's `paths:` filter is **per workflow, not per
job**. `build.yml` is filtered to `build/**` so a doc edit never costs forty minutes of runner
time; a lint job inside it would inherit that filter and would therefore never see the change to
`scripts/` or `deploy/` it exists to catch.

---

## The GHCR visibility trap — read this before the first deploy

**A new GHCR package is private by default, and it does not inherit the repository's
visibility.** This repository is public. The package it pushes will not be, until you say so.

GitHub's own wording, from *[Configuring a package's access control and
visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)*:

> By default, if you publish a package that is linked to a repository, the package automatically
> inherits the access permissions (but not the visibility) of the linked repository.

and

> When you first publish a package that is scoped to your personal account, the default
> visibility is private and only you can see the package.

So the build goes green, the tag exists, and then the first command anyone runs on the VPS —
the image-verification one-liner in [`docs/bring-up.md`](../../docs/bring-up.md) §1.1, before
`docker compose pull` gets a chance — fails with:

```
Error response from daemon: denied
```

which reads like a broken push and is not one.

**[`docs/hosting.md` §3.6](../../docs/hosting.md) owns the full explanation and the two ways
out.** In short, and in its order of preference:

1. **Flip the package public.** Once, by hand:
   `github.com/<owner>` → **Packages** → `wowserver` → **Package settings** → *Danger Zone* →
   **Change visibility** → **Public**. The VPS then pulls anonymously and there is no credential
   on the box at all. The image is a compiled game server and carries no secrets.
2. **Log in on the VPS with a token.** A classic PAT scoped to `read:packages` and nothing else:
   ```bash
   echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_OWNER" --password-stdin
   ```
   This is a *second* credential. CI authenticates with the automatically-provided
   `GITHUB_TOKEN`, which only exists inside a workflow run and cannot be copied to the server.

`build.yml` sets `org.opencontainers.image.source` on the image, which is what links the package
to this repository — the link is what grants the *permissions* inheritance quoted above. It still
does nothing for visibility. Nothing does, except step 1.

---

## Tags, and rolling back

One tag per build: the commit SHA. **There is no `:latest`.** This diverges from the sketch in
`docs/hosting.md` §3.5, which pushes both — the SHA-only rule wins.

`deploy/docker-compose.yml` pins
`ghcr.io/${GHCR_OWNER}/wowserver:${IMAGE_TAG:?pin a SHA, not latest}`, so:

```sh
# deploy/.env on the VPS — a rollback is this line
IMAGE_TAG=<the previous commit sha>
```

then `docker compose pull && docker compose up -d`. Every successful build prints the exact two
lines to paste into `deploy/.env` in its run summary. Keep the previous image on disk; the disk
table in `docs/hosting.md` §1.1 budgets for "one old tag".

A `:latest` tag would make *"which image is that box running?"* unanswerable, which is precisely
the question you are trying to answer when you need to roll back.

---

## Disk

**Disk is the binding constraint on this build.** Not CPU, not RAM, not minutes.

[`docs/hosting.md` §3.3](../../docs/hosting.md) has the table: a public repo gets a
4 vCPU / 16 GB runner and unmetered minutes, a private one 2 vCPU / 8 GB — but **both rows say
14 GB SSD**, and that volume is shared with the preinstalled toolchain image. Against those
14 GB: the builder stage's apt layer, a shallow clone of the core fork plus every module in
`build/modules.txt`, the C++ object tree for AzerothCore *with playerbots compiled into the
core*, the installed prefix, the runtime image, and a `mode=max` buildx cache export of all of
it. AzerothCore's own guidance is 20 GB free minimum, 50 GB recommended.

What `build.yml` does about it, in the `Free runner disk` step, before anything is built:

- **Prints `df -h /` and a depth-1 `du` of `/opt`, `/usr/local`, `/usr/share`** before and after.
  §3.3 asks for exactly this — free space varies by runner-image release, so the log tells the
  truth rather than a number in a doc. Re-tune the delete list from that output, not from memory.
- **Deletes five preinstalled toolchains this job never touches**: `/usr/local/lib/android`
  (the big one), `/usr/share/dotnet`, `/opt/ghc`, `/usr/local/.ghcup`, and the hosted tool cache
  at `$AGENT_TOOLSDIRECTORY`. `rm -rf` on an absent path is a no-op, so a future runner-image
  change degrades this to "freed less" and never to a failed build. Deleting the tool cache is
  safe for the JavaScript actions that run afterwards — the runner executes those on its own
  bundled Node, not on anything in the cache.
- **Prunes the seeded docker images** (`docker image prune --all --force`), before
  `setup-buildx-action` starts its BuildKit container, so that container is not a prune
  candidate.
- **Asserts a floor.** Under 12 GB free it fails immediately with a message; under 25 GB it
  warns. ENOSPC forty minutes into a cold build is the failure this exists to prevent, and a
  tripwire that costs thirty seconds is cheaper than discovering it at minute forty.

No third-party action is used for any of this. It is five `rm -rf` arguments and a prune, and
the delete list is reproduced inline from `jlumbroso/free-disk-space` rather than by depending
on it; `/usr/local/lib/android` is confirmed against `ANDROID_HOME` in
`actions/runner-images`' Ubuntu 24.04 image README.

**If a build ever dies with ENOSPC anyway**, in escalating order:

1. Drop `mode=max` to plain `mode=min` on `cache-to` — smaller export, at the cost of a full
   core rebuild on any module change.
2. Move the cache off the Actions budget entirely, to a registry cache (the commented-out
   `type=registry` lines in `build.yml`). No 10 GB cap there.
3. Relocate the Docker data root onto the runner's `/mnt` temp disk, which is much larger than
   `/`. Not done by default because GitHub does not document `/mnt`'s size, and it means
   restarting the daemon mid-job.

---

## Caching

`cache-from: type=gha` / `cache-to: type=gha,mode=max`. The buildx layer cache is the one that
works out of the box; a `RUN --mount=type=cache` ccache directory is **not** persisted across
runs by `type=gha` without extra plumbing (`docs/hosting.md` §3.5).

`mode=max` is the load-bearing part: it caches the intermediate builder stage too, which is what
makes a `modules.txt`-only change rebuild in minutes. Without it only the final runtime stage is
cached, and every module bump recompiles the whole core.

The catch: the gha cache shares the repository's **10 GB Actions cache allowance** and is
LRU-evicted. If small diffs start producing cold builds, that is eviction thrashing, and the fix
is the registry cache in the escalation list above.

---

## What lint gates on

- **Every shell script in the repo**, found by suffix *and* by shebang, so a helper that loses
  its `.sh` is not silently skipped. Finding zero scripts is itself a failure.
- **`bash -n`, then ShellCheck in two passes.** A broad gate at `--severity=warning`, plus a
  second pass with `--include=SC2086` that promotes exactly one *info*-level check to fatal:
  the unquoted expansion, as in `rm -rf $dir/logs/*`. That one is worth being strict about —
  these scripts run as root out of cron, where the blast radius of an empty variable is the
  disk.
- A single blanket `--severity=info` gate was tried and rejected: it goes red on correct code
  (SC2015 on `phase.sh`'s `&& echo 0 ||` chain, which is safe; SC2016 on `health.sh` printing
  literal backticked command names), and the exclusion list it needs becomes a per-file
  negotiation that ends with somebody disabling a code to turn a red run green. **SC1091** is
  the only exclusion — the scripts `source` the gitignored `deploy/.env`, genuinely absent in a
  checkout.
- Everything below the gate is still printed, as advice, in a collapsed group.
- A footgun worth knowing, since it silently disables checking: a comment line beginning
  `# shellcheck ` (lowercase) is read as a ShellCheck **directive**, and an unparseable one is
  SC1073 — an error that stops the rest of that file being checked at all. Write `ShellCheck`
  in prose.
- **`docker compose config`** over `deploy/`, plus a check that no resolved image is unpinned.
- **A YAML parse** of everything `.yml`/`.yaml`, these workflows included.

Everything runs on the preinstalled toolchain — shellcheck, Docker and Compose all ship in the
`ubuntu-24.04` runner image, so the job downloads nothing.

---

## Time budget

GitHub kills any job at **6 hours**, without a useful message. `build.yml` sets
`timeout-minutes: 330` so it fails loudly, with a log, half an hour earlier.

A cold AzerothCore + playerbots build is tens of minutes on the public-repo runner; a warm one
is minutes. If a run ever approaches 330 minutes the cache is not working — diagnose that rather
than raising the number.

---

## Pinning policy

Everything a run consumes is pinned, because "it worked last Tuesday" is not a recoverable
state (`docs/modules.md` §6 makes the same argument about module commits):

- **Actions by commit SHA**, with the human-readable tag in a trailing comment. A `@v7` tag is a
  branch someone else can move.
- **The runner image** is `ubuntu-24.04`, not `ubuntu-latest`. Identical today, but the label
  moves — and the disk cleanup deletes paths that are properties of *this* image.
- **buildx `v0.35.0` and BuildKit `v0.31.2`.** Left alone, `setup-buildx-action` installs the
  newest buildx and starts `moby/buildkit:buildx-stable-1`, two moving refs in the middle of a
  pipeline that pins everything else. `buildx-stable-1` resolves to v0.31.2 today (tag and
  release both dated 2026-07-16); v0.35.0 is the buildx cut alongside that BuildKit line.

To bump any of them: resolve the new tag to a commit SHA and edit one line.

```sh
gh api repos/docker/build-push-action/releases/latest --jq .tag_name
gh api repos/docker/build-push-action/git/ref/tags/v7.3.0 --jq .object.sha
```

---

## What the build verifies before it goes green

Failing on the runner is free. Failing on the VPS costs a database import and an evening. After
the push, `build.yml` pulls the image back **by digest** — which also proves the push is
pullable, the operation the VPS is about to perform — and checks:

1. **`ldd` finds no missing shared objects** in the *runtime* stage, for both binaries.
   `docs/hosting.md` §3.4 asks for this step by name. It is the check that turns a forgotten
   `libboost-regex1.74.0` into a red CI run instead of a `worldserver` that dies at exec, before
   it logs anything.
2. **The four content requirements** of [`docs/bring-up.md`](../../docs/bring-up.md) §1.1: a
   `mysql` client on `PATH` (AzerothCore's DB updater shells out to it), both binaries, the
   world SQL tree, and the per-module SQL trees. Both SQL checks matter — an image with `data/`
   but not `modules/` imports the three core schemas happily and then dies partway through the
   module migrations. Plus a count of installed module `.conf.dist` files.
3. **An `ENTRYPOINT` and no `CMD`** — §1.1 requirement 5. One image, two daemons, dispatched on
   `$ACORE_COMPONENT`, with no `command:` in the compose file. An image with no entrypoint gives
   two containers that start a shell, find no tty, and exit 0: `docker compose up -d` reports
   success and there is no server.

The lint workflow's compose check is the same instinct applied to `deploy/`: an **unset variable
is only a warning** to compose, which substitutes an empty string and carries on. `docs/bring-up.md`
§5.1 documents the live consequence — an empty `TAILSCALE_IP` turns `"${TAILSCALE_IP}:8085:8085"`
into `":8085:8085"`, which compose accepts as "publish on every interface". So `lint.yml` treats
that warning as fatal.
