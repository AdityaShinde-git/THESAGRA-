import socket
import uuid
import ssl
import threading

from .protocol import (
    CANCEL,
    REQUEST,
    receive_message,
    send_message,
)


class THESAGRAClient:
    def __init__(self, host="127.0.0.1", port=5439, timeout=10,
                 tls=False, tls_ca=None):
        self.host = host
        self.port = port
        self.socket = socket.create_connection((host, port), timeout=timeout)
        if tls:
            context = ssl.create_default_context(
                cafile=tls_ca,
            )
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.socket = context.wrap_socket(
                self.socket,
                server_hostname=host,
            )
        self.socket.settimeout(timeout)
        self.stream = self.socket
        self.session_id = None
        self._request_lock = threading.RLock()

    def handshake(self, username, password, database=None):
        with self._request_lock:
            request_id = str(uuid.uuid4())
            send_message(
                self.stream,
                REQUEST,
                {
                    "operation": "handshake",
                    "request_id": request_id,
                    "username": username,
                    "password": password,
                    "database": database,
                },
            )
            _, response = receive_message(self.stream)
        if not response.get("ok"):
            raise RuntimeError(response["error"]["message"])
        self.session_id = response["session_id"]
        return response

    def query(self, sql, parameters=None):
        with self._request_lock:
            request_id = str(uuid.uuid4())
            send_message(
                self.stream,
                REQUEST,
                {
                    "operation": "query",
                    "request_id": request_id,
                    "session_id": self.session_id,
                    "sql": sql,
                    "parameters": parameters or [],
                },
            )
            _, response = receive_message(self.stream)
        if not response.get("ok"):
            raise RuntimeError(
                f"{response['error']['code']}: {response['error']['message']}"
            )
        return response

    def cancel(self, request_id):
        send_message(
            self.stream,
            CANCEL,
            {"request_id": request_id},
        )
        _, response = receive_message(self.stream)
        return response

    def operation(self, operation, **payload):
        with self._request_lock:
            request_id = str(uuid.uuid4())
            payload = {
                "operation": operation,
                "request_id": request_id,
                "session_id": self.session_id,
                **payload,
            }
            send_message(self.stream, REQUEST, payload)
            _, response = receive_message(self.stream)
        if not response.get("ok"):
            error = response.get("error", {})
            raise RuntimeError(
                f"{error.get('code', 'ERROR')}: "
                f"{error.get('message', 'Operation failed')}"
            )
        return response

    def close(self):
        with self._request_lock:
            if self.session_id:
                try:
                    send_message(
                        self.stream,
                        REQUEST,
                        {
                            "operation": "disconnect",
                            "request_id": str(uuid.uuid4()),
                            "session_id": self.session_id,
                        },
                    )
                    receive_message(self.stream)
                except (OSError, ConnectionError):
                    pass
            self.stream.close()
            self.socket.close()
