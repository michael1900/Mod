#!/usr/bin/env python3
import json
import os
import re
import time
import random
import subprocess
import requests
from urllib.parse import urlencode, quote_plus, unquote
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import threading

# Percorsi base
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Costanti
PORT = int(os.environ.get('PORT', 3000))
DOMAIN = os.environ.get('DOMAIN', 'melatv0bug.duckdns.org')  # Dominio esterno
M3U8_GENERATOR = os.path.join(BASE_DIR, 'm3u8_vavoo.py')  # Script per generare la lista m3u8
CHIAVE_SCRIPT = os.path.join(BASE_DIR, 'chiave.py')  # Script per generare la signature
M3U8_FILE = os.path.join(BASE_DIR, 'channels.m3u8')  # File m3u8 generato

# Default MediaFlow settings dalle variabili d'ambiente
DEFAULT_MEDIAFLOW_URL = os.environ.get('MEDIAFLOW_DEFAULT_URL', '')
DEFAULT_MEDIAFLOW_PSW = os.environ.get('MEDIAFLOW_DEFAULT_PSW', '')

# Percorsi file
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)
HEADERS_FILE = os.path.join(DATA_DIR, 'headers.json')
ICONS_FILE = os.path.join(DATA_DIR, 'channel_icons.json')
CHANNELS_FILE = os.path.join(DATA_DIR, 'channels_data.json')
CATEGORY_KEYWORDS_FILE = os.path.join(BASE_DIR, 'category_keywords.json')  # File per le categorie

# Cache per la signature di Vavoo
vavoo_signature = None
vavoo_signature_timestamp = 0

# Inizializza cartelle necessarie
os.makedirs(os.path.join(BASE_DIR, "templates"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)

# Inizializzazione FastAPI
app = FastAPI()

# Abilita CORS per tutte le origini
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup per servire file statici
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Setup per i template
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Cache channels per non rigenerare la lista continuamente
channels_data_cache = []
channels_data_timestamp = 0

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
        # Crea la directory se non esiste
        os.makedirs(os.path.dirname(filename), exist_ok=True)
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

def extract_url_params(request: Request):
    """Estrae i parametri di mediaflow dall'URL"""
    path = request.url.path
    mediaflow_url = DEFAULT_MEDIAFLOW_URL
    mediaflow_psw = DEFAULT_MEDIAFLOW_PSW
    
    # Ottieni i parametri dall'URL
    try:
        # Cerca i parametri nel path
        if "/mfp/" in path and "/psw/" in path:
            parts = path.split("/")
            mfp_index = parts.index("mfp")
            psw_index = parts.index("psw")
            
            if mfp_index < len(parts) - 1 and psw_index < len(parts) - 1:
                mediaflow_url = unquote(parts[mfp_index + 1])
                mediaflow_psw = unquote(parts[psw_index + 1])
                print(f"Extracted from path: {mediaflow_url}, {mediaflow_psw}")
    except (ValueError, IndexError) as e:
        print(f"Errore nell'estrazione dei parametri dall'URL: {e}")
    
    return mediaflow_url, mediaflow_psw

def get_category_keywords():
    """Ottiene le categorie dal file category_keywords.json"""
    # Se il file esiste, caricalo
    if os.path.exists(CATEGORY_KEYWORDS_FILE):
        return load_json_file(CATEGORY_KEYWORDS_FILE)
    
    # Altrimenti usa categorie di default e salva il file
    default_categories = {
        "SKY": ["sky cin", "tv 8", "fox", "comedy central", "animal planet", "nat geo", "tv8", "sky atl", "sky uno"],
        "RAI": ["rai"],
        "MEDIASET": ["mediaset", "canale 5", "rete 4", "italia", "focus", "tg com 24", "premium crime", "iris"],
        "DISCOVERY": ["discovery", "real time", "investigation", "top crime", "wwe", "hgtv", "nove", "dmax"],
        "SPORT": ["sport", "dazn", "tennis", "moto", "f1", "golf", "sportitalia", "solo calcio"],
        "ALTRI": [],
        "BAMBINI": ["boing", "cartoon", "k2", "discovery k2", "nick", "super", "frisbee"]
    }
    
    # Salva le categorie di default
    save_json_file(CATEGORY_KEYWORDS_FILE, default_categories)
    return default_categories

def get_vavoo_signature():
    """Ottiene la signature per Vavoo, generando una nuova se necessario"""
    global vavoo_signature, vavoo_signature_timestamp
    current_time = time.time()
    
    # Se la signature non esiste o è scaduta (dopo 3 ore)
    if not vavoo_signature or (current_time - vavoo_signature_timestamp) > 10800:
        try:
            # Prova prima con lo script chiave.py
            if os.path.exists(CHIAVE_SCRIPT):
                print(f"Ottenimento signature da: {CHIAVE_SCRIPT}")
                result = subprocess.run(['python3', CHIAVE_SCRIPT], 
                                      capture_output=True, text=True, check=True)
                new_signature = result.stdout.strip()
                if new_signature:
                    vavoo_signature = new_signature
                    vavoo_signature_timestamp = current_time
                    print(f"Nuova signature ottenuta da chiave.py: {vavoo_signature[:10]}...")
                    return vavoo_signature
            
            # Altrimenti usa lo script m3u8_vavoo.py
            print(f"Ottenimento signature da: {M3U8_GENERATOR}")
            result = subprocess.run(['python3', M3U8_GENERATOR, '--get-signature'], 
                                  capture_output=True, text=True, check=True)
            new_signature = result.stdout.strip()
            if new_signature:
                vavoo_signature = new_signature
                vavoo_signature_timestamp = current_time
                print(f"Nuova signature ottenuta da m3u8_vavoo.py: {vavoo_signature[:10]}...")
            else:
                print("Nessuna signature ottenuta dagli script esterni")
        except Exception as e:
            print(f"Errore durante l'ottenimento della signature: {e}")
    
    return vavoo_signature

def create_manifest(mediaflow_url, mediaflow_psw):
    """Crea il manifest dell'addon con i parametri personalizzati"""
    # Carica le categorie dal file
    categories = get_category_keywords()
    
    # Usa le categorie per i cataloghi
    catalogs = []
    for category in categories.keys():
        catalogs.append({
            "type": "tv",
            "id": f"mediaflow-{category}",
            "name": f"MediaFlow - {category}",
            "extra": [{"name": "search", "isRequired": False}]
        })
    
    return {
        "id": "org.mediaflow.iptv",
        "name": "MediaFlow IPTV",
        "version": "1.0.0",
        "description": f"Watch IPTV channels from MediaFlow service ({mediaflow_url})",
        "resources": ["catalog", "meta", "stream"],
        "types": ["tv"],
        "catalogs": catalogs,
        "idPrefixes": ["mediaflow-"],
        "behaviorHints": { 
            "configurable": False,
            "configurationRequired": False
        },
        "logo": "https://dl.strem.io/addon-logo.png",
        "icon": "https://dl.strem.io/addon-logo.png",
        "background": "https://dl.strem.io/addon-background.jpg",
    }

def get_channel_category(channel_name):
    """Determina la categoria di un canale in base al suo nome"""
    category_keywords = get_category_keywords()
    channel_name_lower = channel_name.lower()
    
    # Cerca in tutte le categorie
    for category, keywords in category_keywords.items():
        for keyword in keywords:
            if keyword.lower() in channel_name_lower:
                return category
    
    # Se nessuna categoria corrisponde, usa ALTRI
    return "ALTRI"

def generate_m3u8_list():
    """Genera la lista m3u8 utilizzando lo script m3u8_vavoo.py"""
    try:
        print(f"Esecuzione dello script: {M3U8_GENERATOR}")
        # Controlla se lo script esiste prima di eseguirlo
        if not os.path.exists(M3U8_GENERATOR):
            print(f"ERRORE: Script {M3U8_GENERATOR} non trovato!")
            return False
        
        result = subprocess.run(['python3', M3U8_GENERATOR], 
                              capture_output=True, text=True)
        
        print(f"Output dello script: {result.stdout[:100]}...")
        print(f"Errori dello script: {result.stderr[:100]}...")
        
        if result.returncode == 0:
            # Verifica che il file M3U8 sia stato effettivamente creato
            if os.path.exists(M3U8_FILE):
                file_size = os.path.getsize(M3U8_FILE)
                print(f"Lista M3U8 generata con successo. Dimensione file: {file_size} bytes")
                return True
            else:
                print(f"ERRORE: File {M3U8_FILE} non creato dallo script")
                return False
        else:
            print(f"ERRORE nella generazione della lista M3U8: {result.stderr}")
            return False
    except Exception as e:
        print(f"ERRORE durante l'esecuzione del generatore: {e}")
        return False

def parse_m3u8_to_channels():
    """Analizza il file M3U8 e lo converte in canali per Stremio"""
    channels = []
    
    try:
        if not os.path.exists(M3U8_FILE):
            print(f"File {M3U8_FILE} non trovato, generazione in corso...")
            if not generate_m3u8_list():
                return []
        
        with open(M3U8_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        channel = None
        headers = {}
        signature_placeholder = None
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            if line.startswith('#EXTINF:'):
                # Inizia un nuovo canale
                channel = {}
                
                # Estrai tvg-id
                tvg_id_match = re.search(r'tvg-id="([^"]+)"', line)
                if tvg_id_match:
                    channel_id = tvg_id_match.group(1).replace(' ', '-').lower()
                    channel['id'] = channel_id
                else:
                    channel['id'] = f"channel-{len(channels)}"
                
                # Estrai il nome
                name_match = re.search(r',([^\n]+)$', line)
                if name_match:
                    channel['name'] = name_match.group(1).strip()
                else:
                    channel['name'] = f"Channel {len(channels)}"
                
                # Estrai il genere/categoria dal gruppo o determinala dal nome
                genre_match = re.search(r'group-title="([^"]+)"', line)
                if genre_match:
                    channel['genre'] = genre_match.group(1)
                else:
                    # Se non c'è un gruppo, determina la categoria dal nome
                    channel['genre'] = get_channel_category(channel['name'])
                
                # Estrai il logo
                logo_match = re.search(r'tvg-logo="([^"]+)"', line)
                if logo_match:
                    channel['logo'] = logo_match.group(1)
                else:
                    channel['logo'] = ""
                
                # Reset headers per il nuovo canale
                headers = {}
                signature_placeholder = None
                
            elif line.startswith('#EXTVLCOPT:'):
                # Opzioni VLC per gli header
                if "http-user-agent=" in line:
                    headers['user-agent'] = line.split('=', 1)[1]
                elif "http-origin=" in line:
                    headers['origin'] = line.split('=', 1)[1]
                elif "http-referrer=" in line:
                    headers['referer'] = line.split('=', 1)[1]
                elif "mediahubmx-signature=" in line:
                    signature_placeholder = line.split('=', 1)[1]
            
            elif line and not line.startswith('#') and channel:
                # Questa è la URL
                channel['url'] = line
                channel['headers'] = headers
                channel['signature_placeholder'] = signature_placeholder
                channels.append(channel)
                channel = None
        
        # Salva i canali nel file JSON
        if channels:
            save_json_file(CHANNELS_FILE, channels)
            print(f"Salvati {len(channels)} canali nel file JSON")
        
        return channels
        
    except Exception as e:
        print(f"Errore nell'analisi del file M3U8: {e}")
        return []

def get_channels_data():
    """Ottiene la lista dei canali, rigenerandola solo se necessario"""
    global channels_data_cache, channels_data_timestamp
    current_time = time.time()
    
    print("Inizio get_channels_data()")
    
    # Se la cache è vuota o è passato troppo tempo dall'ultimo aggiornamento
    if not channels_data_cache or (current_time - channels_data_timestamp) > 3600:  # 1 ora
        print("Cache non valida, caricamento lista canali...")
        
        # Prima controlla se esiste il file JSON
        channels = load_json_file(CHANNELS_FILE, [])
        print(f"Caricati {len(channels)} canali dal file JSON")
        
        # Se il file JSON non esiste o è vuoto, analizza il file M3U8
        if not channels:
            print("File JSON vuoto o inesistente, analisi del file M3U8...")
            channels = parse_m3u8_to_channels()
            print(f"Analizzati {len(channels)} canali da M3U8")
        
        # Se ancora non abbiamo canali, usa alcuni canali di esempio
        if not channels:
            print("Nessun canale trovato, utilizzo canali di esempio...")
            channels = [
                {"id": "rai1-example", "name": "Rai 1", "url": "https://example.com/rai1.m3u8", "genre": "RAI"},
                {"id": "canale5-example", "name": "Canale 5", "url": "https://example.com/canale5.m3u8", "genre": "MEDIASET"},
                {"id": "skysport-example", "name": "Sky Sport", "url": "https://example.com/skysport.m3u8", "genre": "SPORT"},
                {"id": "discovery-example", "name": "Discovery Channel", "url": "https://example.com/discovery.m3u8", "genre": "DISCOVERY"}
            ]
            save_json_file(CHANNELS_FILE, channels)
        
        channels_data_cache = channels
        channels_data_timestamp = current_time
        print(f"Caricati {len(channels)} canali in totale")
    else:
        print(f"Utilizzo {len(channels_data_cache)} canali dalla cache")
    
    return channels_data_cache

def to_meta(channel, mediaflow_url, mediaflow_psw):
    """Converte un canale in un oggetto meta formato Stremio"""
    # Ottieni il nome pulito del canale
    channel_name = clean_channel_name(channel["name"])
    
    # Ottieni il logo del canale
    logo = channel.get("logo", "https://dl.strem.io/addon-logo.png")
    
    # Categoria/genere del canale
    genre = channel.get("genre", "ALTRI")
    
    # Non risolvere l'URL qui, poiché sarà gestito dalle funzioni di stream
    return {
        "id": f"mediaflow-{channel['id']}",
        "name": channel_name,
        "type": "tv",
        "genres": [genre],
        "poster": logo,
        "posterShape": "square",
        "background": logo,
        "logo": logo
    }

def resolve_stream_url(channel, mediaflow_url, mediaflow_psw):
    """Risolve l'URL di stream di un canale"""
    channel_name = clean_channel_name(channel["name"])
    
    # Se il canale ha headers specifici, usali
    headers = channel.get("headers", {})
    signature_placeholder = channel.get("signature_placeholder")
    
    # Inizializza l'URL di stream con quello originale
    stream_url = channel["url"]
    
    # Se c'è un placeholder per la signature, risolvi l'URL
    if signature_placeholder == "[$KEY$]":
        # Ottieni la signature aggiornata
        signature = get_vavoo_signature()
        
        if signature:
            # Risolvi l'URL se necessario
            if "localhost" not in stream_url:
                try:
                    print(f"Tentativo di risoluzione URL per lo stream di {channel_name}")
                    # Implementazione diretta della risoluzione URL
                    headers_resolve = {
                        "user-agent": "MediaHubMX/2",
                        "accept": "application/json",
                        "content-type": "application/json; charset=utf-8",
                        "accept-encoding": "gzip",
                        "mediahubmx-signature": signature
                    }
                    
                    data_resolve = {
                        "language": "de",
                        "region": "AT",
                        "url": stream_url,
                        "clientVersion": "3.0.2"
                    }
                    
                    response = requests.post(
                        "https://vavoo.to/vto-cluster/mediahubmx-resolve.json", 
                        json=data_resolve, 
                        headers=headers_resolve,
                        timeout=10  # Aggiungi un timeout per evitare blocchi
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        if isinstance(result, list) and result and "url" in result[0]:
                            stream_url = result[0]["url"]
                            print(f"URL risolto con successo: {stream_url[:50]}...")
                        else:
                            print(f"Formato risposta non valido: {result}")
                    else:
                        print(f"Errore risposta HTTP: {response.status_code}")
                except Exception as e:
                    print(f"Errore nella risoluzione URL: {e}")
            
            # Crea l'URL finale per MediaFlow con l'URL risolto
            params = {
                "api_password": mediaflow_psw,
                "d": stream_url
            }
            
            # Aggiungi headers alla query string
            for key, value in headers.items():
                params[f"h_{key}"] = value
            
            # Aggiungi anche la signature come header
            params["h_mediahubmx-signature"] = signature
            
            final_url = f"https://{mediaflow_url}/proxy/hls/manifest.m3u8?{urlencode(params, quote_via=quote_plus)}"
        else:
            print("Signature non ottenuta, uso URL non risolto")
            # Fallback: usa l'URL originale senza signature
            params = {
                "api_password": mediaflow_psw,
                "d": stream_url
            }
            
            # Aggiungi headers alla query string
            for key, value in headers.items():
                params[f"h_{key}"] = value
            
            final_url = f"https://{mediaflow_url}/proxy/hls/manifest.m3u8?{urlencode(params, quote_via=quote_plus)}"
    else:
        # URL normale senza signature, usa solo MediaFlow con gli header standard
        params = {
            "api_password": mediaflow_psw,
            "d": stream_url
        }
        
        # Aggiungi headers alla query string
        for key, value in headers.items():
            params[f"h_{key}"] = value
        
        final_url = f"https://{mediaflow_url}/proxy/hls/manifest.m3u8?{urlencode(params, quote_via=quote_plus)}"
    
    return {
        "url": final_url,
        "title": channel_name
    }

def get_all_channels(mediaflow_url, mediaflow_psw):
    """Ottiene tutti i canali con i metadati per Stremio"""
    print(f"Inizio get_all_channels con URL: {mediaflow_url}")
    
    if not mediaflow_url or not mediaflow_psw:
        print("ERRORE: URL o password MediaFlow mancante")
        return []
    
    try:
        channels_data = get_channels_data()
        print(f"Ottenuti {len(channels_data)} canali dai dati")
        
        all_channels = []
        for i, channel in enumerate(channels_data):
            try:
                print(f"Elaborazione canale {i+1}/{len(channels_data)}: {channel.get('name', 'Unknown')}")
                meta = to_meta(channel, mediaflow_url, mediaflow_psw)
                all_channels.append(meta)
            except Exception as e:
                print(f"ERRORE durante elaborazione canale {channel.get('name', 'Unknown')}: {e}")
        
        print(f"Elaborati {len(all_channels)} canali in totale")
        return all_channels
    except Exception as e:
        print(f"ERRORE generico in get_all_channels: {e}")
        return []

# Funzione per aggiornare periodicamente la lista dei canali
def refresh_channels_periodically():
    """Aggiorna periodicamente la lista dei canali"""
    while True:
        print(f"Aggiornamento canali alle {time.strftime('%H:%M:%S')}")
        try:
            # Genera una nuova lista m3u8
            if generate_m3u8_list():
                # Analizza la lista e aggiorna il file JSON
                parse_m3u8_to_channels()
                
                # Invalida la cache
                global channels_data_cache, channels_data_timestamp
                channels_data_cache = []
                channels_data_timestamp = 0
                
                # Aggiorna anche la signature di Vavoo
                get_vavoo_signature()
        except Exception as e:
            print(f"Errore nell'aggiornamento dei canali: {e}")
            
        # Attendi 20 minuti prima del prossimo aggiornamento
        time.sleep(20 * 60)

# Crea il file del template se non esiste
def create_index_template():
    """Crea il file del template HTML per la pagina principale"""
    template_path = os.path.join(BASE_DIR, "templates", "index.html")
    if not os.path.exists(template_path):
        with open(template_path, "w", encoding="utf-8") as f:
            f.write("""
<!DOCTYPE html>
<html>
<head>
    <title>MediaFlow IPTV Addon</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 650px; margin: 0 auto; padding: 20px; }
        .header { text-align: center; margin-bottom: 30px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; font-weight: bold; }
        input[type="text"], input[type="password"] { width: 100%; padding: 12px; font-size: 16px; border: 1px solid #ccc; border-radius: 4px; }
        .btn { display: inline-block; padding: 12px 20px; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        .btn:hover { background: #45a049; }
        .result-section { margin-top: 30px; padding: 20px; background-color: #f8f8f8; border-radius: 8px; display: none; }
        .install-btn { background: #2196F3; }
        .install-btn:hover { background: #0b7dda; }
        .url-display { word-break: break-all; padding: 10px; background: #eee; border-radius: 4px; margin: 15px 0; }
    </style>
</head>
<body>
    <div class="header">
        <h1>MediaFlow IPTV Addon per Stremio</h1>
        <p>Inserisci i dati di MediaFlow Proxy per generare il link di installazione</p>
    </div>
    
    <div class="form-group">
        <label for="mediaflow_url">URL MediaFlow Proxy:</label>
        <input type="text" id="mediaflow_url" value="{{ default_url }}" placeholder="es. mfp0bug.duckdns.org">
    </div>
    
    <div class="form-group">
        <label for="mediaflow_psw">Password MediaFlow:</label>
        <input type="password" id="mediaflow_psw" value="{{ default_psw }}" placeholder="Password">
    </div>
    
    <button id="generateLink" class="btn">Genera Link di Installazione</button>
    
    <div id="resultSection" class="result-section">
        <h3>Link generato!</h3>
        <p>Ecco il link per installare l'addon in Stremio:</p>
        <div id="generatedUrl" class="url-display"></div>
        <a id="stremioLink" href="#">
            <button class="btn install-btn">Installa in Stremio</button>
        </a>
    </div>
    
    <script>
        document.getElementById('generateLink').addEventListener('click', function() {
            const mfpUrl = document.getElementById('mediaflow_url').value.trim();
            const mfpPsw = document.getElementById('mediaflow_psw').value.trim();
            
            if (!mfpUrl || !mfpPsw) {
                alert('Inserisci sia URL che password');
                return;
            }
            
            const domain = '{{ domain }}';
            const encodedUrl = encodeURIComponent(mfpUrl);
            const encodedPsw = encodeURIComponent(mfpPsw);
            
            // Usa il formato del percorso URL che Stremio si aspetta
            const stremioLink = `stremio://${domain}/mfp/${encodedUrl}/psw/${encodedPsw}/manifest.json`;
            
            document.getElementById('stremioLink').href = stremioLink;
            document.getElementById('generatedUrl').textContent = stremioLink;
            document.getElementById('resultSection').style.display = 'block';
        });
    </script>
</body>
</html>
            """)

# Rotte API

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Pagina principale con form di configurazione"""
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "default_url": DEFAULT_MEDIAFLOW_URL,
            "default_psw": DEFAULT_MEDIAFLOW_PSW,
            "domain": DOMAIN
        }
    )

@app.get("/status")
async def status():
    """Restituisce lo stato dell'addon"""
    # Controlla i file
    m3u8_exists = os.path.exists(M3U8_FILE)
    m3u8_size = os.path.getsize(M3U8_FILE) if m3u8_exists else 0
    
    channels_file_exists = os.path.exists(CHANNELS_FILE)
    channels_count = len(load_json_file(CHANNELS_FILE, [])) if channels_file_exists else 0
    
    # Controlla le cache
    cache_channels = len(channels_data_cache)
    
    # Controlla gli scripts
    m3u8_generator_exists = os.path.exists(M3U8_GENERATOR)
    chiave_script_exists = os.path.exists(CHIAVE_SCRIPT)
    
    return {
        "m3u8_file": {
            "exists": m3u8_exists,
            "size_bytes": m3u8_size,
            "path": M3U8_FILE
        },
        "channels_file": {
            "exists": channels_file_exists,
            "channels_count": channels_count,
            "path": CHANNELS_FILE
        },
        "cache": {
            "channels_in_cache": cache_channels,
            "cache_timestamp": channels_data_timestamp
        },
        "scripts": {
            "m3u8_generator": {
                "exists": m3u8_generator_exists,
                "path": M3U8_GENERATOR
            },
            "chiave_script": {
                "exists": chiave_script_exists,
                "path": CHIAVE_SCRIPT
            }
        },
        "categories": list(get_category_keywords().keys())
    }

@app.get("/mfp/{url}/psw/{psw}/manifest.json")
async def manifest_with_params(url: str, psw: str):
    """Manifest con parametri inclusi nell'URL"""
    print(f"Manifest requested with URL params: {url}, {psw}")
    return create_manifest(url, psw)

@app.get("/manifest.json")
async def manifest(request: Request):
    """Manifest dell'addon"""
    mediaflow_url, mediaflow_psw = extract_url_params(request)
    print(f"Manifest requested: {mediaflow_url}, {mediaflow_psw}")
    return create_manifest(mediaflow_url, mediaflow_psw)

# Gestisce il formato con il parametro di ricerca nell'URL (search%3Dtv.json)
@app.get("/mfp/{url}/psw/{psw}/catalog/{type}/{id}/{search_param}.json")
async def catalog_with_search_param(url: str, psw: str, type: str, id: str, search_param: str):
    """Catalogo dei canali con parametri nel path e ricerca"""
    print(f"Catalog requested with search param: {type}, {id}, search={search_param}, url={url}, psw={psw}")
    
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"metas": []}
    
    category = id.split("-")[1]
    all_channels = get_all_channels(url, psw)
    
    # Estrai il termine di ricerca dal parametro
    search = None
    if search_param and search_param.startswith("search="):
        search = unquote(search_param.split("=")[1])
    
    # Filtra per categoria se non è una ricerca
    if not search:
        filtered_channels = [c for c in all_channels if c["genres"][0] == category]
    # Altrimenti usa la ricerca su tutti i canali
    else:
        search = search.lower()
        filtered_channels = [c for c in all_channels if search in c["name"].lower()]
    
    print(f"Serving catalog with search for {category} with {len(filtered_channels)} channels")
    return {"metas": filtered_channels}

# Gestisce il formato standard del catalogo
@app.get("/mfp/{url}/psw/{psw}/catalog/{type}/{id}.json")
async def catalog_with_params(url: str, psw: str, type: str, id: str, request: Request, genre: str = None, search: str = None):
    """Catalogo dei canali con parametri nel path"""
    print(f"Catalog requested with path params: {type}, {id}, url={url}, psw={psw}")
    
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"metas": []}
    
    category = id.split("-")[1]
    all_channels = get_all_channels(url, psw)
    
    # Filtra per categoria
    filtered_channels = [c for c in all_channels if c["genres"][0] == category]
    
    # Filtra per ricerca da query params
    if search:
        search = search.lower()
        filtered_channels = [c for c in all_channels if search in c["name"].lower()]
    
    print(f"Serving catalog for {category} with {len(filtered_channels)} channels")
    return {"metas": filtered_channels}

@app.get("/catalog/{type}/{id}.json")
async def catalog(type: str, id: str, request: Request, genre: str = None, search: str = None):
    """Catalogo dei canali"""
    print(f"Catalog requested: {type}, {id}")
    
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"metas": []}
    
    mediaflow_url, mediaflow_psw = extract_url_params(request)
    category = id.split("-")[1]
    all_channels = get_all_channels(mediaflow_url, mediaflow_psw)
    
    # Filtra per categoria
    filtered_channels = [c for c in all_channels if c["genres"][0] == category]
    
    # Filtra per ricerca
    if search:
        search = search.lower()
        filtered_channels = [c for c in all_channels if search in c["name"].lower()]
    
    print(f"Serving catalog for {category} with {len(filtered_channels)} channels")
    return {"metas": filtered_channels}

# Aggiunto supporto per il formato di percorso che Stremio usa per i metadati
@app.get("/mfp/{url}/psw/{psw}/meta/{type}/{id}.json")
async def meta_with_params(url: str, psw: str, type: str, id: str):
    """Metadati del canale con parametri nel path"""
    print(f"Meta requested with path params: {type}, {id}, url={url}, psw={psw}")
    
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"meta": {}}
    
    all_channels = get_all_channels(url, psw)
    channel = next((c for c in all_channels if c["id"] == id), None)
    
    if channel:
        return {"meta": channel}
    else:
        return {"meta": {}}

@app.get("/meta/{type}/{id}.json")
async def meta(type: str, id: str, request: Request):
    """Metadati del canale"""
    print(f"Meta requested: {type}, {id}")
    
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"meta": {}}
    
    mediaflow_url, mediaflow_psw = extract_url_params(request)
    all_channels = get_all_channels(mediaflow_url, mediaflow_psw)
    channel = next((c for c in all_channels if c["id"] == id), None)
    
    if channel:
        return {"meta": channel}
    else:
        return {"meta": {}}

# Aggiunto supporto per il formato di percorso che Stremio usa per gli stream
@app.get("/mfp/{url}/psw/{psw}/stream/{type}/{id}.json")
async def stream_with_params(url: str, psw: str, type: str, id: str):
    """Stream del canale con parametri nel path"""
    print(f"Stream requested with path params: {type}, {id}, url={url}, psw={psw}")
    
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"streams": []}
    
    # Ottieni tutti i canali (senza risoluzione URL)
    all_channels = get_all_channels(url, psw)
    
    # Trova il canale specifico richiesto
    original_channel = next((c for c in channels_data_cache if f"mediaflow-{c['id']}" == id), None)
    
    if not original_channel:
        print(f"No matching channel found for channelID: {id}")
        return {"streams": []}
    
    # Risolvi l'URL del canale e crea le informazioni di stream
    print(f"Trovato il canale, risolvo lo stream per: {original_channel['name']}")
    stream_info = resolve_stream_url(original_channel, url, psw)
    print(f"Stream risolto per {original_channel['name']}")
    
    return {"streams": [stream_info]}

@app.get("/stream/{type}/{id}.json")
async def stream(type: str, id: str, request: Request):
    """Stream del canale"""
    print(f"Stream requested: {type}, {id}")
    
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"streams": []}
    
    mediaflow_url, mediaflow_psw = extract_url_params(request)
    
    # Trova il canale specifico richiesto
    original_channel = next((c for c in channels_data_cache if f"mediaflow-{c['id']}" == id), None)
    
    if not original_channel:
        print(f"No matching channel found for channelID: {id}")
        return {"streams": []}
    
    # Risolvi l'URL del canale e crea le informazioni di stream
    print(f"Trovato il canale, risolvo lo stream per: {original_channel['name']}")
    stream_info = resolve_stream_url(original_channel, mediaflow_url, mediaflow_psw)
    print(f"Stream risolto per {original_channel['name']}")
    
    return {"streams": [stream_info]}

# Avvio dell'applicazione
if __name__ == "__main__":
    # Crea il template HTML
    create_index_template()
    
    print("=== Inizializzazione addon MediaFlow IPTV ===")
    print(f"Cartella corrente: {os.getcwd()}")
    
    # Genera la lista canali all'avvio
    print("Generazione lista canali all'avvio...")
    generate_m3u8_list()  # Prima genera la lista M3U8
    channels = parse_m3u8_to_channels()  # Poi analizzala
    print(f"Canali caricati: {len(channels)}")
    
    # Avvia un thread per l'aggiornamento periodico
    print("Avvio thread per aggiornamento periodico...")
    update_thread = threading.Thread(target=refresh_channels_periodically, daemon=True)
    update_thread.start()
    
    # Avvia il server
    print(f"Avvio server su porta {PORT}...")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
