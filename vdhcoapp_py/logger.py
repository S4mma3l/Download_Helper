# vdhcoapp_py/logger.py

import os
import logging
from logging.handlers import RotatingFileHandler

# Definir las funciones de log como no-op (no-operación) por defecto.
info = lambda *a, **kw: None
error = lambda *a, **kw: None
warn = lambda *a, **kw: None
log = lambda *a, **kw: None

# Obtener la ruta del archivo de log desde la variable de entorno.
log_file = os.environ.get("WEH_NATIVE_LOGFILE") # Similar a logfile en logger.js

if log_file:
    # Si la ruta está definida, configurar el logger real.
    
    # 1. Crear un logger de Python
    logger = logging.getLogger('VdhCoAppLogger')
    logger.setLevel(logging.INFO)

    # 2. Configurar el formato del log (opcionalmente simplificado)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # 3. Crear un manejador que escriba en el archivo de log (RotatingFileHandler es común)
    # El archivo será gestionado con rotación para evitar que crezca indefinidamente.
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=1024 * 1024 * 5, # 5MB
        backupCount=5
    )
    file_handler.setFormatter(formatter)
    
    # 4. Asignar el manejador al logger
    if not logger.handlers:
        logger.addHandler(file_handler)

    # 5. Sobrescribir las funciones no-op con los métodos reales del logger
    info = logger.info
    error = logger.error
    warn = logger.warning
    log = logger.info # Usamos info para el log general, como en simple-node-logger