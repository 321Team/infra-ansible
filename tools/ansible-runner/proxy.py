"""Bounded CONNECT relay. A private Unix socket is the only inbound listener."""
import ipaddress
import os
import re
import select
import socket
import socketserver
import threading
import time

EXACT = frozenset({'github.com', 'api.github.com', 'codeload.github.com',
                  'objects.githubusercontent.com', 'objects-origin.githubusercontent.com',
                  'github-releases.githubusercontent.com', 'github-registry-files.githubusercontent.com',
                  'release-assets.githubusercontent.com', 'results-receiver.actions.githubusercontent.com',
                  'pypi.org', 'files.pythonhosted.org'})
SUFFIXES = ('.actions.githubusercontent.com', '.blob.core.windows.net')


def target(line):
    match = re.fullmatch(rb'CONNECT ([a-zA-Z0-9.-]{1,253}):443 HTTP/1\.[01]', line)
    if not match:
        raise ValueError('invalid CONNECT target')
    host = match[1].decode('ascii').lower()
    if host.endswith('.') or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', p) for p in host.split('.')):
        raise ValueError('invalid hostname')
    if host not in EXACT and not any(host.endswith(suffix) and len(host) > len(suffix) for suffix in SUFFIXES):
        raise ValueError('destination not allowed')
    return host


def addresses(host, resolver=socket.getaddrinfo):
    values = resolver(host, 443, type=socket.SOCK_STREAM)
    if not values:
        raise ValueError('no address')
    for family, kind, proto, _, address in values:
        ip = ipaddress.ip_address(address[0])
        if family not in (socket.AF_INET, socket.AF_INET6) or not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise ValueError('non-public DNS answer')
    return values


def relay(left, right, lifetime=3600):
    deadline = time.monotonic() + lifetime
    while time.monotonic() < deadline:
        ready, _, _ = select.select([left, right], [], [], 30)
        if not ready:
            continue
        for source in ready:
            data = source.recv(65536)
            if not data:
                return
            (right if source is left else left).sendall(data)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = None
        established = False
        try:
            self.request.settimeout(15)
            header = b''
            while b'\r\n\r\n' not in header:
                block = self.request.recv(min(4096, 16385 - len(header)))
                if not block or len(header) + len(block) > 16384:
                    raise ValueError('header bound')
                header += block
            first, tail = header.split(b'\r\n\r\n', 1)
            if tail:
                raise ValueError('unexpected pre-tunnel data')
            host = target(first.split(b'\r\n', 1)[0])
            candidates = addresses(host)
            for family, kind, proto, _, address in candidates:
                attempt = socket.socket(family, kind, proto)
                try:
                    attempt.settimeout(15)
                    attempt.connect(address)  # Reuse validated IP; never resolve again here.
                    upstream = attempt
                    break
                except OSError:
                    attempt.close()
            if upstream is None:
                raise OSError('connect failed')
            self.request.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
            established = True
            self.request.settimeout(30)
            upstream.settimeout(30)
            relay(self.request, upstream)
        except (ValueError, OSError):
            if not established:
                try:
                    self.request.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                except OSError:
                    pass
        finally:
            if upstream is not None:
                upstream.close()


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    request_queue_size = 16
    slots = threading.BoundedSemaphore(32)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def main():
    os.umask(0o077)
    path = '/proxy/connect.sock'
    if os.path.lexists(path):
        raise RuntimeError('Expected fresh socket directory')
    with Server(path, Handler) as server:
        os.chmod(path, 0o600)
        print('PROXY_READY', flush=True)
        server.serve_forever(poll_interval=0.2)


if __name__ == '__main__':
    main()
