# syntax=docker/dockerfile:1
# ^ has to be the literal first line, before any other comment or ARG. It pins the BuildKit
#   frontend, which is what makes `COPY --chmod=` legal below. Without BuildKit this file
#   does not build; CI uses docker/setup-buildx-action, and Docker >= 23 uses BuildKit for
#   plain `docker build` too.
#
# Build context is ./build (docs/hosting.md 3.5: `context: ./build`), so the only things in
# it are this file, modules.txt and entrypoint.sh. Nothing else needs to be sent.
#
# THE RULE THIS FILE EXISTS TO ENFORCE (docs/hosting.md 3.4): builder and runtime derive from
# the SAME base tag. A binary linked against one glibc and copied into a different base fails
# at runtime with `GLIBC_2.xx not found` -- on the VPS, not in CI, which is the worst place to
# find out.
# UBUNTU, NOT DEBIAN, and this is not a preference. AzerothCore requires the ORACLE MySQL
# client library; MariaDB's is not a drop-in. The package name `default-libmysqlclient-dev` is
# the trap, because it resolves differently per distro:
#     Debian bookworm -> MariaDB   (libmariadb-dev)
#     Ubuntu 24.04    -> MySQL     (libmysqlclient-dev, 8.0.46)
# On MariaDB the build dies ~16s into the compile with errors that read like a missing header:
#     'mysql_ssl_mode' was not declared in this scope
#     'MYSQL_OPT_SSL_MODE' was not declared in this scope
#     'mysql_stmt_bind_named_param' was not declared in this scope
# The first two are plain MySQL 5.7+ API that MariaDB Connector/C simply does not have. The
# third is worse and explains why this cannot be patched around: MySQLConnection.cpp guards it
# with `#if MYSQL_VERSION_ID >= 80300`, and MariaDB 11.4 reports MYSQL_VERSION_ID as 110402 --
# numerically larger than 80300 -- so the preprocessor happily selects a MySQL-8.3-only
# function that MariaDB never implemented. Real MySQL 8.0.46 reports 80046 and correctly takes
# the mysql_stmt_bind_param branch. Upstream's own apps/docker/Dockerfile is Ubuntu for exactly
# this reason.
ARG BASE=ubuntu:24.04
# To make an image byte-reproducible, override with a digest and the same value reaches both
# stages: --build-arg BASE=ubuntu:24.04@sha256:<digest>
#
# The core fork pin lives here, not in modules.txt -- see docs/modules.md 6.2. Changing it is
# a different class of event from bumping a module.
# Re-resolved against the GitHub API on 2026-08-08: this commit exists and is still the head
# of branch Playerbot. Committed 2026-08-07T14:08:05Z.
ARG CORE_REPO=https://github.com/mod-playerbots/azerothcore-wotlk.git
ARG CORE_SHA=092e9ba6ff8dc6d861dddd1f31baa9d404381a85

# ---------------------------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------------------------
FROM ${BASE} AS builder
ARG CORE_REPO
ARG CORE_SHA
# Belt and braces: nothing in either apt set pulls tzdata today (checked by simulating both
# installs on bookworm-slim), but a future dependency that does would hang the build on a
# debconf prompt. ARG, not ENV, so it does not persist into any image.
ARG DEBIAN_FRONTEND=noninteractive

# Deps before source, so a core or module bump does not re-run apt.
# Boost >= 1.74, OpenSSL >= 3.0.x, CMake >= 3.16 are the AzerothCore minimums; bookworm ships
# 1.74.0, 3.0.20 and 3.25.1 respectively, so all three are satisfied.
# ca-certificates is NOT optional and its absence is not obvious: debian:*-slim ships no CA
# bundle, and Debian's own mirrors are plain HTTP, so apt succeeds and everything looks fine
# right up until the `git fetch` below dies with
#     fatal: unable to access 'https://github.com/...': server certificate verification
#            failed. CAfile: none CRLfile: none
# Same shape as the missing libboost-regex in the runtime stage: a package you only find out
# about at the moment it is needed, several minutes into a build.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      build-essential cmake git ccache \
      libboost-all-dev libssl-dev default-libmysqlclient-dev libreadline-dev \
      zlib1g-dev libbz2-dev liblzma-dev libzstd-dev \
      && rm -rf /var/lib/apt/lists/*
# liblzma-dev + libzstd-dev exist ONLY because of -DBoost_USE_STATIC_LIBS=ON. Boost.Iostreams
# offers lzma and zstd filters; the SHARED libboost_iostreams.so carries those as its own
# NEEDED entries and the linker never has to think about them. The STATIC .a cannot, so the
# symbols become the final link's problem and CMake's Boost import puts -llzma -lzstd on the
# link line. Without the -dev packages there is no liblzma.so symlink to satisfy -l, and the
# build dies at 99%, after ~1800 objects, with:
#     /usr/bin/ld: cannot find -llzma: No such file or directory
# i.e. the most expensive possible moment. This is the trade for static Boost -- worth it,
# because the alternative couples the runtime image to Boost's minor version (see the runtime
# stage), but it is not free.

WORKDIR /src

# Fetch the pinned COMMIT, not the branch tip: `clone -b Playerbot --depth 1` would make the
# same commit of this repo produce a different image tomorrow. GitHub serves an arbitrary
# commit SHA to `fetch` (allow-reachable-sha1-in-want), so init+fetch+detach works and stays
# shallow. AzerothCore reads git at configure time (src/cmake/genrev.cmake) -- a shallow
# detached checkout is fine there, `git describe --always` degrades to the abbreviated hash.
RUN git init -q . && git remote add origin "$CORE_REPO" \
 && git fetch --depth 1 origin "$CORE_SHA" \
 && git checkout --detach FETCH_HEAD

# Source next. A modules.txt edit invalidates from here down and keeps the apt + core layers.
COPY modules.txt /tmp/modules.txt

# Format is owned by docs/modules.md 6: THREE whitespace-separated fields per line --
# owner/name, ref, pinned commit -- plus `#` comment lines. `ref` is informational (it records
# which branch the SHA came from); the checkout is always the SHA, so a moving branch can never
# end up in an image. This loop is copied from docs/modules.md 6.2, unchanged.
# `set -e` matters: without it a failed clone just continues and you ship a core built without
# one of its modules, with a green CI run.
# The directory name is the repo name, which is load-bearing for exactly one line: the core's
# modules/CMakeLists.txt does `if (SOURCE_MODULE MATCHES "mod-playerbots")` to set
# -DMOD_PLAYERBOTS on the database and game-interface targets. `${repo##*/}` gives
# `mod-playerbots`; renaming that directory silently builds a core without the playerbots
# database support compiled in.
RUN set -e; while read -r repo ref sha; do \
      case "$repo" in ''|\#*) continue ;; esac; \
      name="${repo##*/}"; \
      git clone --filter=blob:none "https://github.com/$repo.git" "modules/$name"; \
      git -C "modules/$name" fetch --depth 1 origin "$sha"; \
      git -C "modules/$name" checkout --detach "$sha"; \
    done < /tmp/modules.txt

# -DTOOLS_BUILD=none, and THERE IS NO `TOOLS` VARIABLE. Get the spelling right, because cmake
# will not tell you: conf/dist/config.cmake (included unconditionally by the top-level
# CMakeLists.txt) declares `set(BUILD_TOOLS_AVAILABLE_OPTIONS none all db-only maps-only)` and
# `set(TOOLS_BUILD "none" CACHE STRING ...)`, and FATAL_ERRORs on a value outside that list --
# whereas an UNKNOWN -D is accepted silently and cached as an unused variable. `-DTOOLS=0`,
# which several third-party guides pass, is a no-op that reads as load-bearing. `none` is the
# default anyway; the flag is documentation of intent. The extractors are only needed to
# extract client data yourself, which we do not do (docs/hosting.md 4).
#
# -DSCRIPTS=static and -DMODULES=static are likewise the defaults declared in that same file
# (`set(SCRIPTS "static" ...)`, `set(MODULES "static" ...)`). Stated explicitly because
# "everything is compiled into worldserver" is the assumption the runtime stage is built on.
#
# NEVER -march=native. The runner CPU is not the VPS CPU; Hetzner shared vCPU fleets are mixed
# silicon and an AVX-512 binary built on a runner SIGILLs on the VPS. AzerothCore's default
# flags are left alone.
#
# ccache is wired in as a compiler launcher AND given a BuildKit cache mount below. The
# distinction matters and is easy to get backwards:
#   - In CI, this buys nothing on its own. buildx `type=gha` caches LAYERS, not RUN cache mounts
#     (docs/hosting.md 3.5), so the mount starts empty every run. The layer cache above is what
#     works there.
#   - Locally, the mount persists in the machine's buildkit state across builds. That is the case
#     that matters while bringing this up: any change below the layer-cache boundary -- a module
#     SHA bump, a cmake flag, a core pin -- otherwise recompiles all of AzerothCore from scratch.
#     With the mount, an unrelated-module rebuild is minutes instead of half an hour.
# The mount is `sharing=locked` because two concurrent builds writing one ccache dir corrupt it.
#
# JOBS defaults to nproc but is overridable: AzerothCore has several translation units that peak
# well past 2 GB, so on a 16-core box with less than ~32 GB free, -j16 swaps and finishes SLOWER
# than -j12. Pass --build-arg JOBS=12 rather than trusting core count.
ARG JOBS=""
RUN --mount=type=cache,target=/root/.ccache,sharing=locked \
    ccache -M 25G -o compression=true -o compression_level=1 >/dev/null \
 && cmake -S . -B /build \
      -DCMAKE_INSTALL_PREFIX=/opt/ac \
      -DCMAKE_BUILD_TYPE=Release \
      -DTOOLS_BUILD=none -DSCRIPTS=static -DMODULES=static \
      -DBoost_USE_STATIC_LIBS=ON \
      -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
 && cmake --build /build -j"${JOBS:-$(nproc)}" \
 && ccache -s | sed -n '1,8p' \
 && cmake --install /build

# ---------------------------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------------------------
FROM ${BASE} AS runtime
ARG DEBIAN_FRONTEND=noninteractive

# Ubuntu 24.04 runtime names. These changed wholesale when the base moved from bookworm to
# 24.04, and several are NOT the names you would guess -- Ubuntu's 64-bit-time_t transition
# renamed a batch of them with a `t64` suffix:
#     libssl3      -> libssl3t64
#     libreadline8 -> libreadline8t64
# Both old names still resolve to nothing on 24.04, and `apt-get install` fails loudly on a
# missing package, so this is a build-time error rather than a silent one. Verified against
# `apt-cache policy` inside ubuntu:24.04 on 2026-08-08.
#
# NO libboost-* PACKAGES AT ALL, and that is the point. The builder now configures with
# -DBoost_USE_STATIC_LIBS=ON (upstream's own apps/docker/Dockerfile does the same), so Boost is
# linked into the binaries and the runtime stage needs none of it. This deliberately kills a
# whole bug class: the previous dynamic-boost arrangement coupled the runtime package list to
# the builder's Boost minor version, and the fork requires FIVE components rather than
# upstream's four (deps/boost/CMakeLists.txt at 092e9ba6 adds `thread`). Missing one produced a
# green CI and two daemons dying at exec before logging anything:
#     error while loading shared libraries: libboost_regex.so.1.74.0
# With static Boost there is nothing to miss. libicu74 stays: statically-linked boost_regex
# still links ICU dynamically.
#
# libmysqlclient21, NOT libmariadb3 -- the counterpart of the base-image decision at the top of
# this file. On Ubuntu the dev metapackage resolves to Oracle MySQL, so the runtime .so must be
# MySQL's too. Mixing them gives a runtime "cannot open shared object file", not a build error.
#
# libbz2-1.0 and zlib1g are listed even though the base already ships both, because deps/bzip2
# and deps/zlib both do `find_package(... REQUIRED)` + `add_library(... SHARED IMPORTED)` on
# UNIX, so both are real DT_NEEDED entries of worldserver rather than something only the builder
# used. Listing a preinstalled package is free; discovering a slimmed base dropped one is not.
#
# default-mysql-client is NOT optional and NOT for you to type commands with. AzerothCore's
# DBUpdater does not apply SQL migrations in C++ -- DBUpdaterUtil::CheckExecutable() looks for a
# `mysql` binary on PATH and the first boot aborts with "Didn't find any executable MySQL binary
# at '...' or in path" when there isn't one (docs/bring-up.md 1.1 row 2).
#
# REGENERATE THIS LIST, DO NOT MAINTAIN IT BY HAND. docs/hosting.md 3.4 has the two commands:
# an ldd-of-the-builder pass that maps every DT_NEEDED back to its package (query both the
# /lib and /usr/lib path forms or the answer comes back quietly short), and a
# `ldd ... | grep "not found"` check on the finished runtime image that turns a missing library
# into a red CI run instead of a dead server. Run both after any core bump.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      libmysqlclient21 libssl3t64 libreadline8t64 libicu74 \
      libbz2-1.0 zlib1g liblzma5 libzstd1 \
      default-mysql-client \
      && rm -rf /var/lib/apt/lists/*

# cmake --install lays this out as /opt/ac/bin/{worldserver,authserver} (install(TARGETS ...
# DESTINATION bin) on UNIX) and /opt/ac/etc + /opt/ac/etc/modules for the .conf.dist files
# (CONF_DIR defaults to ${CMAKE_INSTALL_PREFIX}/etc in src/cmake/platform/unix/settings.cmake).
# docs/bring-up.md 4 explains why the .dist files matter and how the real .conf files get in.
COPY --from=builder /opt/ac /opt/ac

# The .sql files DBUpdater feeds to that mysql client are read off disk at run time, relative
# to SourceDirectory:
#   <src>/data/sql/base/db_{auth,characters,world}   initial import
#   <src>/data/sql/updates/...                       migrations
#   <src>/modules/<module>/data/sql/...              every module's SQL
# `cmake --install` ships none of it, so it comes out of the builder. These are exactly the two
# directories AzerothCore's own db-import image copies (`COPY data data`, `COPY modules
# modules`), and BOTH are load-bearing: an image with data/ but not modules/ imports the three
# core schemas happily and then dies partway through the module migrations.
#
# /opt/ac/src is the value of SourceDirectory. The compiled-in default is the BUILD-TIME CMake
# source path -- /src here -- which does not exist in this stage. deploy/docker-compose.yml sets
# AC_SOURCE_DIRECTORY=/opt/ac/src; docs/bring-up.md 1.1 covers it.
COPY --from=builder /src/data    /opt/ac/src/data
COPY --from=builder /src/modules /opt/ac/src/modules

# Last, so editing the entrypoint rebuilds one tiny layer instead of re-copying /opt/ac.
# Kept as a real file rather than a heredoc (docs/hosting.md 3.4 inlines it) purely so it can
# be shellchecked, `sh -n`'d and diffed like the rest of scripts/. Same destination, same
# content, same semantics. --chmod is belt and braces over the file's git mode.
COPY --chmod=0755 entrypoint.sh /usr/local/bin/acore-entrypoint

# No CMD. deploy/docker-compose.yml sets ACORE_COMPONENT per service and deliberately sets no
# `command:`; a CMD here would be one more thing that could shadow the dispatch.
ENTRYPOINT ["/usr/local/bin/acore-entrypoint"]
