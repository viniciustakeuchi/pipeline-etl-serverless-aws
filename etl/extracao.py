"""Lambda 1: coleta as fontes e grava o conteúdo bruto, sem alterar, na camada raw do S3.

Disparada pelo EventBridge Scheduler de segunda a sexta. O evento pode trazer
`{"data_coleta": "2026-10-10", "fontes": ["cdi"]}` para reprocessar um dia ou uma fonte.
"""

import gzip
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from etl.camadas import ChaveRaw
from etl.config import FUSO, Config, carregar
from etl.fontes import FONTES, Fonte, baixador
from etl.observabilidade import configurar_logs, emitir_metricas
from etl.s3 import S3Client, cliente

log = logging.getLogger(__name__)


class FalhaTotal(Exception):
    """Nenhuma fonte foi coletada: a Lambda falha para o retry e a DLQ entrarem em ação."""


@dataclass
class ResultadoFonte:
    fonte: str
    status: str  # ok | sem_dados | falha
    duracao_ms: int
    chave: str | None = None
    estrategia: str | None = None
    tentativas: int = 0
    bytes: int = 0
    erro: str | None = None


def _data_coleta(evento: dict[str, Any]) -> date:
    if evento.get("data_coleta"):
        return date.fromisoformat(evento["data_coleta"])
    return datetime.now(FUSO).date()


def _fontes(evento: dict[str, Any]) -> list[Fonte]:
    nomes = evento.get("fontes") or list(FONTES)
    desconhecidas = set(nomes) - set(FONTES)
    if desconhecidas:
        raise ValueError(f"Fontes desconhecidas: {sorted(desconhecidas)}")
    return [FONTES[n] for n in nomes]


def extrair_fonte(
    fonte: Fonte, data_coleta: date, cfg: Config, s3: S3Client, execucao: str
) -> ResultadoFonte:
    inicio = time.perf_counter()

    def decorrido() -> int:
        return int((time.perf_counter() - inicio) * 1000)

    try:
        download = baixador(fonte)(fonte, data_coleta, cfg)
        if download is None:
            log.info("sem_dados_na_janela", extra={"fonte": fonte.nome})
            return ResultadoFonte(fonte.nome, "sem_dados", decorrido())
        chave = ChaveRaw(fonte.nome, data_coleta, download.formato).chave
        s3.put_object(
            Bucket=cfg.bucket,
            Key=chave,
            Body=gzip.compress(download.conteudo),
            ContentType="application/gzip",
            Metadata={
                "estrategia": download.estrategia,
                "tentativas": str(download.tentativas),
                "execucao": execucao,
            },
        )
        resultado = ResultadoFonte(
            fonte.nome,
            "ok",
            decorrido(),
            chave=chave,
            estrategia=download.estrategia,
            tentativas=download.tentativas,
            bytes=len(download.conteudo),
        )
        log.info("fonte_extraida", extra=asdict(resultado))
        return resultado
    except Exception as erro:
        log.exception("falha_na_fonte", extra={"fonte": fonte.nome})
        return ResultadoFonte(fonte.nome, "falha", decorrido(), erro=repr(erro)[:500])


def executar(evento: dict[str, Any], cfg: Config, s3: S3Client, execucao: str) -> dict[str, Any]:
    data_coleta = _data_coleta(evento)
    fontes = _fontes(evento)
    inicio = time.perf_counter()
    # As fontes são independentes e a espera é toda de rede: threads bastam.
    with ThreadPoolExecutor(max_workers=len(fontes)) as executor:
        resultados = list(
            executor.map(lambda f: extrair_fonte(f, data_coleta, cfg, s3, execucao), fontes)
        )
    falhas = [r for r in resultados if r.status == "falha"]
    emitir_metricas(
        cfg.namespace_metricas,
        {"Etapa": "extracao"},
        {
            "FontesComSucesso": (sum(r.status != "falha" for r in resultados), "Count"),
            "FontesComFalha": (len(falhas), "Count"),
            "BytesExtraidos": (sum(r.bytes for r in resultados), "Bytes"),
            "DuracaoExecucao": ((time.perf_counter() - inicio) * 1000, "Milliseconds"),
        },
    )
    resumo = {
        "data_coleta": data_coleta.isoformat(),
        "fontes": [asdict(r) for r in resultados],
    }
    if falhas and len(falhas) == len(resultados):
        raise FalhaTotal(f"Todas as {len(falhas)} fontes falharam: {resumo}")
    return resumo


def handler(evento: dict[str, Any], contexto: Any) -> dict[str, Any]:
    configurar_logs()
    cfg = carregar()
    execucao = getattr(contexto, "aws_request_id", "local")
    return executar(evento or {}, cfg, cliente(cfg), execucao)
