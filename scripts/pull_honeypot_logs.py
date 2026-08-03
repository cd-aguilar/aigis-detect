#!/usr/bin/env python3
"""Descarga los logs nuevos del honeypot Cowrie desde S3 al host.

El honeypot (infra/aws-honeypot/) sube sus logs a S3 vía cron cada 1 min.
Este script hace polling del bucket y descarga a data/raw/cowrie/ (ya
excluido de git por .gitignore) lo que todavía no esté en disco. Filebeat
lee esa carpeta (input "cowrie" en filebeat/filebeat.yml) y lo manda a
Elasticsearch, índice cowrie-alerts-*.

Correr desde el host (no dentro de Docker) o vía el servicio
"honeypot-puller" del docker-compose.yml:
    pip install boto3 --break-system-packages
    python scripts/pull_honeypot_logs.py

Requiere HONEYPOT_S3_BUCKET, AWS_REGION, HONEYPOT_AWS_ACCESS_KEY_ID y
HONEYPOT_AWS_SECRET_ACCESS_KEY en el entorno (ver .env.example) — son las
credenciales del usuario IAM "puller" (solo lectura), no las del rol del EC2.
"""
import os
import sys
import time

import boto3

BUCKET = os.environ["HONEYPOT_S3_BUCKET"]
PREFIX = "cowrie/"
DEST_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "cowrie")
POLL_INTERVAL_SECONDS = int(os.getenv("HONEYPOT_POLL_INTERVAL_SECONDS", "60"))


def make_client():
    return boto3.client(
        "s3",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        aws_access_key_id=os.environ["HONEYPOT_AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["HONEYPOT_AWS_SECRET_ACCESS_KEY"],
    )


def sync_once(client) -> int:
    os.makedirs(DEST_DIR, exist_ok=True)
    downloaded = 0

    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=PREFIX):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            filename = key[len(PREFIX):]
            if not filename:
                continue

            local_path = os.path.join(DEST_DIR, filename.replace("/", "_"))
            if os.path.exists(local_path) and os.path.getsize(local_path) == obj["Size"]:
                continue

            client.download_file(BUCKET, key, local_path)
            downloaded += 1

    return downloaded


def main() -> int:
    client = make_client()
    loop = "--once" not in sys.argv

    while True:
        downloaded = sync_once(client)
        if downloaded:
            print(f"Descargados {downloaded} archivo(s) nuevo(s) de s3://{BUCKET}/{PREFIX}")

        if not loop:
            break
        time.sleep(POLL_INTERVAL_SECONDS)

    return 0


if __name__ == "__main__":
    sys.exit(main())
