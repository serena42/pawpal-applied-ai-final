import streamlit as st
from datetime import time
from models import (
    Task, TaskType, Owner, Pet, Scheduler,
    PET_TASK_DEFAULTS, TASK_EMOJI, PET_EMOJI,
    ENERGY_DURATION_MULT, ENERGY_FREQUENCY_MULT,
    AGE_DURATION_MULT, AGE_FREQUENCY_MULT, AGE_FEEDING_FREQUENCY_MULT,
    ACTIVITY_TASKS,
)
from persistence import save, load, save_exists, owner_to_dict
from conflict_detector import detect_conflicts, detect_suggested_slots, recommend_service, suggest_coverage_windows
from agent import ScheduleAgent
from breed_db import get_trie

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")
st.title("🐾 PawPal+")
st.caption("Daily pet care planner")

TASK_LABELS: dict[TaskType, str] = {tt: tt.value.capitalize() for tt in TaskType}
LABEL_TO_TYPE: dict[str, TaskType] = {v: k for k, v in TASK_LABELS.items()}
PET_TYPES = ["dog", "cat", "rabbit", "bird", "snake", "iguana", "fish", "other"]
_ENERGY_OPTS = ["low", "medium", "high", "very_high"]
_AGE_OPTS    = ["puppy", "adult", "senior"]


def _apply_breed(pid: int, breed_map: dict) -> None:
    sel = st.session_state.get(f"p{pid}_breed_suggestion")
    if sel and sel in breed_map:
        st.session_state[f"p{pid}_energy_level"] = breed_map[sel]["energy_level"]


def _reset_tasks_for_type(pid: int) -> None:
    """Called when pet type selectbox changes — resets task list to type-appropriate defaults."""
    new_type = st.session_state.get(f"p{pid}_type", "dog")
    st.session_state[f"p{pid}_tasks"] = [
        TASK_LABELS[tt] for tt in PET_TASK_DEFAULTS.get(new_type, [TaskType.FEEDING])
    ]

# ---------------------------------------------------------------------------
# Session state bootstrap (runs once per browser session)
# ---------------------------------------------------------------------------
if "win_ids" not in st.session_state:
    st.session_state.win_ids = [0]
    st.session_state.next_win_id = 1
    st.session_state["w0_start"] = time(8, 0)
    st.session_state["w0_end"] = time(18, 0)

if "pet_ids" not in st.session_state:
    st.session_state.pet_ids = [0]
    st.session_state.next_pet_id = 1
    st.session_state["p0_name"]         = "Mochi"
    st.session_state["p0_type"]         = "dog"
    st.session_state["p0_energy_level"] = "medium"
    st.session_state["p0_age_group"]    = "adult"


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _session_to_dict() -> dict:
    """Capture current session state as a JSON-serializable dict."""
    windows = [
        {
            "start": st.session_state[f"w{wid}_start"].strftime("%H:%M"),
            "end":   st.session_state[f"w{wid}_end"].strftime("%H:%M"),
        }
        for wid in st.session_state.win_ids
    ]
    pets = []
    for pid in st.session_state.pet_ids:
        tasks = [
            {
                "task_type":        LABEL_TO_TYPE[label].value,
                "duration_minutes": int(st.session_state.get(f"p{pid}_{label}_d", 15)),
                "frequency":        int(st.session_state.get(f"p{pid}_{label}_f", 1)),
                "priority":         int(st.session_state.get(f"p{pid}_{label}_p", 1)),
                "completed":        False,
            }
            for label in st.session_state.get(f"p{pid}_tasks", [])
        ]
        pets.append({
            "name":         st.session_state.get(f"p{pid}_name", ""),
            "type":         st.session_state.get(f"p{pid}_type", "dog"),
            "breed":        st.session_state.get(f"p{pid}_breed", ""),
            "energy_level": st.session_state.get(f"p{pid}_energy_level", "medium"),
            "age_group":    st.session_state.get(f"p{pid}_age_group", "adult"),
            "tasks":        tasks,
        })
    return {
        "owner_name": st.session_state.get("owner_name", ""),
        "windows":    windows,
        "pets":       pets,
    }


def _dict_to_session(data: dict) -> None:
    """Restore session state from a previously saved dict."""
    st.session_state.owner_name = data["owner_name"]

    st.session_state.win_ids = []
    st.session_state.next_win_id = 0
    for w in data["windows"]:
        wid = st.session_state.next_win_id
        st.session_state.win_ids.append(wid)
        h, m = map(int, w["start"].split(":"))
        st.session_state[f"w{wid}_start"] = time(h, m)
        h2, m2 = map(int, w["end"].split(":"))
        st.session_state[f"w{wid}_end"] = time(h2, m2)
        st.session_state.next_win_id += 1

    st.session_state.pet_ids = []
    st.session_state.next_pet_id = 0
    for p in data["pets"]:
        pid = st.session_state.next_pet_id
        st.session_state.pet_ids.append(pid)
        st.session_state[f"p{pid}_name"]         = p["name"]
        st.session_state[f"p{pid}_type"]         = p["type"]
        st.session_state[f"p{pid}_breed"]        = p.get("breed", "")
        st.session_state[f"p{pid}_energy_level"] = p.get("energy_level", "medium")
        st.session_state[f"p{pid}_age_group"]    = p.get("age_group", "adult")
        labels = [TASK_LABELS[TaskType(td["task_type"])] for td in p["tasks"]]
        st.session_state[f"p{pid}_tasks"] = labels
        for td in p["tasks"]:
            label = TASK_LABELS[TaskType(td["task_type"])]
            st.session_state[f"p{pid}_{label}_d"] = td["duration_minutes"]
            st.session_state[f"p{pid}_{label}_f"] = td["frequency"]
            st.session_state[f"p{pid}_{label}_p"] = td["priority"]
        st.session_state.next_pet_id += 1


# ---------------------------------------------------------------------------
# Sidebar: save / load
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Save / Load")
    if st.button("Save settings", use_container_width=True):
        save(_session_to_dict())
        st.success("Settings saved.")
    if save_exists():
        if st.button("Load settings", use_container_width=True):
            _dict_to_session(load())
            st.rerun()
    else:
        st.caption("No saved settings yet.")


# ---------------------------------------------------------------------------
# Section 1: Owner
# ---------------------------------------------------------------------------
st.header("Owner")
st.text_input("Your name", value="Jordan", key="owner_name")

st.subheader("Availability windows")
win_to_remove = None
for wid in st.session_state.win_ids:
    c1, c2, c3 = st.columns([5, 5, 2])
    with c1:
        st.time_input("From", key=f"w{wid}_start")
    with c2:
        st.time_input("Until", key=f"w{wid}_end")
    with c3:
        st.write("")
        if len(st.session_state.win_ids) > 1 and st.button("Remove", key=f"w{wid}_rm"):
            win_to_remove = wid

if win_to_remove is not None:
    st.session_state.win_ids.remove(win_to_remove)
    st.rerun()

if st.button("+ Add time block"):
    nid = st.session_state.next_win_id
    st.session_state.win_ids.append(nid)
    st.session_state[f"w{nid}_start"] = time(8, 0)
    st.session_state[f"w{nid}_end"] = time(18, 0)
    st.session_state.next_win_id += 1
    st.rerun()

# ---------------------------------------------------------------------------
# Section 2 & 3: Pets + Tasks
# ---------------------------------------------------------------------------
st.header("Pets")
pet_to_remove = None

for pid in st.session_state.pet_ids:
    cur_name = st.session_state.get(f"p{pid}_name") or "New Pet"
    cur_type = st.session_state.get(f"p{pid}_type", "dog")
    pet_icon = PET_EMOJI.get(cur_type, "🐾")
    st.subheader(f"{pet_icon} {cur_name}")

    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Name", key=f"p{pid}_name")
    with c2:
        st.selectbox(
            "Type", PET_TYPES,
            index=PET_TYPES.index(cur_type) if cur_type in PET_TYPES else 0,
            key=f"p{pid}_type",
            on_change=_reset_tasks_for_type,
            args=(pid,),
        )

    cur_type = st.session_state[f"p{pid}_type"]

    # Ensure energy/age keys exist before widgets render them
    if f"p{pid}_energy_level" not in st.session_state:
        st.session_state[f"p{pid}_energy_level"] = "medium"
    if f"p{pid}_age_group" not in st.session_state:
        st.session_state[f"p{pid}_age_group"] = "adult"

    # Breed search + energy level + age group
    bc1, bc2, bc3 = st.columns([4, 3, 3])
    with bc1:
        st.text_input("Breed (optional)", key=f"p{pid}_breed",
                      placeholder="e.g. Labrador Retriever")
    with bc2:
        st.selectbox("Energy level", _ENERGY_OPTS, key=f"p{pid}_energy_level")
    with bc3:
        st.selectbox("Age group", _AGE_OPTS, key=f"p{pid}_age_group")

    _breed_val = st.session_state.get(f"p{pid}_breed", "")
    if len(_breed_val) >= 2:
        _matches = get_trie().search(_breed_val)
        if _matches:
            _breed_map = {b["name"]: b for b in _matches}
            st.selectbox(
                "Breed suggestion",
                options=list(_breed_map.keys()),
                key=f"p{pid}_breed_suggestion",
                on_change=_apply_breed,
                args=(pid, _breed_map),
            )

    pet_defaults = [TASK_LABELS[tt] for tt in PET_TASK_DEFAULTS.get(cur_type, [TaskType.FEEDING])]
    st.multiselect(
        "Active tasks",
        options=list(TASK_LABELS.values()),
        default=pet_defaults,
        key=f"p{pid}_tasks",
    )

    selected = st.session_state.get(f"p{pid}_tasks", [])
    if selected:
        h1, h2, h3, h4, h5 = st.columns([3, 2, 2, 2, 3])
        with h2:
            st.caption("min")
        with h3:
            st.caption("times/day")
        with h4:
            st.caption("priority")
        with h5:
            st.caption("time window (optional)")
        for label in selected:
            tt = LABEL_TO_TYPE[label]
            defs = Task(tt)
            c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 3])
            with c1:
                st.markdown(f"**{label}**")
            with c2:
                st.number_input(
                    "min", 1, 240, defs.duration_minutes,
                    label_visibility="collapsed", key=f"p{pid}_{label}_d",
                )
            with c3:
                st.number_input(
                    "times/day", 1, 10, defs.frequency,
                    label_visibility="collapsed", key=f"p{pid}_{label}_f",
                )
            with c4:
                st.number_input(
                    "priority", 1, 5, defs.priority,
                    label_visibility="collapsed", key=f"p{pid}_{label}_p",
                )
            with c5:
                win_key = f"p{pid}_{label}_win"
                if win_key not in st.session_state:
                    st.session_state[win_key] = False
                use_win = st.checkbox("restrict", key=win_key, label_visibility="collapsed")
                if use_win:
                    wc1, wc2 = st.columns(2)
                    with wc1:
                        st.time_input(
                            "earliest", time(8, 0),
                            label_visibility="collapsed",
                            key=f"p{pid}_{label}_earliest",
                        )
                    with wc2:
                        st.time_input(
                            "latest", time(18, 0),
                            label_visibility="collapsed",
                            key=f"p{pid}_{label}_latest",
                        )

        if TaskType.MEDICATION in [LABEL_TO_TYPE[l] for l in selected] and \
           TaskType.FEEDING in [LABEL_TO_TYPE[l] for l in selected]:
            st.info("Medication will be scheduled after Feeding.")

    if len(st.session_state.pet_ids) > 1 and st.button("Remove this pet", key=f"p{pid}_rm"):
        pet_to_remove = pid

    if pid != st.session_state.pet_ids[-1]:
        st.divider()

if pet_to_remove is not None:
    st.session_state.pet_ids.remove(pet_to_remove)
    st.rerun()

if st.button("+ Add another pet"):
    nid = st.session_state.next_pet_id
    st.session_state.pet_ids.append(nid)
    st.session_state[f"p{nid}_name"]         = ""
    st.session_state[f"p{nid}_type"]         = "dog"
    st.session_state[f"p{nid}_energy_level"] = "medium"
    st.session_state[f"p{nid}_age_group"]    = "adult"
    st.session_state.next_pet_id += 1
    st.rerun()

# ---------------------------------------------------------------------------
# Section 4: Generate
# ---------------------------------------------------------------------------
st.divider()
if st.button("Generate daily plan", type="primary"):
    bad_windows = [
        wid for wid in st.session_state.win_ids
        if st.session_state[f"w{wid}_start"] >= st.session_state[f"w{wid}_end"]
    ]
    if bad_windows:
        st.error("Each time block must have a start time before its end time.")
    else:
        owner = Owner(st.session_state.owner_name)
        for wid in st.session_state.win_ids:
            owner.add_window(
                st.session_state[f"w{wid}_start"],
                st.session_state[f"w{wid}_end"],
            )

        for pid in st.session_state.pet_ids:
            pname        = st.session_state.get(f"p{pid}_name") or "Pet"
            ptype        = st.session_state[f"p{pid}_type"]
            energy_level = st.session_state.get(f"p{pid}_energy_level", "medium")
            age_group    = st.session_state.get(f"p{pid}_age_group", "adult")
            selected     = st.session_state.get(f"p{pid}_tasks", [])
            if not selected:
                continue

            e_dur  = ENERGY_DURATION_MULT.get(energy_level, 1.0)
            e_freq = ENERGY_FREQUENCY_MULT.get(energy_level, 1.0)
            a_dur  = AGE_DURATION_MULT.get(age_group, 1.0)
            a_freq = AGE_FREQUENCY_MULT.get(age_group, 1.0)

            pet = Pet(pname, ptype, energy_level=energy_level, age_group=age_group)
            feeding_task = None

            for label in selected:
                tt   = LABEL_TO_TYPE[label]
                dur  = int(st.session_state[f"p{pid}_{label}_d"])
                freq = int(st.session_state[f"p{pid}_{label}_f"])
                pri  = int(st.session_state[f"p{pid}_{label}_p"])
                if tt in ACTIVITY_TASKS:
                    dur  = max(1, round(dur  * e_dur * a_dur))
                    freq = max(1, round(freq * e_freq * a_freq))
                elif tt == TaskType.FEEDING:
                    freq = max(1, round(freq * AGE_FEEDING_FREQUENCY_MULT.get(age_group, 1.0)))
                earliest = latest = None
                if st.session_state.get(f"p{pid}_{label}_win"):
                    earliest = st.session_state.get(f"p{pid}_{label}_earliest")
                    latest   = st.session_state.get(f"p{pid}_{label}_latest")
                task = Task(tt, duration_minutes=dur, frequency=freq, priority=pri,
                            earliest=earliest, latest=latest)
                if tt == TaskType.FEEDING:
                    feeding_task = task
                pet.add_task(task)

            if feeding_task:
                for task in pet.tasks:
                    if task.task_type == TaskType.MEDICATION:
                        task.dependencies = [feeding_task]

            owner.add_pet(pet)

        if not owner.pets:
            st.warning("Select at least one task before generating a plan.")
        else:
            scheduler = Scheduler(owner, owner.pets[0])
            all_plans = scheduler.generate_all_plans()
            # Store in session state so display persists across reruns.
            st.session_state["_plans"] = all_plans
            st.session_state["_owner"] = owner
            st.session_state.pop("_fixed_plans", None)
            st.session_state.pop("_agent_history", None)

# ---------------------------------------------------------------------------
# Schedule display + conflict detection (reads from session state)
# ---------------------------------------------------------------------------
CONFLICT_ICONS = {
    "overlap": "🔴", "dependency": "🟠", "gap": "🟡",
    "timeout": "🟣", "outside_window": "⚪",
    "post_feeding_gap": "🟧", "med_feeding_gap": "🟦", "window_violation": "🔷",
}

if "_plans" in st.session_state:
    all_plans = st.session_state["_plans"]
    owner     = st.session_state["_owner"]

    # Warnings per pet
    for pet_name, plan in all_plans.items():
        for w in plan.warnings:
            p_obj = next((p for p in owner.pets if p.name == pet_name), None)
            p_icon = PET_EMOJI.get(p_obj.pet_type, "") if p_obj else ""
            st.warning(f"{p_icon} **{pet_name}:** {w}")

    # Unified time-ordered schedule
    combined = sorted(
        [(entry, pet_name)
         for pet_name, plan in all_plans.items()
         for entry in plan.scheduled],
        key=lambda x: x[0].start_time,
    )
    st.header("Daily Schedule")
    suggested_slots = detect_suggested_slots(all_plans, owner.pets)

    if combined:
        for entry, pet_name in combined:
            tr = (f"{entry.start_time.strftime('%H:%M')} – "
                  f"{entry.end_time.strftime('%H:%M')}")
            emoji    = TASK_EMOJI.get(entry.task.task_type, "")
            pet_obj  = next((p for p in owner.pets if p.name == pet_name), None)
            pet_icon = PET_EMOJI.get(pet_obj.pet_type, "") if pet_obj else ""
            st.markdown(f"**{tr}** &nbsp; {emoji} {entry.task.name} &nbsp; {pet_icon} _{pet_name}_")

            # After the last task before a suggested slot gap, insert the slot banner.
            entry_end_mins = entry.end_time.hour * 60 + entry.end_time.minute
            for slot in suggested_slots:
                if slot.pet_name == pet_name:
                    slot_earliest_mins = int(slot.earliest[:2]) * 60 + int(slot.earliest[3:])
                    slot_latest_mins   = int(slot.latest[:2])   * 60 + int(slot.latest[3:])
                    if slot_earliest_mins <= entry_end_mins <= slot_latest_mins:
                        st.info(
                            f"📅 **Suggested {slot.task_name} slot for {slot.pet_name}** &nbsp;|&nbsp; "
                            f"Earliest: **{slot.earliest}** &nbsp; Latest: **{slot.latest}** &nbsp; "
                            f"Recommended: **{slot.suggested}**  \n"
                            f"_{slot.reason}_"
                        )
    else:
        st.error("No tasks could be scheduled in the available time windows.")

    # Conflict detection
    conflicts = detect_conflicts(all_plans, owner, owner.pets)
    if conflicts:
        st.divider()
        st.subheader("Conflicts Detected")
        for c in conflicts:
            icon = CONFLICT_ICONS.get(c.conflict_type, "")
            st.error(f"{icon} **{c.conflict_type.upper()}** — {c.reason}")

        rec = recommend_service(conflicts)
        if rec:
            st.info(f"**Tip:** {rec}")

        st.divider()
        if st.button("Fix conflicts with AI", type="primary"):
            with st.spinner("AI agent is repairing the schedule..."):
                fixed_plans, history, coverage = ScheduleAgent().fix_schedule(
                    all_plans, owner, owner.pets
                )
            st.session_state["_fixed_plans"]   = fixed_plans
            st.session_state["_agent_history"] = history
            st.session_state["_coverage"]      = coverage
    else:
        if "_fixed_plans" not in st.session_state:
            has_plan_warnings = any(plan.warnings for plan in all_plans.values())
            if has_plan_warnings:
                st.info("No scheduling conflicts detected, but some tasks could not be fully scheduled — see warnings above.")
            else:
                st.success("No conflicts — schedule is valid.")

# ---------------------------------------------------------------------------
# AI-repaired schedule (displayed after agent runs)
# ---------------------------------------------------------------------------
if "_fixed_plans" in st.session_state:
    fixed_plans = st.session_state["_fixed_plans"]
    history     = st.session_state.get("_agent_history", [])
    owner       = st.session_state["_owner"]

    st.divider()
    st.header("AI-Repaired Schedule")

    with st.expander("Agent reasoning log"):
        for step in history:
            st.markdown(
                f"**Iteration {step['iteration'] + 1}** — "
                f"{step['conflicts_found']} conflict(s) found  \n"
                f"AI suggested: `{step['claude_suggestion']}`"
            )

    combined_fixed = sorted(
        [(sched, pet_name)
         for pet_name, plan in fixed_plans.items()
         for sched in plan.scheduled],
        key=lambda x: x[0].start_time,
    )
    for entry, pet_name in combined_fixed:
        tr = (f"{entry.start_time.strftime('%H:%M')} – "
              f"{entry.end_time.strftime('%H:%M')}")
        emoji    = TASK_EMOJI.get(entry.task.task_type, "")
        pet_obj  = next((p for p in owner.pets if p.name == pet_name), None)
        pet_icon = PET_EMOJI.get(pet_obj.pet_type, "") if pet_obj else ""
        st.markdown(f"**{tr}** &nbsp; {emoji} {entry.task.name} &nbsp; {pet_icon} _{pet_name}_")

    remaining = detect_conflicts(fixed_plans, owner, owner.pets)
    if remaining:
        st.warning(f"{len(remaining)} conflict(s) could not be fully resolved.")
        rec = recommend_service(remaining)
        if rec:
            st.info(f"**Recommendation:** {rec}")
    else:
        st.success(f"All conflicts resolved in {len(history)} iteration(s).")

    # Coverage window suggestions — specific time slots for external services.
    coverage = st.session_state.get("_coverage", [])
    if coverage:
        st.divider()
        st.subheader("Suggested Coverage Windows")
        st.caption(
            "These time slots would resolve gaps that can't be fixed by rescheduling alone. "
            "Add them as owner availability windows or book an external service."
        )
        SERVICE_ICON = {"dog_walker": "🦮", "pet_sitter": "🏠", "owner_window": "📅"}
        SERVICE_LABEL = {"dog_walker": "Dog walker", "pet_sitter": "Pet sitter", "owner_window": "Owner availability"}
        for cw in coverage:
            icon  = SERVICE_ICON.get(cw.service_type, "📋")
            label = SERVICE_LABEL.get(cw.service_type, cw.service_type.replace("_", " ").title())
            pet_obj  = next((p for p in owner.pets if p.name == cw.pet_name), None)
            pet_icon = PET_EMOJI.get(pet_obj.pet_type, "") if pet_obj else ""
            st.info(
                f"{icon} **{label}** &nbsp; {cw.start} – {cw.end} &nbsp; "
                f"{pet_icon} _{cw.pet_name}_"
                + (f" &nbsp; _(covers: {', '.join(cw.tasks)})_" if cw.tasks else "")
                + f"  \n{cw.reason}"
            )
