FROM python:3.10-slim

WORKDIR /app

# Installa le dipendenze
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia i file dell'applicazione
COPY app.py .
COPY *.json ./

# Espone la porta
EXPOSE 3000

# Avvia l'applicazione
CMD ["python", "app.py"]
