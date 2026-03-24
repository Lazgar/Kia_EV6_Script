# -*- coding: utf-8 -*-
import json
import logging
import os
import sys
import time
import paho.mqtt.client as mqtt
from hyundai_kia_connect_api import *

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

is_busy = False

# Config laden
config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'settings.json')
with open(config_path) as f:
    config = json.load(f)

mqtt_topic = config['mqttbasetopic'] # Beispiel: "kia/ev6/"
vehicle_id = config['apivehicleid']

def set_command_status(status):
    """Publiziert den Status nur bei tatsaechlicher Aenderung."""
    if not hasattr(client, 'current_status') or client.current_status != status:
        client.publish(f"{mqtt_topic}command", status, retain=True)
        client.current_status = status
        logger.info(f"MQTT Status -> {status}")

def process_api_response(response):
    try:
        if response is None: return "Keine Antwort"
        if hasattr(response, '__dict__'): return json.dumps(vars(response), default=str)
        return str(response)
    except: return "Fehler beim Parsen"

def update_and_publish(force_mode="auto"):
    global is_busy
    if is_busy: return
    try:
        is_busy = True
        set_command_status("pending")
        
        vm.check_and_refresh_token()
        api_res = vm.force_refresh_vehicle_state(vehicle_id) if force_mode == "force" else vm.check_and_force_update_vehicles(3598)
        
        if api_res:
            client.publish(f"{mqtt_topic}last_action_result", process_api_response(api_res))

        vehicle = vm.get_vehicle(vehicle_id)
        data_points = {
            "ev_battery": vehicle.ev_battery_percentage,
            "odometer": vehicle.odometer,
            "range": vehicle.ev_driving_range,
            "is_locked": vehicle.is_locked,
            "last_updated": str(vehicle.last_updated_at)
            # ... hier die restlichen Punkte bei Bedarf ergaenzen
        }
        client.publish(f"{mqtt_topic}all_data", json.dumps(data_points), retain=True)
    except Exception as e:
        logger.error(f"Update Fehler: {str(e)}")
    finally:
        is_busy = False
        set_command_status("idle")

def on_message(client, userdata, msg):
    global is_busy
    
    # NUR reagieren wenn das Topic auf "/set/" endet (Filter gegen Eigen-Feedback)
    if "/set/" not in msg.topic:
        return

    if is_busy:
        logger.warning("System beschaeftigt. Befehl ignoriert.")
        return

    try:
        topic = msg.topic.split("/set/")[1] # Extrahiert den Befehlsnamen
        payload = msg.payload.decode("utf-8")
        response = None
        
        is_busy = True
        set_command_status("pending")

        if topic == "getAll":
            is_busy = False # update_and_publish hat eigenes Locking
            update_and_publish(force_mode="auto")
        elif topic == "forceAll":
            is_busy = False
            update_and_publish(force_mode="force")
        elif topic == "door":
            response = vm.lock(vehicle_id) if payload.lower() == "lock" else vm.unlock(vehicle_id)
        elif topic == "startClimate":
            try:
                params = json.loads(payload)
                response = vm.start_climate(vehicle_id, **params)
            except:
                response = vm.start_climate(vehicle_id, set_temp=float(payload))
        elif topic == "stopClimate":
            response = vm.stop_climate(vehicle_id)
        # ... weitere Befehle (Charge, Port etc.) analog ...

        if response is not None:
            client.publish(f"{mqtt_topic}last_action_result", process_api_response(response))
            time.sleep(2)
            is_busy = False
            update_and_publish(force_mode="auto")

    except Exception as e:
        logger.error(f"Fehler: {str(e)}")
    finally:
        is_busy = False
        set_command_status("idle")

# --- Init ---
vm = VehicleManager(region=config['apiregion'], brand=config['apibrand'], username=config['apiusername'],
                    password=config['apirefreshtoken'], pin=config['apipin'], language=config['apilanguage'])

client = mqtt.Client(config['mqttclientid'])
client.username_pw_set(config['mqttbrokeruser'], config['mqttbrokerpasswort'])

# WICHTIG: Wir abonnieren nur den "set" Pfad, um nicht auf eigene Nachrichten zu reagieren
def on_connect(c, u, f, rc):
    c.subscribe(f"{mqtt_topic}set/#")
    c.publish(f"{mqtt_topic}LWT", "Online", retain=True)
    set_command_status("idle")

client.on_connect = on_connect
client.on_message = on_message
client.will_set(f"{mqtt_topic}LWT", "Offline", retain=True)

client.connect(config['mqttbrokerip'], config['mqttbrokerport'], 60)
client.loop_forever()
