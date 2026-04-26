# PawPal+ Model Card

> Rubric-aligned reflection on design decisions, AI scope, risks, and validation.

## Overview

PawPal+ is a hybrid system that combines:

- A fully deterministic pet-care scheduler for correctness-critical logic (task ordering, spacing, conflict prevention)
- A lightweight LLM used only for natural-language explanations

The scheduler handles execution logic, while the LLM summarizes coverage needs and provides behavior-aware pet-care insights.

This model card documents:

- How AI influenced design decisions
- What limitations and biases remain
- How correctness was verified

---

## How AI Influenced Design Decisions

### AI Suggestions Accepted

#### 1. Urgency scoring exploration
Early in development, I used the LLM to brainstorm tie-breaking strategies for tasks with identical priorities. Its suggestions helped me converge on a formula where priority dominates frequency and duration. I validated the final numbers manually, but the model accelerated the exploration phase.

#### 2. Natural-language coverage summaries
Once the scheduler became deterministic, the LLM's role shifted to interpretation. It now generates clear, personalized explanations of coverage windows and pet-care tips tailored to species, age group, and energy level.

### AI Suggestions Rejected

#### 1. Using an LLM as the scheduler
The model repeatedly proposed replacing the rule-based scheduler with an LLM that "reasons" about optimal plans. This was intentionally rejected. Deterministic scheduling is reproducible, testable, and safe; LLM-generated schedules are not.

#### 2. Dependency-movement suggestions
The LLM sometimes proposed moving the dependency task (for example, Feeding) instead of the dependent task (for example, Medication). This revealed that domain rules must be explicit; the model will not infer them reliably.

#### 3. Invented conflict scenarios
The LLM occasionally described overlaps or reversed medication order that the deterministic scheduler would never produce. This led to removing the LLM from the scheduling loop entirely and redesigning the demo pipeline to use real scheduler output.

### What Surprised Me

#### Ambiguity in task names across pets
When two pets had tasks with identical names ("Feeding"), the LLM's early repair suggestions exposed ambiguity in the internal data model. This led to requiring explicit `from_time` fields and clearer task identifiers, an improvement that persisted even after removing AI from scheduling.

---

## Biases and Limitations

### System Limitations

| Limitation | Current Behavior | Future Improvement |
| --- | --- | --- |
| Hardcoded breed database | The trie includes around 50 common breeds. Mixed breeds, rare breeds, and misspellings fall back to defaults silently. | Integrate a public breed API to expand coverage. |
| Generic medical heuristics | The 30-minute post-feeding gap and 10-minute medication gap are generic defaults. Different medical conditions may require different timing. | Allow per-task overrides or vet-provided parameters. |

### AI-Related Biases

| Risk | Description | Mitigation |
| --- | --- | --- |
| Behavioral generalization | Without profile context, the LLM produces generic advice (for example, "make sure your dog gets exercise"). | Include species, age group, and energy level in prompts. |
| Non-medical boundary confusion | The LLM is not allowed to generate medical advice, but users may still misinterpret suggestions as health guidance. | UI disclaimer and prompt guardrails. |

---

## Misuse Potential

Risk is low because:

- All safety-critical logic is deterministic.
- The LLM cannot modify schedules.
- Coverage windows are computed by rules, not AI.

The main misuse risk is that a user may interpret behavioral insights as veterinary advice. This is mitigated through disclaimers and prompt guardrails.

---

## Testing Strategy and Results

### Automated Tests

**Status:** 128 tests, all passing.

| Suite | Tests | Coverage Focus |
| --- | ---: | --- |
| `test_scheduler.py` | 36 | Urgency scoring, dependency ordering, gap enforcement, breed multipliers, time-window constraints |
| `test_agent.py` | 92 | Conflict detection (7 types), breed trie, multiplier constants, coverage window suggestions |

### Scenario-Based Evaluation

`eval_coverage.py` runs 19 predefined checks across 6 realistic scenarios, including:

- A control case where everything fits
- Cases with dropped tasks
- Cases with excessive gaps
- Multi-pet households
- Coverage window generation

**Result:** all scenarios pass.

---

## How Correctness Was Verified

- The scheduler is fully deterministic, so every output is reproducible.
- Each conflict type was formalized into explicit rules and validated with positive and negative fixtures.
- The LLM is not involved in scheduling, so correctness does not depend on AI behavior.
- Coverage windows are computed algorithmically and tested directly.

---

## Future Improvements

- Expand breed database via API integration.
- Add user-configurable medical timing overrides.
- Persist AI-generated summaries for weekly review.
- Add multi-caretaker scheduling with capability constraints.
- Introduce weekly and monthly scheduling horizons.
- Add RAG-grounded puppy-training curriculum support.