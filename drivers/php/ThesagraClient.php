<?php

class ThesagraError extends Exception
{
    public string $code;

    public function __construct(string $code, string $message)
    {
        parent::__construct($message);
        $this->code = $code;
    }
}

class ThesagraClient
{
    private const MAGIC = "TSGP";
    private const VERSION = 1;
    private const REQUEST = 1;
    private const CANCEL = 3;

    private $socket;
    private ?string $sessionId = null;

    public function __construct(
        private string $host = "127.0.0.1",
        private int $port = 5439,
        private float $timeout = 10.0
    ) {
    }

    public function connect(string $username, string $password): array
    {
        $socket = @fsockopen(
            $this->host,
            $this->port,
            $errorNumber,
            $errorMessage,
            $this->timeout
        );
        if (!$socket) {
            throw new ThesagraError(
                "CONNECTION_ERROR",
                $errorMessage ?: "Connection failed"
            );
        }
        stream_set_timeout(
            $socket,
            (int) $this->timeout,
            (int) (($this->timeout - (int) $this->timeout) * 1000000)
        );
        $this->socket = $socket;
        $response = $this->send(self::REQUEST, [
            "operation" => "handshake",
            "request_id" => "handshake",
            "username" => $username,
            "password" => $password,
        ]);
        if (!($response["ok"] ?? false)) {
            $error = $response["error"] ?? [];
            throw new ThesagraError(
                $error["code"] ?? "AUTH_FAILED",
                $error["message"] ?? "Authentication failed"
            );
        }
        $this->sessionId = $response["session_id"];
        return $response;
    }

    public function query(string $sql, array $parameters = []): array
    {
        if ($this->sessionId === null) {
            throw new ThesagraError(
                "NOT_AUTHENTICATED",
                "Handshake required"
            );
        }
        $response = $this->send(self::REQUEST, [
            "operation" => "query",
            "request_id" => bin2hex(random_bytes(16)),
            "session_id" => $this->sessionId,
            "sql" => $sql,
            "parameters" => $parameters,
        ]);
        if (!($response["ok"] ?? false)) {
            $error = $response["error"] ?? [];
            throw new ThesagraError(
                $error["code"] ?? "QUERY_ERROR",
                $error["message"] ?? "Query failed"
            );
        }
        return [
            "columns" => $response["columns"] ?? [],
            "rows" => $response["rows"] ?? [],
            "rowcount" => $response["rowcount"] ?? 0,
        ];
    }

    public function close(): void
    {
        if (is_resource($this->socket)) {
            fclose($this->socket);
        }
        $this->socket = null;
        $this->sessionId = null;
    }

    private function send(int $messageType, array $payload): array
    {
        if (!is_resource($this->socket)) {
            throw new ThesagraError(
                "CONNECTION_ERROR",
                "Not connected"
            );
        }
        $json = json_encode(
            $payload,
            JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
        );
        $header = self::MAGIC
            . chr(self::VERSION)
            . chr($messageType)
            . pack("N", strlen($json));
        if (fwrite($this->socket, $header . $json) === false) {
            throw new ThesagraError(
                "CONNECTION_ERROR",
                "Failed to write request"
            );
        }
        $header = fread($this->socket, 10);
        if ($header === false || strlen($header) !== 10) {
            throw new ThesagraError(
                "CONNECTION_ERROR",
                "Connection closed during response"
            );
        }
        $magic = substr($header, 0, 4);
        $version = ord($header[4]);
        if ($magic !== self::MAGIC || $version !== self::VERSION) {
            throw new ThesagraError(
                "PROTOCOL_ERROR",
                "Invalid protocol frame"
            );
        }
        $lengthData = substr($header, 6, 4);
        $lengthValues = unpack("Nlength", $lengthData);
        $length = $lengthValues["length"];
        $body = "";
        while (strlen($body) < $length) {
            $chunk = fread(
                $this->socket,
                $length - strlen($body)
            );
            if ($chunk === false || $chunk === "") {
                throw new ThesagraError(
                    "CONNECTION_ERROR",
                    "Truncated response"
                );
            }
            $body .= $chunk;
        }
        $decoded = json_decode($body, true);
        if (!is_array($decoded)) {
            throw new ThesagraError(
                "PROTOCOL_ERROR",
                "Invalid JSON response"
            );
        }
        return $decoded;
    }
}
