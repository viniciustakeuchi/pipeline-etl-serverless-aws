import gzip
import json
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from etl import extracao
from etl.config import Config
from etl.http import ErroHTTP, Resposta
from etl.s3 import S3Client
from tests.conftest import BUCKET, HTTPFalso, fixture, ok

EVENTO = {"data_coleta": "2026-10-13"}


def _metricas(saida: str) -> dict[str, object]:
    linhas = [json.loads(linha) for linha in saida.splitlines() if linha.startswith('{"_aws"')]
    assert len(linhas) == 1
    metricas: dict[str, object] = linhas[0]
    return metricas


def test_extrai_todas_as_fontes_para_a_camada_raw(
    fontes_ok: HTTPFalso,
    cfg: Config,
    s3: S3Client,
    ler_objeto: Callable[[str], bytes],
    capsys: pytest.CaptureFixture[str],
) -> None:
    resumo = extracao.executar(EVENTO, cfg, s3, execucao="req-1")

    assert resumo["data_coleta"] == "2026-10-13"
    assert {f["fonte"]: f["status"] for f in resumo["fontes"]} == dict.fromkeys(
        ["cdi", "selic", "selic_meta", "ipca", "tesouro"], "ok"
    )
    chave = "raw/fonte=cdi/data_coleta=2026-10-13/cdi.json.gz"
    # O bruto é guardado sem alteração, só comprimido.
    assert gzip.decompress(ler_objeto(chave)) == fixture("sgs_cdi.json")
    cabecalho = s3.head_object(Bucket=BUCKET, Key=chave)
    assert cabecalho["Metadata"] == {"estrategia": "api", "tentativas": "1", "execucao": "req-1"}

    metricas = _metricas(capsys.readouterr().out)
    assert metricas["FontesComSucesso"] == 5
    assert metricas["FontesComFalha"] == 0
    assert metricas["BytesExtraidos"] == sum(f["bytes"] for f in resumo["fontes"])


def test_falha_parcial_nao_derruba_as_outras_fontes(
    fontes_ok: HTTPFalso, cfg: Config, s3: S3Client, capsys: pytest.CaptureFixture[str]
) -> None:
    fontes_ok.rotas["bcdata.sgs.433/"] = ErroHTTP(500, "u")

    resumo = extracao.executar(EVENTO, cfg, s3, execucao="req-2")

    ipca = next(f for f in resumo["fontes"] if f["fonte"] == "ipca")
    assert ipca["status"] == "falha"
    assert "HTTP 500" in ipca["erro"]
    assert sum(f["status"] == "ok" for f in resumo["fontes"]) == 4
    assert _metricas(capsys.readouterr().out)["FontesComFalha"] == 1


def test_falha_total_levanta_erro_para_acionar_retry_e_dlq(
    http: HTTPFalso, cfg: Config, s3: S3Client
) -> None:
    http.rotas["teste"] = ErroHTTP(400, "u")
    with pytest.raises(extracao.FalhaTotal, match="Todas as 5 fontes"):
        extracao.executar(EVENTO, cfg, s3, execucao="req-3")


def test_fonte_sem_dados_nao_grava_arquivo(http: HTTPFalso, cfg: Config, s3: S3Client) -> None:
    http.rotas["bcdata.sgs.12/"] = Resposta(404, b"", "")
    resumo = extracao.executar({**EVENTO, "fontes": ["cdi"]}, cfg, s3, execucao="req-4")
    assert resumo["fontes"][0]["status"] == "sem_dados"
    assert "Contents" not in s3.list_objects_v2(Bucket=BUCKET)


def test_reprocessa_dia_e_fonte_escolhidos(fontes_ok: HTTPFalso, cfg: Config, s3: S3Client) -> None:
    resumo = extracao.executar(
        {"data_coleta": "2026-09-30", "fontes": ["tesouro"]}, cfg, s3, execucao="req-5"
    )
    assert [f["chave"] for f in resumo["fontes"]] == [
        "raw/fonte=tesouro/data_coleta=2026-09-30/tesouro.json.gz"
    ]


def test_rodar_duas_vezes_no_mesmo_dia_sobrescreve(
    fontes_ok: HTTPFalso, cfg: Config, s3: S3Client
) -> None:
    extracao.executar(EVENTO, cfg, s3, execucao="a")
    extracao.executar(EVENTO, cfg, s3, execucao="b")
    assert s3.list_objects_v2(Bucket=BUCKET)["KeyCount"] == 5


def test_tesouro_pelo_csv_grava_com_extensao_csv(
    fontes_ok: HTTPFalso, cfg: Config, s3: S3Client
) -> None:
    fontes_ok.rotas["rentabilidade"] = ErroHTTP(410, "u")
    fontes_ok.rotas["PrecoTaxa"] = ok(fixture("tesouro_precos_taxas.csv"), "text/csv")
    resumo = extracao.executar({**EVENTO, "fontes": ["tesouro"]}, cfg, s3, execucao="c")
    fonte = resumo["fontes"][0]
    assert fonte["chave"].endswith("tesouro.csv.gz")
    assert fonte["estrategia"] == "csv"


def test_fonte_desconhecida(cfg: Config, s3: S3Client) -> None:
    with pytest.raises(ValueError, match="desconhecidas"):
        extracao.executar({"fontes": ["dolar"]}, cfg, s3, execucao="d")


def test_handler_usa_variaveis_de_ambiente_e_id_da_requisicao(
    fontes_ok: HTTPFalso,
    s3: S3Client,
    cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BUCKET_DADOS", BUCKET)
    monkeypatch.setenv("BACKOFF_INICIAL_SEGUNDOS", "0")
    monkeypatch.setenv("SGS_URL_BASE", cfg.sgs_url_base)
    monkeypatch.setenv("TESOURO_URL_API", cfg.tesouro_url_api)
    resumo = extracao.handler({"fontes": ["cdi"]}, SimpleNamespace(aws_request_id="abc"))
    chave = resumo["fontes"][0]["chave"]
    assert s3.head_object(Bucket=BUCKET, Key=chave)["Metadata"]["execucao"] == "abc"
