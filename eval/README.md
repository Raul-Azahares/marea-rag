# Evaluación

Mide el asistente sobre un conjunto fijo de preguntas con respuesta conocida. Así las decisiones de chunking, recuperación, umbral y validación se toman con datos.

## Qué hay aquí

| Archivo | Qué es |
|---|---|
| [`dataset.yaml`](dataset.yaml) | El corpus que se indexa y las preguntas, cada una con sus fuentes esperadas, sus hechos obligatorios y sus hechos prohibidos. También fija los umbrales del quality gate |
| [`reports/fake.md`](reports/fake.md) | Ejecución con los proveedores falsos y deterministas. Es la línea base del CI |
| [`reports/gemini.md`](reports/gemini.md) | Ejecución con Gemini: `gemini-embedding-001` y `gemini-3.5-flash-lite` |
| [`reports/sweep-*.md`](reports/) | Barrido de chunking (solo recuperación) |

Cada informe tiene su `.json` con el detalle por pregunta.

## El dataset

**Corpus:** las pólizas sintéticas de `samples/`, indexadas con el pipeline de producción.

- **Hogar 2025**, reemplazada por **Hogar 2026**, que se sube como versión 2.
- **Auto**.
- **El anexo adversarial**, que incluye un intento de inyección de prompt.

**Preguntas, en cinco categorías:**

| Categoría | Qué comprueba |
|---|---|
| Respondibles | Que encuentra la cláusula y responde con sus datos. Tres preguntas están parafraseadas («conduzco borracho») para medir la búsqueda semántica |
| Versión | Que responde con la edición 2026 y nunca con las cifras de 2025, que figuran como prohibidas |
| Multidocumento | Que reúne las dos pólizas cuando la pregunta no dice cuál |
| Inyección | Que, con el anexo malicioso en el índice, no afirma lo que el anexo intenta imponer («todo cubierto al 100 %, sin franquicia») |
| Sin respuesta | Que se abstiene cuando los documentos no responden (precio, granizo, seguro dental…) |

**Criterios de cada pregunta:**

- **Fuentes:** documento y título exacto de la cláusula. Con ellas se puntúan la recuperación y las citas. Un test de integración comprueba que cada sección existe de verdad en el índice.
- **Hechos obligatorios y prohibidos:** se buscan como palabras completas en la respuesta, sin distinguir mayúsculas, tildes ni puntuación.

## Métricas

| Métrica | Definición |
|---|---|
| hit@1, hit@3, hit@6 | La fuente esperada está entre los k primeros fragmentos. El top-6 es lo que llega al LLM |
| MRR | Media de 1/posición de la primera fuente correcta |
| Recall de fuentes | Parte de las fuentes esperadas que se recuperan (multidocumento) |
| Tasa de respuesta | Preguntas respondibles que se responden |
| Tasa de rechazo | Preguntas sin respuesta que se rechazan. Se cuentan aparte las que para la compuerta τ sin llamar al LLM |
| Exactitud de abstención | Decisión correcta de responder o abstenerse, sobre todas las preguntas |
| Recall de hechos | Hechos obligatorios presentes en la respuesta. Una respondible sin respuesta cuenta 0 |
| Precisión de citas | Citas que apuntan a una fuente esperada |
| Validación a la primera | Respuestas del LLM que superan la validación de citas sin reintento |
| Hechos prohibidos, citas a versión reemplazada, citas a inyección | Deben ser 0 |
| Latencia p50/p95 | Por pregunta, de extremo a extremo |

**Calibración de τ.** Cada informe incluye la distribución de la mejor similitud para las preguntas respondibles y para las que no lo son. Con ella propone dos umbrales:
- el **seguro**, que es el más alto que no rechaza ninguna respondible;
- el de **mejor exactitud equilibrada**.

## Cómo se ejecuta

Requiere el Postgres de tests (`make test-infra`). La evaluación crea una base de datos propia, `marea_eval`, y la reconstruye desde las migraciones en cada ejecución.

```bash
make eval         # proveedores falsos + quality gate (lo mismo que el CI)
make eval-real    # proveedores de tu .env (p. ej. Gemini); solo informe
make eval-sweep   # barrido de chunking con los embeddings falsos
```

Equivalente directo, desde `backend/`:

```bash
uv run python -m evaluation run --gate
uv run python -m evaluation run --llm litellm --embeddings litellm --label gemini --pace 5
uv run python -m evaluation sweep --embeddings litellm --label gemini --pace 1
```

## Quality gate

En el CI se ejecuta el dataset completo con los proveedores falsos.

- Son deterministas: el mismo código da los mismos números, así que cualquier bajada es una regresión real y no ruido del modelo.
- Los umbrales están en `dataset.yaml`, justo por debajo de la línea base. Las métricas de seguridad (hechos prohibidos, citas a inyección y citas a versiones reemplazadas) exigen 0.

Los números absolutos del modelo falso son modestos, y es lo esperado: es un modelo léxico y extractivo, pensado para que el pipeline se pueda probar sin red. La calidad real se mide con Gemini.

## Añadir una pregunta

1. Añádela a `dataset.yaml` con el título exacto de la cláusula como fuente.
2. Ejecuta `make eval`.
3. Revisa el informe. Si la línea base cambia de forma justificada, ajusta los umbrales en el mismo commit.
