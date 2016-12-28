# Copyright 2016 Robert Jordens <jordens@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
from collections import namedtuple
import asyncio

import dbus

from ble import (AsyncInterface, Adapter, Device, Service, Characteristic,
                 MANAGER, BLUEZ, ADAPTER, DEVICE, SERVICE, CHARACTERISTIC,
                 ble_uuid128)


logger = logging.getLogger(__name__)


def ti_uuid128(ti_uuid16):
    return "{:08x}-0451-4000-b000-000000000000".format(ti_uuid16 | 0xf0000000)


class Sensor(Service):
    uuids = None
    enable = (1).to_bytes(1, "little")

    async def start(self, objs):
        chars = {ifaces[CHARACTERISTIC]["UUID"]: path
                 for path, ifaces in objs.items()
                 if path.startswith(self.path + "/") and
                 CHARACTERISTIC in ifaces}
        self.data = Characteristic(
            self.bus, chars[ti_uuid128(self.uuids.data)], self.loop)
        self.conf = Characteristic(
            self.bus, chars[ti_uuid128(self.uuids.conf)], self.loop)
        self.period = Characteristic(
            self.bus, chars[ti_uuid128(self.uuids.period)], self.loop)
        await self.data.start_notify()

    def mu_to_si(self, value):
        return value

    async def measure(self):
        await self.conf.characteristic.WriteValue(self.enable, {})
        while True:
            value = await self.data.changed("Value")
            if any(value):
                break
        value = self.mu_to_si(value)
        await self.conf.characteristic.WriteValue(
            (0).to_bytes(len(self.enable), "little"), {})
        return value


TIUUIDs = namedtuple("TIUUIDs", "service data conf period")


class Temperature(Sensor):
    uuids = TIUUIDs(
        service=0xaa00, data=0xaa01, conf=0xaa02, period=0xaa03)

    def mu_to_si(self, value):
        t = [int.from_bytes(value[i:i + 2], "little", signed=True) / (1 << 7)
             for i in (0, 2)]
        return {"temp_ir": t[0], "temp_die": t[1]}


class Humidity(Sensor):
    uuids = TIUUIDs(0xaa20, 0xaa21, 0xaa22, 0xaa23)

    def mu_to_si(self, value):
        temp = int.from_bytes(value[:2], "little", signed=True) * (
            165/(1 << 16)) - 40
        humidity = int.from_bytes(value[2:], "little") * 100 / (1 << 16)
        return {"temp_rh": temp, "humidity": humidity}


class Pressure(Sensor):
    uuids = TIUUIDs(0xaa40, 0xaa41, 0xaa42, 0xaa44)

    def mu_to_si(self, value):
        temp, pressure = (
            int.from_bytes(value[i:i + 3], "little", signed=True) / 100
            for i in (0, 3))
        return {"temp_p": temp, "pressure": pressure}


class Light(Sensor):
    uuids = TIUUIDs(0xaa70, 0xaa71, 0xaa72, 0xaa73)

    def mu_to_si(self, value):
        lux = int.from_bytes(value, "little")
        lux = .01 * ((lux & 0x0fff) << (lux >> 12))
        return {"lux": lux}


class Motion(Sensor):
    uuids = TIUUIDs(0xaa80, 0xaa81, 0xaa82, 0xaa83)
    acc_range = 2
    enable = (0x007f | ([2, 4, 8, 16].index(acc_range) << 8)
              ).to_bytes(2, "little")

    def mu_to_si(self, value):
        v = [int.from_bytes(value[i:i + 2], "little", signed=True)
             for i in range(0, len(value), 2)]
        assert len(v) == 9, v
        gyro = [vi*250/(1 << 15) for vi in v[:3]]  # deg/s
        acc = [vi*self.acc_range/(1 << 15) for vi in v[3:6]]  # G
        mag = [vi*1. for vi in v[6:]]  # µT
        return {"gyro_x": gyro[0], "gyro_y": gyro[1], "gyro_z": gyro[2],
                "acc_x": acc[0], "acc_y": acc[1], "acc_z": acc[2],
                "mag_x": mag[0], "mag_y": mag[1], "mag_z": mag[2]}


class Tag(Device):
    min_rssi = -110

    def __init__(self, top, path, loop):
        super().__init__(top.bus, path, loop)
        self.top = top
        self.connecting = False
        logger.debug("Add Tag %s", path)

    def _properties_changed_cb(self, interface, changed, invalidated):
        for prop, change in changed.items():
            logger.debug("Prop changed %s %s %s=%s", self.path, interface,
                         prop, change)
        if changed.get("RSSI", self.min_rssi) > self.min_rssi:
            self.loop.create_task(self.start())
        if changed.get("ServicesResolved", False):
            self.loop.create_task(self.populate())

    async def start(self):
        if not (await self.properties.Get(DEVICE, "Connected") and
                self.connecting):
            logger.debug("Connecting %s", self.path)
            self.connecting = True
            try:
                await self.device.Connect()
            finally:
                self.connecting = False
            logger.info("Connected %s", self.path)
        if await self.properties.Get(DEVICE, "ServicesResolved"):
            await self.populate()

    async def populate(self):
        logger.debug("Populate %s", self.path)
        self.address = await self.properties.Get(DEVICE, "Address")

        objs = await self.top.manager.GetManagedObjects()
        services = {ifaces[SERVICE]["UUID"]: path
                    for path, ifaces in objs.items()
                    if path.startswith(self.path + "/") and
                    SERVICE in ifaces}
        for T in Temperature, Pressure, Light, Humidity, Motion:
            sensor = T(self.bus, services[ti_uuid128(T.uuids.service)],
                       self.loop)
            setattr(self, T.__name__.lower(), sensor)
            await sensor.start(objs)
            await sensor.period.characteristic.WriteValue([0xff], {})

        # self.io = Sensor(0xaa65, 0xaa65)
        # self.keys = Sensor(0xffe1)
        # self.ccs = 0xccc1, 0xccc2, 0xccc3
        # self.reg = 0xac01, 0xac02, 0xac03


class TagManager:
    _auto_discover = False

    def __init__(self, loop=None):
        if loop is None:
            loop = asyncio.get_event_loop()
        self.loop = loop

        self.devices = {}

        self.bus = dbus.SystemBus()
        self.manager = AsyncInterface(
            self.bus.get_object(BLUEZ, "/"),
            MANAGER,
            loop)
        self.bus.add_signal_receiver(
            self._interfaces_added,
            dbus_interface=MANAGER,
            signal_name="InterfacesAdded")
        self.bus.add_signal_receiver(
            self._interfaces_removed,
            dbus_interface=MANAGER,
            signal_name="InterfacesRemoved")

    def _interfaces_added(self, path, ifaces):
        self.loop.create_task(self._maybe_add(path, ifaces))

    def _interfaces_removed(self, path, ifaces):
        pass

    async def _maybe_add(self, path, ifaces):
        if DEVICE not in ifaces or path in self.devices:
            return
        uuids = [str(s) for s in ifaces[DEVICE]["UUIDs"]]
        if not (ble_uuid128(Motion.uuids.service) in uuids or
                ti_uuid128(Motion.uuids.service) in uuids):
            return
        self.devices[path] = dev = Tag(self, path, self.loop)
        await dev.start()  # FIXME: can fail

    async def start(self):
        for path, ifaces in (await self.manager.GetManagedObjects()).items():
            await self._maybe_add(path, ifaces)

    async def start_discovery(self):
        for path, ifaces in (await self.manager.GetManagedObjects()).items():
            if ADAPTER not in ifaces:
                continue
            adapter = Adapter(self.bus, path, self.loop)
            if not await adapter.properties.Get(ADAPTER, "Powered"):
                await adapter.properties.Set(ADAPTER, "Powered", True)
            await adapter.adapter.SetDiscoveryFilter(dict(
                UUIDs=[
                    ble_uuid128(Motion.uuids.service),
                    ti_uuid128(Motion.uuids.service)
                ],
                Transport="le"))
            if not await adapter.properties.Get(ADAPTER, "Discovering"):
                await adapter.adapter.StartDiscovery()

    async def auto_discover(self, interval=60):
        while True:
            await self.start_discovery()  # FIXME can fail
            await asyncio.sleep(interval)
