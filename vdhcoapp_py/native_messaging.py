# vdhcoapp_py/native_messaging.py

import sys
import json
import struct # Para manejar los 4 bytes little-endian de longitud
import threading
from . import rpc # Importamos nuestro módulo RPC

logger = sys.stderr # Usado antes de cargar el logger real

def send_message(message):
    """
    Envía un objeto JSON al navegador usando el protocolo de Native Messaging.
    (4 bytes little-endian para la longitud + contenido JSON UTF-8)
    """
    try:
        # Serializar el objeto a una cadena JSON UTF-8
        msg_str = json.dumps(message, ensure_ascii=False)
        msg_bytes = msg_str.encode('utf-8')
        
        # Calcular la longitud de los datos
        msg_length = len(msg_bytes)
        
        # Empaquetar la longitud en 4 bytes little-endian (UInt32LE en Node.js)
        # El formato '<I' significa: '<' little-endian, 'I' unsigned integer (4 bytes)
        length_bytes = struct.pack('<I', msg_length)

        # Escribir la longitud y luego el mensaje al stdout (binario)
        sys.stdout.buffer.write(length_bytes)
        sys.stdout.buffer.write(msg_bytes)
        sys.stdout.buffer.flush() # Asegurar el envío inmediato

    except Exception as e:
        logger.write(f"ERROR al enviar mensaje: {e}\n")

def read_message():
    """
    Lee un mensaje del navegador usando el protocolo de Native Messaging.
    Bloquea hasta que se lee un mensaje completo.
    """
    try:
        # Leer los primeros 4 bytes (longitud) en modo binario
        length_bytes = sys.stdin.buffer.read(4)
        if not length_bytes:
            # Fin de la entrada (el navegador cerró el pipe)
            return None 

        # Desempaquetar los 4 bytes a un entero little-endian (longitud del mensaje)
        msg_length = struct.unpack('<I', length_bytes)[0]
        
        if msg_length == 0:
            return None

        # Leer el mensaje JSON completo
        msg_bytes = sys.stdin.buffer.read(msg_length)
        if len(msg_bytes) != msg_length:
            logger.write("ERROR: Lectura incompleta del mensaje.\n")
            return None
        
        # Decodificar el mensaje a una cadena UTF-8 y luego a un objeto JSON
        msg_str = msg_bytes.decode('utf-8')
        logger.write(f"DEBUG: Mensaje RPC recibido: {msg_str}\n")
        msg_object = json.loads(msg_str)
        
        return msg_object

    except Exception as e:
        logger.write(f"ERROR al leer mensaje: {e}\n")
        return None

def start_messaging_loop():
    """Bucle principal de lectura que simula el listener de stdin en native-messaging.js."""
    global logger
    logger.write("=================== iniciado ====================\n") # Simula log de native-messaging.js

    # Configurar la función de post para el RPC, usando nuestra función de envío.
    rpc.set_post(send_message)

    # Iniciar el bucle de lectura de mensajes.
    while True:
        message = read_message()
        if message is None:
            # La conexión se cerró (navegador o pipe)
            logger.write("=================== terminado ===================\n") # Simula log de native-messaging.js
            break
        
        # Enviar el mensaje recibido a la capa RPC para su procesamiento.
        # rpc.receive gestiona si es una petición o una respuesta.
        rpc.receive(message, send_message)
        
    sys.exit(0) # Salir después de que el pipe se cierre.