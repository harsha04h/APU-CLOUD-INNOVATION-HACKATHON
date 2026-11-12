import os

BROKER = "broker.hivemq.com"   # free public MQTT broker, no signup
PORT = 1883
PREFIX = "apu-smartspace-CHANGE-ME-48213"   # keep the same unique prefix you used before
ROOMS = ["R1", "R2", "R3", "R4", "R5"]
DB_FILE = "smartspace.db"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-flash"

# All times are seconds AFTER you press "Start demo" (demo time compression)
FAULT_DELAY_SECONDS = 30    # R4 flagged as faulty
NOSHOW_SECONDS = 60         # R2 booking released (stands for 15 minutes)
WASTE_SECONDS = 90          # R3 AC switched off (stands for 15 minutes)
FAULT_POWER_W = 2000