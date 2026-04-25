import streamlit as st
from datetime import time
from models import Task, TaskType, Owner, Pet, Scheduler, PET_TASK_DEFAULTS, TASK_EMOJI, PET_EMOJI
from persistence import save, load, save_exists, owner_to_dict
from conflict_detector import detect_conflicts
from agent import ScheduleAgent

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")
st.title("🐾 PawPal+")
st.caption("Daily pet care planner")

TASK_LABELS: dict[TaskType, str] = {tt: tt.value.capitalize() for tt in TaskType}
LABEL_TO_TYPE: dict[str, TaskType] = {v: k for k, v in TASK_LABELS.items()}
PET_TYPES = ["dog", "cat", "rabbit", "bird", "snake", "iguana", "fish", "other"]

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
    st.session_state["p0_name"] = "Mochi"
    st.session_state["p0_type"] = "dog"


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
            "name":  st.session_state.get(f"p{pid}_name", ""),
            "type":  st.session_state.get(f"p{pid}_type", "dog"),
            "tasks": tasks,
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
        st.session_state[f"p{pid}_name"] = p["name"]
        st.session_state[f"p{pid}_type"] = p["type"]
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
        )

    cur_type = st.session_state[f"p{pid}_type"]
    pet_defaults = [TASK_LABELS[tt] for tt in PET_TASK_DEFAULTS.get(cur_type, [TaskType.FEEDING])]
    st.multiselect(
        "Active tasks",
        options=list(TASK_LABELS.values()),
        default=pet_defaults,
        key=f"p{pid}_tasks",
    )

    selected = st.session_state.get(f"p{pid}_tasks", [])
    if selected:
        h1, h2, h3, h4 = st.columns([3, 2, 2, 2])
        with h2:
            st.caption("min")
        with h3:
            st.caption("times/day")
        with h4:
            st.caption("priority")
        for label in selected:
            tt = LABEL_TO_TYPE[label]
            defs = Task(tt)
            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
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
    st.session_state[f"p{nid}_name"] = ""
    st.session_state[f"p{nid}_type"] = "dog"
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
            pname = st.session_state.get(f"p{pid}_name") or "Pet"
            ptype = st.session_state[f"p{pid}_type"]
            selected = st.session_state.get(f"p{pid}_tasks", [])
            if not selected:
                continue

            pet = Pet(pname, ptype)
            feeding_task = None

            for label in selected:
                tt = LABEL_TO_TYPE[label]
                dur  = int(st.session_state[f"p{pid}_{label}_d"])
                freq = int(st.session_state[f"p{pid}_{label}_f"])
                pri  = int(st.session_state[f"p{pid}_{label}_p"])
                task = Task(tt, duration_minutes=dur, frequency=freq, priority=pri)
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
    if combined:
        for entry, pet_name in combined:
            tr = (f"{entry.start_time.strftime('%H:%M')} – "
                  f"{entry.end_time.strftime('%H:%M')}")
            emoji    = TASK_EMOJI.get(entry.task.task_type, "")
            pet_obj  = next((p for p in owner.pets if p.name == pet_name), None)
            pet_icon = PET_EMOJI.get(pet_obj.pet_type, "") if pet_obj else ""
            st.markdown(f"**{tr}** &nbsp; {emoji} {entry.task.name} &nbsp; {pet_icon} _{pet_name}_")
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

        st.divider()
        if st.button("Fix conflicts with AI", type="primary"):
            with st.spinner("AI agent is repairing the schedule..."):
                fixed_plans, history = ScheduleAgent().fix_schedule(
                    all_plans, owner, owner.pets
                )
            st.session_state["_fixed_plans"]   = fixed_plans
            st.session_state["_agent_history"] = history
    else:
        if "_fixed_plans" not in st.session_state:
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
    else:
        st.success(f"All conflicts resolved in {len(history)} iteration(s).")
