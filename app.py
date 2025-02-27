#!/usr/bin/env python3
import json
import os
import re
import time
import random
from urllib.parse import urlencode, quote_plus, unquote
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Costanti
PORT = int(os.environ.get('PORT', 3000))
DOMAIN = os.environ.get('DOMAIN', 'melatv0bug.duckdns.org')  # Dominio esterno

# Default MediaFlow settings dalle variabili d'ambiente
DEFAULT_MEDIAFLOW_URL = os.environ.get('MEDIAFLOW_DEFAULT_URL', '')
DEFAULT_MEDIAFLOW_PSW = os.environ.get('MEDIAFLOW_DEFAULT_PSW', '')

# Percorsi file
DATA_DIR = 'data'
os.makedirs(DATA_DIR, exist_ok=True)
HEADERS_FILE = os.path.join(DATA_DIR, 'headers.json')
ICONS_FILE = os.path.join(DATA_DIR, 'channel_icons.json')
CHANNELS_FILE = os.path.join(DATA_DIR, 'channels_data.json')

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

# Abilita CORS per tutte le origini
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup per servire file statici
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup per i template
templates = Jinja2Templates(directory="templates")

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

def generate_id(name):
    """Genera un ID unico basato sul nome del canale"""
    clean_name = re.sub(r'[^a-zA-Z0-9]', '', clean_channel_name(name).lower())
    return f"{clean_name}-{int(time.time())}-{random.randint(1000, 9999)}"

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

def create_manifest(mediaflow_url, mediaflow_psw):
    """Crea il manifest dell'addon con i parametri personalizzati"""
    return {
        "id": "org.mediaflow.iptv",
        "name": "MediaFlow IPTV",
        "version": "1.0.0",
        "description": f"Watch IPTV channels from MediaFlow service ({mediaflow_url})",
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
        "behaviorHints": { 
            "configurable": False,
            "configurationRequired": False
        },
        "logo": "https://dl.strem.io/addon-logo.png",
        "icon": "https://dl.strem.io/addon-logo.png",
        "background": "https://dl.strem.io/addon-background.jpg",
    }

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
        }
    }

def get_channels_data():
    """Ottiene la lista dei canali, rigenerandola solo se necessario"""
    global channels_data_cache, channels_data_timestamp
    current_time = time.time()
    
    # Se la cache è vuota o è passato troppo tempo dall'ultimo aggiornamento
    if not channels_data_cache or (current_time - channels_data_timestamp) > 3600:  # 1 ora
        print("Generazione lista canali...")
        channels = load_json_file(CHANNELS_FILE, [])
        if not channels:
            # Se il file non esiste, usa dati di esempio
            channels = [
                {"id": "rai1-example", "name": "Rai 1 .I", "url": "https://example.com/rai1.m3u8", "genre": "general"},
                {"id": "canale5-example", "name": "Canale 5 .I", "url": "https://example.com/canale5.m3u8", "genre": "general"},
                {"id": "skysport-example", "name": "Sky Sport .I", "url": "https://example.com/skysport.m3u8", "genre": "sports"},
                {"id": "discovery-example", "name": "Discovery Channel .I", "url": "https://example.com/discovery.m3u8", "genre": "documentary"}
            ]
            save_json_file(CHANNELS_FILE, channels)
        
        channels_data_cache = channels
        channels_data_timestamp = current_time
    
    return channels_data_cache

def get_all_channels(mediaflow_url, mediaflow_psw):
    """Ottiene tutti i canali con i metadati per Stremio"""
    if not mediaflow_url or not mediaflow_psw:
        return []
    
    channels_data = get_channels_data()
    
    all_channels = [
        to_meta(channel, mediaflow_url, mediaflow_psw)
        for channel in channels_data
    ]
    
    return all_channels

# Crea il file del template se non esiste
def create_index_template():
    """Crea il file del template HTML per la pagina principale"""
    template_path = os.path.join("templates", "index.html")
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

# Aggiunto supporto per il formato di percorso che Stremio usa
@app.get("/mfp/{url}/psw/{psw}/catalog/{type}/{id}.json")
async def catalog_with_params(url: str, psw: str, type: str, id: str, request: Request, genre: str = None, search: str = None):
    """Catalogo dei canali con parametri nel path"""
    print(f"Catalog requested with path params: {type}, {id}, url={url}, psw={psw}")
    
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"metas": []}
    
    category = id.split("-")[1]
    all_channels = get_all_channels(url, psw)
    
    # Filtra per categoria
    filtered_channels = [c for c in all_channels if category in c["genres"]]
    
    # Filtra per ricerca
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
    filtered_channels = [c for c in all_channels if category in c["genres"]]
    
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
    
    all_channels = get_all_channels(url, psw)
    channel = next((c for c in all_channels if c["id"] == id), None)
    
    if channel and "streamInfo" in channel:
        print(f"Serving stream id: {channel['id']}")
        return {"streams": [channel["streamInfo"]]}
    else:
        print(f"No matching stream found for channelID: {id}")
        return {"streams": []}

@app.get("/stream/{type}/{id}.json")
async def stream(type: str, id: str, request: Request):
    """Stream del canale"""
    print(f"Stream requested: {type}, {id}")
    
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"streams": []}
    
    mediaflow_url, mediaflow_psw = extract_url_params(request)
    all_channels = get_all_channels(mediaflow_url, mediaflow_psw)
    channel = next((c for c in all_channels if c["id"] == id), None)
    
    if channel and "streamInfo" in channel:
        print(f"Serving stream id: {channel['id']}")
        return {"streams": [channel["streamInfo"]]}
    else:
        print(f"No matching stream found for channelID: {id}")
        return {"streams": []}

# Avvio dell'applicazione
if __name__ == "__main__":
    # Crea il template HTML
    create_index_template()
    
    # Avvia il server
    uvicorn.run(app, host="0.0.0.0", port=PORT)
