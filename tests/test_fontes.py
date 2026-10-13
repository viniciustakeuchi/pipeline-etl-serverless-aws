from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from etl.config import Config
from etl.fontes import FONTES, baixador, baixar_sgs, baixar_tesouro, janela
from etl.http import ErroHTTP, Resposta
from tests.conftest import HTTPFalso, fixture, ok

DIA = date(2026, 10, 13)


def test_catalogo_cobre_as_cinco_fontes() -> None:
    assert set(FONTES) == {"cdi", "selic", "selic_meta", "ipca", "tesouro"}
    assert baixador(FONTES["tesouro"]) is baixar_tesouro
    assert baixador(FONTES["cdi"]) is baixar_sgs


def test_janela_do_ipca_cobre_doze_meses() -> None:
    desde, ate = janela(FONTES["ipca"], DIA)
    assert ate == DIA
    assert (ate - desde).days >= 365


def test_sgs_monta_a_consulta_com_a_janela(http: HTTPFalso, cfg: Config) -> None:
    http.rotas["bcdata.sgs.12/"] = ok(fixture("sgs_cdi.json"))
    download = baixar_sgs(FONTES["cdi"], DIA, cfg)
    assert download is not None
    assert (download.formato, download.estrategia, download.tentativas) == ("json", "api", 1)
    url = urlsplit(http.chamadas[0])
    assert url.path.endswith("/bcdata.sgs.12/dados")
    assert parse_qs(url.query) == {
        "formato": ["json"],
        "dataInicial": ["03/10/2026"],
        "dataFinal": ["13/10/2026"],
    }


@pytest.mark.parametrize("resposta", [Resposta(404, b"", ""), ok(b"[]"), ok(b"  ")])
def test_sgs_sem_dados_na_janela(http: HTTPFalso, cfg: Config, resposta: Resposta) -> None:
    http.rotas["bcdata.sgs.12/"] = resposta
    assert baixar_sgs(FONTES["cdi"], DIA, cfg) is None


def test_sgs_repete_erro_transitorio(http: HTTPFalso, cfg: Config) -> None:
    http.rotas["bcdata.sgs.12/"] = [ErroHTTP(503, "u"), ok(fixture("sgs_cdi.json"))]
    download = baixar_sgs(FONTES["cdi"], DIA, cfg)
    assert download is not None and download.tentativas == 2


def test_tesouro_pela_api(http: HTTPFalso, cfg: Config) -> None:
    http.rotas["rentabilidade"] = ok(fixture("tesouro_rentabilidade.json"))
    download = baixar_tesouro(FONTES["tesouro"], DIA, cfg)
    assert (download.formato, download.estrategia) == ("json", "api")
    assert len(http.chamadas) == 1


@pytest.mark.parametrize(
    "falha_da_api",
    [
        [ErroHTTP(503, "u")] * 3,  # esgota o retry
        [ErroHTTP(410, "u")],  # API antiga desativada: não repete
        [ok(b"<html>Access denied</html>", "text/html")],  # 200 com bloqueio
        [ok(b'{"TesouroLegado": []}')],  # estrutura certa, nenhum título
        [ok(b'{"TesouroLegado": [{"treasuryBondName": "X 2030"}]}')],  # todos rejeitados
    ],
)
def test_tesouro_cai_para_o_csv(
    http: HTTPFalso, cfg: Config, falha_da_api: list[Resposta | Exception]
) -> None:
    http.rotas["rentabilidade"] = list(falha_da_api)
    http.rotas["PrecoTaxa"] = ok(fixture("tesouro_precos_taxas.csv"), "text/csv")
    download = baixar_tesouro(FONTES["tesouro"], DIA, cfg)
    assert (download.formato, download.estrategia) == ("csv", "csv")
    assert download.conteudo == fixture("tesouro_precos_taxas.csv")


def test_tesouro_falha_quando_as_duas_camadas_falham(http: HTTPFalso, cfg: Config) -> None:
    http.rotas["rentabilidade"] = ErroHTTP(403, "u")
    http.rotas["PrecoTaxa"] = ErroHTTP(404, "u")
    with pytest.raises(ErroHTTP):
        baixar_tesouro(FONTES["tesouro"], DIA, cfg)
