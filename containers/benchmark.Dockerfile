FROM node:24-bookworm-slim

ARG CODEX_VERSION=0.162.1
ARG CLAUDE_VERSION=2.1.325
ARG OPENCODE_VERSION=1.15.10

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 g++ make git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @openai/codex@${CODEX_VERSION} \
       @anthropic-ai/claude-code@${CLAUDE_VERSION} opencode-ai@${OPENCODE_VERSION} \
    && npm cache clean --force

# Claude's credential scrubber needs its Linux subprocess sandbox runtime.
RUN apt-get update && apt-get install -y --no-install-recommends bubblewrap socat \
    && rm -rf /var/lib/apt/lists/*

COPY puzzlebench/proxy.py /opt/puzzlebench/proxy.py
COPY puzzlebench/bwrap.py /opt/puzzlebench/claude-bwrap
RUN chmod 0555 /opt/puzzlebench/claude-bwrap \
    && mkdir -p /workspace /bench /home/bench /etc/claude-code \
    && printf '%s\n' '{"sandbox":{"bwrapPath":"/opt/puzzlebench/claude-bwrap"}}' \
       > /etc/claude-code/managed-settings.json
ENV HOME=/home/bench PYTHONPATH=/bench PYTHONDONTWRITEBYTECODE=1 \
    NODE_USE_ENV_PROXY=1 NO_COLOR=1
WORKDIR /workspace
CMD ["sleep", "infinity"]

# Fixed URLs and SHA-512 values from Google's Linux release manifests.
ARG TARGETARCH
RUN set -eu; release=1.5.12-5281398513336320; \
    case "${TARGETARCH:-$(dpkg --print-architecture)}" in \
      arm64) artifact=linux-arm/cli_linux_arm64; sha=1030d89ce9e5cb39509e272cb89b71fde0e0d5d6527b7392525d5ef2683da54fb49230449107486d91c02ded39a678faaa649b2041304a6cf82a3a332d5819d9 ;; \
      amd64) artifact=linux-x64/cli_linux_x64; sha=26de25fccb3fbf0b093e090ce14a14ac1df1ec3e90ef4ea6106887d3a81b0cc9edb0dadea7b9101d07f9606eba159062a6fb7b78e91b73f7520684a24db73428 ;; \
      *) echo "Unsupported Antigravity architecture" >&2; exit 1 ;; esac; \
    curl --fail --silent --show-error --location --retry 3 \
      "https://storage.googleapis.com/antigravity-public/antigravity-cli/${release}/${artifact}.tar.gz" -o /tmp/agy.tar.gz; \
    echo "${sha}  /tmp/agy.tar.gz" | sha512sum -c -; \
    tar -xOzf /tmp/agy.tar.gz antigravity > /usr/local/bin/agy; \
    chmod 0555 /usr/local/bin/agy; rm /tmp/agy.tar.gz; \
    test "$(AGY_CLI_DISABLE_AUTO_UPDATE=true agy --version)" = 1.5.12

RUN install -d -m 1777 /opt/puzzlebench/ipc
COPY containers/agy/worker.py /opt/puzzlebench/agy-worker.py
COPY containers/agy/policy.py /opt/puzzlebench/agy-policy.py
COPY containers/agy/*.json /opt/puzzlebench/agy/config/
