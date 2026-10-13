# EventBridge Scheduler (e não uma regra do EventBridge): aceita fuso horário, então
# "19h de São Paulo" continua certo sem conversão para UTC.

data "aws_iam_policy_document" "assume_scheduler" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.conta]
    }
  }
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.extracao.arn]
  }
  statement {
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.nome}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.assume_scheduler.json
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "invoca-extracao"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "coleta_diaria" {
  name                         = "${local.nome}-coleta-diaria"
  description                  = "Dispara a extração nos dias úteis"
  schedule_expression          = var.agendamento
  schedule_expression_timezone = var.fuso_horario

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.extracao.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({})

    retry_policy {
      maximum_retry_attempts       = 3
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = aws_sqs_queue.dlq.arn
    }
  }
}
