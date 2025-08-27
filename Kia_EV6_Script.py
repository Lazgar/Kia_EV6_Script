from hyundai_kia_connect_api import *
import paho.mqtt.client as mqtt
import sys
import os
import string
import json
from time import sleep
from datetime import datetime, timedelta

vm = VehicleManager(region=1, brand=1, username="andreas@markl.biz", password="2@9b7j1q4r5B6!3g8", pin="1025", language="de", geocode_api_enable=True, geocode_api_use_email=True)
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
             "target_range_charge_AC=",
             "target_range_charge_DC="
            ]

useMQTT = True
mqttBroker = "10.0.0.3"
mqttuser ="fhemqtt"
mqttpasswort = "2O9c7l1q4t5w6"
mqttport = 1883

vehicle_id = '872d889e-17f8-4af9-b394-e1f477b49c61'

def on_connect(client, userdata, flags, rc):
    client.publish("Kia_EV6/LWT", "Online")
    client.subscribe("Kia_EV6/getAll/#")
    client.subscribe("Kia_EV6/charging/#")
    client.subscribe("Kia_EV6/climate/#")
    client.subscribe("Kia_EV6/lock_state/#")
    client.subscribe("Kia_EV6/charge_port/#")

def on_message(client, userdata, msg):
  vm.check_and_refresh_token()
  
  if msg.topic == "Kia_EV6/getAll":
    
    client.publish("Kia_EV6/command", "pending")
    client.loop(5)
    get_full_status()
    client.publish("Kia_EV6/command", "idle")
    
  elif msg.topic == "Kia_EV6/climate" and str(msg.payload) == "b'start'":
    
    client.publish("Kia_EV6/command", "pending")
    client.loop(5)
    vm.start_climate(vehicle_id)
    sleep(60)
    client.publish("Kia_EV6/command", "idle")
    
  elif msg.topic == "Kia_EV6/climate" and str(msg.payload) == "b'stop'":
    
    client.publish("Kia_EV6/command", "pending")
    client.loop(5)
    vm.stop_climate(vehicle_id)
    sleep(60)
    client.publish("Kia_EV6/command", "idle")
    
  elif msg.topic == "Kia_EV6/lock_state" and str(msg.payload) == "b'lock'":
    
    client.publish("Kia_EV6/command", "pending")
    client.loop(5)
    vm.lock(vehicle_id)
    sleep(60)
    client.publish("Kia_EV6/command", "idle")
    
  elif msg.topic == "Kia_EV6/lock_state" and str(msg.payload) == "b'unlock'":
    
    client.publish("Kia_EV6/command", "pending")
    client.loop(5)
    vm.unlock(vehicle_id)
    sleep(60)
    client.publish("Kia_EV6/command", "idle")
    
  elif msg.topic == "Kia_EV6/chargeing" and str(msg.payload) == "b'start'":
    
    client.publish("Kia_EV6/command", "pending")
    client.loop(5)
    vm.start_charge(vehicle_id)
    sleep(60)
    client.publish("Kia_EV6/command", "idle")
    
  elif msg.topic == "Kia_EV6/charging" and str(msg.payload) == "b'stop'":
    
    client.publish("Kia_EV6/command", "pending")
    client.loop(5)
    vm.stop_charge(vehicle_id)
    sleep(60)
    client.publish("Kia_EV6/command", "idle")
    
  elif msg.topic == "Kia_EV6/charge_port" and str(msg.payload) == "b'open'":
    
    client.publish("Kia_EV6/command", "pending")
    client.loop(5)
    vm.open_charge_port(vehicle_id)
    sleep(60)
    client.publish("Kia_EV6/command", "idle")
    
  elif msg.topic == "Kia_EV6/charge_port" and str(msg.payload) == "b'close'":
    
    client.publish("Kia_EV6/command", "pending")
    client.loop(5)
    vm.close_charge_port(vehicle_id)
    sleep(60)
    client.publish("Kia_EV6/command", "idle")

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
      client.publish("Kia_EV6/vehicle_id", ret.rstrip("'"))
    else:
      client.publish("Kia_EV6/" + searchValue.rstrip("='"), ret.rstrip("'"))
      
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
   client = mqtt.Client("my_Kia_EV6")
   client.username_pw_set(mqttuser, mqttpasswort)
   client.on_connect = on_connect
   client.on_message = on_message
   client.will_set("Kia_EV6/LWT", "Offline", qos=0, retain=False)
   client.reconnect_delay_set(min_delay=1, max_delay=120)
   client.connect_async(mqttBroker, mqttport,30)
   client.loop_start()
except:
   print("Die Ip Adresse des Brokers ist falsch!")
   sys.exit()

while 1:
  
  sleep(60)
