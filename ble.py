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
from functools import wraps
from collections import defaultdict
import asyncio

import dbus


logger = logging.getLogger(__name__)

MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPERTIES = dbus.PROPERTIES_IFACE

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
SERVICE = "org.bluez.GattService1"
CHARACTERISTIC = "org.bluez.GattCharacteristic1"
DESCRIPTOR = "org.bluez.GattDescriptor1"


def ble_uuid128(ble_uuid16):
    return "{:08x}-0000-1000-8000-00805f9b34fb".format(ble_uuid16)


class AsyncInterface(dbus.Interface):
    def __init__(self, path, interface, loop):
        super().__init__(path, interface)
        self.loop = loop

    def __getattr__(self, method):
        method = super().__getattr__(method)

        @wraps(method)
        def wrapper(*args, **kwargs):
            fut = self.loop.create_future()
            method(*args,
                   reply_handler=lambda *a: fut.set_result(*(a or (None,))),
                   error_handler=fut.set_exception,
                   **kwargs)
            return fut
        return wrapper


class Properties:
    interfaces = {}

    def __init__(self, bus, path, loop):
        self.bus = bus
        self.path = path
        self.loop = loop
        self.obj = bus.get_object(BLUEZ, path)
        self.properties = AsyncInterface(self.obj, PROPERTIES, loop)
        for k, v in self.interfaces.items():
            setattr(self, k, AsyncInterface(self.obj, v, loop))

        self._changed_cbs = defaultdict(lambda: [])
        self._invalidated_cbs = defaultdict(lambda: [])
        bus.add_signal_receiver(
            self._properties_changed_cb,
            dbus_interface=PROPERTIES,
            signal_name="PropertiesChanged",
            path=path)

    def _properties_changed_cb(self, interface, changed, invalidated):
        # for prop, change in changed.items():
        #     logger.debug("prop change: %s, %s=%s", self.path, prop, change)
        for prop in changed.keys() & self._changed_cbs.keys():
            for f in self._changed_cbs.pop(prop):
                f.set_result(changed[prop])
        for prop in set(invalidated) & self._invalidated_cbs.keys():
            for f in self._invalidated_cbs.pop(prop):
                f.set_result(None)

    def changed(self, prop):
        fut = self.loop.create_future()
        self._changed_cbs[prop].append(fut)
        return fut

    def invalidated(self, prop):
        fut = self.loop.create_future()
        self._invalidated_cbs[prop].append(fut)
        return fut

    def children(self, objs, interface, cls=None, cls_map=None):
        children = []
        for path, ifaces in objs.items():
            if not (path.startswith(self.path + "/") and interface in ifaces):
                continue
            uuid = ifaces[interface]["UUID"]
            k = cls
            if cls_map is not None:
                k = cls_map.get(uuid, cls)
            child = k(self.bus, path, self.loop, objs)
            child.uuid = uuid
            children.append(child)
        return children


class Descriptor(Properties):
    interfaces = {"descriptor": DESCRIPTOR}

    def __init__(self, bus, path, loop, objs):
        super().__init__(bus, path, loop)


class Characteristic(Properties):
    interfaces = {"characteristic": CHARACTERISTIC}

    def __init__(self, bus, path, loop, objs):
        super().__init__(bus, path, loop)


class Service(Properties):
    interfaces = {"service": SERVICE}

    def __init__(self, bus, path, loop, objs):
        super().__init__(bus, path, loop)
        self.characteristics = self.children(
            objs, CHARACTERISTIC, cls=Characteristic)


class Device(Properties):
    interfaces = {"device": DEVICE}

    def populate(self, objs, cls=Service, cls_map=None):
        self.services = self.children(objs, SERVICE, cls=cls, cls_map=cls_map)


class Adapter(Properties):
    interfaces = {"adapter": ADAPTER}
