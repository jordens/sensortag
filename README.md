# CC2650 SenSortag InfluxDB logger


## Requirements

* python >= 3.5
* bluez >= 5.42
* python-dbus (and dbus)
* gbulb (https://github.com/nathan-hoad/gbulb)

## Setup

* `cp logger.conf.example logger.conf`
* edit logger.conf
* `./logger.py`

## Mechanism

* regularly scans for SensorTags
* connects to them and activates notifications
* regularly takes measurements
