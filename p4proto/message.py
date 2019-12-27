from functools import reduce

import asyncio
import operator

class Message:
    def __init__(self, args=None, syms=None):
        self.args = args if args is not None else []
        self.syms = syms if syms is not None else {}

    def __repr__(self):
        return '{}({!r}, {!r})'.format(
            self.__class__.__name__, self.args, self.syms)

    def get_sym_list(self, name):
        index = 0
        while True:
            prop = name + str(index).encode()
            index = index + 1
            if prop not in self.syms:
                return
            yield self.syms[prop]

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

    def to_stream_writer(self, writer):
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
