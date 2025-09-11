# Project Overview

This repository contains an experiment evaluating whether explicitly maintained structured state improves agentic LLM performance versus a vanilla ReAct-style baseline for a constrained vacation planning problem.

**Core Task:**  
Given (a) user weather preference, (b) fixed date span candidates (three optional departure/return windows), (c) a budget, and (d) a shortlist of destination cities, the agent must:
1. Inspect weather (qualitatively) across options.
2. Select one destination.
3. Find a valid flight + hotel pair within budget for the chosen span.
4. Book both (must provide both confirmations to count as success).
5. Avoid prohibited behaviors (retrying failed identical searches, mixing spans, booking multiple hotels/flights, inventing data).

---

## Quick Start

```bash
pip install -r requirements.txt
python -m src.agent.baseline_agent
# or
python -m src.agent.stateful_agent
```

---

## Architecture Summary

Two agent variants share the same tool layer and high-level objective but differ in memory design:

- Baseline Agent: Pure message-history (ReAct style). All “memory” is emergent in prior turns.
- Stateful Agent: Injects a serialized structured state object into every reasoning step; state is mutated deterministically before and after tool execution.

Execution graphs are built with LangGraph. Trials are orchestrated by `src/experiment.py`, which logs per-run JSONL metrics and full transcripts.

---

## Tools

| Tool | Purpose (Simplified) |
|------|-----------------------|
| Weather Tool | Day-wise temperature & precipitation for a location/date range |
| Flight Search | List flights for (from, to, departure, return) with USD prices |
| Flight Booking | Book chosen flight id over departure/return window |
| Hotel Search | List hotels (local currency nightly price + amenities) |
| Hotel Booking | Book a hotel id over check-in/check-out |
| Currency Conversion | Convert given amount between currencies |

Tools are invoked via model-generated tool calls (parallel disabled for predictable ordering).

---

## Agents

### Baseline Agent (`src/agent/baseline_agent.py`)
Flow:
1. System + user prompt seed conversation.
2. LLM turn predicts reasoning + (optional) tool calls.
3. If tool calls exist, a ToolNode executes them; tool results appended as messages.
4. Loop until the model stops calling tools.


### Stateful Agent (`src/agent/stateful_agent.py`)
Flow (graph nodes):
START → assistant → (if tool calls) pre_tool_update → tools → post_tool_update → assistant → … → END

Components:
1. Assistant prompt = static system instructions + serialized current state + sliced recent messages (last ~10).
2. pre_tool_update:
   - Parses pending tool calls.
   - Appends intent records with `result = null` into the correct span arrays.
   - Seeds weather summaries and sets `selected_city` when first commitment is implied.
3. tools: Executes each tool call.
4. post_tool_update:
   - Resolves tool outputs, filling `result` fields (e.g., first viable option or “No flights/hotels found” marker).
   - Writes booking confirmations into dedicated `flight_booking` / `hotel_booking`.
5. Assistant reasons with authoritative structured memory, decides next action or termination.

---

## Structured State Schema (Stateful Agent)

Core fields (see `State` / `GraphState` in `src/agent/stateful_agent.py`):
- `weather_checked`: map city → qualitative weather summary.
- `selected_city`: canonical chosen destination.
- `flights_01_08`, `flights_02_09`, `flights_03_10`: arrays of flight search attempt objects:
  - `{ destination, departure, return, id, result }`
- `hotels_01_08`, `hotels_02_09`, `hotels_03_10`: analogous arrays for hotel searches.
- `flight_booking`, `hotel_booking`: final booking confirmation objects (or null).

Semantics:
- A record with `result = null` = intent reserved; prevents silent duplicate issuance.
- A populated `result` = authoritative outcome (success list or explicit “No X found”).
- Span suffix (e.g., `_01_08`) enforces consistent pairing of flight & hotel attempts for that date window.
- Terminal success requires both booking objects non-null.


## Key Files & References

- Prompts & Constraints: `src/agent/prompts.py`
- Baseline Agent: `src/agent/baseline_agent.py`
- Stateful Agent: `src/agent/stateful_agent.py`
- Experiment Orchestrator: `src/experiment.py`
- Tools: `src/tools/*.py`
- Logs (metrics + transcripts): `logs/`

---

## What We Measure

- Task completion success
- Token efficiency
- Tool usage patterns (redundancy or discipline)

---