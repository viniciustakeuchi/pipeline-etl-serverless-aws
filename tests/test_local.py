import json
from decimal import Decimal

import pytest

from etl import local
from etl.config import Config
from etl.s3 import S3Client
from tests.conftest import HTTPFalso, json_bytes, ok


def test_pipeline_completo_e_consultas_no_duckdb(
    fontes_ok: HTTPFalso, cfg: Config, s3: S3Client
) -> None:
    resumo = local.executar(cfg, s3, "2026-10-13", None)
    assert len(resumo["transformacao"]["arquivos"]) == 5

    premissas = local.consultar(cfg, s3, "premissas")
    assert len(premissas) == 1
    linha = premissas[0]
    # CDI de 0,055131% ao dia equivale a 14,90% ao ano em 252 dias úteis.
    assert float(linha["cdi_anual"]) == pytest.approx(14.90, abs=0.01)
    assert linha["selic_meta"] == Decimal("15.00000000")
    # IPCA de out/2024 a set/2025 (12 meses), acumulado.
    assert linha["meses_ipca"] == 12
    assert float(linha["ipca_12m"]) == pytest.approx(5.17, abs=0.01)

    ultimos = {r["serie"]: r for r in local.consultar(cfg, s3, "ultimos_indicadores")}
    assert set(ultimos) == {"cdi", "selic", "selic_meta", "ipca"}
    assert str(ultimos["ipca"]["data_referencia"]) == "2025-09-01"

    curva = local.consultar(cfg, s3, "curva_tesouro")
    assert len(curva) == 9
    assert {r["origem"] for r in curva} == {"api"}


def test_snapshot_mais_novo_vence_na_deduplicacao(
    fontes_ok: HTTPFalso, cfg: Config, s3: S3Client
) -> None:
    local.executar(cfg, s3, "2026-10-13", ["cdi"])
    # O Banco Central revisou o último valor no dia seguinte.
    fontes_ok.rotas["bcdata.sgs.12/"] = ok(
        json_bytes([{"data": "07/10/2025", "valor": "0.060000"}])
    )
    local.executar(cfg, s3, "2026-10-14", ["cdi"])

    ultimos = {r["serie"]: r for r in local.consultar(cfg, s3, "ultimos_indicadores")}
    assert ultimos["cdi"]["valor"] == Decimal("0.06000000")


def test_cria_o_bucket_quando_nao_existe(fontes_ok: HTTPFalso, cfg: Config, s3: S3Client) -> None:
    novo = Config(**{**cfg.__dict__, "bucket": "bucket-novo"})
    local.executar(novo, s3, "2026-10-13", ["cdi"])
    assert s3.list_objects_v2(Bucket="bucket-novo")["KeyCount"] == 2


def test_linha_de_comando(
    fontes_ok: HTTPFalso,
    cfg: Config,
    s3: S3Client,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for nome, valor in {
        "BUCKET_DADOS": cfg.bucket,
        "BACKOFF_INICIAL_SEGUNDOS": "0",
        "SGS_URL_BASE": cfg.sgs_url_base,
        "TESOURO_URL_API": cfg.tesouro_url_api,
    }.items():
        monkeypatch.setenv(nome, valor)

    assert local.main(["executar", "--data", "2026-10-13", "--fontes", "cdi,selic_meta"]) == 0
    saida = capsys.readouterr().out
    resumo = json.loads(saida[saida.index("{\n") :])
    assert [f["fonte"] for f in resumo["fontes"]] == ["cdi", "selic_meta"]

    assert local.main(["consultar", "ultimos_indicadores"]) == 0
    linhas = json.loads(capsys.readouterr().out)
    assert [r["serie"] for r in linhas] == ["cdi", "selic_meta"]
