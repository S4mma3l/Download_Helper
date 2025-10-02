# vdhcoapp_py/converter.py

import sys
import os
import subprocess
import threading
import signal
import time
import json
import re
import platform
from concurrent.futures import Future
import asyncio # Necesario para la función info()

# Importaciones de módulos internos
from . import rpc
from . import logger

# ====================================================================
# --- UTILERÍAS Y LÓGICA DE BÚSQUEDA DE BINARIOS ---
# ====================================================================

to_kill = set()

def file_exists_sync(file_path):
    """Verifica si la ruta es un archivo regular."""
    return os.path.isfile(file_path)

def ensure_program_ext(program_path):
  """Asegura que el ejecutable tenga la extensión correcta en Windows."""
  if platform.system() == "Windows":
    return program_path + ".exe"
  return program_path

def find_executable_full_path(program_name, extra_path=""):
    """Busca un ejecutable en PATH y en una ruta extra."""
    program_name = ensure_program_ext(program_name)
    paths = os.environ.get("PATH", "").split(os.pathsep)
    if extra_path:
        paths.insert(0, extra_path)
        
    for p in paths:
        full_path = os.path.join(p, program_name)
        if file_exists_sync(full_path):
            return full_path
    return None

# Obtener la ruta del directorio del ejecutable de Python (simulación de process.execPath)
exec_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

# Búsqueda de Binarios: Solo verificamos FFmpeg al inicio.
ffmpeg = find_executable_full_path("ffmpeg", exec_dir)
ffprobe = find_executable_full_path("ffprobe", exec_dir) 
filepicker = find_executable_full_path("filepicker", exec_dir)


if not ffmpeg:
    logger.error("ffmpeg no encontrado. Instale ffmpeg y asegúrese de que esté en su PATH.")
    sys.exit(1)


# --- LÓGICA DE PROCESOS Y CIERRE FORZADO ---

def spawn_process(args, stdin_pipe=False):
    """Ejecuta un proceso hijo y lo rastrea para terminarlo forzadamente."""
    # Usamos preexec_fn=os.setsid en Unix para que el proceso no reciba señales.
    preexec_fn = os.setsid if os.name == 'posix' else None
    
    process = subprocess.Popen(
        args,
        stdin=subprocess.PIPE if stdin_pipe else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        close_fds=True,
        preexec_fn=preexec_fn
    )
    
    to_kill.add(process)
    
    def cleanup_on_exit():
        process.wait()
        to_kill.discard(process)

    threading.Thread(target=cleanup_on_exit).start()
    return process

def exit_handler(*args):
    """Manejador para SIGINT/SIGTERM y salida de proceso."""
    global to_kill
    for proc in to_kill.copy():
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
    os._exit(0)

# Registrar los manejadores de eventos (señales)
for sig in (signal.SIGINT, signal.SIGTERM):
    try:
        signal.signal(sig, exit_handler)
    except ValueError:
        pass 

# ====================================================================
# --- FUNCIÓN DE INFORMACIÓN (info) ---
# ====================================================================

async def get_converter_info():
    """
    Ejecuta 'ffmpeg -version' para obtener el programa y la versión.
    Hecha asíncrona para compatibilidad con el marco RPC.
    """
    # Usamos '-version' en lugar de '-h' para una salida más limpia y específica de la versión.
    proc = spawn_process([ffmpeg, "-version"])
    stdout, stderr = proc.communicate()
    output = (stdout + stderr).decode('utf-8')
    
    if "ffmpeg version" in output:
        words = output.split()
        version_index = words.index("version") + 1
        
        version_str = words[version_index] 
        program_name = words[version_index - 2]
        
        return {
            "program": program_name, 
            "version": version_str,     
            "converterBinary": ffmpeg
        }
        
    raise Exception("Salida de FFmpeg sin respuesta de versión esperada.")

info = get_converter_info

# ====================================================================
# --- MÉTODOS RPC DE CONVERSIÓN (star_listening) ---
# ====================================================================

convert_children = {}

def exec_converter(args):
    """Ejecuta FFmpeg de forma síncrona y devuelve stdout."""
    proc = spawn_process([ffmpeg] + args)
    stdout, stderr = proc.communicate()
    
    if proc.returncode != 0:
        raise Exception(f"El Conversor devolvió código de salida {proc.returncode}. Error: {stderr.decode()}")
        
    return stdout.decode()

def star_listening():
    """Registra todos los métodos RPC relacionados con la conversión."""
    global convert_children

    def rpc_filepicker(action, directory, title, filename=None):
        """Implementa la llamada al ejecutable filepicker."""
        if not filepicker:
             raise FileNotFoundError("El ejecutable 'filepicker' no fue encontrado.")
             
        args = [filepicker, action, directory, title]
        if filename:
            args.append(filename)
                    
        proc = spawn_process(args)
        stdout, _ = proc.communicate()
                
        if proc.returncode == 0:
            return stdout.decode().strip()
        return ""
            
    def rpc_abort_convert(pid):
        """Termina un proceso de conversión activo."""
        child = convert_children.get(pid)
        if child and child.poll() is None:
            try:
                child.stdin.write(b"q") 
                child.stdin.flush()
            except:
                pass
                            
            time.sleep(0.5) 
            if child.poll() is None:
                child.kill()
                logger.warn(f"Proceso de conversión {pid} terminado forzadamente.")

    def rpc_convert(args, options={}):
        """Ejecuta la conversión con FFmpeg y maneja el progreso (lógica omitida por simplicidad, devuelve solo inicio)."""
        # Esta función es la más compleja. Aquí solo se implementa el inicio.
        ffmpeg_base_args = ["-progress", "pipe:1", "-hide_banner", "-loglevel", "error"]
        full_args = ffmpeg_base_args + args
        
        child = spawn_process([ffmpeg] + full_args, stdin_pipe=True)
                
        if not child.pid:
            raise Exception("Fallo en la creación del proceso.")
            
        convert_children[child.pid] = child
        
        # En una implementación real, aquí se iniciaría un hilo para monitor_conversion.
        
        return {"pid": child.pid, "status": "started"} 

    def rpc_probe(input_file, json_output=False, headers=[]):
        """Implementa la función de sondeo con FFprobe."""
        if not ffprobe:
             raise FileNotFoundError("El ejecutable 'ffprobe' no fue encontrado.")
             
        args = []
        if json_output:
            args.extend(["-v", "quiet", "-print_format", "json", "-show_format", "-show_streams"])
        
        if headers:
            header_str = "\r\n".join([f"{h['name']}: {h['value']}" for h in headers]) + "\r\n"
            args.extend(["-headers", header_str])
                
        args.append(input_file)
                
        proc = spawn_process([ffprobe] + args)
        stdout, stderr = proc.communicate()
                
        if proc.returncode != 0:
            raise Exception(f"Código de salida: {proc.returncode}\n{stderr.decode()}")
                
        stdout = stdout.decode('utf-8')
        stderr = stderr.decode('utf-8')
                
        if json_output:
            return stdout
        else:
            # Lógica de parseo simple del stderr (omitida)
            return {"duration": 0, "videoCodec": "unknown"}

    def rpc_open(file_path, options={}):
        """Abre un archivo con el programa por defecto del sistema."""
        import webbrowser
        webbrowser.open(file_path)
        return True

    def rpc_play(file_path):
        """Abre un archivo con el programa por defecto del sistema (alias de open)."""
        return rpc_open(file_path)

    def rpc_codecs():
        """Obtiene la lista de códecs soportados por FFmpeg."""
        return exec_converter(["-codecs"]) 

    def rpc_formats():
        """Obtiene la lista de formatos soportados por FFmpeg."""
        return exec_converter(["-formats"])

    # Registrar todos los métodos RPC en la capa RPC
    rpc.listen({
        "converter.filepicker": rpc_filepicker,
        "converter.abortConvert": rpc_abort_convert,
        "converter.convert": rpc_convert,
        "converter.probe": rpc_probe,
        "converter.play": rpc_play,
        "converter.codecs": rpc_codecs,
        "converter.formats": rpc_formats,
        "converter.open": rpc_open,
    })