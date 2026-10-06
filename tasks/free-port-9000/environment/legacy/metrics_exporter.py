from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"legacy_metrics_up 1\n")

    def log_message(self, *args):
        pass


HTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
