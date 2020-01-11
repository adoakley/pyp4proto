from .env import Environment
from .message import Message
import hashlib, re, socket

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
            print(expand_string(fmt, msg.syms).decode())
