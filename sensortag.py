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

    def __init__(self, bus, path, loop, objs):
        super().__init__(bus, path, loop, objs)
        for name in "data conf period".split():
            chars = [c for c in self.characteristics
                     if c.uuid == ti_uuid128(getattr(self.uuids, name))]
            setattr(self, name, chars[0])

    def mu_to_si(self, value):
        return value

    async def measure(self, enable=(1).to_bytes(1, "little")):
        await self.conf.characteristic.WriteValue(enable, {})
        while True:
            value = await self.data.changed("Value")
            if any(value):
                break
        value = self.mu_to_si(value)
        await self.conf.characteristic.WriteValue(
            (0).to_bytes(len(enable), "little"), {})
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

    async def measure(self, enable=None):
        if enable is None:
            enable = (0x007f | ([2, 4, 8, 16].index(self.acc_range) << 8)
                      ).to_bytes(2, "little")
        return await super().measure(enable)

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


class ConnectionControl(Service):
    uuid_service = 0xccc0

    def __init__(self, bus, path, loop, objs):
        super().__init__(bus, path, loop, objs)
        for name, uuid in zip("current request disconnect".split(),
                              (0xccc1, 0xccc2, 0xccc3)):
            chars = [c for c in self.characteristics
                     if c.uuid == ti_uuid128(uuid)]
            setattr(self, name, chars[0])

    async def get_current(self):
        return self.mu_to_si(await self.current.characteristic.ReadValue({}))

    def mu_to_si(self, v):
        v = [int.from_bytes(v[i:i + 2], "little") for i in range(0, 6, 2)]
        return {"interval": v[0], "latency": v[1], "timeout": v[2]}

    async def set_request(self, interval_max, interval_min, latency, timeout):
        v = b"".join(vi.to_bytes(2, "little") for vi in
                     (interval_min, interval_max, latency, timeout))
        await self.request.characteristic.WriteValue(v, {})


class BatteryLevel(Service):
    uuid_service = 0x180f

    def __init__(self, bus, path, loop, objs):
        super().__init__(bus, path, loop, objs)
        self.data = [c for c in self.characteristics
                     if c.uuid == ble_uuid128(0x2a19)][0]

    async def measure(self):
        return self.mu_to_si(await self.data.characteristic.ReadValue({}))

    def mu_to_si(self, v):
        return {"battery_level": int.from_bytes(v, "little")}


class Tag(Device):
    min_rssi = -110
    cls_map = {
        ti_uuid128(Temperature.uuids.service): Temperature,
        ti_uuid128(Humidity.uuids.service): Humidity,
        ti_uuid128(Pressure.uuids.service): Pressure,
        ti_uuid128(Light.uuids.service): Light,
        ti_uuid128(Motion.uuids.service): Motion,
        ti_uuid128(ConnectionControl.uuid_service): ConnectionControl,
        # self.io = Sensor(0xaa65, 0xaa65)
        # self.keys = Sensor(0xffe1)
        # self.reg = 0xac01, 0xac02, 0xac03
        ble_uuid128(BatteryLevel.uuid_service): BatteryLevel,
    }

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
        if not (await self.properties.Get(DEVICE, "Connected") or
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
        super().populate(objs, cls_map=self.cls_map)

        for service in self.services:
            if not isinstance(service, tuple(self.cls_map.values())):
                continue
            setattr(self, service.__class__.__name__.lower(), service)
            if hasattr(service, "period"):
                # 2.55 s measurement period if enabled
                await service.period.characteristic.WriteValue([0xff], {})
            if hasattr(service, "data"):
                if not await service.data.properties.Get(
                        CHARACTERISTIC, "Notifying"):
                    await service.data.characteristic.StartNotify()

        logger.info("%s: battery %s", self.path,
                    await self.batterylevel.measure())
        await self.connectioncontrol.current.characteristic.StartNotify()
        await self.connectioncontrol.set_request(
            int(.38/1.25e-3), int(.4/1.25e-3), 0, int(6/10e-3))
        # await self.connectioncontrol.current.changed("Value")
        # await asyncio.sleep(10)
        # logger.info("%s", await self.connectioncontrol.get_current())
        # await self.connectioncontrol.disconnect.characteristic.WriteValue(
        #     [1], {})


class TagManager:
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
        self.bus.add_signal_receiver(  # TODO: disconnect
            self._interfaces_added,
            dbus_interface=MANAGER,
            signal_name="InterfacesAdded")
        self.bus.add_signal_receiver(
            self._interfaces_removed,
            dbus_interface=MANAGER,
            signal_name="InterfacesRemoved")

    def _interfaces_added(self, path, ifaces):
        self._maybe_add(path, ifaces)

    def _interfaces_removed(self, path, ifaces):
        pass

    def _maybe_add(self, path, ifaces):
        if DEVICE not in ifaces or path in self.devices:
            return
        uuids = [str(s) for s in ifaces[DEVICE]["UUIDs"]]
        if not (ble_uuid128(Motion.uuids.service) in uuids or
                ti_uuid128(Motion.uuids.service) in uuids):
            return
        self.devices[path] = dev = Tag(self, path, self.loop)
        self.loop.create_task(dev.start())

    async def start(self):
        for path, ifaces in (await self.manager.GetManagedObjects()).items():
            self._maybe_add(path, ifaces)

    async def auto_discover(self, interval=60, duration=5):
        self._auto_discover = True
        while self._auto_discover:
            for path, ifaces in (await self.manager.GetManagedObjects()
                                 ).items():
                if ADAPTER not in ifaces:
                    continue
                adapter = Adapter(self.bus, path, self.loop)
                if not await adapter.properties.Get(ADAPTER, "Powered"):
                    try:
                        await adapter.properties.Set(ADAPTER, "Powered", True)
                    except dbus.exceptions.DBusException:
                        logger.warning("could not power %s", path,
                                       exc_info=True)
                        continue
                await adapter.adapter.SetDiscoveryFilter(dict(
                    UUIDs=[
                        ble_uuid128(Motion.uuids.service),
                        ti_uuid128(Motion.uuids.service)
                    ],
                    Transport="le"))
                if not await adapter.properties.Get(ADAPTER, "Discovering"):
                    try:
                        await adapter.adapter.StartDiscovery()
                    except dbus.exceptions.DBusException:
                        logger.warning("could not start discovery on %s", path,
                                       exc_info=True)
                        continue
                    await asyncio.sleep(duration)
                    try:
                        await adapter.adapter.StopDiscovery()
                    except dbus.exceptions.DBusException:
                        logger.warning("could not stop discovery on %s", path,
                                       exc_info=True)
                        continue
            await asyncio.sleep(interval)
