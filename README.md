# Despacho Diario — Boletín Oficial de Córdoba

Sistema automático: cada mañana hábil descarga el Boletín, lo analiza con
la API de Anthropic según `instrucciones.md`, publica la app y avisa por
Telegram y correo.

## Qué hay en esta carpeta

    boletin.py                  → el motor (corre una vez por día)
    instrucciones.md            → el cerebro editable (criterios y extensión)
    requirements.txt            → dependencias de Python
    .github/workflows/despacho.yml → el despertador (lun-vie 07:30, 09:30, 11:30)
    docs/index.html             → la app (funciona sola como demo si la abrís)
    docs/data/                  → acá se van guardando los despachos diarios

## Pasos para mañana (en orden, ~20 minutos)

**1. Cargar créditos y crear la clave** — en console.anthropic.com:
"Agregar fondos" (con USD 5-10 alcanza para meses) → menú "Claves de API"
→ "Crear clave" → nombre `boletin-cordoba` → copiarla y guardarla
(se muestra una sola vez). NO tocar "Crear un agente".

**2. Crear el bot de Telegram** — en Telegram, hablarle a **@BotFather**:
`/newbot` → elegir nombre → guardar el **token** que te da. Después
mandale cualquier "hola" a tu bot nuevo, y abrí en el navegador:
`https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
→ buscá `"chat":{"id": UN_NÚMERO}` y anotá ese número (tu **chat_id**).

**3. Crear el repositorio** — en github.com: "New repository", nombre
`despacho-cordoba`, **público** (necesario para GitHub Pages gratis;
todo el contenido es información pública del Boletín). Subir TODOS los
archivos de esta carpeta respetando la estructura.

**4. Cargar los secretos** — en el repo: Settings → Secrets and
variables → Actions → "New repository secret", uno por uno:

    ANTHROPIC_API_KEY    (obligatorio — la clave del paso 1)
    TELEGRAM_BOT_TOKEN   (paso 2)
    TELEGRAM_CHAT_ID     (paso 2)
    GMAIL_USUARIO        (opcional — tu Gmail)
    GMAIL_CLAVE_APP      (opcional — clave de aplicación, no tu contraseña)
    APP_URL              (opcional — la URL del paso 5, para los avisos)

**5. Activar la página** — Settings → Pages → "Deploy from a branch"
→ rama `main`, carpeta `/docs` → Save. En unos minutos la app vive en:
`https://TU-USUARIO.github.io/despacho-cordoba/`
(mientras no haya datos, muestra la demostración).

**6. Descarga** — ya está resuelta: `boletin.py` construye la URL directa
de cada sección con el patrón verificado del sitio
(`.../wp-content/4p96humuzp/AAAA/MM/N_Secc_DDMMAA.pdf`). Si el boletín
del día aún no salió, no falla: sale en silencio y reintenta después.
No hay nada que pegar.

**7. Probar** — pestaña Actions → "Despacho Diario" → "Run workflow".
Mirar el log: si todo va bien, aparece el JSON en `docs/data/`, la app
muestra "Datos reales" y llega el aviso de Telegram.

## Si el sitio del Boletín bloquea a GitHub (plan B)

El sitio tiene protección anti-bots. Si la descarga falla desde GitHub
Actions pero funciona desde tu Mac, plan B sin perder nada: tu Mac corre
`python boletin.py` con launchd (como hasta ahora) y hace `git push` de
`docs/data/` — la página, el buscador y los avisos siguen exactamente
igual. Solo cambia dónde se ejecuta el motor.

## Costos y control

- La API se paga con los créditos prepagos de la Console (separado del
  plan de claude.ai). Este sistema consume centavos por día hábil.
- Recarga automática: dejarla desactivada. Si el crédito se acaba, el
  sistema se frena solo, jamás cobra sin permiso.
- Para pausar todo: Actions → "Despacho Diario" → ⋯ → "Disable workflow".

## Ajustes del día a día

- Cambiar extensión, criterios o temas vigilados → editar
  `instrucciones.md` (los lugares editables están marcados con ←) y
  hacer commit. Rige desde la corrida siguiente. No se toca código.
- Ver el gasto real → console.anthropic.com → Usage.
