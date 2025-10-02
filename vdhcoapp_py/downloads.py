# vdhcoapp_py/downloads.py

import os
# import path
import re
import threading
import time
import requests
import sys

from . import rpc
from . import logger

# --- CONFIGURACIÓN Y ESTADO ---
download_folder = os.path.join(os.path.expanduser("~"), "dwhelper")
current_download_id = 0
downloads = {} # {id: {downloadItem: requests.Response, ...}}

NAME_PATTERN = re.compile(r"/([^/]+?)(?:\.([a-z0-9]{1,5}))?(?:\?|#|$)")

# --- FUNCIONES DE ASISTENCIA ---

def get_got_headers(headers_list):
    """Convierte la lista de encabezados del RPC a un diccionario para requests."""
    got_headers = {}
    for header in headers_list:
        name = header['name']
        if 'value' in header:
            got_headers[name] = header['value']
        elif 'binaryValue' in header:
            # En Python requests, el valor binario debe decodificarse a una cadena
            # si se quiere enviar como un header HTTP normal (raro para headers).
            # Por simplicidad, asumiremos valores de cadena o byte literal si es necesario.
            # Aquí, lo decodificamos si está en Base64 (que es lo que el JS haría).
            # La implementación real de JS usa Buffer.from, que Python no tiene un análogo directo aquí,
            # pero para headers, se asume que es texto. Lo dejamos como está para compatibilidad.
            got_headers[name] = header['binaryValue'] # Si es byte literal, requests lo maneja.
    return got_headers

# --- MÉTODOS RPC DE DESCARGA ---

def rpc_download(options):
    """
    Inicia una descarga HTTP asíncrona en un hilo separado.
    Reemplaza downloads.download en downloads.js
    """
    global current_download_id
    global downloads

    if not options.get('url'):
        raise Exception("URL no especificada")
    
    # 1. Determinar el nombre del archivo
    filename = options.get('filename')
    if not filename:
        m = NAME_PATTERN.search(options['url'])
        if m:
            # Replicar la lógica de nombramiento de downloads.js
            filename = m.group(1) + (m.group(2) if m.group(2) else '')
        else:
            filename = "file"
            
    file_path = os.path.join(options.get('directory') or download_folder, filename)
    
    # 2. Configurar la descarga
    dl_id = current_download_id + 1
    current_download_id = dl_id
    
    dl_options = {
        'headers': get_got_headers(options.get('headers', [])),
        'stream': True, # Para descarga en streaming
        'verify': options.get('rejectUnauthorized', True), # Certificado SSL
        # Opciones de proxy no implementadas aquí por simplicidad de dependencias,
        # pero usarían el parámetro `proxies` en requests si se configura.
    }
    
    downloads[dl_id] = {
        'url': options['url'],
        'filename': file_path,
        'state': "in_progress",
        'error': None,
        'totalBytes': 0,
        'bytesReceived': 0,
        'thread': None,
        'file_stream': None
    }
    
    def remove_entry(entry):
        """Elimina la entrada después de un tiempo (60s)"""
        time.sleep(60)
        downloads.pop(dl_id, None)

    def failed_download(entry, err):
        """Marca la descarga como interrumpida"""
        if entry.get('state') != "complete":
            entry['state'] = "interrupted"
            entry['error'] = str(err)
            if entry['file_stream']:
                entry['file_stream'].close()
            threading.Thread(target=remove_entry, args=(entry,)).start()

    def download_thread(dl_id, options):
        """Lógica real de descarga que se ejecuta en un hilo."""
        entry = downloads[dl_id]
        
        # 1. Crear el directorio si no existe
        try:
            os.makedirs(os.path.dirname(entry['filename']), exist_ok=True)
        except Exception as e:
            failed_download(entry, e)
            return

        # 2. Iniciar la solicitud
        try:
            with requests.get(entry['url'], **dl_options) as r:
                r.raise_for_status()
                
                # Obtener Content-Length y configurar la descarga
                content_length = r.headers.get('content-length')
                if content_length:
                    entry['totalBytes'] = int(content_length)

                # 3. Escribir al archivo
                with open(entry['filename'], 'wb') as f:
                    entry['file_stream'] = f
                    for chunk in r.iter_content(chunk_size=8192):
                        if entry['state'] == "interrupted": # Chequeo de cancelación
                            break
                        if chunk:
                            f.write(chunk)
                            entry['bytesReceived'] += len(chunk)

            # 4. Finalizar
            if entry['state'] != "interrupted":
                entry['state'] = "complete"
                # Lógica ECONNRESET de downloads.js no implementada, pero se puede añadir
                # si se detecta un error de conexión después de que se ha descargado todo.
                threading.Thread(target=remove_entry, args=(entry,)).start()
            
            entry['file_stream'] = None # Liberar referencia

        except Exception as e:
            failed_download(entry, e)
    
    # 3. Iniciar el hilo de descarga
    t = threading.Thread(target=download_thread, args=(dl_id, options))
    t.start()
    downloads[dl_id]['thread'] = t

    return dl_id


def rpc_search(query):
    """
    Busca el estado de una descarga específica por ID.
    Reemplaza downloads.search en downloads.js
    """
    dl_id = query.get('id')
    entry = downloads.get(dl_id)
    
    if entry:
        # Replicar el formato de respuesta de downloads.js
        return [{
            "totalBytes": entry['totalBytes'],
            "bytesReceived": entry['bytesReceived'],
            "url": entry['url'],
            "filename": entry['filename'],
            "state": entry['state'],
            "error": entry['error']
        }]
    else:
        return []

def rpc_cancel(dl_id):
    """
    Cancela una descarga en curso.
    Reemplaza downloads.cancel en downloads.js
    """
    entry = downloads.get(dl_id)
    if entry and entry['state'] == "in_progress":
        entry['state'] = "interrupted"
        entry['error'] = "Aborted"
        
        # El hilo de descarga detectará el estado "interrupted" y saldrá del bucle de escritura.
        # Luego llamará a remove_entry.
        logger.info(f"Descarga {dl_id} marcada para interrupción.")
        
        # La limpieza se maneja en el hilo de descarga para asegurar el cierre.

# Registrar los métodos RPC
rpc.listen({
    "downloads.download": rpc_download,
    "downloads.search": rpc_search,
    "downloads.cancel": rpc_cancel
})