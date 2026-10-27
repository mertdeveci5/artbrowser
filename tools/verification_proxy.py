"""Loopback-only HTTPS tunnel and state fixture for isolated shutdown tests.

Only explicitly named public test sites can be reached. Browser credentials,
request headers, URLs and response bodies are never logged or inspected.
"""

import http.server
import ipaddress
import json
from pathlib import Path
import select
import socket
import threading
import sys
from urllib.parse import urlsplit

ALLOWED = {"example.com", "www.iana.org", "iana.org", "example.org"}


class VerificationProxy(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, report: Path, port=0):
        self.report = report
        self.report_lock = threading.Lock()
        self.response_mode = "gone"
        self.stopping = threading.Event()
        super().__init__(("127.0.0.1", port), Handler)

    def record(self, **item):
        with self.report_lock, self.report.open("a") as file:
            file.write(json.dumps(item) + "\n")

    def handle_error(self, request, client_address):
        self.record(event="proxy_connection_closed", error=type(sys.exc_info()[1]).__name__)


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def reject(self, reason):
        self.server.record(event="proxy_denied", reason=reason)
        if self.server.response_mode == "timeout":
            self.server.record(event="remote_response_blackholed")
            self.server.stopping.wait(65)
            self.close_connection=True
            return
        body = b"This destination is unavailable during the shutdown verification."
        self.send_response(410)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_CONNECT(self):
        try:
            host, port = self.path.rsplit(":", 1)
            port = int(port)
            if host.lower() not in ALLOWED or port != 443:
                return self.reject("destination_not_allowlisted")
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                return self.reject("non_public_address")
            remote = socket.create_connection(addresses[0][4][:2], timeout=10)
        except (OSError, ValueError):
            return self.reject("connection_failed")
        self.send_response(200, "Connection Established")
        self.end_headers()
        self.server.record(event="https_tunnel_opened", host=host.lower())
        try:
            sockets = [self.connection, remote]
            while True:
                readable, _, _ = select.select(sockets, [], [], 15)
                if not readable:
                    break
                for source in readable:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    (remote if source is self.connection else self.connection).sendall(chunk)
        except OSError:
            pass
        finally:
            remote.close()
            self.close_connection = True

    def do_GET(self):
        parsed = urlsplit(self.path)
        # Absolute URLs are proxy requests; no public plaintext proxying is needed.
        if parsed.hostname:
            return self.reject("plaintext_proxy_not_allowed")
        if parsed.path == "/echo-cookie":
            present = "artbrowser_qa_cookie=present" in self.headers.get("Cookie", "")
            body = json.dumps({"fixture_cookie_restored": present}).encode()
            content_type = "application/json"
        else:
            body = b'''<!doctype html><title>ArtBrowser shutdown verification</title>
<h1>Shutdown verification page loaded</h1><p id="storage"></p><p id="cookie"></p>
<script>
const old=localStorage.getItem('artbrowser_qa_marker');
document.querySelector('#storage').textContent=old==='retained'?'Local storage restored':'Local storage initialized';
localStorage.setItem('artbrowser_qa_marker','retained');
fetch('/echo-cookie').then(r=>r.json()).then(r=>{document.querySelector('#cookie').textContent=r.fixture_cookie_restored?'Fixture cookie restored':'Fixture cookie initialized';document.cookie='artbrowser_qa_cookie=present;path=/;max-age=31536000;SameSite=Lax';});
</script>'''
            content_type = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.server.record(event="local_fixture_requested", kind="cookie" if parsed.path == "/echo-cookie" else "page")
