-- Último valor publicado de cada série.
-- Os snapshots diários se sobrepõem (cada coleta pede os últimos 10 dias ao Banco Central),
-- então cada data de referência fica com a versão do snapshot mais recente.
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
ranqueado AS (
    SELECT
        serie,
        data_referencia,
        valor,
        row_number() OVER (PARTITION BY serie ORDER BY data_referencia DESC) AS posicao
    FROM deduplicado
    WHERE versao = 1
)
SELECT serie, data_referencia, valor
FROM ranqueado
WHERE posicao = 1
ORDER BY serie
