#!/usr/bin/env python3

from p4proto import Message, Environment

import argparse
import asyncio
import socket
import os

def parse_server(server):
    # TODO: make this more similar to P4PORT parsing
    host, _, port = server.rpartition(':')
    if not host:
        host = 'localhost'
    return {'host': host, 'port': port}

async def logging_proxy(loop, opts, local_port):
    count = 0

    async def handle_client(reader, writer):
        nonlocal count

        # connect to upstream
        (upstream_reader, upstream_writer) = await asyncio.open_connection(
            **opts.server, loop=loop)

        # forward data between the two, with logging
        print("new connection")
        loop.create_task(log_and_forward("{}>".format(count), reader, upstream_writer))
        loop.create_task(log_and_forward("{}<".format(count), upstream_reader, writer))
        count = count + 1

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

async def run_command(loop, opts, env, cmd, *args):
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

    def run(opts, env):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            run_command(loop, opts, env, opts.command, *opts.args))
    parser_run = subparsers.add_parser('run')
    parser_run.add_argument('command')
    parser_run.add_argument('args', nargs=argparse.REMAINDER)
    parser_run.set_defaults(func=run)

    def proxy(opts, env):
        loop = asyncio.get_event_loop()
        loop.create_task(logging_proxy(loop, opts, opts.port))
        loop.run_forever()
    parser_proxy = subparsers.add_parser('proxy')
    parser_proxy.add_argument('port')
    parser_proxy.set_defaults(func=proxy)

    args = parser.parse_args()

    env = Environment(args.directory)

    if not args.server:
        args.server = env.get('P4PORT', 'perforce:1666')
    if not args.host:
        args.host = socket.gethostname()
    if not args.client:
        args.client = env.get('P4CLIENT', args.host)
    if not args.user:
        args.user = env.get_user()
    args.server = parse_server(args.server)

    args.func(args, env)
