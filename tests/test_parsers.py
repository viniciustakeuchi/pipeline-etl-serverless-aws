from datetime import date
from decimal import Decimal

import pytest

from etl.parsers import (
    FormatoInesperado,
    decimal_br,
    interpretar_sgs,
    interpretar_tesouro_csv,
    interpretar_tesouro_json,
    normalizar_titulo,
    taxa_do_texto,
)
from tests.conftest import fixture, json_bytes


class TestDecimal:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("1.234,56", "1234.56"),
            ("0,0598", "0.0598"),
            ("1234.56", "1234.56"),
            (" -0.11 ", "-0.11"),
        ],
    )
    def test_formatos_brasileiro_e_americano(self, texto: str, esperado: str) -> None:
        assert decimal_br(texto) == Decimal(esperado)

    @pytest.mark.parametrize("texto", ["NaN", "Infinity", "abc"])
    def test_rejeita_valores_nao_finitos_ou_invalidos(self, texto: str) -> None:
        with pytest.raises(ArithmeticError):
            decimal_br(texto)


class TestSGS:
    def test_le_a_serie_do_banco_central(self) -> None:
        resultado = interpretar_sgs("cdi", fixture("sgs_cdi.json"))
        assert resultado.rejeitados == 0
        assert len(resultado.registros) == 5
        primeiro = resultado.registros[0]
        assert (primeiro.serie, primeiro.data_referencia) == ("cdi", date(2025, 10, 1))
        assert primeiro.valor == Decimal("0.055131")

    def test_valor_negativo_do_ipca_e_valido(self) -> None:
        valores = {
            p.data_referencia: p.valor
            for p in interpretar_sgs("ipca", fixture("sgs_ipca.json")).registros
        }
        assert valores[date(2025, 8, 1)] == Decimal("-0.11")

    def test_descarta_e_conta_itens_malformados(self) -> None:
        conteudo = json_bytes(
            [
                {"data": "01/10/2025", "valor": "0.05"},
                {"data": "2025-10-02", "valor": "0.05"},
                {"data": "03/10/2025"},
                {"data": "06/10/2025", "valor": "NaN"},
                "lixo",
            ]
        )
        resultado = interpretar_sgs("cdi", conteudo)
        assert len(resultado.registros) == 1
        assert resultado.rejeitados == 4

    def test_resposta_que_nao_e_lista(self) -> None:
        with pytest.raises(FormatoInesperado, match="esperava lista"):
            interpretar_sgs("cdi", json_bytes({"erro": "limite"}))

    def test_resposta_que_nao_e_json(self) -> None:
        with pytest.raises(FormatoInesperado, match="não é JSON"):
            interpretar_sgs("cdi", b"<html>manutencao</html>")


class TestTesouroJSON:
    def test_le_todos_os_segmentos(self) -> None:
        resultado = interpretar_tesouro_json(fixture("tesouro_rentabilidade.json"))
        assert resultado.rejeitados == 0
        assert len(resultado.registros) == 9
        titulos = {c.titulo for c in resultado.registros}
        assert "Tesouro Selic" in titulos
        assert not any(t[-4:].isdigit() for t in titulos)

    def test_converte_taxas_datas_e_precos(self) -> None:
        cotacoes = interpretar_tesouro_json(fixture("tesouro_rentabilidade.json")).registros
        selic_2027 = next(
            c for c in cotacoes if c.titulo == "Tesouro Selic" and c.vencimento == date(2027, 3, 1)
        )
        assert selic_2027.data_base == date(2026, 10, 13)
        assert selic_2027.taxa_venda == Decimal("0.0218")
        assert selic_2027.taxa_compra is None  # "SELIC" sem percentual
        assert selic_2027.pu_compra is None  # 0 = não está à venda
        assert selic_2027.pu_venda == Decimal("20076.8")

    def test_item_sem_campo_obrigatorio_e_rejeitado(self) -> None:
        conteudo = json_bytes(
            {
                "TesouroLegado": [
                    {
                        "treasuryBondName": "Tesouro Prefixado 2031",
                        "maturityDate": "2031-01-01T00:00",
                        "lastMarketPricingDate": "2026-10-13T13:00:00",
                        "investmentProfitabilityIndexerName": "13,45%",
                        "unitaryInvestmentValue": 650.12,
                    },
                    {"treasuryBondName": "Tesouro Quebrado 2030"},
                ]
            }
        )
        resultado = interpretar_tesouro_json(conteudo)
        assert resultado.rejeitados == 1
        assert resultado.registros[0].taxa_compra == Decimal("13.45")
        assert resultado.registros[0].pu_venda is None

    @pytest.mark.parametrize("payload", [[1, 2], {"outra": "coisa"}, {"lista": [{"x": 1}]}])
    def test_estrutura_desconhecida(self, payload: object) -> None:
        with pytest.raises(FormatoInesperado):
            interpretar_tesouro_json(json_bytes(payload))

    @pytest.mark.parametrize(
        ("nome", "esperado"),
        [
            ("Tesouro IPCA+ 2035", "Tesouro IPCA+"),
            ("Tesouro  Renda+  Aposentadoria Extra 2049", "Tesouro Renda+ Aposentadoria Extra"),
            ("Tesouro Selic", "Tesouro Selic"),
        ],
    )
    def test_normaliza_nome_do_titulo(self, nome: str, esperado: str) -> None:
        assert normalizar_titulo(nome) == esperado

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("IPCA + 6,82%", Decimal("6.82")),
            ("13,45%", Decimal("13.45")),
            ("SELIC", None),
            (None, None),
        ],
    )
    def test_taxa_do_texto(self, texto: str | None, esperado: Decimal | None) -> None:
        assert taxa_do_texto(texto) == esperado


class TestTesouroCSV:
    def test_le_o_csv_de_dados_abertos(self) -> None:
        resultado = interpretar_tesouro_csv(fixture("tesouro_precos_taxas.csv"))
        assert resultado.registros
        ipca = next(c for c in resultado.registros if c.titulo == "Tesouro IPCA+")
        assert ipca.taxa_compra == Decimal("7.63")
        assert ipca.pu_venda == Decimal("2574.55")

    def test_campo_vazio_vira_nulo(self) -> None:
        cotacoes = interpretar_tesouro_csv(fixture("tesouro_precos_taxas.csv")).registros
        semestral = next(c for c in cotacoes if c.titulo == "Tesouro IPCA+ com Juros Semestrais")
        assert semestral.taxa_compra is None
        assert semestral.pu_compra is None

    def test_recorta_a_janela_de_datas(self) -> None:
        todas = interpretar_tesouro_csv(fixture("tesouro_precos_taxas.csv")).registros
        datas = sorted({c.data_base for c in todas})
        recorte = interpretar_tesouro_csv(
            fixture("tesouro_precos_taxas.csv"), desde=datas[-1], ate=datas[-1]
        ).registros
        assert recorte
        assert {c.data_base for c in recorte} == {datas[-1]}

    def test_aceita_latin1_e_linhas_em_branco(self) -> None:
        conteudo = (
            "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
            "PU Compra Manha;PU Venda Manha\n"
            "Tesouro Educa+;15/12/2030;06/10/2025;7,1;7,2;3000,00;2990,00\n"
            ";;;;;;\n"
            "Tesouro Pré-fixado quebrado;xx;06/10/2025;1;1;1;1\n"
        ).encode("latin-1")
        resultado = interpretar_tesouro_csv(conteudo)
        assert [c.titulo for c in resultado.registros] == ["Tesouro Educa+"]
        assert resultado.rejeitados == 1

    def test_cabecalho_mudou(self) -> None:
        with pytest.raises(FormatoInesperado, match="cabeçalho"):
            interpretar_tesouro_csv(b"Titulo;Vencimento\nX;01/01/2030\n")
