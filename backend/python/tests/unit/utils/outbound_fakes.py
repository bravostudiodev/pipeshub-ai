"""A loopback TCP server that records the request line it is sent.

Used both as a fake forward proxy (the request line then shows what the client asked the
proxy to fetch: an absolute URL, or ``CONNECT host:port``) and as a fake in-cluster service.
"""

import socket
import threading


class FakeServer:
    def __init__(
        self,
        body: bytes = b"ok",
        content_type: str = "text/plain",
        status: int = 200,
        connect_status: int = 502,
    ) -> None:
        self.request_lines: list[str] = []
        self.raw_requests: list[bytes] = []
        self._body = body
        self._content_type = content_type
        self._status = status
        self._connect_status = connect_status
        self.headers: dict[str, str] = {}
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port: int = self._sock.getsockname()[1]
        self._stopped = False
        threading.Thread(target=self._serve, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _serve(self) -> None:
        while not self._stopped:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(5)
            data = b""
            try:
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            except OSError:
                return
            if not data:
                return
            head_part, _, rest = data.partition(b"\r\n\r\n")
            for line in head_part.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    wanted = int(line.split(b":", 1)[1])
                    try:
                        while len(rest) < wanted:
                            chunk = conn.recv(65536)
                            if not chunk:
                                break
                            rest += chunk
                    except OSError:
                        pass
                    data = head_part + b"\r\n\r\n" + rest
            self.raw_requests.append(data)
            first = data.split(b"\r\n", 1)[0].decode("latin-1")
            self.request_lines.append(first)
            status = self._connect_status if first.startswith("CONNECT ") else self._status
            body = b"" if first.startswith("CONNECT ") else self._body
            extra = "".join(f"{k}: {v}\r\n" for k, v in self.headers.items())
            head = (
                f"HTTP/1.1 {status} X\r\nContent-Type: {self._content_type}\r\n{extra}"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
            ).encode()
            try:
                conn.sendall(head + body)
            except OSError:
                return

    def respond_with(self, status: int, **headers: str) -> None:
        self._status = status
        self.headers = dict(headers)

    def close(self) -> None:
        self._stopped = True
        self._sock.close()
