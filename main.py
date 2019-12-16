#!/usr/bin/env python3

from p4proto import Environment, Message, parse_p4port

import argparse
import asyncio
import socket
import os

async def logging_proxy(server, local_port):
    count = 0

    loop = asyncio.get_event_loop()
    server = parse_p4port(server)

    async def handle_client(reader, writer):
        nonlocal count

        # connect to upstream
        (upstream_reader, upstream_writer) = await asyncio.open_connection(
            **server)

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
            msg.to_stream_writer(writer)

    loop.create_task(
        asyncio.start_server(handle_client, port=local_port))

async def run_command(env, cmd, *args):
    server = parse_p4port(env.get('P4PORT'))
    reader, writer = await asyncio.open_connection(**server)
    sock = writer.get_extra_info('socket')

    # The protocol message is intended to match what the official 2018.1 client
    # does.  Many of the settings are hardcoded, with no indication of what
    # behaviour they are intended to control.  It seems unlikely that settings
    # not used by the official client will be tested, so it seems best to just
    # do the same thing.
    Message([], {
        b'func': b'protocol',
        b'host': env.get('P4HOST').encode(),
        b'port': server['port'].encode(),
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

    Message([arg.encode() for arg in args], {
        b'func': b'user-%s' % cmd.encode(),
        b'client': env.get('P4CLIENT').encode(),
        b'host': env.get('P4HOST').encode(),
        b'user': env.get('P4USER').encode(),
        b'cwd': env.cwd.encode(),
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
            Message([], {
                b'func': b'release2',
            }).to_stream_writer(writer)
            break

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', dest='P4PORT')
    parser.add_argument('--host', dest='P4HOST')
    parser.add_argument('--client', dest='P4CLIENT')
    parser.add_argument('--user', dest='P4USER')
    parser.add_argument('--directory', default=os.getcwd())

    subparsers = parser.add_subparsers(dest='command')

    # https://bugs.python.org/issue33109
    subparsers.required = True

    def run(opts, env):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            run_command(env, opts.command, *opts.args))
    parser_run = subparsers.add_parser('run')
    parser_run.add_argument('command')
    parser_run.add_argument('args', nargs=argparse.REMAINDER)
    parser_run.set_defaults(func=run)

    def proxy(opts, env):
        loop = asyncio.get_event_loop()
        loop.create_task(logging_proxy(env.get('P4PORT'), opts.port))
        loop.run_forever()
    parser_proxy = subparsers.add_parser('proxy')
    parser_proxy.add_argument('port')
    parser_proxy.set_defaults(func=proxy)

    args = parser.parse_args()
    env = Environment(
        args.directory,
        {k: v for (k, v) in vars(args).items()
            if k.startswith('P4') and v is not None})
    args.func(args, env)
