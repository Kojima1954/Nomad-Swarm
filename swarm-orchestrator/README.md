# swarm-orchestrator

**Conversational Swarm Intelligence (CSI) Orchestrator for Project N.O.M.A.D.**

A single Python 3.12+ async service that connects a local Matrix room to a
federated swarm of N.O.M.A.D. nodes via GoToSocial (ActivityPub).

---

## Overview

```
Local Matrix room (Conduit)
        │
        ▼
 TranscriptBuffer
        │  (timer / message count / !summarize)
        ▼
    Summarizer  ←── RAG context (Qdrant)
        │
        ▼
  SwarmSummary
        │
   ┌────┴────┐
   │         │
   ▼         ▼
Qdrant   Publisher ──► GoToSocial outbox ──► Adjacent Nodes
              ▲
              │
Subscriber ◄──┘
(polls GoToSocial inbox, decrypts, injects into Matrix room)
```

Each **round** goes through three phases:

| Phase | What happens |
|-------|-------------|
| **DISCUSS** | Chat accumulates in the transcript buffer. Inbound Swarm Signals from adjacent nodes are injected. |
| **SUMMARIZE** | The LLM distils the transcript (+ RAG context) into a `SwarmSummary`. |
| **PROPAGATE** | The summary is encrypted (X25519 / SealedBox) and posted via GoToSocial DMs to adjacent nodes. |

---

## Quick Start

### 1. Configuration

Copy `config/default.toml` to `/etc/orchestrator/config.toml` and fill in:

- `[node]` — unique ID for this instance
- `[matrix]` — Conduit credentials
- `[ollama]` — model name (default `llama3.1:8b`)
- `[gotosocial]` — API token for the node's ActivityPub actor
- `[crypto]` — paths for the auto-generated NaCl keypair

Copy `config/topology.example.toml` to `/etc/orchestrator/topology.toml` and
list all swarm nodes and their edges.

### 2. Run with Docker

```bash
docker build -t swarm-orchestrator .
docker run -d \
  -v /path/to/data:/data \
  -v /path/to/config:/etc/orchestrator:ro \
  --name swarm-orchestrator \
  swarm-orchestrator
```

### 3. Run locally (development)

```bash
cd swarm-orchestrator
pip install -e ".[dev]"
ORCHESTRATOR_CONFIG=config/default.toml python -m orchestrator.main
```

---

## Testing

```bash
pip install -e ".[dev]"
pytest
```

---

## Architecture

| Module | Purpose |
|--------|---------|
| `config.py` | Pydantic settings loaded from TOML |
| `models/summary.py` | `SwarmSummary` — JSON-LD schema |
| `models/topology.py` | `SwarmNode`, `Topology` |
| `matrix/client.py` | matrix-nio wrapper (login, sync, send) |
| `matrix/transcript.py` | Rolling message buffer with token counting |
| `llm/summarizer.py` | Two-pass Ollama summarization |
| `llm/prompts.py` | System/user prompt templates |
| `rag/store.py` | Qdrant embed + retrieve |
| `federation/crypto.py` | X25519 keygen, encrypt, decrypt |
| `federation/publisher.py` | Encrypt + post to GoToSocial |
| `federation/subscriber.py` | Poll + decrypt inbound summaries |
| `topology/manager.py` | Parse topology.toml, resolve neighbours |
| `rounds/controller.py` | Async state machine (DISCUSS→SUMMARIZE→PROPAGATE) |
| `main.py` | Dependency injection + run loop |

---

## Security

- All secrets (passwords, tokens, keys) come from config files or environment
  variables — nothing is hardcoded.
- NaCl `SealedBox` (X25519 + XSalsa20-Poly1305) is used for end-to-end
  encryption of summaries in transit over the Fediverse.
- The subscriber validates that every received summary originates from a
  known adjacent node before processing it.
- Private key files are created with mode `0600`.
