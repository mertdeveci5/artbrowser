"""Ensure the shutdown test's network escape hatch stays restricted."""

import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from verification_proxy import VerificationProxy


class VerificationProxyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.report = Path(self.directory.name) / "events.jsonl"
        self.proxy = VerificationProxy(self.report)
        self.thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.proxy.stopping.set()
        self.proxy.shutdown()
        self.proxy.server_close()
        self.thread.join()
        self.directory.cleanup()

    def request(self, method, target):
        connection = http.client.HTTPConnection(*self.proxy.server_address, timeout=2)
        try:
            connection.request(method, target)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_only_fixture_is_available_over_plain_http(self):
        self.assertEqual(self.request("GET", "/state")[0], 200)
        self.assertEqual(self.request("GET", "http://example.com/private-path")[0], 410)

    def test_connect_rejects_other_hosts_and_ports_before_dns(self):
        connection = http.client.HTTPConnection(*self.proxy.server_address, timeout=2)
        connection.connect()
        try:
            with patch("verification_proxy.socket.getaddrinfo") as resolve:
                for target in ("arc.net:443", "www.iana.org:80", "www.iana.org.evil.invalid:443"):
                    connection.request("CONNECT", target)
                    response = connection.getresponse()
                    self.assertEqual(response.status, 410)
                    response.read()
                resolve.assert_not_called()
        finally:
            connection.close()

    def test_allowlisted_name_cannot_resolve_to_private_address(self):
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        # HTTPConnection also uses getaddrinfo, so establish the client first.
        connection = http.client.HTTPConnection(*self.proxy.server_address, timeout=2)
        connection.connect()
        try:
            with patch("verification_proxy.socket.getaddrinfo", return_value=addresses):
                connection.request("CONNECT", "www.iana.org:443")
                response = connection.getresponse()
                self.assertEqual(response.status, 410)
                response.read()
        finally:
            connection.close()

    def test_remote_blackhole_sends_no_synthetic_response(self):
        self.proxy.response_mode = "timeout"
        with socket.create_connection(self.proxy.server_address, timeout=2) as client:
            client.settimeout(.1)
            client.sendall(b"CONNECT arc.net:443 HTTP/1.1\r\nHost: arc.net:443\r\n\r\n")
            with self.assertRaises(socket.timeout):
                client.recv(1)
        events = [json.loads(line)["event"] for line in self.report.read_text().splitlines()]
        self.assertIn("remote_response_blackholed", events)


if __name__ == "__main__":
    unittest.main()
