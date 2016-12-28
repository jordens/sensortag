#!/usr/bin/python3

import logging
import asyncio
from configparser import ConfigParser

import gbulb
import dbus
import dbus.mainloop.glib

from influx_udp import InfluxLineProtocol
from sensortag import TagManager, DEVICE


logger = logging.getLogger(__name__)


def main():
    gbulb.install()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    loop = asyncio.get_event_loop()

    cfg = ConfigParser()
    cfg.read("logger.conf")

    logging.basicConfig(level=cfg["log"]["level"])

    async def measure(tag):
        try:
            if not (await tag.properties.Get(DEVICE, "Connected") and
                    await tag.properties.Get(DEVICE, "ServicesResolved")):
                return
        except AttributeError:
            return
        logger.debug("measuring on %s", tag.path)
        data = {}
        for k in await asyncio.gather(tag.temperature.measure(),
                                      tag.humidity.measure(),
                                      tag.pressure.measure(),
                                      tag.light.measure(),
                                      tag.motion.measure(),
                                      ):
            data.update(k)
        logger.info("%s: %s", tag.path, data)
        return InfluxLineProtocol.fmt("sensortag", data, tags=dict(
            address=tag.address))

    async def log():
        idb_transport, idb = await loop.create_datagram_endpoint(
            lambda: InfluxLineProtocol(loop),
            remote_addr=(cfg["influxdb_udp"]["host"],
                         int(cfg["influxdb_udp"]["port"])))

        m = TagManager()
        await m.start()
        loop.create_task(m.auto_discover(
            float(cfg["logger"]["discover"])))

        while True:
            await asyncio.sleep(float(cfg["logger"]["measure"]))
            done, pending = await asyncio.wait(
                [measure(tag) for tag in m.devices.values()],
                timeout=float(cfg["logger"]["timeout"]))
            for fut in pending:
                logger.warning("timeout on %s", fut)
                fut.cancel()
            for fut in done:
                if fut.exception():
                    logger.warning("exception on %s", fut)
            msg = [i.result() for i in done
                   if not i.exception() and i.result()]
            if msg:
                idb.write_many(msg)

    loop.run_until_complete(log())


if __name__ == '__main__':
    main()
