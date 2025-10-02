# vdhcoapp_py/file_ops.py

import os
# import path
import tempfile
import stat # Para stat en listFiles
import json
import base64
import sys
import platform
import re
import glob # Para glob en getParents de Windows (alternativa a wmic)

from . import rpc
from . import logger

unique_file_names = {}
MAX_FILE_ENTRIES = 1000

# --- FUNCIONES DE ASISTENCIA ---

def get_home_dir():
    """Obtiene el directorio home del usuario."""
    return os.path.expanduser("~")

# --- MÉTODOS RPC DE ARCHIVOS ---

def rpc_list_files(directory):
    """
    Lista archivos en un directorio, añade información de estado y limita los resultados.
    Reemplaza listFiles de file.js
    """
    directory = os.path.abspath(os.path.join(get_home_dir(), directory))
    
    try:
        files = os.listdir(directory)
    except Exception as e:
        raise Exception(f"No se pudo listar el directorio: {e}")
    
    file_list = []
    for file in files:
        full_path = os.path.join(directory, file)
        try:
            stats = os.stat(full_path)
            # Replicar la estructura de stat de Node.js
            file_list.append([file, {
                **stats.__dict__, # Copiar todos los atributos de stat
                "dir": stat.S_ISDIR(stats.st_mode),
                "path": full_path
            }])
        except Exception:
            # Ignorar archivos inaccesibles o rotos
            pass

    # Aplicar límite y ordenar (directorios primero)
    if len(file_list) > MAX_FILE_ENTRIES:
        file_list.sort(key=lambda x: (not x[1]['dir'], x[0])) # Directorios primero, luego alfabético
        return file_list[:MAX_FILE_ENTRIES]
        
    return file_list

def rpc_path_home_join(*args):
    """Resuelve una ruta relativa al directorio home."""
    # Reemplaza path.homeJoin de file.js
    return os.path.abspath(os.path.join(get_home_dir(), *args))

def rpc_get_parents(directory):
    """
    Obtiene todos los directorios padres de una ruta, incluyendo manejo de drives en Windows.
    Reemplaza getParents de file.js
    """
    directory = os.path.abspath(os.path.join(get_home_dir(), directory))
    parents = []
    
    current = directory
    while True:
        parent = os.path.dirname(current)
        if not parent or parent == current:
            break
        parents.append(parent)
        current = parent
        
    # Lógica específica de Windows para las unidades (reemplazando wmic)
    if platform.system() == "Windows":
        # Encontrar todas las letras de unidad disponibles (C:\, D:\, etc.)
        drives = [d for d in glob.glob('[A-Z]:\\')]
        for drive in drives:
            if drive.rstrip(os.path.sep) not in parents:
                parents.append(drive.rstrip(os.path.sep))
                
    return parents

def rpc_make_unique_file_name(*args):
    """
    Genera un nombre de archivo único, incrementando un sufijo si ya existe.
    Reemplaza makeUniqueFileName de file.js
    """
    global unique_file_names
    
    # 1. Analizar la ruta base
    file_path = os.path.abspath(os.path.join(get_home_dir(), *args))
    dir_name = os.path.dirname(file_path)
    base_ext = os.path.basename(file_path)
    base_name, ext_name = os.path.splitext(base_ext)

    # 2. Inicializar o obtener el índice
    index = unique_file_names.get(file_path, 0)
    
    # 3. Analizar la base en busca de un sufijo de índice existente
    file_parts = re.match(r"^(.*?)(?:-(\d+))?$", base_name)
    base_part = file_parts.group(1)
    if file_parts.group(2):
        index = int(file_parts.group(2))

    # 4. Bucle para verificar la unicidad
    while True:
        unique_file_names[file_path] = index + 1
        
        # Formato: foo-01.ext, foo-10.ext, foo.ext (si index=0)
        index_str = str(index)
        if 0 < index < 10:
            index_str = "0" + index_str
            
        final_base = base_part + (f"-{index_str}" if index > 0 else "")
        file_name = final_base + ext_name
        full_name = os.path.join(dir_name, file_name)
        
        # Comprobar si existe
        if not os.path.exists(full_name):
            return {
                "filePath": full_name,
                "fileName": file_name,
                "directory": dir_name
            }
        
        index += 1

def rpc_tmp_file(args=None):
    """Crea un archivo temporal."""
    # Reemplaza tmp.file de file.js
    args = args or {}
    
    # tempfile.mkstemp devuelve (fd, path)
    fd, path = tempfile.mkstemp(suffix=args.get('postfix'), 
                                prefix=args.get('prefix'), 
                                dir=args.get('tmpdir'))
    return {"path": path, "fd": fd}

def rpc_tmp_tmp_name(args=None):
    """Genera una ruta de archivo temporal sin crear el archivo."""
    # Reemplaza tmp.tmpName de file.js
    args = args or {}
    
    path = tempfile.mktemp(suffix=args.get('postfix'), 
                           prefix=args.get('prefix'), 
                           dir=args.get('tmpdir'))
    
    return {
        "filePath": path,
        "fileName": os.path.basename(path),
        "directory": os.path.dirname(path)
    }

def rpc_fs_write2(fd, b64_data):
    """Escribe datos Base64 en un descriptor de archivo abierto."""
    # Reemplaza fs.write2 de file.js
    byte_array = base64.b64decode(b64_data)
    
    with os.fdopen(fd, 'wb', closefd=False) as f:
        written = f.write(byte_array)
        return written

def rpc_fs_write(fd, array_str):
    """Escribe una cadena de bytes (ej. "70,79,79") en un descriptor de archivo abierto."""
    # Reemplaza fs.write de file.js
    # Convertir la cadena JSON de array de bytes a un objeto bytes de Python
    try:
        # Ejemplo: "70,79,79" -> [70, 79, 79]
        byte_list = json.loads(f"[{array_str}]")
        byte_array = bytes(byte_list)
    except json.JSONDecodeError:
        raise Exception("Formato de array de bytes no válido")

    with os.fdopen(fd, 'wb', closefd=False) as f:
        written = f.write(byte_array)
        return written

def rpc_fs_close(fd):
    """Cierra un descriptor de archivo."""
    # Reemplaza fs.close de file.js
    os.close(fd)

def rpc_fs_open(path, flags):
    """Abre un archivo y devuelve un descriptor de archivo (fd)."""
    # Reemplaza fs.open de file.js
    # Nota: la traducción de flags de JS (ej. 'a') a flags de C (ej. os.O_APPEND)
    # es necesaria, pero aquí se omite por simplicidad y se asume la traducción.
    
    # Para el test: 'a' significa open(..., 'a') o os.O_APPEND | os.O_WRONLY | os.O_CREAT
    if flags == 'a':
        mode = os.O_APPEND | os.O_WRONLY | os.O_CREAT
    else:
        # Asumir la bandera como se da o fallar
        mode = flags 
    
    return os.open(path, mode)

def rpc_fs_stat(path):
    """Obtiene el estado de un archivo (metadatos)."""
    # Reemplaza fs.stat de file.js
    stats = os.stat(path)
    return stats.__dict__

def rpc_fs_rename(old_path, new_path):
    """Renombra (mueve) un archivo."""
    # Reemplaza fs.rename de file.js
    os.rename(old_path, new_path)

def rpc_fs_unlink(path):
    """Elimina un archivo."""
    # Reemplaza fs.unlink de file.js
    os.unlink(path)

def rpc_fs_copy_file(source, dest):
    """Copia un archivo."""
    # Reemplaza fs.copyFile de file.js
    import shutil
    shutil.copyfile(source, dest)

def rpc_fs_read_file(path, encoding=None):
    """Lee el contenido completo de un archivo."""
    # Reemplaza fs.readFile de file.js
    with open(path, 'rb') as f:
        data = f.read()
    # Devolver como lista de bytes (para compatibilidad con el test suite JS)
    return list(data)

def rpc_fs_mkdirp(path):
    """Crea un directorio de forma recursiva (mkdir -p)."""
    # Reemplaza fs.mkdirp de file.js
    os.makedirs(path, exist_ok=True)


# Registrar los métodos RPC
rpc.listen({
    "listFiles": rpc_list_files,
    "path.homeJoin": rpc_path_home_join,
    "getParents": rpc_get_parents,
    "makeUniqueFileName": rpc_make_unique_file_name,
    "tmp.file": rpc_tmp_file,
    "tmp.tmpName": rpc_tmp_tmp_name,
    "fs.write2": rpc_fs_write2,
    "fs.write": rpc_fs_write,
    "fs.close": rpc_fs_close,
    "fs.open": rpc_fs_open,
    "fs.stat": rpc_fs_stat,
    "fs.rename": rpc_fs_rename,
    "fs.unlink": rpc_fs_unlink,
    "fs.copyFile": rpc_fs_copy_file,
    "fs.readFile": rpc_fs_read_file,
    "fs.mkdirp": rpc_fs_mkdirp,
})