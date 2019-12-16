import os, pathlib, re

# This is intended to match the Perforce environment loading behaviour, but is
# currently missing Windows specific behaviour.

def parse_p4port(p4port):
    ssl, host, port = (False, None, None)

    # Perforce does strange things to determine if IPv4 or IPv6 should be used,
    # but we will just let the OS choose.
    prefix, colon, rest = p4port.partition(':')
    if colon:
        if prefix in ['tcp:', 'tcp4:', 'tcp6:', 'tcp46:', 'tcp64:']:
            p4port = rest
        elif prefix in ['ssl:', 'ssl4:', 'ssl6:', 'ssl46:', 'ssl64:']:
            ssl = True
            p4port = rest

    # Perforce allows any kind of address to be in square brackets, not just an
    # IPv6address.  We keep the same behaviour.
    bracketed = re.fullmatch('\[(.*)\]:?(.*)', p4port)
    if bracketed:
        host = bracketed.group(1)
        port = bracketed.group(2)
    else:
        host, colon, port = p4port.rpartition(':')

    if host == '':
        host = None

    return { 'ssl': ssl, 'host': host, 'port': port }

class Environment():
    def __init__(self, cwd, config={}):
        self.cwd = cwd
        self._home = os.path.expanduser('~')
        self._values = {}

        def loadconfig(filename):
            values = dict()
            try:
                with open(filename, 'r') as f:
                    for line in f:
                        name, eq, val = line.partition('=')
                        if eq:
                            val = val.rstrip(' \n')
                            values[name] = val
            except FileNotFoundError:
                pass
            return values
        def do_replacements(val, extra_replacements={}):
            replacements = { '$home': self._home, **extra_replacements }
            for old, new in replacements.items():
                val = val.replace(old, new)
            return val
        def add_config(config, extra_replacements={}):
            for k, v in config.items():
                self._values[k] = do_replacements(v, extra_replacements)
        def default_filename(basename):
            return do_replacements('$home/.{}'.format(basename))

        filename = do_replacements(
            os.getenv('P4ENVIRO', self._home + '/.p4enviro'))
        add_config(loadconfig(filename))

        add_config(
            {k: v for (k, v) in os.environ.items() if k.startswith('P4')})

        filename = self._values.get('P4CONFIG')
        if filename is not None:
            cwd = pathlib.Path(cwd)
            for configdir in reversed([cwd, *cwd.parents]):
                add_config(
                    loadconfig(configdir / path),
                    { '$configdir': str(configdir) })

        add_config(config)

        if 'P4PORT' not in self._values:
            self._values['P4PORT'] = 'perforce:1666'
        if 'P4USER' not in self._values:
            import pwd
            self._values['P4USER'] = pwd.getpwuid(os.getuid()).pw_name
        if 'P4HOST' not in self._values:
            import socket
            self._values['P4HOST'] = socket.gethostname()
        if 'P4CLIENT' not in self._values:
            self._values['P4CLIENT'] = self._values['P4HOST']
        if 'P4TICKETS' not in self._values:
            self._values['P4TICKETS'] = default_filename('p4tickets')
        if 'P4TRUST' not in self._values:
            self._values['P4TRUST'] = default_filename('p4trust')

    def get(self, name, default=None):
        return self._values.get(name, default)


if __name__ == '__main__':
    print(Environment(os.getcwd())._values)
