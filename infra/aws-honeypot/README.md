# Fase 3 — Honeypot Cowrie en AWS

Módulo standalone: expone un honeypot SSH/Telnet ([Cowrie](https://github.com/cowrie/cowrie))
a internet en una instancia EC2 free tier, para generar datos de ataque
reales (no sintéticos) que alimentan el mismo homelab de detección. No está
integrado al pipeline de triage IA/n8n todavía — solo manda logs a
Elasticsearch vía el mismo Filebeat que ya usa el resto del proyecto.

## Arquitectura

```
Internet ──(scans/ataques reales, puerto 22/23)──▶ EC2 t3.micro (Cowrie, Docker)
                                                         │ cron cada 1 min
                                                         ▼
                                                   S3 bucket (logs JSON)
                                                         │ IAM user de solo lectura
                                                         ▼ (polling cada 1-5 min)
                                          scripts/pull_honeypot_logs.py (host)
                                                         │
                                                         ▼
                                          Filebeat (input cowrie) ──▶ Elasticsearch
                                                                      índice cowrie-alerts-*
```

## Por qué así

- **S3 + polling, no Elasticsearch expuesto a internet.** El
  `docker-compose.yml` del homelab corre con `xpack.security.enabled: "false"`
  y Elasticsearch solo escucha en `127.0.0.1`. Exponerlo a internet con
  auth+VPN es mucho más superficie de cambio/ataque sobre el homelab real.
  S3 + polling deja el homelab 100% cerrado hacia afuera (cero puertos
  nuevos en casa), al costo de un delay de 1-5 min — aceptable acá.
- **Cowrie, no T-Pot.** Más liviano, entra en free tier, logs JSON fáciles
  de mapear a MITRE con el mismo patrón que el resto del proyecto.
- **Acceso admin vía AWS SSM Session Manager, no SSH real.** El puerto 22
  queda 100% dedicado a ser el cebo de Cowrie — sin un SSH "de verdad"
  escondido en otro puerto.
- **Sin credenciales AWS estáticas en el honeypot.** El EC2 usa un IAM
  instance role (`s3:PutObject` scoped a su prefix). Si el honeypot es
  comprometido de verdad — posible, es su propósito — no hay credenciales de
  larga vida que robar.
- **IAM user "puller" de solo lectura**, scoped a `GetObject`/`ListBucket` en
  ese bucket. Sus access keys viven en `.env` local (gitignored), mismo
  patrón que `THEHIVE_API_KEY`/`TELEGRAM_BOT_TOKEN`.
- **Sin NAT Gateway**: el EC2 va en subnet pública con IP propia + Internet
  Gateway (ahorra ~USD 32/mes); SSM funciona igual vía el IGW.

## Requisitos previos

- Credenciales AWS configuradas localmente (`aws configure` o variables de
  entorno) — fuera del alcance de Terraform.
- Terraform >= 1.9.

## Uso

```bash
cd infra/aws-honeypot
terraform init
terraform plan -var="alert_email=tu-email@ejemplo.com"
terraform apply -var="alert_email=tu-email@ejemplo.com"
```

O crear un `terraform.tfvars` (nunca commitear si tiene secretos) con:

```hcl
alert_email = "tu-email@ejemplo.com"
```

Al terminar, completar en `.env` (raíz del proyecto) con los outputs:

```bash
terraform output s3_bucket_name
terraform output -raw puller_access_key_id
terraform output -raw puller_secret_access_key
```

→ `HONEYPOT_S3_BUCKET`, `HONEYPOT_AWS_ACCESS_KEY_ID`,
`HONEYPOT_AWS_SECRET_ACCESS_KEY`, `AWS_REGION`.

## Verificar que funciona

1. **SSM en vez de SSH real**: `aws ssm start-session --target $(terraform output -raw instance_id)`
   conecta a la instancia sin necesidad de un puerto SSH de administración.
2. **Generar tráfico de prueba**: `ssh cualquier_usuario@$(terraform output -raw instance_public_ip)`
   desde otra máquina (o esperar tráfico real de scanners de internet — suele
   tardar minutos/horas, no hace falta forzarlo).
3. **Confirmar que sube a S3**: `aws s3 ls s3://$(terraform output -raw s3_bucket_name)/cowrie/`
4. **Correr el puller** (`python scripts/pull_honeypot_logs.py` o el servicio
   `honeypot-puller` del compose) y confirmar archivos en `data/raw/cowrie/`.
5. **Confirmar en Kibana** (http://localhost:5601) que el índice
   `cowrie-alerts-*` tiene documentos.

## Apagar / destruir

Este módulo cobra mientras la instancia y el bucket existan (aunque sea
centavos, dentro de free tier). Para no dejarlo corriendo entre sesiones de
trabajo:

```bash
terraform destroy -var="alert_email=tu-email@ejemplo.com"
```

Los logs ya sincronizados a `data/raw/cowrie/` y al índice `cowrie-alerts-*`
de Elasticsearch no se pierden al destruir — solo se apaga la captura de
tráfico nuevo.
