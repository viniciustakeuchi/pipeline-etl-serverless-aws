"""Cliente HTTP mínimo sobre urllib.

A Lambda de extração não leva dependências: urllib basta para três GETs por dia e evita
empacotar httpx (e o zip continua editável no console, se precisar).
"""

import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0 Safari/537.36"
)


@dataclass(frozen=True)
class Resposta:
    status: int
    corpo: bytes
    tipo: str


class ErroHTTP(Exception):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"HTTP {status} em {url}")
        self.status = status
        self.url = url


def baixar(url: str, timeout: float, aceitar: frozenset[int] = frozenset()) -> Resposta:
    """GET simples. Status em `aceitar` (ex.: 404 do SGS sem dados) não viram erro."""
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
            return Resposta(resposta.status, resposta.read(), resposta.headers.get_content_type())
    except urllib.error.HTTPError as erro:
        if erro.code in aceitar:
            return Resposta(erro.code, b"", "")
        raise ErroHTTP(erro.code, url) from erro


def erro_transitorio(erro: BaseException) -> bool:
    """Vale repetir: timeout, falha de rede, 429 e 5xx."""
    if isinstance(erro, ErroHTTP):
        return erro.status == 429 or erro.status >= 500
    return isinstance(erro, urllib.error.URLError | socket.timeout | TimeoutError | ConnectionError)
