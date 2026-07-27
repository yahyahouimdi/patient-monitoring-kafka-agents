# Track A -- Tier 2 Reasoning Layer

## Structure

```
TrackA/
├── shared/                  # Framework-agnostic. Never imports from *_impl/.
│   ├── config.py            # All env-driven settings (Kafka, Ollama, retrieval)
│   ├── schemas.py           # PatientState, ReasoningResult, NetworkRequest
│   ├── rules.py             # Severity thresholds -- single source of truth,
│   │                         # must match tier1_agent.py's evaluate()
│   ├── gate.py               # should_reason_about() -- decides when to call the LLM
│   ├── retrieval_client.py  # Calls Track B's POST /search (stub fallback)
│   ├── reasoning_client.py  # The ONLY module that calls an LLM (Ollama)
│   ├── guardrail.py         # Never lets the LLM downgrade below the rule table
│   └── emission.py          # Builds + publishes the network-request artifact
│
├── langgraph_impl/          # Phase 1 candidate #1. One prototype subfolder
│   └── graph.py             # per candidate -- add crewai_impl/, autogen_impl/,
│                             # swarm_impl/ the same way for the comparison matrix.
│
└── tier2_agent.py           # Kafka consumer entrypoint. update_state() and
                              # main() never change. should_reason_about() and
                              # reason_about() delegate to shared/ + the chosen
                              # *_impl/ package.
```

## Rule for adding a new framework candidate (Phase 1)

Per the reference architecture this mirrors: **no framework implementation
imports from another.** Every `*_impl/` package may only import from
`shared/`. To benchmark CrewAI, for example:

1. Create `crewai_impl/crew.py` with a `run_pipeline(patient_id, merged_state, producer=None)`
   function with the same signature as `langgraph_impl/graph.py`'s.
2. Build it out of the same `shared/gate.py`, `shared/retrieval_client.py`,
   `shared/reasoning_client.py`, `shared/guardrail.py`, `shared/emission.py`
   calls -- do not duplicate that logic inside `crewai_impl/`.
3. In `tier2_agent.py`, swap the import line:
   `from crewai_impl.crew import run_pipeline`
4. Nothing else in `tier2_agent.py`, or anywhere in `shared/`, changes.

This is what makes the Phase 1 comparison fair: every candidate reasons
over identical inputs, with identical gating/guardrail/emission logic --
the only variable is how each framework orchestrates the
retrieval -> reasoning -> mapping -> emission sequence.

## Running

```bash
pip install kafka-python requests langgraph --break-system-packages
python tier2_agent.py
```

Requires Kafka running (see repo root `docker-compose.yml`) and Ollama
running locally with `qwen2.5:3b` pulled. Track B's retrieval service is
optional -- `shared/retrieval_client.py` falls back to an obvious stub
if `RETRIEVAL_SERVICE_URL` is unreachable.
