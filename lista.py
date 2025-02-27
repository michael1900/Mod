#!/usr/bin/env python3

import requests
import json
import logging
import sys
import re

# Carica configurazione generale e icone
def load_config():
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    
    with open("icons.json", "r", encoding="utf-8") as f:
        icons = json.load(f)
    
    return config, icons

config, icons = load_config()

def get_auth_signature():
    try:
        response = requests.post("https://www.vavoo.tv/api/app/ping", json=config["signature_request"], headers=config["headers"])
        response.raise_for_status()
        return response.json().get("addonSig")
    except Exception as e:
        print(f"Errore durante il recupero della firma: {e}")
        return None

def setup_logging():
    logging.basicConfig(filename="excluded_channels.log", level=logging.INFO, format="%(asctime)s - %(message)s")

# Funzione per pulire il nome del canale
def sanitize_channel_name(name):
    return re.sub(r"[\s.][a-zA-Z]$", "", name).replace(" ", "").replace(".", "")

def get_category(channel_name):
    lower_name = channel_name.lower()
    for category, keywords in config["category_keywords"].items():
        if any(keyword in lower_name for keyword in keywords):
            return category
    return "ALTRI"

def get_channel_list(signature):
    headers = {
        "Accept-Encoding": "gzip",
        "User-Agent": "MediaHubMX/2",
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
        "mediahubmx-signature": signature
    }
    
    cursor = 0
    all_items = []

    while True:
        data = {
            "language": "de",
            "region": "AT",
            "catalogId": "vto-iptv",
            "id": "vto-iptv",
            "adult": False,
            "search": "",
            "sort": "name",
            "filter": {"group": "Italy"},
            "cursor": cursor,
            "clientVersion": "3.0.2"
        }
        
        try:
            response = requests.post("https://vavoo.to/vto-cluster/mediahubmx-catalog.json", json=data, headers=headers)
            response.raise_for_status()
            items = response.json().get("items", [])
            if not items:
                break
            all_items.extend(items)
            cursor += len(items)
        except Exception as e:
            print(f"Errore durante il recupero della lista dei canali: {e}")
            break

    return {"items": all_items}

def generate_m3u(channels_json, signature, filename="channels.m3u8"):
    setup_logging()
    items = channels_json.get("items", [])

    if not items:
        print("Nessun canale disponibile.")
        return

    print(f"Generating M3U8 file with {len(items)} channels...")

    with open(filename, "w", encoding="utf-8") as f:
        f.write('#EXTM3U url-tvg="http://epg-guide.com/it.gz"\n')

        for idx, item in enumerate(items, 1):
            name = item.get("name", "Unknown")

            if any(remove_word.lower() in name.lower() for remove_word in config["channel_remove"]):
                print(f"Skipping channel {name} (in CHANNEL_REMOVE)")
                continue

            if not any(filter_word.lower() in name.lower() for filter_word in config["channel_filters"]):
                logging.info(f"Excluded channel: {name}")
                continue

            tvg_id = sanitize_channel_name(name)
            original_link = item.get("url")

            if not original_link:
                continue

            print(f"Processing channel {idx}/{len(items)}: {name}")

            category = get_category(name)
            logo_url = icons.get(tvg_id.lower(), "")

            f.write(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_id}" tvg-logo="{logo_url}" group-title="{category}",{tvg_id}\n')
            f.write('#EXTVLCOPT:http-user-agent=okhttp/4.11.0\n')
            f.write('#EXTVLCOPT:http-origin=https://vavoo.to/\n')
            f.write('#EXTVLCOPT:http-referrer=https://vavoo.to/\n')
            f.write(f'{original_link}\n')

    print(f"M3U8 file generated successfully: {filename}")

def main():
    print("Getting authentication signature...")
    signature = get_auth_signature()
    if not signature:
        print("Failed to get authentication signature.")
        sys.exit(1)

    print("Getting channel list...")
    channels_json = get_channel_list(signature)
    if not channels_json:
        print("Failed to get channel list.")
        sys.exit(1)

    print("Generating M3U8 file...")
    generate_m3u(channels_json, signature)
    print("Done!")

if __name__ == "__main__":
    main()
