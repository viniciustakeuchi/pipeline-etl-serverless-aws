"""Retry com backoff exponencial e jitter, sem dependências."""

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Resultado[T]:
    valor: T
    tentativas: int


def com_retry[T](
    operacao: Callable[[], T],
    *,
    tentativas: int,
    backoff_inicial: float,
    repetir_se: Callable[[BaseException], bool],
    contexto: str,
    dormir: Callable[[float], None] = time.sleep,
    backoff_maximo: float = 20.0,
) -> Resultado[T]:
    """Executa `operacao` até dar certo ou esgotar as tentativas.

    Só repete erros que `repetir_se` considera transitórios (timeout, 5xx, 429). Um 400
    ou um JSON fora do formato sobem na primeira vez: repetir não mudaria o resultado.
    A espera é exponencial com jitter "full" para não sincronizar várias Lambdas.
    """
    for tentativa in range(1, tentativas + 1):
        try:
            return Resultado(operacao(), tentativa)
        except Exception as erro:
            if tentativa == tentativas or not repetir_se(erro):
                raise
            teto = min(backoff_maximo, backoff_inicial * 2 ** (tentativa - 1))
            espera = random.uniform(0, teto)  # noqa: S311 (jitter, não criptografia)
            log.warning(
                "nova_tentativa",
                extra={
                    "contexto": contexto,
                    "tentativa": tentativa,
                    "espera_s": round(espera, 2),
                    "erro": repr(erro),
                },
            )
            dormir(espera)
    raise AssertionError("inalcançável")  # pragma: no cover
