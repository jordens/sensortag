# CC2650 SenSortag InfluxDB logger


## Requirements

* needs bluez >= 5.42
* needs python-dbus (and dbus)
* needs gbulb (https://github.com/m-labs/gbulb.git)

## Setup

* `cp logger.conf.example logger.conf`
* edit logger.conf
* `./logger.py`

## Mechanism

* regularly scans for SensorTags
* connects to them and activates notifications
* regularly takes measurements
