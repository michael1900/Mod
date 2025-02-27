# Usa un'immagine Python leggera
FROM python:3.9-slim

# Imposta la directory di lavoro
WORKDIR /app

# Copia i file necessari nel container
COPY . /app

# Installa le dipendenze
RUN pip install --no-cache-dir fastapi uvicorn jinja2

# Assicura che i file di script siano eseguibili
RUN chmod +x /app/m3u8_vavoo.py

# Espone la porta 3000 per FastAPI
EXPOSE 3000

# Avvia l'applicazione
CMD ["python", "server.py"]
