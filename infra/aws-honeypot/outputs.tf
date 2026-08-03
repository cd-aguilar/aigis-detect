output "instance_id" {
  description = "ID de la instancia EC2 del honeypot — usado con `aws ssm start-session --target`."
  value       = aws_instance.cowrie.id
}

output "instance_public_ip" {
  description = "IP pública del honeypot — el destino real de los ataques."
  value       = aws_instance.cowrie.public_ip
}

output "s3_bucket_name" {
  description = "Bucket S3 donde Cowrie sube sus logs."
  value       = aws_s3_bucket.logs.bucket
}

output "puller_access_key_id" {
  description = "Access key del usuario IAM de solo lectura — completar HONEYPOT_AWS_ACCESS_KEY_ID en .env."
  value       = aws_iam_access_key.puller.id
  sensitive   = true
}

output "puller_secret_access_key" {
  description = "Secret key del usuario IAM de solo lectura — completar HONEYPOT_AWS_SECRET_ACCESS_KEY en .env."
  value       = aws_iam_access_key.puller.secret
  sensitive   = true
}
