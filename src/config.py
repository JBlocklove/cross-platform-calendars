# src/config.py
#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
import yaml

SUPPORTED_TYPES = ('caldav', 'google')

def get_config_path() -> Path:
    """
    Locate the YAML config file:
      1. $SYNC_CONFIG
      2. $XDG_CONFIG_HOME/omnicalendar/config.yaml
      3. $HOME/.config/omnicalendar/config.yaml
    """
    if 'SYNC_CONFIG' in os.environ:
        return Path(os.environ['SYNC_CONFIG']).expanduser()
    xdg_cfg = Path(os.getenv('XDG_CONFIG_HOME', Path.home() / '.config'))
    return xdg_cfg / 'omnicalendar' / 'config.yaml'


def get_state_dir() -> Path:
    """
    Determine base directory for state files:
      1. `state_dir` in config
      2. $XDG_DATA_HOME/omnicalendar/state
      3. $HOME/.local/share/omnicalendar/state
    """
    xdg_data = Path(os.getenv('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
    return xdg_data / 'omnicalendar' / 'state'


def load_config() -> dict:
    """
    Load and validate configuration.

    Returns:
      {
        'accounts': { name: params_dict, ... },
        'mappings': [ ... ],
        'state_base': Path
      }
    """
    cfg_path = get_config_path()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")

    raw = yaml.safe_load(cfg_path.read_text()) or {}

    # Determine state directory
    if 'state_dir' in raw:
        state_base = Path(raw['state_dir']).expanduser()
    else:
        state_base = get_state_dir()
    state_base.mkdir(parents=True, exist_ok=True)

    # Parse account definitions
    accounts_list = raw.get('accounts')
    if not isinstance(accounts_list, list) or not accounts_list:
        raise KeyError("'accounts' must be a non-empty list in config")

    accounts = {}
    for entry in accounts_list:
        typ  = entry.get('type')
        name = entry.get('name')
        if not typ or not name:
            raise KeyError("Each account must have 'type' and 'name'")
        if typ not in SUPPORTED_TYPES:
            raise KeyError(f"Unsupported account type '{typ}' for '{name}'")
        if name in accounts:
            raise KeyError(f"Duplicate account name '{name}' in config")

        params = {}
        if typ == 'caldav':
            for key in ('url', 'username'):
                if key not in entry:
                    raise KeyError(f"Missing '{key}' for CalDAV account '{name}'")
            # password or command
            if 'password_cmd' in entry:
                pwd = subprocess.check_output(
                    entry['password_cmd'], shell=True, text=True
                ).strip()
            elif 'password' in entry:
                pwd = entry['password']
            else:
                raise KeyError(f"CalDAV account '{name}' needs 'password' or 'password_cmd'")
            params = {
                'type': 'caldav',
                'url': entry['url'],
                'username': entry['username'],
                'password': pwd,
            }

        elif typ == 'google':
            for key in ('credentials_path', 'token_path'):
                if key not in entry:
                    raise KeyError(f"Missing '{key}' for Google account '{name}'")
            params = {
                'type': 'google',
                'credentials_path': Path(entry['credentials_path']).expanduser(),
                'token_path': Path(entry['token_path']).expanduser(),
            }

        accounts[name] = params

    # Parse sync mappings
    mappings = raw.get('sync', {}).get('mappings', [])
    if not isinstance(mappings, list):
        raise KeyError("'sync.mappings' must be a list in config")

    return {
        'accounts': accounts,
        'mappings': mappings,
        'state_base': state_base,
    }


def print_config():
    """Load and pretty-print the current configuration for debugging."""
    cfg = load_config()
    from pprint import pprint
    pprint({
        'accounts': cfg['accounts'],
        'mappings': cfg['mappings'],
        'state_base': str(cfg['state_base']),
    })


if __name__ == '__main__':
    print_config()

