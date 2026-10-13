"""Catálogo das fontes e o download do conteúdo bruto de cada uma."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial
from typing import Literal
from urllib.parse import urlencode

from etl.camadas import Formato
from etl.config import Config
from etl.http import Resposta, baixar, erro_transitorio
from etl.parsers import FormatoInesperado, interpretar_tesouro_json
from etl.retry import com_retry

log = logging.getLogger(__name__)

Tabela = Literal["indicadores", "tesouro"]


@dataclass(frozen=True)
class Fonte:
    nome: str
    tabela: Tabela
    descricao: str
    janela_dias: int
    codigo_sgs: int | None = None


FONTES: dict[str, Fonte] = {
    f.nome: f
    for f in (
        Fonte("cdi", "indicadores", "CDI diário (% ao dia), SGS 12", 10, 12),
        Fonte("selic", "indicadores", "Selic diária (% ao dia), SGS 11", 10, 11),
        Fonte("selic_meta", "indicadores", "Meta Selic do Copom (% ao ano), SGS 432", 10, 432),
        # Série mensal: 400 dias cobrem os 12 meses do IPCA acumulado.
        Fonte("ipca", "indicadores", "IPCA mensal (% ao mês), SGS 433", 400, 433),
        Fonte("tesouro", "tesouro", "Taxas e preços dos títulos do Tesouro Direto", 5),
    )
}


@dataclass(frozen=True)
class Download:
    conteudo: bytes
    formato: Formato
    estrategia: str
    tentativas: int


def janela(fonte: Fonte, data_coleta: date) -> tuple[date, date]:
    return data_coleta - timedelta(days=fonte.janela_dias), data_coleta


def _get(
    cfg: Config, url: str, contexto: str, aceitar: frozenset[int] = frozenset()
) -> tuple[Resposta, int]:
    resultado = com_retry(
        partial(baixar, url, cfg.timeout_segundos, aceitar),
        tentativas=cfg.tentativas,
        backoff_inicial=cfg.backoff_inicial_segundos,
        repetir_se=erro_transitorio,
        contexto=contexto,
    )
    return resultado.valor, resultado.tentativas


def baixar_sgs(fonte: Fonte, data_coleta: date, cfg: Config) -> Download | None:
    """Uma consulta à API do SGS. Devolve None quando não há dado na janela (HTTP 404)."""
    desde, ate = janela(fonte, data_coleta)
    parametros = urlencode(
        {
            "formato": "json",
            "dataInicial": desde.strftime("%d/%m/%Y"),
            "dataFinal": ate.strftime("%d/%m/%Y"),
        }
    )
    url = f"{cfg.sgs_url_base}/bcdata.sgs.{fonte.codigo_sgs}/dados?{parametros}"
    resposta, tentativas = _get(cfg, url, fonte.nome, aceitar=frozenset({404}))
    if resposta.status == 404 or resposta.corpo.strip() in (b"", b"[]"):
        return None
    return Download(resposta.corpo, "json", "api", tentativas)


def baixar_tesouro(fonte: Fonte, data_coleta: date, cfg: Config) -> Download:
    """JSON do site do Tesouro Direto; se falhar, o CSV de dados abertos.

    A resposta da API passa pelo parser antes de ser aceita: um 200 com HTML de bloqueio
    ou com a estrutura mudada também aciona a contingência.
    """
    tentativas = 0
    try:
        resposta, tentativas = _get(cfg, cfg.tesouro_url_api, "tesouro_api")
        if not interpretar_tesouro_json(resposta.corpo).registros:
            raise FormatoInesperado("tesouro: API respondeu sem nenhum título válido")
        return Download(resposta.corpo, "json", "api", tentativas)
    except Exception as erro:
        log.warning("tesouro_contingencia_csv", extra={"erro": repr(erro)})
    resposta, tentativas_csv = _get(cfg, cfg.tesouro_url_csv, "tesouro_csv")
    return Download(resposta.corpo, "csv", "csv", tentativas + tentativas_csv)


def baixador(fonte: Fonte) -> Callable[[Fonte, date, Config], Download | None]:
    return baixar_tesouro if fonte.tabela == "tesouro" else baixar_sgs
