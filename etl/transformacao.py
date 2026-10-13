"""Lambda 2: lê um arquivo da camada raw, valida e grava Parquet na camada processed.

Disparada por notificação do S3 (ObjectCreated em `raw/`). Cada arquivo bruto gera
exatamente um Parquet com chave derivada da sua, então um evento repetido sobrescreve o
mesmo arquivo: a transformação é idempotente.
"""

import gzip
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote_plus

from etl.camadas import ChaveRaw, chave_processada
from etl.config import Config, carregar
from etl.fontes import FONTES, janela
from etl.observabilidade import configurar_logs, emitir_metricas
from etl.parquet import indicadores_para_parquet, tesouro_para_parquet
from etl.parsers import (
    FormatoInesperado,
    interpretar_sgs,
    interpretar_tesouro_csv,
    interpretar_tesouro_json,
)
from etl.s3 import S3Client, cliente

log = logging.getLogger(__name__)


@dataclass
class ResultadoTransformacao:
    origem: str
    destino: str | None
    registros: int
    rejeitados: int


def transformar(
    chave: str, cfg: Config, s3: S3Client, agora: datetime | None = None
) -> ResultadoTransformacao:
    raw = ChaveRaw.de_texto(chave)
    fonte = FONTES.get(raw.fonte)
    if fonte is None:
        raise FormatoInesperado(f"Fonte sem transformação definida: {raw.fonte}")
    ingerido_em = (agora or datetime.now(UTC)).replace(tzinfo=None)

    objeto = s3.get_object(Bucket=cfg.bucket, Key=chave)
    conteudo = gzip.decompress(objeto["Body"].read())

    if fonte.tabela == "indicadores":
        pontos = interpretar_sgs(fonte.nome, conteudo)
        registros, rejeitados = len(pontos.registros), pontos.rejeitados
        parquet = indicadores_para_parquet(pontos.registros, ingerido_em)
    elif raw.formato == "json":
        cotacoes = interpretar_tesouro_json(conteudo)
        registros, rejeitados = len(cotacoes.registros), cotacoes.rejeitados
        parquet = tesouro_para_parquet(cotacoes.registros, "api", ingerido_em)
    else:
        # O CSV traz anos de histórico; o snapshot do dia guarda só a janela da fonte.
        desde, ate = janela(fonte, raw.data_coleta)
        cotacoes = interpretar_tesouro_csv(conteudo, desde, ate)
        registros, rejeitados = len(cotacoes.registros), cotacoes.rejeitados
        parquet = tesouro_para_parquet(cotacoes.registros, "csv", ingerido_em)

    if registros == 0:
        # Arquivo inteiro rejeitado é sinal de formato novo: falhar leva o evento à DLQ.
        if rejeitados:
            raise FormatoInesperado(f"{chave}: todas as {rejeitados} linhas foram rejeitadas")
        log.info("arquivo_sem_registros", extra={"origem": chave})
        return ResultadoTransformacao(chave, None, 0, 0)

    destino = chave_processada(fonte.tabela, fonte.nome, raw.data_coleta)
    s3.put_object(
        Bucket=cfg.bucket,
        Key=destino,
        Body=parquet,
        ContentType="application/vnd.apache.parquet",
        Metadata={"origem": chave},
    )
    resultado = ResultadoTransformacao(chave, destino, registros, rejeitados)
    log.info("arquivo_transformado", extra=asdict(resultado))
    return resultado


def chaves_do_evento(evento: dict[str, Any]) -> list[str]:
    """Chaves de uma notificação do S3. Elas chegam codificadas: 'data_coleta%3D...'."""
    return [unquote_plus(r["s3"]["object"]["key"]) for r in evento.get("Records", [])]


def executar(evento: dict[str, Any], cfg: Config, s3: S3Client) -> dict[str, Any]:
    resultados = [transformar(chave, cfg, s3) for chave in chaves_do_evento(evento)]
    emitir_metricas(
        cfg.namespace_metricas,
        {"Etapa": "transformacao"},
        {
            "RegistrosGravados": (sum(r.registros for r in resultados), "Count"),
            "RegistrosRejeitados": (sum(r.rejeitados for r in resultados), "Count"),
        },
    )
    return {"arquivos": [asdict(r) for r in resultados]}


def handler(evento: dict[str, Any], contexto: Any) -> dict[str, Any]:
    configurar_logs()
    cfg = carregar()
    return executar(evento, cfg, cliente(cfg))
