"""Lanzador: servidor HTTP local + abre el navegador.

Con `--live` arranca también el backend de seguimiento en vivo (live_tracker) en
:8770, para que las páginas /partido tengan su API en desarrollo. En producción
ese servicio corre por systemd y Caddy proxya /api/*.
"""
import http.server, threading, webbrowser, socket, os, sys, subprocess

PORT = 8765

# Backend de live tracking en dev (opt-in para no machacar la API de ESPN al desarrollar).
if '--live' in sys.argv:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print('Arrancando live_tracker en :8770 …')
    subprocess.Popen([sys.executable, '-m', 'live_tracker'], cwd=repo)

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args): pass  # silencia el log

def find_free_port():
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]

# Sirve la raíz del repo (carpeta padre de scripts/), no scripts/.
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
port = PORT
try:
    server = http.server.HTTPServer(('localhost', port), Handler)
except OSError:
    port = find_free_port()
    server = http.server.HTTPServer(('localhost', port), Handler)

url = f'http://localhost:{port}/index.html'
print(f'Servidor corriendo en {url}')
print('Ctrl+C para detener.')

threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
server.serve_forever()
