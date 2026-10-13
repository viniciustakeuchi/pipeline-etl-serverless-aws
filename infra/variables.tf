variable "regiao" {
  description = "Região AWS. São Paulo deixa os dados perto da origem (Banco Central e Tesouro)."
  type        = string
  default     = "sa-east-1"
}

variable "projeto" {
  description = "Prefixo dos nomes de todos os recursos."
  type        = string
  default     = "pipeline-etl"
}

variable "agendamento" {
  description = "Quando a extração roda, no fuso abaixo. Padrão: dias úteis às 19h, após o fechamento."
  type        = string
  default     = "cron(0 19 ? * MON-FRI *)"
}

variable "fuso_horario" {
  type    = string
  default = "America/Sao_Paulo"
}

variable "email_alertas" {
  description = "E-mail que recebe os alarmes. Vazio: os alarmes existem, mas sem assinatura."
  type        = string
  default     = ""
}

variable "retencao_logs_dias" {
  type    = number
  default = 14
}

variable "limite_bytes_por_consulta" {
  description = "Teto de dados lidos por consulta no Athena (protege o custo). Mínimo da AWS: 10 MB."
  type        = number
  default     = 104857600 # 100 MB
}

variable "pacote_funcao" {
  description = "Zip com o código das Lambdas, gerado por scripts/empacotar.py."
  type        = string
  default     = "../build/funcao.zip"
}

variable "pacote_layer" {
  description = "Zip da layer com pyarrow, gerado por scripts/empacotar.py."
  type        = string
  default     = "../build/layer-pyarrow.zip"
}
