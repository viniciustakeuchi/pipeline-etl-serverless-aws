import threading
import urllib.error
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from etl.http import USER_AGENT, ErroHTTP, baixar, erro_transitorio


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        status = int(self.path.strip("/").split("?")[0] or 200)
        corpo = self.headers["User-Agent"].encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def servidor() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_get_com_sucesso_envia_user_agent(servidor: str) -> None:
    resposta = baixar(f"{servidor}/200", timeout=5)
    assert resposta.status == 200
    assert resposta.corpo.decode() == USER_AGENT
    assert resposta.tipo == "application/json"


def test_status_aceito_nao_vira_erro(servidor: str) -> None:
    resposta = baixar(f"{servidor}/404", timeout=5, aceitar=frozenset({404}))
    assert (resposta.status, resposta.corpo) == (404, b"")


def test_status_de_erro_vira_excecao(servidor: str) -> None:
    with pytest.raises(ErroHTTP) as erro:
        baixar(f"{servidor}/503", timeout=5)
    assert erro.value.status == 503


@pytest.mark.parametrize(
    ("erro", "transitorio"),
    [
        (ErroHTTP(500, "u"), True),
        (ErroHTTP(503, "u"), True),
        (ErroHTTP(429, "u"), True),
        (ErroHTTP(404, "u"), False),
        (ErroHTTP(400, "u"), False),
        (urllib.error.URLError("dns"), True),
        (TimeoutError(), True),
        (ConnectionResetError(), True),
        (ValueError(), False),
    ],
)
def test_classifica_erros_transitorios(erro: BaseException, transitorio: bool) -> None:
    assert erro_transitorio(erro) is transitorio
