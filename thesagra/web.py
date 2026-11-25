import json
import os
import threading
import base64
import hmac
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .query.engine import QueryError, RelationalEngine
from .query.parser import ParseError, parse
from .storage.database import DatabaseFile
from .security import AuditLog, FailureThrottle, verify_password


class THESAGRAWebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        database_path,
        host="127.0.0.1",
        port=8080,
        username=None,
        password=None,
        password_hash=None,
        tls_cert=None,
        tls_key=None,
    ):
        self.database_path = os.fspath(database_path)
        exists = os.path.isfile(self.database_path)
        database = (
            DatabaseFile.open(self.database_path)
            if exists
            else DatabaseFile.create(self.database_path)
        )
        self.engine = RelationalEngine(database)
        self.engine_lock = threading.Lock()
        self.username = username or os.environ.get(
            "THESAGRA_USERNAME",
            "admin",
        )
        self.password = password or os.environ.get(
            "THESAGRA_PASSWORD",
            "change-me",
        )
        self.password_hash = password_hash or os.environ.get(
            "THESAGRA_PASSWORD_HASH"
        )
        self.failure_throttle = FailureThrottle()
        self.audit = AuditLog(self.database_path)
        self.tls_context = None
        if tls_cert or tls_key:
            if not tls_cert or not tls_key:
                raise ValueError("Both TLS certificate and key are required")
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(tls_cert, tls_key)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.tls_context = context
        super().__init__((host, port), THESAGRAWebHandler)

    def get_request(self):
        socket, address = super().get_request()
        if self.tls_context is not None:
            try:
                socket = self.tls_context.wrap_socket(
                    socket,
                    server_side=True,
                )
            except ssl.SSLError:
                socket.close()
                raise
        return socket, address


class THESAGRAWebHandler(BaseHTTPRequestHandler):
    server_version = "THESAGRAWeb/1.0"

    def _json(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _authorized(self):
        auth = self.headers.get("Authorization")
        if not auth or not auth.startswith("Basic "):
            return False
        try:
            encoded = auth.split(" ", 1)[1]
            decoded = base64.b64decode(encoded).decode("utf-8")
            username, password = decoded.split(":", 1)
        except Exception:
            return False
        username_matches = hmac.compare_digest(
            username.encode("utf-8"),
            self.server.username.encode("utf-8"),
        )
        password_matches = (
            verify_password(password, self.server.password_hash)
            if self.server.password_hash
            else hmac.compare_digest(
                password.encode("utf-8"),
                self.server.password.encode("utf-8"),
            )
        )
        identity = str(self.client_address[0])
        if not username_matches or not password_matches:
            blocked = self.server.failure_throttle.record_failure(identity)
            self.server.audit.write(
                "auth_failed",
                peer=self.client_address,
                detail="account locked" if blocked else None,
            )
            return False
        self.server.failure_throttle.record_success(identity)
        return True

    def _require_auth(self):
        identity = str(self.client_address[0])
        if self.server.failure_throttle.blocked(identity):
            self.server.audit.write(
                "auth_blocked",
                peer=self.client_address,
            )
            self.send_response(429)
            self.send_header("Retry-After", "60")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        if self._authorized():
            self.server.audit.write(
                "auth_success",
                peer=self.client_address,
            )
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="THESAGRA"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            if not self._require_auth():
                return
            self._serve_index()
            return
        if parsed.path == "/api/status":
            if not self._require_auth():
                return
            self._json(
                200,
                {
                    "ok": True,
                    "database": os.path.basename(
                        self.server.database_path
                    ),
                },
            )
            return
        if parsed.path == "/api/blob/download":
            if not self._require_auth():
                return
            object_id = parse_qs(parsed.query).get("id", [None])[0]
            try:
                object_id = int(object_id)
                metadata = self.server.engine.get_blob_metadata(object_id)
                if metadata is None or metadata.state != "ready":
                    raise ValueError("Blob does not exist or is not ready")
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    metadata.mime_type or "application/octet-stream",
                )
                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{metadata.name}"',
                )
                self.send_header(
                    "Content-Length",
                    str(metadata.byte_length),
                )
                self.end_headers()
                for chunk in self.server.engine.stream_blob(
                    object_id,
                    64 * 1024,
                ):
                    self.wfile.write(chunk)
            except Exception as exc:
                self._json(404, {"ok": False, "error": str(exc)})
            return
        self._json(404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        if not self._require_auth():
            return
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        if length > 8 * 1024 * 1024:
            self._json(
                413,
                {"ok": False, "error": "Request exceeds 8 MiB limit"},
            )
            return
        try:
            body = self.rfile.read(length)
        except Exception as exc:
            self._json(400, {"ok": False, "error": str(exc)})
            return

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            self._json(400, {"ok": False, "error": "Invalid JSON"})
            return

        if parsed.path == "/api/query":
            sql = payload.get("sql")
            parameters = payload.get("parameters", [])
            if not isinstance(sql, str):
                self._json(
                    400,
                    {"ok": False, "error": "SQL must be a string"},
                )
                return
            try:
                if parameters:
                    from .server.protocol import bind_parameters

                    sql = bind_parameters(sql, parameters)
                statement = parse(sql)
                with self.server.engine_lock:
                    result = self.server.engine.execute(statement)
                self._json(
                    200,
                    {
                        "ok": True,
                        "columns": result.columns,
                        "rows": [list(row) for row in result.rows],
                        "rowcount": result.rowcount,
                    },
                )
            except (ParseError, QueryError, Exception) as exc:
                self._json(
                    400,
                    {"ok": False, "error": str(exc)},
                )
            return

        if parsed.path == "/api/graph/node":
            try:
                with self.server.engine_lock:
                    node = self.server.engine.create_node(
                        payload.get("label"),
                        payload.get("properties"),
                        payload.get("node_id"),
                    )
                self._json(
                    200,
                    {
                        "ok": True,
                        "node": {
                            "node_id": node.node_id,
                            "label": node.label,
                            "properties": node.properties,
                        },
                    },
                )
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            return

        if parsed.path == "/api/graph/traverse":
            try:
                with self.server.engine_lock:
                    paths = self.server.engine.traverse(
                        payload.get("start_node_id"),
                        payload.get("depth", 1),
                        payload.get("relationship_type"),
                        payload.get("max_nodes", 100),
                    )
                self._json(
                    200,
                    {
                        "ok": True,
                        "paths": [
                            [
                                {
                                    "node_id": node.node_id,
                                    "label": node.label,
                                    "properties": node.properties,
                                }
                                for node in path
                            ]
                            for path in paths
                        ],
                    },
                )
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            return

        if parsed.path == "/api/blob/begin":
            try:
                with self.server.engine_lock:
                    object_id = self.server.engine.begin_blob_upload(
                        payload.get("name"),
                        payload.get("mime_type",
                                     "application/octet-stream"),
                        payload.get("metadata"),
                        payload.get("max_size"),
                    )
                self._json(200, {"ok": True, "object_id": object_id})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            return

        if parsed.path == "/api/blob/append":
            import base64

            try:
                data = base64.b64decode(
                    payload.get("data", ""),
                    validate=True,
                )
                with self.server.engine_lock:
                    written = self.server.engine.append_blob_chunk(
                        payload.get("object_id"),
                        data,
                    )
                self._json(200, {"ok": True, "written": written})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            return

        if parsed.path == "/api/blob/finalize":
            try:
                with self.server.engine_lock:
                    metadata = self.server.engine.finalize_blob(
                        payload.get("object_id"),
                        payload.get("declared_size"),
                    )
                self._json(
                    200,
                    {
                        "ok": True,
                        "metadata": {
                            "object_id": metadata.object_id,
                            "name": metadata.name,
                            "mime_type": metadata.mime_type,
                            "byte_length": metadata.byte_length,
                            "checksum": metadata.checksum,
                            "state": metadata.state,
                        },
                    },
                )
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            return

        self._json(404, {"ok": False, "error": "Not found"})

    def _serve_index(self):
        html = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>THESAGRA Console</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#111827;color:#e5e7eb}
header{padding:16px 20px;background:#1f2937;border-bottom:1px solid #374151}
main{display:grid;grid-template-columns:1fr 1fr;gap:12px;padding:12px}
section{background:#1f2937;border:1px solid #374151;border-radius:8px;padding:12px}
textarea,input,button{box-sizing:border-box;font:14px monospace}
textarea,input{width:100%;padding:8px;margin:6px 0;background:#111827;color:#fff;border:1px solid #4b5563;border-radius:4px}
button{padding:8px 12px;margin:4px 4px 4px 0;background:#2563eb;color:white;border:0;border-radius:4px;cursor:pointer}
button:hover{background:#1d4ed8}
pre{white-space:pre-wrap;background:#111827;padding:10px;border-radius:4px;min-height:80px}
#blobList{min-height:40px}
@media(max-width:800px){main{grid-template-columns:1fr}}
</style>
</head>
<body>
<header><strong>THESAGRA</strong> Browser Console</header>
<main>
<section>
<h3>SQL</h3>
<textarea id="sql" rows="10">CREATE TABLE people (id INTEGER PRIMARY KEY, name TEXT);
INSERT INTO people VALUES (1, 'Ada');
SELECT * FROM people;</textarea>
<button onclick="executeSQL()">Execute</button>
<pre id="sqlOutput"></pre>
</section>
<section>
<h3>Graph</h3>
<input id="nodeId" type="number" value="1" placeholder="Node ID">
<input id="nodeLabel" value="Person" placeholder="Label">
<button onclick="createNode()">Create Node</button>
<input id="depth" type="number" value="2" placeholder="Depth">
<button onclick="traverse()">Traverse</button>
<pre id="graphOutput"></pre>
</section>
<section style="grid-column:1/-1">
<h3>Blobs</h3>
<input id="blobFile" type="file">
<button onclick="uploadBlob()">Upload Streaming</button>
<input id="blobId" type="number" placeholder="Blob object ID">
<button onclick="downloadBlob()">Download</button>
<pre id="blobOutput"></pre>
</section>
</main>
<script>
async function api(path, options={}) {
 const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
 const data=await response.json();
 if(!response.ok) throw new Error(data.error||response.statusText);
 return data;
}
async function executeSQL(){
 try{
  const statements=document.getElementById('sql').value.split(';').map(s=>s.trim()).filter(Boolean);
  let output=[];
  for(const sql of statements) output.push(await api('/api/query',{method:'POST',body:JSON.stringify({sql})}));
  document.getElementById('sqlOutput').textContent=JSON.stringify(output,null,2);
 }catch(error){document.getElementById('sqlOutput').textContent=error.message}
}
async function createNode(){
 try{
  const nodeId=Number(document.getElementById('nodeId').value);
  const label=document.getElementById('nodeLabel').value;
  const data=await api('/api/graph/node',{method:'POST',body:JSON.stringify({node_id:nodeId,label,properties:{}})});
  document.getElementById('graphOutput').textContent=JSON.stringify(data,null,2);
 }catch(error){document.getElementById('graphOutput').textContent=error.message}
}
async function traverse(){
 try{
  const start=Number(document.getElementById('nodeId').value);
  const depth=Number(document.getElementById('depth').value);
  const data=await api('/api/graph/traverse',{method:'POST',body:JSON.stringify({start_node_id:start,depth,max_nodes:100})});
  document.getElementById('graphOutput').textContent=JSON.stringify(data,null,2);
 }catch(error){document.getElementById('graphOutput').textContent=error.message}
}
async function uploadBlob(){
 const file=document.getElementById('blobFile').files[0];
 if(!file){document.getElementById('blobOutput').textContent='Choose a file';return}
 try{
  const begun=await api('/api/blob/begin',{method:'POST',body:JSON.stringify({name:file.name,mime_type:file.type||'application/octet-stream',metadata:{},max_size:file.size})});
  const objectId=begun.object_id;
  const chunkSize=64*1024;
  let offset=0;
  while(offset<file.size){
   const chunk=file.slice(offset,offset+chunkSize);
   const bytes=new Uint8Array(await chunk.arrayBuffer());
   let binary='';
   for(let i=0;i<bytes.length;i+=0x8000) binary+=String.fromCharCode(...bytes.subarray(i,i+0x8000));
   await api('/api/blob/append',{method:'POST',body:JSON.stringify({object_id:objectId,data:btoa(binary)})});
   offset+=bytes.length;
  }
  const finished=await api('/api/blob/finalize',{method:'POST',body:JSON.stringify({object_id:objectId,declared_size:file.size})});
  document.getElementById('blobOutput').textContent=JSON.stringify(finished,null,2);
 }catch(error){document.getElementById('blobOutput').textContent=error.message}
}
function downloadBlob(){
 const id=document.getElementById('blobId').value;
 if(id) window.location='/api/blob/download?id='+encodeURIComponent(id);
}
</script>
</body>
</html>"""
        encoded = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        return
