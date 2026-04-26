# PawPal+ Model Card

## System Overview

PawPal+ is a hybrid AI system that pairs a fully deterministic pet‑care scheduler with an LLM that provides natural‑language insight, context, and user guidance.  
Over the course of development, the system evolved from relying on the LLM for conflict repair to eliminating those conflicts entirely through rule‑based logic — a deliberate shift toward correctness, reproducibility, and testability.

The LLM now plays a higher‑value role: translating structured schedule output into personalized, behavior‑aware insights that help owners understand why the plan works and how to adapt it throughout the day.

**Intended use:** Personal, single-user daily pet care planning. Not a substitute for veterinary advice.

---

## Testing Results

**139 tests, all passing.**

```
pytest test_scheduler.py test_agent.py -v
139 passed in ~1.5s
```

| Suite | Tests | What it covers |
|---|---|---|
| `test_scheduler.py` | 36 | Scheduler behavior — urgency scoring, dependency ordering, gap enforcement, breed multipliers, time window constraints |
| `test_agent.py` | 103 | Conflict detection (7 types), agent fix parsing, breed trie, multiplier constants, coverage window suggestions |

The original fix_schedule() loop is no longer part of the production pipeline — all conflict types are now prevented by deterministic rules. The LLM is still exercised through the Streamlit UI, but its role is limited to generating explanations, summaries, and pet‑care insights rather than modifying the schedule itself.

What worked: Formalizing every conflict type into explicit rules made the scheduler fully testable. Positive/negative fixtures for each rule caught subtle logic errors and ensured the engine produces conflict‑free plans without relying on AI repair.

What changed: As the rule engine matured, the LLM’s repair role became unnecessary. This was a deliberate architectural improvement: correctness moved into deterministic logic, and the LLM shifted to interpretation and user‑facing guidance.

---

## Limitations and Biases

- **Breed data is hardcoded.** The trie covers 50 common breeds. Mixed breeds, rare breeds, and misspellings fall back to defaults silently. *Future: integrate a public breed API (e.g., The Dog API) to expand coverage and remove the hardcoded list.*

- **Hardcoded medical heuristics.** The 30‑minute post‑feeding gap and 10‑minute medication gap are generic defaults and may not apply to pets with specific conditions. *Future: expose these as per-task user-configurable parameters with a vet-provided override field.*

- **Insight generation is non‑medical.** The LLM provides behavioral and routine‑based suggestions, not veterinary advice. The disclaimer is surfaced in the UI; a future version could add a persistent banner. *Future: add a system-prompt guardrail that refuses to reframe behavioral tips as medical advice.*

- **No agent history persistence.** Explanations and insights are session‑only. *Future: append summaries to a local log file so owners can review past recommendations.*

- **Single‑user, no auth.** Anyone with the URL can edit the schedule. *Future: add a PIN or simple session token before deploying beyond localhost.*

---

## Misuse Potential

Risk is low — the scheduler enforces all safety‑critical constraints deterministically. The LLM’s insights are intentionally non‑medical and framed as general behavioral guidance. The primary misuse risk is a user interpreting insights as health advice. Mitigation: clear disclaimers and visible surfacing of any unresolved constraints.

---

## What Surprised Me During Testing


Tasks with identical names across pets (e.g., both pets have “Feeding”) required explicit disambiguation. This led to the requirement that all move actions include a from_time field. Although the LLM no longer performs moves, this insight improved the internal data model and reduced ambiguity in user‑facing explanations.

---

## AI Collaboration

**Helpful — shaping the urgency scoring formula**
Early in development, I used the LLM to explore tie‑breaking strategies for tasks with identical priorities. Its proposed formula helped surface the key requirement: the priority coefficient must dominate frequency and duration so that no combination of lower‑priority attributes can outrank a higher‑priority task. I validated the final numbers manually, but the model accelerated the exploration phase.

**Helpful — natural‑language insight generation (current role) ** 
As the scheduler became fully deterministic, the LLM’s role shifted from repairing conflicts to interpreting the schedule. It now generates daily pet‑care insights, behavioral context, and user‑friendly explanations of why the plan is structured the way it is. This keeps correctness in the rule engine while letting the AI enhance clarity, personalization, and user engagement.

**Flawed — LLM as a scheduler (intentionally rejected) ** 
The model repeatedly suggested replacing the rule‑based scheduler with an LLM that would “reason” about the optimal plan. This was discarded early. Deterministic scheduling is reproducible, testable, and safe; LLM‑generated schedules are not. This reinforced a core design principle: use algorithms for correctness, use AI for interpretation.

**Flawed — dependency‑movement suggestions ** 
In early prompts, the LLM sometimes proposed moving the dependency task (e.g., Feeding) instead of the dependent task (e.g., Medication). This highlighted that domain rules must be stated explicitly — the model will not infer them. These failures informed clearer constraints and ultimately contributed to removing the LLM from the scheduling loop entirely.

**Flawed — unrealistic conflict scenarios  **
The LLM often suggested demo cases (overlaps, reversed medication order) that the deterministic scheduler would never produce. This led to a redesign of the demo pipeline: instead of hand‑crafted conflicts, the system now uses real generate_all_plans() output, and the LLM focuses on explanation rather than repair. This also led to the ralization that the schedule fix that was originally the LLM's job was completely codable. 

