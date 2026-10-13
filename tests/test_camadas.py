from datetime import date

import pytest

from etl.camadas import ChaveInvalida, ChaveRaw, chave_processada


def test_chave_raw_ida_e_volta() -> None:
    chave = ChaveRaw("selic_meta", date(2026, 10, 13), "json")
    assert chave.chave == "raw/fonte=selic_meta/data_coleta=2026-10-13/selic_meta.json.gz"
    assert ChaveRaw.de_texto(chave.chave) == chave


def test_chave_raw_csv() -> None:
    chave = ChaveRaw.de_texto("raw/fonte=tesouro/data_coleta=2026-10-13/tesouro.csv.gz")
    assert chave.formato == "csv"


@pytest.mark.parametrize(
    "texto",
    [
        "raw/fonte=cdi/data_coleta=2026-10-13/selic.json.gz",
        "raw/fonte=cdi/data_coleta=13-10-2026/cdi.json.gz",
        "processed/indicadores/serie=cdi/data_coleta=2026-10-13/cdi.parquet",
        "raw/fonte=cdi/data_coleta=2026-10-13/cdi.xml.gz",
    ],
)
def test_rejeita_chaves_fora_do_padrao(texto: str) -> None:
    with pytest.raises(ChaveInvalida):
        ChaveRaw.de_texto(texto)


def test_chaves_processadas() -> None:
    dia = date(2026, 10, 13)
    assert (
        chave_processada("indicadores", "cdi", dia)
        == "processed/indicadores/serie=cdi/data_coleta=2026-10-13/cdi.parquet"
    )
    assert (
        chave_processada("tesouro", "tesouro", dia)
        == "processed/tesouro/data_coleta=2026-10-13/tesouro.parquet"
    )
    with pytest.raises(ValueError, match="Tabela"):
        chave_processada("outra", "x", dia)
