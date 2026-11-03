# Barrido de chunking · embeddings `gemini/gemini-embedding-001`

- Fecha: 2026-11-03 23:29 UTC
- Solo recuperación (sin LLM), sobre las preguntas respondibles del dataset; recuperación híbrida, top-6. El índice se reconstruye con el pipeline real para cada configuración.

| Tamaño | Solape | Cabecera | Fragmentos | hit@1 | hit@3 | hit@6 | MRR | Recall fuentes |
|---|---|---|---|---|---|---|---|---|
| 900 | 150 | sí | 47 | 0,81 | 0,90 | 0,94 | 0,86 | 0,94 |

## Modo de recuperación (configuración por defecto)

| Modo | hit@1 | hit@3 | hit@6 | MRR | Recall fuentes |
|---|---|---|---|---|---|
| hybrid | 0,81 | 0,90 | 0,94 | 0,86 | 0,94 |
| vector | 0,97 | 1,00 | 1,00 | 0,98 | 1,00 |
| text | 0,65 | 0,84 | 0,90 | 0,74 | 0,87 |

Preguntas en las que los modos no coinciden (posición de la primera fuente correcta; — = fuera del top-6):

| Pregunta | hybrid | vector | text |
|---|---|---|---|
| `hogar-hurto` | #1 | #1 | #3 |
| `hogar-inundacion` | — | #3 | — |
| `hogar-tuberia-rota` | — | #1 | — |
| `auto-conduzco-borracho` | #4 | #1 | — |
| `auto-rc-obligatoria` | #1 | #1 | #2 |
| `exacto-articulo-7-bis` | #1 | #1 | #2 |
| `exacto-articulo-9-auto` | #1 | #1 | #2 |
| `multi-denuncia-robo` | #2 | #1 | #3 |
| `multi-que-es-franquicia` | #3 | #1 | #6 |
| `injection-exclusiones` | #1 | #1 | #2 |
| `injection-mascotas` | #2 | #1 | #5 |
