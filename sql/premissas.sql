-- Premissas no formato da API de carteira de renda fixa:
-- CDI anualizado (252 dias úteis), meta Selic e IPCA acumulado em 12 meses.
WITH deduplicado AS (
    SELECT
        serie,
        data_referencia,
        valor,
        row_number() OVER (
            PARTITION BY serie, data_referencia ORDER BY data_coleta DESC
        ) AS versao
    FROM indicadores
),
historico AS (
    SELECT
        serie,
        valor,
        row_number() OVER (PARTITION BY serie ORDER BY data_referencia DESC) AS posicao
    FROM deduplicado
    WHERE versao = 1
)
SELECT
    round(
        (power(1 + max(CASE WHEN serie = 'cdi' AND posicao = 1 THEN valor END) / 100, 252) - 1)
        * 100,
        2
    ) AS cdi_anual,
    max(CASE WHEN serie = 'selic_meta' AND posicao = 1 THEN valor END) AS selic_meta,
    round(
        (exp(sum(CASE WHEN serie = 'ipca' AND posicao <= 12 THEN ln(1 + valor / 100) END)) - 1)
        * 100,
        2
    ) AS ipca_12m,
    count(CASE WHEN serie = 'ipca' AND posicao <= 12 THEN 1 END) AS meses_ipca
FROM historico
