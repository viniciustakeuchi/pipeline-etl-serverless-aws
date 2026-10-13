# Bucket de dados: camada raw (bruto, versionado) e processed (Parquet para o Athena).
resource "aws_s3_bucket" "dados" {
  bucket = "${local.nome}-dados-${local.conta}"
}

# Bucket separado para resultados do Athena e para os pacotes de deploy: nada disso é dado
# do negócio, e cada um tem regra de expiração própria.
resource "aws_s3_bucket" "apoio" {
  bucket = "${local.nome}-apoio-${local.conta}"
}

locals {
  buckets = {
    dados = aws_s3_bucket.dados
    apoio = aws_s3_bucket.apoio
  }
}

resource "aws_s3_bucket_public_access_block" "todos" {
  for_each = local.buckets
  bucket   = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "todos" {
  for_each = local.buckets
  bucket   = each.value.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "todos" {
  for_each = local.buckets
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "somente_tls" {
  for_each = local.buckets

  statement {
    sid     = "NegaAcessoSemTLS"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      each.value.arn,
      "${each.value.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "todos" {
  for_each = local.buckets
  bucket   = each.value.id
  policy   = data.aws_iam_policy_document.somente_tls[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.todos]
}

# Versionamento só nos dados: reprocessar um dia sobrescreve o bruto, e a versão anterior
# continua disponível por 30 dias para auditoria.
resource "aws_s3_bucket_versioning" "dados" {
  bucket = aws_s3_bucket.dados.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "dados" {
  bucket = aws_s3_bucket.dados.id

  rule {
    id     = "versoes-antigas"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  depends_on = [aws_s3_bucket_versioning.dados]
}

resource "aws_s3_bucket_lifecycle_configuration" "apoio" {
  bucket = aws_s3_bucket.apoio.id

  rule {
    id     = "resultados-athena"
    status = "Enabled"
    filter {
      prefix = "athena/"
    }
    expiration {
      days = 7
    }
  }
}

# Cada arquivo novo na camada raw dispara a Lambda de transformação.
resource "aws_s3_bucket_notification" "raw" {
  bucket = aws_s3_bucket.dados.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.transformacao.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"
    filter_suffix       = ".gz"
  }

  depends_on = [aws_lambda_permission.s3_invoca_transformacao]
}
