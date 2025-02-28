#!/usr/bin/env python3
import requests
import sys
import json
import argparse

def resolve_link(link, signature):
    """
    Risolve un link di Vavoo utilizzando la signature fornita.
    
    Args:
        link (str): L'URL da risolvere
        signature (str): La signature di autenticazione Vavoo
        
    Returns:
        str: L'URL risolto o None in caso di errore
    """
    if "localhost" in link:
        return link

    headers = {
        "user-agent": "MediaHubMX/2",
        "accept": "application/json",
        "content-type": "application/json; charset=utf-8",
        "accept-encoding": "gzip",
        "mediahubmx-signature": signature
    }

    data = {
        "language": "de",
        "region": "AT",
        "url": link,
        "clientVersion": "3.0.2"
    }

    try:
        response = requests.post("https://vavoo.to/vto-cluster/mediahubmx-resolve.json", json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        if isinstance(result, list) and result and "url" in result[0]:
            return result[0]["url"]
    except Exception as e:
        print(f"Errore durante la risoluzione del link: {e}", file=sys.stderr)
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Risolvi un link Vavoo')
    parser.add_argument('--url', required=True, help='URL da risolvere')
    parser.add_argument('--signature', required=True, help='Signature per autenticazione')
    parser.add_argument('--json', action='store_true', help='Restituisci output in formato JSON')
    
    args = parser.parse_args()
    
    resolved_url = resolve_link(args.url, args.signature)
    
    if args.json:
        result = {
            "original_url": args.url,
            "resolved_url": resolved_url,
            "success": resolved_url is not None
        }
        print(json.dumps(result))
    else:
        if resolved_url:
            print(resolved_url)
        else:
            print("Errore: Impossibile risolvere l'URL", file=sys.stderr)
            sys.exit(1)
