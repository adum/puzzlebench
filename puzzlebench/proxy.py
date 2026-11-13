"""CONNECT-only inference gateway. Run in a separate container, never with secrets."""
from __future__ import annotations

import ipaddress
import os
import select
import socket
import socketserver
from http.server import BaseHTTPRequestHandler


def public_addresses(host: str, port: int) -> list[tuple]:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("Non-public destination")
    return addresses


def allowed_target(authority: str, allowed: set[str]) -> tuple[str, int]:
    host, separator, port = authority.rpartition(":")
    if not separator or port != "443" or host not in allowed:
        raise ValueError("Destination is not an allowed inference endpoint")
    return host, 443


class Proxy(BaseHTTPRequestHandler):
    timeout = 30

    def log_message(self, *_):
        pass  # Never log headers, URLs, credentials, or model requests.

    def do_CONNECT(self):
        upstream = None
        try:
            host, port = allowed_target(self.path, self.server.allowed)
            # Connect to the checked address, not to the hostname a second time.
            for family, kind, proto, _, address in public_addresses(host, port):
                try:
                    upstream = socket.socket(family, kind, proto)
                    upstream.settimeout(20)
                    upstream.connect(address)
                    break
                except OSError:
                    if upstream:
                        upstream.close()
                    upstream = None
            if upstream is None:
                raise OSError("Cannot connect to inference endpoint")
        except (ValueError, OSError):
            self.send_error(403, "Destination unavailable or denied")
            return
        self.send_response(200, "Connection established")
        self.end_headers()
        self.connection.settimeout(300)
        upstream.settimeout(300)
        try:
            while True:
                ready, _, _ = select.select([self.connection, upstream], [], [], 300)
                if not ready:
                    break
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)
        except OSError:
            pass
        finally:
            upstream.close()


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with Server(("0.0.0.0", 8080), Proxy) as server:
        server.allowed = set(os.environ["INFERENCE_HOSTS"].split(","))
        server.serve_forever()
