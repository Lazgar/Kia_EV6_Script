from hyundai_kia_connect_api import *
import paho.mqtt.client as mqtt
import sys
import os
import string
import json
from time import sleep
from datetime import datetime, timedelta

configFile = os.path.dirname(os.path.realpath(__file__)) + '/settings.json'

if not os.path.exists(configFile):
    print("Kein Configfile gefunden bitte eines anlegen.")
    sys.exit(-1)

if not os.access(configFile, os.R_OK):
    print("ConfigFile " + configFile + " kann nicht gelesen werden!\n\n")
    sys.exit(-2)

config = json.load(open(configFile))

neededConfig = ['mqttclientid', 'mqttbasetopic', 'mqttbrokerip', 'mqttbrokerport', 'mqttbrokeruser', 'mqttbrokerpasswort', "apiusername", 'apipassword', 'apipin', 'apibrand', 'apiregion', 'apilanguage', 'apivehicleid']
for conf in neededConfig:
    if conf not in config:
        print(conf + ' Fehlt im Configfile!')
        sys.exit(3)

mqttclientid = config['mqttclientid']
mqttbasetopic = config['mqttbasetopic']
mqttbroker = config['mqttbrokerip']
mqttport = config['mqttbrokerport']             #1883 ist der Standard Port
mqttuser = config['mqttbrokeruser']              #wenn kein User verwendet wird leer lassen ""
mqttpasswort = config['mqttbrokerpasswort']     #wenn kein Passwort verwendet wird leer lassen ""

apiuser = config['apiusername']
apipassword = config['apipassword']
apipin = config['apipin']
apibrand = config['apibrand']
apiregion = config['apiregion']
apilanguage = config['apilanguage']
vehicle_id = config['apivehicleid']

vm = VehicleManager(region=apiregion, brand=apibrand, username=apiuser, password=apipassword, pin=apipin, language=apilanguage, geocode_api_enable=True, geocode_api_use_email=True)

getValues = ["id='",
             "model='",
             "is_locked=",
             "odometer=",
             "ev_battery_percentage=",
             "air_temperature=",
             "car_battery_percentage=",
             "ev_driving_range=",
             "location_latitude=",
             "location_longitude=",
             "engine_is_running=",
             "smart_key_battery_warning_is_on=",
             "washer_fluid_warning_is_on=",
             "brake_fluid_warning_is_on=",
             "defrost_is_on=",
             "steering_wheel_heater_is_on=",
             "back_window_heater_is_on=",
             "front_left_door_is_open=",
             "front_right_door_is_open=",
             "back_left_door_is_open=",
             "back_right_door_is_open=",
             "trunk_is_open=",
             "hood_is_open=",
             "front_left_window_is_open=",
             "front_right_window_is_open=",
             "back_left_window_is_open=",
             "back_right_window_is_open=",
             "tire_pressure_all_warning_is_on=",
             "tire_pressure_rear_left_warning_is_on=",
             "tire_pressure_front_left_warning_is_on=",
             "tire_pressure_front_right_warning_is_on=",
             "tire_pressure_rear_right_warning_is_on=",
             "charge_port_door_is_open=",
             "charging_power=",
             "charge_limits_dc=",
             "charge_limits_ac=",
             "charging_current=",
             "battery_is_charging=",
             "battery_is_plugged_in=",
             "target_range_charge_AC=",
             "target_range_charge_DC="
            ]

def on_connect(client, userdata, flags, rc):
    client.publish(mqttbasetopic + "LWT", "Online")
    client.subscribe(mqttbasetopic + "getAll/#")
    client.subscribe(mqttbasetopic + "charging/#")
    client.subscribe(mqttbasetopic + "climate/#")
    client.subscribe(mqttbasetopic + "lock_state/#")
    client.subscribe(mqttbasetopic + "charge_port/#")

def on_message(client, userdata, msg):
  vm.check_and_refresh_token()
  
  if msg.topic == mqttbasetopic + "getAll":
    
    client.publish(mqttbasetopic + "command", "pending")
    client.loop(5)
    get_full_status()
    client.publish(mqttbasetopic + "command", "idle")
    
  elif msg.topic == mqttbasetopic + "climate" and str(msg.payload) == "b'start'":
    
    client.publish(mqttbasetopic + "command", "pending")
    client.loop(5)
    vm.start_climate(vehicle_id)
    sleep(60)
    client.publish(mqttbasetopic + "command", "idle")
    
  elif msg.topic == mqttbasetopic + "climate" and str(msg.payload) == "b'stop'":
    
    client.publish(mqttbasetopic + "command", "pending")
    client.loop(5)
    vm.stop_climate(vehicle_id)
    sleep(60)
    client.publish(mqttbasetopic + "command", "idle")
    
  elif msg.topic == mqttbasetopic + "lock_state" and str(msg.payload) == "b'lock'":
    
    client.publish(mqttbasetopic + "command", "pending")
    client.loop(5)
    vm.lock(vehicle_id)
    sleep(60)
    client.publish(mqttbasetopic + "command", "idle")
    
  elif msg.topic == mqttbasetopic + "lock_state" and str(msg.payload) == "b'unlock'":
    
    client.publish(mqttbasetopic + "command", "pending")
    client.loop(5)
    vm.unlock(vehicle_id)
    sleep(60)
    client.publish(mqttbasetopic + "command", "idle")
    
  elif msg.topic == mqttbasetopic + "chargeing" and str(msg.payload) == "b'start'":
    
    client.publish(mqttbasetopic + "command", "pending")
    client.loop(5)
    vm.start_charge(vehicle_id)
    sleep(60)
    client.publish(mqttbasetopic + "command", "idle")
    
  elif msg.topic == mqttbasetopic + "charging" and str(msg.payload) == "b'stop'":
    
    client.publish(mqttbasetopic + "command", "pending")
    client.loop(5)
    vm.stop_charge(vehicle_id)
    sleep(60)
    client.publish(mqttbasetopic + "command", "idle")
    
  elif msg.topic == mqttbasetopic + "charge_port" and str(msg.payload) == "b'open'":
    
    client.publish(mqttbasetopic + "command", "pending")
    client.loop(5)
    vm.open_charge_port(vehicle_id)
    sleep(60)
    client.publish(mqttbasetopic + "command", "idle")
    
  elif msg.topic == mqttbasetopic + "charge_port" and str(msg.payload) == "b'close'":
    
    client.publish(mqttbasetopic + "command", "pending")
    client.loop(5)
    vm.close_charge_port(vehicle_id)
    sleep(60)
    client.publish(mqttbasetopic + "command", "idle")

def get_full_status():
  vm.check_and_force_update_vehicles(299)

  string = str(vm.vehicles)
  
  for searchValue in getValues:

    start = string.find(searchValue)
    end = string.find(",",start)

    ret = string[start + len(searchValue):end]
      
    if ret == "0":
      ret = "False"
    elif ret == "1":
      ret = "True"

    if searchValue.rstrip("='") == "id":
      client.publish(mqttbasetopic + "vehicle_id", ret.rstrip("'"))
    else:
      client.publish(mqttbasetopic + searchValue.rstrip("='"), ret.rstrip("'"))
      
def mqtt_reconnect():
  connected = False
  while not connected:
    try:
      client.reconnect()
      connected = True
    except:
      print("Lost Connection to MQTT...Trying to reconnect in 2 Seconds")
      time.sleep(2)
      
try:
   client = mqtt.Client(mqttclientid)
   client.username_pw_set(mqttuser, mqttpasswort)
   client.on_connect = on_connect
   client.on_message = on_message
   client.will_set(mqttbasetopic + "LWT", "Offline", qos=0, retain=False)
   client.reconnect_delay_set(min_delay=1, max_delay=120)
   client.connect_async(mqttbroker, mqttport,119)
   client.loop_start()
except:
   print("Die Ip Adresse des Brokers ist falsch!")
   sys.exit()

while 1:
  
  sleep(10)
