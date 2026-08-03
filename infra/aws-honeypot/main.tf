data "aws_availability_zones" "available" {
  state = "available"
}

# ── Red dedicada mínima — el honeypot no comparte VPC con nada más ────────

resource "aws_vpc" "honeypot" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name    = "${var.project_name}-vpc"
    Project = var.project_name
  }
}

resource "aws_internet_gateway" "honeypot" {
  vpc_id = aws_vpc.honeypot.id

  tags = {
    Name    = "${var.project_name}-igw"
    Project = var.project_name
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.honeypot.id
  cidr_block              = "10.42.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = {
    Name    = "${var.project_name}-public"
    Project = var.project_name
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.honeypot.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.honeypot.id
  }

  tags = {
    Name    = "${var.project_name}-public-rt"
    Project = var.project_name
  }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# ── Security group — 22/23 abiertos a internet a propósito (es el cebo) ───
# Sin regla de administración por SSH: el acceso admin va por SSM Session
# Manager (egress-only, no necesita ingress adicional).

resource "aws_security_group" "honeypot" {
  name        = "${var.project_name}-sg"
  description = "Cowrie honeypot - ports 22/23 intentionally open to internet"
  vpc_id      = aws_vpc.honeypot.id

  ingress {
    description = "SSH cebo (Cowrie)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "Telnet cebo (Cowrie)"
    from_port   = 23
    to_port     = 23
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Salida completa (S3, SSM, pulls de imagen Docker)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "${var.project_name}-sg"
    Project = var.project_name
  }
}

# ── S3 — destino de los logs de Cowrie, privado, expira a los N días ──────

resource "aws_s3_bucket" "logs" {
  bucket = "${var.project_name}-logs-${data.aws_caller_identity.current.account_id}"

  tags = {
    Name    = "${var.project_name}-logs"
    Project = var.project_name
  }
}

resource "aws_s3_bucket_public_access_block" "logs" {
  bucket = aws_s3_bucket.logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = var.log_retention_days
    }
  }
}

data "aws_caller_identity" "current" {}

# ── IAM: rol de la instancia EC2 — solo puede escribir en su prefix de S3
#    y usar SSM. Sin permisos de lectura ni de administración de más nada.

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${var.project_name}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "ec2_s3_put" {
  statement {
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.logs.arn}/cowrie/*"]
  }

  # `aws s3 sync` necesita listar el bucket (aunque sea scoped por prefix)
  # para saber qué objetos ya existen y no volver a subirlos — PutObject solo
  # no alcanza, sync falla con AccessDenied en la llamada a ListObjectsV2.
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.logs.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["cowrie/*"]
    }
  }
}

resource "aws_iam_role_policy" "ec2_s3_put" {
  name   = "${var.project_name}-ec2-s3-put"
  role   = aws_iam_role.ec2.id
  policy = data.aws_iam_policy_document.ec2_s3_put.json
}

resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2.name
}

# ── IAM: usuario "puller" de solo lectura — sus access keys las usa
#    scripts/pull_honeypot_logs.py desde el homelab (fuera de AWS).

resource "aws_iam_user" "puller" {
  name = "${var.project_name}-puller"
}

data "aws_iam_policy_document" "puller_read" {
  statement {
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.logs.arn]
  }

  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.logs.arn}/cowrie/*"]
  }
}

resource "aws_iam_user_policy" "puller_read" {
  name   = "${var.project_name}-puller-read"
  user   = aws_iam_user.puller.name
  policy = data.aws_iam_policy_document.puller_read.json
}

resource "aws_iam_access_key" "puller" {
  user = aws_iam_user.puller.name
}

# ── EC2: AMI Amazon Linux 2023 más reciente ────────────────────────────────
# Vía el parámetro SSM oficial de AWS, no un filtro por nombre: un filtro
# como "al2023-ami-*-x86_64" también matchea la variante ECS-optimized
# (trae un ecs-agent que arranca solo y compite por recursos) — se
# descubrió al ver un contenedor "ecs-agent" corriendo sin haberlo pedido.

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "cowrie" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.honeypot.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  user_data = templatefile("${path.module}/user_data.sh", {
    s3_bucket  = aws_s3_bucket.logs.bucket
    aws_region = var.aws_region
  })

  metadata_options {
    http_tokens = "required" # IMDSv2 obligatorio
  }

  tags = {
    Name    = "${var.project_name}-cowrie"
    Project = var.project_name
  }
}

# ── Alerta de costo — este módulo entero apunta a free tier + S3 casi gratis

resource "aws_budgets_budget" "honeypot" {
  name         = "${var.project_name}-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Sin cost_filter por tag: requeriría activar a mano el tag "Project" como
  # cost allocation tag en la consola de Billing (paso manual, fuera del
  # alcance de Terraform) antes de que AWS lo deje filtrar por él. Con un
  # límite bajo (default USD 5) sobre el costo total de la cuenta alcanza
  # para el propósito de esta alerta.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
