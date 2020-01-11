from .env import Environment
from .message import Message
import hashlib, re, socket, sys

expand_string_pattern = re.compile(rb"""
    (?: %' (?P<raw>.*?) '% ) |
    (?:
        \[
            (?P<pre>[^[%]*)
            % (?P<var>[^%]*) %
            (?P<post>[^]|]*)
            (?: | (?P<alt>[^]]*) )?
        \]
    ) |
    (?: % (?P<simple>[^%]*) %)""", re.VERBOSE)
def expand_string(string, values):
    def do_replace(match):
        raw = match['raw']
        if raw is not None:
            return raw

        var = match['var']
        if var is not None:
            if var in values:
                return b''.join([
                    match['pre'] or b'',
                    values[var],
                    match['post'] or b''])
            else:
                return match['alt'] or b''

        simple = match['simple']
        if simple is not None:
            if simple in values:
                return values[simple]
            else:
                return b''
    return expand_string_pattern.sub(do_replace, string)

class BaseClientCommandHandler:
    def __init__(self, *, quiet=False):
        self._quiet = quiet
        self._fstat_partial = {}

    async def on_ipcfn_Crypto(self, conn, msg):
        daddr = 'unknown'
        if conn.sock.family == socket.AF_INET:
            daddr = '{peer[0]}:{peer[1]}'.format(peer=conn.sock.getpeername())
        elif conn.sock.family == socket.AF_INET6:
            daddr = '[{peer[0]}]:{peer[1]}'.format(peer=conn.sock.getpeername())

        def to_hex_bytes(value):
            return value.hex().upper().encode()
        def get_hash(value):
            if not re.fullmatch(br'^[0-9a-fA-F]{32}$', value):
                value = to_hex_bytes(hashlib.md5(value).digest())
            value = to_hex_bytes(hashlib.md5(msg.syms[b'token'] + value).digest())
            value = to_hex_bytes(hashlib.md5(value + daddr.encode()).digest())
            return value
        passwords = list(map(get_hash, filter(None, [
            conn.env.get_ticket(msg.syms[b'serverAddress'], msg.syms[b'user']),
            conn.env.get('P4PASSWD')])))

        response = {
            b'func': msg.syms[b'confirm'],
            b'daddr': daddr.encode() }
        if len(passwords) == 0:
            response[b'token'] = b''
        else:
            response[b'token'] = passwords[0]
            if len(passwords) > 1:
                response[b'token2'] = passwords[1]

        conn.write_message(Message([], response))

    async def on_ipcfn_Message(self, conn, msg):
        code_it = msg.get_sym_list(b'code')
        fmt_it = msg.get_sym_list(b'fmt')
        for code, fmt in zip(code_it, fmt_it):
            severity = (int(code) >> 28) & ((1 << 4) - 1)
            await self.on_message(
                severity,
                expand_string(fmt, msg.syms).decode())

    async def on_message(self, severity, msg):
        if severity >= 2:
            print(msg, file=sys.stderr)
        elif not self._quiet:
            print(msg)

    async def on_ipcfn_FstatInfo(self, conn, msg):
        self._fstat_partial.update(
            {k: v for k, v in msg.syms.items() if k != b'func'})
        await self.on_fstat_info(self._fstat_partial)
        self._fstat_partial = {}

    async def on_ipcfn_FstatPartial(self, conn, msg):
        self._fstat_partial.update(
            {k: v for k, v in msg.syms.items() if k != b'func'})

    async def on_fstat_info(self, data):
        pass
