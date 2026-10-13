import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

from etl.config import Config
from etl.http import ErroHTTP, Resposta
from etl.s3 import S3Client

FIXTURES = Path(__file__).parent / "fixtures"
BUCKET = "pipeline-etl-testes"


def fixture(nome: str) -> bytes:
    return (FIXTURES / nome).read_bytes()


def json_bytes(dados: Any) -> bytes:
    return json.dumps(dados).encode()


SGS_SELIC = json_bytes([{"data": "10/10/2025", "valor": "0.055131"}])
SGS_SELIC_META = json_bytes(
    [{"data": "09/10/2025", "valor": "15.00"}, {"data": "10/10/2025", "valor": "15.00"}]
)


@pytest.fixture(autouse=True)
def credenciais_falsas(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nenhum teste pode alcançar uma conta AWS de verdade."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "teste")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "teste")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "sa-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)


@pytest.fixture
def cfg() -> Config:
    return Config(
        bucket=BUCKET,
        s3_endpoint=None,
        tentativas=3,
        backoff_inicial_segundos=0,
        sgs_url_base="https://sgs.teste/dados/serie",
        tesouro_url_api="https://tesouro.teste/o/rentabilidade/resgatar",
        tesouro_url_csv="https://transparente.teste/PrecoTaxaTesouroDireto.csv",
    )


@pytest.fixture
def s3() -> Iterator[S3Client]:
    with mock_aws():
        cliente = boto3.client("s3", region_name="sa-east-1")
        cliente.create_bucket(
            Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "sa-east-1"}
        )
        yield cliente


Rota = Resposta | Exception | list[Resposta | Exception]


class HTTPFalso:
    """Substitui `etl.fontes.baixar`: responde por trecho da URL e guarda as chamadas."""

    def __init__(self) -> None:
        self.rotas: dict[str, Rota] = {}
        self.chamadas: list[str] = []

    def __call__(self, url: str, timeout: float, aceitar: frozenset[int] = frozenset()) -> Resposta:
        self.chamadas.append(url)
        for trecho, rota in self.rotas.items():
            if trecho in url:
                resposta = rota.pop(0) if isinstance(rota, list) else rota
                if isinstance(resposta, Exception):
                    raise resposta
                if resposta.status >= 400 and resposta.status not in aceitar:
                    raise ErroHTTP(resposta.status, url)
                return resposta
        raise AssertionError(f"URL sem rota no teste: {url}")


def ok(corpo: bytes, tipo: str = "application/json") -> Resposta:
    return Resposta(200, corpo, tipo)


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> HTTPFalso:
    falso = HTTPFalso()
    monkeypatch.setattr("etl.fontes.baixar", falso)
    return falso


@pytest.fixture
def fontes_ok(http: HTTPFalso) -> HTTPFalso:
    http.rotas.update(
        {
            "bcdata.sgs.12/": ok(fixture("sgs_cdi.json")),
            "bcdata.sgs.11/": ok(SGS_SELIC),
            "bcdata.sgs.432/": ok(SGS_SELIC_META),
            "bcdata.sgs.433/": ok(fixture("sgs_ipca.json")),
            "rentabilidade": ok(fixture("tesouro_rentabilidade.json")),
        }
    )
    return http


@pytest.fixture
def ler_objeto(s3: S3Client) -> Callable[[str], bytes]:
    def ler(chave: str) -> bytes:
        return s3.get_object(Bucket=BUCKET, Key=chave)["Body"].read()

    return ler
