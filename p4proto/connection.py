import asyncio
import collections
import socket
import os

from . import commands
from .env import parse_p4port
from .error import ProtocolError
from .message import Message

async def connect(env):
    c = Connection(env)
    await c.connect()
    return c

class Connection():
    def __init__(self, env):
        self.env = env

        self._server = parse_p4port(env.get('P4PORT'))
        self._host = env.get('P4HOST')
        self._client = env.get('P4CLIENT')
        self._user = env.get('P4USER')

        self._lock = asyncio.Lock()

    async def connect(self):
        self._reader, self._writer = await asyncio.open_connection(
                **self._server)
        self.sock = self._writer.get_extra_info('socket')

        # The protocol message is intended to match what the official 2018.1
        # client does.  Many of the settings are hardcoded, with no indication
        # of what behaviour they are intended to control.  It seems unlikely
        # that settings not used by the official client will be tested, so it
        # seems best to just do the same thing.
        Message([], {
            b'func': b'protocol',
            b'host': self._host.encode(),
            b'port': self._server['port'].encode(),
            b'rcvbuf': b'%i' % self.sock.getsockopt(
                    socket.SOL_SOCKET, socket.SO_RCVBUF),
            b'sndbuf': b'%i' % self.sock.getsockopt(
                    socket.SOL_SOCKET, socket.SO_RCVBUF),

            b'api': b'99999',
            b'enableStreams': b'',
            b'enableGraph': b'',
            b'expandAndmaps': b'',

            b'cmpfile': b'',
            b'client': b'84',
        }).to_stream_writer(self._writer)

    async def _read_messages(self, handler):
        while True:
            msg = await Message.from_stream_reader(self._reader)
            if msg is None:
                # TODO: signal somehow (exception?)
                break
            func = msg.syms[b'func']
            if func == b'protocol':
                pass
            elif func == b'release':
                return
            elif func == b'flush1':
                msg.syms[b'func'] = b'flush2'
                msg.to_stream_writer(self._writer)
            # TODO: compress/compress2, echo (maybe)
            elif func.startswith(b'client-'):
                client_func = func[len(b'client-'):].decode()
                fn = getattr(handler, 'on_ipcfn_' + client_func, None)
                if fn is None:
                    raise ProtocolError(
                        "unhandled client function {}".format(client_func))
                else:
                    await fn(self, msg)
            else:
                raise ProtocolError("unhandled function {}".format(func))

    async def run(self, cmd, handler, *args, **syms):
        async with self._lock:
            Message([arg.encode() for arg in args], {
                b'func': b'user-%s' % cmd.encode(),
                b'client': self._client.encode(),
                b'host': self._host.encode(),
                b'user': self._user.encode(),
                b'cwd': self.env.cwd.encode(),
                b'prog': b'p4pyproto',
                b'version': b'0',
                b'os': b'UNIX', # always UNIX to get consistent results
                b'clientCase': b'0', # always UNIX case folding rules
                b'charset': b'1', # always UTF-8
                **{k.encode(): v for k, v in syms.items()}
            }).to_stream_writer(self._writer)
            await self._read_messages(handler)

    def write_message(self, message):
        message.to_stream_writer(self._writer)
