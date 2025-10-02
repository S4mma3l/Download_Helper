# vdhcoapp_py/rpc.py

import json
import threading
import traceback
import sys
from concurrent.futures import Future

# Variable para generar IDs de solicitud únicos (similar a guuid en JS).
global_uuid = 0
# Mapa para almacenar las promesas (Future objects) de las peticiones salientes.
promise_map = {}
# Mapa para almacenar las funciones de los métodos que la CoApp puede ejecutar.
handler_map = {}
# Objeto para enviar mensajes al proceso principal (configurado por native_messaging.py).
post_function = None
# Objeto para logging (simplemente usamos console/stderr por ahora).
logger = sys.stderr

def set_post(post_func):
    """Establece la función para enviar el mensaje serializado de vuelta al navegador."""
    global post_function
    post_function = post_func

def set_logger(log_obj):
    """Establece el objeto de logging."""
    global logger
    logger = log_obj

def listen(listeners):
    """Registra los manejadores de métodos que la extensión puede llamar."""
    global handler_map
    handler_map.update(listeners)

def receive(message, send, peer=None):
    """
    Procesa un mensaje entrante (Petición o Respuesta).
    Implementa la lógica central de weh-rpc.js: receive().
    """
    global logger
    
    # Manejo de Respuesta (el navegador responde a una llamada nuestra)
    if message.get('_reply'):
        reply_id = message['_reply']
        # Buscar la promesa (Future) asociada a esta respuesta.
        future_obj = promise_map.pop(reply_id, None)
        
        if not future_obj:
            logger.write(f"RPC ERROR: Falta manejador de respuesta para ID {reply_id}\n")
            return

        if message.get('_error'):
            # Rechazar la promesa con el mensaje de error.
            error_message = message['_error']
            logger.write(f"RPC WARNING: Recibido error para ID {reply_id}: {error_message}\n")
            # Usamos una excepción para replicar el comportamiento de rechazo de promesa.
            future_obj.set_exception(Exception(error_message))
        else:
            # Resolver la promesa con el resultado.
            result = message.get('_result')
            future_obj.set_result(result)
            
    # Manejo de Petición (el navegador nos llama)
    elif message.get('_request'):
        request_id = message['_request']
        method_name = message.get('_method')
        args = message.get('_args', [])
        
        # Debe correr en un hilo separado o en un pool de ejecución para no bloquear
        # la lectura de más mensajes (simulando el asincronismo de Node.js).
        # Esto previene que una operación larga como 'convert' detenga la comunicación.
        def execute_request():
            try:
                handler = handler_map.get(method_name)
                
                if not handler:
                    raise Exception(f"Método '{method_name}' no registrado.")

                # Ejecutar el método del manejador.
                result = handler(*args)
                
                # Si el resultado es una 'Future' o similar (operación asíncrona),
                # esperar su finalización (opcionalmente, si se sabe que es síncrono, se omite).
                # En Python, simplemente esperamos un valor. Si el manejador es asíncrono,
                # debería estar dentro de un pool o hilo, o la función 'receive' ser async.
                
                # Enviar la respuesta de éxito.
                send({
                    "type": "weh#rpc",
                    "_reply": request_id,
                    "_result": result
                })

            except Exception as e:
                logger.write(f"RPC ERROR: Error al ejecutar método '{method_name}': {e}\n")
                # Enviar respuesta de error.
                send({
                    "type": "weh#rpc",
                    "_reply": request_id,
                    "_error": str(e) # Enviar solo el mensaje de error como hace JS.
                })

        # Ejecutar en un nuevo hilo.
        threading.Thread(target=execute_request).start()

def call(method, *args):
    """
    Realiza una llamada RPC desde la CoApp al navegador (Cliente RPC).
    Implementa la lógica central de weh-rpc.js: call().
    """
    global global_uuid
    global post_function
    
    if not post_function:
        raise Exception("La función 'post' no ha sido configurada.")

    # Crear una ID para la solicitud.
    global_uuid += 1
    request_id = global_uuid
    
    # Crear el mensaje de solicitud.
    request_message = {
        "type": "weh#rpc",
        "_request": request_id,
        "_method": method,
        "_args": list(args),
    }

    # Crear un objeto Future para manejar la respuesta asíncrona.
    future = Future()
    promise_map[request_id] = future
    
    # Enviar la solicitud.
    post_function(request_message)

    # Bloquear y esperar el resultado (simulando la espera de una promesa).
    # En un entorno Node.js, esto sería asíncrono; aquí es un bloqueo.
    return future.result()

# El resto de módulos de Python (como converter.py o downloads.py) llamarán a rpc.call()
# para comunicarse con la extensión del navegador (ej. para enviar notificaciones de progreso).