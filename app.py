#!/usr/bin/env python3
import json
import os
import re
import time
import random
import threading
from urllib.parse import urlencode, quote_plus, unquote
from fastapi import FastAPI, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

# Costanti
PORT = int(os.environ.get('PORT', 3000))
FETCH_INTERVAL = 20 * 60  # 20 minuti in secondi
FETCH_TIMEOUT = 10  # 10 secondi
DOMAIN = os.environ.get('DOMAIN', 'melatv0bug.duckdns.org')  # Dominio esterno

# Percorsi file
DATA_DIR = 'data'
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')
HEADERS_FILE = os.path.join(DATA_DIR, 'headers.json')
GENRE_FILE = os.path.join(DATA_DIR, 'genres.json')
ICONS_FILE = os.path.join(DATA_DIR, 'channel_icons.json')
CHANNELS_FILE = os.path.join(DATA_DIR, 'channels_data.json')
SAMPLE_CHANNELS_FILE = os.path.join(DATA_DIR, 'sample_channels.json')

# Default MediaFlow settings dalle variabili d'ambiente
DEFAULT_MEDIAFLOW_URL = os.environ.get('MEDIAFLOW_DEFAULT_URL', '')
DEFAULT_MEDIAFLOW_PSW = os.environ.get('MEDIAFLOW_DEFAULT_PSW', '')

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

# Crea una classe per i parametri di configurazione
class ConfigParams:
    def __init__(self, mediaflow_url=None, mediaflow_psw=None):
        self.mediaflow_url = mediaflow_url or DEFAULT_MEDIAFLOW_URL
        self.mediaflow_psw = mediaflow_psw or DEFAULT_MEDIAFLOW_PSW

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
    config = load_json_file(CONFIG_FILE, {
        "mediaflow_url": DEFAULT_MEDIAFLOW_URL, 
        "mediaflow_psw": DEFAULT_MEDIAFLOW_PSW
    })
    return config

def get_config_from_request(request: Request) -> ConfigParams:
    """Estrae i parametri di configurazione dalla richiesta o dal path"""
    # Prima controlla se ci sono parametri mfp e psw nell'URL
    path = request.url.path
    if "/mfp/" in path and "/psw/" in path:
        try:
            # Estrai i parametri dal path
            parts = path.split("/")
            mfp_index = parts.index("mfp")
            psw_index = parts.index("psw")
            
            if mfp_index < len(parts) - 1 and psw_index < len(parts) - 1:
                mediaflow_url = unquote(parts[mfp_index + 1])
                mediaflow_psw = unquote(parts[psw_index + 1])
                return ConfigParams(mediaflow_url, mediaflow_psw)
        except (ValueError, IndexError) as e:
            print(f"Errore nell'estrazione dei parametri dall'URL: {e}")
    
    # Se non ci sono parametri nell'URL, usa la configurazione salvata
    config = load_config()
    return ConfigParams(config["mediaflow_url"], config["mediaflow_psw"])

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

def get_all_channels(params: ConfigParams):
    """Ottiene tutti i canali con i metadati per Stremio"""
    # Genera una chiave di cache basata sui parametri
    cache_key = f"channels_{params.mediaflow_url}_{params.mediaflow_psw}"
    
    if cache_key in channel_cache:
        return channel_cache[cache_key]
    
    if not params.mediaflow_url or not params.mediaflow_psw:
        return []
    
    channels_data = load_json_file(CHANNELS_FILE, [])
    if not channels_data:
        return []
    
    all_channels = [
        to_meta(channel, params.mediaflow_url, params.mediaflow_psw)
        for channel in channels_data
    ]
    
    channel_cache[cache_key] = all_channels
    return all_channels

def generate_channel_list():
    """Genera la lista dei canali"""
    # Carica le configurazioni
    headers = load_json_file(HEADERS_FILE, {})
    genre_mapping = load_json_file(GENRE_FILE, {})
    icons = load_json_file(ICONS_FILE, {})
    
    # Se headers è vuoto, inizializza con alcuni default
    if not headers:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Referer": "https://vavoo.to/",
            "Origin": "https://vavoo.to"
        }
        save_json_file(HEADERS_FILE, headers)
    
    # Prepara la lista m3u8
    channels_data = []
    
    # Esempio di dati di canale per test se necessario
    if not os.path.exists(SAMPLE_CHANNELS_FILE):
        sample_channels = [
            {"name": "Rai 1 .I", "url": "https://example.com/rai1.m3u8", "genre": "general"},
            {"name": "Canale 5 .I", "url": "https://example.com/canale5.m3u8", "genre": "general"},
            {"name": "Sky Sport .I", "url": "https://example.com/skysport.m3u8", "genre": "sports"},
            {"name": "Discovery Channel .I", "url": "https://example.com/discovery.m3u8", "genre": "documentary"}
        ]
        save_json_file(SAMPLE_CHANNELS_FILE, sample_channels)
    
    # Nelle implementazioni reali, qui si eseguirebbe lo scraping o l'ottenimento dei dati
    # Per questo esempio, usiamo dati di prova
    sample_channels = load_json_file(SAMPLE_CHANNELS_FILE, [])
    
    for channel in sample_channels:
        channel_name = channel['name']
        clean_name = clean_channel_name(channel_name)
        
        # Verifica se già esiste un'icona, altrimenti assegna un placeholder
        icon_url = icons.get(clean_name, "https://dl.strem.io/addon-logo.png")
        
        # Assegna un genere al canale
        genre = channel.get('genre') or assign_genre(channel_name, genre_mapping)
        if genre not in AVAILABLE_GENRES:
            genre = "general"
        
        # Crea l'oggetto canale
        channel_obj = {
            "id": generate_id(channel_name),
            "name": channel_name,
            "url": channel['url'],
            "genre": genre,
            "icon": icon_url
        }
        
        channels_data.append(channel_obj)
        
        # Aggiorna il mapping del genere se non è già presente
        if clean_name not in genre_mapping:
            genre_mapping[clean_name] = genre
    
    # Salva il mapping dei generi aggiornato
    save_json_file(GENRE_FILE, genre_mapping)
    
    # Salva i dati dei canali
    if save_json_file(CHANNELS_FILE, channels_data):
        print(f"Lista canali salvata: {len(channels_data)} canali")
        # Invalida tutte le chiavi della cache
        channel_cache.clear()
        return True
    else:
        print("Errore nel salvataggio della lista canali")
        return False

def refresh_channels_periodically():
    """Aggiorna periodicamente la lista dei canali"""
    while True:
        print(f"Aggiornamento canali alle {time.strftime('%H:%M:%S')}")
        generate_channel_list()
        time.sleep(FETCH_INTERVAL)

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
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }
        .form-group { margin-bottom: 15px; }
        label { display: block; margin-bottom: 5px; }
        input[type="text"], input[type="password"] { width: 100%; padding: 8px; }
        button { padding: 10px 15px; background: #4caf50; color: white; border: none; cursor: pointer; }
        .install-button { margin-top: 20px; }
        .success { color: green; margin-top: 10px; }
        .current { margin-top: 20px; padding: 15px; background-color: #f8f8f8; border-radius: 5px; }
    </style>
</head>
<body>
    <h1>MediaFlow IPTV Addon</h1>
    
    <div class="current">
        <h3>Configurazione attuale</h3>
        <p><strong>URL MediaFlow:</strong> {{ url }}</p>
        <p><strong>Password:</strong> {{ psw }}</p>
        
        <div class="install-button">
            <a href="stremio://{{ host }}/mfp/{{ url }}/psw/{{ psw }}/manifest.json">
                <button type="button">Installa in Stremio</button>
            </a>
        </div>
    </div>
    
    <h3>Cambia configurazione</h3>
    <form id="configForm" action="/save-config" method="post">
        <div class="form-group">
            <label for="mediaflow_url">URL MediaFlow Proxy:</label>
            <input type="text" id="mediaflow_url" name="mediaflow_url" value="{{ url }}" required>
        </div>
        
        <div class="form-group">
            <label for="mediaflow_psw">Password MediaFlow:</label>
            <input type="password" id="mediaflow_psw" name="mediaflow_psw" value="{{ psw }}" required>
        </div>
        
        <button type="submit">Salva Configurazione</button>
    </form>
    
    <div id="success" class="success" style="display:none;">
        Configurazione salvata! Usa il pulsante per installare l'addon con i nuovi parametri.
    </div>
    
    <script>
        document.getElementById('configForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const formData = new FormData(this);
            
            fetch('/save-config', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    document.getElementById('success').style.display = 'block';
                    setTimeout(() => {
                        window.location.reload();
                    }, 1500);
                }
            });
        });
    </script>
</body>
</html>
            """)

# Rotte API

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Pagina principale con form di configurazione"""
    config = load_config()
    return templates.TemplateResponse(
        "index.html", 
        {
            "request": request, 
            "url": config["mediaflow_url"], 
            "psw": config["mediaflow_psw"],
            "host": DOMAIN
        }
    )

@app.post("/save-config")
async def save_configuration(mediaflow_url: str = Form(...), mediaflow_psw: str = Form(...)):
    """Salva la configurazione dell'utente"""
    if not mediaflow_url or not mediaflow_psw:
        raise HTTPException(status_code=400, detail="Mancano dei parametri")
    
    if save_config(mediaflow_url, mediaflow_psw):
        # Trigger generazione lista per aggiornare la cache
        # Ma prima invalidiamo la cache
        channel_cache.clear()
        return {"success": True}
    else:
        raise HTTPException(status_code=500, detail="Errore nel salvataggio della configurazione")

@app.get("/mfp/{url}/psw/{psw}/manifest.json")
async def manifest_with_params(url: str, psw: str):
    """Manifest con parametri inclusi nell'URL"""
    params = ConfigParams(url, psw)
    # Non salviamo più qui la configurazione - la usiamo solo per questa richiesta
    return create_manifest(params.mediaflow_url, params.mediaflow_psw)

@app.get("/manifest.json")
async def manifest(request: Request):
    """Manifest dell'addon"""
    params = get_config_from_request(request)
    return create_manifest(params.mediaflow_url, params.mediaflow_psw)

@app.get("/catalog/{type}/{id}.json")
async def catalog(type: str, id: str, request: Request, genre: str = None, search: str = None):
    """Catalogo dei canali"""
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"metas": []}
    
    params = get_config_from_request(request)
    category = id.split("-")[1]
    all_channels = get_all_channels(params)
    
    # Filtra per categoria
    filtered_channels = [c for c in all_channels if category in c["genres"]]
    
    # Filtra per ricerca
    if search:
        search = search.lower()
        filtered_channels = [c for c in all_channels if search in c["name"].lower()]
    
    print(f"Serving catalog for {category} with {len(filtered_channels)} channels")
    return {"metas": filtered_channels}

@app.get("/meta/{type}/{id}.json")
async def meta(type: str, id: str, request: Request):
    """Metadati del canale"""
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"meta": {}}
    
    params = get_config_from_request(request)
    all_channels = get_all_channels(params)
    channel = next((c for c in all_channels if c["id"] == id), None)
    
    if channel:
        return {"meta": channel}
    else:
        return {"meta": {}}

@app.get("/stream/{type}/{id}.json")
async def stream(type: str, id: str, request: Request):
    """Stream del canale"""
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"streams": []}
    
    params = get_config_from_request(request)
    all_channels = get_all_channels(params)
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
    
    # Genera la lista canali all'avvio
    generate_channel_list()
    
    # Avvia un thread per l'aggiornamento periodico
    update_thread = threading.Thread(target=refresh_channels_periodically, daemon=True)
    update_thread.start()
    
    # Avvia il server
    uvicorn.run(app, host="0.0.0.0", port=PORT)
