"""Lanzador: servidor HTTP local + abre el navegador.

Con `--live` arranca también el backend de seguimiento en vivo (live_tracker) en
:8770, para que las páginas /partido tengan su API en desarrollo. En producción
ese servicio corre por systemd y Caddy proxya /api/*.

Con `--accounts` arranca el backend de cuentas (accounts) en :8771, con la feature
encendida y la cookie de sesión en modo NO-Secure (para poder probar el login por
http en local). En producción corre por systemd (flag off en CP0).
"""
import http.server, threading, webbrowser, socket, os, sys, subprocess

PORT = 8765

# Backend de live tracking en dev (opt-in para no machacar la API de ESPN al desarrollar).
if '--live' in sys.argv:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print('Arrancando live_tracker en :8770 …')
    subprocess.Popen([sys.executable, '-m', 'live_tracker'], cwd=repo)

# Backend de cuentas en dev (opt-in). Feature encendida y cookie NO-Secure para
# poder probar el login por http en local; en producción corre por systemd.
if '--accounts' in sys.argv:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print('Arrancando accounts en :8771 …')
    env = {**os.environ, 'ACCOUNTS_ENABLED': 'true', 'ACCOUNTS_COOKIE_SECURE': 'false'}
    subprocess.Popen([sys.executable, '-m', 'accounts'], cwd=repo, env=env)

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # Reescribe /equipo/<view> → /equipo.html (espejo del `rewrite` de Caddy en
        # producción, ver CLAUDE.md → URLs limpias) para poder probar las sub-vistas
        # /equipo/news · /equipo/stats · /equipo/matches · /equipo/players en local.
        path, _, query = self.path.partition('?')
        if path.startswith('/equipo/') and not path.startswith('/equipos/'):
            seg = path.rstrip('/').rsplit('/', 1)[-1]
            if seg in ('news', 'stats', 'matches', 'players'):
                self.path = '/equipo.html' + ('?' + query if query else '')
        super().do_GET()

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
