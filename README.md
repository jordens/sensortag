# CC2650 SenSortag InfluxDB logger

* needs dbus, python-dbus
* needs bluez >= 5.42
* cp logger.conf.example logger.conf  # and edit

* regularly scans for SensorTags
* connects to them and activates notifications
* actively takes measurements every X seconds
