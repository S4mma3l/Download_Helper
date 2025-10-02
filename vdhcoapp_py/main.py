# vdhcoapp_py/main.py

# Importaciones de módulos estándar de Python
import sys
import os
import json
import argparse
import platform
import asyncio
import time 
import tomllib as toml 
from dotenv import load_dotenv # Para cargar el archivo .env

# Importaciones de módulos internos del paquete vdhcoapp_py
from . import rpc
from . import logger
from . import autoinstall
from . import converter
from . import downloads 
from . import file_ops 
from . import request_ops 
from . import vm
from . import native_messaging 

# =================================================================
# --- CARGA DE CONFIGURACIÓN Y .ENV ---
# =================================================================

# Cargar las variables de entorno desde un archivo .env
load_dotenv() 

CONFIG_FILENAME = 'config.toml'
config = None 

# Lógica de búsqueda forzada para el config.toml
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    config_path = os.path.join(project_root, CONFIG_FILENAME)
    
    with open(config_path, 'rb') as f: 
        config = toml.load(f)

except Exception as e:
    # Si la configuración falla, la aplicación no puede iniciar
    print(f"Error fatal: No se pudo encontrar ni cargar {CONFIG_FILENAME}.", file=sys.stderr)
    sys.exit(1)


# =================================================================
# --- FUNCIÓN INFO (ASÍNCRONA) ---
# =================================================================

async def get_info():
    """
    Recopila información de la aplicación y la versión del conversor (FFmpeg).
    
    Returns:
        dict: Objeto JSON con los metadatos de la aplicación y del conversor.
    """
    result = {
        "id": config["meta"]["id"],
        "name": config["meta"]["name"],
        "version": config["meta"]["version"],
        "binary": sys.executable, 
        "displayName": config["meta"]["name"],
        "description": config["meta"]["description"],
        "home": os.path.expanduser("~") or "" 
    }
    
    try:
        # Llama al conversor de forma asíncrona para obtener su información
        conv_info = await converter.info()
        result.update({
            "converterBinary": conv_info.get("converterBinary"),
            "converterBase": conv_info.get("program"),
            "converterBaseVersion": conv_info.get("version")
        })
    except Exception as error:
        result["converterError"] = str(error)
        
    return result

# =================================================================
# --- FUNCIÓN DE DESCARGA AUTÓNOMA (NUEVO CLI) ---
# =================================================================

def autonomous_download(url, output_dir):
    """
    Inicia y monitorea una descarga de video de forma síncrona
    utilizando variables de entorno para la autenticación (Cookie y User-Agent).
    """
    
    # 1. Obtener las claves de autenticación de os.environ
    cookie_value = os.environ.get("USER_SESSION_COOKIE")
    user_agent_value = os.environ.get("USER_AGENT")

    if not cookie_value or not user_agent_value:
        print("❌ Error: USER_SESSION_COOKIE o USER_AGENT no encontrados en .env.", file=sys.stderr)
        print("Por favor, revisa tu archivo .env en el directorio raíz.", file=sys.stderr)
        sys.exit(1)

    try:
        # 2. Preparar las opciones de descarga con los valores del entorno
        options = {
            "url": url,
            "directory": os.path.abspath(output_dir), 
            "filename": None,
            "headers": [
                {"name": "Cookie", "value": cookie_value},
                {"name": "User-Agent", "value": user_agent_value} 
            ]
        }
        
        # 3. Iniciar la descarga
        download_id = downloads.rpc_download(options)

        print(f"✅ Descarga iniciada (ID: {download_id}). Directorio: {options['directory']}")
        
        # 4. Bucle de monitoreo
        while True:
            results = downloads.rpc_search({"id": download_id})
            
            if results:
                entry = results[0]
                state = entry['state']
                
                total_bytes = entry.get('totalBytes', 0)
                received_bytes = entry.get('bytesReceived', 0)
                
                progress = (received_bytes / total_bytes) * 100 if total_bytes > 0 else 0
                
                # Mostrar el progreso en la misma línea
                print(f"Estado: {state} | Progreso: {progress:.2f}% | Recibido: {received_bytes:,} bytes", end='\r')
                
                if state == "complete":
                    print(f"\n🎉 ¡Descarga completa! Archivo guardado como: {entry['filename']}")
                    break
                elif state == "interrupted":
                    print(f"\n❌ Error en la descarga: {entry.get('error', 'Descarga interrumpida')}")
                    break
            
            # Pausa de 1 segundo para evitar saturar el sistema
            time.sleep(1) 
            
    except Exception as e:
        # Manejo de errores durante el proceso de descarga
        print(f"\n❌ Error al iniciar/monitorear la descarga: {e}", file=sys.stderr)
        sys.exit(1)


# =================================================================
# --- LÓGICA PRINCIPAL Y CLI ---
# =================================================================

def main():
    
    # 1. Configuración del analizador de argumentos de línea de comandos
    parser = argparse.ArgumentParser(
        description=f"{config['meta']['name']} CLI y Companion App.",
        add_help=False # Evitar conflicto con nuestra opción --help
    )
    subparsers = parser.add_subparsers(dest='command', help='Comandos disponibles.')

    # Subcomando: download
    download_parser = subparsers.add_parser('download', help='Inicia una descarga de video autónoma.')
    download_parser.add_argument('url', help='URL del video a descargar.')
    download_parser.add_argument('output_dir', help='Directorio de destino para el archivo.')
    
    # Subcomando: install
    install_parser = subparsers.add_parser('install', help='Registra la aplicación con los navegadores.')
    install_parser.add_argument('--user', action='store_true', help='Forzar instalación a nivel de usuario.')
    install_parser.add_argument('--system', action='store_true', help='Forzar instalación a nivel de sistema.')
    
    # Subcomando: uninstall
    uninstall_parser = subparsers.add_parser('uninstall', help='Elimina el registro de la aplicación.')
    uninstall_parser.add_argument('--user', action='store_true', help='Forzar desinstalación a nivel de usuario.')
    uninstall_parser.add_argument('--system', action='store_true', help='Forzar desinstalación a nivel de sistema.')

    # Opciones que pueden estar en cualquier lugar
    parser.add_argument('--version', action='store_true', help='Muestra la versión de la CoApp.')
    parser.add_argument('--info', action='store_true', help='Muestra la información del conversor.')
    parser.add_argument('--help', action='store_true', help='Muestra esta ayuda.')

    try:
        args = parser.parse_args(sys.argv[1:]) 
    except argparse.ArgumentError as e:
        # Si hay un error, se imprime la ayuda y se termina.
        print(f"Error de argumento: {e}", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(1)

    # --- Lógica de Manejo de Comandos ---
    
    if args.command == 'download':
        autonomous_download(args.url, args.output_dir)
        return
        
    elif args.command == 'install':
        install_args = sys.argv[2:] 
        autoinstall.install(install_args)
        return
        
    elif args.command == 'uninstall':
        uninstall_args = sys.argv[2:]
        autoinstall.uninstall(uninstall_args)
        return
        
    elif args.version:
        print(config["meta"]["version"])
        return
        
    elif args.info:
        try:
            info_data = asyncio.run(get_info())
            print(json.dumps(info_data, indent=2))
        except Exception as e:
            print(f"Error al obtener información: {e}", file=sys.stderr)
        return
        
    # --- MODO NATIVE MESSAGING (DEFAULT) ---
    
    try:
        rpc.set_logger(logger)
        rpc.set_debug_level(2)
        converter.start_listening()
        
        rpc.listen({
            "quit": lambda: sys.exit(0),
            "env": lambda: os.environ,
            "ping": lambda arg: arg,
            "info": get_info,
        })
        native_messaging.start_loop()
        
    except AttributeError:
        pass 
        

if __name__ == "__main__":
    main()