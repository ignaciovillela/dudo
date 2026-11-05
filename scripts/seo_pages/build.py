#!/usr/bin/env python3
"""Genera las páginas de contenido SEO en static/pages/ y el sitemap.

Uso:  python scripts/seo_pages/build.py
Cada página = un fragmento <slug>.body.html + los metadatos de PAGES.
"""
import html
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(__file__).resolve().parent
OUT = ROOT / "static" / "pages"
BASE = "https://dudo.igna.cl"
TODAY = date.today().isoformat()

PAGES = [
    {
        "slug": "como-jugar-dudo",
        "nav": "Cómo jugar",
        "title": "Dudo o Perudo: reglas y cómo jugar | Dudo online",
        "h1": "Cómo jugar al Dudo (Perudo): reglas completas",
        "description": "Aprende a jugar Dudo (Perudo, cacho o Liar's Dice): reglas completas paso a paso, apuestas, dudo, calzo, gavilán y los nombres de las pintas. Juego de dados con apuestas.",
        "lead": "<strong>Dudo</strong> —en Chile, \"los cachos\" o simplemente \"cacho\"— es un juego de dados de apuestas y engaño. Es el mismo juego que se conoce como <a href=\"/perudo\"><strong>Perudo</strong></a>, <strong>Cachito</strong>, <strong>Pico</strong>, <strong>Dadinho</strong> o, en inglés, <a href=\"/liars-dice\"><strong>Liar's Dice</strong></a>. Aquí tienes las reglas del Dudo paso a paso, tal como funcionan en <a href=\"/jugar-dudo-online\">Dudo online</a>, donde puedes jugarlo gratis y sin registro.",
        "faq": [
            ("¿Qué es Dudo o el juego de los cachos?", "Es un juego de dados de apuestas y engaño. Cada jugador tiene 5 dados ocultos bajo un cacho (vaso) y, por turnos, se apuesta cuántos dados de una pinta hay entre todos los de la mesa. Quien no cree la apuesta dice «¡Dudo!». Gana el último jugador que conserva dados."),
            ("¿Dudo, Cacho y Perudo son el mismo juego?", "Sí, son nombres y variantes del mismo juego. También se le conoce como Cachito, Pico, Dadinho y, en inglés, Liar's Dice o Pirate's Dice. Las reglas pueden variar levemente según el país o la mesa."),
            ("¿Qué significa calzar?", "Calzar es afirmar que la apuesta anterior es exacta: hay exactamente esa cantidad de dados de esa pinta en la mesa. Si aciertas no pierdes dado (y puedes recuperar uno); si fallas, pierdes un dado."),
            ("¿Qué es el gavilán?", "El gavilán es dudar o calzar fuera de tu turno. En Dudo online se puede activar o desactivar al crear la sala."),
            ("¿Cómo funcionan los ases?", "Los ases (1) son comodines: cuentan como cualquier pinta cuando se apuesta por otra cara. En una apuesta de ases solo cuentan los dados con cara 1. Al cambiar entre ases y otras pintas la cantidad mínima se ajusta (de normales a ases, la mitad hacia arriba; de ases a normales, el doble más uno)."),
            ("¿Cuántas personas pueden jugar?", "De 2 a 6 jugadores por sala, más espectadores. Puedes completar la mesa con bots de cinco niveles de dificultad."),
            ("¿Se puede jugar Dudo online gratis?", "Sí. En dudo.igna.cl se juega gratis, desde el celular o el computador y sin registrarse: creas una sala y compartes el enlace con tus amigos."),
        ],
    },
    {
        "slug": "perudo",
        "nav": "Perudo",
        "title": "Perudo: reglas, cómo jugar y diferencias con el Dudo",
        "h1": "Perudo: reglas y cómo jugar",
        "description": "Reglas del Perudo explicadas en español: cómo se juega, apuestas, ases comodín, dudo y calzo. Diferencias entre Perudo, Dudo y cacho, y dónde jugarlo online gratis.",
        "lead": "El <strong>Perudo</strong> es el <a href=\"/como-jugar-dudo\">Dudo</a> con otro nombre: el mismo juego de dados con apuestas, conocido también como <strong>cacho</strong>, <strong>Cachito</strong> o <a href=\"/liars-dice\">Liar's Dice</a>. Te explicamos sus reglas y en qué se diferencian las versiones.",
        "faq": [
            ("¿Perudo y Dudo son lo mismo?", "Sí. Perudo es el nombre con el que el juego se conoce internacionalmente y Dudo (o cacho) el que se usa en Chile y otros países de Sudamérica. Las reglas básicas son las mismas; cambian detalles según la mesa."),
            ("¿Cuántos dados se usan en el Perudo?", "Cada jugador empieza con 5 dados y un vaso para ocultarlos."),
            ("¿Los ases son comodines en el Perudo?", "Sí, los ases (1) cuentan como cualquier cara, salvo cuando se apuesta por ases."),
            ("¿Dónde puedo jugar Perudo online gratis?", "En dudo.igna.cl puedes jugarlo gratis desde el navegador, sin registro, con amigos o contra bots."),
        ],
    },
    {
        "slug": "liars-dice",
        "nav": "Liar's Dice",
        "title": "Liar's Dice en español: reglas y cómo jugar online",
        "h1": "Liar's Dice en español: reglas y cómo jugar",
        "description": "Liar's Dice (dados del mentiroso) explicado en español: reglas, vocabulario inglés–español y cómo jugarlo online gratis. Es el Dudo, Perudo o cacho.",
        "lead": "<strong>Liar's Dice</strong> es el nombre en inglés del juego que en Chile se llama <a href=\"/como-jugar-dudo\"><strong>Dudo</strong></a> o cacho, y que se conoce como <a href=\"/perudo\">Perudo</a> en otros países. Aquí tienes las reglas en español y cómo jugarlo online.",
        "faq": [
            ("¿Qué es Liar's Dice?", "Es un juego de dados de engaño en el que cada jugador oculta sus dados y se apuesta sobre cuántos hay en la mesa. En español se conoce como Dudo, cacho o Perudo."),
            ("¿Cómo se dice Liar's Dice en español?", "Dudo, cacho (o cachos), Cachito o Perudo, según el país. También se traduce literalmente como dados del mentiroso."),
            ("¿Hay una versión online de Liar's Dice en español?", "Sí: dudo.igna.cl es una versión gratuita en español, con salas para jugar con amigos y bots."),
        ],
    },
    {
        "slug": "jugar-dudo-online",
        "nav": "Jugar online",
        "title": "Jugar Dudo online gratis, con amigos o contra bots",
        "h1": "Jugar Dudo online gratis",
        "description": "Juega Dudo online gratis y sin registro: crea una sala, invita a tus amigos por WhatsApp o practica contra bots. Funciona en celular y computador. También llamado Perudo o cacho.",
        "lead": "Juega <strong>Dudo online</strong> —el juego de los cachos, también llamado <a href=\"/perudo\">Perudo</a>— <strong>gratis</strong>, desde el navegador y sin registrarte. Crea una sala, comparte el enlace y juega con tus amigos o contra bots.",
        "faq": [
            ("¿Se puede jugar Dudo online gratis?", "Sí. Dudo online es gratuito y no necesita registro ni descarga."),
            ("¿Puedo jugar Dudo en el celular?", "Sí, la web funciona en celulares y computadores sin instalar nada."),
            ("¿Puedo jugar Dudo contra bots?", "Sí. Hay bots de cinco niveles: fácil, medio, difícil, muy difícil y experto."),
            ("¿Cómo invito a mis amigos?", "Al crear una sala se genera un código y un enlace de invitación que puedes compartir por WhatsApp o cualquier app."),
            ("¿Cuántos jugadores pueden entrar a una sala?", "Hasta 6 jugadores, más espectadores."),
        ],
    },
    {
        "slug": "estrategia-dudo",
        "nav": "Estrategia",
        "title": "Estrategia del Dudo: probabilidades y trucos para ganar",
        "h1": "Estrategia del Dudo: probabilidades y trucos",
        "description": "Cómo ganar al Dudo (Perudo, cacho): probabilidades con ases comodín, la regla de dividir por tres, cuándo calzar y consejos de bluff. Tablas incluidas.",
        "lead": "Cómo ganar al <strong>Dudo</strong> (o <a href=\"/perudo\">Perudo</a>, o cacho): las probabilidades que importan, cuándo dudar, cuándo calzar y cómo bluffear.",
        "faq": [
            ("¿Cuántos dados de una pinta suele haber en la mesa?", "Con los ases como comodines, cada dado cuenta para una cara normal con probabilidad 1/3, así que esperas un tercio de los dados de la mesa. Para ases, un sexto."),
            ("¿Cuándo conviene calzar?", "Cuando quedan pocos dados en la mesa o tu mano reduce la incertidumbre. Calzar exige un número exacto, por lo que incluso en el mejor caso acierta menos de una de cada cuatro veces."),
            ("¿Cómo practico contra rivales difíciles?", "Con los bots de Dudo online: el nivel experto modela a los rivales y bluffea a propósito."),
        ],
    },
    {
        "slug": "glosario-dudo",
        "nav": "Glosario",
        "title": "Glosario del Dudo: dudo, calzo, gavilán, cacho y pintas",
        "h1": "Glosario del Dudo: qué significa cada término",
        "description": "Qué significan dudo, calzo, gavilán, pasar, cacho, pinta, tonto, tren, cuadra, quina y cena en el juego de dados Dudo (Perudo, cacho). Glosario completo.",
        "lead": "Qué significan <strong>dudo</strong>, <strong>calzo</strong>, <strong>gavilán</strong>, <strong>cacho</strong> y los nombres de las pintas en el juego de dados Dudo.",
        "faq": [
            ("¿Qué significa calzar en el Dudo?", "Afirmar que la apuesta anterior es exacta. Si aciertas no pierdes dado y puedes recuperar uno; si fallas, pierdes uno."),
            ("¿Qué es el cacho?", "El vaso donde se agitan y ocultan los dados. En Chile también es el nombre del juego."),
            ("¿Cómo se llaman las caras del dado en el Dudo?", "As (1), tonto (2), tren (3), cuadra o alemán (4), quina o chincol (5) y cena (6)."),
        ],
    },
]

GUIDES = [(p["slug"], p["nav"]) for p in PAGES]


def esc(s):
    return html.escape(s, quote=True)


def strip_tags(s):
    import re
    return re.sub(r"<[^>]+>", "", s)


def render(page):
    slug = page["slug"]
    url = f"{BASE}/{slug}"
    body = (SRC / f"{slug}.body.html").read_text(encoding="utf-8")
    faq = page["faq"]
    faq_html = "".join(
        f"<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>\n    " for q, a in faq
    )
    others = "".join(
        f'<a href="/{s}">{esc(n)}</a>' for s, n in GUIDES if s != slug
    )
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Dudo", "item": BASE + "/"},
                {"@type": "ListItem", "position": 2, "name": page["nav"], "item": url},
            ]},
            {"@type": "Article", "headline": page["h1"], "inLanguage": "es-CL",
             "description": page["description"], "dateModified": TODAY,
             "about": "Dudo, juego de dados también llamado Cacho, Perudo, Cachito o Liar's Dice",
             "author": {"@type": "Person", "name": "Ignacio Villela", "url": "https://github.com/ignaciovillela"},
             "image": BASE + "/static/og-cover.png", "mainEntityOfPage": url},
            {"@type": "FAQPage", "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq]},
        ],
    }
    toc = ""
    return f"""<!DOCTYPE html>
<html lang="es-CL">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{esc(page["title"])}</title>
  <meta name="description" content="{esc(page["description"])}" />
  <meta name="robots" content="index, follow, max-image-preview:large" />
  <meta name="theme-color" content="#0d2b18" />
  <link rel="canonical" href="{url}" />
  <link rel="icon" type="image/svg+xml" href="/static/favicon.svg" />
  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png" />
  <meta property="og:type" content="article" />
  <meta property="og:locale" content="es_CL" />
  <meta property="og:site_name" content="Dudo" />
  <meta property="og:url" content="{url}" />
  <meta property="og:title" content="{esc(page["title"])}" />
  <meta property="og:description" content="{esc(page["description"])}" />
  <meta property="og:image" content="{BASE}/static/og-cover.png" />
  <meta name="twitter:card" content="summary_large_image" />
  <script type="application/ld+json">
{json.dumps(ld, ensure_ascii=False, indent=2)}
  </script>
  <link rel="stylesheet" href="/static/pages.css" />
</head>
<body>
  <header>
    <a class="logo" href="/" aria-label="Dudo, ir al juego">DUDO</a>
    <a class="cta" href="/">Jugar ahora</a>
  </header>

  <main>
    <nav aria-label="Migas de pan" style="font-size:.9rem;color:var(--dim)"><a href="/">Dudo</a> › {esc(page["nav"])}</nav>

    <h1>{esc(page["h1"])}</h1>
    <p class="lead">{page["lead"]}</p>

    {body}

    <h2 id="faq">Preguntas frecuentes</h2>
    {faq_html}
    <p class="final"><a class="cta" href="/">Crear sala y jugar</a></p>
  </main>

  <footer>
    <p class="guides"><strong>Guías:</strong> {others}</p>
    <p><a href="/">Dudo</a> · Juego de los cachos (Cacho, Perudo, Liar's Dice) online, gratis y sin registro · <a href="https://github.com/ignaciovillela/dudo">Código en GitHub</a></p>
  </footer>
</body>
</html>
"""


def sitemap():
    urls = [("", "1.0")] + [(f"/{p['slug']}", "0.8" if p["slug"] in ("como-jugar-dudo", "perudo", "jugar-dudo-online") else "0.6") for p in PAGES]
    items = "".join(
        f"  <url>\n    <loc>{BASE}{path or '/'}</loc>\n    <lastmod>{TODAY}</lastmod>\n    <changefreq>monthly</changefreq>\n    <priority>{prio}</priority>\n  </url>\n"
        for path, prio in urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{items}</urlset>\n'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.html"):
        old.unlink()
    for page in PAGES:
        (OUT / f"{page['slug']}.html").write_text(render(page), encoding="utf-8")
    (ROOT / "static" / "sitemap.xml").write_text(sitemap(), encoding="utf-8")
    print(f"{len(PAGES)} páginas generadas en {OUT}")


if __name__ == "__main__":
    main()
