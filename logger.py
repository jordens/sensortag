#!/usr/bin/python3

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
import asyncio
from configparser import ConfigParser
import signal
import time
from argparse import ArgumentParser

import gbulb
import dbus
import dbus.mainloop.glib

from influx_udp import InfluxLineProtocol
from sensortag import TagManager, DEVICE


logger = logging.getLogger(__name__)


def main():
    p = ArgumentParser()
    p.add_argument("config")
    args = p.parse_args()

    cfg = ConfigParser()
    cfg.read(args.config)

    gbulb.install()
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    loop = asyncio.get_event_loop()

    logging.basicConfig(level=cfg["log"]["level"])

    async def measure(tag):
        try:
            if not (await tag.properties.Get(DEVICE, "Connected") and
                    await tag.properties.Get(DEVICE, "ServicesResolved") and
                    hasattr(tag, "temperature")):
                return
        except AttributeError:
            return
        logger.debug("measuring on %s", tag.path)
        t0 = time.time()
        data = {}
        for k in await asyncio.gather(# tag.temperature.measure(),
                                      tag.humidity.measure(),
                                      tag.pressure.measure(),
                                      # tag.light.measure(),
                                      # tag.motion.measure(),
                                      ):
            data.update(k)
        t = round((t0 + time.time())/2)*1000*1000*1000
        logger.info("%s: %s", tag.path, data)
        return InfluxLineProtocol.fmt("sensortag", data, tags=dict(
            address=tag.address), timestamp=t)

    async def log(m):
        idb_transport, idb = await loop.create_datagram_endpoint(
            lambda: InfluxLineProtocol(loop),
            remote_addr=(cfg["influxdb_udp"]["host"],
                         int(cfg["influxdb_udp"]["port"])))

        await m.start()

        while True:
            done, pending = await asyncio.wait(
                [measure(tag) for tag in m.devices.values()],
                timeout=float(cfg["logger"]["timeout"]))
            for fut in pending:
                logger.warning("timeout on %s", fut)
                fut.cancel()
            msg = []
            for fut in done:
                try:
                    r = fut.result()
                except:
                    logger.warning("exception in measure", exc_info=True)
                else:
                    if r:
                        msg.append(r)
            if msg:
                idb.write_many(msg)
            await asyncio.sleep(float(cfg["logger"]["measure"]))

    m = TagManager()

    log_task = loop.create_task(log(m))

    discover_task = loop.create_task(m.auto_discover(
            float(cfg["logger"]["discover_interval"]),
            float(cfg["logger"]["discover_duration"]),
    ))

    def stop():
        logger.info("stopping")
        m._auto_discover = False
        discover_task.cancel()
        log_task.cancel()
        loop.stop()

    for sig in signal.SIGINT, signal.SIGTERM:
        loop.add_signal_handler(sig, stop)

    try:
        loop.run_forever()
    finally:
        loop.close()


if __name__ == '__main__':
    main()
