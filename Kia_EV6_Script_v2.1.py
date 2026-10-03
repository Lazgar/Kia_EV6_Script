# -*- coding: utf-8 -*-
"""Kia EV6 -> MQTT Bruecke (v2.1)

Aenderungen gegenueber v2.0:
- MQTT-Befehle blockieren den MQTT-Thread nicht mehr: on_message legt Befehle nur in eine Warteschlange,
  ein Worker-Thread arbeitet sie nacheinander ab (die Kia-API verträgt nur einen Befehl gleichzeitig).
- Echter Befehlsstatus: nach dem Absenden wird der Status der Aktion bei Kia abgefragt
  (ORDER_STATUS: SUCCESS / FAILED / TIMEOUT / PENDING / UNKNOWN) und als JSON nach <basetopic>last_action veroeffentlicht.
  <basetopic>last_action_result bleibt wie bisher ("success" oder Fehlertext), <basetopic>command: pending/idle/fail.
- Weitere Werte aus der Antwort des Autos (Gesamtverbrauch, 30-Tage-Verbrauch, geschaetzte Ladezeiten,
  Ladeplan/Abfahrtszeiten, Rohwerte remoteWaitingTimeAlert u. a.). Nicht jeder Wert wird vom Auto geliefert -> `null`.
- Library-Logger auf WARNING (der INFO-Dump enthielt VIN und Standort im Journal).
- Login mit Wiederholversuchen, MQTT-Reconnect nur noch durch paho (kein doppelter Reconnect, kein loop() neben loop_start()).
- paho-mqtt 2.x kompatibel.
- Neuer MQTT-Befehl <basetopic>set/getDump: schreibt die komplette Fahrzeugantwort (alle Felder + Rohdaten der API)
  einmalig in eine Datei (Standard: vehicleDump.txt neben dem Skript, oder "dumpfile" in settings.json).
  Es wird nur auf diesen Befehl geschrieben, nie bei normalen Abfragen (schont die SSD). Payload "force" holt vorher frische Daten
  vom Auto (weckt es auf, belastet die 12-V-Batterie), sonst werden die zwischengespeicherten Daten verwendet.
"""
import json
import logging
import os
import queue
import sys
import threading
import time
import paho.mqtt.client as mqtt
from hyundai_kia_connect_api import *
from hyundai_kia_connect_api.const import ORDER_STATUS
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
# Die Library loggt nach jedem Abruf das komplette Fahrzeug (inkl. VIN/GPS) auf INFO.
logging.getLogger("hyundai_kia_connect_api").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
start_time = datetime.now()
last_stats_date = None

config_path = os.environ.get("KIA_SETTINGS") or os.path.join(os.path.dirname(os.path.realpath(__file__)), 'settings.json')
if not os.path.exists(config_path):
    logger.error("Kein Configfile gefunden.")
    sys.exit(-1)

with open(config_path) as f:
    config = json.load(f)

mqtt_topic = config['mqttbasetopic']
stats_topic = config['mqtthistorytopic']
vehicle_id = config['apivehicleid']
driving_history_days = config['drivinghistorydays']

dump_path = config.get('dumpfile') or os.path.join(os.path.dirname(os.path.realpath(__file__)), 'vehicleDump.txt')

ACTION_TIMEOUT = 90          # Sekunden, so lange wird auf die Rueckmeldung des Autos gewartet
ACTION_POLL = 3              # Sekunden zwischen den Statusabfragen
ACTION_STATE_CHECK_AFTER = 20  # ab hier zusaetzlich den Fahrzeugzustand pruefen (falls Aktion nicht auffindbar)

vm = None
client = None
api_lock = threading.RLock()     # nur ein API-Zugriff gleichzeitig (Worker, Statistik)
cmd_queue = queue.Queue(maxsize=20)


def nonBlocking_sleep(sec):
    end_time = time.time() + sec
    while time.time() < end_time:
        time.sleep(1)


def get_uptime():
    """Berechnet die Laufzeit seit Skriptstart"""
    diff = datetime.now() - start_time
    days = diff.days
    time_str = str(timedelta(seconds=diff.seconds))
    if days > 0:
        return f"{days} days, {time_str}"
    return time_str


def set_command_status(status):
    client.publish(f"{mqtt_topic}command", status, retain=True)
    logger.info(f"System-Status: {status}")


def publish_last_action(cmd, payload, state, detail="", action_id=None, started=None):
    """Detailstatus des letzten Befehls als JSON (state: queued/sent/success/failed/timeout/error)."""
    d = {
        "command": cmd,
        "payload": payload,
        "state": state,
        "detail": detail,
        "action_id": action_id,
        "time": datetime.now().isoformat(timespec="seconds"),
    }
    if started is not None:
        d["duration_s"] = round(time.time() - started, 1)
    client.publish(f"{mqtt_topic}last_action", json.dumps(d, ensure_ascii=False), retain=True)


def _g(obj, name, default=None):
    """Attribut sicher lesen (aeltere/neuere Library-Staende kennen nicht alle Felder)."""
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _raw(vehicle, *path):
    """Rohwert aus der API-Antwort (vehicle.data), z. B. _raw(v, 'vehicleStatus', 'hazardStatus')."""
    cur = _g(vehicle, 'data')
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def update_and_publish(force_mode="auto"):
    try:
        with api_lock:
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
            "turn_signal_right_rear": vehicle.turn_signal_right_rear,
            # --- neu in v2.1 (null, wenn das Auto den Wert nicht liefert) ---
            "total_power_consumed_wh": _g(vehicle, 'total_power_consumed'),
            "total_power_regenerated_wh": _g(vehicle, 'total_power_regenerated'),
            "power_consumption_30d": _g(vehicle, 'power_consumption_30d'),
            "charge_duration_fast_min": _g(vehicle, '_ev_estimated_fast_charge_duration'),
            "charge_duration_station_min": _g(vehicle, '_ev_estimated_station_charge_duration'),
            "charge_duration_portable_min": _g(vehicle, '_ev_estimated_portable_charge_duration'),
            "schedule_charge_enabled": _g(vehicle, 'ev_schedule_charge_enabled'),
            "departure1_enabled": _g(vehicle, 'ev_first_departure_enabled'),
            "departure1_time": _g(vehicle, 'ev_first_departure_time'),
            "departure1_days": _g(vehicle, 'ev_first_departure_days'),
            "departure1_climate_enabled": _g(vehicle, 'ev_first_departure_climate_enabled'),
            "departure2_enabled": _g(vehicle, 'ev_second_departure_enabled'),
            "departure2_time": _g(vehicle, 'ev_second_departure_time'),
            "departure2_days": _g(vehicle, 'ev_second_departure_days'),
            "departure2_climate_enabled": _g(vehicle, 'ev_second_departure_climate_enabled'),
            "off_peak_start_time": _g(vehicle, 'ev_off_peak_start_time'),
            "off_peak_end_time": _g(vehicle, 'ev_off_peak_end_time'),
            "off_peak_charge_only": _g(vehicle, 'ev_off_peak_charge_only_enabled'),
            "battery_preconditioning": _raw(vehicle, 'vehicleStatus', 'evStatus', 'batteryPreconditioning'),
            "remote_control_available": _raw(vehicle, 'vehicleStatus', 'remoteWaitingTimeAlert', 'remoteControlAvailable'),
            "remote_control_waiting_time": _raw(vehicle, 'vehicleStatus', 'remoteWaitingTimeAlert', 'remoteControlWaitingTime'),
            "remote_control_elapsed_time": _raw(vehicle, 'vehicleStatus', 'remoteWaitingTimeAlert', 'elapsedTime'),
            "power_auto_cut_mode": _raw(vehicle, 'vehicleStatus', 'battery', 'powerAutoCutMode'),
            "system_cut_off_alert": _raw(vehicle, 'vehicleStatus', 'systemCutOffAlert'),
            "hazard_status": _raw(vehicle, 'vehicleStatus', 'hazardStatus'),
            "ignition_on": _raw(vehicle, 'vehicleStatus', 'ign3'),
            "last_updated_at": _g(vehicle, '_last_updated_at'),
        }

        client.publish(f"{mqtt_topic}data", json.dumps(data_points, default=str), retain=True)
        client.publish(f"{mqtt_topic}last_action_result", "success")
        logger.info("Daten erfolgreich publiziert.")

    except Exception as e:
        logger.error(f"Update Fehler: {str(e)}")


def fetch_and_publish_stats():
    try:
        with api_lock:
            vm.check_and_refresh_token()
            vm.update_all_vehicles_with_cached_state()
            vehicle = vm.get_vehicle(vehicle_id)
        stats = getattr(vehicle, '_daily_stats', [])

        # WICHTIG: ein flaches Dictionary {}, keine Liste
        daily_data = {}

        for i, day in enumerate(stats[:driving_history_days], start=1):
            prefix = f"{i:02d}_"
            dist = float(day.distance)
            total_kwh = round(day.total_consumed / 1000, 2)
            avg_100km = round((total_kwh / dist * 100), 1) if dist > 0 else 0

            daily_data[f"{prefix}datum"] = day.date.strftime("%d-%m-%Y")
            daily_data[f"{prefix}distanz_km"] = dist
            daily_data[f"{prefix}avg_100km"] = avg_100km
            daily_data[f"{prefix}verbrauch_kwh"] = total_kwh
            daily_data[f"{prefix}regen_kwh"] = round(day.regenerated_energy / 1000, 2)
            # neu in v2.1: Aufteilung des Verbrauchs
            daily_data[f"{prefix}antrieb_kwh"] = round(_g(day, 'engine_consumption', 0) / 1000, 2)
            daily_data[f"{prefix}klima_kwh"] = round(_g(day, 'climate_consumption', 0) / 1000, 2)
            daily_data[f"{prefix}bordelektronik_kwh"] = round(_g(day, 'onboard_electronics_consumption', 0) / 1000, 2)

        payload = json.dumps(daily_data, ensure_ascii=True).encode('utf-8')
        client.publish(stats_topic, payload, retain=True)

    except Exception as e:
        logger.error(f"Fehler beim Statistik-Abruf: {str(e)}")


def write_dump(vehicle):
    """Schreibt den kompletten Fahrzeugzustand (Felder + API-Rohdaten) atomar in dump_path (nur 1x pro getDump-Befehl)."""
    fields = {k: v for k, v in vars(vehicle).items() if k != 'data'}
    dump = {
        "dumped_at": datetime.now().isoformat(timespec="seconds"),
        "fields": fields,
        "raw_api_data": _g(vehicle, 'data'),
    }
    tmp = dump_path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # enthaelt VIN/Standort -> nur Besitzer
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(dump, f, default=str, ensure_ascii=False, indent=1)
    os.replace(tmp, dump_path)
    return os.path.getsize(dump_path)


def confirm_by_state(cmd, payload):
    """Fallback: Fahrzeugzustand mit dem erwarteten Ergebnis vergleichen. True/False, None = nicht pruefbar."""
    try:
        with api_lock:
            vm.check_and_force_update_vehicles(3598)
            vehicle = vm.get_vehicle(vehicle_id)
        if cmd in ("startClimate", "stopClimate"):
            return vehicle.air_control_is_on == (cmd == "startClimate")
        if cmd == "door":
            return vehicle.is_locked == (payload.lower() == "lock")
        if cmd in ("startCharge", "stopCharge"):
            return vehicle.ev_battery_is_charging == (cmd == "startCharge")
        if cmd == "charge_port":
            return vehicle.ev_charge_port_door_is_open == (payload.lower() == "open")
    except Exception as e:
        logger.warning(f"Zustandspruefung fehlgeschlagen: {e}")
    return None


def wait_for_action(res, cmd, payload):
    """Fragt den echten Aktionsstatus bei Kia ab. Rueckgabe: (state, detail, action_id).
    state: success | failed | timeout | error"""
    action_id = getattr(res, 'action_id', res)
    if not action_id:
        return "error", "Keine Action-ID von der Kia-API erhalten", None

    started = time.time()
    publish_last_action(cmd, payload, "sent", "Befehl an das Auto gesendet, warte auf Bestaetigung", action_id)
    last_state_check = 0
    last_status = None

    while time.time() - started < ACTION_TIMEOUT:
        time.sleep(ACTION_POLL)
        try:
            with api_lock:
                last_status = vm.check_action_status(vehicle_id, action_id, synchronous=False)
        except DeviceIDError:
            logger.warning("DeviceID ungueltig - versuche Token-Refresh")
            try:
                with api_lock:
                    vm.check_and_refresh_token()
            except Exception as e:
                logger.warning(f"Token-Refresh fehlgeschlagen: {e}")
            continue
        except Exception as e:
            logger.warning(f"Statusabfrage fehlgeschlagen: {e}")
            continue

        if last_status == ORDER_STATUS.SUCCESS:
            return "success", "Auto hat den Befehl bestaetigt", action_id
        if last_status == ORDER_STATUS.FAILED:
            return "failed", "Auto hat den Befehl abgelehnt (Bedingung nicht erfuellt)", action_id
        if last_status == ORDER_STATUS.TIMEOUT:
            return "timeout", "Auto hat nicht geantwortet (Befehl vermutlich nicht ausgefuehrt)", action_id

        # PENDING oder UNKNOWN: nach einer Weile zusaetzlich den Zustand pruefen
        elapsed = time.time() - started
        if elapsed >= ACTION_STATE_CHECK_AFTER and time.time() - last_state_check >= 15:
            last_state_check = time.time()
            if confirm_by_state(cmd, payload):
                return "success", f"Zustand des Autos bestaetigt das Ergebnis (API-Status: {last_status})", action_id
            if cmd == "targetSoC":
                return "success", "Ladelimit gesendet (Zustand nicht pruefbar)", action_id

    return "timeout", f"Keine Rueckmeldung innerhalb {ACTION_TIMEOUT}s (letzter API-Status: {last_status})", action_id


def execute_command(topic, payload, raw):
    """Fuehrt einen Befehl aus. Rueckgabe: (state, detail, action_id) oder None (bei getAll/forceAll)."""
    with api_lock:
        vm.check_and_refresh_token()

    if topic == "getDump":
        with api_lock:
            if payload.strip().lower() == "force":
                vm.force_refresh_vehicle_state(vehicle_id)
            else:
                vm.check_and_force_update_vehicles(3598)
            size = write_dump(vm.get_vehicle(vehicle_id))
        return "success", f"Dump geschrieben: {dump_path} ({size} Bytes)", None

    if topic == "getAll":
        update_and_publish(force_mode="auto")
        return None
    if topic == "forceAll":
        update_and_publish(force_mode="force")
        return None

    with api_lock:
        if topic == "door":
            res = vm.lock(vehicle_id) if payload.lower() == "lock" else vm.unlock(vehicle_id)
            refresh = "force"
        elif topic == "startClimate":
            res = vm.start_climate(vehicle_id, ClimateRequestOptions(**json.loads(raw)))
            refresh = "auto"
        elif topic == "stopClimate":
            res = vm.stop_climate(vehicle_id)
            refresh = "auto"
        elif topic in ("startCharge", "stopCharge"):
            res = vm.start_charge(vehicle_id) if topic == "startCharge" else vm.stop_charge(vehicle_id)
            refresh = "auto"
        elif topic == "charge_port":
            res = vm.open_charge_port(vehicle_id) if payload.lower() == "open" else vm.close_charge_port(vehicle_id)
            refresh = "auto"
        elif topic == "targetSoC":
            jsonmsg = json.loads(payload)
            res = vm.set_charge_limits(vehicle_id, jsonmsg['ac'], jsonmsg['dc'])
            refresh = "auto"
        else:
            return "error", f"Unbekannter Befehl: {topic}", None

    state, detail, action_id = wait_for_action(res, topic, payload)
    if state == "success":
        update_and_publish(refresh)
    return state, detail, action_id


def run_command(topic, payload, raw):
    """Fuehrt einen Befehl aus und veroeffentlicht das Ergebnis. Rueckgabe: True/False (Erfolg)."""
    started = time.time()
    state, detail, action_id = "error", "", None
    try:
        result = execute_command(topic, payload, raw)
        if result is None:           # getAll / forceAll: update_and_publish hat bereits veroeffentlicht
            publish_last_action(topic, payload, "success", "Daten abgerufen", None, started)
            return True
        state, detail, action_id = result
    except RateLimitingError:
        state, detail = "error", "API Limit erreicht."
        logger.warning(detail)
    except AuthenticationError:
        state, detail = "error", "Token ausgelaufen oder Account gesperrt."
        logger.error(detail)
    except RequestTimeoutError:
        state, detail = "timeout", "Timeout: Das Auto reagiert nicht schnell genug."
        logger.error(detail)
    except ServiceTemporaryUnavailable:
        state, detail = "error", "Kia Connect Service nicht erreichbar"
        logger.error(detail)
    except DuplicateRequestError:
        state, detail = "error", "Request abgelehnt da bereits ein Request verarbeitet wird"
        logger.error(detail)
    except DeviceIDError:
        state, detail = "error", "Ungueltige DeviceID - Relogin kann helfen"
        logger.error(detail)
    except (ValueError, KeyError, TypeError) as e:
        state, detail = "error", f"Ungueltige Werte uebergeben: {e}"
        logger.error(f"{topic}: {detail}")
    except Exception as e:
        state, detail = "error", f"Unerwarteter Fehler: {str(e)}"
        logger.error(detail)

    publish_last_action(topic, payload, state, detail, action_id, started)
    client.publish(f"{mqtt_topic}last_action_result", "success" if state == "success" else detail)
    logger.info(f"Befehl {topic}: {state} - {detail}")
    return state == "success"


def command_worker():
    """Arbeitet Befehle nacheinander ab, ohne den MQTT-Thread zu blockieren."""
    while True:
        topic, payload, raw = cmd_queue.get()
        ok = False
        try:
            ok = run_command(topic, payload, raw)
        except Exception as e:      # darf den Worker nie beenden
            logger.error(f"Worker-Fehler: {e}")
        finally:
            cmd_queue.task_done()
            if cmd_queue.empty():
                set_command_status("idle" if ok else "fail")


def on_message(client_, userdata, msg):
    """Nimmt Befehle nur an und stellt sie in die Warteschlange (kehrt sofort zurueck)."""
    topic = msg.topic.replace(mqtt_topic + "set/", "")
    payload = msg.payload.decode("utf-8", errors="replace")
    logger.info(f"MQTT-Befehl empfangen: {topic} mit Payload: {payload}")
    try:
        cmd_queue.put_nowait((topic, payload, msg.payload))
    except queue.Full:
        publish_last_action(topic, payload, "error", "Befehlswarteschlange voll")
        return
    set_command_status("pending")
    publish_last_action(topic, payload, "queued", f"In Warteschlange (Position {cmd_queue.qsize()})")


def on_disconnect(c, userdata, rc):
    # Reconnect uebernimmt paho (loop_start + reconnect_delay_set); hier nur loggen.
    logger.warning(f"MQTT Verbindung verloren (Code {rc}). paho verbindet automatisch neu.")


def on_connect(c, u, f, rc):
    if rc == 0:
        logger.info("Verbunden mit MQTT Broker.")
        c.subscribe(f"{mqtt_topic}set/#")
        c.publish(f"{mqtt_topic}LWT", "Online", retain=True)
        set_command_status("idle")


def login_with_retry(max_attempts=8):
    delay = 10
    for attempt in range(1, max_attempts + 1):
        try:
            vm.login()
            return
        except Exception as e:
            logger.error(f"Login fehlgeschlagen ({attempt}/{max_attempts}): {e}")
            if attempt == max_attempts:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 300)


def main():
    global vm, client, last_stats_date

    vm = VehicleManager(region=config['apiregion'],
                        brand=config['apibrand'],
                        username=config['apiusername'],
                        password=config['apipassword'],
                        pin=config['apipin'],
                        language=config['apilanguage']
                        )
    login_with_retry()

    try:                              # paho-mqtt >= 2.0
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, config['mqttclientid'])
    except AttributeError:            # paho-mqtt 1.x
        client = mqtt.Client(config['mqttclientid'])
    client.username_pw_set(config['mqttbrokeruser'], config['mqttbrokerpasswort'])
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.will_set(f"{mqtt_topic}LWT", "Offline", retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=120)

    threading.Thread(target=command_worker, daemon=True, name="kia-worker").start()

    # connect_async: das Skript startet auch dann, wenn der Broker gerade nicht erreichbar ist
    client.connect_async(config['mqttbrokerip'], config['mqttbrokerport'], 119)
    client.loop_start()

    logger.info("Initialer Abruf der Daily Stats beim Scriptstart...")
    fetch_and_publish_stats()

    while True:
        now = datetime.now()

        # Taeglicher Abruf um 01:00 Uhr
        if now.hour == 1 and now.minute == 0 and last_stats_date != now.date():
            fetch_and_publish_stats()
            last_stats_date = now.date()

        nonBlocking_sleep(10)


if __name__ == "__main__":
    main()
