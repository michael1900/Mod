# Usa un'immagine Python leggera
FROM python:3.9-slim

# Imposta la directory di lavoro
WORKDIR /app

# Copia i file necessari nel container
COPY . /app

# Installa le dipendenze da requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Assicura i permessi di scrittura per tutti sulla cartella /app
RUN chmod -R 777 /app

# Espone la porta 3000 per FastAPI
EXPOSE 3000

# Avvia l'applicazione
CMD ["python", "app.py"]
