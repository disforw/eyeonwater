"""Constants for the Eye On Water integration."""
from datetime import timedelta

SCAN_INTERVAL = timedelta(minutes=60)
DEBOUNCE_COOLDOWN = 1800  # Seconds

DATA_COORDINATOR = "coordinator"
DATA_SMART_METER = "smart_meter_data"

DOMAIN = "eyeonwater"

WATER_METER = "Water Meter"
WATER_LEAK_SENSOR = "Water Leak Sensor"