output "bucket_dados" {
  value = aws_s3_bucket.dados.id
}

output "funcao_extracao" {
  value = aws_lambda_function.extracao.function_name
}

output "funcao_transformacao" {
  value = aws_lambda_function.transformacao.function_name
}

output "banco_glue" {
  value = aws_glue_catalog_database.dados.name
}

output "workgroup_athena" {
  value = aws_athena_workgroup.pipeline.name
}

output "fila_de_erros" {
  value = aws_sqs_queue.dlq.url
}
