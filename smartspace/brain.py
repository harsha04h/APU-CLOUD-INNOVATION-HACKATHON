import json
import sqlite3
import time
import paho.mqtt.client as mqtt
from config import *

db = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=10)
db.execute("PRAGMA journal_mode=WAL")
db.execute("""CREATE TABLE IF NOT EXISTS rooms(
    room_id TEXT PRIMARY KEY, occupied INT, ac_on INT, temp REAL,
    power_w REAL, booking TEXT, status TEXT, updated REAL)""")
db.execute("""CREATE TABLE IF NOT EXISTS actions(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, room_id TEXT,
    action TEXT, reason TEXT, saved_wh REAL DEFAULT 0)""")
db.execute("CREATE TABLE IF NOT EXISTS control(key TEXT PRIMARY KEY, value REAL)")
# Start clean every time the brain starts
db.execute("DELETE FROM rooms")
db.execute("DELETE FROM actions")
db.execute("DELETE FROM control")
db.commit()

# Fake room bookings for today
BOOKINGS = {
    "R1": "Data Structures lecture",
    "R2": "Networking tutorial",
    "R5": "Group project meeting",
}


def fresh_state():
    return {
        r: {"empty_since": None, "ac_empty_since": None, "released": False,
            "ac_cmd_sent": False, "ac_saved": False, "fault_flagged": False, "history": []}
        for r in ROOMS
    }


state = fresh_state()
last_start = None


def get_demo_start():
    row = db.execute("SELECT value FROM control WHERE key='demo_start'").fetchone()
    return row[0] if row else None


def log_action(room_id, action, reason, saved_wh=0):
    db.execute(
        "INSERT INTO actions(ts, room_id, action, reason, saved_wh) VALUES (?,?,?,?,?)",
        (time.time(), room_id, action, reason, saved_wh),
    )
    db.commit()
    print(f"[{room_id}] {action}: {reason}")


def explain_fault(room_id, history):
    first_temp, last_temp = history[0][0], history[-1][0]
    last_power = history[-1][1]
    fallback = (f"Power draw is abnormally high ({last_power} W) while temperature keeps rising "
                f"({first_temp} -> {last_temp} C). Possible failing compressor or blocked airflow. "
                f"Please inspect the unit.")
    if not GEMINI_API_KEY:
        return fallback
    try:
        from google import genai
        gc = genai.Client(api_key=GEMINI_API_KEY)
        prompt = (
            "You are a building maintenance assistant. A normal air conditioner in a classroom "
            "draws about 900-1200 W and cools the room. Recent readings for room "
            f"{room_id} as (temperature C, power W), oldest first: {history}. "
            "In 2 short sentences, say what is abnormal, the most likely cause, and the "
            "recommended action. Do not claim certainty."
        )
        resp = gc.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return resp.text.strip()
    except Exception as e:
        print("Gemini error:", e)
        return fallback


def on_connect(client, userdata, flags, reason_code, properties):
    print("Brain connected:", reason_code)
    client.subscribe(f"{PREFIX}/room/+/telemetry")


def on_message(client, userdata, msg):
    global last_start
    d = json.loads(msg.payload)
    room_id = d["room"]
    if room_id not in state:
        return
    now = time.time()

    # Did someone press "Start demo" or reset the dashboard?
    demo_start = get_demo_start()
    if demo_start is None and last_start is not None:
        last_start = None
        state.clear()
        state.update(fresh_state())
        client.publish(f"{PREFIX}/control/reset", "1")
        print("Demo reset to READY state")
    elif demo_start is not None and demo_start != last_start:
        last_start = demo_start
        state.clear()
        state.update(fresh_state())
        db.execute("DELETE FROM actions")
        db.execute("INSERT OR REPLACE INTO control VALUES ('ack', ?)", (demo_start,))
        db.commit()
        client.publish(f"{PREFIX}/control/reset", "1")
        print("Demo (re)started")
    running = demo_start is not None

    s = state[room_id]

    if running:
        s["history"] = (s["history"] + [(d["temp"], d["power_w"])])[-6:]

        # Track how long the room has been empty
        if d["occupied"]:
            s["empty_since"] = None
            s["ac_empty_since"] = None
        else:
            if s["empty_since"] is None:
                s["empty_since"] = now
            if d["ac_on"]:
                if s["ac_empty_since"] is None:
                    s["ac_empty_since"] = now
            else:
                s["ac_empty_since"] = None

        # RULE 1: booked but nobody came -> release the booking
        if (room_id in BOOKINGS and not s["released"] and s["empty_since"]
                and now - s["empty_since"] >= NOSHOW_SECONDS):
            s["released"] = True
            log_action(room_id, "RELEASE_BOOKING",
                       f"'{BOOKINGS[room_id]}' was booked, but the room has been empty "
                       f"for {NOSHOW_SECONDS}s (demo time = 15 min). Room freed for others.")

        # RULE 2: empty room with AC on -> switch AC off
        if (d["ac_on"] and s["ac_empty_since"] and not s["ac_cmd_sent"]
                and now - s["ac_empty_since"] >= WASTE_SECONDS):
            client.publish(f"{PREFIX}/room/{room_id}/command", "ac_off")
            s["ac_cmd_sent"] = True
            s["ac_saved"] = True
            log_action(room_id, "AC_OFF",
                       f"Room empty while AC was running at {d['power_w']} W. "
                       f"Sent 'ac_off' command to the device.",
                       saved_wh=float(d["power_w"]))   # estimate: AC would have run 1 more hour
        if not d["ac_on"]:
            s["ac_cmd_sent"] = False

        # RULE 3: power too high and temperature rising -> possible fault, ask Gemini
        h = s["history"]
        if (not s["fault_flagged"] and now - demo_start >= FAULT_DELAY_SECONDS and len(h) >= 5
                and all(p > FAULT_POWER_W for _, p in h[-5:]) and h[-1][0] > h[-5][0]):
            s["fault_flagged"] = True
            explanation = explain_fault(room_id, h)
            log_action(room_id, "FAULT_ALERT", explanation)

    # Status label for the dashboard
    if s["fault_flagged"]:
        status = "Possible fault"
    elif s["released"]:
        status = "Booking released"
    elif d["occupied"]:
        status = "In use"
    elif s["ac_saved"]:
        status = "Saving energy"
    else:
        status = "Empty"

    booking = BOOKINGS.get(room_id, "")
    if s["released"]:
        booking += " (released)"

    db.execute("INSERT OR REPLACE INTO rooms VALUES (?,?,?,?,?,?,?,?)",
               (room_id, int(d["occupied"]), int(d["ac_on"]), d["temp"],
                d["power_w"], booking, status, now))
    db.commit()


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_forever()