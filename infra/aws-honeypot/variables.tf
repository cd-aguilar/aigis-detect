variable "aws_region" {
  description = "Región AWS donde vive el honeypot."
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "Tipo de instancia EC2 — t3.micro entra en free tier."
  type        = string
  default     = "t3.micro"
}

variable "project_name" {
  description = "Prefijo para nombrar los recursos (tags, bucket, etc.)."
  type        = string
  default     = "aigis-honeypot"
}

variable "budget_limit_usd" {
  description = "Umbral (USD/mes) de la alerta de presupuesto de este módulo."
  type        = number
  default     = 5
}

variable "alert_email" {
  description = "Email al que llega la alerta de presupuesto de AWS Budgets."
  type        = string
}

variable "log_retention_days" {
  description = "Días que se conservan los logs de Cowrie en S3 antes de expirar (lifecycle)."
  type        = number
  default     = 30
}
