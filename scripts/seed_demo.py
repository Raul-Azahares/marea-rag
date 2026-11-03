#!/usr/bin/env python3
"""Load the sample policies into a running stack, as an agent would through the UI:

1. Marea Hogar Plus, 2025 edition;
2. its 2026 edition, uploaded as *version 2* (the 2025 one becomes superseded);
3. Marea Auto;
4. the adversarial annex (contains a prompt-injection attempt, on purpose).

For a clean demo:  make clean && make up && make demo

    python3 scripts/seed_demo.py [--base-url http://localhost:3000]
"""

import argparse
import sys
from pathlib import Path

from marea_api import ApiError, upload_pdf, wait_until_ready

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
HOME_TITLE = "Marea Hogar Plus · Condicionado General"


def load(
    base_url: str, file: str, *, title: str | None = None, version_of: str | None = None
) -> str:
    path = SAMPLES / file
    document = upload_pdf(
        base_url, path.read_bytes(), path.name, title=title, new_version_of=version_of
    )
    if document["deduplicated"]:
        print(f"= {path.name}: ya estaba cargado (mismo contenido), se reutiliza")
    document = wait_until_ready(base_url, document["id"])
    print(
        f"✓ {document['title']} · v{document['version']}: "
        f"{document['page_count']} págs, {document['chunk_count']} fragmentos"
    )
    return str(document["id"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default="http://localhost:3000")
    base_url = parser.parse_args().base_url
    try:
        home = load(base_url, "marea-hogar-condicionado-2025.pdf", title=HOME_TITLE)
        load(base_url, "marea-hogar-condicionado-2026.pdf", version_of=home)
        load(
            base_url, "marea-auto-condicionado-2025.pdf", title="Marea Auto · Condicionado General"
        )
        load(
            base_url,
            "adversarial/anexo-condiciones-especiales.pdf",
            title="Anexo de Condiciones Especiales (prueba de seguridad)",
        )
    except (ApiError, OSError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    print(f"Listo. Abre {base_url} y pregunta, por ejemplo:")
    print("  «¿Qué franquicia se aplica a los daños por agua en la vivienda habitual?»")
    return 0


if __name__ == "__main__":
    sys.exit(main())
