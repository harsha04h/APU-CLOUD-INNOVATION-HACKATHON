import copy
import json
import random
import time
import paho.mqtt.client as mqtt
from config import *

rooms = {
    "R1": {"occupied": True,  "ac_on": True,  "temp": 24.0, "base_power": 1000},  # normal, in use
    "R2": {"occupied": False, "ac_on": False, "temp": 25.0, "base_power": 1000},  # booked, nobody came
    "R3": {"occupied": False, "ac_on": True,  "temp": 22.0, "base_power": 1000},  # empty, AC wasting energy
    "R4": {"occupied": True,  "ac_on": True,  "temp": 26.0, "base_power": 2600},  # faulty AC
    "R5": {"occupied": True,  "ac_on": True,  "temp": 24.0, "base_power": 1000},  # normal, in use
}
INITIAL = copy.deepcopy(rooms)


def on_connect(client, userdata, flags, reason_code, properties):
    print("Simulator connected:", reason_code)
    client.subscribe(f"{PREFIX}/room/+/command")
    client.subscribe(f"{PREFIX}/control/reset")


def on_message(client, userdata, msg):
    if msg.topic.endswith("/control/reset"):
        for rid, start in INITIAL.items():
            rooms[rid].update(start)
        print("Simulator reset to starting state")
        return
    room_id = msg.topic.split("/")[-2]
    command = msg.payload.decode()
    print(f"Command received for {room_id}: {command}")
    if room_id in rooms:
        if command == "ac_off":
            rooms[room_id]["ac_on"] = False
        elif command == "ac_on":
            rooms[room_id]["ac_on"] = True


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_start()

while True:
    for room_id, r in list(rooms.items()):
        if r["ac_on"]:
            if room_id == "R4":
                r["temp"] = min(36.0, r["temp"] + 0.1)   # fault: temperature keeps rising
            else:
                r["temp"] += (23.5 - r["temp"]) * 0.05
            power = r["base_power"] + random.randint(-80, 80)
        else:
            r["temp"] += (29.0 - r["temp"]) * 0.02
            power = random.randint(20, 40)

        payload = {
            "room": room_id,
            "occupied": r["occupied"],
            "ac_on": r["ac_on"],
            "temp": round(r["temp"], 1),
            "power_w": power,
            "ts": time.time(),
        }
        client.publish(f"{PREFIX}/room/{room_id}/telemetry", json.dumps(payload))
    time.sleep(2)