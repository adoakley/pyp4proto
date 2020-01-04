#!/usr/bin/env python3

import argparse
import asyncio
import socket
import os
import p4proto

async def logging_proxy(server, local_port):
    count = 0

    loop = asyncio.get_event_loop()
    server = p4proto.parse_p4port(server)

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
            msg = await p4proto.Message.from_stream_reader(reader)
            if msg is None:
                writer.close()
                return
            print(log_prefix, msg)
            msg.to_stream_writer(writer)

    loop.create_task(
        asyncio.start_server(handle_client, port=local_port))

async def run_command(env, cmd, *args, **syms):
    connection = await p4proto.connect(env)
    await connection.run(cmd, p4proto.BaseClientCommandHandler(), *args, **syms)

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
    env = p4proto.Environment(
        args.directory,
        {k: v for (k, v) in vars(args).items()
            if k.startswith('P4') and v is not None})
    args.func(args, env)
