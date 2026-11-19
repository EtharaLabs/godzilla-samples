# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# The agent's environment, built from this folder: pinned toolchains, then the task's workspace and reference executable.
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
ARG TARGETARCH
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 LC_ALL=C.UTF-8 TZ=UTC \
    RUSTUP_HOME=/usr/local/rustup CARGO_HOME=/usr/local/cargo RUSTUP_TOOLCHAIN=1.99.1 \
    PATH=/usr/local/cargo/bin:/usr/local/go/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake pkg-config git ca-certificates curl xz-utils unzip zip python3 python3-pip python3-venv python3-dev tmux less file jq bsdutils procps psmisc \
 && rm -rf /var/lib/apt/lists/*
# Rust 1.99.1 and Go 1.27.3, each download checked by sha256
RUN set -eu; case "$TARGETARCH" in \
      amd64) rt=x86_64-unknown-linux-gnu; rs=5be191e8c70a5007074254cb74d78dbfdd25cd5a61c27de7b8e5410122ec24f4; gs=65efbc80fdc1fa2cd2631cad5b481777a68e8725f34e89f50fc6ac714e379b40 ;; \
      arm64) rt=aarch64-unknown-linux-gnu; rs=a9c168dbea81a84671c6b7a5c1795cb0eb699020110d107ddfca427bd797e697; gs=a06e99309dbcbdca1a8ccd2282c3ee146e55930886e26b4f1193269587165f49 ;; \
      *) echo "unsupported $TARGETARCH" >&2; exit 1 ;; esac; \
    curl -sSf --proto '=https' -o /tmp/rustup-init "https://static.rust-lang.org/rustup/archive/1.29.2/$rt/rustup-init"; \
    echo "$rs  /tmp/rustup-init" | sha256sum -c -; chmod +x /tmp/rustup-init; \
    /tmp/rustup-init -y --no-modify-path --profile minimal --default-toolchain 1.99.1; rm /tmp/rustup-init; \
    rustup component add llvm-tools-preview; chmod -R a+rwX "$RUSTUP_HOME" "$CARGO_HOME"; \
    curl -sSfL -o /tmp/go.tgz "https://go.dev/dl/go1.27.3.linux-$TARGETARCH.tar.gz"; \
    echo "$gs  /tmp/go.tgz" | sha256sum -c -; tar -C /usr/local -xzf /tmp/go.tgz; rm /tmp/go.tgz
# pytest and libtmux for the agent's own tests and for driving tmux, exact versions checked by hash
COPY base-requirements.txt /tmp/base-requirements.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir --no-deps --require-hashes -r /tmp/base-requirements.txt \
 && rm /tmp/base-requirements.txt
# The agent's unprivileged user (it can run the reference executable, not read it)
RUN useradd -m -u 1001 -s /bin/bash agent \
 && git config --system user.name agent && git config --system user.email agent@localhost \
 && git config --system init.defaultBranch main && git config --system --add safe.directory '*'
WORKDIR /workspace
# Pyfun finds its interpreter by spawning `python`, then `python3`. Under the build host's user-mode QEMU a spawn of a
# missing program succeeds, so the emulated amd64 build chose a `python` that does not exist (2026-11-09: 722 tests
# arch_mismatch). With a `python` command both platforms choose it, and it is the same python3.
RUN ln -s /usr/bin/python3 /usr/local/bin/python
COPY --chown=agent:agent workspace/ /workspace/
RUN git init -q && git add -A \
 && GIT_AUTHOR_DATE=2000-01-01T00:00:00Z GIT_COMMITTER_DATE=2000-01-01T00:00:00Z \
    git -c user.name=godzilla -c user.email=godzilla@localhost -c commit.gpgsign=false commit -q -m "Initial commit" \
 && chown -R agent:agent /workspace
COPY --chmod=0111 bin/${TARGETARCH}/executable /workspace/executable
ENV PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/local/go/bin:/usr/local/cargo/bin
USER root
