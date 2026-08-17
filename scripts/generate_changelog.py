#!/usr/bin/env python3
"""
Genera un resumen del último commit (o rango de commits) con la API de
Claude y lo antepone a CHANGELOG.md.

Pensado para correr dentro de un GitHub Action en cada push (ver
.github/workflows/update-changelog.yml). También se puede correr local:

    ANTHROPIC_API_KEY=sk-... REPO_NAME=usuario/repo python scripts/generate_changelog.py
"""
import os
import subprocess
import sys
from datetime import date

import anthropic

CHANGELOG_PATH = "CHANGELOG.md"
MODEL = "claude-sonnet-5"


def get_commit_range() -> str:
    """Diff de mensajes de commit desde el último tag, o el último commit si no hay tags."""
    try:
        last_tag = subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        range_spec = f"{last_tag}..HEAD"
    except subprocess.CalledProcessError:
        range_spec = "HEAD~1..HEAD"

    log = subprocess.run(
        ["git", "log", range_spec, "--pretty=format:- %s (%h)"],
        capture_output=True, text=True,
    ).stdout.strip()

    if not log:
        log = subprocess.check_output(
            ["git", "log", "-1", "--pretty=format:- %s (%h)"], text=True
        ).strip()
    return log


def summarize_with_claude(commit_log: str, repo_name: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY no está seteada, saliendo sin generar resumen.")
        sys.exit(0)

    client = anthropic.Anthropic(api_key=api_key)
    prompt = f"""Sos un asistente que escribe entradas de changelog concisas y
profesionales para un repositorio de portfolio técnico ({repo_name}).

Estos son los commits nuevos:
{commit_log}

Escribí un resumen de 2 a 5 bullets en español, en tono técnico y directo,
agrupando cambios relacionados. No repitas los mensajes de commit tal cual;
sintetizá el impacto (qué cambió y por qué importa). No agregues encabezados
ni fecha, solo los bullets, cada uno empezando con "- "."""

    message = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    text_blocks = [block.text for block in message.content if block.type == "text"]
    return "".join(text_blocks).strip()


def update_changelog(summary: str):
    today = date.today().isoformat()
    entry = f"## {today}\n\n{summary}\n\n"

    existing = ""
    if os.path.exists(CHANGELOG_PATH):
        with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
            existing = f.read()
    else:
        existing = "# Changelog\n\n"
        if existing and not existing.startswith("# Changelog"):
            existing = "# Changelog\n\n" + existing

    # Insertar la nueva entrada después del título
    if existing.startswith("# Changelog"):
        header, _, rest = existing.partition("\n\n")
        new_content = f"{header}\n\n{entry}{rest}"
    else:
        new_content = f"# Changelog\n\n{entry}{existing}"

    with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)

    print("CHANGELOG.md actualizado:")
    print(entry)


def main():
    repo_name = os.environ.get("REPO_NAME", "repo")
    commit_log = get_commit_range()
    if not commit_log:
        print("No hay commits nuevos para resumir.")
        return
    summary = summarize_with_claude(commit_log, repo_name)
    update_changelog(summary)


if __name__ == "__main__":
    main()
