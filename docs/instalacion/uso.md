# Usar y mantener la instalación

Lo común a Mac, Windows y servidor, una vez instalado con su guía
([`README.md`](README.md)). Los comandos van en la carpeta del repo: en
Windows, en la terminal de Ubuntu; en el servidor, por SSH.

## Primer rastreo

**Desde la interfaz:** crea un cliente, un perfil de rastreo con la URL de
inicio y dale a «Lanzar ahora». Empieza con un sitio pequeño o con pocas URLs.

**Desde la terminal**, con la configuración de un cliente en
`projects/<cliente>/config.json` ([`projects/README.md`](../../projects/README.md)).
Para probar que todo funciona, la web de Lin3s con 20 URLs:

```bash
cp -r projects/_ejemplo projects/prueba
# en projects/prueba/config.json, cambia "_seeds" por ["https://lin3s.com/"]
export API_TOKEN=$(grep '^API_TOKEN=' .env | cut -d= -f2 | tr -d '\r')
python3 scripts/lanzar_job.py prueba --canary --set max_urls=20
```

Imprime el id del rastreo; en la interfaz aparece en marcha y, en uno o dos
minutos, terminado con sus 20 URLs y sus incidencias. Con un cliente de
verdad, **siempre el canario primero** (`--canary`: 300 URLs como mucho) y
después el completo (sin `--canary`).

Las carpetas de `projects/` de los clientes no están en git (solo
`_ejemplo/`): pídeselas a quien lleve el cliente o cógelas del Drive.

Qué hace el worker mientras rastrea:

```bash
docker compose logs -f crawler
```

Al acabar el rastreo, el mismo worker lanza el análisis, y el censo aparece en
la interfaz con sus incidencias.

## El día a día

| Para… | Comando |
|---|---|
| Arrancar (tras reiniciar, Docker lo hace solo si está abierto) | `docker compose up -d` |
| Parar sin perder datos | `docker compose stop` |
| Ver logs | `docker compose logs -f api` o `docker compose logs -f crawler` |
| Actualizar a la última versión | [Abajo](#actualizar-a-la-última-versión): cinco pasos, y el orden importa |
| Abrir la base de datos | `docker compose exec postgres psql -U crawler -d crawler_db` |
| Re-analizar un censo | `docker compose exec crawler python -m analysis.analyzer <job_id>` |
| Borrar las imágenes viejas (no toca los datos) | `docker image prune -f` |
| Borrarlo **todo** (también los datos) | `docker compose down -v` |

`docker compose down` (sin `-v`) quita los contenedores y conserva los datos.
Con `-v` se borran la base de datos, los enlaces archivados y las llaves
subidas, y no hay vuelta atrás.

## Actualizar a la última versión

```bash
git pull
docker compose build
docker compose run --rm --no-deps --entrypoint python crawler scripts/migrate_add_missing_columns.py
docker compose up -d
docker compose exec api python scripts/init_db.py
```

Es lo mismo que hace el despliegue de producción, en el mismo orden:

- **Las columnas nuevas, antes de arrancar el código nuevo.** La API crea al
  arrancar las tablas que falten, pero no añade columnas a las que ya existen.
  Si el código nuevo espera una columna que tu base de datos no tiene, la API
  da error 500. `migrate_add_missing_columns.py` añade todas las que falten
  (nunca borra ni cambia nada) y `init_db.py` aplica el resto de migraciones.
  Repetir cualquiera de los dos no hace nada.
- **Actualizar mata el rastreo que esté en marcha**: `up -d` recrea el
  contenedor del worker. Espera a que acabe o cancélalo.

## Integraciones (opcionales)

Nada de esto hace falta para rastrear y auditar. Las claves van en el `.env` o
se suben desde la ficha del cliente; nunca en la base de datos ni en el
código. Tras tocar el `.env`, `docker compose up -d` para que lo lean los
contenedores.

| Integración | Qué poner | Más detalle |
|---|---|---|
| Search Console | Se sube la llave de la cuenta de servicio, o tu login de Google ([abajo](#search-console-con-tu-login-de-google)), desde la ficha del cliente | [`despliegue-y-entorno.md`](../referencia/despliegue-y-entorno.md) |
| Slack | Token del bot (`xoxb-…`) en la ficha del cliente, o `SLACK_<NOMBRE>` en `.env` | `.env.example` |
| Capa de IA (Jev) | `DECISIONS_ENABLED=1`, `OPENROUTER_API_KEY` y `ENRICHMENT_TOKEN`. **Cuesta dinero**: déjala apagada salvo que vayas a probarla | `.env.example` y [`decisiones/`](../decisiones/README.md) |
| MCP (Claude Code contra tu instalación) | En local, `CRAWLER_API_URL=http://127.0.0.1:8000` y tu token en `CRAWLER_API_TOKEN`. En un servidor con dominio, el MCP remoto en `https://<dominio>/mcp` | [`mcp_servidor/README.md`](../../mcp_servidor/README.md) |

### Search Console con tu login de Google

Si ya tienes acceso a las propiedades con tu usuario (el mismo login con el
que conectas los MCP de Search Console), puedes subir ese login en vez de una
cuenta de servicio: no hace falta dar de alta nada en cada propiedad. Se sube
igual, desde la ficha del cliente o desde Ajustes, como un JSON con esta forma:

```json
{
  "type": "authorized_user",
  "client_id": "….apps.googleusercontent.com",
  "client_secret": "…",
  "refresh_token": "1//…",
  "account": "tu@agencia.com"
}
```

- **Con `gcloud`:** `gcloud auth application-default login
  --client-id-file=client_secret.json
  --scopes=https://www.googleapis.com/auth/webmasters.readonly,https://www.googleapis.com/auth/cloud-platform`
  abre el navegador y deja el JSON en
  `~/.config/gcloud/application_default_credentials.json` (en Windows,
  `%APPDATA%\gcloud\`). El `client_secret.json` es el de un cliente OAuth de
  escritorio de tu proyecto de Google Cloud.
- **Desde un MCP ya conectado:** `client_id` y `client_secret` salen de su
  `client_secret….json` (clave `installed`) y `refresh_token` del token que
  guardó tras el login.

`account` es opcional: es lo que la interfaz enseña en lugar del email de la
cuenta de servicio. El refresh token da acceso a todo lo que ve ese usuario en
Search Console: trátalo como una contraseña.

## Problemas frecuentes

Los propios de cada plataforma están al final de su guía.

**`api` en `Restarting` y en los logs `type "vector" does not exist`.** Tu
copia del repo es anterior al 2026-10-29, cuando la API aún no creaba la
extensión sola: actualiza ([arriba](#actualizar-a-la-última-versión)), o pasa
a mano `docker compose run --rm api python scripts/init_db.py` y
`docker compose restart api crawler`.

**`/api/jobs` da error 500 después de actualizar, con `column … does not
exist` en `docker compose logs api`.** Te has saltado el paso de las columnas:
`docker compose run --rm --no-deps --entrypoint python crawler scripts/migrate_add_missing_columns.py`.

**`port is already allocated` al arrancar.** Algo ya usa el 8000, el 5432
(otro Postgres) o el 6379 (otro Redis). Para eso otro o cambia los puertos
sin tocar `docker-compose.yml`: crea un `docker-compose.override.yml`
(Compose lo lee solo y git lo ignora; en un servidor, añádelo al que ya
tienes):

```yaml
services:
  postgres:
    ports: !override ["127.0.0.1:15432:5432"]
  redis:
    ports: !override ["127.0.0.1:16379:6379"]
  api:
    ports: !override ["127.0.0.1:18000:8000"]
```

y entra por <http://127.0.0.1:18000>. Con `lanzar_job.py`, añade
`--api http://localhost:18000`.

**La interfaz dice que la clave no es válida, o la API da 503.** El
`API_TOKEN` del `.env` está vacío o tiene menos de 24 caracteres, o lo
cambiaste sin recrear la API (`docker compose up -d api`).

**`lanzar_job.py` dice `Falta API_TOKEN en el entorno`.** No has hecho el
`export API_TOKEN=…` en esa terminal (vale solo para la terminal donde se
hace), o la clave no es la del `.env` del servidor al que apuntas.

**`password authentication failed for user "crawler"`.** Cambiaste
`POSTGRES_PASSWORD` después del primer arranque. O la devuelves a la de antes,
o borras los datos y empiezas de cero con `docker compose down -v`.

**El worker se muere (`Killed`, código 137) en rastreos con JavaScript.**
Falta memoria para Docker (ver la guía de tu plataforma), o baja
`JS_CONCURRENT_REQUESTS` y `PLAYWRIGHT_MAX_PAGES` en el `.env`.

**Un rastreo acaba en `failed` con `sin_urls`.** No consiguió descargar ni la
primera página. Mira el log del worker: si es `tls_error` o `SSLError`,
prueba la URL desde tu navegador; si tampoco abre, el problema es el sitio o la
red, no el crawler.

**Un sitio devuelve 403 o captcha.** Es el WAF del sitio, no tu instalación.
Baja el ritmo en el `config.json` del cliente (`concurrent_requests` 4,
`concurrent_requests_per_domain` 2, `crawl_behavior.request_delay` 0.5) y mira
si hay notas en su `projects/<cliente>/README.md`.

## Si vas a tocar el código

Lee antes [`CLAUDE.md`](../../CLAUDE.md): las reglas que no se pueden romper y
dónde está cada cosa. **Mergear a `master` despliega a producción** y corta el
rastreo que esté en marcha allí. Los tests:
[`referencia/testing.md`](../referencia/testing.md).
