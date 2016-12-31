# CC2650 SenSortag InfluxDB logger


## Requirements

* python >= 3.5
* bluez >= 5.42
* python-dbus (and dbus) with glib event loop support
* python-gi, gir-glib
* gbulb (https://github.com/nathan-hoad/gbulb)

## Setup

* `cp logger.conf.example logger.conf`
* edit logger.conf
* `./logger.py`
* to optimize the BLE connection parameters for low power (while `logger.py` is running):
  1. determine the connection handle `XXXX` using `hcitool con`
  2. change the connection parameters using `hcitool lecup --handle=XXXX --min 304 --max 320 --latency 4`--timeout 600

## Mechanism

* regularly scans for SensorTags
* connects to them and activates notifications
* regularly takes measurements
