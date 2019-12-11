import os

# This is intended to match the Perforce environment loading behaviour, but is
# currently missing Windows specific behaviour.

def _do_replacements(val, replacements):
    for old, new in replacements.items():
        val = val.replace(old, new)
    return val

def _loadconfig(filename, replacements):
    values = dict()
    try:
        with open(filename, "r") as f:
            for line in f:
                name, eq, val = line.partition("=")
                if eq:
                    val = val.rstrip(" \n")
                    values[name] = _do_replacements(val, replacements)
    except FileNotFoundError:
        pass
    return values

def _getenv(name, home, default=None):
    # On Windows perforce tries reading from the registry first
    env = os.getenv(name)
    if env is not None:
        return _do_replacements(env, { "$home": home })
    else:
        return default

class Environment():
    def __init__(self, cwd):
        self._home = os.path.expanduser("~")
        self._values = dict()

        replacements = { "$home": self._home }

        # On Windows perforce doesn't have a default filename
        p4enviro = _loadconfig(
            _getenv("P4ENVIRO", self._home, self._home + "/.p4enviro"),
            replacements)

        p4config = []
        p4config_filename = _getenv("P4CONFIG", self._home, p4enviro.get("P4CONFIG"))
        if p4config_filename is not None:
            search_dir = cwd
            while True:
                path = os.path.join(search_dir, p4config_filename)
                replacements["$configdir"] = os.path.dirname(path)
                p4config.append(_loadconfig(path, replacements))
                new_search_dir = os.path.dirname(search_dir)
                if new_search_dir == search_dir:
                    break
                search_dir = new_search_dir

        for config in p4config:
            for k, v in config.items():
                if k not in self._values:
                    self._values[k] = v
        for k, v in p4enviro.items():
            if k not in self._values:
                self._values[k] = _getenv(k, self._home, v)

    def get(self, name, default=None):
        if name in self._values:
            return self._values[name]
        env = _getenv(name, self._home)
        if env:
            self._values[name] = env
            return env
        return default

    def get_user(self):
        user = self.get('P4USER')
        if not user:
            user = self.get('USER')
            if not user:
                import pwd
                user = pwd.getpwuid(os.getuid()).pw_name
        return user

if __name__ == "__main__":
    print(Environment(os.getcwd())._values)
