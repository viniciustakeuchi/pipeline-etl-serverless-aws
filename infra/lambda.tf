locals {
  ambiente_comum = {
    BUCKET_DADOS       = aws_s3_bucket.dados.id
    NAMESPACE_METRICAS = "PipelineETL"
  }
}

# --------------------------------------------------------------------- layer pyarrow

# A layer passa de 30 MB, então sobe pelo S3 em vez de ir direto na API da Lambda.
resource "aws_s3_object" "layer_pyarrow" {
  bucket      = aws_s3_bucket.apoio.id
  key         = "pacotes/layer-pyarrow-${filemd5(var.pacote_layer)}.zip"
  source      = var.pacote_layer
  source_hash = filemd5(var.pacote_layer)
}

resource "aws_lambda_layer_version" "pyarrow" {
  layer_name               = "${local.nome}-pyarrow"
  description              = "pyarrow 21 para escrever Parquet"
  s3_bucket                = aws_s3_object.layer_pyarrow.bucket
  s3_key                   = aws_s3_object.layer_pyarrow.key
  source_code_hash         = filebase64sha256(var.pacote_layer)
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["arm64"]
}

# ----------------------------------------------------------------------- extração

resource "aws_cloudwatch_log_group" "extracao" {
  name              = "/aws/lambda/${local.nome}-extracao"
  retention_in_days = var.retencao_logs_dias
}

resource "aws_lambda_function" "extracao" {
  function_name    = "${local.nome}-extracao"
  description      = "Coleta Banco Central e Tesouro Direto e grava o bruto em raw/"
  role             = aws_iam_role.extracao.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "etl.extracao.handler"
  filename         = var.pacote_funcao
  source_code_hash = filebase64sha256(var.pacote_funcao)
  memory_size      = 256
  timeout          = 180

  environment {
    variables = local.ambiente_comum
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.extracao.name
  }
}

# ------------------------------------------------------------------ transformação

resource "aws_cloudwatch_log_group" "transformacao" {
  name              = "/aws/lambda/${local.nome}-transformacao"
  retention_in_days = var.retencao_logs_dias
}

resource "aws_lambda_function" "transformacao" {
  function_name    = "${local.nome}-transformacao"
  description      = "Valida o bruto de raw/ e grava Parquet em processed/"
  role             = aws_iam_role.transformacao.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "etl.transformacao.handler"
  filename         = var.pacote_funcao
  source_code_hash = filebase64sha256(var.pacote_funcao)
  layers           = [aws_lambda_layer_version.pyarrow.arn]
  memory_size      = 512
  timeout          = 60

  environment {
    variables = local.ambiente_comum
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.transformacao.name
  }
}

resource "aws_lambda_permission" "s3_invoca_transformacao" {
  statement_id   = "PermiteNotificacaoDoS3"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.transformacao.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.dados.arn
  source_account = local.conta
}

# ----------------------------------------------------- retry assíncrono e fila de erros

# As duas Lambdas são chamadas de forma assíncrona (Scheduler e S3). Depois de 2 novas
# tentativas o evento vai para a DLQ, de onde pode ser reprocessado.
resource "aws_lambda_function_event_invoke_config" "todas" {
  for_each = {
    extracao      = aws_lambda_function.extracao.function_name
    transformacao = aws_lambda_function.transformacao.function_name
  }

  function_name                = each.value
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600

  destination_config {
    on_failure {
      destination = aws_sqs_queue.dlq.arn
    }
  }
}

resource "aws_sqs_queue" "dlq" {
  name                      = "${local.nome}-dlq"
  message_retention_seconds = 1209600 # 14 dias, o máximo
  sqs_managed_sse_enabled   = true
}
