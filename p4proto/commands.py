from .env import Environment
from .message import Message
import hashlib, re, socket

def client_crypto(conn, msg):
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
