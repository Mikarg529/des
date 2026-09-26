#!/usr/bin/env python3
"""MCP stateless pour les dés PF1. Outil roll. CSPRNG = secrets.randbelow."""
import json
import os
import re
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FORMULA = re.compile(r"^(\d+)[dD](\d+)\s*(?:([+-])\s*(\d+))?$")
ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
PROTOCOL = "2025-03-26"

def ledger_path() -> Path:
    raw = os.environ.get("DES_LEDGER")
    if raw:
        return Path(raw)
    return Path.home() / ".des-pf1" / "ledger.json"

def load_ledger() -> dict:
    path = ledger_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))

def save_ledger(data: dict) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)

def parse_formula(expr: str) -> dict:
    raw = str(expr).strip()
    match = FORMULA.match(raw)
    if not match:
        raise ValueError("Formule refusée. Un seul groupe de dés, puis un bonus. Exemple : 1d20+16")
    if str(int(match.group(1))) != match.group(1) or str(int(match.group(2))) != match.group(2):
        raise ValueError("Formule refusée. Exemple : 1d20+16")
    count = int(match.group(1))
    sides = int(match.group(2))
    if count < 1 or count > 40:
        raise ValueError("Entre 1 et 40 dés.")
    if sides < 2 or sides > 100:
        raise ValueError("Le dé doit aller de d2 à d100.")
    modifier = 0
    modifier_text = ""
    if match.group(3):
        if str(int(match.group(4))) != match.group(4):
            raise ValueError("Formule refusée. Exemple : 1d20+16")
        modifier = int(match.group(4))
        if match.group(3) == "-":
            modifier = -modifier
        if modifier < -999 or modifier > 999:
            raise ValueError("Le bonus doit rester entre -999 et +999.")
        modifier_text = match.group(3) + match.group(4)
    return {"n": count, "sides": sides, "mod": modifier, "expr": f"{count}d{sides}{modifier_text}"}

def roll_new(spec: dict) -> dict:
    bruts = []
    for _ in range(spec["n"]):
        face = secrets.randbelow(spec["sides"]) + 1
        if face < 1 or face > spec["sides"]:
            raise RuntimeError("Erreur technique. Le jet n'est pas renvoyé.")
        bruts.append(face)
    total = sum(bruts) + spec["mod"]
    if len(bruts) != spec["n"] or total != sum(bruts) + spec["mod"]:
        raise RuntimeError("Erreur technique. Le jet n'est pas renvoyé.")
    line = f"{spec['expr']} | brut [{','.join(str(n) for n in bruts)}] | total {total}"
    return {"expr": spec["expr"], "bruts": bruts, "total": total, "line": line, "replay": False}

def roll(formula: str, roll_id: str) -> dict:
    if not isinstance(roll_id, str) or not ID_RE.match(roll_id):
        raise ValueError("id requis : lettres, chiffres, point, underscore, deux-points, tiret")
    spec = parse_formula(formula)
    data = load_ledger()
    previous = data.get(roll_id)
    if previous:
        if previous["expr"] != spec["expr"]:
            raise ValueError("Cet id a déjà un autre jet. Change l'id.")
        return {
            "expr": previous["expr"],
            "bruts": previous["bruts"],
            "total": previous["total"],
            "line": previous["line"],
            "replay": True,
        }
    result = roll_new(spec)
    data[roll_id] = {
        "expr": result["expr"],
        "bruts": result["bruts"],
        "total": result["total"],
        "line": result["line"],
    }
    if len(data) > 500:
        for key in list(data)[: len(data) - 500]:
            data.pop(key, None)
    save_ledger(data)
    return result

TOOLS = {
    "name": "roll",
    "description": "Seule source de hasard. Utilise cet outil pour chaque jet, avant d'annoncer un nombre. Formule fixée d'abord, par exemple 1d20+16. Renvoie expr, bruts, total et line. Cite line mot pour mot. Le même id renvoie le même jet et ne relance pas.",
    "inputSchema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["formula", "id"],
        "properties": {
            "formula": {"type": "string", "description": "Un groupe de dés et un bonus. Exemples : 1d20+16, 2d6+10, 1d8-2."},
            "id": {"type": "string", "description": "Identifiant unique de ce jet. Ne pas réutiliser un id pour une autre formule."},
        },
    },
}

def rpc(message: dict):
    method = message.get("method")
    number = message.get("id")
    if method == "notifications/initialized" or (isinstance(method, str) and method.startswith("notifications/")):
        return None
    if number is None:
        return None
    if method == "initialize":
        payload = {
            "protocolVersion": PROTOCOL,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "des-pf1", "version": "1"},
            "instructions": "Chaque jet passe par roll. Cite le champ line mot pour mot. N'invente aucun dé. Un id déjà vu n'est pas un nouveau jet.",
        }
        return {"jsonrpc": "2.0", "id": number, "result": payload}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": number, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": number, "result": {"tools": [TOOLS]}}
    if method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") != "roll":
            return {"jsonrpc": "2.0", "id": number, "error": {"code": -32602, "message": "outil inconnu"}}
        args = params.get("arguments") or {}
        try:
            got = roll(args.get("formula"), args.get("id"))
        except ValueError as exc:
            return {
                "jsonrpc": "2.0",
                "id": number,
                "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            }
        return {
            "jsonrpc": "2.0",
            "id": number,
            "result": {
                "content": [{"type": "text", "text": got["line"]}],
                "structuredContent": got,
                "isError": False,
            },
        }
    return {"jsonrpc": "2.0", "id": number, "error": {"code": -32601, "message": "méthode inconnue"}}

class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, payload) -> None:
        if payload is None:
            self.send_response(202)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-headers", "content-type, accept, mcp-protocol-version")
        self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/health"):
            self._json(200, {"ok": True, "mcp": "/mcp", "tool": "roll"})
            return
        self._json(404, {"ok": False})

    def do_POST(self):
        if self.path.split("?")[0] != "/mcp":
            self._json(404, {"ok": False})
            return
        length = int(self.headers.get("content-length", "0"))
        try:
            message = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON invalide"}})
            return
        self._json(200, rpc(message))

    def log_message(self, fmt, *args):
        return

def self_test() -> None:
    os.environ["DES_LEDGER"] = str(Path("/tmp/des-pf1-selftest.json"))
    ledger_path().unlink(missing_ok=True)
    calls = {"n": 0}
    real = secrets.randbelow
    def wrapped(span):
        calls["n"] += 1
        return real(span)
    secrets.randbelow = wrapped
    try:
        listed = rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert listed["result"]["tools"][0]["name"] == "roll"
        good = ["1d20", "1d20+16", "1d20-5", "2d6+10", "40d100-999"]
        for index, formula in enumerate(good):
            calls["n"] = 0
            answer = rpc({"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": "roll", "arguments": {"formula": formula, "id": f"OK{index}"}}})
            got = answer["result"]["structuredContent"]
            assert calls["n"] == parse_formula(formula)["n"], formula
            assert got["total"] == sum(got["bruts"]) + parse_formula(formula)["mod"]
            assert answer["result"]["content"][0]["text"] == got["line"]
            print("PASS", got["line"])
        for formula in ["0d20", "1d101", "1d20+1000", "1d20+2d6", "abc"]:
            calls["n"] = 0
            answer = rpc({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "roll", "arguments": {"formula": formula, "id": "BAD"}}})
            assert answer["result"]["isError"] is True
            assert calls["n"] == 0
            print("PASS refuse", formula)
        first = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "roll", "arguments": {"formula": "1d20+16", "id": "SAME"}}})
        calls["n"] = 0
        second = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "roll", "arguments": {"formula": "1d20+16", "id": "SAME"}}})
        assert first["result"]["structuredContent"]["line"] == second["result"]["structuredContent"]["line"]
        assert second["result"]["structuredContent"]["replay"] is True
        assert calls["n"] == 0
        print("PASS replay")
    finally:
        secrets.randbelow = real
    print("SELF_TEST_OK")

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        port = int(os.environ.get("PORT", "8787"))
        ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
