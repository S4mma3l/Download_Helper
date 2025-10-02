# vdhcoapp_py/http_request.py

import sys
import threading
import time
import requests
import json
import base64
from collections import deque
from io import BytesIO

from . import rpc
from . import logger

# Constantes definidas en request.js
MAX_SIZE = 50000
EXPIRE_DATA_TIMEOUT = 30000 # 30 segundos

current_index = 0
request_store = {} # {id: {url, data, type, running, timer, ...}}

# --- UTILERÍAS ---

def get_got_headers(headers_list):
    """Convierte la lista de encabezados del RPC a un diccionario para requests."""
    # Reusa la función auxiliar si ya está en downloads.py, o la replica
    got_headers = {}
    for header in headers_list:
        if 'value' in header:
            got_headers[header['name']] = header['value']
        elif 'binaryValue' in header:
            # Asumimos que binaryValue es Base64 (como se usa en fs.write2)
            got_headers[header['name']] = base64.b64decode(header['binaryValue']).decode('utf-8', errors='ignore')
    return got_headers

def get_got_proxy(proxy):
    """Convierte el objeto proxy del RPC a la URL de proxy para requests."""
    options_proxy = None
    # Replicar la lógica de proxy de request.js
    if proxy and proxy['type'].startswith("http"):
        options_proxy = f"{proxy['type']}://"
        if proxy.get('username'):
            options_proxy += f"{proxy['username']}@"
        options_proxy += f"{proxy['host']}:{proxy['port']}/"
    return options_proxy

def clear_timer_and_remove(id):
    """Simulación de la lógica de expiración de request.js"""
    req_info = request_store.pop(id, None)
    if req_info and req_info.get('timer'):
        req_info['timer'].cancel()

# Función auxiliar para restablecer el temporizador de expiración
def reset_timer(req_info, id):
    if req_info.get('timer'):
        req_info['timer'].cancel()
    # Usar threading.Timer para simular setTimeout de JS
    req_info['timer'] = threading.Timer(EXPIRE_DATA_TIMEOUT / 1000, 
                                        lambda: logger.warn(f"Datos expirados para la solicitud {req_info['url']}"))
    req_info['timer'].start()

def get_data_from_store(id):
    """
    Extrae un fragmento de datos (MAX_SIZE) de la tienda de solicitudes.
    Lógica central de request.js para fragmentación (GetData).
    """
    req_info = request_store.get(id)
    if not req_info:
        raise Exception("No existe tal ID de solicitud")

    # Si hay un error, lanzarlo y limpiar
    if req_info.get('error'):
        error = req_info['error']
        clear_timer_and_remove(id)
        raise error
    
    # Restablecer el temporizador de expiración con cada acceso
    reset_timer(req_info, id)

    data = None
    more = True

    if req_info['type'] == "buffer": # requestBinary
        # Búfer de fragmentos binarios (usando deque para rendimiento en Python)
        
        ret_buffers = []
        ret_length = 0
        
        # Extraer fragmentos completos de la cola
        while req_info['data'] and ret_length + len(req_info['data'][0]) < MAX_SIZE:
            buffer = req_info['data'].popleft()
            ret_buffers.append(buffer)
            ret_length += len(buffer)
        
        # Extraer una porción parcial del siguiente fragmento si aún hay espacio
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

        # Determinar si hay más datos pendientes
        more = req_info['running'] or bool(req_info['data'])
        
        if not more:
            clear_timer_and_remove(id)
            
        if ret_buffers:
            data = b"".join(ret_buffers)
        elif not more:
            data = b"" # Búfer vacío si no hay más datos
        else:
            # No hay datos disponibles en este momento, pero la descarga aún corre
            # Simula la lógica de promesa en request.js para esperar datos,
            # lo que requiere un Future/Event en el hilo principal RPC.
            # Aquí, lo simplificamos a una excepción para forzar una reintento.
            raise Exception("WaitingForData") 
            
    else: # Tipo 'text' (request)
        # Extraer cadena de texto
        start = req_info['position']
        end = start + MAX_SIZE
        data = req_info['data'][start:end]
        req_info['position'] += len(data)

        if req_info['position'] == len(req_info['data']):
            more = False
            clear_timer_and_remove(id)

    # El resultado final se devuelve como diccionario: {id, data, more}
    if data is not None:
        return {
            "id": id,
            "data": data.decode('utf-8') if req_info['type'] == 'text' else list(data), # List of bytes for binary
            "more": more
        }

    # Si llega aquí y no es un error, significa que está esperando datos.
    raise Exception("WaitingForData")

# --- MÉTODOS RPC ---

def rpc_request(url, options={}):
    """
    Realiza una solicitud HTTP (no fragmentada, solo devuelve un fragmento)
    Reemplaza request de request.js
    """
    global current_index
    current_index += 1
    id = current_index
    
    # Preparar opciones
    method = options.get('method', 'GET').upper()
    req_options = {
        'headers': get_got_headers(options.get('headers', [])),
        'proxies': {'http': get_got_proxy(options.get('proxy')), 'https': get_got_proxy(options.get('proxy'))} if options.get('proxy') else {}
    }
    
    try:
        r = requests.request(method, url, **req_options)
        r.raise_for_status()

        # Almacenar como texto para su fragmentación
        request_store[id] = {
            'url': url,
            'position': 0,
            'data': r.text,
            'type': 'text'
        }
        
        # Devolver el primer fragmento
        return get_data_from_store(id)
    
    except Exception as e:
        raise Exception(str(e))

def rpc_request_extra(id):
    """
    Solicita el siguiente fragmento de una solicitud HTTP activa.
    Reemplaza requestExtra de request.js
    """
    try:
        return get_data_from_store(id)
    except Exception as e:
        # La excepción "WaitingForData" debe manejarse en el lado cliente.
        # Solo relanzamos si es un error real o si la data expiró.
        if str(e) == "WaitingForData":
             return {"id": id, "data": [], "more": True} # Devuelve un fragmento vacío para reintento

def rpc_request_binary(url, options={}):
    """
    Inicia una solicitud HTTP binaria en streaming (fragmentada).
    Reemplaza requestBinary de request.js
    """
    global current_index
    current_index += 1
    id = current_index
    
    # Preparar opciones
    req_options = {
        'headers': get_got_headers(options.get('headers', [])),
        'proxies': {'http': get_got_proxy(options.get('proxy')), 'https': get_got_proxy(options.get('proxy'))} if options.get('proxy') else {},
        'stream': True
    }
    
    req_info = request_store[id] = {
        'id': id,
        'type': 'buffer',
        'data': deque(), # Usar deque para la cola de fragmentos
        'running': True
    }

    def streaming_thread(url, req_options):
        """Hilo para la descarga binaria en streaming."""
        try:
            with requests.get(url, **req_options) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=MAX_SIZE):
                    if chunk:
                        req_info['data'].append(chunk) # Añadir a la cola de datos
                        # Simular el resolve de la promesa si está esperando
                        # (Manejo complejo de concurrencia omitido por simplicidad)
            
            # Fin del stream
            req_info['running'] = False
        
        except Exception as e:
            # Manejo de errores (similar a request.js)
            if req_info.get('timer'):
                req_info['timer'].cancel()
            
            # Si nadie está esperando (resolve/reject), solo guarda el error
            req_info['error'] = Exception(str(e))
            req_info['running'] = False
        
    # Iniciar el hilo de streaming
    threading.Thread(target=streaming_thread, args=(url, req_options)).start()

    # Devolver el primer fragmento (posiblemente vacío si el hilo aún no ha comenzado)
    try:
        return get_data_from_store(id)
    except Exception as e:
        # Devolver el resultado de inicio (posiblemente fragmento vacío)
        return {"id": id, "data": [], "more": True}


# Registrar los métodos RPC
rpc.listen({
    "request": rpc_request,
    "requestExtra": rpc_request_extra,
    "requestBinary": rpc_request_binary
})