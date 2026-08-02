#!/usr/bin/env python3
"""Harness de evaluación del agente de triage — versión reducida.

Llama a POST /triage directo por cada caso de data/eval_dataset.json
(bypassea Wazuh/n8n para poder iterar rápido) y compara el veredicto y la
técnica MITRE devueltos contra lo esperado. Pensado para medir el impacto
real del cambio a qwen3:1.7b (ver CLAUDE.md, Próximos pasos #5).

No incluye todavía disparo real de Atomic Red Team vía WinRM ni consulta a
TheHive — eso requiere un host Windows target que hoy no está armado en el
homelab. Los 12 casos son sintéticos, con el mismo criterio de diseño que
las pruebas manuales previas (TP variantes, FP legítimos, borderline).

Uso:
    python scripts/run_evaluation.py
    python scripts/run_evaluation.py --agent-url http://localhost:8080/triage
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

DATASET_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "eval_dataset.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "processed")


def normalize(value):
    return str(value or "").strip().upper().replace(" ", "_")


def run_case(agent_url: str, case: dict, timeout: int) -> dict:
    alert = dict(case["alert"])
    alert["alert_id"] = case["case_id"]
    alert.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    start = time.monotonic()
    try:
        resp = requests.post(agent_url, json=alert, timeout=timeout)
        latency = time.monotonic() - start
        resp.raise_for_status()
        verdict = resp.json()
    except Exception as exc:  # noqa: BLE001 — se registra como fallo del caso, no corta el harness
        latency = time.monotonic() - start
        return {
            "case_id": case["case_id"],
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "ERROR",
            "verdict_match": False,
            "expected_mitre": case.get("expected_mitre") or "",
            "actual_mitre": "",
            "mitre_match": None,
            "tool_calls": "",
            "latency_s": round(latency, 1),
            "explanation": f"request failed: {exc}",
        }

    actual_verdict = verdict.get("verdict", "")
    actual_mitre = verdict.get("mitre_technique") or ""
    expected_mitre = case.get("expected_mitre")

    mitre_match = None
    if expected_mitre:
        mitre_match = normalize(expected_mitre) in normalize(actual_mitre)

    return {
        "case_id": case["case_id"],
        "expected_verdict": case["expected_verdict"],
        "actual_verdict": actual_verdict,
        "verdict_match": normalize(actual_verdict) == normalize(case["expected_verdict"]),
        "expected_mitre": expected_mitre or "",
        "actual_mitre": actual_mitre,
        "mitre_match": mitre_match,
        "tool_calls": ";".join(verdict.get("tool_calls", [])),
        "latency_s": round(latency, 1),
        "explanation": verdict.get("explanation", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-url", default=os.getenv("AGENT_URL", "http://localhost:8080/triage"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("EVAL_TIMEOUT", "300")))
    parser.add_argument("--dataset", default=DATASET_PATH)
    args = parser.parse_args()

    with open(args.dataset, encoding="utf-8") as f:
        cases = json.load(f)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = os.path.join(RESULTS_DIR, f"eval_results_{run_id}.csv")

    results = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case['case_id']} ...", flush=True)
        result = run_case(args.agent_url, case, args.timeout)
        results.append(result)
        status = "OK" if result["verdict_match"] else "MISS"
        print(f"    -> {status} esperado={result['expected_verdict']} obtenido={result['actual_verdict']} ({result['latency_s']}s)", flush=True)

    fieldnames = ["case_id", "expected_verdict", "actual_verdict", "verdict_match",
                  "expected_mitre", "actual_mitre", "mitre_match", "tool_calls",
                  "latency_s", "explanation"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    total = len(results)
    verdict_hits = sum(1 for r in results if r["verdict_match"])
    mitre_cases = [r for r in results if r["mitre_match"] is not None]
    mitre_hits = sum(1 for r in mitre_cases if r["mitre_match"])
    avg_latency = sum(r["latency_s"] for r in results) / total if total else 0
    tool_calls_empty = sum(1 for r in results if not r["tool_calls"])

    print("\n--- Resumen ---")
    print(f"Veredicto correcto: {verdict_hits}/{total} ({verdict_hits/total*100:.0f}%)")
    if mitre_cases:
        print(f"Técnica MITRE correcta: {mitre_hits}/{len(mitre_cases)} ({mitre_hits/len(mitre_cases)*100:.0f}%)")
    print(f"Latencia promedio: {avg_latency:.1f}s")
    print(f"Casos sin ninguna tool invocada: {tool_calls_empty}/{total}")
    print(f"Resultados: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
