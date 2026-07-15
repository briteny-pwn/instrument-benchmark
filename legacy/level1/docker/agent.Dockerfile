FROM node:22-bookworm-slim

ARG CLAUDE_CODE_VERSION=2.1.123
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && useradd --create-home --uid 10001 agent
USER agent
WORKDIR /workspace
