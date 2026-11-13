FROM node:24-bookworm-slim

ARG CODEX_VERSION=0.162.1
ARG CLAUDE_VERSION=2.1.257
ARG OPENCODE_VERSION=1.15.10

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 g++ make git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @openai/codex@${CODEX_VERSION} \
       @anthropic-ai/claude-code@${CLAUDE_VERSION} opencode-ai@${OPENCODE_VERSION} \
    && npm cache clean --force

COPY puzzlebench/proxy.py /opt/puzzlebench/proxy.py
RUN mkdir -p /workspace /bench /home/bench
ENV HOME=/home/bench PYTHONPATH=/bench PYTHONDONTWRITEBYTECODE=1 \
    NODE_USE_ENV_PROXY=1 NO_COLOR=1
WORKDIR /workspace
CMD ["sleep", "infinity"]
