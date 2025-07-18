# sync_main.py
#!/usr/bin/env python3
import os
import sys
import logging
from pathlib import Path

from src.config import load_config
from src.sync import sync_caldav_caldav, sync_caldav_busy, sync_caldav_full_oneway
from src.caldav_client import CaldavClient
from src.google_client import GoogleCalendarClient

def main():
    # Load configuration
    try:
        cfg = load_config()
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Instantiate clients
    clients = {}
    for name, params in cfg['accounts'].items():
        if params['type'] == 'caldav':
            clients[name] = CaldavClient(
                url=params['url'],
                username=params['username'],
                password=params['password'],
            )
        elif params['type'] == 'google':
            clients[name] = GoogleCalendarClient(
                credentials_path=params['credentials_path'],
                token_path=params['token_path'],
            )

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        datefmt='%H:%M:%S',
    )

    # Process mappings
    mappings = cfg['mappings']
    if not mappings:
        print("No sync mappings defined.", file=sys.stderr)
        sys.exit(1)

    state_base = cfg['state_base']
    for mapping in mappings:
        src = mapping['source']
        tgt = mapping['target']
        mode = mapping.get('mode', 'full').lower()

        acct_src, cal_src = src['account'], src['calendar']
        acct_tgt, cal_tgt = tgt['account'], tgt['calendar']

        if acct_src not in clients or acct_tgt not in clients:
            print(f"Unknown account '{acct_src}' or '{acct_tgt}'", file=sys.stderr)
            sys.exit(1)

        client_src = clients[acct_src]
        client_tgt = clients[acct_tgt]

        if mode == 'full':
            state_file = state_base / f"{acct_src}__{cal_src}__{acct_tgt}__{cal_tgt}__full.json"
            print(f"[Full-sync] {acct_src}:{cal_src} ↔ {acct_tgt}:{cal_tgt}")
            sync_caldav_caldav(
                client_src, cal_src,
                client_tgt, cal_tgt,
                state_path=str(state_file),
            )

        elif mode == 'busy':
            busy_state = state_base / f"{acct_src}__{cal_src}__{acct_tgt}__{cal_tgt}__busy.json"
            full_state = state_base / f"{acct_tgt}__{cal_tgt}__{acct_src}__{cal_src}__full.json"
            print(f"[Busy-sync] {acct_src}:{cal_src} → {acct_tgt}:{cal_tgt}")
            sync_caldav_busy(
                client_src, cal_src,
                client_tgt, cal_tgt,
                state_path=str(busy_state),
            )
            print(f"[Full-sync One-way] {acct_tgt}:{cal_tgt} → {acct_src}:{cal_src}")
            sync_caldav_full_oneway(
                client_tgt, cal_tgt,
                client_src, cal_src,
                state_path=str(full_state),
            )

        else:
            print(f"Unsupported mode '{mode}'", file=sys.stderr)
            sys.exit(1)

    print("✅ All sync operations completed.")

if __name__ == '__main__':
    main()
