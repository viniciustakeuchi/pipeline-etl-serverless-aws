# Usado só no CI: copiado para infra/ como moto_override.tf, faz o Terraform aplicar a
# infraestrutura inteira contra o moto server (uma AWS simulada), sem conta nem custo.
# Prova que os recursos e as referências entre eles estão corretos, não só a sintaxe.

terraform {
  backend "local" {}
}

provider "aws" {
  access_key                  = "teste"
  secret_key                  = "teste"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = false
  s3_use_path_style           = true
  insecure                    = true # certificado autoassinado do moto

  endpoints {
    athena     = "https://localhost:5000"
    cloudwatch = "https://localhost:5000"
    glue       = "https://localhost:5000"
    iam        = "https://localhost:5000"
    lambda     = "https://localhost:5000"
    logs       = "https://localhost:5000"
    s3         = "https://localhost:5000"
    s3control  = "https://localhost:5000"
    scheduler  = "https://localhost:5000"
    sns        = "https://localhost:5000"
    sqs        = "https://localhost:5000"
    sts        = "https://localhost:5000"
  }
}

# O moto não preenche a condição aws:SecureTransport e acaba negando todo acesso ao bucket.
# Só no teste, a política troca por uma inofensiva; o recurso continua sendo criado.
resource "aws_s3_bucket_policy" "todos" {
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "SomenteTeste"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:DeleteBucketWebsite"
      Resource  = each.value.arn
    }]
  })
}

# O moto ainda não entende o protocolo JSON que o provider 6.x usa no PutMetricAlarm.
# Os alarmes ficam de fora do teste (o `terraform validate` do CI continua cobrindo-os).
resource "aws_cloudwatch_metric_alarm" "pipeline" {
  for_each = {}
}
