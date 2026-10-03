# -*- coding: utf-8 -*-
"""Tests fuer Kia_EV6_Script_v2.1.py ohne Auto, ohne Kia-Konto und ohne MQTT-Broker (alles gemockt).
Aufruf:  python3 -m unittest tests/test_v2_1.py -v
"""
import enum
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------- Stubs fuer hyundai_kia_connect_api (und paho, falls nicht installiert) ----------
class ORDER_STATUS(enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


def _exc(name):
    return type(name, (Exception,), {})


def install_stubs():
    pkg = types.ModuleType("hyundai_kia_connect_api")
    pkg.VehicleManager = object
    pkg.ClimateRequestOptions = lambda **kw: kw
    const = types.ModuleType("hyundai_kia_connect_api.const")
    const.ORDER_STATUS = ORDER_STATUS
    exc = types.ModuleType("hyundai_kia_connect_api.exceptions")
    for n in ("APIError", "AuthenticationError", "DuplicateRequestError", "RequestTimeoutError",
              "ServiceTemporaryUnavailable", "NoDataFound", "InvalidAPIResponseError", "RateLimitingError", "DeviceIDError"):
        setattr(exc, n, _exc(n))
    sys.modules.update({"hyundai_kia_connect_api": pkg, "hyundai_kia_connect_api.const": const,
                        "hyundai_kia_connect_api.exceptions": exc})
    try:
        import paho.mqtt.client  # noqa: F401
    except ImportError:
        p1, p2, p3 = types.ModuleType("paho"), types.ModuleType("paho.mqtt"), types.ModuleType("paho.mqtt.client")
        p3.Client = object
        sys.modules.update({"paho": p1, "paho.mqtt": p2, "paho.mqtt.client": p3})
    return exc


EXC = install_stubs()
SETTINGS = {"mqttclientid": "t", "mqttbasetopic": "kia/", "mqtthistorytopic": "kia/hist", "mqttbrokerip": "127.0.0.1",
            "mqttbrokerport": 1883, "mqttbrokeruser": "u", "mqttbrokerpasswort": "p", "apiusername": "u",
            "apipassword": "p", "apipin": "0000", "apibrand": 1, "apiregion": 1, "apilanguage": "de",
            "apivehicleid": "VID", "drivinghistorydays": 3}
_tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
json.dump(SETTINGS, _tmp)
_tmp.close()
os.environ["KIA_SETTINGS"] = _tmp.name
spec = importlib.util.spec_from_file_location("kia21", os.path.join(ROOT, "Kia_EV6_Script_v2.1.py"))
kia = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kia)


class FakeClient:
    def __init__(self):
        self.pub = []
        self.lock = threading.Lock()

    def publish(self, topic, payload=None, retain=False, **kw):
        with self.lock:
            self.pub.append((topic, payload))

    def topic(self, name):
        with self.lock:
            return [p for t, p in self.pub if t == "kia/" + name]


class FakeVehicle:
    id, model, VIN = "VID", "EV6", "X"
    total_power_consumed = 1234
    data = {"vehicleStatus": {"hazardStatus": 0, "ign3": True,
                              "remoteWaitingTimeAlert": {"remoteControlAvailable": 1, "remoteControlWaitingTime": 168,
                                                         "elapsedTime": "17:45:07"}}}
    is_locked = True
    air_control_is_on = False

    def __getattr__(self, name):    # unbekannte Felder liefert das Auto nicht -> None
        if name.startswith("__"):
            raise AttributeError(name)
        return None


class FakeVM:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = []
        self.vehicle = FakeVehicle()

    def check_and_refresh_token(self): pass
    def check_and_force_update_vehicles(self, s): pass
    def force_refresh_vehicle_state(self, v): self.calls.append("force")
    def update_all_vehicles_with_cached_state(self): pass
    def get_vehicle(self, v): return self.vehicle
    def lock(self, v): self.calls.append("lock"); return "ACT1"
    def unlock(self, v): self.calls.append("unlock"); return "ACT2"
    def start_charge(self, v): self.calls.append("startCharge"); return "ACT3"
    def set_charge_limits(self, v, ac, dc): self.calls.append("limits"); return "ACT4"

    def check_action_status(self, vehicle_id, action_id, synchronous=False):
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]


class Msg:
    def __init__(self, topic, payload):
        self.topic, self.payload = "kia/set/" + topic, payload.encode()


class V21Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        kia.ACTION_POLL = 0.05
        kia.ACTION_TIMEOUT = 3
        kia.ACTION_STATE_CHECK_AFTER = 0.2
        threading.Thread(target=kia.command_worker, daemon=True).start()

    def setUp(self):
        kia.client = FakeClient()
        kia.cmd_queue.join()

    def run_cmd(self, topic, payload, statuses):
        kia.vm = FakeVM(statuses)
        t0 = time.time()
        kia.on_message(None, None, Msg(topic, payload))
        returned_in = time.time() - t0
        kia.cmd_queue.join()
        time.sleep(0.1)
        states = [json.loads(p)["state"] for p in kia.client.topic("last_action")]
        return returned_in, states

    def test_on_message_blockiert_nicht_und_erfolg(self):
        P, S = ORDER_STATUS.PENDING, ORDER_STATUS.SUCCESS
        returned_in, states = self.run_cmd("door", "lock", [P, P, S])
        self.assertLess(returned_in, 0.1)                       # MQTT-Thread kommt sofort zurueck
        self.assertEqual(states, ["queued", "sent", "success"])
        self.assertEqual(kia.client.topic("command")[-1], "idle")
        self.assertIn("success", kia.client.topic("last_action_result"))
        self.assertTrue(kia.client.topic("data"))               # nach Erfolg Daten neu veroeffentlicht

    def test_abgelehnt(self):
        _, states = self.run_cmd("startCharge", "", [ORDER_STATUS.FAILED])
        self.assertEqual(states[-1], "failed")
        self.assertEqual(kia.client.topic("command")[-1], "fail")
        self.assertIn("abgelehnt", kia.client.topic("last_action_result")[-1])

    def test_keine_antwort_vom_auto(self):
        _, states = self.run_cmd("door", "unlock", [ORDER_STATUS.TIMEOUT])
        self.assertEqual(states[-1], "timeout")

    def test_unbekannt_dann_zustandspruefung(self):
        # API findet die Aktion nicht (UNKNOWN), der Fahrzeugzustand (is_locked=True) bestaetigt aber "lock"
        _, states = self.run_cmd("door", "lock", [ORDER_STATUS.UNKNOWN])
        self.assertEqual(states[-1], "success")

    def test_ungueltiges_targetsoc(self):
        _, states = self.run_cmd("targetSoC", "kein json", [ORDER_STATUS.SUCCESS])
        self.assertEqual(states[-1], "error")
        self.assertIn("Ungueltige", kia.client.topic("last_action_result")[-1])

    def test_unbekannter_befehl(self):
        _, states = self.run_cmd("quatsch", "", [ORDER_STATUS.SUCCESS])
        self.assertEqual(states[-1], "error")

    def test_zwei_befehle_nacheinander(self):
        kia.vm = FakeVM([ORDER_STATUS.SUCCESS])
        kia.on_message(None, None, Msg("door", "lock"))
        kia.on_message(None, None, Msg("startCharge", ""))
        kia.cmd_queue.join()
        time.sleep(0.1)
        self.assertEqual([c for c in kia.vm.calls if c != "force"], ["lock", "startCharge"])
        done = [json.loads(p) for p in kia.client.topic("last_action") if json.loads(p)["state"] == "success"]
        self.assertEqual([d["command"] for d in done], ["door", "startCharge"])
        self.assertEqual(kia.client.topic("command")[-1], "idle")

    def test_neue_werte_und_null_fuer_fehlendes(self):
        kia.vm = FakeVM([ORDER_STATUS.SUCCESS])
        kia.update_and_publish("auto")
        d = json.loads(kia.client.topic("data")[-1])
        self.assertEqual(d["total_power_consumed_wh"], 1234)
        self.assertEqual(d["remote_control_waiting_time"], 168)
        self.assertEqual(d["hazard_status"], 0)
        self.assertIsNone(d["power_consumption_30d"])           # vom Auto nicht geliefert -> null


if __name__ == "__main__":
    unittest.main()
