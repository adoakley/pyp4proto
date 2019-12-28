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
    class Command:
        def __init__(self, cmd, handler, args):
            self.cmd = cmd
            self.args = args
            self.handler = handler

            self._exception = None
            self._future = asyncio.get_event_loop().create_future()

        async def call_handler(self, func, conn, msg):
            fn = getattr(self.handler, 'on' + func.decode(), None)
            if fn is None:
                raise ProtocolError("unhandled client function {}".format(func))
            else:
                await getattr(self.handler, 'on' + func.decode())(conn, msg)

        def complete(self):
            if self._exception is None:
                self._future.set_result(None)
            else:
                self._future.set_exception(self._exception)

        def add_exception(self, e):
            if self._exception is None:
                self._exception = e

        async def wait_for_result(self):
            return await self._future

    def __init__(self, env):
        self.env = env

        self._server = parse_p4port(env.get('P4PORT'))
        self._host = env.get('P4HOST')
        self._client = env.get('P4CLIENT')
        self._user = env.get('P4USER')

        self._loop = asyncio.get_event_loop()
        self._command_queue = collections.deque()
        self._current_command = None
        self._exceptions = []

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

        asyncio.ensure_future(self._read_messages())

    def _run_queued_command(self):
        if self._command_queue and not self._current_command:
            command = self._command_queue.pop()
            self._current_command = command
            Message([arg.encode() for arg in command.args], {
                b'func': b'user-%s' % command.cmd.encode(),
                b'client': self._client.encode(),
                b'host': self._host.encode(),
                b'user': self._user.encode(),
                b'cwd': self.env.cwd.encode(),
                b'prog': b'p4pyproto',
                b'version': b'0',
                b'os': b'UNIX', # always UNIX to get consistent results
                b'clientCase': b'0', # always UNIX case folding rules
                b'charset': b'1', # always UTF-8
            }).to_stream_writer(self._writer)

    def _complete_command(self):
        command = self._current_command
        self._current_command = None

        command.complete()

        self._run_queued_command()

    async def _read_messages(self):
        while True:
            msg = await Message.from_stream_reader(self._reader)
            if msg is None:
                # TODO: signal somehow (exception?)
                break
            func = msg.syms[b'func']
            command = self._current_command
            try:
                if func == b'protocol':
                    continue
                elif func == b'release' or func == b'release2':
                    self._complete_command()
                    continue
                elif func == b'flush1':
                    msg.syms[b'func'] = b'flush2'
                    msg.to_stream_writer(self._writer)
                # TODO: compress/compress2, echo (maybe)
                elif func.startswith(b'client-'):
                    client_func = func[len(b'client-'):]
                    await command.call_handler(client_func, self, msg)
                else:
                    raise ProtocolError("unhandled function {}".format(func))
            except Exception as e:
                if command:
                    command.add_exception(e)
                else:
                    self._exceptions.append(e)

    def run(self, cmd, handler, *args):
        # Perforce doesn't support running multiple commands concurrently or
        # pipelining of commands.  To support that we would need multiple
        # connections to the server.
        #
        # The commands are added to a queue and executed on a connection that
        # isn't currently running a command.  At the moment there is only one
        # connection, but there could be a pool.

        command = Connection.Command(cmd, handler, args)
        self._command_queue.appendleft(command)

        if self._exceptions:
            for e in self._exceptions:
                command.add_exception(e)
            self._exceptions = []

        self._run_queued_command()
        return command.wait_for_result()

    def write_message(self, message):
        message.to_stream_writer(self._writer)
