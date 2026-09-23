"""Control del laboratorio GNS3 via API REST + consolas telnet."""
import socket, time, re, json, os, sys, urllib.request, base64, configparser

CTRL = "http://127.0.0.1:3080"
VMIP = "192.168.56.101"

def _auth():
    ini = os.path.join(os.environ["APPDATA"], "GNS3", "2.2", "gns3_server.ini")
    cp = configparser.ConfigParser()
    cp.read(ini)
    sec = cp["Server"] if cp.has_section("Server") else cp[cp.sections()[0]]
    return sec.get("user", ""), sec.get("password", "")

_U, _P = _auth()

def api(method, path, body=None, timeout=900):
    url = CTRL + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{_U}:{_P}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return {"_error": e.code, **json.loads(raw)}
        except Exception:
            return {"_error": e.code, "message": raw[:400]}

def _clean(b):
    out = bytearray(); i = 0
    while i < len(b):
        c = b[i]
        if c == 255:
            if i + 1 < len(b):
                cmd = b[i + 1]
                if cmd == 250:
                    j = i + 2
                    while j + 1 < len(b) and not (b[j] == 255 and b[j + 1] == 240):
                        j += 1
                    i = j + 2; continue
                if cmd in (251, 252, 253, 254):
                    i += 3; continue
                i += 2; continue
            i += 1; continue
        out.append(c); i += 1
    return bytes(out)

CRLF = b"\r\n"
CR = b"\r"

class Console:
    """Sesion telnet a la consola de un nodo. eol=CR para VPCS, CRLF para shells."""
    def __init__(self, port, host=VMIP, settle=5.0, eol=CRLF):
        self.eol = eol
        self.s = socket.create_connection((host, port), timeout=20)
        self.s.settimeout(2)
        self.buf = b""
        self.s.sendall(self.eol)
        self._drain(settle)

    def _drain(self, t, quiet=1.3):
        """Lee hasta 't' segundos. Corta antes solo si ya llego algo y luego
        hubo 'quiet' segundos de silencio. Un ping bloqueado tarda varios
        segundos en imprimir su primer 'timeout', asi que no se puede cortar
        al primer silencio."""
        deadline = time.time() + t
        last = None
        while time.time() < deadline:
            try:
                x = self.s.recv(65536)
                if not x:
                    return
                self.buf += x
                last = time.time()
            except socket.timeout:
                pass
            if last is not None and time.time() - last >= quiet:
                return

    def run(self, cmd, wait=5.0, quiet=1.3):
        self.buf = b""
        self.s.sendall(cmd.encode() + self.eol)
        self._drain(wait, quiet)
        t = _clean(self.buf).decode("utf-8", "replace")
        return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", t)

    def runmany(self, cmds, wait=5.0, quiet=1.3):
        return "\n".join(self.run(c, wait, quiet) for c in cmds)

    def close(self):
        try: self.s.close()
        except Exception: pass

def sh(port, cmds, wait=5.0, settle=5.0, eol=CRLF, quiet=1.3):
    c = Console(port, settle=settle, eol=eol)
    try:
        return c.runmany(cmds if isinstance(cmds, list) else [cmds], wait, quiet)
    finally:
        c.close()

def vpcs(port, cmds, wait=8.0, settle=5.0, quiet=1.3):
    return sh(port, cmds, wait=wait, settle=settle, eol=CR, quiet=quiet)
