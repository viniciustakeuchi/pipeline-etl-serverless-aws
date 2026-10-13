import pytest

from etl.retry import Resultado, com_retry


class Transitorio(Exception):
    pass


def _operacao_que_falha(vezes: int, erro: Exception) -> tuple[list[int], object]:
    chamadas: list[int] = []

    def operacao() -> str:
        chamadas.append(1)
        if len(chamadas) <= vezes:
            raise erro
        return "ok"

    return chamadas, operacao


def test_repete_erros_transitorios_ate_dar_certo() -> None:
    chamadas, operacao = _operacao_que_falha(2, Transitorio())
    esperas: list[float] = []
    resultado: Resultado[str] = com_retry(
        operacao,  # type: ignore[arg-type]
        tentativas=4,
        backoff_inicial=1,
        repetir_se=lambda e: isinstance(e, Transitorio),
        contexto="teste",
        dormir=esperas.append,
    )
    assert (resultado.valor, resultado.tentativas) == ("ok", 3)
    assert len(esperas) == 2
    # Jitter "full": cada espera fica entre 0 e o teto exponencial (1s, depois 2s).
    assert 0 <= esperas[0] <= 1 and 0 <= esperas[1] <= 2


def test_erro_permanente_sobe_na_primeira() -> None:
    chamadas, operacao = _operacao_que_falha(5, ValueError("400"))
    with pytest.raises(ValueError):
        com_retry(
            operacao,  # type: ignore[arg-type]
            tentativas=4,
            backoff_inicial=0,
            repetir_se=lambda e: isinstance(e, Transitorio),
            contexto="teste",
            dormir=lambda _: None,
        )
    assert len(chamadas) == 1


def test_esgota_as_tentativas() -> None:
    chamadas, operacao = _operacao_que_falha(10, Transitorio())
    with pytest.raises(Transitorio):
        com_retry(
            operacao,  # type: ignore[arg-type]
            tentativas=3,
            backoff_inicial=0,
            repetir_se=lambda e: True,
            contexto="teste",
            dormir=lambda _: None,
        )
    assert len(chamadas) == 3


def test_espera_respeita_o_teto() -> None:
    _, operacao = _operacao_que_falha(10, Transitorio())
    esperas: list[float] = []
    with pytest.raises(Transitorio):
        com_retry(
            operacao,  # type: ignore[arg-type]
            tentativas=8,
            backoff_inicial=10,
            backoff_maximo=15,
            repetir_se=lambda e: True,
            contexto="teste",
            dormir=esperas.append,
        )
    assert max(esperas) <= 15
