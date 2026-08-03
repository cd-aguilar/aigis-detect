#!/bin/bash
# cloud-init de la instancia del honeypot — instala Docker, levanta Cowrie
# (SSH/Telnet cebo) y sube sus logs JSON a S3 cada minuto vía cron.
# Sin credenciales AWS estáticas en la instancia: `aws s3 sync` usa el rol
# IAM adjunto (instance profile), con permiso s3:PutObject solo en su prefix.
set -euxo pipefail

dnf update -y
dnf install -y docker cronie unzip

systemctl enable --now docker
systemctl enable --now crond
usermod -aG docker ec2-user

if ! command -v aws >/dev/null 2>&1; then
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  (cd /tmp && unzip -q awscliv2.zip && ./aws/install)
fi

mkdir -p /opt/cowrie/log
# La imagen cowrie/cowrie corre como usuario no-root dentro del contenedor;
# sin esto, el output "jsonlog" de Cowrie falla al arrancar con
# PermissionError al no poder escribir en el bind mount (creado por root).
chmod 777 /opt/cowrie/log

# El puerto 22 es 100% el cebo de Cowrie -- el sshd real de la AMI (que
# escucha ahí por default) se apaga; el acceso admin va por SSM, no SSH.
systemctl disable --now sshd

docker run -d \
  --name cowrie \
  --restart unless-stopped \
  -p 22:2222 \
  -p 23:2223 \
  -v /opt/cowrie/log:/cowrie/cowrie-git/var/log/cowrie \
  cowrie/cowrie:latest

cat > /etc/cron.d/honeypot-sync <<CRON
* * * * * root aws s3 sync /opt/cowrie/log s3://${s3_bucket}/cowrie/ --exclude "*" --include "*.json" --region ${aws_region} >> /var/log/honeypot-sync.log 2>&1
CRON
chmod 644 /etc/cron.d/honeypot-sync
