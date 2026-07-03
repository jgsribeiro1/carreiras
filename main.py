"""
Le Grand Terroir - Sistema de Candidaturas
Backend usando SOMENTE a biblioteca padrão do Python (nenhuma dependência externa).
Serve a API (/api/...) e também o site estático (frontend/index.html e frontend/admin.html).

Não há upload de arquivos: por decisão de segurança (evitar que candidatos anexem
arquivos maliciosos), toda a candidatura, incluindo experiências profissionais e
formação acadêmica, é preenchida como texto no próprio formulário.

Rodar localmente:
    python3 main.py
    (abre em http://localhost:8000)

Variáveis de ambiente:
    ADMIN_TOKEN      - senha/token do painel administrativo (obrigatório em produção)
    ALLOWED_ORIGIN   - origem liberada para CORS, use "*" em teste
    PORT             - porta do servidor (padrão 8000; a maioria dos serviços de
                       hospedagem define isso automaticamente)
"""

import csv
import io
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "candidaturas.db"
FRONTEND_DIR = BASE_DIR / "frontend"

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "troque-este-token")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
PORT = int(os.environ.get("PORT", "8000"))

MAX_BODY_SIZE_BYTES = 300 * 1024  # 300 KB, de sobra para um formulário só de texto
MAX_LIST_ITEMS = 12  # limite de experiências/formações por candidatura (evita abuso)
MAX_FIELD_LEN = 4000  # limite de caracteres por campo de texto longo (ex: descrição)

VAGAS_VALIDAS = [
    "Gerente de Centro de Distribuição (CD)",
    "Analista de Logística / Planejamento",
    "Analista Fiscal / Expedição (Armazém Geral)",
    "Conferente / Controlador de Estoque",
    "Operador de Empilhadeira (NR-11)",
    "Operador de Armazém (Separação e Packing)",
    "Auxiliar de Embalagem",
    "Motorista CNH D (Entregas + Passageiros)",
    "Motorista CNH E (Carreta / Transferências)",
    "Atendimento ao Cliente B2B / Customer Success",
    "Atendimento E-commerce / Consumidor Final",
    "Técnico de Segurança do Trabalho (SESMT)",
    "Qualidade e Recebimento (Controle de Qualidade)",
    "Manutenção / Facilities Técnico",
    "Suporte de TI / WMS",
    "Gerente de Loja",
    "Sommelier / Consultor de Vinhos",
    "Consultor de Vendas / Wine Advisor (multifunção)",
    "Estoquista / Repositor",
    "Banco de talentos (nenhuma vaga específica)",
]

STATUS_VALIDOS = {"novo", "em análise", "entrevista", "aprovado", "rejeitado"}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".svg": "image/svg+xml; charset=utf-8",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
}


# --------------------------------------------------------------------------
# Banco de dados
# --------------------------------------------------------------------------

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS candidaturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vaga TEXT NOT NULL,
            nome TEXT NOT NULL,
            telefone TEXT NOT NULL,
            email TEXT NOT NULL,
            endereco_json TEXT,
            linkedin TEXT,
            experiencias_json TEXT,
            formacoes_json TEXT,
            mensagem TEXT,
            criado_em TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'novo'
        )
        """
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------
# Validação de payload
# --------------------------------------------------------------------------

ENDERECO_CAMPOS = ["cep", "rua", "numero", "complemento", "bairro", "cidade", "estado"]
EXPERIENCIA_CAMPOS = ["empresa", "cargo", "periodo", "descricao"]
FORMACAO_CAMPOS = ["instituicao", "curso", "nivel", "status", "periodo"]


def _clean_text(value, max_len=MAX_FIELD_LEN) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text[:max_len]


def _clean_dict(raw, campos) -> dict:
    if not isinstance(raw, dict):
        return {}
    return {campo: _clean_text(raw.get(campo, "")) for campo in campos}


def _clean_list(raw, campos):
    if not isinstance(raw, list):
        return []
    limpo = [_clean_dict(item, campos) for item in raw[:MAX_LIST_ITEMS]]
    # remove entradas totalmente vazias
    return [item for item in limpo if any(v for v in item.values())]


# --------------------------------------------------------------------------
# HTTP handler
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "LeGrandTerroir/2.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    # -- utilitários de resposta -------------------------------------------------

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Admin-Token")

    def send_json(self, status: int, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: int, detail: str):
        self.send_json(status, {"detail": detail})

    def send_file(self, path: Path):
        if not path.exists() or not path.is_file():
            self.send_error_json(404, "Arquivo não encontrado")
            return
        ext = path.suffix.lower()
        ctype = CONTENT_TYPES.get(ext, "application/octet-stream")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        if length > MAX_BODY_SIZE_BYTES:
            raise ValueError("Corpo da requisição excede o tamanho máximo permitido")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ValueError("JSON inválido")
        if not isinstance(data, dict):
            raise ValueError("Corpo da requisição deve ser um objeto JSON")
        return data

    def _check_admin(self, query: dict) -> bool:
        token = self.headers.get("X-Admin-Token") or (query.get("token", [None])[0])
        return bool(token) and token == ADMIN_TOKEN

    # -- roteamento ----------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        try:
            if path == "/api/health":
                return self.send_json(200, {"status": "ok"})

            if path == "/api/vagas":
                return self.send_json(200, {"vagas": VAGAS_VALIDAS})

            if path == "/api/candidaturas":
                return self._handle_list_candidaturas(query)

            if path == "/api/candidaturas/export/csv":
                return self._handle_export_csv(query)

            return self._serve_static(path)

        except Exception as exc:  # pragma: no cover
            self.send_error_json(500, f"Erro interno: {exc}")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/api/candidaturas":
                return self._handle_create_candidatura()
            self.send_error_json(404, "Rota não encontrada")
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:  # pragma: no cover
            self.send_error_json(500, f"Erro interno: {exc}")

    def do_PATCH(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            m = re.match(r"^/api/candidaturas/(\d+)/status$", path)
            if m:
                return self._handle_update_status(int(m.group(1)))
            self.send_error_json(404, "Rota não encontrada")
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:  # pragma: no cover
            self.send_error_json(500, f"Erro interno: {exc}")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            m = re.match(r"^/api/candidaturas/(\d+)$", path)
            if m:
                return self._handle_delete_candidatura(int(m.group(1)))
            self.send_error_json(404, "Rota não encontrada")
        except Exception as exc:  # pragma: no cover
            self.send_error_json(500, f"Erro interno: {exc}")

    # -- handlers --------------------------------------------------------------

    def _serve_static(self, path: str):
        if path == "/":
            path = "/index.html"
        safe_path = path.lstrip("/")
        file_path = (FRONTEND_DIR / safe_path).resolve()

        if FRONTEND_DIR.resolve() not in file_path.parents and file_path != FRONTEND_DIR.resolve():
            return self.send_error_json(403, "Acesso negado")

        if not file_path.exists():
            return self.send_error_json(404, "Página não encontrada")

        return self.send_file(file_path)

    def _handle_create_candidatura(self):
        content_type = self.headers.get("Content-Type", "")
        if "application/json" not in content_type:
            raise ValueError("Content-Type deve ser application/json")

        data = self._read_json_body()

        vaga = _clean_text(data.get("vaga"), 200)
        nome = _clean_text(data.get("nome"), 200)
        telefone = _clean_text(data.get("telefone"), 40)
        email = _clean_text(data.get("email"), 200)
        linkedin = _clean_text(data.get("linkedin"), 300)
        mensagem = _clean_text(data.get("mensagem"), MAX_FIELD_LEN)

        endereco = _clean_dict(data.get("endereco"), ENDERECO_CAMPOS)
        experiencias = _clean_list(data.get("experiencias"), EXPERIENCIA_CAMPOS)
        formacoes = _clean_list(data.get("formacoes"), FORMACAO_CAMPOS)

        if vaga not in VAGAS_VALIDAS:
            raise ValueError("Vaga inválida")
        if not nome or not telefone or not email:
            raise ValueError("Nome, telefone e e-mail são obrigatórios")

        conn = get_db()
        cur = conn.execute(
            """
            INSERT INTO candidaturas
                (vaga, nome, telefone, email, endereco_json, linkedin,
                 experiencias_json, formacoes_json, mensagem, criado_em)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vaga, nome, telefone, email,
                json.dumps(endereco, ensure_ascii=False),
                linkedin,
                json.dumps(experiencias, ensure_ascii=False),
                json.dumps(formacoes, ensure_ascii=False),
                mensagem,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()

        self.send_json(201, {"id": new_id, "message": "Candidatura recebida com sucesso"})

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        for campo in ("endereco_json", "experiencias_json", "formacoes_json"):
            chave_final = campo.replace("_json", "")
            try:
                d[chave_final] = json.loads(d.pop(campo) or ("{}" if campo == "endereco_json" else "[]"))
            except (json.JSONDecodeError, TypeError):
                d[chave_final] = {} if campo == "endereco_json" else []
        return d

    def _handle_list_candidaturas(self, query: dict):
        if not self._check_admin(query):
            return self.send_error_json(401, "Token de administrador inválido")

        vaga = query.get("vaga", [None])[0]
        status = query.get("status", [None])[0]
        q = query.get("q", [None])[0]

        sql = "SELECT * FROM candidaturas WHERE 1=1"
        params = []
        if vaga:
            sql += " AND vaga = ?"
            params.append(vaga)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if q:
            sql += " AND (nome LIKE ? OR email LIKE ? OR telefone LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like, like])
        sql += " ORDER BY criado_em DESC"

        conn = get_db()
        rows = conn.execute(sql, params).fetchall()
        conn.close()

        result = [self._row_to_dict(r) for r in rows]
        self.send_json(200, {"candidaturas": result, "total": len(result)})

    def _handle_update_status(self, candidatura_id: int):
        if not self._check_admin({}):
            return self.send_error_json(401, "Token de administrador inválido")

        data = self._read_json_body()
        status = _clean_text(data.get("status"), 40)
        if status not in STATUS_VALIDOS:
            raise ValueError("Status inválido")

        conn = get_db()
        conn.execute("UPDATE candidaturas SET status = ? WHERE id = ?", (status, candidatura_id))
        conn.commit()
        conn.close()

        self.send_json(200, {"message": "Status atualizado"})

    def _handle_delete_candidatura(self, candidatura_id: int):
        if not self._check_admin({}):
            return self.send_error_json(401, "Token de administrador inválido")

        conn = get_db()
        conn.execute("DELETE FROM candidaturas WHERE id = ?", (candidatura_id,))
        conn.commit()
        conn.close()

        self.send_json(200, {"message": "Candidatura removida"})

    def _handle_export_csv(self, query: dict):
        if not self._check_admin(query):
            return self.send_error_json(401, "Token de administrador inválido")

        conn = get_db()
        rows = conn.execute("SELECT * FROM candidaturas ORDER BY criado_em DESC").fetchall()
        conn.close()

        def fmt_endereco(raw):
            try:
                e = json.loads(raw or "{}")
            except json.JSONDecodeError:
                e = {}
            partes = [e.get("rua", ""), e.get("numero", ""), e.get("complemento", ""),
                      e.get("bairro", ""), e.get("cidade", ""), e.get("estado", ""), e.get("cep", "")]
            return ", ".join(p for p in partes if p)

        def fmt_experiencias(raw):
            try:
                items = json.loads(raw or "[]")
            except json.JSONDecodeError:
                items = []
            return " | ".join(
                f"{i.get('cargo', '')} @ {i.get('empresa', '')} ({i.get('periodo', '')}): {i.get('descricao', '')}"
                for i in items
            )

        def fmt_formacoes(raw):
            try:
                items = json.loads(raw or "[]")
            except json.JSONDecodeError:
                items = []
            return " | ".join(
                f"{i.get('curso', '')} - {i.get('instituicao', '')} ({i.get('nivel', '')}, {i.get('status', '')}, {i.get('periodo', '')})"
                for i in items
            )

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            ["ID", "Vaga", "Nome", "Telefone", "Email", "Endereço", "LinkedIn",
             "Experiências", "Formação", "Mensagem", "Status", "Criado em"]
        )
        for r in rows:
            writer.writerow([
                r["id"], r["vaga"], r["nome"], r["telefone"], r["email"],
                fmt_endereco(r["endereco_json"]), r["linkedin"],
                fmt_experiencias(r["experiencias_json"]), fmt_formacoes(r["formacoes_json"]),
                r["mensagem"], r["status"], r["criado_em"],
            ])

        data = output.getvalue().encode("utf-8-sig")  # BOM ajuda o Excel a ler acentos
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", "attachment; filename=candidaturas.csv")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)


def main():
    init_db()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Le Grand Terroir - sistema de candidaturas rodando em http://localhost:{PORT}")
    print(f"Painel admin em http://localhost:{PORT}/admin.html")
    if ADMIN_TOKEN == "troque-este-token":
        print("AVISO: defina a variável de ambiente ADMIN_TOKEN antes de publicar em produção.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
