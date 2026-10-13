import gzip
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from etl import transformacao
from etl.camadas import ChaveInvalida
from etl.config import Config
from etl.local import evento_s3
from etl.parquet import SCHEMA_INDICADORES, SCHEMA_TESOURO
from etl.parsers import FormatoInesperado
from etl.s3 import S3Client
from tests.conftest import BUCKET, fixture, json_bytes

AGORA = datetime(2026, 10, 13, 22, 0, 0)


def _gravar_raw(s3: S3Client, chave: str, conteudo: bytes) -> str:
    s3.put_object(Bucket=BUCKET, Key=chave, Body=gzip.compress(conteudo))
    return chave


def _ler_parquet(ler_objeto: Callable[[str], bytes], chave: str) -> pa.Table:
    return pq.read_table(pa.BufferReader(ler_objeto(chave)))


def test_indicador_vira_parquet_com_schema_fixo(
    cfg: Config, s3: S3Client, ler_objeto: Callable[[str], bytes]
) -> None:
    chave = _gravar_raw(
        s3, "raw/fonte=cdi/data_coleta=2025-10-08/cdi.json.gz", fixture("sgs_cdi.json")
    )

    resultado = transformacao.transformar(chave, cfg, s3, agora=AGORA)

    assert resultado.destino == "processed/indicadores/serie=cdi/data_coleta=2025-10-08/cdi.parquet"
    assert (resultado.registros, resultado.rejeitados) == (5, 0)
    tabela = _ler_parquet(ler_objeto, resultado.destino)
    assert tabela.schema.equals(SCHEMA_INDICADORES)
    linhas = tabela.to_pylist()
    assert linhas[0] == {
        "data_referencia": date(2025, 10, 1),
        "valor": Decimal("0.05513100"),
        "ingerido_em": AGORA,
    }
    assert s3.head_object(Bucket=BUCKET, Key=resultado.destino)["Metadata"] == {"origem": chave}


def test_datas_repetidas_sao_deduplicadas(
    cfg: Config, s3: S3Client, ler_objeto: Callable[[str], bytes]
) -> None:
    conteudo = json_bytes(
        [
            {"data": "02/10/2025", "valor": "0.05"},
            {"data": "01/10/2025", "valor": "0.04"},
            {"data": "02/10/2025", "valor": "0.06"},
        ]
    )
    chave = _gravar_raw(s3, "raw/fonte=selic/data_coleta=2025-10-08/selic.json.gz", conteudo)
    destino = transformacao.transformar(chave, cfg, s3).destino
    assert destino
    linhas = _ler_parquet(ler_objeto, destino).to_pylist()
    assert [(r["data_referencia"].day, r["valor"]) for r in linhas] == [
        (1, Decimal("0.04000000")),
        (2, Decimal("0.06000000")),
    ]


def test_tesouro_json_vira_parquet(
    cfg: Config, s3: S3Client, ler_objeto: Callable[[str], bytes]
) -> None:
    chave = _gravar_raw(
        s3,
        "raw/fonte=tesouro/data_coleta=2026-10-13/tesouro.json.gz",
        fixture("tesouro_rentabilidade.json"),
    )
    resultado = transformacao.transformar(chave, cfg, s3, agora=AGORA)
    assert resultado.destino == "processed/tesouro/data_coleta=2026-10-13/tesouro.parquet"
    tabela = _ler_parquet(ler_objeto, resultado.destino)
    assert tabela.schema.equals(SCHEMA_TESOURO)
    assert tabela.num_rows == 9
    assert set(tabela.column("origem").to_pylist()) == {"api"}


def test_tesouro_csv_guarda_so_a_janela_da_coleta(
    cfg: Config, s3: S3Client, ler_objeto: Callable[[str], bytes]
) -> None:
    antigo = b"Tesouro Prefixado;01/01/2020;02/01/2019;9,10;9,22;700,00;699,00;699,00\n"
    chave = _gravar_raw(
        s3,
        "raw/fonte=tesouro/data_coleta=2025-10-08/tesouro.csv.gz",
        fixture("tesouro_precos_taxas.csv") + antigo,
    )
    resultado = transformacao.transformar(chave, cfg, s3)
    assert resultado.destino
    tabela = _ler_parquet(ler_objeto, resultado.destino)
    # A linha de 2019 fica de fora; os dias dentro da janela de 5 dias ficam.
    assert set(tabela.column("data_base").to_pylist()) == {date(2025, 10, 6), date(2025, 10, 7)}
    assert set(tabela.column("origem").to_pylist()) == {"csv"}


def test_arquivo_vazio_nao_gera_parquet(cfg: Config, s3: S3Client) -> None:
    chave = _gravar_raw(s3, "raw/fonte=cdi/data_coleta=2025-10-11/cdi.json.gz", b"[]")
    resultado = transformacao.transformar(chave, cfg, s3)
    assert resultado.destino is None
    assert s3.list_objects_v2(Bucket=BUCKET, Prefix="processed/")["KeyCount"] == 0


def test_arquivo_todo_rejeitado_falha_para_ir_a_dlq(cfg: Config, s3: S3Client) -> None:
    chave = _gravar_raw(
        s3,
        "raw/fonte=cdi/data_coleta=2025-10-11/cdi.json.gz",
        json_bytes([{"date": "2025-10-01", "value": 1}]),
    )
    with pytest.raises(FormatoInesperado, match="todas as 1 linhas"):
        transformacao.transformar(chave, cfg, s3)


def test_chave_fora_do_padrao_ou_fonte_sem_transformacao(cfg: Config, s3: S3Client) -> None:
    with pytest.raises(ChaveInvalida):
        transformacao.transformar("raw/outra/coisa.json", cfg, s3)
    chave = _gravar_raw(s3, "raw/fonte=dolar/data_coleta=2025-10-11/dolar.json.gz", b"[]")
    with pytest.raises(FormatoInesperado, match="dolar"):
        transformacao.transformar(chave, cfg, s3)


def test_handler_decodifica_a_chave_do_evento_do_s3(
    cfg: Config, s3: S3Client, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("BUCKET_DADOS", BUCKET)
    _gravar_raw(s3, "raw/fonte=cdi/data_coleta=2025-10-08/cdi.json.gz", fixture("sgs_cdi.json"))
    # O S3 entrega a chave codificada como em URL.
    evento = evento_s3(BUCKET, ["raw/fonte%3Dcdi/data_coleta%3D2025-10-08/cdi.json.gz"])

    resposta = transformacao.handler(evento, None)

    assert resposta["arquivos"][0]["registros"] == 5
    assert '"RegistrosGravados": 5' in capsys.readouterr().out


def test_evento_repetido_e_idempotente(
    cfg: Config, s3: S3Client, ler_objeto: Callable[[str], bytes]
) -> None:
    chave = _gravar_raw(
        s3, "raw/fonte=cdi/data_coleta=2025-10-08/cdi.json.gz", fixture("sgs_cdi.json")
    )
    evento = evento_s3(BUCKET, [chave])
    transformacao.executar(evento, cfg, s3)
    transformacao.executar(evento, cfg, s3)
    processados = s3.list_objects_v2(Bucket=BUCKET, Prefix="processed/")
    assert processados["KeyCount"] == 1
    assert _ler_parquet(ler_objeto, processados["Contents"][0]["Key"]).num_rows == 5
