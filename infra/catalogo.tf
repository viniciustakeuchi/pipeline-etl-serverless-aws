# Tabelas do Glue para o Athena, com partition projection: as partições são calculadas a
# partir do padrão das chaves no S3, então não há crawler nem MSCK REPAIR a cada carga.
# O schema espelha etl/parquet.py.

locals {
  local_processado = "s3://${aws_s3_bucket.dados.id}/processed"
  projecao_data = {
    "projection.data_coleta.type"          = "date"
    "projection.data_coleta.format"        = "yyyy-MM-dd"
    "projection.data_coleta.range"         = "2025-01-01,NOW"
    "projection.data_coleta.interval"      = "1"
    "projection.data_coleta.interval.unit" = "DAYS"
  }
}

resource "aws_glue_catalog_database" "dados" {
  name        = replace("${local.nome}_dados", "-", "_")
  description = "Indicadores do Banco Central e taxas do Tesouro Direto"
}

resource "aws_glue_catalog_table" "indicadores" {
  name          = "indicadores"
  database_name = aws_glue_catalog_database.dados.name
  description   = "Um snapshot por série e dia de coleta. Use as consultas salvas para deduplicar."
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(local.projecao_data, {
    "classification"            = "parquet"
    "projection.enabled"        = "true"
    "projection.serie.type"     = "enum"
    "projection.serie.values"   = "cdi,selic,selic_meta,ipca"
    "storage.location.template" = "${local.local_processado}/indicadores/serie=$${serie}/data_coleta=$${data_coleta}/"
  })

  partition_keys {
    name = "serie"
    type = "string"
  }
  partition_keys {
    name = "data_coleta"
    type = "string"
  }

  storage_descriptor {
    location      = "${local.local_processado}/indicadores/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name    = "data_referencia"
      type    = "date"
      comment = "Dia (ou mês, no IPCA) a que o valor se refere"
    }
    columns {
      name    = "valor"
      type    = "decimal(18,8)"
      comment = "% ao dia (CDI, Selic), % ao ano (meta Selic) ou % ao mês (IPCA)"
    }
    columns {
      name = "ingerido_em"
      type = "timestamp"
    }
  }
}

resource "aws_glue_catalog_table" "tesouro" {
  name          = "tesouro"
  database_name = aws_glue_catalog_database.dados.name
  description   = "Taxas e preços dos títulos do Tesouro Direto, um snapshot por dia de coleta"
  table_type    = "EXTERNAL_TABLE"

  parameters = merge(local.projecao_data, {
    "classification"            = "parquet"
    "projection.enabled"        = "true"
    "storage.location.template" = "${local.local_processado}/tesouro/data_coleta=$${data_coleta}/"
  })

  partition_keys {
    name = "data_coleta"
    type = "string"
  }

  storage_descriptor {
    location      = "${local.local_processado}/tesouro/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name = "titulo"
      type = "string"
    }
    columns {
      name = "vencimento"
      type = "date"
    }
    columns {
      name = "data_base"
      type = "date"
    }
    columns {
      name    = "taxa_compra"
      type    = "decimal(9,4)"
      comment = "% ao ano; nulo quando o título não está à venda"
    }
    columns {
      name = "taxa_venda"
      type = "decimal(9,4)"
    }
    columns {
      name = "pu_compra"
      type = "decimal(18,6)"
    }
    columns {
      name = "pu_venda"
      type = "decimal(18,6)"
    }
    columns {
      name    = "origem"
      type    = "string"
      comment = "api (site do Tesouro) ou csv (dados abertos, contingência)"
    }
    columns {
      name = "ingerido_em"
      type = "timestamp"
    }
  }
}

# ------------------------------------------------------------------------- Athena

resource "aws_athena_workgroup" "pipeline" {
  name          = local.nome
  description   = "Consultas sobre a camada processed"
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.limite_bytes_por_consulta

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${aws_s3_bucket.apoio.id}/athena/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

# Os mesmos arquivos SQL rodam no DuckDB nos testes e no `docker compose up`.
resource "aws_athena_named_query" "consultas" {
  for_each = fileset("${path.module}/../sql", "*.sql")

  name      = trimsuffix(each.value, ".sql")
  workgroup = aws_athena_workgroup.pipeline.id
  database  = aws_glue_catalog_database.dados.name
  query     = file("${path.module}/../sql/${each.value}")
}
