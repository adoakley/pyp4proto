#!/usr/bin/env python3

from functools import reduce
import argparse
import asyncio
import operator
import socket
import os

def parse_server(server):
    # TODO: make this more similar to P4PORT parsing
    if not server:
        server = 'perforce:1666'
    host, _, port = server.rpartition(':')
    if not host:
        host = 'localhost'
    return {'host': host, 'port': port}

def get_default_user():
    # this sequence of calls matches what the official p4 client does
    if os.name == 'nt':
        user = os.environ.get('USERNAME')
        if not user:
            user = os.getlogin()
    else:
        user = os.environ.get('USER')
        if not user:
            import pwd
            user = pwd.getpwuid(os.getuid()).pw_name
    return user

class Message:
    def __init__(self, args=None, syms=None):
        self.args = args if args is not None else []
        self.syms = syms if syms is not None else {}

    def __repr__(self):
        return '{}({!r}, {!r})'.format(
            self.__class__.__name__, self.args, self.syms)

    @staticmethod
    async def from_stream_reader(reader):
        # read header, handle closed connection gracefully
        try:
            header = await reader.readexactly(5)
        except asyncio.streams.IncompleteReadError as e:
            if not e.partial:
                return None
            raise

        # parse header
        length = int.from_bytes(header[1:], byteorder='little')
        if header[0] != reduce(operator.xor, header[1:], 0):
            raise "header checksum failed"

        # read body
        body = await reader.readexactly(length)
        args, syms = [], {}
        pos = 0
        while pos < len(body):
            # null-terminated name
            off = body.index(b'\0', pos)
            name = body[pos:off]
            pos = off + 1
            # 4 byte length
            length = int.from_bytes(body[pos:pos+4], byteorder='little')
            pos = pos + 4
            # null-terminated value
            value = body[pos:pos+length]
            pos = pos + length + 1
            if name:
                syms[name] = value
            else:
                args.append(value)

        return Message(args, syms)

    async def to_stream_writer(self, writer):
        body = b''
        for value in self.args:
            body = body + b'\0' + \
                len(value).to_bytes(4, byteorder='little') + value + b'\0'
        for name, value in self.syms.items():
            body = body + name + b'\0' + \
                len(value).to_bytes(4, byteorder='little') + value + b'\0'
        length = len(body).to_bytes(4, byteorder='little')
        check = reduce(operator.xor, length, 0)
        writer.write(bytes([check]) + length)
        writer.write(body)

async def logging_proxy(loop, opts, local_port):
    async def handle_client(reader, writer):
        # connect to upstream
        (upstream_reader, upstream_writer) = await asyncio.open_connection(
            **opts.server, loop=loop)

        # forward data between the two, with logging
        loop.create_task(log_and_forward(">", reader, upstream_writer))
        loop.create_task(log_and_forward("<", upstream_reader, writer))

    async def log_and_forward(log_prefix, reader, writer):
        while True:
            msg = await Message.from_stream_reader(reader)
            if msg is None:
                writer.close()
                return
            print(log_prefix, msg)
            await msg.to_stream_writer(writer)

    loop.create_task(
        asyncio.start_server(handle_client, port=local_port, loop=loop))

async def run_command(loop, opts, cmd, *args):
    reader, writer = await asyncio.open_connection(**opts.server, loop=loop)
    sock = writer.get_extra_info('socket')

    # The protocol message is intended to match what the official 2018.1 client
    # does.  Many of the settings are hardcoded, with no indication of what
    # behaviour they are intended to control.  It seems unlikely that settings
    # not used by the official client will be tested, so it seems best to just
    # do the same thing.
    await Message([], {
        b'func': b'protocol',
        b'host': opts.host.encode(),
        b'port': opts.server['port'].encode(),
        b'rcvbuf': b'%i' % sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF),
        b'sndbuf': b'%i' % sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF),

        # from clientRunCommand
        b'api': b'99999',
        b'enableStreams': b'',
        b'enableGraph': b'',
        b'expandAndmaps': b'',

        # from Client::Client
        b'cmpfile': b'',
        b'client': b'84',
    }).to_stream_writer(writer)

    await Message([arg.encode() for arg in args], {
        b'func': b'user-%s' % cmd.encode(),
        b'client': opts.client.encode(),
        b'host': opts.host.encode(),
        b'user': opts.user.encode(),
        b'cwd': opts.directory.encode(),
        b'prog': b'p4pyproto',
        b'version': b'0',
        b'os': b'UNIX', # always UNIX to get consistent results
        b'clientCase': b'0', # always UNIX case folding rules
        b'charset': b'1', # always UTF-8
    }).to_stream_writer(writer)

    while True:
        msg = await Message.from_stream_reader(reader)
        if msg is None:
            break
        print("<", msg)
        if msg.syms[b'func'] == b'release':
            await Message([], {
                b'func': b'release2',
            }).to_stream_writer(writer)
            break

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', default=os.environ.get('P4PORT'))
    parser.add_argument('--client', default=os.environ.get('P4CLIENT'))
    parser.add_argument('--host', default=os.environ.get('P4HOST'))
    parser.add_argument('--user', default=os.environ.get('P4USER'))
    parser.add_argument('--directory', default=os.getcwd())

    subparsers = parser.add_subparsers(dest='command')

    # https://bugs.python.org/issue33109
    subparsers.required = True

    def run(opts):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_command(loop, opts, opts.command, *opts.args))
    parser_run = subparsers.add_parser('run')
    parser_run.add_argument('command')
    parser_run.add_argument('args', nargs=argparse.REMAINDER)
    parser_run.set_defaults(func=run)

    def proxy(opts):
        loop = asyncio.get_event_loop()
        loop.create_task(logging_proxy(loop, opts, opts.port))
        loop.run_forever()
    parser_proxy = subparsers.add_parser('proxy')
    parser_proxy.add_argument('port')
    parser_proxy.set_defaults(func=proxy)

    args = parser.parse_args()

    args.server = parse_server(args.server)
    if args.host is None:
        args.host = socket.gethostname()
    if args.client is None:
        args.client = args.host
    if args.user is None:
        args.user = get_default_user()

    args.func(args)
