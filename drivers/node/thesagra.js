const net = require("net");

const MAGIC = Buffer.from("TSGP");
const VERSION = 1;
const REQUEST = 1;
const RESPONSE = 2;
const CANCEL = 3;

class ThesagraError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ThesagraError";
    this.code = code;
  }
}

class ThesagraConnection {
  constructor({ host = "127.0.0.1", port = 5439, timeout = 10000 } = {}) {
    this.host = host;
    this.port = port;
    this.timeout = timeout;
    this.socket = null;
    this.buffer = Buffer.alloc(0);
    this.pending = [];
  }

  connect(username, password) {
    return new Promise((resolve, reject) => {
      this.socket = net.createConnection({
        host: this.host,
        port: this.port,
      });
      this.socket.setTimeout(this.timeout);
      this.socket.once("error", reject);
      this.socket.once("timeout", () => reject(new ThesagraError("TIMEOUT", "Connection timed out")));
      this.socket.once("connect", () => {
        this.socket.on("data", (chunk) => this._readFrames(chunk));
        this._send(REQUEST, {
          operation: "handshake",
          request_id: "handshake",
          username,
          password,
        }).then((response) => {
          if (!response.ok) {
            reject(new ThesagraError(response.error.code, response.error.message));
          } else {
            this.sessionId = response.session_id;
            resolve(this);
          }
        }).catch(reject);
      });
    });
  }

  _readFrames(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (this.buffer.length >= 10) {
      const magic = this.buffer.subarray(0, 4);
      if (!magic.equals(MAGIC)) {
        this.pending.forEach((pending) => pending.reject(
          new ThesagraError("PROTOCOL_ERROR", "Invalid protocol magic"),
        ));
        this.pending = [];
        return;
      }
      if (this.buffer[4] !== VERSION) {
        this.pending.forEach((pending) => pending.reject(
          new ThesagraError("PROTOCOL_ERROR", "Unsupported protocol version"),
        ));
        this.pending = [];
        return;
      }
      const length = this.buffer.readUInt32BE(6);
      if (this.buffer.length < 10 + length) return;
      const payload = JSON.parse(
        this.buffer.subarray(10, 10 + length).toString("utf8"),
      );
      this.buffer = this.buffer.subarray(10 + length);
      const pending = this.pending.shift();
      if (pending) pending.resolve(payload);
    }
  }

  _send(messageType, payload) {
    return new Promise((resolve, reject) => {
      if (!this.socket) {
        reject(new ThesagraError("CONNECTION_ERROR", "Not connected"));
        return;
      }
      const json = Buffer.from(JSON.stringify(payload), "utf8");
      const header = Buffer.alloc(10);
      MAGIC.copy(header, 0);
      header[4] = VERSION;
      header[5] = messageType;
      header.writeUInt32BE(json.length, 6);
      this.pending.push({ resolve, reject });
      this.socket.write(Buffer.concat([header, json]));
    });
  }

  query(sql, parameters = []) {
    if (!this.sessionId) {
      return Promise.reject(
        new ThesagraError("NOT_AUTHENTICATED", "Handshake required"),
      );
    }
    const requestId = `${Date.now()}-${Math.random()}`;
    return this._send(REQUEST, {
      operation: "query",
      request_id: requestId,
      session_id: this.sessionId,
      sql,
      parameters,
    }).then((response) => {
      if (!response.ok) {
        throw new ThesagraError(
          response.error.code,
          response.error.message,
        );
      }
      return {
        columns: response.columns,
        rows: response.rows,
        rowcount: response.rowcount,
      };
    });
  }

  cancel(requestId) {
    return this._send(CANCEL, { request_id: requestId });
  }

  close() {
    if (this.socket) this.socket.end();
  }
}

module.exports = {
  ThesagraConnection,
  ThesagraError,
};
