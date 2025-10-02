# vdhcoapp_py/autoinstall.py

import os
import sys
import json
import platform
import subprocess
import glob 
import stat
import re
# import path # Mantener la importación de 'path' para compatibilidad si estaba en el original.

# Importaciones de módulos del paquete
from . import rpc
from . import logger

# Importar el módulo principal para acceder a la configuración global si es necesario
# Nota: La implementación correcta en Python sería pasar la 'config' a install/uninstall.
# Para evitar un error de circularidad, lo manejaremos como una función de paquete:
try:
    from . import main # Intentamos importar main
    CONFIG = main.config # Accedemos a la variable cargada en main.py (si existe)
except Exception:
    # Fallback si main no se ha cargado o no expone 'config'
    CONFIG = None 
    logger.error("La configuración global no está disponible para autoinstall.py.")


# --- CONSTANTES ---
# Obtenemos las claves de las tiendas directamente de la configuración
if CONFIG:
    STORES = list(CONFIG['store'].keys())
else:
    STORES = []


# --- UTILERÍAS ---

def exec_p(cmd):
    """Ejecuta un comando de forma síncrona y lanza excepción en caso de error."""
    # Reemplaza exec_p de native-autoinstall.js
    result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
    return result

def display_message(body, title=None):
    """Muestra un mensaje al usuario (consola o notificación)."""
    # Reemplaza DisplayMessage de native-autoinstall.js
    if title:
        logger.info(f"{title} : {body}")
    else:
        logger.info(body)
        
    # Lógica de osascript para Mac (Replicación parcial)
    if platform.system() == "Darwin":
        try:
            # Usar la configuración de meta.name para el título de la notificación
            app_name = CONFIG['meta']['name'] if CONFIG else "App"
            subprocess.run(["/usr/bin/osascript", "-e", f'display notification "{body}" with title "{title or app_name}"'], check=False)
        except Exception:
            pass

def build_manifests():
    """Genera el contenido JSON de los manifiestos para cada tienda."""
    # Reemplaza BuildManifests de native-autoinstall.js
    if not CONFIG:
        raise Exception("Configuración no cargada.")
        
    manifest = {
        "name": CONFIG['meta']['id'],
        "description": CONFIG['meta']['description'],
        "path": sys.executable, # Usar la ruta del ejecutable actual
    }
    stores = {}
    for store in CONFIG['store']:
        stores[store] = {
            **CONFIG['store'][store]['manifest'],
            **manifest
        }
    return stores

def get_mode(args):
    """Determina si la instalación es 'user' o 'system'."""
    # Reemplaza GetMode de native-autoinstall.js
    
    # Se debe basar en el argumento 'args' pasado
    if "--user" in args:
        mode = "user"
    elif "--system" in args:
        mode = "system"
    elif os.getuid() == 0: 
        mode = "system"
    else:
        mode = "user"
        
    if mode == "system" and os.getuid() != 0:
        logger.error("No se puede instalar a nivel de sistema sin privilegios de root/administrador. Vuelva a ejecutar con sudo o con --user.")
        sys.exit(1)
        
    return mode

def expand_tilde(p):
    """Expande el tilde (~) a la ruta de inicio del usuario."""
    # Reemplaza expand_tilde de native-autoinstall.js
    if p.startswith("~"):
        return os.path.expanduser(p)
    return p

# --- INSTALACIÓN Y DESINSTALACIÓN LÓGICA ---

def setup_files(platform_name, mode, uninstall):
    """Escribe o elimina los archivos de manifiesto JSON."""
    if not CONFIG:
        raise Exception("Configuración no cargada, no se pueden configurar los archivos.")

    manifests = build_manifests()
    ops = []

    for store in STORES:
        paths_config = CONFIG['store'][store]['msg_manifest_paths'].get(platform_name, {})
        directories = paths_config.get(mode, [])
        
        for dir_entry in directories:
            dir_path = dir_entry
            only_if_dir_exists = None
            
            if isinstance(dir_entry, dict):
                dir_path = dir_entry['path']
                only_if_dir_exists = dir_entry['only_if_dir_exists']
            
            dir_path = expand_tilde(dir_path)

            if only_if_dir_exists:
                # Comprobar la existencia del directorio padre
                try:
                    os.stat(expand_tilde(only_if_dir_exists))
                except FileNotFoundError:
                    continue
            
            # Usar CONFIG['meta']['id'] para el nombre del archivo JSON
            manifest_path = os.path.join(dir_path, CONFIG['meta']['id'] + ".json")
            
            ops.append({
                "path": manifest_path,
                "content": json.dumps(manifests[store], indent=2)
            })

    for op in ops:
        if uninstall:
            # Desinstalación: Eliminar el archivo
            try:
                os.unlink(op['path'])
                logger.info(f"Eliminando archivo {op['path']}")
            except FileNotFoundError:
                pass 
            except Exception as e:
                logger.warn(f"No se pudo eliminar el manifiesto {op['path']}: {e}")
        else:
            # Instalación: Escribir el archivo
            try:
                logger.info(f"Escribiendo {op['path']}")
                dir_name = os.path.dirname(op['path'])
                
                os.makedirs(dir_name, exist_ok=True) 
                
                with open(op['path'], 'wb') as f:
                    f.write(op['content'].encode('utf-8'))
                    
            except Exception as e:
                # Falló la escritura
                display_message(f"No se pudo escribir el archivo de manifiesto: {str(e)}", op['path'])
                sys.exit(1)

    # Mensaje final de éxito
    if uninstall:
        text = f"{CONFIG['meta']['name']} se ha desregistrado correctamente."
    else:
        text = f"{CONFIG['meta']['name']} está listo para usarse."
    display_message(text, CONFIG['meta']['name'])

def prepare_flatpak():
    """Configura permisos de Flatpak para el navegador sandboxeado."""
    # Reemplaza PrepareFlatpak de native-autoinstall.js
    if not CONFIG:
        logger.error("Configuración no cargada, omitiendo Flatpak.")
        return

    try:
        exec_p("flatpak --version")
    except Exception:
        return 
        
    logger.info("Flatpak está instalado. Haciendo la coapp disponible desde los sandboxes del navegador:")
    install_dir = os.path.dirname(sys.executable)
    
    for id in CONFIG['flatpak']['ids']: 
        try:
            exec_p(f"flatpak override --user --filesystem={install_dir}:ro {id}")
            logger.info(f"Coapp vinculada dentro de {id}.")
        except Exception:
            pass 

def install_uninstall(uninstall=False, args=[]):
    """Función unificada de instalación/desinstalación."""
    if not CONFIG:
        logger.error("Error: La configuración no fue cargada. Abortando instalación/desinstalación.")
        sys.exit(1)
        
    platform_name = platform.system().lower()
    
    if platform_name == "darwin": # Mac
        mode = get_mode(args)
        setup_files("mac", mode, uninstall)
        
    elif platform_name == "linux": # Linux
        mode = get_mode(args)
        if mode == "user":
            prepare_flatpak() # Solo Flatpak en modo usuario
        setup_files("linux", mode, uninstall)

    elif platform_name == "windows":
        # La instalación de Windows se maneja fuera de este script (instalador NSIS)
        display_message(f"La instalación desde la línea de comandos no es la vía principal en Windows. Use el instalador .exe.")
    
    else:
        display_message(f"Instalación desde la línea de comandos no soportada en {platform.system()}")

# --- MÉTODOS DE EXPORTACIÓN (RPC) ---
# Estas funciones se exponen a la capa RPC y son llamadas por main.py

def install(args=[]):
    logger.info("Instalando...")
    install_uninstall(False, args)

def uninstall(args=[]):
    logger.info("Desinstalando...")
    install_uninstall(True, args)

# Registrar los métodos RPC para que puedan ser llamados por la extensión
rpc.listen({
    "autoinstall.install": install,
    "autoinstall.uninstall": uninstall
})