"""Registros -> Parquet com schema fixo.

O schema aqui é o mesmo declarado nas tabelas do Glue (infra/glue.tf). Decimal em vez de
float: taxa e preço unitário não podem ganhar ruído de ponto flutuante no caminho.
"""

import io
from datetime import datetime
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from etl.parsers import CotacaoTesouro, PontoIndicador

_CAMPOS_INDICADORES: "list[pa.Field[Any]]" = [
    pa.field("data_referencia", pa.date32(), nullable=False),
    pa.field("valor", pa.decimal128(18, 8), nullable=False),
    pa.field("ingerido_em", pa.timestamp("ms"), nullable=False),
]
SCHEMA_INDICADORES = pa.schema(_CAMPOS_INDICADORES)

_CAMPOS_TESOURO: "list[pa.Field[Any]]" = [
    pa.field("titulo", pa.string(), nullable=False),
    pa.field("vencimento", pa.date32(), nullable=False),
    pa.field("data_base", pa.date32(), nullable=False),
    pa.field("taxa_compra", pa.decimal128(9, 4)),
    pa.field("taxa_venda", pa.decimal128(9, 4)),
    pa.field("pu_compra", pa.decimal128(18, 6)),
    pa.field("pu_venda", pa.decimal128(18, 6)),
    pa.field("origem", pa.string(), nullable=False),
    pa.field("ingerido_em", pa.timestamp("ms"), nullable=False),
]
SCHEMA_TESOURO = pa.schema(_CAMPOS_TESOURO)


def _serializar(tabela: pa.Table) -> bytes:
    buffer = io.BytesIO()
    pq.write_table(tabela, buffer, compression="snappy")
    return buffer.getvalue()


def indicadores_para_parquet(pontos: list[PontoIndicador], ingerido_em: datetime) -> bytes:
    # Ordenado e sem repetição: a mesma data pode vir duas vezes se a fonte errar.
    unicos = {p.data_referencia: p for p in pontos}
    ordenados = [unicos[d] for d in sorted(unicos)]
    tabela = pa.table(
        {
            "data_referencia": [p.data_referencia for p in ordenados],
            "valor": [p.valor for p in ordenados],
            "ingerido_em": [ingerido_em] * len(ordenados),
        },
        schema=SCHEMA_INDICADORES,
    )
    return _serializar(tabela)


def tesouro_para_parquet(
    cotacoes: list[CotacaoTesouro], origem: str, ingerido_em: datetime
) -> bytes:
    unicas = {(c.titulo, c.vencimento, c.data_base): c for c in cotacoes}
    ordenadas = [unicas[k] for k in sorted(unicas)]
    tabela = pa.table(
        {
            "titulo": [c.titulo for c in ordenadas],
            "vencimento": [c.vencimento for c in ordenadas],
            "data_base": [c.data_base for c in ordenadas],
            "taxa_compra": [c.taxa_compra for c in ordenadas],
            "taxa_venda": [c.taxa_venda for c in ordenadas],
            "pu_compra": [c.pu_compra for c in ordenadas],
            "pu_venda": [c.pu_venda for c in ordenadas],
            "origem": [origem] * len(ordenadas),
            "ingerido_em": [ingerido_em] * len(ordenadas),
        },
        schema=SCHEMA_TESOURO,
    )
    return _serializar(tabela)
