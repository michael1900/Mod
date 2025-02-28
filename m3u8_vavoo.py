#!/usr/bin/env python3
import requests
import json
import logging
import sys
import re
import os
import subprocess
import argparse

# Importa direttamente la funzione da chiave.py se disponibile
try:
    from chiave import get_auth_signature
except ImportError:
    # Fallback: il file chiave.py potrebbe non essere ancora stato creato
    def get_auth_signature():
        try:
            # Esegui lo script chiave.py come processo separato
            result = subprocess.run(['python3', 'chiave.py'], 
                                  capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except Exception as e:
            print(f"Errore durante l'esecuzione di chiave.py: {e}")
            return None

def setup_logging():
    logging.basicConfig(filename="excluded_channels.log", level=logging.INFO, format="%(asctime)s - %(message)s")

def sanitize_tvg_id(channel_name):
    channel_name = re.sub(r"\.[cs]$", "", channel_name, flags=re.IGNORECASE).strip()
    return " ".join(word.capitalize() for word in channel_name.split())

def load_config(filename):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def get_category(channel_name, category_keywords):
    lower_name = channel_name.lower()
    for category, keywords in category_keywords.items():
        if any(keyword.lower() in lower_name for keyword in keywords):
            return category
    return "ALTRI"

def get_logo_url(channel_name, channel_logos):
    logo_url = channel_logos.get(channel_name.lower(), "")
    if logo_url:
        return logo_url
    
    # Genera URL placeholder se non esiste un logo
    clean_name = re.sub(r"\.[cs]$", "", channel_name, flags=re.IGNORECASE).strip()
    # Rimuovi gli ultimi 3 caratteri come richiesto
    if len(clean_name) > 3:
        clean_name = clean_name[:-3]
    # Sostituisci spazi con + per l'URL
    formatted_name = clean_name.replace(" ", "+")
    return f"https://placehold.co/400x400?text={formatted_name}&.png"

def get_channel_list(signature, group="Italy"):
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
            "filter": {"group": group},
            "cursor": cursor,
            "clientVersion": "3.0.2"
        }

        try:
            response = requests.post("https://vavoo.to/vto-cluster/mediahubmx-catalog.json", json=data, headers=headers)
            response.raise_for_status()
            result = response.json()

            items = result.get("items", [])
            if not items:
                break  # Se non ci sono più canali, esce dal ciclo

            all_items.extend(items)
            cursor += len(items)  # Aggiorna il cursore con il numero di canali ricevuti

        except Exception as e:
            print(f"Errore durante il recupero della lista dei canali: {e}")
            break

    return {"items": all_items}
    
def generate_m3u(channels_json, signature, channel_filters, channel_remove, category_keywords, channel_logos, filename="channels.m3u8"):
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
            if any(remove_word.lower() in name.lower() for remove_word in channel_remove):
                print(f"Skipping channel {name} (in CHANNEL_REMOVE)")
                continue

            if not any(filter_word.lower() in name.lower() for filter_word in channel_filters):
                logging.info(f"Excluded channel: {name}")
                continue

            tvg_id = sanitize_tvg_id(name)
            original_link = item.get("url")

            if not original_link:
                continue

            print(f"Processing channel {idx}/{len(items)}: {name}")
            
            # Non risolvere il link, usarlo direttamente
            category = get_category(name, category_keywords)
            logo_url = get_logo_url(name, channel_logos)

            f.write(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_id}" tvg-logo="{logo_url}" group-title="{category}",{tvg_id}\n')
            # Aggiungi header per il player
            f.write('#EXTVLCOPT:http-user-agent=okhttp/4.11.0\n')
            f.write('#EXTVLCOPT:http-origin=https://vavoo.to/\n')
            f.write('#EXTVLCOPT:http-referrer=https://vavoo.to/\n')
            f.write('#EXTVLCOPT:mediahubmx-signature=[$KEY$]\n')  # Placeholder per la chiave di firma
            f.write(f'{original_link}\n')

    print(f"M3U8 file generated successfully: {filename}")


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Genera lista M3U8 da Vavoo')
    parser.add_argument('--get-signature', action='store_true', help='Ottieni solo la signature e stampala')
    args = parser.parse_args()

    # Se l'opzione --get-signature è specificata, stampa solo la signature e esci
    if args.get_signature:
        signature = get_auth_signature()
        if signature:
            print(signature)
            sys.exit(0)
        else:
            print("Non è stato possibile ottenere la signature")
            sys.exit(1)

    # Carica configurazioni da file separati
    channel_filters = load_config("channel_filters.json")
    if not channel_filters:
        channel_filters = CHANNEL_FILTERS  # Fallback se il file non esiste
        # Salva il file
        with open("channel_filters.json", 'w', encoding='utf-8') as f:
            json.dump(channel_filters, f, indent=4)
    
    channel_remove = load_config("channel_remove.json")
    if not channel_remove:
        channel_remove = CHANNEL_REMOVE  # Fallback
        with open("channel_remove.json", 'w', encoding='utf-8') as f:
            json.dump(channel_remove, f, indent=4)
    
    category_keywords = load_config("category_keywords.json")
    if not category_keywords:
        category_keywords = CATEGORY_KEYWORDS  # Fallback
        with open("category_keywords.json", 'w', encoding='utf-8') as f:
            json.dump(category_keywords, f, indent=4)
    
    channel_logos = load_config("channel_logos.json")
    if not channel_logos:
        channel_logos = CHANNEL_LOGOS  # Fallback
        with open("channel_logos.json", 'w', encoding='utf-8') as f:
            json.dump(channel_logos, f, indent=4)
    
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
    generate_m3u(channels_json, signature, channel_filters, channel_remove, category_keywords, channel_logos)
    print("Done!")

# Dati di fallback in caso i file non esistano
CHANNEL_FILTERS = [
    "sky", "fox", "rai", "cine34", "real time", "crime+ investigation", "top crime", "wwe", "tennis", "k2",
    "inter", "rsi", "la 7", "la7", "la 7d", "la7d", "27 twentyseven", "premium crime", "comedy central", "super!",
    "animal planet", "hgtv", "avengers grimm channel", "catfish", "rakuten", "nickelodeon", "cartoonito", "nick jr",
    "history", "nat geo", "tv8", "canale 5", "italia", "mediaset", "rete 4",
    "focus", "iris", "discovery", "dazn", "cine 34", "la 5", "giallo", "dmax", "cielo", "eurosport", "disney+", "food", "tv 8", "MOTORTREND",
    "BOING", "FRISBEE", "DEEJAY TV", "CARTOON NETWORK", "TG COM 24", "WARNER TV", "BOING PLUS", "27 TWENTY SEVEN", "TGCOM 24", "SKY UNO", "sky uno"
]

CHANNEL_REMOVE = ["maria+vision", "telepace", "uninettuno", "lombardia", "cusano", "FM italia", "Juwelo", "kiss kiss", "qvc", "rete tv", "italia 3", "fishing", "inter tv", "avengers"]

CATEGORY_KEYWORDS = {
    "SKY": ["sky cin", "tv 8", "fox", "comedy central", "animal planet", "nat geo", "tv8", "sky atl", "sky uno", "sky prima", "sky serie", "sky arte", "sky docum", "sky natu", "cielo", "history", "sky tg"],
    "RAI": ["rai"],
    "MEDIASET": ["mediaset", "canale 5", "rete 4", "italia", "focus", "tg com 24", "tgcom 24", "premium crime", "iris", "mediaset iris", "cine 34", "27 twenty seven", "27 twentyseven"],
    "DISCOVERY": ["discovery", "real time", "investigation", "top crime", "wwe", "hgtv", "nove", "dmax", "food network", "warner tv"],
    "SPORT": ["sport", "dazn", "tennis", "moto", "f1", "golf", "sportitalia", "sport italia", "solo calcio", "solocalcio"],
    "ALTRI": [],
    "BAMBINI": ["boing", "cartoon", "k2", "discovery k2", "nick", "super", "frisbee"]
}

CHANNEL_LOGOS = {
    "sky uno .c": "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/italy/sky-uno-it.png",
    "rai 1 .c": "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/italy/rai-1-it.png",
    # Il resto dei loghi è stato rimosso per brevità e sarà salvato nel file JSON
}

if __name__ == "__main__":
    main()
