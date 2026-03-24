# -*- coding: utf-8 -*-
import json
import logging
import os
import sys
import paho.mqtt.client as mqtt
from hyundai_kia_connect_api import *

# Logging Setup
logging.basicConfig(level=logging.INFO)
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

def process_api_response(response):
    """Wandelt API-Antworten in lesbare JSON-Strings um."""
    try:
        if response is None: return "Keine Antwort"
        if hasattr(response, '__dict__'): return json.dumps(vars(response), default=str)
        return _check_response_for_errors(str(response))
    except: return "Fehler beim Parsen der Antwort"

def update_and_publish(force_mode="auto"):
    """
    Holt Daten und publiziert alle verfuegbaren EV6 Datenpunkte.
    'auto' nutzt check_and_force_update_vehicles(3598).
    'force' nutzt force_refresh_vehicle_state.
    """
    try:
        vm.check_and_refresh_token()
        
        if force_mode == "force":
            logger.info("Erzwinge sofortiges Live-Update...")
            vm.force_refresh_vehicle_state(vehicle_id)
        else:
            logger.info("Pruefe Intervall (3598s) fuer Update...")
            vm.check_and_force_update_vehicles(3598)
        
        vehicle = vm.get_vehicle(vehicle_id)
        
        # Maximale Liste aller sinnvollen Datenpunkte
        data_points = {
            # --- Basis & Identifikation ---
            "id": vehicle.id,
            "model": vehicle.model,
            "manufacturer": "Kia" if config['apibrand'] == 1 else "Hyundai",
            "odometer": vehicle.odometer,
            
            # --- Energie & Laden (EV Spezifisch) ---
            "ev_battery_percentage": vehicle.ev_battery_percentage,
            "car_battery_percentage": vehicle.car_battery_percentage, # 12V Batterie
            "driving_range": vehicle.ev_driving_range,
            "battery_is_charging": vehicle.ev_battery_is_charging,
            "battery_is_plugged_in": vehicle.ev_battery_is_plugged_in,
            "target_range_charge_AC": vehicle._ev_target_range_charge_AC,
            "target_range_charge_DC": vehicle._ev_target_range_charge_DC,
            "charge_limits_ac": vehicle.ev_charge_limits_ac,
            "charge_limits_dc": vehicle.ev_charge_limits_dc,
            "charging_power": vehicle.ev_charging_power,
            "current_charge_duration": vehicle._ev_estimated_current_charge_duration,
            
            # --- Fahrzeugstatus ---
            "is_locked": vehicle.is_locked,
            "engine_is_running": vehicle.engine_is_running,
            "front_left_window_is_open": vehicle.front_left_window_is_open,
            "front_right_window_is_open": vehicle.front_right_window_is_open,
            "back_left_window_is_open": vehicle.back_left_window_is_open,
            "back_right_window_is_open": vehicle.back_right_window_is_open,
            "front_left_door_is_open": vehicle.front_left_door_is_open,
            "front_right_door_is_open": vehicle.front_right_door_is_open,
            "back_left_door_is_open": vehicle.back_left_door_is_open,
            "back_right_door_is_open": vehicle.back_right_door_is_open,
            "charge_port_door_is_open": vehicle.ev_charge_port_door_is_open,
            "trunk_is_open": vehicle.trunk_is_open,
            "hood_is_open": vehicle.hood_is_open,
            
            # --- Klima & Komfort ---
            "air_temperature": vehicle.air_temperature,
            "air_control_is_on": vehicle.air_control_is_on,
            "defrost_is_on": vehicle.defrost_is_on,
            "steering_wheel_heater_is_on": vehicle.steering_wheel_heater_is_on,
            "back_window_heater_is_on": vehicle.back_window_heater_is_on,
            
            # --- Position & Sicherheit ---
            "location_latitude": vehicle.location_latitude,
            "location_longitude": vehicle.location_longitude,
            "smart_key_battery_warning_is_on": vehicle.smart_key_battery_warning_is_on,
            "washer_fluid_warning_is_on": vehicle.washer_fluid_warning_is_on,
            "brake_fluid_warning_is_on": vehicle.brake_fluid_warning_is_on,
            
            # --- Reifen (TPMS) ---
            "tire_pressure_all_warning_is_on": vehicle.tire_pressure_all_warning_is_on,
            "tire_pressure_front_left_warning_is_on": vehicle.tire_pressure_front_left_warning_is_on,
            "tire_pressure_front_right_warning_is_on": vehicle.tire_pressure_front_right_warning_is_on,
            "tire_pressure_rear_left_warning_is_on": vehicle.tire_pressure_rear_left_warning_is_on,
            "tire_pressure_rear_right_warning_is_on": vehicle.tire_pressure_rear_right_warning_is_on,

            # --- Script Status ---
            "command_status": "idle"
        }

        for key, value in data_points.items():
            client.publish(f"{mqtt_topic}{key}", str(value), retain=True)
            
        logger.info("Update abgeschlossen.")
        
    except Exception as e:
        logger.error(f"Update Fehler: {e}")
        client.publish(f"{mqtt_topic}lastScriptError", str(e))

def on_message(client, userdata, msg):
    try:
        topic = msg.topic.replace(mqtt_topic, "")
        payload = msg.payload.decode("utf-8")
        response = None
        
        if topic in ["door", "startClimate", "stopClimate", "targetSoC", "startCharge", "stopCharge", "forceAll", "getAll", "charge_port"]:
            client.publish(f"{mqtt_topic}command_status", "pending")

        if topic == "getAll":
            update_and_publish(force_mode="auto")
        elif topic == "forceAll":
            update_and_publish(force_mode="force")
        elif topic == "door":
            response = vm.lock(vehicle_id) if payload == "lock" else vm.unlock(vehicle_id)
        elif topic == "startClimate":
            response = vm.start_climate(vehicle_id, ClimateRequestOptions(**json.loads(payload)))
        elif topic == "stopClimate":
            response = vm.stop_climate(vehicle_id)
        elif topic == "startCharge":
            response = vm.start_charge(vehicle_id)
        elif topic == "stopCharge":
            response = vm.stop_charge(vehicle_id)
        elif topic == "charge_port":
            response = vm.open_charge_port(vehicle_id) if payload == "open" else vm.close_charge_port(vehicle_id)
        elif topic == "targetSoC":
            d = json.loads(payload)
            response = vm.set_charge_limits(vehicle_id, d['ac'], d['dc'])

        if response is not None:
            client.publish(f"{mqtt_topic}last_action_result", process_api_response(response))
            update_and_publish(force_mode="auto")

    except Exception as e:
        logger.error(f"MQTT Fehler: {e}")
        client.publish(f"{mqtt_topic}command_status", "error")
        client.publish(f"{mqtt_topic}lastScriptError", str(e))

# Initialisierung
vm = VehicleManager(region=config['apiregion'], brand=config['apibrand'], username=config['apiusername'],
                    password=config['apirefreshtoken'], pin=config['apipin'], language=config['apilanguage'])

client = mqtt.Client(config['mqttclientid'])
client.username_pw_set(config['mqttbrokeruser'], config['mqttbrokerpasswort'])
client.on_connect = lambda c, u, f, rc: (c.subscribe(f"{mqtt_topic}#"), c.publish(f"{mqtt_topic}LWT", "Online", retain=True))
client.on_message = on_message
client.will_set(f"{mqtt_topic}LWT", "Offline", retain=True)

client.connect(config['mqttbrokerip'], config['mqttbrokerport'], 60)
client.loop_forever()
