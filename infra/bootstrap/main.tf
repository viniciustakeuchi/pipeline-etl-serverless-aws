# Roda uma vez, com credenciais de administrador, antes do primeiro deploy:
#   cd infra/bootstrap && terraform init && terraform apply
# Cria o bucket do estado remoto e a role que o GitHub Actions assume via OIDC, sem
# nenhuma chave de acesso guardada no GitHub.

terraform {
  required_version = ">= 1.10"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

variable "regiao" {
  type    = string
  default = "sa-east-1"
}

variable "projeto" {
  type    = string
  default = "pipeline-etl"
}

variable "repositorio_github" {
  description = "Repositório autorizado a fazer deploy, no formato dono/nome."
  type        = string
  default     = "viniciustakeuchi/pipeline-etl-serverless-aws"
}

provider "aws" {
  region = var.regiao
  default_tags {
    tags = {
      Projeto    = var.projeto
      Gerenciado = "terraform-bootstrap"
    }
  }
}

data "aws_caller_identity" "atual" {}

locals {
  conta = data.aws_caller_identity.atual.account_id
}

# ------------------------------------------------------------------ estado remoto

resource "aws_s3_bucket" "estado" {
  bucket = "${var.projeto}-tfstate-${local.conta}"
}

resource "aws_s3_bucket_versioning" "estado" {
  bucket = aws_s3_bucket.estado.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "estado" {
  bucket = aws_s3_bucket.estado.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "estado" {
  bucket                  = aws_s3_bucket.estado.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ----------------------------------------------------------- GitHub Actions via OIDC

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "assume_github" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Só o ambiente "producao" do repositório (que só roda a partir da main) pode assumir.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.repositorio_github}:environment:producao"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "${var.projeto}-deploy-github"
  assume_role_policy   = data.aws_iam_policy_document.assume_github.json
  max_session_duration = 3600
}

# PowerUserAccess cobre os serviços do pipeline, mas não IAM. A política abaixo libera IAM
# apenas para roles com o prefixo do projeto, o que impede o deploy de escalar privilégio.
resource "aws_iam_role_policy_attachment" "deploy_poweruser" {
  role       = aws_iam_role.deploy.name
  policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

data "aws_iam_policy_document" "deploy_iam" {
  statement {
    sid = "RolesDoProjeto"
    actions = [
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:PassRole",
    ]
    resources = ["arn:aws:iam::${local.conta}:role/${var.projeto}-*"]
  }
  statement {
    sid       = "NaoAlteraARolePropria"
    effect    = "Deny"
    actions   = ["iam:*"]
    resources = [aws_iam_role.deploy.arn]
  }
}

resource "aws_iam_role_policy" "deploy_iam" {
  name   = "iam-somente-do-projeto"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy_iam.json
}

output "state_bucket" {
  description = "Use em: terraform init -backend-config=\"bucket=...\""
  value       = aws_s3_bucket.estado.id
}

output "role_deploy_arn" {
  description = "Cadastre como variável AWS_ROLE_ARN no ambiente producao do GitHub."
  value       = aws_iam_role.deploy.arn
}
