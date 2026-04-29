"""Lanzador: servidor HTTP local + abre el navegador."""
import http.server, threading, webbrowser, socket, os

PORT = 8765

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args): pass  # silencia el log

def find_free_port():
    with socket.socket() as s:
        s.bind(('', 0))
        return s.getsockname()[1]

os.chdir(os.path.dirname(os.path.abspath(__file__)))
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
