"""Converte o conteúdo bruto de cada fonte em registros tipados.

Só biblioteca padrão: a extração também usa estes parsers para conferir a resposta da API do
Tesouro antes de decidir se precisa cair para o CSV.
Linhas malformadas são contadas e descartadas; formato irreconhecível levanta erro.
"""

import csv
import io
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

log = logging.getLogger(__name__)

PERCENTUAL = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*%")


class FormatoInesperado(Exception):
    """A fonte respondeu, mas num formato que o parser não reconhece."""


@dataclass(frozen=True)
class PontoIndicador:
    serie: str
    data_referencia: date
    valor: Decimal


@dataclass(frozen=True)
class CotacaoTesouro:
    titulo: str
    vencimento: date
    data_base: date
    taxa_compra: Decimal | None
    taxa_venda: Decimal | None
    pu_compra: Decimal | None
    pu_venda: Decimal | None


@dataclass
class Interpretacao[R]:
    registros: list[R]
    rejeitados: int


def decimal_br(texto: str) -> Decimal:
    """'1.234,56' ou '1234.56' -> Decimal."""
    texto = texto.strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    valor = Decimal(texto)
    if not valor.is_finite():
        raise InvalidOperation(texto)
    return valor


def _json(conteudo: bytes, fonte: str) -> Any:
    try:
        return json.loads(conteudo)
    except ValueError as erro:
        raise FormatoInesperado(f"{fonte}: conteúdo não é JSON") from erro


# ------------------------------------------------------------------------ SGS


def interpretar_sgs(serie: str, conteudo: bytes) -> Interpretacao[PontoIndicador]:
    """[{"data": "02/01/2025", "valor": "0.055131"}, ...]"""
    payload = _json(conteudo, serie)
    if not isinstance(payload, list):
        raise FormatoInesperado(f"{serie}: SGS devolveu {type(payload).__name__}, esperava lista")
    pontos: list[PontoIndicador] = []
    rejeitados = 0
    for item in payload:
        try:
            pontos.append(
                PontoIndicador(
                    serie,
                    datetime.strptime(item["data"], "%d/%m/%Y").date(),
                    decimal_br(str(item["valor"])),
                )
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            rejeitados += 1
            log.warning("item_rejeitado", extra={"fonte": serie, "item": str(item)[:200]})
    return Interpretacao(pontos, rejeitados)


# -------------------------------------------------------------------- Tesouro


def normalizar_titulo(nome: str) -> str:
    """'Tesouro IPCA+ 2035' -> 'Tesouro IPCA+'. O vencimento fica em coluna própria."""
    return re.sub(r"\s+\d{4}$", "", " ".join(nome.split()))


def taxa_do_texto(texto: str | None) -> Decimal | None:
    """'IPCA + 6,82%' -> 6.82; 'SELIC' -> None."""
    encontrado = PERCENTUAL.search(texto or "")
    return decimal_br(encontrado.group(1)) if encontrado else None


def _positivo(valor: Decimal | None) -> Decimal | None:
    """O Tesouro informa 0 quando o título não está à venda."""
    return valor if valor is not None and valor > 0 else None


def _decimal_json(valor: Any) -> Decimal | None:
    return None if valor is None else _positivo(decimal_br(str(valor)))


def interpretar_tesouro_json(conteudo: bytes) -> Interpretacao[CotacaoTesouro]:
    """JSON do site: {"TesouroLegado": [títulos...], "Tesouro24x7": [...]}"""
    payload = _json(conteudo, "tesouro")
    if not isinstance(payload, dict):
        raise FormatoInesperado("tesouro: JSON fora do formato esperado")
    itens = [i for v in payload.values() if isinstance(v, list) for i in v]
    if not any(isinstance(i, dict) and "treasuryBondName" in i for i in itens):
        raise FormatoInesperado(f"tesouro: JSON sem títulos, chaves {list(payload)[:5]}")

    cotacoes: list[CotacaoTesouro] = []
    rejeitados = 0
    for item in itens:
        try:
            cotacoes.append(
                CotacaoTesouro(
                    titulo=normalizar_titulo(item["treasuryBondName"]),
                    vencimento=datetime.fromisoformat(item["maturityDate"]).date(),
                    data_base=datetime.fromisoformat(item["lastMarketPricingDate"]).date(),
                    taxa_compra=taxa_do_texto(item.get("investmentProfitabilityIndexerName")),
                    taxa_venda=taxa_do_texto(item.get("redemptionProfitabilityFeeIndexerName")),
                    pu_compra=_decimal_json(item.get("unitaryInvestmentValue")),
                    pu_venda=_decimal_json(item.get("unitaryRedemptionValue")),
                )
            )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            rejeitados += 1
            log.warning("item_rejeitado", extra={"fonte": "tesouro", "item": str(item)[:200]})
    return Interpretacao(cotacoes, rejeitados)


COLUNAS_CSV = {
    "titulo": "Tipo Titulo",
    "vencimento": "Data Vencimento",
    "data_base": "Data Base",
    "taxa_compra": "Taxa Compra Manha",
    "taxa_venda": "Taxa Venda Manha",
    "pu_compra": "PU Compra Manha",
    "pu_venda": "PU Venda Manha",
}


def _decodificar(conteudo: bytes) -> str:
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("latin-1")


def _data_br(texto: str) -> date:
    return datetime.strptime(texto.strip(), "%d/%m/%Y").date()


def _decimal_csv(texto: str) -> Decimal | None:
    return _positivo(decimal_br(texto)) if texto.strip() else None


def interpretar_tesouro_csv(
    conteudo: bytes, desde: date | None = None, ate: date | None = None
) -> Interpretacao[CotacaoTesouro]:
    """CSV de dados abertos do Tesouro Transparente: histórico diário de todos os títulos.

    O arquivo tem anos de histórico; `desde`/`ate` recortam a janela da coleta.
    """
    leitor = csv.reader(io.StringIO(_decodificar(conteudo)), delimiter=";")
    cabecalho = [c.strip() for c in next(leitor, [])]
    try:
        posicao = {campo: cabecalho.index(coluna) for campo, coluna in COLUNAS_CSV.items()}
    except ValueError as erro:
        raise FormatoInesperado(f"tesouro: cabeçalho do CSV mudou: {cabecalho}") from erro

    cotacoes: list[CotacaoTesouro] = []
    rejeitados = 0
    for campos in leitor:
        if not any(c.strip() for c in campos):
            continue
        try:
            data_base = _data_br(campos[posicao["data_base"]])
            if (desde and data_base < desde) or (ate and data_base > ate):
                continue
            cotacoes.append(
                CotacaoTesouro(
                    titulo=" ".join(campos[posicao["titulo"]].split()),
                    vencimento=_data_br(campos[posicao["vencimento"]]),
                    data_base=data_base,
                    taxa_compra=_decimal_csv(campos[posicao["taxa_compra"]]),
                    taxa_venda=_decimal_csv(campos[posicao["taxa_venda"]]),
                    pu_compra=_decimal_csv(campos[posicao["pu_compra"]]),
                    pu_venda=_decimal_csv(campos[posicao["pu_venda"]]),
                )
            )
        except (IndexError, ValueError, InvalidOperation):
            rejeitados += 1
            log.warning("linha_rejeitada", extra={"fonte": "tesouro", "linha": str(campos)[:200]})
    return Interpretacao(cotacoes, rejeitados)
