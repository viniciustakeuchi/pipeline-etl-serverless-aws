terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Estado remoto no S3 criado por infra/bootstrap. O bucket vem na inicialização:
  #   terraform init -backend-config="bucket=<saída state_bucket do bootstrap>"
  backend "s3" {
    key          = "pipeline-etl/terraform.tfstate"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.regiao

  default_tags {
    tags = {
      Projeto     = var.projeto
      Gerenciado  = "terraform"
      Repositorio = "github.com/viniciustakeuchi/pipeline-etl-serverless-aws"
    }
  }
}

data "aws_caller_identity" "atual" {}
data "aws_region" "atual" {}

locals {
  conta  = data.aws_caller_identity.atual.account_id
  regiao = data.aws_region.atual.region
  nome   = var.projeto
}
