import html
import sqlite3
import time

import pandas as pd
import streamlit as st

from config import *

import subprocess
import sys
import os
import streamlit as st

@st.cache_resource
def start_background_services():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    brain_path = os.path.join(base_dir, "brain.py")
    sim_path = os.path.join(base_dir, "simulator.py")
    
    # Start brain.py and simulator.py inside the cloud container
    subprocess.Popen([sys.executable, brain_path])
    subprocess.Popen([sys.executable, sim_path])
    return True

start_background_services()

st.set_page_config(page_title="Smart Space Orchestrator", page_icon="🏫", layout="wide")

if not hasattr(st, "fragment"):
    st.error("Please run: pip install -U streamlit (version 1.37 or newer is needed), then restart the dashboard.")
    st.stop()

# status -> (icon, main colour, light background, plain-English meaning)
STATUS = {
    "In use": ("🟢", "#15803d", "#dcfce7", "People are inside and the AC is working normally."),
    "Saving energy": ("💤", "#1d4ed8", "#dbeafe", "Empty room. The system switched the AC off to save power."),
    "Booking released": ("🔓", "#b45309", "#fef3c7", "Booked, but nobody came. The room was freed for others."),
    "Possible fault": ("🔴", "#b91c1c", "#fee2e2", "AC uses too much power and the room keeps heating up."),
    "Empty": ("⚪", "#475569", "#e2e8f0", "Room is empty. The system is watching it."),
}

ACTION = {
    "RELEASE_BOOKING": ("🔓", "Booking released", "#b45309"),
    "AC_OFF": ("💤", "AC switched off automatically", "#1d4ed8"),
    "FAULT_ALERT": ("🚨", "Possible AC fault detected", "#b91c1c"),
}

TIMELINE = sorted([
    (FAULT_DELAY_SECONDS, "🚨", "R4's air conditioner gets flagged as faulty"),
    (NOSHOW_SECONDS, "🔓", "R2's booking is released (nobody showed up)"),
    (WASTE_SECONDS, "💤", "R3's AC is switched off (empty room)"),
])
DEMO_LENGTH = max(t for t, _, _ in TIMELINE) + 10

st.markdown(
    """
<style>
#MainMenu, footer {visibility: hidden;}
.block-container {padding-top: 1.2rem; max-width: 1400px;}
.hero {background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); border-radius: 16px;
       padding: 22px 28px; margin-bottom: 18px;}
.hero-title {font-size: 1.9rem; font-weight: 800; color: #ffffff;}
.hero-sub {color: #cbd5e1; margin-top: 4px; font-size: 0.98rem;}
.kpi {background: #ffffff; border-radius: 12px; padding: 14px 18px; border-top: 4px solid #1e3a8a;
      box-shadow: 0 1px 6px rgba(0,0,0,0.15);}
.kpi-label {color: #64748b; font-size: 0.82rem; font-weight: 600; text-transform: uppercase;}
.kpi-value {font-size: 1.9rem; font-weight: 800; line-height: 1.2;}
.room-card {background: #ffffff; border-radius: 14px; padding: 16px; border-top: 6px solid;
            box-shadow: 0 2px 8px rgba(0,0,0,0.18); color: #0f172a; height: 100%;}
.room-head {display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;}
.room-id {font-size: 1.5rem; font-weight: 800;}
.badge {font-size: 0.78rem; font-weight: 700; padding: 4px 10px; border-radius: 999px;}
.room-desc {font-size: 0.82rem; color: #475569; min-height: 52px;}
.metrics {display: flex; justify-content: space-between; margin: 10px 0; padding: 10px 0;
          border-top: 1px solid #e2e8f0; border-bottom: 1px solid #e2e8f0;}
.m-val {font-size: 1.05rem; font-weight: 800;}
.m-lab {font-size: 0.7rem; color: #64748b; text-transform: uppercase;}
.room-foot {font-size: 0.82rem; color: #334155; line-height: 1.6;}
.event-banner {border-radius: 14px; padding: 16px 22px; margin-bottom: 16px; color: #ffffff;
               animation: pulse 1.2s ease-in-out infinite;}
.event-banner .tag {background: rgba(255,255,255,0.25); border-radius: 999px; padding: 2px 10px;
                    font-size: 0.75rem; font-weight: 800; margin-right: 8px;}
.event-banner .big {font-size: 1.3rem; font-weight: 800;}
.event-banner .small {font-size: 0.95rem; margin-top: 4px;}
@keyframes pulse {0% {opacity: 1;} 50% {opacity: 0.82;} 100% {opacity: 1;}}
.feed {background: #ffffff; border-radius: 12px; padding: 12px 16px; margin-bottom: 10px;
       border-left: 6px solid; box-shadow: 0 1px 5px rgba(0,0,0,0.15); color: #0f172a;}
.feed .top {font-weight: 800;}
.feed .time {font-size: 0.8rem; color: #64748b; font-weight: 500;}
.feed .why {font-size: 0.9rem; margin-top: 4px; color: #334155;}
.feed .new {background: #dc2626; color: #ffffff; font-size: 0.7rem; font-weight: 800;
            padding: 2px 8px; border-radius: 999px; margin-left: 6px;}
</style>
""",
    unsafe_allow_html=True,
)


def load():
    conn = sqlite3.connect(DB_FILE, timeout=10)
    try:
        rooms = pd.read_sql("SELECT * FROM rooms ORDER BY room_id", conn)
        actions = pd.read_sql("SELECT * FROM actions ORDER BY id DESC LIMIT 8", conn)
        saved = float(pd.read_sql("SELECT COALESCE(SUM(saved_wh),0) AS s FROM actions", conn)["s"][0])
        total = int(pd.read_sql("SELECT COUNT(*) AS n FROM actions", conn)["n"][0])
        ctl = dict(conn.execute("SELECT key, value FROM control").fetchall())
        return {"rooms": rooms, "actions": actions, "saved": saved, "total": total,
                "demo_start": ctl.get("demo_start"), "ack": ctl.get("ack")}
    except Exception:
        return None
    finally:
        conn.close()


def start_demo():
    """Clears the old run immediately, then tells the brain to start a new one."""
    conn = sqlite3.connect(DB_FILE, timeout=10)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS control(key TEXT PRIMARY KEY, value REAL)")
        for table in ("actions", "rooms"):
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass
        conn.execute("DELETE FROM control WHERE key='ack'")
        conn.execute("INSERT OR REPLACE INTO control VALUES ('demo_start', ?)", (time.time(),))
        conn.commit()
    finally:
        conn.close()


def on_press():
    start_demo()
    st.session_state.pressed = True
    st.session_state.last_id = 0


def pill(text, color):
    return (f'<span style="background:{color};color:#ffffff;font-weight:700;font-size:0.85rem;'
            f'padding:6px 14px;border-radius:999px">{text}</span>')


def kpi(label, value, color="#1e3a8a"):
    return (f'<div class="kpi" style="border-top-color:{color}"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value" style="color:{color}">{value}</div></div>')


# Button label: "Start" first, "Restart" once a demo has been started
# if "pressed" not in st.session_state:
    first = load()
    st.session_state.pressed = bool(first and first["demo_start"] is not None)

# Button label: always show "Start demo" for a fresh visitor session
if "pressed" not in st.session_state:
    st.session_state.pressed = False

# ---------- Sidebar ----------
with st.sidebar:
    st.header("📖 Demo guide")
    st.write("Press **Start demo**, then watch for:")
    for t, icon, text in TIMELINE:
        st.write(f"**{t} s** {icon} {text}")
    st.caption("Demo seconds stand for real minutes.")
    st.divider()
    st.caption("All sensor data is simulated.")

# ---------- Header (static) ----------
st.markdown(
    '<div class="hero"><div class="hero-title">🏫 Smart Space Orchestrator</div>'
    '<div class="hero-sub">An automatic campus building assistant that saves energy, '
    'frees unused rooms and catches faults early.</div></div>',
    unsafe_allow_html=True,
)


@st.fragment(run_every=2)
def status_panel():
    d = load()
    if d is None:
        st.markdown(pill("● WAITING FOR BRAIN", "#64748b"), unsafe_allow_html=True)
        st.caption("Make sure brain.py and simulator.py are running in the same folder as this dashboard.")
        return
    ds = d["demo_start"]
    if ds is None:
        st.markdown(pill("● READY - PRESS START", "#d97706"), unsafe_allow_html=True)
        st.caption("Press the button. The events will then happen one by one so you can watch them.")
    else:
        elapsed = time.time() - ds
        st.markdown(pill("● DEMO RUNNING", "#16a34a"), unsafe_allow_html=True)
        st.progress(min(elapsed / DEMO_LENGTH, 1.0), text=f"Demo running: {int(elapsed)} seconds")
        upcoming = [x for x in TIMELINE if x[0] > elapsed]
        if upcoming:
            st.caption(f"⏭ Next event in about {int(upcoming[0][0] - elapsed)} s: {upcoming[0][2]}")
        else:
            st.caption("✅ All scheduled events have happened. Press Restart demo to replay.")
        if d["ack"] != ds and elapsed > 6:
            st.error("⚠️ The brain did not answer the button. Close ALL terminals, then start "
                     "brain.py, simulator.py and the dashboard again from the same folder.")
    if d["rooms"].empty:
        st.caption("Waiting for the sensors to report...")
    else:
        age = time.time() - float(d["rooms"]["updated"].max())
        if age > 8:
            st.error(f"⚠️ No sensor data for {int(age)} s. Is simulator.py running?")


c_btn, c_status = st.columns([1, 3])
with c_btn:
    st.button("🔄 Restart demo" if st.session_state.pressed else "▶ Start demo",
              type="primary", use_container_width=True, on_click=on_press)
with c_status:
    status_panel()

with st.expander("ℹ️ How does this work?", expanded=False):
    a, b, c = st.columns(3)
    a.markdown("**1. Sensors report**\n\nEach room sends its temperature, power use and whether anyone is inside.")
    b.markdown("**2. The system decides**\n\nSimple rules handle the clear cases. Gemini AI explains suspicious ones.")
    c.markdown("**3. Devices act**\n\nIt switches off wasted AC, frees empty bookings and alerts maintenance.")


@st.fragment(run_every=2)
def live():
    d = load()
    if d is None or d["rooms"].empty:
        st.info("Waiting for sensor data... (after pressing the button this takes a few seconds)")
        return
    rooms, actions = d["rooms"], d["actions"]
    saved_wh, total_actions = d["saved"], d["total"]

    # ---------- Pop-up notifications (toasts) ----------
    max_id = int(actions["id"].max()) if not actions.empty else 0
    if "last_id" not in st.session_state:
        st.session_state.last_id = max_id
    else:
        if max_id < st.session_state.last_id:
            st.session_state.last_id = 0
        for _, a in actions.sort_values("id").iterrows():
            if int(a["id"]) > st.session_state.last_id:
                icon, title, _ = ACTION.get(a["action"], ("•", a["action"], "#475569"))
                short = str(a["reason"])
                short = short if len(short) <= 110 else short[:107] + "..."
                st.toast(f"**{title} · Room {a['room_id']}**\n\n{short}", icon=icon)
        st.session_state.last_id = max(st.session_state.last_id, max_id)

    # ---------- Big "new event" banner ----------
    if not actions.empty:
        latest = actions.iloc[0]
        if time.time() - latest["ts"] < 15:
            icon, title, color = ACTION.get(latest["action"], ("•", latest["action"], "#475569"))
            st.markdown(
                "".join([
                    f'<div class="event-banner" style="background:{color}">',
                    f'<div class="big"><span class="tag">NEW EVENT</span>{icon} {title} · Room {html.escape(str(latest["room_id"]))}</div>',
                    f'<div class="small">{html.escape(str(latest["reason"]))}</div>',
                    '</div>',
                ]),
                unsafe_allow_html=True,
            )

    # ---------- Key numbers ----------
    faults = rooms[rooms["status"] == "Possible fault"]
    k1, k2, k3, k4 = st.columns(4)
    k1.markdown(kpi("Rooms monitored", len(rooms)), unsafe_allow_html=True)
    k2.markdown(kpi("Rooms needing attention", len(faults), "#b91c1c" if len(faults) else "#15803d"), unsafe_allow_html=True)
    k3.markdown(kpi("Automatic actions", total_actions), unsafe_allow_html=True)
    k4.markdown(kpi("Energy saved (estimate)", f"{saved_wh / 1000:.2f} kWh", "#15803d"), unsafe_allow_html=True)

    st.write("")
    st.subheader("Live room status")
    cols = st.columns(len(rooms))
    for col, (_, r) in zip(cols, rooms.iterrows()):
        icon, color, bg, desc = STATUS.get(r["status"], STATUS["Empty"])
        booking = r["booking"] if isinstance(r["booking"], str) and r["booking"] else "No booking"
        power_color = "#b91c1c" if r["power_w"] > FAULT_POWER_W else "#0f172a"
        card = "".join([
            f'<div class="room-card" style="border-top-color:{color}">',
            f'<div class="room-head"><span class="room-id">{html.escape(str(r["room_id"]))}</span>',
            f'<span class="badge" style="background:{bg};color:{color}">{icon} {html.escape(str(r["status"]))}</span></div>',
            f'<div class="room-desc">{desc}</div>',
            '<div class="metrics">',
            f'<div><div class="m-val">{r["temp"]:.1f}°C</div><div class="m-lab">Temp</div></div>',
            f'<div><div class="m-val" style="color:{power_color}">{r["power_w"]:.0f} W</div><div class="m-lab">Power</div></div>',
            f'<div><div class="m-val">{"ON" if r["ac_on"] else "OFF"}</div><div class="m-lab">AC</div></div>',
            '</div>',
            f'<div class="room-foot">👥 {"Occupied" if r["occupied"] else "Empty"}<br>📅 {html.escape(booking)}</div>',
            '</div>',
        ])
        col.markdown(card, unsafe_allow_html=True)

    st.write("")
    left, right = st.columns([2, 3])

    with left:
        st.subheader("Power use per room")
        st.bar_chart(rooms.set_index("room_id")["power_w"])
        st.caption("About 1000 W is a normal AC. Above 2000 W is suspicious. About 30 W means the AC is off.")

    with right:
        st.subheader("What the system did")
        if actions.empty:
            st.write("Nothing yet. The system is watching...")
        for _, a in actions.iterrows():
            icon, title, color = ACTION.get(a["action"], ("•", a["action"], "#475569"))
            t = time.strftime("%H:%M:%S", time.localtime(a["ts"]))
            new_tag = '<span class="new">NEW</span>' if time.time() - a["ts"] < 15 else ""
            st.markdown(
                "".join([
                    f'<div class="feed" style="border-left-color:{color}">',
                    f'<div class="top">{icon} {title} · Room {html.escape(str(a["room_id"]))}',
                    f' <span class="time">at {t}</span>{new_tag}</div>',
                    f'<div class="why">{html.escape(str(a["reason"]))}</div>',
                    '</div>',
                ]),
                unsafe_allow_html=True,
            )


live()