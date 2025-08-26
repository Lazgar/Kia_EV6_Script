import os
from bs4 import BeautifulSoup
import curlify
import dateutil
import pytz
import certifi
import geopy
from hyundai_kia_connect_api import *

vm = VehicleManager(region=1, brand=1, username="andreas@markl.biz", password="2@9b7j1q4r5B6!3g8", pin="1025", language="de")
vm.check_and_refresh_token()
vm.update_all_vehicles_with_cached_state()
print(vm.get_vehicle('872d889e-17f8-4af9-b394-e1f477b49c61'))
