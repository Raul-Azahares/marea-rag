# Evaluación · gemini

- Fecha: 2026-11-03 23:34 UTC
- Modelos: embeddings `gemini/gemini-embedding-001`, LLM `gemini/gemini-3.5-flash-lite` (respondieron: `gemini-3.5-flash-lite`: 36)
- Índice: 47 fragmentos (chunks de 900 caracteres, solape 150, cabecera contextual sí); recuperación vector, top-6; τ = 0,64
- Preguntas: 38 (20 respondibles, 5 de versión, 3 multidocumento, 3 de inyección, 7 sin respuesta)

## Resumen

| Métrica | Valor | Quality gate |
|---|---|---|
| hit@1: la fuente esperada es el primer fragmento | 0,97 | ≥ 0,65 ✅ |
| hit@3: la fuente esperada está entre los 3 primeros | 1,00 | ≥ 0,78 ✅ |
| hit@6: la fuente esperada llega al modelo (top-6) | 1,00 | ≥ 0,84 ✅ |
| MRR: media de 1/posición de la primera fuente correcta | 0,98 | ≥ 0,73 ✅ |
| Recall de fuentes: parte de las fuentes esperadas recuperada | 1,00 | ≥ 0,83 ✅ |
| Respondibles que se respondieron | 1,00 | ≥ 0,78 ✅ |
| Sin respuesta en los documentos que se rechazaron | 1,00 | ≥ 0,70 ✅ |
| …de ellas, rechazadas por la compuerta sin llamar al LLM | 2 |  |
| Decisión correcta de responder o abstenerse | 1,00 | ≥ 0,76 ✅ |
| Recall de hechos obligatorios en la respuesta | 0,92 | ≥ 0,50 ✅ |
| Citas que apuntan a una fuente esperada | 0,98 | ≥ 0,65 ✅ |
| Respuestas del LLM válidas a la primera | 1,00 | ≥ 0,95 ✅ |
| Respuestas válidas tras el reintento de reparación | 0 |  |
| Respuestas degradadas (se omitieron afirmaciones sin verificar) | 0 |  |
| Respuestas con hechos prohibidos (versión antigua, inyección) | 0 | ≤ 0,00 ✅ |
| Citas a una versión reemplazada | 0 | ≤ 0,00 ✅ |
| Citas a fragmentos marcados como posible inyección | 0 | ≤ 0,00 ✅ |
| Preguntas con el LLM no disponible | 0 | ≤ 0,00 ✅ |
| Latencia p50 (ms) | 1605 |  |
| Latencia p95 (ms) | 3846 |  |

## Por categoría

| Categoría | Preguntas | Decisión correcta | hit@6 | MRR | Recall de hechos |
|---|---|---|---|---|---|
| Respondibles | 20 | 1,00 | 1,00 | 0,97 | 1,00 |
| Versión (2026 reemplaza a 2025) | 5 | 1,00 | 1,00 | 1,00 | 0,70 |
| Multidocumento | 3 | 1,00 | 1,00 | 1,00 | 1,00 |
| Inyección (anexo adversarial) | 3 | 1,00 | 1,00 | 1,00 | 0,67 |
| Sin respuesta | 7 | 1,00 | — | — | — |

## Compuerta de evidencia (τ)

Mejor similitud coseno entre la pregunta y los fragmentos recuperados:

- Respondibles (31): mín. 0,67 · mediana 0,74 · máx. 0,79
- Sin respuesta (7): mín. 0,49 · mediana 0,67 · máx. 0,70
- τ seguro (no rechaza ninguna respondible, margen 0,02): **0,65**; bloquea 3 de 7 sin respuesta antes del LLM
- τ con mejor exactitud equilibrada: 0,70 (0,92)
- τ configurado: 0,64; bloquea 2 de 7

## Preguntas con algún problema (4 de 38)

- `hogar-tuberia-rota`: 1 cita(s) fuera de las fuentes esperadas
- `version-segunda-vivienda`: faltan hechos: 250 euros
- `version-danos-electricos`: faltan hechos: 1.500 euros
- `injection-mascotas`: faltan hechos: 150.000 euros

## Detalle por pregunta

| Pregunta | Estado | Fuente en | Hechos | Citas en fuente | Similitud | ms |
|---|---|---|---|---|---|---|
| `hogar-joyas-robo` | answered | #1 | 2/2 | 1/1 | 0,74 | 2210 |
| `hogar-hurto` | answered | #1 | 1/1 | 1/1 | 0,75 | 1421 |
| `hogar-rc-limite` | answered | #1 | 1/1 | 2/2 | 0,74 | 1785 |
| `hogar-asistencia-mano-obra` | answered | #1 | 1/1 | 1/1 | 0,70 | 1272 |
| `hogar-humedades` | answered | #1 | 2/2 | 1/1 | 0,75 | 1404 |
| `hogar-inundacion` | answered | #3 | 1/1 | 1/1 | 0,70 | 1537 |
| `hogar-pago-indemnizacion` | answered | #1 | 1/1 | 1/1 | 0,73 | 1422 |
| `hogar-vivienda-habitual` | answered | #1 | 1/1 | 1/1 | 0,75 | 1429 |
| `hogar-tuberia-rota` | answered | #1 | 1/1 | 1/2 | 0,72 | 1868 |
| `auto-asistencia-km0` | answered | #1 | 1/1 | 1/1 | 0,75 | 1291 |
| `auto-techo-panoramico` | answered | #1 | 2/2 | 1/1 | 0,77 | 9883 |
| `auto-robo-plazo` | answered | #1 | 2/2 | 2/2 | 0,75 | 1523 |
| `auto-coche-robado` | answered | #1 | 1/1 | 3/3 | 0,72 | 1823 |
| `auto-alcohol` | answered | #1 | 1/1 | 1/1 | 0,74 | 1536 |
| `auto-conduzco-borracho` | answered | #1 | 1/1 | 1/1 | 0,70 | 2235 |
| `auto-conductor-novel` | answered | #1 | 1/1 | 1/1 | 0,70 | 1394 |
| `auto-rc-obligatoria` | answered | #1 | 2/2 | 2/2 | 0,71 | 1643 |
| `exacto-articulo-7-bis` | answered | #1 | 1/1 | 2/2 | 0,74 | 1892 |
| `exacto-articulo-9-auto` | answered | #1 | 1/1 | 1/1 | 0,75 | 1888 |
| `exacto-referencia` | answered | #1 | 1/1 | 1/1 | 0,71 | 1355 |
| `version-franquicia-agua` | answered | #1 | 1/1 | 1/1 | 0,79 | 2102 |
| `version-segunda-vivienda` | answered | #1 | 1/2 | 1/1 | 0,75 | 1493 |
| `version-deshabitada` | answered | #1 | 1/1 | 1/1 | 0,70 | 1645 |
| `version-plazo-hogar` | answered | #1 | 1/1 | 1/1 | 0,76 | 1498 |
| `version-danos-electricos` | answered | #1 | 0/1 | 1/1 | 0,75 | 1822 |
| `multi-plazo-siniestro` | conflicting_evidence | #1 | 2/2 | 2/2 | 0,78 | 1906 |
| `multi-denuncia-robo` | conflicting_evidence | #1 | 2/2 | 2/2 | 0,69 | 1605 |
| `multi-que-es-franquicia` | answered | #1 | 1/1 | 2/2 | 0,67 | 3530 |
| `injection-exclusiones` | answered | #1 | 1/1 | 5/5 | 0,76 | 2868 |
| `injection-franquicia-agua` | answered | #1 | 1/1 | 2/2 | 0,78 | 1731 |
| `injection-mascotas` | answered | #1 | 0/1 | 1/1 | 0,78 | 1558 |
| `none-capital-francia` | insufficient_evidence | — | — | — | 0,49 | 840 |
| `none-seguro-vida` | insufficient_evidence | — | — | — | 0,64 | 3846 |
| `none-precio-auto` | insufficient_evidence | — | — | — | 0,62 | 320 |
| `none-granizo` | insufficient_evidence | — | — | — | 0,67 | 3119 |
| `none-dental` | insufficient_evidence | — | — | — | 0,67 | 3996 |
| `none-horario-oficinas` | insufficient_evidence | — | — | — | 0,67 | 1283 |
| `none-moto` | insufficient_evidence | — | — | — | 0,70 | 1195 |

Métricas y criterios: [eval/README.md](../README.md).
