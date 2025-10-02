# vdhcoapp_py/request_ops.py

import sys
import os
import json
import threading
import time
import requests # Usamos requests como el cliente HTTP
import base64
from collections import deque
from io import BytesIO

from . import rpc
from . import logger

# Constantes definidas en request.js
MAX_SIZE = 50000
EXPIRE_DATA_TIMEOUT = 30000 # 30 segundos

current_index = 0
request_store = {} # {id: {url, data/deque, type, running, timer, ...}}

# --- UTILERÍAS ---

def get_got_headers(headers_list):
    """Convierte la lista de encabezados del RPC a un diccionario para requests."""
    got_headers = {}
    for header in headers_list:
        if 'value' in header:
            got_headers[header['name']] = header['value']
        elif 'binaryValue' in header:
            # En el JS original, esto sería un Buffer, en Python, lo decodificamos si es Base64
            # (aunque los headers HTTP suelen ser cadenas)
            try:
                got_headers[header['name']] = base64.b64decode(header['binaryValue']).decode('utf-8')
            except:
                got_headers[header['name']] = header['binaryValue']
    return got_headers

def get_got_proxy(proxy):
    """Convierte el objeto proxy del RPC a un diccionario de proxies para requests."""
    options_proxy = None
    if proxy and proxy['type'].startswith("http"):
        options_proxy = f"{proxy['type']}://"
        if proxy.get('username'):
            options_proxy += f"{proxy['username']}@"
        options_proxy += f"{proxy['host']}:{proxy['port']}"
        return {'http': options_proxy, 'https': options_proxy}
    return {}

def clear_timer_and_remove(id):
    """Cancela el temporizador de expiración y elimina la entrada."""
    req_info = request_store.pop(id, None)
    if req_info and req_info.get('timer'):
        req_info['timer'].cancel()

def reset_timer(req_info, id):
    """Reinicia el temporizador de expiración para la entrada de solicitud."""
    if req_info.get('timer'):
        req_info['timer'].cancel()
    # Usar threading.Timer para simular setTimeout de JS
    req_info['timer'] = threading.Timer(EXPIRE_DATA_TIMEOUT / 1000, 
                                        lambda: clear_timer_and_remove(id))
    req_info['timer'].start()

def get_data_from_store(id):
    """
    Extrae un fragmento de datos (MAX_SIZE) de la tienda de solicitudes.
    Lógica central de fragmentación (GetData).
    """
    req_info = request_store.get(id)
    if not req_info:
        raise Exception("No existe tal ID de solicitud")

    if req_info.get('error'):
        error = req_info['error']
        clear_timer_and_remove(id)
        raise error
    
    reset_timer(req_info, id)

    data = None
    more = True

    if req_info['type'] == "buffer": # requestBinary
        ret_buffers = []
        ret_length = 0
        
        # Extraer fragmentos completos
        while req_info['data'] and ret_length + len(req_info['data'][0]) <= MAX_SIZE:
            buffer = req_info['data'].popleft()
            ret_buffers.append(buffer)
            ret_length += len(buffer)
        
        # Si aún queda espacio, tomar una porción parcial del siguiente fragmento
        remaining_length = MAX_SIZE - ret_length
        if req_info['data'] and remaining_length > 0:
            buffer = req_info['data'].popleft()
            buffer2 = buffer[:remaining_length]
            ret_buffers.append(buffer2)
            ret_length += len(buffer2)
            
            # Devolver el resto del fragmento a la cola
            buffer3 = buffer[remaining_length:]
            if buffer3:
                req_info['data'].appendleft(buffer3)

        more = req_info['running'] or bool(req_info['data'])
        
        if not more:
            clear_timer_and_remove(id)
            
        if ret_buffers:
            data = b"".join(ret_buffers)
        elif not more:
            data = b"" # Búfer vacío
        else:
            # Esperando datos del hilo de descarga
            raise Exception("WaitingForData") 
            
    else: # Tipo 'text' (request)
        start = req_info['position']
        end = start + MAX_SIZE
        data = req_info['data'][start:end]
        req_info['position'] += len(data)

        if req_info['position'] == len(req_info['data']):
            more = False
            clear_timer_and_remove(id)

    # El resultado final se devuelve como diccionario
    if data is not None:
        return {
            "id": id,
            # Devolver lista de bytes para datos binarios (compatible con test suite JS)
            "data": data.decode('utf-8') if req_info['type'] == 'text' else list(data), 
            "more": more
        }

    raise Exception("WaitingForData")

# --- MÉTODOS RPC ---

def rpc_request(url, options={}):
    """Realiza una solicitud HTTP y devuelve el primer fragmento de texto."""
    global current_index
    current_index += 1
    id = current_index
    
    method = options.get('method', 'GET').upper()
    
    req_options = {
        'headers': get_got_headers(options.get('headers', [])),
        'proxies': get_got_proxy(options.get('proxy')),
    }
    
    try:
        # Usamos requests para una solicitud simple (sin streaming)
        r = requests.request(method, url, **req_options)
        r.raise_for_status()

        # Almacenar como texto para su fragmentación
        request_store[id] = {
            'url': url,
            'position': 0,
            'data': r.text,
            'type': 'text'
        }
        
        return get_data_from_store(id)
    
    except Exception as e:
        raise Exception(str(e))

def rpc_request_extra(id):
    """Solicita el siguiente fragmento de una solicitud HTTP activa."""
    try:
        return get_data_from_store(id)
    except Exception as e:
        # Si está esperando datos, devuelve un fragmento vacío para reintento
        if str(e) == "WaitingForData":
             return {"id": id, "data": [], "more": True}
        raise

def rpc_request_binary(url, options={}):
    """Inicia una solicitud HTTP binaria en streaming (fragmentada)."""
    global current_index
    current_index += 1
    id = current_index
    
    req_options = {
        'headers': get_got_headers(options.get('headers', [])),
        'proxies': get_got_proxy(options.get('proxy')),
        'stream': True
    }
    
    req_info = request_store[id] = {
        'id': id,
        'type': 'buffer',
        'data': deque(), 
        'running': True
    }

    def streaming_thread(url, req_options):
        """Hilo para la descarga binaria en streaming."""
        try:
            with requests.get(url, **req_options) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=MAX_SIZE):
                    if chunk:
                        req_info['data'].append(chunk) 
            
            # Fin del stream
            req_info['running'] = False
        
        except Exception as e:
            if req_info.get('timer'):
                req_info['timer'].cancel()
            
            req_info['error'] = Exception(str(e))
            req_info['running'] = False
        
    # Iniciar el hilo de streaming
    threading.Thread(target=streaming_thread, args=(url, req_options)).start()

    # Devolver el primer fragmento (posiblemente vacío)
    try:
        return get_data_from_store(id)
    except Exception as e:
        return {"id": id, "data": [], "more": True}


# Registrar los métodos RPC
rpc.listen({
    "request": rpc_request,
    "requestExtra": rpc_request_extra,
    "requestBinary": rpc_request_binary
})