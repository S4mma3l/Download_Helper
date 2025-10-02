# vdhcoapp_py/vm.py

# En Python, para ejecutar código en un "sandbox", simplemente se usa la función nativa 'eval' o 'exec'.
# No existe un módulo directo como 'vm' de Node.js que cree un contexto nuevo de forma sencilla
# y que funcione en el mismo modelo de seguridad. Usaremos 'eval' para simular la ejecución.

from . import rpc

def rpc_vm_run(code):
    """
    Ejecuta código de Python en un entorno de sandbox limitado.
    Reemplaza vm.run de vm.js
    """
    # Usar dict vacío como sandbox para simular newContext de JS.
    # ADVERTENCIA: 'eval' en Python no es seguro y no es un sandbox verdadero.
    # Esta es una recreación *funcional*, no de seguridad.
    sandbox = {}
    
    try:
        # Ejecutar el código. Si la extensión envía "var x = 2; x + 40", esto fallaría en Python.
        # Asumimos que el código enviado por la extensión es un código Python válido para esta recreación.
        # Si la extensión aún envía JS, esto fallará.
        result = eval(code, {"__builtins__": None}, sandbox)
        return result
    except Exception as e:
        raise Exception(f"Error en la ejecución de código (Python): {e}")

rpc.listen({
    "vm.run": rpc_vm_run,
})