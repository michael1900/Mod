#!/usr/bin/env python3
import json
import os
import re
import time
import random
import threading
from urllib.parse import urlencode, quote_plus
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

# Costanti
PORT = int(os.environ.get('PORT', 3000))
FETCH_INTERVAL = 20 * 60  # 20 minuti in secondi
FETCH_TIMEOUT = 10  # 10 secondi

# Percorsi file
CONFIG_FILE = 'config.json'
HEADERS_FILE = 'headers.json'
GENRE_FILE = 'genres.json'
ICONS_FILE = 'channel_icons.json'
CHANNELS_FILE = 'channels_data.json'
SAMPLE_CHANNELS_FILE = 'sample_channels.json'

# Generi disponibili
AVAILABLE_GENRES = [
    "animation", "business", "classic", "comedy", "cooking", "culture", 
    "documentary", "education", "entertainment", "family", "kids", 
    "legislative", "lifestyle", "movies", "music", "general", "religious", 
    "news", "outdoor", "relax", "series", "science", "shop", "sports", 
    "travel", "weather", "xxx", "auto"
]

# Inizializza cartelle necessarie
os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)

# Inizializzazione FastAPI
app = FastAPI()

# Setup per servire file statici
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup per i template
templates = Jinja2Templates(directory="templates")

# Cache in memoria
channel_cache = {}

def load_json_file(filename, default=None):
    """Carica un file JSON, ritorna default se il file non esiste o non è valido"""
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as file:
                return json.load(file)
    except Exception as e:
        print(f"Errore nel caricamento di {filename}: {e}")
    return default if default is not None else {}

def save_json_file(filename, data):
    """Salva i dati in un file JSON"""
    try:
        with open(filename, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Errore nel salvataggio di {filename}: {e}")
        return False

def clean_channel_name(name):
    """Pulisce il nome del canale rimuovendo gli ultimi 3 caratteri se sono uno spazio, un punto e una lettera"""
    if len(name) > 3:
        last_three = name[-3:]
        if re.match(r'\s\.[A-Za-z]', last_three):
            return name[:-3]
    return name

def generate_id(name):
    """Genera un ID unico basato sul nome del canale"""
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', clean_channel_name(name).lower())
    return f"{clean_name}-{int(time.time())}-{random.randint(1000, 9999)}"

def assign_genre(channel_name, genre_mapping):
    """Assegna un genere al canale in base al nome o al mapping"""
    clean_name = clean_channel_name(channel_name).lower()
    
    # Controllo diretto nel mapping
    if clean_name in genre_mapping:
        return genre_mapping[clean_name]
    
    # Ricerca per parole chiave
    keywords = {
        "sport": "sports",
        "calcio": "sports",
        "football": "sports",
        "news": "news",
        "notizie": "news",
        "tg": "news",
        "film": "movies",
        "cinema": "movies",
        "movie": "movies",
        "bambini": "kids",
        "kids": "kids",
        "cartoni": "animation",
        "documentari": "documentary",
        "doc": "documentary",
        "musica": "music",
        "music": "music",
        "comedy": "comedy",
        "commedia": "comedy",
        "lifestyle": "lifestyle",
        "cucina": "cooking",
        "food": "cooking",
        "meteo": "weather",
        "weather": "weather",
        "viaggi": "travel",
        "travel": "travel",
        "serie": "series",
        "auto": "auto",
        "motor": "auto",
        "xxx": "xxx",
        "adult": "xxx",
    }
    
    for keyword, genre in keywords.items():
        if keyword in clean_name:
            return genre
    
    # Default genre
    return "general"

def create_manifest(mediaflow_url, mediaflow_psw):
    """Crea il manifest dell'addon con i parametri personalizzati"""
    return {
        "id": "org.mediaflow.iptv",
        "name": "MediaFlow IPTV",
        "version": "1.0.0",
        "description": "Watch IPTV channels from MediaFlow service",
        "resources": ["catalog", "meta", "stream"],
        "types": ["tv"],
        "catalogs": [
            {
                "type": "tv",
                "id": f"mediaflow-{genre}",
                "name": f"MediaFlow - {genre.capitalize()}",
                "extra": [{"name": "search", "isRequired": False}]
            } for genre in AVAILABLE_GENRES
        ],
        "idPrefixes": ["mediaflow-"],
        "behaviorHints": {"configurable": False, "configurationRequired": False},
        "logo": "https://dl.strem.io/addon-logo.png",
        "icon": "https://dl.strem.io/addon-logo.png",
        "background": "https://dl.strem.io/addon-background.jpg",
    }

def save_config(mediaflow_url, mediaflow_psw):
    """Salva la configurazione dell'utente"""
    config = {"mediaflow_url": mediaflow_url, "mediaflow_psw": mediaflow_psw}
    return save_json_file(CONFIG_FILE, config)

def load_config():
    """Carica la configurazione dell'utente"""
    return load_json_file(CONFIG_FILE, {"mediaflow_url": "", "mediaflow_psw": ""})

def to_meta(channel, mediaflow_url, mediaflow_psw):
    """Converte un canale in un oggetto meta formato Stremio"""
    icons = load_json_file(ICONS_FILE, {})
    channel_name = clean_channel_name(channel["name"])
    logo = icons.get(channel_name, icons.get(channel["name"], "https://dl.strem.io/addon-logo.png"))
    
    # Prepara l'URL per lo streaming attraverso MediaFlow Proxy
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
        "referer": "https://vavoo.to/",
        "origin": "https://vavoo.to"
    }
    
    params = {
        "api_password": mediaflow_psw,
        "d": channel["url"]
    }
    
    # Aggiungi headers alla query string
    for key, value in headers.items():
        params[f"h_{key}"] = value
    
    stream_url = f"https://{mediaflow_url}/proxy/hls/manifest.m3u8?{urlencode(params, quote_via=quote_plus)}"
    
    return {
        "id": f"mediaflow-{channel['id']}",
        "name": channel_name,
        "type": "tv",
        "genres": [channel.get("genre", "general")],
        "poster": logo,
        "posterShape": "square",
        "background": logo,
        "logo": logo,
        "streamInfo": {
            "url": stream_url,
            "title": channel_name
