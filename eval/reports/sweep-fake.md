# Barrido de chunking · embeddings `fake-hashing-v1`

- Fecha: 2026-11-03 23:31 UTC
- Solo recuperación (sin LLM), sobre las preguntas respondibles del dataset; recuperación `hybrid`, top-6. El índice se reconstruye con el pipeline real para cada configuración.

| Tamaño | Solape | Cabecera | Fragmentos | hit@1 | hit@3 | hit@6 | MRR | Recall fuentes |
|---|---|---|---|---|---|---|---|---|
| 500 | 0 | sí | 52 | 0,61 | 0,84 | 0,90 | 0,73 | 0,89 |
| 500 | 0 | no | 52 | 0,55 | 0,71 | 0,90 | 0,67 | 0,89 |
| 500 | 150 | sí | 56 | 0,68 | 0,81 | 0,90 | 0,76 | 0,89 |
| 500 | 150 | no | 56 | 0,58 | 0,71 | 0,87 | 0,67 | 0,85 |
| 900 | 0 | sí | 47 | 0,61 | 0,81 | 0,87 | 0,72 | 0,84 |
| 900 | 0 | no | 47 | 0,61 | 0,68 | 0,87 | 0,68 | 0,85 |
| 900 | 150 | sí | 47 | 0,68 | 0,81 | 0,87 | 0,76 | 0,85 |
| 900 | 150 | no | 47 | 0,58 | 0,65 | 0,87 | 0,66 | 0,85 |
| 1500 | 0 | sí | 45 | 0,61 | 0,81 | 0,87 | 0,72 | 0,84 |
| 1500 | 0 | no | 45 | 0,55 | 0,68 | 0,87 | 0,65 | 0,85 |
| 1500 | 150 | sí | 45 | 0,61 | 0,81 | 0,87 | 0,72 | 0,84 |
| 1500 | 150 | no | 45 | 0,55 | 0,68 | 0,87 | 0,65 | 0,85 |

## Modo de recuperación (configuración por defecto)

| Modo | hit@1 | hit@3 | hit@6 | MRR | Recall fuentes |
|---|---|---|---|---|---|
| hybrid | 0,68 | 0,81 | 0,87 | 0,76 | 0,85 |
| vector | 0,71 | 0,81 | 0,84 | 0,76 | 0,82 |
| text | 0,65 | 0,84 | 0,90 | 0,74 | 0,87 |

Preguntas en las que los modos no coinciden (posición de la primera fuente correcta; — = fuera del top-6):

| Pregunta | hybrid | vector | text |
|---|---|---|---|
| `hogar-hurto` | #2 | #2 | #3 |
| `auto-coche-robado` | #4 | — | #1 |
| `exacto-articulo-7-bis` | #1 | #1 | #2 |
| `exacto-articulo-9-auto` | — | — | #2 |
| `multi-denuncia-robo` | #2 | #2 | #3 |
| `injection-exclusiones` | #1 | #1 | #2 |
| `injection-mascotas` | #2 | #1 | #5 |
