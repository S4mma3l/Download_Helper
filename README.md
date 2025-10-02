# DownloadHelper CoApp (Python Port)

## 🐍 Visión General del Proyecto

Este proyecto es una recreación funcional y modular de la aplicación auxiliar (**Companion Application** o **CoApp**) utilizada por la extensión de navegador [Video DownloadHelper](https://downloadhelper.net/). El código original basado en Node.js ha sido **importado íntegramente a Python** para ofrecer una solución multiplataforma y extensible para tareas que requieren acceso de bajo nivel al sistema, como:

1.  **Conversión de Video:** Utilizando el binario FFmpeg para manipular y transformar *streams* de video.
2.  **Descargas Autónomas:** Ejecución de descargas de archivos grandes (incluyendo contenido autenticado con cookies) desde la línea de comandos (CLI).
3.  **Comunicación con el Navegador:** Implementación del protocolo Native Messaging (RPC) para comunicarse con la extensión.
4.  **Gestión de Archivos:** Operaciones seguras de E/S y manejo de archivos temporales.

---

## 🚀 Uso Autónomo (CLI)

La CoApp puede ser utilizada como una herramienta de línea de comandos independiente para iniciar descargas de contenido restringido, ya que gestiona la autenticación a través de variables de entorno seguras.

### 1. Requerimientos

* **Python:** Versión 3.11+ (requerida por el módulo `tomllib`).
* **FFmpeg y FFprobe:** Los binarios deben estar instalados y accesibles en su variable de entorno `PATH`.
* **Librerías de Python:**
    ```bash
    pip install python-dotenv requests toml
    ```

### 2. Configuración de Autenticación (`.env`)

Para descargar contenido de sitios protegidos (ej., cursos de Alura), debe proporcionar las credenciales de sesión.

Cree un archivo llamado **`.env`** en la raíz del proyecto (junto a `vdhcoapp_py/`) y defina su token de sesión (`Cookie`) y un agente de usuario:

```env
# Archivo: .env

# IDENTIFICADOR CRUCIAL: Obtenga este valor completo del encabezado 'Cookie' de su navegador.
# Ejemplo: JSESSIONID=MzY5YmJjZDctMDQ3Yy00OGZmLTllZGEtY453MzZmYTdmNzAw
USER_SESSION_COOKIE="[PEGUE AQUÍ SU CLAVE DE SESIÓN COMPLETA]"

# Encabezado Referer (Obligatorio para la mayoría de CDNs)
# Debe ser la URL de la página donde se reproduce el video.
DOWNLOAD_REFERER="[PEGUE AQUÍ LA URL COMPLETA DE LA PÁGINA DEL CURSO]"

# User Agent para simular un navegador real
USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
```

# Ejecutar desde el directorio Download_Helper
python -m vdhcoapp_py.main download "[URL_DIRECTA_DEL_VIDEO]" "C:\Ruta\de\Descarga"


🛠️ Comandos de Mantenimiento

La aplicación mantiene los comandos CLI originales para el mantenimiento del sistema y el diagnóstico.
Comando	Descripción
python -m vdhcoapp_py.main --info	Muestra la versión de la CoApp y verifica la ruta/versión de FFmpeg y FFprobe.
python -m vdhcoapp_py.main --version	Muestra la versión de la CoApp (2.0.19).
python -m vdhcoapp_py.main install	Crea las claves de registro de Native Messaging para que los navegadores detecten la CoApp (necesario para usar la extensión).
python -m vdhcoapp_py.main uninstall	Elimina las claves de registro y los archivos de manifiesto.

💻 Arquitectura y Estructura

El proyecto está organizado como un paquete modular de Python para replicar la estructura limpia de Node.js.
Módulo	Función Principal	Origen (JS)
main.py	Punto de entrada, manejador de CLI y orquestador RPC.	main.js
converter.py	Interfaz principal para FFmpeg y FFprobe; maneja la conversión y sondeo.	converter.js
downloads.py	Gestiona el inicio y el monitoreo de las descargas HTTP/S (cliente requests).	downloads.js
request_ops.py	Maneja solicitudes HTTP/S fragmentadas (binario/texto) para el stream de datos.	request.js
autoinstall.py	Lógica para la creación de manifiestos y la escritura en el registro/archivos del sistema.	native-autoinstall.js
native_messaging.py	Implementación del protocolo de comunicación Native Messaging (E/S binaria).	native-messaging.js
weh-rpc.py	Protocolo RPC (Remote Procedure Call) para gestionar llamadas asíncronas entre procesos.	weh-rpc.js
config.toml	Archivo de metadatos y configuración de rutas.	config.toml