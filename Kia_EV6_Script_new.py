# -*- coding: utf-8 -*-
import json
import logging
import os
import sys
import time
import paho.mqtt.client as mqtt
from hyundai_kia_connect_api import *
from datetime import datetime, timedelta

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Config laden
config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'settings.json')
if not os.path.exists(config_path):
    logger.error("Kein Configfile gefunden.")
    sys.exit(-1)

with open(config_path) as f:
    config = json.load(f)

mqtt_topic = config['mqttbasetopic']
vehicle_id = config['apivehicleid']

def set_command_status(status):
    """Publiziert den Status 'pending' oder 'idle' via MQTT."""
    client.publish(f"{mqtt_topic}command", status, retain=True)
    logger.info(f"System-Status: {status}")

def process_api_response(response):
    """Extrahiert Status-Codes (z.B. 0000) aus der API-Antwort."""
    try:
        if response is None: return "Keine Antwort"
        if hasattr(response, '__dict__'): return json.dumps(vars(response), default=str)
        return str(response)
    except: return "Fehler beim Parsen der Antwort"

def update_and_publish(force_mode="auto"):
    """Holt alle EV6 Datenpunkte und publiziert sie."""
    global is_busy
    try:
        is_busy = True
        vm.check_and_refresh_token()
        
        api_res = vm.force_refresh_vehicle_state(vehicle_id) if force_mode == "force" else vm.check_and_force_update_vehicles(3598)
        
        if api_res:
            client.publish(f"{mqtt_topic}last_action_result", process_api_response(api_res))

        vehicle = vm.get_vehicle(vehicle_id)
        
        # --- ALLE DATENPUNKTE (VOLLSTÄNDIG) ---
        data_points = {
            "id": vehicle.id,
            "model": vehicle.model,
            "manufacturer": "Kia" if config['apibrand'] == 1 else "Hyundai",
            "odometer": vehicle.odometer,
            "ev_battery_percentage": vehicle.ev_battery_percentage,
            "car_battery_percentage": vehicle.car_battery_percentage,
            "driving_range": vehicle.ev_driving_range,
            "battery_charging": vehicle.ev_battery_is_charging,
            "battery_plugged_in": vehicle.ev_battery_is_plugged_in,
            "target_range_charge_AC": vehicle._ev_target_range_charge_AC,
            "target_range_charge_DC": vehicle._ev_target_range_charge_DC,
            "charge_limits_ac": vehicle.ev_charge_limits_ac,
            "charge_limits_dc": vehicle.ev_charge_limits_dc,
            "charging_power": vehicle.ev_charging_power,
            "current_charge_duration": vehicle._ev_estimated_current_charge_duration,
            "is_locked": vehicle.is_locked,
            "engine_running": vehicle.engine_is_running,
            "front_left_window_open": vehicle.front_left_window_is_open,
            "front_right_window_open": vehicle.front_right_window_is_open,
            "back_left_window_open": vehicle.back_left_window_is_open,
            "back_right_window_open": vehicle.back_right_window_is_open,
            "front_left_door_open": vehicle.front_left_door_is_open,
            "front_right_door_open": vehicle.front_right_door_is_open,
            "back_left_door_open": vehicle.back_left_door_is_open,
            "back_right_door_open": vehicle.back_right_door_is_open,
            "charge_port_door_open": vehicle.ev_charge_port_door_is_open,
            "trunk_open": vehicle.trunk_is_open,
            "hood_open": vehicle.hood_is_open,
            "air_temperature": vehicle.air_temperature,
            "air_control": vehicle.air_control_is_on,
            "defrost": vehicle.defrost_is_on,
            "steering_wheel_heater": vehicle.steering_wheel_heater_is_on,
            "back_window_heater": vehicle.back_window_heater_is_on,
            "location_latitude": vehicle.location_latitude,
            "location_longitude": vehicle.location_longitude,
            "smart_key_battery_warning": vehicle.smart_key_battery_warning_is_on,
            "washer_fluid_warning": vehicle.washer_fluid_warning_is_on,
            "brake_fluid_warning": vehicle.brake_fluid_warning_is_on,
            "tire_pressure_all_warning": vehicle.tire_pressure_all_warning_is_on,
            "tire_pressure_front_left_warning": vehicle.tire_pressure_front_left_warning_is_on,
            "tire_pressure_front_right_warning": vehicle.tire_pressure_front_right_warning_is_on,
            "tire_pressure_rear_left_warning": vehicle.tire_pressure_rear_left_warning_is_on,
            "tire_pressure_rear_right_warning": vehicle.tire_pressure_rear_right_warning_is_on
        }

        client.publish(f"{mqtt_topic}data", json.dumps(data_points), retain=True)
        logger.info("Daten erfolgreich publiziert.")
        
    except Exception as e:
        logger.error(f"Update Fehler: {str(e)}")
    finally:
        is_busy = False

def on_message(client, userdata, msg):    
    
    try:
        topic = msg.topic.replace(mqtt_topic, "")
        payload = msg.payload.decode("utf-8")
        response = None

        set_command_status("pending")

        if topic == "getAll":
            update_and_publish(force_mode="auto")
            set_command_status("idle")
        elif topic == "forceAll":
            update_and_publish(force_mode="force")
            set_command_status("idle")
        elif topic == "door":
            response = vm.lock(vehicle_id) if payload.lower() == "lock" else vm.unlock(vehicle_id)
            client.loop(5)
            time.sleep(30)
            set_command_status("idle")
        elif topic == "startClimate":
            try:
                params = json.loads(payload)
                response = vm.start_climate(vehicle_id, **params)
            except:
                response = vm.start_climate(vehicle_id, set_temp=float(payload))
            client.loop(5)
            time.sleep(30)
            set_command_status("idle")
        elif topic == "stopClimate":
            response = vm.stop_climate(vehicle_id)
            client.loop(5)
            time.sleep(30)
            set_command_status("idle")
        elif topic == "startCharge" or topic == "stopCharge":
            response = vm.start_charge(vehicle_id) if "start" in topic else vm.stop_charge(vehicle_id)
            client.loop(5)
            time.sleep(30)
            set_command_status("idle")
        elif topic == "charge_port":
            response = vm.open_charge_port(vehicle_id) if payload.lower() == "open" else vm.close_charge_port(vehicle_id)
            client.loop(5)
            time.sleep(30)
            set_command_status("idle")
        elif topic == "targetSoC":
            d = json.loads(payload)
            response = vm.set_charge_limits(vehicle_id, d['ac'], d['dc'])
            client.loop(5)
            time.sleep(30)
            set_command_status("idle")

        if response is not None:
            client.publish(f"{mqtt_topic}last_action_result", process_api_response(response))
            time.sleep(2)

    except Exception as e:
        logger.error(f"MQTT Fehler: {str(e)}")

# Initialisierung & Loop
vm = VehicleManager(region=config['apiregion'], brand=config['apibrand'], username=config['apiusername'],
                    password=config['apirefreshtoken'], pin=config['apipin'], language=config['apilanguage'])

client = mqtt.Client(config['mqttclientid'])
client.username_pw_set(config['mqttbrokeruser'], config['mqttbrokerpasswort'])

def on_connect(c, u, f, rc):
    c.subscribe(f"{mqtt_topic}set/#")
    c.publish(f"{mqtt_topic}LWT", "Online", retain=True)
    set_command_status("idle")

client.on_connect = on_connect
client.on_message = on_message
client.will_set(f"{mqtt_topic}LWT", "Offline", retain=True)
client.connect(config['mqttbrokerip'], config['mqttbrokerport'], 60)

# Hintergrund-Check fuer Idle-Status
client.loop_start()
while True:
    
    time.sleep(10)
