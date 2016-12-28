import logging
from functools import wraps
from collections import defaultdict
import asyncio

import dbus


logger = logging.getLogger(__name__)

MANAGER = "org.freedesktop.DBus.ObjectManager"
PROPERTIES = "org.freedesktop.DBus.Properties"

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
            dbus_interface=dbus.PROPERTIES_IFACE,
            signal_name="PropertiesChanged",
            path=path)

    def _properties_changed_cb(self, interface, changed, invalidated):
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


class Characteristic(Properties):
    interfaces = {"characteristic": CHARACTERISTIC}

    def __init__(self, bus, path, loop):
        super().__init__(bus, path, loop)

    async def start_notify(self):
        if await self.properties.Get(CHARACTERISTIC, "Notifying"):
            return
        await self.characteristic.StartNotify()


class Service(Properties):
    interfaces = {"service": SERVICE}


class Device(Properties):
    interfaces = {"device": DEVICE}


class Adapter(Properties):
    interfaces = {"adapter": ADAPTER}
