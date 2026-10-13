-- Taxas e preços dos títulos do Tesouro Direto no snapshot mais recente.
-- Quando a coleta caiu para o CSV, o snapshot traz alguns dias; fica só o último.
WITH ultimo_snapshot AS (
    SELECT *
    FROM tesouro
    WHERE data_coleta = (SELECT max(data_coleta) FROM tesouro)
)
SELECT titulo, vencimento, taxa_compra, taxa_venda, pu_compra, pu_venda, data_base, origem
FROM ultimo_snapshot
WHERE data_base = (SELECT max(data_base) FROM ultimo_snapshot)
ORDER BY titulo, vencimento
