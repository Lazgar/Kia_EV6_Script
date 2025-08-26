from hyundai_kia_connect_api import *
import paho.mqtt.client as mqtt
import sys
import os
import string
from time import sleep
from datetime import datetime, timedelta

vm = VehicleManager(region=1, brand=1, username="andreas@markl.biz", password="2@9b7j1q4r5B6!3g8", pin="1025", language="de")
getValues = ["is_locked=","odometer_value=","ev_battery_percentage=","car_battery_percentage=","ev_driving_range="]

useMQTT = True
mqttBroker = "10.0.0.3"
mqttuser ="fhemqtt"
mqttpasswort = "2O9c7l1q4t5w6"
mqttport = 1883

def on_connect(client, userdata, flags, rc):
    client.publish("Kia_EV6/LWT", "Online")

try:
   client = mqtt.Client("Kia")
   client.username_pw_set(mqttuser, mqttpasswort)
   client.on_connect = on_connect
   client.will_set("Kia_EV6/LWT", "Offline", qos=0, retain=False)
   client.reconnect_delay_set(min_delay=1, max_delay=120)
   client.connect(mqttBroker, mqttport)
   client.loop_start()
except:
   print("Die Ip Adresse des Brokers ist falsch!")
   sys.exit()

while 1:

  vm.check_and_refresh_token()
  vm.update_all_vehicles_with_cached_state()

  string = str(vm.get_vehicle('872d889e-17f8-4af9-b394-e1f477b49c61'))

  print(string)

  connected = False
  while not connected:
    try:
      client.reconnect()
      connected = True
    except:
      print("Lost Connection to MQTT...Trying to reconnect in 2 Seconds")
      time.sleep(2)

  for searchValue in getValues:

    start = string.find(searchValue)
    end = string.find(",",start)

    ret = string[start + len(searchValue):end]
    client.publish("Kia_EV6/" + searchValue.rstrip("="), ret)

  sleep(300)
