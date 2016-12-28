import logging
import asyncio

logger = logging.getLogger(__name__)


class InfluxLineProtocol(asyncio.DatagramProtocol):
    def __init__(self, loop):
        self.loop = loop
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport

    @staticmethod
    def fmt(measurement, fields, *, tags={}, timestamp=None):
        msg = measurement
        msg = msg.replace(" ", "\\ ")
        msg = msg.replace(",", "\\,")
        for k, v in tags.items():
            k = k.replace(" ", "\\ ")
            k = k.replace(",", "\\,")
            k = k.replace("=", "\\=")
            v = v.replace(" ", "\\ ")
            v = v.replace(",", "\\,")
            v = v.replace("=", "\\=")
            msg += ",{}={}".format(k, v)
        msg += " "
        for k, v in fields.items():
            k = k.replace(" ", "\\ ")
            k = k.replace(",", "\\,")
            k = k.replace("=", "\\=")
            msg += "{:s}=".format(k)
            if isinstance(v, int):
                msg += "{:d}i".format(v)
            elif isinstance(v, float):
                msg += "{:g}".format(v)
            elif isinstance(v, bool):
                msg += "{:s}".format(v)
            elif isinstance(v, str):
                msg += '"{:s}"'.format(v.replace('"', '\\"'))
            else:
                raise TypeError(v)
            msg += ","
        if fields:
            msg = msg[:-1]
        if timestamp:
            msg += " {:d}".format(timestamp)
        return msg

    def write_one(self, *args, **kwargs):
        msg = self.fmt(*args, **kwargs)
        logger.debug(msg)
        self.transport.sendto(msg.encode())

    def write_many(self, lines):
        msg = "\n".join(lines)
        logger.debug(msg)
        self.transport.sendto(msg.encode())

    def datagram_received(self, data, addr):
        logger.error("recvd %s %s", data, addr)
        self.transport.close()

    def error_received(self, exc):
        logger.error("error %s", exc)

    def connection_lost(self, exc):
        logger.info("lost conn %s", exc)
