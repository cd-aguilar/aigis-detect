# Changelog

## 2026-08-17

- Se consolidó la documentación de pendientes (ítems 9-13) junto con el addendum de Tier 2 en un único documento, eliminando duplicación y fragmentación de información.
- La unificación mejora la trazabilidad del roadmap técnico, facilitando el seguimiento de tareas pendientes y su relación con los requisitos de Tier 2.
- Este cambio simplifica futuras actualizaciones de la documentación al centralizar el contexto relevante en una sola fuente de verdad.

## 2026-08-17

- Se documentó el cierre de la investigación técnica sobre el webhook Tier 2 en CLAUDE.md, consolidando hallazgos y decisiones tomadas durante el análisis.
- Esta actualización deja registro formal del estado de la integración Tier 2, facilitando el seguimiento futuro y evitando retrabajo en próximas revisiones.

## 2026-08-17

- Se re-validó la transición de Tier1 a Tier2 luego de resolver el crash-loop de n8n, confirmando la estabilidad del pipeline tras el fix.
- Se actualizó la documentación técnica para reflejar el estado verificado del sistema, asegurando trazabilidad del proceso de validación post-incidente.

## 2026-08-17

- Se corrigió el manejo de bloques de contenido no textuales en `generate_changelog.py`, evitando fallos cuando la respuesta del modelo incluye elementos distintos a texto plano.
- Mejora la robustez del script de generación de changelogs frente a respuestas variadas de la API, reduciendo riesgos de interrupción en la automatización del proceso.

## 2026-08-16

- Se amplió la documentación del README incorporando el diagrama de arquitectura del sistema, facilitando la comprensión del flujo de detección para nuevos colaboradores.
- Se incorporaron métricas de desempeño del modelo, aportando visibilidad sobre la precisión y efectividad de la solución.
- Se mejoró la presentación general del proyecto, reforzando su valor como referencia técnica dentro del portfolio.

## 2026-08-03

- Se incorporó integración continua para ejecutar el harness de evaluación del agente, permitiendo detectar regresiones de forma automática.
- El pipeline soporta disparo manual y ejecución programada semanal, facilitando tanto pruebas puntuales como monitoreo continuo de calidad.
- Esta automatización reduce la dependencia de validaciones manuales y aumenta la confiabilidad del proceso de evaluación a lo largo del tiempo.

## 2026-08-02

- Se corrigió la documentación del README para reflejar el estado actual del archivo mitre_techniques.json, evitando información desactualizada sobre su contenido o cobertura.
- Se mejora la precisión de la referencia técnica del repositorio, facilitando su uso como fuente confiable para quienes consulten el mapeo de técnicas MITRE.

