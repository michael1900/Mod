#!/usr/bin/env python3
import requests
import json
import sys
import os

def get_auth_signature():
    """
    Recupera la firma di autenticazione dalle API di Vavoo.
    Restituisce la signature come stringa o None in caso di errore.
    """
    headers = {
        "user-agent": "okhttp/4.11.0",
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
        "content-length": "1106",
        "accept-encoding": "gzip"
    }

    data = {
        "token": "8Us2TfjeOFrzqFFTEjL3E5KfdAWGa5PV3wQe60uK4BmzlkJRMYFu0ufaM_eeDXKS2U04XUuhbDTgGRJrJARUwzDyCcRToXhW5AcDekfFMfwNUjuieeQ1uzeDB9YWyBL2cn5Al3L3gTnF8Vk1t7rPwkBob0swvxA",
        "reason": "player.enter",
        "locale": "de",
        "theme": "dark",
        "metadata": {
            "device": {
                "type": "Handset",
                "brand": "google",
                "model": "Nexus 5",
                "name": "21081111RG",
                "uniqueId": "d10e5d99ab665233"
            },
            "os": {
                "name": "android",
                "version": "7.1.2",
                "abis": ["arm64-v8a", "armeabi-v7a", "armeabi"],
                "host": "android"
            },
            "app": {
                "platform": "android",
                "version": "3.0.2",
                "buildId": "288045000",
                "engine": "jsc",
                "signatures": ["09f4e07040149486e541a1cb34000b6e12527265252fa2178dfe2bd1af6b815a"],
                "installer": "com.android.secex"
            },
            "version": {
                "package": "tv.vavoo.app",
                "binary": "3.0.2",
                "js": "3.1.4"
            }
        },
        "appFocusTime": 27229,
        "playerActive": True,
        "playDuration": 0,
        "devMode": False,
        "hasAddon": True,
        "castConnected": False,
        "package": "tv.vavoo.app",
        "version": "3.1.4",
        "process": "app",
        "firstAppStart": 1728674705639,
        "lastAppStart": 1728674705639,
        "ipLocation": "",
        "adblockEnabled": True,
        "proxy": {
            "supported": ["ss"],
            "engine": "ss",
            "enabled": False,
            "autoServer": True,
            "id": "ca-bhs"
        },
        "iap": {
            "supported": False
        }
    }

    try:
        response = requests.post("https://www.vavoo.tv/api/app/ping", json=data, headers=headers)
        response.raise_for_status()
        res_json = response.json()
        return res_json.get("addonSig")
    except Exception as e:
        print(f"Errore durante il recupero della firma: {e}")
        return None

# Se lo script viene eseguito direttamente, stampa la signature
if __name__ == "__main__":
    signature = get_auth_signature()
    if signature:
        print(signature)
    else:
        print("Non è stato possibile ottenere la signature")
        sys.exit(1)
