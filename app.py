#!/usr/bin/env python3
import json, os, re, time, subprocess, requests, threading
from urllib.parse import urlencode, quote_plus, unquote
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Percorsi e costanti
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('PORT', 3000))
DOMAIN = os.environ.get('DOMAIN', 'melatv0bug.duckdns.org')
M3U8_GENERATOR = os.path.join(BASE_DIR, 'm3u8_vavoo.py')
CHIAVE_SCRIPT = os.path.join(BASE_DIR, 'chiave.py')
M3U8_FILE = os.path.join(BASE_DIR, 'channels.m3u8')
DEFAULT_MF_URL = os.environ.get('MEDIAFLOW_DEFAULT_URL', '')
DEFAULT_MF_PSW = os.environ.get('MEDIAFLOW_DEFAULT_PSW', '')

# Percorsi file
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)
HEADERS_FILE = os.path.join(DATA_DIR, 'headers.json')
ICONS_FILE = os.path.join(DATA_DIR, 'channel_icons.json')
CHANNELS_FILE = os.path.join(DATA_DIR, 'channels_data.json')
CATEGORY_KEYWORDS_FILE = os.path.join(BASE_DIR, 'category_keywords.json')

# Inizializza cartelle necessarie
os.makedirs(os.path.join(BASE_DIR, "templates"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "static"), exist_ok=True)

# Inizializzazione FastAPI
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Variabili cache
channels_data_cache = []
channels_data_timestamp = 0

def load_json_file(filename, default=None):
    try:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as file:
                return json.load(file)
    except Exception as e:
        print(f"Errore nel caricamento di {filename}: {e}")
    return default if default is not None else {}

def save_json_file(filename, data):
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Errore nel salvataggio di {filename}: {e}")
        return False

def clean_channel_name(name):
    if len(name) > 3 and re.match(r'\s\.[A-Za-z]', name[-3:]):
        return name[:-3]
    return name

def extract_url_params(request: Request):
    path = request.url.path
    mf_url, mf_psw = DEFAULT_MF_URL, DEFAULT_MF_PSW
    try:
        if "/mfp/" in path and "/psw/" in path:
            parts = path.split("/")
            mfp_index, psw_index = parts.index("mfp"), parts.index("psw")
            if mfp_index < len(parts) - 1 and psw_index < len(parts) - 1:
                mf_url, mf_psw = unquote(parts[mfp_index + 1]), unquote(parts[psw_index + 1])
    except Exception as e:
        print(f"Errore nell'estrazione parametri URL: {e}")
    return mf_url, mf_psw

def get_category_keywords():
    return load_json_file(CATEGORY_KEYWORDS_FILE, {})

def get_channel_category(channel_name):
    category_keywords = get_category_keywords()
    if not category_keywords:
        return "ALTRI"
    channel_name_lower = channel_name.lower()
    for category, keywords in category_keywords.items():
        for keyword in keywords:
            if keyword.lower() in channel_name_lower:
                return category
    return "ALTRI"

def get_vavoo_signature():
    try:
        if os.path.exists(CHIAVE_SCRIPT):
            result = subprocess.run(['python3', CHIAVE_SCRIPT], capture_output=True, text=True, check=True)
            if result.stdout.strip():
                return result.stdout.strip()
        result = subprocess.run(['python3', M3U8_GENERATOR, '--get-signature'], capture_output=True, text=True, check=True)
        return result.stdout.strip() if result.stdout.strip() else None
    except Exception as e:
        print(f"Errore signature: {e}")
        return None

def create_manifest(mf_url, mf_psw):
    categories = get_category_keywords()
    catalogs = [{"type": "tv", "id": f"mediaflow-{category}", "name": f"MediaFlow - {category}", 
               "extra": [{"name": "search", "isRequired": False}]} for category in categories.keys()]
    return {
        "id": "org.mediaflow.iptv", "name": "MediaFlow IPTV", "version": "1.0.0",
        "description": f"Watch IPTV channels from MediaFlow service ({mf_url})",
        "resources": ["catalog", "meta", "stream"], "types": ["tv"], "catalogs": catalogs,
        "idPrefixes": ["mediaflow-"], "behaviorHints": {"configurable": False, "configurationRequired": False},
        "logo": "https://dl.strem.io/addon-logo.png", "icon": "https://dl.strem.io/addon-logo.png",
        "background": "https://dl.strem.io/addon-background.jpg",
    }

def generate_m3u8_list():
    try:
        if not os.path.exists(M3U8_GENERATOR):
            print(f"ERRORE: Script {M3U8_GENERATOR} non trovato!")
            return False
        result = subprocess.run(['python3', M3U8_GENERATOR], capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(M3U8_FILE):
            print(f"Lista M3U8 generata. Dimensione: {os.path.getsize(M3U8_FILE)} bytes")
            return True
        else:
            print(f"ERRORE generazione M3U8: {result.stderr}")
            return False
    except Exception as e:
        print(f"ERRORE esecuzione generatore: {e}")
        return False

def parse_m3u8_to_channels():
    channels = []
    try:
        if not os.path.exists(M3U8_FILE):
            if not generate_m3u8_list():
                return []
        with open(M3U8_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        channel, headers, sig_placeholder = None, {}, None
        for line in lines:
            line = line.strip()
            if line.startswith('#EXTINF:'):
                channel = {}
                tvg_id_match = re.search(r'tvg-id="([^"]+)"', line)
                channel['id'] = tvg_id_match.group(1).replace(' ', '-').lower() if tvg_id_match else f"channel-{len(channels)}"
                
                name_match = re.search(r',([^\n]+)$', line)
                channel['name'] = name_match.group(1).strip() if name_match else f"Channel {len(channels)}"
                
                genre_match = re.search(r'group-title="([^"]+)"', line)
                channel['genre'] = genre_match.group(1) if genre_match else get_channel_category(channel['name'])
                
                logo_match = re.search(r'tvg-logo="([^"]+)"', line)
                channel['logo'] = logo_match.group(1) if logo_match else ""
                
                headers, sig_placeholder = {}, None
            elif line.startswith('#EXTVLCOPT:'):
                if "http-user-agent=" in line:
                    headers['user-agent'] = line.split('=', 1)[1]
                elif "http-origin=" in line:
                    headers['origin'] = line.split('=', 1)[1]
                elif "http-referrer=" in line:
                    headers['referer'] = line.split('=', 1)[1]
                elif "mediahubmx-signature=" in line:
                    sig_placeholder = line.split('=', 1)[1]
            elif line and not line.startswith('#') and channel:
                channel['url'] = line
                channel['headers'] = headers
                channel['signature_placeholder'] = sig_placeholder
                channels.append(channel)
                channel = None
        
        if channels:
            save_json_file(CHANNELS_FILE, channels)
        return channels
    except Exception as e:
        print(f"Errore analisi M3U8: {e}")
        return []

def get_channels_data():
    global channels_data_cache, channels_data_timestamp
    current_time = time.time()
    
    if not channels_data_cache or (current_time - channels_data_timestamp) > 3600:
        channels = load_json_file(CHANNELS_FILE, [])
        if not channels:
            channels = parse_m3u8_to_channels()
        
        if channels:
            channels_data_cache = channels
            channels_data_timestamp = current_time
    
    return channels_data_cache

def to_meta(channel, mf_url, mf_psw):
    channel_name = clean_channel_name(channel["name"])
    logo = channel.get("logo", "https://dl.strem.io/addon-logo.png")
    genre = channel.get("genre", "ALTRI")
    
    return {
        "id": f"mediaflow-{channel['id']}", "name": channel_name, "type": "tv",
        "genres": [genre], "poster": logo, "posterShape": "square",
        "background": logo, "logo": logo
    }

def resolve_stream_url(channel, mf_url, mf_psw):
    channel_name = clean_channel_name(channel["name"])
    headers = channel.get("headers", {})
    sig_placeholder = channel.get("signature_placeholder")
    stream_url = channel["url"]
    resolved_url, stremio_headers = None, {}
    
    if sig_placeholder == "[$KEY$]":
        signature = get_vavoo_signature()
        
        if signature:
            if "localhost" not in stream_url:
                try:
                    RESOLVER_SCRIPT = os.path.join(BASE_DIR, 'resolver.py')
                    if os.path.exists(RESOLVER_SCRIPT):
                        result = subprocess.run(
                            ['python3', RESOLVER_SCRIPT, '--url', stream_url, '--signature', signature, '--json'],
                            capture_output=True, text=True, timeout=15
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            try:
                                resolver_result = json.loads(result.stdout)
                                if resolver_result["success"] and resolver_result["resolved_url"]:
                                    resolved_url = resolver_result["resolved_url"]
                            except json.JSONDecodeError:
                                resolved_url = result.stdout.strip()
                except Exception as e:
                    print(f"Errore resolver.py: {e}")
            
            if headers:
                stremio_headers = headers.copy()
            
            stremio_headers["mediahubmx-signature"] = signature
            stremio_headers["user-agent"] = "Mozilla/5.0 (Linux; Android 10; Nexus 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.101 Mobile Safari/537.36"
            
            params = {
                "api_password": mf_psw,
                "d": resolved_url or stream_url
            }
            
            for key, value in headers.items():
                params[f"h_{key}"] = value
            
            params["h_mediahubmx-signature"] = signature
            
            mf_url_final = f"https://{mf_url}/proxy/hls/manifest.m3u8?{urlencode(params, quote_via=quote_plus)}"
        else:
            params = {
                "api_password": mf_psw,
                "d": stream_url
            }
            
            for key, value in headers.items():
                params[f"h_{key}"] = value
            
            mf_url_final = f"https://{mf_url}/proxy/hls/manifest.m3u8?{urlencode(params, quote_via=quote_plus)}"
    else:
        params = {
            "api_password": mf_psw,
            "d": stream_url
        }
        
        for key, value in headers.items():
            params[f"h_{key}"] = value
        
        mf_url_final = f"https://{mf_url}/proxy/hls/manifest.m3u8?{urlencode(params, quote_via=quote_plus)}"
        stremio_headers = headers.copy()
        stremio_headers["user-agent"] = "Mozilla/5.0 (Linux; Android 10; Nexus 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.101 Mobile/15E148 Safari/537.36"
        resolved_url = stream_url
    
    streams = [
        {
            "url": mf_url_final,
            "title": f"{channel_name} (MediaFlow Proxy)",
            "name": "MediaFlow"
        }
    ]
    
    url_to_proxy = stream_url
    if "vavoo.to/vto-tv/play/" in url_to_proxy:
        url_to_proxy = url_to_proxy.replace("/vto-tv/play/", "/play/")
        if not url_to_proxy.endswith("/index.m3u8"):
            url_to_proxy = url_to_proxy + "/index.m3u8"
    
    smallprox_params = {
        "url": url_to_proxy,
        "header_Referer": "https://vavoo.to/",
        "header_User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) FxiOS/33.0 Mobile/15E148 Safari/605.1.15",
        "header_Origin": "https://vavoo.to/"
    }
    
    if sig_placeholder == "[$KEY$]" and signature:
        smallprox_params["header_mediahubmx-signature"] = signature
    
    smallprox_url = f"https://smallprox.onrender.com/proxy/m3u8?{urlencode(smallprox_params, quote_via=quote_plus)}"
    
    streams.append({
        "url": smallprox_url,
        "title": f"{channel_name} (SmallProx)",
        "name": "SmallProx"
    })
    
    return streams

def get_all_channels(mf_url, mf_psw):
    if not mf_url or not mf_psw:
        return []
    
    try:
        channels_data = get_channels_data()
        all_channels = []
        for channel in channels_data:
            try:
                meta = to_meta(channel, mf_url, mf_psw)
                all_channels.append(meta)
            except Exception as e:
                print(f"Errore canale {channel.get('name', 'Unknown')}: {e}")
        
        return all_channels
    except Exception as e:
        print(f"Errore in get_all_channels: {e}")
        return []

def refresh_channels_periodically():
    while True:
        try:
            if generate_m3u8_list():
                parse_m3u8_to_channels()
                global channels_data_cache, channels_data_timestamp
                channels_data_cache = []
                channels_data_timestamp = 0
        except Exception as e:
            print(f"Errore aggiornamento canali: {e}")
        time.sleep(20 * 60)

def create_index_template():
    template_path = os.path.join(BASE_DIR, "templates", "index.html")
    template_json_path = os.path.join(BASE_DIR, "template.json")
    
    if not os.path.exists(template_path):
        if os.path.exists(template_json_path):
            template_data = load_json_file(template_json_path)
            html_content = template_data.get("index_html")
            if html_content:
                with open(template_path, "w", encoding="utf-8") as f:
                    f.write(html_content)
            else:
                raise Exception("Template HTML non trovato nel file JSON")
        else:
            raise Exception(f"File template non trovato: {template_json_path}")

# Rotte API
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "default_url": DEFAULT_MF_URL, "default_psw": DEFAULT_MF_PSW, "domain": DOMAIN}
    )

@app.get("/status")
async def status():
    m3u8_exists = os.path.exists(M3U8_FILE)
    m3u8_size = os.path.getsize(M3U8_FILE) if m3u8_exists else 0
    channels_file_exists = os.path.exists(CHANNELS_FILE)
    channels_count = len(load_json_file(CHANNELS_FILE, [])) if channels_file_exists else 0
    cache_channels = len(channels_data_cache)
    m3u8_generator_exists = os.path.exists(M3U8_GENERATOR)
    chiave_script_exists = os.path.exists(CHIAVE_SCRIPT)
    
    return {
        "m3u8_file": {"exists": m3u8_exists, "size_bytes": m3u8_size, "path": M3U8_FILE},
        "channels_file": {"exists": channels_file_exists, "channels_count": channels_count, "path": CHANNELS_FILE},
        "cache": {"channels_in_cache": cache_channels, "cache_timestamp": channels_data_timestamp},
        "scripts": {
            "m3u8_generator": {"exists": m3u8_generator_exists, "path": M3U8_GENERATOR},
            "chiave_script": {"exists": chiave_script_exists, "path": CHIAVE_SCRIPT}
        },
        "categories": list(get_category_keywords().keys())
    }

@app.get("/mfp/{url}/psw/{psw}/manifest.json")
async def manifest_with_params(url: str, psw: str):
    return create_manifest(url, psw)

@app.get("/manifest.json")
async def manifest(request: Request):
    mf_url, mf_psw = extract_url_params(request)
    return create_manifest(mf_url, mf_psw)

@app.get("/mfp/{url}/psw/{psw}/catalog/{type}/{id}/{search_param}.json")
async def catalog_with_search_param(url: str, psw: str, type: str, id: str, search_param: str):
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"metas": []}
    
    category = id.split("-")[1]
    all_channels = get_all_channels(url, psw)
    
    search = None
    if search_param and search_param.startswith("search="):
        search = unquote(search_param.split("=")[1])
    
    if not search:
        filtered_channels = [c for c in all_channels if c["genres"][0] == category]
    else:
        search = search.lower()
        filtered_channels = [c for c in all_channels if search in c["name"].lower()]
    
    return {"metas": filtered_channels}

@app.get("/mfp/{url}/psw/{psw}/catalog/{type}/{id}.json")
async def catalog_with_params(url: str, psw: str, type: str, id: str, request: Request, genre: str = None, search: str = None):
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"metas": []}
    
    category = id.split("-")[1]
    all_channels = get_all_channels(url, psw)
    
    filtered_channels = [c for c in all_channels if c["genres"][0] == category]
    
    if search:
        search = search.lower()
        filtered_channels = [c for c in all_channels if search in c["name"].lower()]
    
    return {"metas": filtered_channels}

@app.get("/catalog/{type}/{id}.json")
async def catalog(type: str, id: str, request: Request, genre: str = None, search: str = None):
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"metas": []}
    
    mf_url, mf_psw = extract_url_params(request)
    category = id.split("-")[1]
    all_channels = get_all_channels(mf_url, mf_psw)
    
    filtered_channels = [c for c in all_channels if c["genres"][0] == category]
    
    if search:
        search = search.lower()
        filtered_channels = [c for c in all_channels if search in c["name"].lower()]
    
    return {"metas": filtered_channels}

@app.get("/mfp/{url}/psw/{psw}/meta/{type}/{id}.json")
async def meta_with_params(url: str, psw: str, type: str, id: str):
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"meta": {}}
    
    all_channels = get_all_channels(url, psw)
    channel = next((c for c in all_channels if c["id"] == id), None)
    
    return {"meta": channel} if channel else {"meta": {}}

@app.get("/meta/{type}/{id}.json")
async def meta(type: str, id: str, request: Request):
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"meta": {}}
    
    mf_url, mf_psw = extract_url_params(request)
    all_channels = get_all_channels(mf_url, mf_psw)
    channel = next((c for c in all_channels if c["id"] == id), None)
    
    return {"meta": channel} if channel else {"meta": {}}

@app.get("/mfp/{url}/psw/{psw}/stream/{type}/{id}.json")
async def stream_with_params(url: str, psw: str, type: str, id: str):
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"streams": []}
    
    all_channels = get_all_channels(url, psw)
    original_channel = next((c for c in channels_data_cache if f"mediaflow-{c['id']}" == id), None)
    
    if not original_channel:
        return {"streams": []}
    
    stream_info = resolve_stream_url(original_channel, url, psw)
    
    return {"streams": stream_info}

@app.get("/stream/{type}/{id}.json")
async def stream(type: str, id: str, request: Request):
    if type != "tv" or not id.startswith("mediaflow-"):
        return {"streams": []}
    
    mf_url, mf_psw = extract_url_params(request)
    original_channel = next((c for c in channels_data_cache if f"mediaflow-{c['id']}" == id), None)
    
    if not original_channel:
        return {"streams": []}
    
    stream_info = resolve_stream_url(original_channel, mf_url, mf_psw)
    
    return {"streams": stream_info}

# Avvio dell'applicazione
if __name__ == "__main__":
    create_index_template()
    
    if generate_m3u8_list():
        channels = parse_m3u8_to_channels()
    
    update_thread = threading.Thread(target=refresh_channels_periodically, daemon=True)
    update_thread.start()
    
    uvicorn.run(app, host="0.0.0.0", port=PORT)
