# Aigis-Detect — Revisión de arquitectura externa (2026-08-17)

> Consolidación de una evaluación hecha por otro agente de IA sobre el estado
> actual de Aigis-Detect (a esa fecha: Fase 1 SOC homelab + Fase 2 agente de
> triage + Fase 3 honeypot AWS, harness de evals con `qwen3:1.7b` mostrando
> 50% de veredicto correcto / 20% de técnica MITRE correcta). Se guarda
> textual como insumo para decidir próximos pasos — **no son decisiones
> tomadas todavía**, es una propuesta a evaluar. Ver puntero desde
> `CLAUDE.md` (Próximos pasos, ítem 13).

## Veredicto

Aigis-Detect evaluado como **proyecto de portfolio para Detection
Engineering / SOC Engineering / Security Automation**, no como producto
operativo 24/7. El diferencial no es la cantidad de herramientas sino que ya
combina: pipeline SOC real end-to-end, detecciones mapeadas a MITRE,
generación de ataques controlados, agente IA con tool calling, SOAR,
respuesta automática, honeypot expuesto a Internet y, sobre todo, un harness
de evaluación que demuestra que el agente falla.

| Área                                  | Evaluación |
| ------------------------------------- | ---------: |
| Arquitectura SOC                      |   9/10 |
| Detection Engineering                 |   8/10 |
| SOAR / Automation                     |   9/10 |
| DFIR                                  |   8/10 |
| IA aplicada a SOC                     |   7/10 |
| Evaluación científica del agente      | 9.5/10 |
| Reproducibilidad                      |   8/10 |
| Portfolio profesional                 | 9.5/10 |
| Viabilidad con el hardware actual     |   6/10 |
| Potencial como proyecto diferenciador | 9.5/10 |

Recomendación general: **no ampliar mucho más en infraestructura — hacerlo
más riguroso.**

---

## 1. El mayor hallazgo: el problema no es la IA, es la arquitectura de decisión

El resultado del eval (6/12 veredicto correcto, 20% técnica MITRE correcta,
6/12 sin ninguna tool invocada, sesgo sistemático a subestimar amenazas
reales) es más interesante que un supuesto 95% de precisión, y no debería
esconderse — al contrario, convertirlo en pieza central del proyecto:

> "Evaluating Local LLMs for SOC Alert Triage: Why Accuracy Alone Is Not
> Enough"

El agente actual, cuando no está seguro, tiende a minimizar la amenaza — peor
que tener falsos positivos en un SOC. Propone cambiar el objetivo de "crear
un agente IA que haga triage" a **"construir un sistema de triage SOC
evaluable, con IA bajo restricciones de seguridad y con evidencia
cuantificable."**

## 2. Separar detección, evidencia y decisión

De `Alert → LLM → Verdict` a:

```text
Wazuh/Elastic → Alert Parser → (IOC Intel + Elastic context + ATT&CK context)
  → Evidence Object → LLM Analyst → Policy Engine
  → (FP/BP/TP | Human Review | Auto-response)
```

El LLM no debería decidir directamente qué hacer — debe ser un componente de
análisis; la política debe ser determinista.

## 3. `EvidenceBundle` antes de llamar al LLM

```json
{
  "alert_id": "...",
  "rule_id": "91823",
  "timestamp": "...",
  "source_ip": "...",
  "destination_ip": "...",
  "user": "...",
  "mitre": { "technique": "T1059.001", "confidence": 0.92 },
  "elastic_context": [],
  "ioc_reputation": [],
  "historical_activity": [],
  "detection_metadata": { "severity": "high", "rule_confidence": "medium" }
}
```

El LLM recibe evidencia estructurada, no solo "aquí tienes una alerta, dime
qué piensas" — reduce la dependencia del razonamiento espontáneo del modelo.

## 4. Tool calling obligatorio (no discrecional) para ciertas alertas

El eval mostró 6/12 casos sin ninguna tool invocada. Propuesta de niveles:

- **Nivel 1 — enriquecimiento obligatorio siempre:** IOC → reputation, MITRE
  → technique lookup, Elastic → historical context.
- **Nivel 2 — tools condicionales según tipo:** network alert → Elastic +
  IP reputation; authentication → user history + source IP reputation;
  PowerShell → Elastic process history + MITRE; file deletion → endpoint
  context.
- **Nivel 3 — LLM:** evidence → LLM → assessment.

Permite comparar **LLM autónomo vs. LLM evidence-driven** como evaluación
científica.

## 5. Métrica de costo del error, no solo accuracy/precision/recall

Para SOC: False Negative Rate y, especialmente, **False Negative Cost**
ponderado:

| Error                        | Peso |
| ---------------------------- | ---: |
| TP → FP                      |    1 |
| TP → borderline               |    2 |
| TP → FP cuando es ransomware |   10 |
| FP → TP                      |    3 |
| FP → borderline               |    1 |

Con eso, calcular un `Risk-weighted triage score` — permite argumentar "el
modelo A tiene 70% accuracy pero mayor riesgo operacional que el modelo B con
65%", que es Security Engineering y no solo AI demo.

## 6. Dataset de 50 casos → benchmark versionado

```text
dataset/
├── cases/{tp,fp,borderline}/
├── manifest.yaml
├── ground_truth.json
└── README.md
```

Cada caso con `id`, `attack.technique`, `expected.verdict/severity/mitre`,
`expected_tools`, `risk.false_negative`. Reproducible con `make eval`.

## 7. Benchmark A/B entre 5 baselines

Rule only → LLM sin tools → LLM + tools opcionales → LLM + evidencia
obligatoria → LLM + evidencia + policy determinista. Medir accuracy, recall,
FN, MITRE accuracy, tool use, latency por cada uno.

## 8. MITRE: fuente STIX 2.1 oficial versionada, no 8 técnicas hardcoded

Fuente: repo `mitre-attack/attack-stix-data` (release actual 19.1 al momento
de la revisión). Estructura propuesta: `data/mitre/enterprise-attack.json` +
`version.txt` + `scripts/update_mitre.py` (descarga → valida → extrae →
indexa → actualiza Chroma → corre tests). Convierte el KB de "JSON
artesanal" a "versioned CTI knowledge pipeline".

## 9. ATT&CK debe alimentar Detection Engineering, no solo al LLM

`MITRE → Technique → Detection → Atomic Test → Expected Alert → Agent Triage
→ Response` — Detection-as-Code. Elastic recomienda gestionar reglas vía
API/Detection-as-Code con validación en CI/CD (ver Elastic docs sobre
"Validate and test rules").

## 10. CI/CD más allá de `pytest`

`lint → unit tests → schema validation → MITRE validation → detection tests
→ agent eval → regression check → security checks → PASS/FAIL` con reporte
tipo "Recall dropped: 92% → 75%, False negatives: 2 → 7".

## 11. Evaluation gates en CI

```yaml
minimum:
  triage_recall: 0.90
  critical_recall: 0.95
  mitre_accuracy: 0.80
  schema_validity: 1.00
  tool_success_rate: 0.95
```

Un cambio de prompt que baja recall de 90%→82% hace fallar el pipeline —
convierte el prompt en software testeable.

## 12. No mejorar el modelo todavía

Primero probar `qwen3:1.7b` + evidencia obligatoria + salida estructurada +
policy determinista, y recién ahí medir. `qwen3:4b` ya se descartó por
timeout/recursos en el hardware actual (16GB RAM, WSL2 en 12GB). Optimizar
arquitectura antes que modelo — coherente con la regla de ROI del proyecto.

## 13. Capa de calibración de confianza (opcional)

No confundir `confidence` reportado por el LLM con probabilidad real —
calibrar sobre el dataset (bins low/medium/high como punto de partida,
Brier score / calibration error como siguiente paso). Refuerza el perfil AI
Engineer.

## 14. Policy Engine explícito

```text
src/policy/{policy.py, thresholds.yaml, allowlist.yaml, response_matrix.yaml}
```

Ejemplo: `critical` → sin auto-response, requiere aprobación humana; `high` →
auto-response condicional; `medium`/`low` → sin auto-response. La IA
recomienda, la policy decide.

## 15. Auto-block de IP: ajuste a la arquitectura ya decidida (ítem 9 de CLAUDE.md)

La combinación AbuseIPDB + VirusTotal + GreyNoise → decisión → Wazuh Active
Response es buena, pero **GreyNoise "benign" no debería ser la única
condición de corte** — GreyNoise clasifica por comportamiento/actor y
"benign" puede coexistir con comportamiento que en otro contexto parecería
malicioso (ver GreyNoise docs sobre clasificaciones). Usar un score
determinista combinando las 3 fuentes → BLOCK / REVIEW / ALLOW, no un atajo
de "GreyNoise dice benigno, no bloquear" aislado.

## 16. Bloqueo stateful (ya contemplado, mantenerlo)

`BLOCK → TTL (ej. 30 min) → RE-EVALUATE → UNBLOCK`, no `iptables DROP`
permanente. Wazuh soporta active response stateful/timeout y tiene
`firewall-drop` nativo.

## 17. Human Approval Gate — tres niveles de autonomía

- **L0 — Observe:** alert → enrichment → triage → notify.
- **L1 — Recommend:** alert → enrichment → AI → recommendation → aprobación
  humana → acción.
- **L2 — Autonomous:** alert → enrichment → policy determinista → acción →
  audit.

Permite mostrar la evolución de "AI assistant" a "AI-assisted SOC" a
"bounded autonomous SOC".

## 18. Integrar el honeypot al pipeline de triage

Hoy: `Internet → Cowrie → S3 → homelab → Elastic`, sin llegar a
`Wazuh/Elastic → Detection → Agent → TheHive → Slack/Telegram`. Cerrar ese
circuito sería el "demo estrella": Internet attacker → detection → AI triage
→ case creation → notification → optional automated response.

## 19. Segunda fuente de ataque: attack replay

Atomic Red Team (ataques controlados) + Cowrie (ruido real de Internet)
alimentando el mismo pipeline `Wazuh → Elastic → Detection Rule → AI Triage
→ TheHive → Response` — dos fuentes de evidencia para la evaluación.

## 20-21. Scope creep — congelar infraestructura

Stack actual ya es grande (Wazuh, Elastic, Kibana, TheHive, Velociraptor,
n8n, Redis, Ollama, Chroma, AWS, Terraform, Cowrie, Slack, Telegram, Atomic
Red Team, Mordor, BOTS, CI/CD futuro, autoblock futuro). Riesgo de pasar de
"construí y evalué una arquitectura de SOC automatizada" a "construí todo un
SOC". Recomendación: **no agregar** Splunk, OpenSearch, Suricata, Zeek,
Kafka, Kubernetes, LangChain, otro vector DB, otro LLM, otra plataforma
SOAR. La decisión de no sumar LangChain mientras el tool calling nativo de
Ollama alcance se considera correcta (ya es la política de ROI del
proyecto).

## 22. Tres capacidades, un solo repo

```text
detections/ tests/ mitre/ atomic/          # A. Detection Engineering
src/agent/ src/evidence/ src/policy/ evals/ # B. AI Triage
n8n/ response/ honeypot/                    # C. SOAR
```

Un solo proyecto (Aigis-Detect), portfolio presentado como tres
capacidades.

## 23. Posicionamiento

En vez de "AI SOC Agent" (categoría saturada):

> **Aigis-Detect — Evidence-Driven SOC Automation**
> An evaluated local-LLM security operations pipeline combining detection
> engineering, evidence-based AI triage, SOAR and bounded automated
> response.

## 24. Arquitectura objetivo (diagrama consolidado)

```text
INTERNET → Cowrie ─┐
Atomic Red Team ────┼→ Wazuh → Elasticsearch → Detection Layer
                                                     → Evidence Builder
                        (Threat Intel + MITRE KB + Elastic Context) →
                                                     → AI Triage LLM
                                                     → Policy Engine
                        → TheHive / Human Review / Auto Response
                              (Slack, Telegram, Audit)   (Wazuh Active Response)

En paralelo: GitHub → CI (tests, detections, ATT&CK validation, agent eval,
regression, security scan)
```

## 25. Diferencial a explotar en el portfolio

> "The agent failed. We measured why. Then we redesigned the architecture."

Más convincente que "My AI SOC agent achieves 95% accuracy" — demuestra
ingeniería, experimentación, observabilidad, evaluación, pensamiento
crítico, seguridad y capacidad de corregir el diseño. Encaja con el perfil
AI Engineer + Blue Team.

## 26. Prioridad de mejoras propuesta

**P0 — imprescindible**
1. Rediseñar triage como Evidence → LLM → Policy
2. Mandatory tools para determinadas alertas
3. Benchmark A/B (LLM / LLM+tools / evidence-driven)
4. Métricas: recall, FN, critical FN, MITRE accuracy, latency, tool usage
5. CI evaluation gate

**P1 — muy recomendable**
6. Detection-as-Code
7. ATT&CK STIX versionado
8. Honeypot → Elastic → Triage
9. Auto-block con human approval
10. Stateful IP blocking

**P2 — después**
11. Calibration
12. 100–200 casos de benchmark
13. Más técnicas ATT&CK
14. Velociraptor integrado en casos de alto riesgo

**P3 — evitar por ahora**
15. Kubernetes · 16. LangChain · 17. Otro SIEM · 18. Otro LLM · 19. Kafka ·
20. Más infraestructura cloud

## 27. Sobre Wazuh Active Response

La elección de Wazuh para Active Response se considera acertada — ya provee
`firewall-drop`, `netsh.exe`, `route-null` y scripts custom, con soporte
stateful. Recomendación: no construir un sistema de firewall-block propio;
la innovación va arriba (threat intel + evidence + AI assessment + policy),
Wazuh ejecuta la acción — separación clara de responsabilidades.

## 28. Recomendación estratégica final

No agrandar Aigis-Detect — hacerlo más científico y demostrable.

```text
ACTUAL: SOC Lab + AI Agent + SOAR + Honeypot
   ↓
OBJETIVO: Detection Engineering + Evidence-driven AI + Deterministic Policy
          + SOAR + Bounded Autonomous Response + Continuous Evaluation
```

Claim central propuesto:

> "Aigis-Detect investigates whether a small local LLM can safely assist SOC
> triage, measures where it fails, and constrains its behavior through
> evidence, deterministic policy and continuous evaluation."

Conclusión de la revisión: mantener Aigis-Detect como proyecto único (no
crear un proyecto "AI SOC" aparte, consistente con la decisión ya tomada en
CLAUDE.md ítem 9 de no fragmentar el portfolio). Siguiente hito sugerido:
**Evidence-Driven Triage + benchmark A/B + CI quality gates**, y recién
después integrar honeypot y auto-block.
