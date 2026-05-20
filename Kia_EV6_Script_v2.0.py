# -*- coding: utf-8 -*-
import json
import logging
import os
import sys
import time
import paho.mqtt.client as mqtt
from hyundai_kia_connect_api import *
from hyundai_kia_connect_api.exceptions import (
    APIError,
    AuthenticationError,
    DuplicateRequestError,
    RequestTimeoutError,
    ServiceTemporaryUnavailable,
    NoDataFound,
    InvalidAPIResponseError,
    RateLimitingError,
    DeviceIDError
)
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
start_time = datetime.now()
last_stats_date = None

config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'settings.json')
if not os.path.exists(config_path):
    logger.error("Kein Configfile gefunden.")
    sys.exit(-1)

with open(config_path) as f:
    config = json.load(f)

mqtt_topic = config['mqttbasetopic']
vehicle_id = config['apivehicleid']
driving_history_days = config['drivinghistorydays']

def nonBlocking_sleep(sec):
    end_time = time.time() + sec
    while time.time() < end_time:
      time.sleep(1)

def get_uptime():
    """Berechnet die Laufzeit seit Skriptstart"""
    diff = datetime.now() - start_time
    days = diff.days
    # Formatiert hh:mm:ss aus den Sekunden (ohne Mikrosekunden)
    time_str = str(timedelta(seconds=diff.seconds))
    if days > 0:
        return f"{days} days, {time_str}"
    return time_str

def set_command_status(status):
    client.publish(f"{mqtt_topic}command", status, retain=True)
    client.loop(3)
    logger.info(f"System-Status: {status}")

def process_api_response(response):
    try:
        if response is None: return "Keine Antwort"
        if hasattr(response, '__dict__'): return json.dumps(vars(response), default=str)
        return str(response)
    except: return "Fehler beim Parsen der Antwort"

def update_and_publish(force_mode="auto"):
    try:
        vm.force_refresh_vehicle_state(vehicle_id) if force_mode == "force" else vm.check_and_force_update_vehicles(3598)
        vehicle = vm.get_vehicle(vehicle_id)

        data_points = {
            "id": vehicle.id,
            "script_uptime": get_uptime(),
            "model": vehicle.model,
            "manufacturer": "Kia" if config['apibrand'] == 1 else "Hyundai",
            "odometer": vehicle.odometer,
            "VIN": vehicle.VIN,
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
            "tire_pressure_rear_right_warning": vehicle.tire_pressure_rear_right_warning_is_on,
            "headlamp_status": vehicle.headlamp_status, 
            "headlamp_left_low": vehicle.headlamp_left_low, 
            "headlamp_right_low": vehicle.headlamp_right_low, 
            "stop_lamp_left": vehicle.stop_lamp_left, 
            "stop_lamp_right": vehicle.stop_lamp_right, 
            "turn_signal_left_front": vehicle.turn_signal_left_front, 
            "turn_signal_right_front": vehicle.turn_signal_right_front, 
            "turn_signal_left_rear": vehicle.turn_signal_left_rear, 
            "turn_signal_right_rear": vehicle.turn_signal_right_rear
        }

        client.publish(f"{mqtt_topic}data", json.dumps(data_points), retain=True)
        client.publish(f"{mqtt_topic}last_action_result", "success")
        logger.info("Daten erfolgreich publiziert.")

    except Exception as e:
        logger.error(f"Update Fehler: {str(e)}")

def fetch_and_publish_stats():
    stats_topic = "Garage/Kia/EV6/history" 
    try:
        vm.check_and_refresh_token()
        vm.update_all_vehicles_with_cached_state()
        vehicle = vm.get_vehicle(vehicle_id)
        stats = getattr(vehicle, '_daily_stats', [])
        
        # WICHTIG: Ein Dictionary {} statt einer Liste []
        daily_data = {} 
        
        for i, day in enumerate(stats[:driving_history_days], start=1):
            prefix = f"{i:02d}_" 
            dist = float(day.distance)
            total_kwh = round(day.total_consumed / 1000, 2)
            avg_100km = round((total_kwh / dist * 100), 1) if dist > 0 else 0
            
            # Wir fuegen alles direkt in das eine Dictionary ein
            daily_data[f"{prefix}datum"] = day.date.strftime("%d-%m-%Y")
            daily_data[f"{prefix}distanz_km"] = dist
            daily_data[f"{prefix}avg_100km"] = avg_100km
            daily_data[f"{prefix}verbrauch_kwh"] = total_kwh
            daily_data[f"{prefix}regen_kwh"] = round(day.regenerated_energy / 1000, 2)
        
        # Senden des flachen Objekts
        payload = json.dumps(daily_data, ensure_ascii=True).encode('utf-8')
        client.publish(f"{mqtt_topic}drivinghistory", payload, retain=True)
        
    except Exception as e:
        logger.error(f"Fehler beim Statistik-Abruf: {str(e)}")

def on_message(client, userdata, msg):
    global vm, vehicle_id, mqtt_topic
    final_status = "idle"
    
    try:
        set_command_status("pending")
        vm.check_and_refresh_token()
        
        # Topic parsen (z.B. "getAll", "startClimate", "door")
        topic = msg.topic.replace(mqtt_topic + "set/", "")
        payload = msg.payload.decode("utf-8")
        
        logger.info(f"MQTT-Befehl empfangen: {topic} mit Payload: {payload}")
        
        # getAll & forceAll
        if topic == "getAll":
            update_and_publish(force_mode="auto")
        elif topic == "forceAll":
            update_and_publish(force_mode="force")
            
        # Türen sperren / entsperren
        elif topic == "door":
            res = vm.lock(vehicle_id) if payload.lower() == "lock" else vm.unlock(vehicle_id)
            if wait_for_action(vm, vehicle_id, res, mqtt_topic, client):
                update_and_publish("force")
            else:
                final_status = "fail"
                
        # Klimaanlage Starten
        elif topic == "startClimate":
            try:
                climateClass = ClimateRequestOptions(**json.loads(msg.payload))
                action_response = vm.start_climate(vehicle_id, climateClass)
                
                # Antwort-Objekt roh an MQTT senden (wie in deinem Original)
                client.publish(f"{mqtt_topic}response", process_api_response(action_response), retain=True)
                
                action_id = getattr(action_response, 'action_id', action_response)
                if wait_for_action(vm, vehicle_id, action_id, mqtt_topic, client):
                    update_and_publish("force")
                else:
                    final_status = "fail"
            except Exception as e:
                logging.error(f"Klima Start fehlgeschlagen: {e}")
                final_status = "fail"
                
        # Klimaanlage Stoppen
        elif topic == "stopClimate":
            res = vm.stop_climate(vehicle_id)
            if wait_for_action(vm, vehicle_id, res, mqtt_topic, client):
                update_and_publish("force")
            else:
                final_status = "fail"
                
        # Laden starten / stoppen
        elif topic == "startCharge" or topic == "stopCharge":
            res = vm.start_charge(vehicle_id) if "start" in topic else vm.stop_charge(vehicle_id)
            if wait_for_action(vm, vehicle_id, res, mqtt_topic, client):
                update_and_publish("force")
            else:
                final_status = "fail"
                
        # Ladeklappe steuern
        elif topic == "charge_port":
            res = vm.open_charge_port(vehicle_id) if payload.lower() == "open" else vm.close_charge_port(vehicle_id)
            if wait_for_action(vm, vehicle_id, res, mqtt_topic, client):
                update_and_publish("force")
            else:
                final_status = "fail"
                
        # Ladelimits (Target SoC) setzen
        elif topic == "targetSoC":
            try:
                jsonmsg = json.loads(payload)
                res = vm.set_charge_limits(vehicle_id, jsonmsg['ac'], jsonmsg['dc'])
                if wait_for_action(vm, vehicle_id, res, mqtt_topic, client):
                    update_and_publish("force")
                else:
                    final_status = "fail"
            except Exception as e:
                final_status = "fail"
                client.publish(f"{mqtt_topic}last_action_result", "ungueltige Werte uebergeben")
                logger.error(f"TargetSoC Fehler: {e}")
        else:
            logger.warning(f"Unbekannter Befehl erhalten: {topic}")
            final_status = "fail"

    except RateLimitingError:
        final_status = "fail"
        error_msg = "API Limit erreicht."
        client.publish(f"{mqtt_topic}last_action_result", error_msg)
        logger.warning(error_msg)
        
    except AuthenticationError:
        final_status = "fail"
        error_msg = "Token ausgelaufen oder Account gesperrt."
        client.publish(f"{mqtt_topic}last_action_result", error_msg)
        logger.error(error_msg)
        
    except RequestTimeoutError:
        final_status = "fail"
        error_msg = "Timeout: Das Auto reagiert nicht schnell genug."
        client.publish(f"{mqtt_topic}last_action_result", error_msg)
        logger.error(error_msg)

    except ServiceTemporaryUnavailable:
        final_status = "fail"
        error_msg = "Kia Connect Service nicht erreichbar"
        client.publish(f"{mqtt_topic}last_action_result", error_msg)
        logger.error(error_msg)

    except DuplicateRequestError:
        final_status = "fail"
        error_msg = "Request abgelehnt da bereits ein Request verarbeitet wird"
        client.publish(f"{mqtt_topic}last_action_result", error_msg)
        logger.error(error_msg)

    except DeviceIDError:
        final_status = "fail"
        error_msg = "Ungueltige DeviceID - Relogin kann helfen"
        client.publish(f"{mqtt_topic}last_action_result", error_msg)
        logger.error(error_msg)

    except Exception as e:
        final_status = "fail"
        error_msg = f"Unerwarteter Fehler: {str(e)}"
        client.publish(f"{mqtt_topic}last_action_result", error_msg)
        logger.error(error_msg)
        
    finally:
        # Reaktiviert, damit der Systemstatus am Ende des Befehls wieder auf idle/fail springt
        set_command_status(final_status)

vm = VehicleManager(region=config['apiregion'], 
                    brand=config['apibrand'], 
                    username=config['apiusername'],
                    password=config['apirefreshtoken'], 
                    pin=config['apipin'], 
                    language=config['apilanguage']
                   )

client = mqtt.Client(config['mqttclientid'])
client.username_pw_set(config['mqttbrokeruser'], config['mqttbrokerpasswort'])

# Hilfsfunktion zum Abwarten des API-Status (In on_message oder als globale Funktion definieren)
def wait_for_action(vm, vehicle_id, action_response, topic_base, client):
    """Fragt den Status einer Aktion ab, bis sie abgeschlossen ist oder ein Timeout laeuft."""
    action_id = getattr(action_response, 'action_id', action_response)
    
    if not action_id:
        client.publish(f"{topic_base}last_action_result", "No Action ID found", retain=False)
        return False

    max_retries = 15  # Erhöht auf 15 Versuche * 5 Sek = 75 Sek maximal (Klima braucht oft etwas länger)
    
    for attempt in range(max_retries):
        try:
            status_obj = vm.check_action_status(vehicle_id, action_id)
            
            # Status in reinen String umwandeln und bereinigen (z.B. "order_status.success" -> "success")
            status_str = str(status_obj).lower()
            if "." in status_str:
                status_str = status_str.split(".")[-1]
                
            logger.info(f"Aktions-Status (Versuch {attempt+1}/{max_retries}): {status_obj} -> Erkannt als: {status_str}")
            
            # Den rohen Status für dein Dashboard publizieren
            client.publish(f"{topic_base}status/last_action_status", str(status_obj), retain=False)
            
            # Prüfung auf Erfolg oder Fehlschlag
            if "success" in status_str:
                client.publish(f"{mqtt_topic}command", "idle", retain=True) # Explizit hier auf idle setzen
                client.publish(f"{topic_base}last_action_result", f"Success (ID: {action_id})", retain=False)
                return True
            elif "fail" in status_str or "denied" in status_str:
                client.publish(f"{topic_base}last_action_result", f"Failed (ID: {action_id})", retain=False)
                return False
                
            # Bei "unknown", "pending" oder "processing" schläft die Schleife und versucht es erneut
                
        except Exception as e:
            logging.warning(f"Fehler beim Abfragen des Action-Status: {e}")
            
        time.sleep(5)
        
    client.publish(f"{topic_base}last_action_result", f"Timeout waiting for action {action_id}", retain=False)
    return False

def on_disconnect(client, userdata, rc):
    logger.warning(f"MQTT Verbindung verloren (Code {rc}). Automatisch Reconnect...")

def on_connect(c, u, f, rc):
    if rc == 0:
        logger.info("Verbunden mit MQTT Broker.")
        client.subscribe(f"{mqtt_topic}set/#")
        client.publish(f"{mqtt_topic}LWT", "Online", retain=True)
        set_command_status("idle")

client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_message = on_message
client.will_set(f"{mqtt_topic}LWT", "Offline", retain=True)
client.reconnect_delay_set(min_delay=1, max_delay=120)

client.connect(config['mqttbrokerip'], config['mqttbrokerport'], 119)
client.loop_start()

logger.info("Initialer Abruf der Daily Stats beim Scriptstart...")
fetch_and_publish_stats()

while True:

    now = datetime.now()

    # Täglicher Abruf um 01:00 Uhr
    if now.hour == 1 and now.minute == 0 and last_stats_date != now.date():
        fetch_and_publish_stats()
        last_stats_date = now.date()

    nonBlocking_sleep(10)
