import io
import json
import logging

from etl.observabilidade import FormatoJSON, configurar_logs, emitir_metricas


def test_formato_json_inclui_campos_extras_e_excecao() -> None:
    registro = logging.makeLogRecord(
        {"msg": "fonte_extraida", "levelname": "INFO", "name": "etl", "fonte": "cdi"}
    )
    dados = json.loads(FormatoJSON().format(registro))
    assert dados == {"nivel": "INFO", "evento": "fonte_extraida", "logger": "etl", "fonte": "cdi"}

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        registro = logging.makeLogRecord({"msg": "falha", "exc_info": sys.exc_info()})
    assert "RuntimeError: boom" in json.loads(FormatoJSON().format(registro))["excecao"]


def test_configurar_logs_troca_o_formato() -> None:
    raiz = logging.getLogger()
    antigos = raiz.handlers[:]
    nivel = raiz.level
    raiz.handlers = []
    try:
        configurar_logs("DEBUG")
        assert raiz.level == logging.DEBUG
        assert isinstance(raiz.handlers[0].formatter, FormatoJSON)
    finally:
        raiz.handlers = antigos
        raiz.setLevel(nivel)


def test_metricas_no_formato_emf() -> None:
    saida = io.StringIO()
    emitir_metricas(
        "PipelineETL",
        {"Etapa": "extracao"},
        {"FontesComFalha": (1, "Count"), "DuracaoExecucao": (12.5, "Milliseconds")},
        saida=saida,
    )
    documento = json.loads(saida.getvalue())
    definicao = documento["_aws"]["CloudWatchMetrics"][0]
    assert definicao["Namespace"] == "PipelineETL"
    assert definicao["Dimensions"] == [["Etapa"]]
    assert {"Name": "FontesComFalha", "Unit": "Count"} in definicao["Metrics"]
    assert documento["Etapa"] == "extracao"
    assert documento["FontesComFalha"] == 1
    assert documento["DuracaoExecucao"] == 12.5
