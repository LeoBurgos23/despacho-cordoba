#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DESPACHO DIARIO — Boletín Oficial de la Provincia de Córdoba
============================================================
Corre una vez por día (GitHub Actions o launchd). Es idempotente:
si el despacho de hoy ya existe, no hace nada; si el boletín aún no
se publicó, termina en silencio y la próxima corrida reintenta.

Flujo: descargar PDFs → extraer texto con marcadores de página →
llamar a la API con instrucciones.md → guardar JSON del día +
actualizar índice → avisar por Telegram y correo.

Variables de entorno (en GitHub van como Secrets):
  ANTHROPIC_API_KEY   (obligatoria)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID          (opcionales)
  GMAIL_USUARIO, GMAIL_CLAVE_APP                (opcionales)
  APP_URL  → link de la app para incluir en los avisos (opcional)
"""

import datetime as dt
import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from io import BytesIO
from pathlib import Path

import requests
from pypdf import PdfReader

import anthropic

# ----------------------------- Configuración -----------------------------

TZ_CORDOBA = dt.timezone(dt.timedelta(hours=-3))
HOY = dt.datetime.now(TZ_CORDOBA).date()

RAIZ = Path(__file__).resolve().parent
DOCS = RAIZ / "docs"
DATA = DOCS / "data"

MODELO = "claude-haiku-4-5"      # el más económico: ideal para esta tarea diaria
MAX_TOKENS_SALIDA = 16000

# Secciones del Boletín a procesar. 1ª = Legislación y decretos,
# 4ª = Concesiones y licitaciones. Agregá "2" o "3" si algún día
# querés judiciales/sociedades (sube el costo por volumen).
SECCIONES = ["1", "4"]

CABECERAS_NAVEGADOR = {
   CABECERAS_NAVEGADOR = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/138.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Referer": "https://boletinoficial.cba.gov.ar/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
}
}
# ------------------------------- Descarga --------------------------------

# Patrón de URL de los PDF del Boletín, verificado contra ediciones reales:
#   https://boletinoficial.cba.gov.ar/wp-content/4p96humuzp/2026/07/1_Secc_070726.pdf
#                                                          └año┘└mes┘ │       └DDMMAA┘
#                                                                     └ número de sección
BASE_PDF = "https://boletinoficial.cba.gov.ar/wp-content/4p96humuzp"


def _url_pdf(fecha: dt.date, seccion: str) -> str:
    """Arma la URL del PDF de una sección para una fecha dada."""
    return (f"{BASE_PDF}/{fecha.year}/{fecha.month:02d}/"
            f"{seccion}_Secc_{fecha.strftime('%d%m%y')}.pdf")


def _bajar_pdf(url: str):
    """
    Devuelve los bytes del PDF, o None si todavía no está publicado.
    Distingue tres casos: no existe (404), existe pero no es un PDF real
    (el sitio a veces responde una página de error con código 200), y
    descarga correcta.
    """
    try:
        r = requests.get(url, headers=CABECERAS_NAVEGADOR, timeout=90)
    except requests.RequestException as e:
        print(f"   · error de red en {url}: {e}")
        return None

    if r.status_code in (403, 404):
        print(f"   · el servidor respondió {r.status_code}")
        return None
    r.raise_for_status()

    if not r.content.startswith(b"%PDF"):
        print(f"   · la respuesta de {url} no es un PDF (¿aún no publicado?)")
        return None

    return r.content


def descargar_pdfs():
    """
    Descarga las secciones configuradas en SECCIONES de la edición de HOY.

    Devuelve [(seccion, bytes_del_pdf, url), ...] o [] si el boletín
    todavía no salió (en ese caso el workflow reintenta más tarde).

    La 1ª Sección (Legislación) es obligatoria: si no está, se considera
    que la edición aún no se publicó. Las demás son opcionales, porque
    hay días en que una sección no se edita.
    """
    pdfs = []

    for seccion in SECCIONES:
        url = _url_pdf(HOY, seccion)
        print(f"→ Sección {seccion}: {url}")
        contenido = _bajar_pdf(url)

        if contenido is None:
            if seccion == SECCIONES[0]:
                print("   La edición de hoy todavía no está publicada.")
                return []
            print(f"   Sección {seccion} no disponible hoy; se continúa sin ella.")
            continue

        print(f"   ✓ {len(contenido) // 1024} KB descargados")
        pdfs.append((seccion, contenido, url))

    return pdfs

# --------------------------- Extracción de texto --------------------------

def extraer_texto(pdf_bytes: bytes) -> str:
    """Texto del PDF con marcadores '=== PÁGINA N ===' para que la IA
    pueda informar la página exacta de cada norma."""
    lector = PdfReader(BytesIO(pdf_bytes))
    paginas = []
    for i, pagina in enumerate(lector.pages, start=1):
        paginas.append(f"=== PÁGINA {i} ===\n{(pagina.extract_text() or '').strip()}")
    return "\n\n".join(paginas)


def detectar_numero_boletin(texto: str) -> str:
    m = re.search(r"BOLET[ÍI]N\s+OFICIAL[^\n]{0,40}?N[°ºo]?\s*([\d\.]+)", texto, re.I)
    return m.group(1) if m else "s/d"

# ------------------------------ Llamado a la API ---------------------------

def llamar_api(texto_boletin: str) -> dict:
    instrucciones = (RAIZ / "instrucciones.md").read_text(encoding="utf-8")
    cliente = anthropic.Anthropic()  # toma ANTHROPIC_API_KEY del entorno

    respuesta = cliente.messages.create(
        model=MODELO,
        max_tokens=MAX_TOKENS_SALIDA,
        messages=[{
            "role": "user",
            "content": instrucciones + "\n\n=== BOLETÍN DE HOY ===\n\n" + texto_boletin,
        }],
    )
    bruto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
    bruto = re.sub(r"^```(?:json)?\s*|\s*```$", "", bruto)  # por si envuelve en ```
    try:
        return json.loads(bruto)
    except json.JSONDecodeError:
        # Guardar la salida cruda para diagnóstico y abortar con error real.
        (RAIZ / f"salida_invalida_{HOY}.txt").write_text(bruto, encoding="utf-8")
        raise

# ------------------------------- Persistencia -----------------------------

def _url_de_seccion(etiqueta_seccion: str, urls: dict) -> str:
    """'1ª Sección · Legislación' → urls['1'] (o la primera disponible)."""
    m = re.match(r"\s*(\d)", etiqueta_seccion or "")
    if m and m.group(1) in urls:
        return urls[m.group(1)]
    return next(iter(urls.values()), "https://boletinoficial.cba.gov.ar/")


def guardar(despacho: dict, urls: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    ahora = dt.datetime.now(TZ_CORDOBA).strftime("%H:%M")

    despacho["fecha"] = str(HOY)
    despacho["hora_procesado"] = ahora
    despacho["estado"] = "publicado"

    # Completar URL oficial en normas y movimientos según su sección
    for n in despacho.get("normas", []):
        n.setdefault("pagina", 1)
        n["url_oficial"] = _url_de_seccion(n.get("seccion", "1"), urls)
    for m in despacho.get("movimientos", []):
        m.setdefault("pagina", 1)
        m["url_oficial"] = _url_de_seccion("1", urls)

    # 1) Despacho del día
    (DATA / f"{HOY}.json").write_text(
        json.dumps(despacho, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    # 2) Índice acumulado (solo metadatos, para el buscador)
    ruta_indice = DATA / "indice.json"
    indice = json.loads(ruta_indice.read_text(encoding="utf-8")) if ruta_indice.exists() else []
    existentes = {(e.get("fecha"), e.get("numero")) for e in indice}
    nro = despacho.get("numero_boletin", "s/d")

    nuevos = []
    for e in despacho.get("indice_nuevas", []):
        nuevos.append({
            "fecha": str(HOY), "boletin": nro,
            "tipo": e.get("tipo", ""), "numero": e.get("numero", ""),
            "titulo": e.get("titulo", ""), "pagina": e.get("pagina", 1),
            "url": _url_de_seccion(e.get("seccion", "1"), urls),
        })
    for m in despacho.get("movimientos", []):
        nuevos.append({
            "fecha": str(HOY), "boletin": nro,
            "tipo": m.get("tipo", "Designación"), "numero": m.get("instrumento", ""),
            "titulo": f"{m.get('titulo', '')} — {m.get('organismo', '')}".strip(" —"),
            "pagina": m.get("pagina", 1), "url": m.get("url_oficial", ""),
        })
    indice = [e for e in nuevos if (e["fecha"], e["numero"]) not in existentes] + indice
    ruta_indice.write_text(json.dumps(indice, ensure_ascii=False, indent=0), encoding="utf-8")

    # 3) Puntero "ultimo.json" con el archivo de titulares
    ruta_ultimo = DATA / "ultimo.json"
    ultimo = json.loads(ruta_ultimo.read_text(encoding="utf-8")) if ruta_ultimo.exists() else {"archivo": []}
    titulares = [n.get("titulo", "") for n in despacho.get("normas", [])[:2]]
    entrada = {"fecha": str(HOY), "numero": nro,
               "titular": ("; ".join(t for t in titulares if t))[:160] + "."}
    archivo = [e for e in ultimo.get("archivo", []) if e.get("fecha") != str(HOY)]
    ultimo = {"hoy": str(HOY), "archivo": ([entrada] + archivo)[:90]}
    ruta_ultimo.write_text(json.dumps(ultimo, ensure_ascii=False, indent=1), encoding="utf-8")

# --------------------------------- Avisos ---------------------------------

def avisar(despacho: dict) -> None:
    nro = despacho.get("numero_boletin", "s/d")
    app_url = os.environ.get("APP_URL", "")
    texto = despacho.get("telegram") or (
        f"📋 Salió el B.O. N° {nro} — resumen listo."
    )
    if app_url:
        texto += f"\n{app_url}"

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": texto},
                timeout=30,
            ).raise_for_status()
            print("Aviso de Telegram enviado.")
        except Exception as e:  # el aviso nunca debe tirar abajo la corrida
            print(f"⚠️  Telegram falló: {e}")

    usuario = os.environ.get("GMAIL_USUARIO")
    clave = os.environ.get("GMAIL_CLAVE_APP")
    if usuario and clave:
        try:
            cuerpo = "\n\n".join(despacho.get("sintesis_juridica", []) +
                                 despacho.get("sintesis_politica", []))
            if app_url:
                cuerpo += f"\n\nVer el despacho completo: {app_url}"
            msj = MIMEText(cuerpo, "plain", "utf-8")
            msj["Subject"] = f"Despacho Diario — B.O. N° {nro} ({HOY})"
            msj["From"] = usuario
            msj["To"] = usuario
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
                s.login(usuario, clave)
                s.send_message(msj)
            print("Correo enviado.")
        except Exception as e:
            print(f"⚠️  Correo falló: {e}")

# ---------------------------------- Main ----------------------------------

def main() -> None:
    print(f"— Despacho Diario · {HOY} —")

    if (DATA / f"{HOY}.json").exists():
        print("El despacho de hoy ya está publicado; nada que hacer.")
        return

    try:
        pdfs = descargar_pdfs()
    except NotImplementedError as e:
        print(f"⚠️  {e}")
        return

    if not pdfs:
        print("El boletín de hoy aún no está publicado; la próxima corrida reintenta.")
        return

    urls, partes = {}, []
    for seccion, contenido, url in pdfs:
        urls[seccion] = url
        partes.append(f"\n\n##### SECCIÓN {seccion} #####\n\n" + extraer_texto(contenido))
    texto = "".join(partes)

    nro = detectar_numero_boletin(texto)
    print(f"Boletín N° {nro} · ~{len(texto) // 1000} mil caracteres · consultando {MODELO}…")

    despacho = llamar_api(texto)
    despacho.setdefault("numero_boletin", nro)

    guardar(despacho, urls)
    avisar(despacho)
    print("✅ Despacho generado y guardado en docs/data/.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
