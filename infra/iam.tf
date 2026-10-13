# Uma role por Lambda, cada uma só com o que usa: a extração não lê nada do bucket e a
# transformação não escreve em raw/.

data "aws_iam_policy_document" "assume_lambda" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "extracao" {
  statement {
    sid       = "GravaBruto"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.dados.arn}/raw/*"]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.extracao.arn}:*"]
  }
  statement {
    sid       = "EnviaFalhasParaDLQ"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

data "aws_iam_policy_document" "transformacao" {
  statement {
    sid       = "LeBruto"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.dados.arn}/raw/*"]
  }
  statement {
    sid       = "GravaParquet"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.dados.arn}/processed/*"]
  }
  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.transformacao.arn}:*"]
  }
  statement {
    sid       = "EnviaFalhasParaDLQ"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.dlq.arn]
  }
}

resource "aws_iam_role" "extracao" {
  name               = "${local.nome}-extracao"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

resource "aws_iam_role_policy" "extracao" {
  name   = "permissoes-minimas"
  role   = aws_iam_role.extracao.id
  policy = data.aws_iam_policy_document.extracao.json
}

resource "aws_iam_role" "transformacao" {
  name               = "${local.nome}-transformacao"
  assume_role_policy = data.aws_iam_policy_document.assume_lambda.json
}

resource "aws_iam_role_policy" "transformacao" {
  name   = "permissoes-minimas"
  role   = aws_iam_role.transformacao.id
  policy = data.aws_iam_policy_document.transformacao.json
}
