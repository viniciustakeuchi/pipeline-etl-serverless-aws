resource "aws_sns_topic" "alertas" {
  name              = "${local.nome}-alertas"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.email_alertas == "" ? 0 : 1
  topic_arn = aws_sns_topic.alertas.arn
  protocol  = "email"
  endpoint  = var.email_alertas
}

locals {
  alarmes = {
    erro-extracao = {
      descricao   = "A Lambda de extração falhou (todas as fontes caíram ou erro inesperado)"
      namespace   = "AWS/Lambda"
      metrica     = "Errors"
      dimensoes   = { FunctionName = aws_lambda_function.extracao.function_name }
      estatistica = "Sum"
    }
    erro-transformacao = {
      descricao   = "A Lambda de transformação falhou (provável mudança de formato na fonte)"
      namespace   = "AWS/Lambda"
      metrica     = "Errors"
      dimensoes   = { FunctionName = aws_lambda_function.transformacao.function_name }
      estatistica = "Sum"
    }
    fonte-com-falha = {
      descricao   = "Ao menos uma fonte falhou na coleta, mesmo com a execução concluída"
      namespace   = "PipelineETL"
      metrica     = "FontesComFalha"
      dimensoes   = { Etapa = "extracao" }
      estatistica = "Maximum"
    }
    dlq-com-mensagens = {
      descricao   = "Há eventos na fila de erros esperando reprocessamento"
      namespace   = "AWS/SQS"
      metrica     = "ApproximateNumberOfMessagesVisible"
      dimensoes   = { QueueName = aws_sqs_queue.dlq.name }
      estatistica = "Maximum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "pipeline" {
  for_each = local.alarmes

  alarm_name          = "${local.nome}-${each.key}"
  alarm_description   = each.value.descricao
  namespace           = each.value.namespace
  metric_name         = each.value.metrica
  dimensions          = each.value.dimensoes
  statistic           = each.value.estatistica
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alertas.arn]
  ok_actions          = [aws_sns_topic.alertas.arn]
}
