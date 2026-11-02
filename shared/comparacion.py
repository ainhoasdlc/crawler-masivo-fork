"""Comparar dos censos del mismo sitio: qué cambió entre uno y otro.

Vive en `shared/` y no en `analysis/` porque lo necesitan la API —que no lleva
`analysis/` en su imagen— y el worker. Es la misma razón que las reglas de
robots (decisión 23), la indexabilidad (39) y los dominios (64).

Las cuatro decisiones de criterio son las de #32, y cada una evita una forma
distinta de mentir:

1. **Las URLs se emparejan por el texto normalizado**, no por `urls.id`, que
   cambia entre censos.
2. **Un censo truncado no permite afirmar ausencias.** Si uno de los dos lados
   paró por `max_urls`, por tiempo o por estancamiento, decir «estas 4.000
   URLs han desaparecido» es falso: simplemente no se llegó a ellas. En ese
   caso el resultado se marca **no concluyente** y las ausencias no se cuentan.
3. **Dos orígenes distintos no se comparan.** Producción contra preproducción
   es legítimo, pero sin un mapeo explícito de host el resultado es «ha
   desaparecido el sitio entero».
4. **La versión del código viaja en el resultado** (decisión 66). Si los dos
   censos se hicieron con código distinto, una diferencia puede ser nuestra y
   no del sitio; eso hay que decirlo antes de atribuir nada.
5. **Dos ALCANCES distintos tampoco se comparan del todo.** El guardia del
   punto 3 mira el host, y dos rastreos del mismo host pueden ser dos cosas
   distintas: medido con los dos censos de cst.gov.sa del mismo día, uno
   sembrado en el árbol castellano y otro en el inglés, **0 semillas en común**
   de 4.780 — y la comparación afirmaba que habían desaparecido 834 páginas que
   nunca estuvieron en el alcance. Las ausencias solo se pueden afirmar si cada
   semilla del censo ANTERIOR está también en el posterior. No es un umbral: es
   una contención, y distingue los casos buenos sin ajustar nada (Lopesan
   2.935/2.935, el canario de penguin 1.950/1.950, CST 0/4.780). La Jaccard
   serviría de poco: el canario de penguin da 0,022 contra su censo completo y
   es un subconjunto limpio.
6. **El orden lo pone la FECHA, no quién llame.** «Antes» y «ahora» no pueden
   depender de qué censo se elija primero en un desplegable: una página que
   sale del índice y una que entra son hallazgos opuestos. Si no se sabe la
   fecha de alguno de los dos, no se afirma ninguna dirección y no se emite
   ninguna alerta.

Y la capa de alertas, que es lo que convierte una lista de diferencias en algo
que alguien mira: un cambio que afecta a una **parte grande de las páginas
indexables** no es trabajo editorial, es una plantilla, una configuración o un
despliegue. Ver `REGLAS` y la decisión 68.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

import logging
import os
import re
import time

from shared.accesibilidad import TIPOS as TIPOS_AXE
from shared.dominios import dominio_registrable
from shared.plantillas import firma_de_ruta
from shared.perfiles import perfil_de_ua
from shared.respuestas import MOTIVOS_BLOQUEO, NO_VALIDAS

logger = logging.getLogger(__name__)


# Motivos de cierre que dejan un censo incompleto: con cualquiera de ellos no
# se puede afirmar que una URL haya desaparecido.
MOTIVOS_TRUNCADO = frozenset({
    "max_urls_reached", "max_runtime_reached", "stalled", "cancelled",
    "closespider_itemcount", "closespider_pagecount", "closespider_timeout",
    # Frontera agotada, pero algun tope por carpeta dejo URLs sin pedir
    # (decision 172): en esas partes el censo no esta entero.
    "tope_por_carpeta",
    # La cola en disco perdio peticiones (decision 216).
    "frontera_sin_disco",
})

# Cuántas URLs de ejemplo se devuelven por cada tipo de cambio.
MUESTRA = 10

# Cuánto tiene que moverse el recuento de palabras para contarlo como cambio.
# Un 20%: por debajo es ruido de plantilla (una fecha, un contador, un
# "hace 3 días"), y la decisión 13 ya avisa de que los sitios varían solos.
UMBRAL_PALABRAS = 0.20

# Cuándo un cambio deja de ser trabajo de una página y pasa a ser una alerta.
# El 5% de las indexables, con un piso de 20 páginas porque en un censo de 30
# URLs «el 10%» son tres y no significa nada. Medido contra los pares de censos
# reales disponibles: con estos valores no salta ninguna alerta por la variación
# normal de un sitio entre dos rastreos (decisión 13) y sí salta el caso de
# Lopesan, 2.367 páginas canonicalizadas a un host de preproducción.
PCT_ALERTA = 0.05
MINIMO_PAGINAS = 20
# Una plantilla entera rota se diluye en el total: las 2.367 de Lopesan son el
# 99,5% de su plantilla y el 11% del sitio. Por eso también se mira por forma de
# ruta, con un umbral alto porque ahí el denominador es pequeño.
PCT_ALERTA_PLANTILLA = 0.50

# Los campos de la decision 131 (enlazado, description, datos estructurados y
# hreflang). Cada umbral esta medido contra pares de censos reales de control
# para que la variacion normal de un sitio entre dos rastreos no dispare nada
# (decisiones 13 y 68); las cifras, en la decision 131.
#
# Enlaces internos: paginas DISTINTAS que la enlazan (`unique_inlinks_count`),
# no instancias: un menu que repite el enlace dos veces no es otra pagina. Se
# cuenta cuando pierde la mitad o mas Y al menos `MINIMO_INLINKS_PERDIDOS`: de
# 3 a 1 es un 66% y es ruido de un listado que rota.
UMBRAL_INLINKS = 0.50
MINIMO_INLINKS_PERDIDOS = 10
# Profundidad en clics desde la home (decision 90): dos clics mas, o quedarse
# sin camino. Un clic se mueve solo cuando un listado pagina distinto.
UMBRAL_CLICS = 2
# PageRank 0-100: cada 25 puntos son una decada (decision 34). Bajar una decada
# entera es diez veces menos autoridad; menos que eso se mueve solo.
UMBRAL_PAGERANK = 25

# Qué decide Google con cada cosa. Sin esta columna una alerta es un número
# (regla 0 de docs/PRIORIDADES.md).
REGLAS: dict[str, tuple[str, str]] = {
    "canonical_a_otro_host": ("critical",
        "Google consolida estas páginas en una URL de OTRO host: dejan de "
        "aparecer en resultados y su autoridad se va fuera del sitio. Suele ser "
        "una fuga de un entorno de preproducción o de un CDN."),
    # Esta no mira si la página era indexable, porque lo que se va fuera del
    # sitio es el DESTINO de la consolidación. Medido en Lopesan: de las 2.367
    # páginas que acabaron apuntando a `webserver-lopesan-prd.lfr.cloud`, 1.832
    # ya estaban canonicalizadas a una URL legítima del sitio, así que la regla
    # de «era indexable y deja de serlo» las descartaba enteras.
    "canonical_a_otra_url": ("critical",
        "Google consolida estas páginas en la URL del canonical: dejan de "
        "aparecer en resultados y su autoridad pasa a la otra."),
    "rotas": ("critical",
        "Una página que responde 4xx o 5xx sale del índice, y con ella sus "
        "enlaces internos (decisión 57)."),
    "salen_del_indice": ("critical",
        "Google las saca del índice por algún otro motivo (noindex, robots): "
        "dejan de poder aparecer en resultados."),
    "redirigidas": ("warning",
        "Google indexa el destino, no esta URL. Si la redirección es "
        "intencionada no hay nada que arreglar; si no, son páginas perdidas."),
    "pierden_contenido": ("warning",
        "Menos texto en la misma URL es menos contenido que posicionar. Mirar "
        "antes si el cambio es nuestro: lo dice el aviso de versión."),
    "cambia_el_titulo": ("warning",
        "El título es el enlace del resultado: Google lo vuelve a evaluar y el "
        "CTR se mueve. Un cambio masivo es una plantilla, no una redacción."),
    "desaparecen": ("warning",
        "Ya no se llega a ellas desde el sitio, así que Google tampoco: dejan "
        "de recibir enlaces internos y acaban saliendo del índice."),
    "entran_en_el_indice": ("info",
        "Páginas que antes no podían aparecer en resultados y ahora sí. Si no "
        "era lo que se buscaba, es contenido entrando al índice sin querer."),
    # Decision 131. Las tres de enlazado son UNA familia: una pagina que pierde
    # los enlaces del menu se aleja de la home, pierde entrantes y pierde
    # PageRank a la vez, y es un solo hallazgo (decision 36). Va a la primera
    # que cumple, en este orden.
    "se_alejan_de_la_home": ("warning",
        "Están dos clics o más lejos de la home, o ya no se llega a ellas "
        "desde la home: Google rastrea con menos frecuencia lo que queda "
        "lejos, y les llega menos autoridad interna."),
    "pierden_enlaces_internos": ("warning",
        "Las enlazan la mitad de páginas o menos que antes: es la señal con la "
        "que Google descubre la página y decide cuánto importa. Un cambio "
        "masivo es un menú o un listado que ha dejado de enlazarlas."),
    "pierden_pagerank": ("warning",
        "Reciben diez veces menos autoridad interna que antes (una década de "
        "PageRank): el enlazado del sitio ha dejado de empujarlas."),
    "pierden_datos_estructurados": ("warning",
        "Un tipo de datos estructurados que tenían ya no está: sin el marcado "
        "Google deja de poder mostrar el resultado enriquecido de ese tipo "
        "(estrellas, precio, migas, preguntas)."),
    "pierden_hreflang": ("warning",
        "Han perdido la anotación hreflang de algún idioma: Google deja de "
        "saber qué versión enseñar en ese idioma o país y puede mostrar la "
        "equivocada, o tratarlas como duplicadas."),
    "cambia_la_description": ("info",
        "La meta description es la propuesta de fragmento del resultado. "
        "Google la reescribe a menudo, así que no decide el posicionamiento, "
        "pero un cambio masivo es una plantilla, no una redacción."),
}

# Las reglas que miden el GRAFO de enlaces. Con un censo truncado o con
# alcances distintos el grafo de las paginas comunes esta incompleto —las que
# las enlazaban pueden no haberse rastreado—, y «pierde enlaces» seria falso:
# no se comparan, igual que no se afirman ausencias (decisiones 67 y 70).
REGLAS_DE_GRAFO = frozenset({
    "se_alejan_de_la_home", "pierden_enlaces_internos", "pierden_pagerank"})


def _norm(url: str | None) -> str:
    """Forma comparable de una URL, la misma que usa el deduplicador.

    Sin `w3lib` el criterio NO es parecido, es el contrario en los dos casos
    que importan: `?a=1&b=2` deja de casar con `?b=2&a=1` (dos URLs donde hay
    una) y `/a/` empieza a casar con `/a` (una donde hay dos, y normalmente
    una redirige a la otra). Estuvo así en la imagen de la API, que no llevaba
    w3lib, de modo que el mismo par de censos se comparaba con un criterio
    distinto según dónde corriera el código. No se tapa: si falta, revienta.
    """
    if not url:
        return ""
    from w3lib.url import canonicalize_url

    return canonicalize_url(url, keep_fragments=False)


def _host(url: str | None) -> str:
    from urllib.parse import urlparse

    try:
        return (urlparse(url or "").hostname or "").lower()
    except Exception:
        return ""


def _truncado(estado: str | None, motivo: str | None) -> bool:
    return estado != "completed" or (motivo or "") in MOTIVOS_TRUNCADO


def _bloqueo(job: dict[str, Any]) -> str | None:
    """Causa si el censo se rastreo detras de un muro (decision 103)."""
    motivo = job.get("finish_reason") or ""
    if motivo in MOTIVOS_BLOQUEO:
        return motivo
    return (job.get("salud") or {}).get("causa")


def _aplicar_mapa(url: str, mapa: dict[str, str]) -> str:
    """Reescribe el host de una URL según el mapa `pre.x.com -> x.com`."""
    if not mapa:
        return url
    h = _host(url)
    destino = mapa.get(h)
    if not destino:
        return url
    return url.replace(f"//{h}", f"//{destino}", 1)


# --- Mapeo de rutas por regex (decision 131) ---------------------------------
#
# Una migracion cambia las rutas (`/es/hoteles/x.html` -> `/es/hotel/x/`) y,
# sin decirle al comparador como se corresponden, el resultado es «han
# desaparecido 3.000 paginas y han aparecido 3.000 nuevas»: cierto y sin
# ninguna utilidad. El mapeo reescribe las URLs del censo ANTERIOR antes de
# emparejar, igual que `map_host` reescribe el host.

MAX_REGLAS_RUTAS = 50
MAX_LONGITUD_PATRON = 500


def compilar_mapa_rutas(reglas) -> list[tuple[re.Pattern, str, str]]:
    """[(regex compilada, reemplazo, patron)] o ValueError con el motivo.

    Acepta pares `[patron, reemplazo]` o `{"patron", "reemplazo"}`. El
    reemplazo se valida tambien: `\\2` con un solo grupo no falla al compilar
    la regex sino al sustituir, y sustituir es ya emparejar. Python valida la
    plantilla entera antes de buscar, asi que basta con sustituir en vacio.
    """
    if not reglas:
        return []
    if not isinstance(reglas, (list, tuple)):
        raise ValueError("el mapeo de rutas es una lista de pares [patron, reemplazo]")
    if len(reglas) > MAX_REGLAS_RUTAS:
        raise ValueError(f"como mucho {MAX_REGLAS_RUTAS} reglas de mapeo de rutas")
    salida = []
    for i, r in enumerate(reglas, 1):
        if isinstance(r, dict):
            patron, reemplazo = r.get("patron"), r.get("reemplazo")
        elif isinstance(r, (list, tuple)) and len(r) == 2:
            patron, reemplazo = r
        else:
            raise ValueError(f"regla {i}: tiene que ser [patron, reemplazo]")
        if not isinstance(patron, str) or not patron or not isinstance(reemplazo, str):
            raise ValueError(f"regla {i}: patron y reemplazo son texto, y el patron no puede ir vacio")
        if len(patron) > MAX_LONGITUD_PATRON:
            raise ValueError(f"regla {i}: el patron pasa de {MAX_LONGITUD_PATRON} caracteres")
        try:
            rx = re.compile(patron)
        except re.error as e:
            raise ValueError(f"regla {i}: el patron {patron!r} no compila: {e}") from None
        try:
            rx.sub(reemplazo, "")
        except (re.error, IndexError) as e:
            raise ValueError(f"regla {i}: el reemplazo {reemplazo!r} no vale para {patron!r}: {e}") from None
        salida.append((rx, reemplazo, patron))
    return salida


def _ruta_de(url: str) -> tuple[str, str]:
    """(origen `https://host`, ruta con su `?query`) de una URL."""
    p = urlsplit(url)
    origen = f"{p.scheme}://{p.netloc}" if p.netloc else ""
    return origen, p.path + (f"?{p.query}" if p.query else "")


def _aplicar_rutas(url: str, reglas) -> tuple[str, int | None]:
    """La URL con la RUTA reescrita por la primera regla que casa, y cual fue.

    Sobre la ruta y no sobre la URL entera: el host lo cambia `map_host`, y
    una regex escrita para rutas que tocara el host haria saltar el guardia de
    origen (decision 67) sin que nadie entendiera por que. La primera que casa
    gana, como en un mapa de redirecciones: aplicarlas en cadena haria que una
    regla reescribiera lo que ya reescribio otra.
    """
    if not reglas:
        return url, None
    origen, ruta = _ruta_de(url)
    for i, (rx, reemplazo, _p) in enumerate(reglas):
        nueva, n = rx.subn(reemplazo, ruta, count=1)
        if n:
            return origen + nueva, i
    return url, None


def _con_dato(paginas, campo: str) -> bool:
    """Si el censo tiene la medida: un censo anterior a la columna la lleva a
    NULL en todas, y eso es «no se sabe», no «ninguna llega desde la home»."""
    return any(p.get(campo) is not None for p in paginas)


def _conjunto(valor) -> frozenset:
    return frozenset(v for v in (valor or ()) if v)


def comparar_censos(
    paginas_a: list[dict[str, Any]],
    paginas_b: list[dict[str, Any]],
    *,
    job_a: dict[str, Any],
    job_b: dict[str, Any],
    mapa_hosts: dict[str, str] | None = None,
    mapa_rutas=None,
    umbral_palabras: float = UMBRAL_PALABRAS,
    umbral_absoluto: int | None = None,
    umbrales: dict[str, dict[str, Any]] | None = None,
    ignorar: list[str] | None = None,
) -> dict[str, Any]:
    """Compara dos listas de páginas ya cargadas. Función pura, sin BD.

    Cada página es un dict con: `url`, `status_code`, `indexability_status`,
    `canonical_href`, `title`, `h1`, `word_count`.

    `umbral_absoluto` (decisión 128, modo lista): una alerta salta con ese
    número de páginas, sin porcentaje ni el piso de `MINIMO_PAGINAS`. Lo
    calcula `shared.modo_lista.umbral_absoluto`; None = el criterio de la 68.

    `mapa_rutas` (decision 131): pares `(patron, reemplazo)` que reescriben la
    RUTA de las URLs del censo anterior antes de emparejar (una migracion).
    Lanza ValueError si una regex no compila; la API lo convierte en un 422.

    `ignorar` (decision 230): regex del cliente que se quitan del title y la
    description antes de decir que cambiaron (el año, un contador).
    """
    mapa_hosts = mapa_hosts or {}
    textos = _comparador_de_textos(ignorar)
    reglas_rutas = compilar_mapa_rutas(mapa_rutas)

    # El orden lo pone la FECHA. Si no, "antes" y "ahora" los decide el
    # desplegable: la misma pareja de censos diria que 2.367 paginas salen del
    # indice o que entran, segun cual se eligiera primero. Es el mismo error que
    # tenia el umbral de palabras, que daba 1.639 cambios en un sentido y 439 en
    # el otro.
    fa, fb = job_a.get("fecha"), job_b.get("fecha")
    direccion_sabida = bool(fa and fb and fa != fb)
    if direccion_sabida and fa > fb:
        paginas_a, paginas_b = paginas_b, paginas_a
        job_a, job_b = job_b, job_a

    # Se compara el HOST, no el dominio registrable: `pre.x.com` y `x.com`
    # comparten dominio pero sus URLs no casan ni una, asi que el resultado
    # seria "ha desaparecido el sitio entero". Lo mismo con `www` y sin `www`.
    # Para eso esta el mapeo explicito.
    host_a = _host(job_a.get("semilla"))
    host_b = _host(job_b.get("semilla"))
    host_a_map = _host(_aplicar_mapa(job_a.get("semilla") or "", mapa_hosts))
    host_b_map = _host(_aplicar_mapa(job_b.get("semilla") or "", mapa_hosts))
    if host_a_map and host_b_map and host_a_map != host_b_map:
        misma_casa = dominio_registrable(host_a_map) == dominio_registrable(host_b_map)
        return {
            "comparable": False,
            "motivo": (
                f"son dos origenes distintos ({host_a} y {host_b})"
                + (", del mismo dominio pero no el mismo host" if misma_casa else "")
                + ". Sin un mapeo explicito de host el resultado seria que ha "
                "desaparecido el sitio entero."
            ),
        }

    # Un censo bloqueado no dice nada del sitio: lo que «cambio» es que el WAF
    # nos dejo de servir la pagina. Ni ausencias ni alertas (decision 103).
    bloqueo_a, bloqueo_b = _bloqueo(job_a), _bloqueo(job_b)
    truncado_a = (_truncado(job_a.get("status"), job_a.get("finish_reason"))
                  and not bloqueo_a)
    truncado_b = (_truncado(job_b.get("status"), job_b.get("finish_reason"))
                  and not bloqueo_b)
    concluyente = not (truncado_a or truncado_b or bloqueo_a or bloqueo_b)

    avisos: list[str] = []

    if bloqueo_a or bloqueo_b:
        cual = []
        if bloqueo_a:
            cual.append(f"el primero ({bloqueo_a})")
        if bloqueo_b:
            cual.append(f"el segundo ({bloqueo_b})")
        avisos.append(
            "NO CONCLUYENTE: censo bloqueado. " + " y ".join(cual).capitalize()
            + " se rastreo detras de un muro (desafio de un WAF, captcha o "
            "limite de peticiones): lo que cambia es lo que nos dejaron ver, no "
            "el sitio. No se emiten alertas.")

    if truncado_a or truncado_b:
        # Solo cuando algo esta DE VERDAD truncado: `concluyente` tambien lo
        # pone a False el guardia de alcance, y con el mensaje colgado de ahi
        # salia un "NO CONCLUYENTE:  no termino entero" sin sujeto, repitiendo
        # ademas lo que el otro aviso ya decia mejor.
        cual = []
        if truncado_a:
            cual.append(f"el primero ({job_a.get('finish_reason') or job_a.get('status')})")
        if truncado_b:
            cual.append(f"el segundo ({job_b.get('finish_reason') or job_b.get('status')})")
        avisos.append(
            "NO CONCLUYENTE: " + " y ".join(cual) + " no termino entero, asi que "
            "no se puede afirmar que falte ninguna URL ni que se haya resuelto nada."
        )
    # Dos rastreos del MISMO host pueden tener dos alcances distintos. Las
    # ausencias solo se pueden afirmar si cada semilla del censo anterior esta
    # tambien en el posterior: si no, lo que "falta" puede no haber estado
    # nunca en el alcance.
    sem_a, sem_b = job_a.get("semillas"), job_b.get("semillas")
    if sem_a is not None and sem_b is not None:
        conj_b = {_norm(_aplicar_mapa(u, mapa_hosts)) for u in sem_b}
        # Las del anterior, con el mapeo de rutas: tras una migracion la
        # semilla vieja es la nueva con otro nombre, no otro alcance.
        fuera = [u for u in sem_a
                 if _norm(_aplicar_rutas(_aplicar_mapa(u, mapa_hosts), reglas_rutas)[0])
                 not in conj_b]
        if fuera:
            concluyente = False
            avisos.append(
                f"ALCANCES DISTINTOS: {len(fuera)} de las {len(sem_a)} semillas "
                f"del censo anterior no estan en el posterior (p. ej. "
                f"{fuera[0]}), asi que no se puede afirmar que falte ninguna "
                f"URL: puede no haber estado nunca en el alcance."
            )

    # El render cambia lo que se ve, no lo que hay: una plantilla que monta sus
    # enlaces con JavaScript solo los enseña al rastreo que renderiza, que es
    # justo lo que mide `js_check` (decision 35). No hay en los datos ninguna
    # pareja de censos que difiera en esto, asi que el aviso sale de ese
    # mecanismo y no de una medida.
    if (job_a.get("render_js") is not None and job_b.get("render_js") is not None
            and bool(job_a["render_js"]) != bool(job_b["render_js"])):
        avisos.append(
            "Uno de los dos censos renderiza JavaScript y el otro no: el que "
            "renderiza ve enlaces y texto que el otro no llega a ver, asi que "
            "una diferencia puede ser del render y no del sitio."
        )
    # Un censo con UA de movil y otro de escritorio no ven la misma pagina en
    # un sitio con servido dinamico o m-dot: lo que cambia puede ser el perfil
    # (decision 119). Y la paridad movil de uno no se compara con la del otro.
    perfil_a, perfil_b = job_a.get("perfil"), job_b.get("perfil")
    if perfil_a and perfil_b and perfil_a != perfil_b:
        avisos.append(
            f"Un censo se rastreo con perfil {perfil_a} y el otro con perfil "
            f"{perfil_b}: si el sitio sirve otra cosa a un movil, una diferencia "
            f"puede ser del perfil y no del sitio."
        )
    ver_a, ver_b = job_a.get("crawler_version"), job_b.get("crawler_version")
    if not ver_a or not ver_b:
        # Desconocido NO es igual. Si uno de los dos censos es anterior al
        # sello de version (decision 66), callarse equivale a afirmar que se
        # hicieron con el mismo codigo, y eso es justo lo que no se sabe.
        # Comprobado con dos censos reales de progym: 439 paginas cambian su
        # recuento de palabras y el cambio es NUESTRO (la extraccion de
        # contenido), no del sitio.
        avisos.append(
            "No se sabe con que version del crawler se hizo "
            + ("el primer censo" if not ver_a else "el segundo censo")
            + (" ni el segundo" if not ver_a and not ver_b else "")
            + ": cualquier diferencia podria ser nuestra y no del sitio."
        )
    elif ver_a != ver_b:
        avisos.append(
            f"Los dos censos se hicieron con versiones distintas del crawler "
            f"({ver_a} y {ver_b}): una diferencia puede ser nuestra y no del "
            f"sitio."
        )

    # Con que se ANALIZO es otra pregunta, y hace falta igual: un re-analisis
    # cambia las cifras de un censo sin que cambie el sitio ni el rastreo.
    # Medido en penguin, un censo de julio re-analizado con el codigo de
    # octubre. Solo se avisa cuando se SABE que difieren: aqui, a diferencia
    # del rastreo, el desconocido ya lo cubre el aviso de arriba.
    ana_a, ana_b = job_a.get("analisis_version"), job_b.get("analisis_version")
    if ana_a and ana_b and ana_a != ana_b:
        avisos.append(
            f"Los dos censos se ANALIZARON con versiones distintas ({ana_a} y "
            f"{ana_b}): un re-analisis cambia las cifras sin que cambie el "
            f"sitio, asi que parte de la diferencia puede ser nuestra."
        )

    def indexar(paginas):
        return {
            _norm(_aplicar_mapa(p["url"], mapa_hosts)): p
            for p in paginas
            if p.get("url")
        }

    if reglas_rutas and not direccion_sabida:
        avisos.append(
            "Sin la fecha de los dos censos no se sabe cual es el anterior: el "
            "mapeo de rutas se ha aplicado al primero de los dos que se ha "
            "pedido.")
    # El mapeo de rutas va SOLO sobre el anterior: describe como se llaman
    # hoy las URLs de antes. Se cuenta cuantas reescribe cada regla y cuantas
    # caen en la misma URL nueva (dos viejas que pasan a ser una: la segunda
    # se pierde de la comparacion, y eso se dice).
    reescritas_por_regla = [0] * len(reglas_rutas)
    reescritas: set[str] = set()
    colisiones = 0
    a = {}
    for p in paginas_a:
        if not p.get("url"):
            continue
        u, i = _aplicar_rutas(_aplicar_mapa(p["url"], mapa_hosts), reglas_rutas)
        k = _norm(u)
        if i is not None:
            reescritas_por_regla[i] += 1
            reescritas.add(k)
        if k in a:
            colisiones += 1
        if reglas_rutas and p.get("canonical_href"):
            # El canonical de antes, con el mismo mapeo: tras una migracion
            # `/x.html` con canonical `/x.html` y `/x/` con canonical `/x/`
            # no han cambiado de canonical. Solo para la tabla de cambios;
            # las alertas comparan cada canonical con la URL de SU censo.
            p = {**p, "_canonical_cmp": _norm(_aplicar_rutas(
                _aplicar_mapa(p["canonical_href"], mapa_hosts), reglas_rutas)[0])}
        a[k] = p
    b = indexar(paginas_b)
    # Una pagina que en cualquiera de los dos censos fue un muro no se ha visto
    # en ese censo: ni cambia, ni desaparece, ni sale del indice. Fuera de la
    # comparacion, y se cuenta (decision 103).
    muros = {k for k, p in a.items() if p.get("response_class") in NO_VALIDAS}
    muros |= {k for k, p in b.items() if p.get("response_class") in NO_VALIDAS}
    for k in muros:
        a.pop(k, None)
        b.pop(k, None)
    comunes = a.keys() & b.keys()
    # Las alertas se reparten por el segmento de ANTES (`_grupo`): si solo el
    # nuevo esta segmentado, se dice, para que «sin segmentos» no se lea como
    # «ningun segmento ha cambiado».
    if (any(_segmento_propio(p.get("segmento")) for p in b.values())
            and not any(_segmento_propio(p.get("segmento")) for p in a.values())):
        avisos.append(
            "El censo anterior no tiene segmentos: las alertas se reparten por "
            "plantilla y no por segmento. Re-segmentarlo con las reglas de hoy "
            "(POST /api/jobs/<id>/segmentos) para verlas por segmento.")

    cambios: dict[str, list[dict[str, Any]]] = {
        "status_code": [], "indexability_status": [], "canonical_href": [],
        "title": [], "h1": [], "word_count": [],
        # Decision 131.
        "meta_description": [], "sd_tipos": [], "hreflang": [],
        "inlinks": [], "click_depth": [], "pagerank_score": [],
    }
    # Que se puede comparar de lo de la 131. El grafo solo con los dos censos
    # enteros y del mismo alcance; cada medida, solo si los DOS la tienen.
    motivo_grafo = _motivo_sin_grafo(job_a, job_b, concluyente)
    grafo = motivo_grafo is None
    medidas = {
        "grafo": grafo,
        "click_depth": grafo and _con_dato(a.values(), "click_depth")
                       and _con_dato(b.values(), "click_depth"),
        "pagerank_score": grafo and _con_dato(a.values(), "pagerank_score")
                          and _con_dato(b.values(), "pagerank_score"),
        "inlinks": grafo and _con_dato(a.values(), "inlinks")
                   and _con_dato(b.values(), "inlinks"),
        "sd_tipos": _con_dato(a.values(), "sd_tipos") and _con_dato(b.values(), "sd_tipos"),
        "hreflang": _con_dato(a.values(), "hreflang") and _con_dato(b.values(), "hreflang"),
        "meta_description": ("meta_description" in next(iter(a.values()), {})
                             and "meta_description" in next(iter(b.values()), {})),
    }
    # Páginas por regla de alerta, y el denominador de cada regla: cuántas
    # podían haberle pasado. "2.367 páginas" no dice nada sin "de 2.379".
    afectadas: dict[str, list[dict[str, Any]]] = {r: [] for r in REGLAS}
    # Por (forma de ruta, segmento), para poder decir "99,5% de ESTA
    # plantilla" o "del 60% de las fichas" (decision 127).
    bases: dict[str, dict[tuple[str, str | None], int]] = {
        "era_indexable": defaultdict(int),
        "no_era_indexable": defaultdict(int),
        "era_indexable_en_el_primero": defaultdict(int),
        "todas_las_comunes": defaultdict(int),
        # Decision 131: «pierden el hreflang» sobre las que lo tenian.
        "indexable_con_datos_estructurados": defaultdict(int),
        "indexable_con_hreflang": defaultdict(int),
    }

    for clave in sorted(comunes):
        pa, pb = a[clave], b[clave]
        for campo in ("status_code", "indexability_status", "canonical_href", "title", "h1"):
            va, vb = pa.get(campo), pb.get(campo)
            if campo == "canonical_href" and "_canonical_cmp" in pa:
                if pa["_canonical_cmp"] == _norm(vb or ""):
                    continue
            distinto = textos(va, vb) if campo in ("title", "h1") else va != vb
            if distinto:
                cambios[campo].append({"url": pb.get("url"), "antes": va, "ahora": vb})
        wa, wb = pa.get("word_count") or 0, pb.get("word_count") or 0
        # El denominador es el MAYOR de los dos, no el "antes": si no,
        # comparar A con B y B con A da resultados distintos. Medido con dos
        # censos reales de progym: 1.639 paginas en un sentido y 439 en el
        # otro, con los mismos datos. Pasar de 100 a 130 palabras y de 130 a
        # 100 es el mismo cambio y tiene que contarse igual.
        mayor = max(wa, wb)
        if mayor and abs(wb - wa) / mayor >= umbral_palabras:
            cambios["word_count"].append({"url": pb.get("url"), "antes": wa, "ahora": wb})
        _cambios_131(pa, pb, cambios, medidas)

        _clasificar(pa, pb, afectadas, bases, umbral_palabras, medidas, textos)

    # Lo que extraen las reglas a medida, sobre las mismas paginas comunes y
    # sin los muros (decision 127).
    extraido, entradas_extraido = _comparar_extraido(a, b, comunes, job_a, job_b)

    nuevas = sorted(b.keys() - a.keys())
    desaparecidas = sorted(a.keys() - b.keys()) if concluyente else []
    if concluyente:
        # Solo las que podían aparecer en resultados: que deje de estar
        # enlazada una `?utm` o un `/page/2` no es un hallazgo. El denominador
        # es todo el primer censo, no solo las comunes: una URL que desaparece
        # no está en las comunes por definición.
        for pagina in a.values():
            if _era_indexable(pagina):
                bases["era_indexable_en_el_primero"][_grupo(pagina)] += 1
        afectadas["desaparecen"] = [
            {"url": a[k]["url"], "_g": _grupo(a[k])}
            for k in desaparecidas if _era_indexable(a[k])]

    resultado = {
        "comparable": True,
        "concluyente": concluyente,
        "avisos": avisos,
        "antes": _sin_semillas(job_a),
        "ahora": _sin_semillas(job_b),
        "direccion_sabida": direccion_sabida,
        "urls": {
            "en_ambos": len(comunes),
            "nuevas": len(nuevas),
            "desaparecidas": len(desaparecidas) if concluyente else None,
            "desaparecidas_no_afirmables": len(a.keys() - b.keys()) if not concluyente else 0,
            "sin_comparar_por_muro": len(muros),
            "ejemplos_nuevas": [b[k]["url"] for k in nuevas[:MUESTRA]],
            "ejemplos_desaparecidas": [a[k]["url"] for k in desaparecidas[:MUESTRA]],
        },
        "cambios": {
            campo: ({"total": len(filas), "ejemplos": filas[:MUESTRA]}
                    if medidas.get(campo, True) else
                    {"total": None, "ejemplos": [],
                     "motivo": motivo_grafo if campo in CAMPOS_DE_GRAFO and motivo_grafo
                     else "uno de los dos censos no tiene este dato (anterior a la columna)"})
            for campo, filas in cambios.items()
        },
        "extraido": extraido,
    }
    resultado["urls"]["pct_emparejadas_del_anterior"] = (
        round(100 * len(comunes) / len(a), 1) if a else None)
    if reglas_rutas:
        resultado["mapeo_rutas"] = {
            "reglas": [
                {"patron": pat, "reemplazo": rep, "reescritas": n}
                for (_rx, rep, pat), n in zip(reglas_rutas, reescritas_por_regla)],
            "urls_del_anterior": len(a),
            "reescritas": len(reescritas),
            "reescritas_emparejadas": len(reescritas & comunes),
            "emparejadas": len(comunes),
            "pct_emparejadas": round(100 * len(comunes) / len(a), 1) if a else None,
            # Dos URLs viejas que el mapeo convierte en la misma: solo una
            # entra en la comparacion.
            "colisiones": colisiones,
        }
    if bloqueo_a or bloqueo_b:
        resultado["alertas"] = []
        resultado["bloqueado"] = bloqueo_b or bloqueo_a
    elif direccion_sabida:
        resultado["alertas"] = _ordenar_alertas(
            _alertas(afectadas, bases, umbral_absoluto, umbrales)
            + _alertas_extraido(entradas_extraido, umbral_absoluto))
    else:
        resultado["alertas"] = []
        avisos.append(
            "No se emiten alertas: sin la fecha de los dos censos no se sabe "
            "cual es el ANTES, y una pagina que sale del indice y una que entra "
            "son hallazgos opuestos."
        )
    return resultado


def _sin_semillas(job: dict[str, Any]) -> dict[str, Any]:
    """El resumen del job sin la lista de semillas, que puede ser enorme.

    Se necesitan para comprobar el alcance, pero devolverlas serian 87.429
    URLs en la respuesta del censo de penguin. Queda el recuento, que es lo
    unico que alguien va a leer.
    """
    recortado = dict(job)
    if "semillas" in recortado:
        recortado["n_semillas"] = len(recortado.pop("semillas") or [])
    # Las definiciones de las reglas a medida tampoco: basta con sus nombres.
    if isinstance(recortado.get("reglas_a_medida"), dict):
        recortado["reglas_a_medida"] = sorted(recortado["reglas_a_medida"])
    return recortado


def _era_indexable(pagina: dict[str, Any]) -> bool:
    """Si Google podía posicionarla: 200 y sin nada que la saque del índice."""
    return (pagina.get("status_code") == 200
            and (pagina.get("indexability_status") or "") == "Indexable")


def _canonical_que_cuenta(pagina: dict[str, Any]) -> str | None:
    """El canonical que Google usa, o None.

    Con dos o más canonicals de destino distinto en el head Google los ignora
    TODOS (decisión 115): la página no está canonicalizada a ninguno, y
    `canonical_href` guarda el primero solo como dato. Leerlo aquí disparaba
    `canonical_a_otro_host` —una alerta crítica con webhook— por un canonical
    que Google descarta. Sin la columna (censo anterior), manda el primero,
    como antes.
    """
    distintos = pagina.get("canonical_distintos")
    if distintos is not None and distintos > 1:
        return None
    return pagina.get("canonical_href")


def _canonical_a_otra(pagina: dict[str, Any]) -> str | None:
    """El canonical de la página si apunta a OTRA URL; None si es la suya."""
    can = _canonical_que_cuenta(pagina)
    if not can:
        return None
    return can if _norm(can) != _norm(pagina.get("url")) else None


# A qué conjunto de páginas se compara cada regla. "2.367 páginas" no dice
# nada sin "de 2.379", y el conjunto no es el mismo para todas: una página que
# ENTRA en el índice se cuenta sobre las que no estaban, no sobre las que sí.
BASE_DE_LA_REGLA: dict[str, str] = {
    "canonical_a_otro_host": "todas_las_comunes",
    "canonical_a_otra_url": "era_indexable",
    "rotas": "era_indexable",
    "salen_del_indice": "era_indexable",
    "redirigidas": "era_indexable",
    "pierden_contenido": "era_indexable",
    "cambia_el_titulo": "era_indexable",
    "entran_en_el_indice": "no_era_indexable",
    "desaparecen": "era_indexable_en_el_primero",
    "se_alejan_de_la_home": "era_indexable",
    "pierden_enlaces_internos": "era_indexable",
    "pierden_pagerank": "era_indexable",
    "pierden_datos_estructurados": "indexable_con_datos_estructurados",
    "pierden_hreflang": "indexable_con_hreflang",
    "cambia_la_description": "era_indexable",
}


def _canonical_fuera(pagina: dict[str, Any]) -> str | None:
    """El canonical si apunta a un host distinto del de la propia página."""
    can = _canonical_que_cuenta(pagina)
    hc = _host(can)
    return can if can and hc and hc != _host(pagina.get("url")) else None


def _firma(url: str | None) -> str:
    from urllib.parse import urlparse
    try:
        return firma_de_ruta(urlparse(url or "").path)
    except Exception:
        return "?"


# --- Extraccion a medida (decisiones 104 y 127) ------------------------------
#
# Lo que el consultor pide a cada pagina —precio, disponibilidad, SKU, «¿lleva
# el tag de GTM?»— comparado entre dos censos. Lo que no es obvio:
#
# - Solo se compara una regla que existe con el MISMO nombre en los dos censos
#   y con la misma definicion. Si la expresion cambio, una diferencia puede ser
#   de la regla y no del sitio, y eso no se afirma (la misma idea que la
#   decision 91 con el analisis).
# - Sin fila no es «vacio» (decision 104): si en uno de los dos censos la URL no
#   tiene fila para esa regla (no era HTML 2xx, cayo fuera de `solo_urls`, se
#   rastreo antes de la regla), NO es un cambio. Se cuenta como `sin_dato`.
# - Solo dos estados son un dato: `ok` y `sin_coincidencia`. Lo demas
#   (`tiempo_agotado`, `pagina_bloqueada`, `incompleta`...) es «no se sabe» y se
#   cuenta como `sin_saber`, nunca como «el precio ha desaparecido».
# - Un valor sacado del DOM renderizado y otro del HTML de la respuesta
#   (`custom_extraction.render`) no se comparan: `render_distinto`.

# Estados que dicen algo de la pagina; el resto es «no se pudo evaluar».
ESTADOS_CON_DATO = frozenset({"ok", "sin_coincidencia"})

# Campos de la definicion que NO cambian lo que significa el valor: el rotulo
# y el alcance (`solo_urls` acota que URLs llevan fila; las que no la llevan ya
# quedan fuera por la regla de «sin fila»).
_CAMPOS_COSMETICOS = frozenset({"etiqueta", "solo_urls"})

REGLAS_EXTRAIDO: dict[str, tuple[str, str, str]] = {
    # id: (severidad, clase de la regla, que decide Google)
    "extraido_cambia": ("warning", "extractor",
        "El valor que extrae esta regla ha cambiado en una parte grande de las "
        "paginas a la vez: es un cambio de catalogo, de plantilla o de un "
        "proceso, no de una ficha. Si es un precio o la disponibilidad, Google "
        "lo lee del marcado de producto y lo muestra en el resultado "
        "enriquecido: un cambio masivo que nadie decidio se ve en la SERP."),
    "extraido_desaparece": ("warning", "extractor",
        "Paginas que tenian este dato y ahora la regla no lo encuentra en la "
        "misma URL. Si es el precio o el stock de una ficha, el resultado "
        "enriquecido de Google se queda sin el; si la plantilla cambio, hay "
        "que reescribir la regla antes de leer la cifra."),
    "extraido_aparece": ("info",
        "extractor",
        "Paginas en las que la regla ahora encuentra un dato que antes no "
        "estaba. Si no era lo esperado, es una plantilla nueva."),
    "busqueda_deja_de_contener": ("warning", "busqueda",
        "Paginas que contenian lo que busca esta regla y ya no: si es un tag "
        "de analitica, un marcado o un texto legal, se ha caido de la "
        "plantilla en bloque."),
    "busqueda_pasa_a_contener": ("info", "busqueda",
        "Paginas que ahora contienen lo que busca esta regla y antes no. Si "
        "es un texto que no deberia estar (un «sin stock», un error), es una "
        "plantilla, no una pagina."),
}

# A que base se compara cada una: «2.300 fichas cambian de precio» sin «de las
# 2.400 que tenian precio en los dos» no dice nada (decision 68).
BASE_EXTRAIDO: dict[str, str] = {
    "extraido_cambia": "ok_en_los_dos",
    "extraido_desaparece": "ok_antes",
    "extraido_aparece": "sin_antes",
    "busqueda_deja_de_contener": "ok_antes",
    "busqueda_pasa_a_contener": "sin_antes",
}


def _definicion(regla: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (regla or {}).items() if k not in _CAMPOS_COSMETICOS}


def reglas_a_medida(config: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """{nombre: {clase, definicion}} de las reglas a medida de un `jobs.config`."""
    config = config or {}
    salida: dict[str, dict[str, Any]] = {}
    for clave, clase in (("custom_extraction", "extractor"), ("custom_search", "busqueda")):
        for nombre, regla in (config.get(clave) or {}).items():
            if isinstance(regla, dict):
                salida[nombre] = {"clase": clase, "definicion": _definicion(regla)}
    return salida


def _reglas_comparables(job_a, job_b, a, b) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Que reglas se comparan ({nombre: clase}) y cuales no, con el motivo."""
    ra, rb = job_a.get("reglas_a_medida"), job_b.get("reglas_a_medida")
    if ra is None or rb is None:
        # Sin la configuracion (un resumen sin ella) se mira que nombres tienen
        # filas en los dos censos. No hay forma de saber si la regla cambio.
        def nombres(pags):
            vistos: dict[str, str] = {}
            for p in pags.values():
                for n, e in (p.get("extraido") or {}).items():
                    vistos.setdefault(n, e.get("clase") or "extractor")
            return vistos
        na, nb = nombres(a), nombres(b)
        return {n: na[n] for n in na.keys() & nb.keys()}, []

    comparables: dict[str, str] = {}
    fuera: list[dict[str, Any]] = []
    for n in sorted(ra.keys() | rb.keys()):
        if n not in ra or n not in rb:
            fuera.append({"nombre": n, "motivo": (
                "solo existe en el censo " + ("posterior" if n in rb else "anterior")
                + ": lo que no se extrajo en uno no es un cambio")})
            continue
        if ra[n]["clase"] != rb[n]["clase"]:
            fuera.append({"nombre": n, "motivo": "en un censo es una extraccion y en el otro una busqueda"})
            continue
        da, db_ = ra[n]["definicion"], rb[n]["definicion"]
        # Solo los campos que estan en los dos: un `jobs.config` guardado sin
        # los valores por defecto no puede leerse como «la regla cambio».
        distintos = sorted(k for k in da.keys() & db_.keys() if da[k] != db_[k])
        if distintos:
            fuera.append({"nombre": n, "motivo": (
                "la regla cambio entre los dos censos (" + ", ".join(distintos)
                + "): una diferencia puede ser de la regla y no del sitio")})
            continue
        comparables[n] = ra[n]["clase"]
    return comparables, fuera


def _mismo_valor(ea: dict[str, Any], eb: dict[str, Any]) -> bool:
    na, nb = ea.get("num"), eb.get("num")
    if na is not None and nb is not None:
        return abs(na - nb) <= 1e-9 * max(1.0, abs(na), abs(nb))
    return (ea.get("valor") or "") == (eb.get("valor") or "")


def _mediana(valores: list[float]) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def _comparar_extraido(a, b, comunes, job_a, job_b) -> tuple[dict[str, Any], list[tuple]]:
    """El resumen por regla y las entradas de alerta (`_alerta`) que salen."""
    comparables, no_comparadas = _reglas_comparables(job_a, job_b, a, b)
    resumen: list[dict[str, Any]] = []
    entradas: list[tuple] = []
    for nombre in sorted(comparables):
        clase = comparables[nombre]
        filas: dict[str, list[dict[str, Any]]] = {r: [] for r in REGLAS_EXTRAIDO
                                                   if REGLAS_EXTRAIDO[r][1] == clase}
        bases: dict[str, dict] = {"ok_en_los_dos": defaultdict(int),
                                  "ok_antes": defaultdict(int),
                                  "sin_antes": defaultdict(int)}
        sin_dato = sin_saber = comparadas = render_distinto = 0
        transiciones: dict[tuple, int] = defaultdict(int)
        variaciones: list[float] = []
        sube = baja = 0
        for k in sorted(comunes):
            pa, pb = a[k], b[k]
            ea = (pa.get("extraido") or {}).get(nombre)
            eb = (pb.get("extraido") or {}).get(nombre)
            if ea is None and eb is None:
                continue                      # fuera del alcance de la regla
            if ea is None or eb is None:
                sin_dato += 1                 # sin fila no es «vacio» (104)
                continue
            if ea.get("estado") not in ESTADOS_CON_DATO or eb.get("estado") not in ESTADOS_CON_DATO:
                sin_saber += 1
                continue
            # Uno del DOM renderizado y otro del HTML de la respuesta no leen la
            # misma pagina: lo que monta el JavaScript solo esta en uno.
            ra_, rb_ = ea.get("render"), eb.get("render")
            if ra_ is not None and rb_ is not None and bool(ra_) != bool(rb_):
                render_distinto += 1
                continue
            comparadas += 1
            g = _grupo(pb, pa)
            url = pb.get("url")
            antes_ok, ahora_ok = ea["estado"] == "ok", eb["estado"] == "ok"
            if antes_ok:
                bases["ok_antes"][g] += 1
            else:
                bases["sin_antes"][g] += 1
            if clase == "busqueda":
                if antes_ok and not ahora_ok:
                    filas["busqueda_deja_de_contener"].append({"url": url, "_g": g})
                elif ahora_ok and not antes_ok:
                    filas["busqueda_pasa_a_contener"].append(
                        {"url": url, "ahora": eb.get("valor"), "_g": g})
                continue
            if antes_ok and ahora_ok:
                bases["ok_en_los_dos"][g] += 1
                if not _mismo_valor(ea, eb):
                    filas["extraido_cambia"].append(
                        {"url": url, "antes": ea.get("valor"), "ahora": eb.get("valor"), "_g": g})
                    na, nb = ea.get("num"), eb.get("num")
                    if na is not None and nb is not None:
                        sube += nb > na
                        baja += nb < na
                        if na:
                            variaciones.append(100 * (nb - na) / abs(na))
                    else:
                        transiciones[(str(ea.get("valor") or "")[:80],
                                      str(eb.get("valor") or "")[:80])] += 1
            elif antes_ok:
                filas["extraido_desaparece"].append(
                    {"url": url, "antes": ea.get("valor"), "_g": g})
            elif ahora_ok:
                filas["extraido_aparece"].append(
                    {"url": url, "ahora": eb.get("valor"), "_g": g})

        extra: dict[str, Any] = {"extraccion": nombre}
        if clase == "extractor" and (sube or baja or variaciones):
            med = _mediana(variaciones)
            extra["variacion"] = {"suben": sube, "bajan": baja,
                                  "mediana_pct": round(med, 1) if med is not None else None}
        if transiciones:
            extra["transiciones"] = [
                {"antes": t[0], "ahora": t[1], "paginas": n}
                for t, n in sorted(transiciones.items(), key=lambda x: -x[1])[:5]]
        resumen.append({
            "nombre": nombre, "clase": clase, "comparadas": comparadas,
            "sin_dato": sin_dato, "sin_saber": sin_saber,
            "render_distinto": render_distinto,
            "cambios": {r: {"total": len(f), "ejemplos": [_sin_grupo(x) for x in f[:MUESTRA]]}
                        for r, f in filas.items()},
            **{k: v for k, v in extra.items() if k != "extraccion"},
        })
        for regla, f in filas.items():
            entradas.append((regla, f, bases[BASE_EXTRAIDO[regla]], extra))
    return {"reglas": resumen, "no_comparadas": no_comparadas}, entradas


def _alertas_extraido(entradas, umbral_absoluto=None) -> list[dict[str, Any]]:
    salida = []
    for regla, filas, base, extra in entradas:
        severidad, _clase, que_decide = REGLAS_EXTRAIDO[regla]
        al = _alerta(regla, severidad, que_decide, filas, base, umbral_absoluto)
        if al is not None:
            al.update(extra)
            salida.append(al)
    return salida


def _segmento_propio(seg: str | None) -> bool:
    """Si el segmento lo puso una regla del consultor (decision 125).

    El repuesto es la forma de la ruta (empieza por `/`), que es exactamente
    la plantilla: contarlo tambien como segmento seria el mismo aviso dos
    veces. `(externa)` y `(recurso)` no son paginas del sitio.
    """
    return bool(seg) and not seg.startswith("/") and not seg.startswith("(")


def _grupo(pagina: dict[str, Any], antes: dict[str, Any] | None = None) -> tuple[str, str | None]:
    """(forma de ruta, segmento) de una pagina, para repartir las alertas.

    La forma sale de la URL de `pagina`; el segmento, SIEMPRE del censo
    ANTERIOR (`antes`, o la propia `pagina` cuando es del anterior). Un
    segmento puede depender de `indexable`, del codigo o de un valor extraido
    (decision 125), y el del censo nuevo puede estar definido por el propio
    cambio: «no indexables» contiene justo las paginas que salieron del indice
    y la alerta saldria al 100% con 25 de 1.000 fichas. El porcentaje se cuenta
    sobre la poblacion de ANTES del cambio. Si el anterior no tiene segmento
    (censo previo a la columna o sin re-segmentar) no se usa el del nuevo, por
    el mismo motivo: queda solo la plantilla.
    """
    seg = (antes if antes is not None else pagina).get("segmento")
    return _firma(pagina.get("url")), seg


CAMPOS_DE_GRAFO = ("click_depth", "pagerank_score", "inlinks")


def _motivo_sin_grafo(job_a, job_b, concluyente) -> str | None:
    """Por que no se puede comparar el grafo de enlaces, o None si se puede.

    Tres cosas, y cualquiera basta:
    - un censo truncado, bloqueado o con otro alcance: las paginas que
      enlazaban pueden no haberse rastreado (decisiones 67 y 70);
    - una lista (`max_depth` 0, decision 128) o dos profundidades distintas:
      lo que no se rastreo no enlaza, y frente al censo completo TODAS las
      URLs de la lista «perderian» sus entrantes;
    - dos versiones del ANALIZADOR, o una desconocida: entrantes, profundidad
      y PageRank los calcula el analisis, no el rastreo, y un re-analisis los
      mueve sin que cambie el sitio (decisiones 38 y 57; la misma regla que la
      91 aplica a las incidencias).
    """
    if not concluyente:
        return ("el grafo de enlaces no se compara: uno de los dos censos esta "
                "truncado, bloqueado o tiene otro alcance, y las paginas que "
                "enlazaban pueden no haberse rastreado (decisiones 67 y 70)")
    pa, pb = job_a.get("max_depth"), job_b.get("max_depth")
    if pa == 0 or pb == 0 or (pa is not None and pb is not None and pa != pb):
        return (f"el grafo de enlaces no se compara: los censos tienen otra "
                f"profundidad maxima ({pa} y {pb}; 0 es una lista, que no sigue "
                f"enlaces), y lo que uno no rastreo no enlaza (decision 128)")
    ana_a, ana_b = job_a.get("analisis_version"), job_b.get("analisis_version")
    if not (ana_a and ana_b and ana_a == ana_b):
        return (f"el grafo de enlaces no se compara: los censos se analizaron "
                f"con versiones distintas del codigo ({ana_a or 'desconocida'} y "
                f"{ana_b or 'desconocida'}), y los entrantes, la profundidad y "
                f"el PageRank los calcula el analisis (decision 91). Vuelve a "
                f"analizar el mas antiguo con el codigo de hoy.")
    return None


def _tipos(pagina) -> frozenset:
    return _conjunto(pagina.get("sd_tipos"))


def _idiomas(pagina) -> frozenset:
    return _conjunto(pagina.get("hreflang"))


def _cambios_131(pa, pb, cambios, medidas) -> None:
    """La tabla de «que cambio» con los campos de la decision 131.

    Solo entre paginas que responden 200 en los dos: si una pasa a 404 ya lo
    cuenta `status_code`, y que «pierda» sus datos estructurados es el mismo
    hallazgo (decision 36). Con los mismos umbrales que las alertas: una
    tabla que cuenta como cambio el ruido de un rastreo a otro no se lee.
    """
    if pa.get("status_code") != 200 or pb.get("status_code") != 200:
        return
    url = pb.get("url")
    if medidas["meta_description"] and (pa.get("meta_description") or None) != (pb.get("meta_description") or None):
        cambios["meta_description"].append(
            {"url": url, "antes": pa.get("meta_description"), "ahora": pb.get("meta_description")})
    for campo, leer in (("sd_tipos", _tipos), ("hreflang", _idiomas)):
        if medidas[campo]:
            ta, tb = leer(pa), leer(pb)
            if ta != tb:
                cambios[campo].append({
                    "url": url, "antes": ", ".join(sorted(ta)) or None,
                    "ahora": ", ".join(sorted(tb)) or None,
                    "pierde": sorted(ta - tb), "gana": sorted(tb - ta)})
    if medidas["inlinks"] and _inlinks_cambian(pa.get("inlinks"), pb.get("inlinks")):
        cambios["inlinks"].append({"url": url, "antes": pa.get("inlinks"), "ahora": pb.get("inlinks")})
    if medidas["click_depth"]:
        ca, cb = pa.get("click_depth"), pb.get("click_depth")
        if (ca is None) != (cb is None) or (ca is not None and abs(cb - ca) >= UMBRAL_CLICS):
            cambios["click_depth"].append({"url": url, "antes": ca, "ahora": cb})
    if medidas["pagerank_score"]:
        ra, rb = pa.get("pagerank_score"), pb.get("pagerank_score")
        if ra is not None and rb is not None and abs(rb - ra) >= UMBRAL_PAGERANK:
            cambios["pagerank_score"].append({"url": url, "antes": ra, "ahora": rb})


def _inlinks_cambian(ia, ib) -> bool:
    """Si los entrantes se mueven de verdad, en cualquiera de los dos sentidos."""
    ia, ib = ia or 0, ib or 0
    mayor = max(ia, ib)
    return bool(mayor) and abs(ib - ia) >= MINIMO_INLINKS_PERDIDOS and abs(ib - ia) / mayor >= UMBRAL_INLINKS


def _pierde_inlinks(ia, ib) -> bool:
    ia, ib = ia or 0, ib or 0
    return ia > 0 and (ia - ib) >= MINIMO_INLINKS_PERDIDOS and (ia - ib) / ia >= UMBRAL_INLINKS


def _clasificar(pa, pb, afectadas, bases, umbral_palabras, medidas=None,
                textos=None) -> None:
    """Pone una página en la regla que nombra su CAUSA, y solo en una.

    Un aviso por hallazgo (decisión 36): una página que pierde el índice porque
    le han puesto un canonical a otra URL no se cuenta además en
    `salen_del_indice`, que diría lo mismo sin decir qué arreglar.
    """
    url = pb.get("url")
    g = _grupo(pb, pa)
    bases["todas_las_comunes"][g] += 1

    # El canonical se va a otro host: se mira ANTES de todo lo demás y sin
    # exigir que la página fuera indexable. Lo que abandona el sitio es el
    # destino de la consolidación, no esta página.
    fuera_antes = _canonical_fuera(pa)
    fuera_ahora = _canonical_fuera(pb)
    if fuera_ahora and not fuera_antes:
        afectadas["canonical_a_otro_host"].append(
            {"url": url, "antes": pa.get("canonical_href"), "ahora": fuera_ahora, "_g": g})

    if not _era_indexable(pa):
        bases["no_era_indexable"][g] += 1
        if _era_indexable(pb):
            afectadas["entran_en_el_indice"].append({"url": url, "_g": g})
        return

    bases["era_indexable"][g] += 1

    codigo = pb.get("status_code")
    can_antes, can_ahora = _canonical_a_otra(pa), _canonical_a_otra(pb)
    if can_ahora and not can_antes:
        # Si el destino está fuera del sitio ya se contó arriba: un aviso por
        # hallazgo (decisión 36), y el de fuera dice qué arreglar.
        if not fuera_ahora:
            afectadas["canonical_a_otra_url"].append(
                {"url": url, "antes": pa.get("canonical_href"), "ahora": can_ahora, "_g": g})
    elif codigo and 400 <= codigo < 600:
        afectadas["rotas"].append({"url": url, "antes": 200, "ahora": codigo, "_g": g})
    elif codigo and 300 <= codigo < 400:
        afectadas["redirigidas"].append({"url": url, "antes": 200, "ahora": codigo, "_g": g})
    elif not _era_indexable(pb):
        afectadas["salen_del_indice"].append(
            {"url": url, "antes": pa.get("indexability_status"),
             "ahora": pb.get("indexability_status"), "_g": g})
    else:
        # Sigue indexable: los cambios de grado, que no la sacan del índice.
        wa, wb = pa.get("word_count") or 0, pb.get("word_count") or 0
        if wa and (wa - wb) / wa >= umbral_palabras:
            afectadas["pierden_contenido"].append(
                {"url": url, "antes": wa, "ahora": wb, "_g": g})
        textos = textos or _comparador_de_textos(None)
        if textos(pa.get("title"), pb.get("title")):
            afectadas["cambia_el_titulo"].append(
                {"url": url, "antes": pa.get("title"), "ahora": pb.get("title"), "_g": g})
        if medidas:
            _clasificar_131(pa, pb, afectadas, bases, medidas, url, g, textos)


def _clasificar_131(pa, pb, afectadas, bases, medidas, url, g, textos=None) -> None:
    """Los cambios de grado de la decision 131, en una pagina que sigue indexable."""
    # Enlazado: una familia, un hallazgo por pagina (decision 36).
    ca, cb = pa.get("click_depth"), pb.get("click_depth")
    if (medidas["click_depth"] and ca is not None
            and (cb is None or cb - ca >= UMBRAL_CLICS)):
        afectadas["se_alejan_de_la_home"].append(
            {"url": url, "antes": ca, "ahora": cb, "_g": g})
    elif medidas["inlinks"] and _pierde_inlinks(pa.get("inlinks"), pb.get("inlinks")):
        afectadas["pierden_enlaces_internos"].append(
            {"url": url, "antes": pa.get("inlinks"), "ahora": pb.get("inlinks"), "_g": g})
    elif (medidas["pagerank_score"] and pa.get("pagerank_score") is not None
          and pb.get("pagerank_score") is not None
          and pa["pagerank_score"] - pb["pagerank_score"] >= UMBRAL_PAGERANK):
        afectadas["pierden_pagerank"].append(
            {"url": url, "antes": pa["pagerank_score"], "ahora": pb["pagerank_score"], "_g": g})

    if medidas["sd_tipos"] and _tipos(pa):
        bases["indexable_con_datos_estructurados"][g] += 1
        perdidos = _tipos(pa) - _tipos(pb)
        if perdidos:
            afectadas["pierden_datos_estructurados"].append(
                {"url": url, "antes": ", ".join(sorted(_tipos(pa))),
                 "ahora": ", ".join(sorted(_tipos(pb))) or None,
                 "pierde": sorted(perdidos), "_g": g})
    if medidas["hreflang"] and _idiomas(pa):
        bases["indexable_con_hreflang"][g] += 1
        perdidos = _idiomas(pa) - _idiomas(pb)
        if perdidos:
            afectadas["pierden_hreflang"].append(
                {"url": url, "antes": ", ".join(sorted(_idiomas(pa))),
                 "ahora": ", ".join(sorted(_idiomas(pb))) or None,
                 "pierde": sorted(perdidos), "_g": g})
    textos = textos or _comparador_de_textos(None)
    if (medidas["meta_description"]
            and textos(pa.get("meta_description"), pb.get("meta_description"))):
        afectadas["cambia_la_description"].append(
            {"url": url, "antes": pa.get("meta_description"),
             "ahora": pb.get("meta_description"), "_g": g})


def _comparador_de_textos(ignorar: list[str] | None):
    """`distintos(a, b)` para el title, el h1 y la description (decision 230).

    Siempre se pliegan los espacios —Google tambien lo hace al mostrar un
    title—: `Hoteles  en Gran Canaria` y `Hoteles en Gran Canaria` no son un
    cambio. Con `ignorar`, ademas, se quita lo que case con cada patron del
    cliente (un año, `(123 productos)`) antes de comparar. Un patron que
    no compila se salta: en la BD a mano puede haber cualquier cosa, y una
    regex rota no puede tumbar la comparacion entera (ni su alerta critica).
    Vacio o None, igual que antes salvo los espacios: None es None.
    """
    patrones = []
    for p in ignorar or ():
        try:
            patrones.append(re.compile(p))
        except (re.error, TypeError):
            logger.warning("ignorar_en_textos: patron no valido, se salta: %r", p)

    def limpio(t):
        if t is None:
            return None
        t = str(t)[:2000]
        for p in patrones:
            t = p.sub(" ", t)
        return " ".join(t.split()) or None

    def distintos(a, b) -> bool:
        if a == b:
            return False
        return limpio(a) != limpio(b)

    return distintos


def _sin_grupo(fila: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in fila.items() if k != "_g"}


def _alerta(regla, severidad, que_decide, filas, base, umbral_absoluto=None,
            pct_sitio=PCT_ALERTA, min_paginas=MINIMO_PAGINAS,
            pct_plantilla=PCT_ALERTA_PLANTILLA) -> dict[str, Any] | None:
    """Una regla contra su umbral: en el sitio, en un segmento o en una plantilla.

    Tres disparadores, porque una plantilla entera rota se diluye en el total:
    las 2.367 páginas de Lopesan son el 99,5% de su plantilla y el 11% del
    sitio. Si solo se mirara el total, el fallo más grave que hemos encontrado
    en un cliente no habría disparado nada. Y el segmento de negocio (decisión
    125) es como lo lee el consultor: «el 60% de las fichas» dice qué mirar,
    `/:slug (1n)` no (decisión 127).

    `base` cuenta por (forma de ruta, segmento). Un segmento cuyas páginas son
    EXACTAMENTE las de una plantilla —la regla `^/blog/` y la forma
    `/blog/:slug`— es el mismo hallazgo con dos nombres: sale una vez, como
    segmento, con la plantilla al lado, y no se repite en la lista de
    plantillas (un aviso por hallazgo, decisión 36).
    """
    de = sum(base.values())
    if not filas or not de:
        return None

    base_pl: dict[str, int] = defaultdict(int)
    base_seg: dict[str, int] = defaultdict(int)
    firmas_de_seg: dict[str, set] = defaultdict(set)
    segs_de_firma: dict[str, set] = defaultdict(set)
    for (firma, seg), n in base.items():
        if not n:
            continue
        base_pl[firma] += n
        segs_de_firma[firma].add(seg if _segmento_propio(seg) else None)
        if _segmento_propio(seg):
            base_seg[seg] += n
            firmas_de_seg[seg].add(firma)

    por_pl: dict[str, int] = defaultdict(int)
    por_seg: dict[str, int] = defaultdict(int)
    for f in filas:
        firma, seg = f.get("_g") or (_firma(f.get("url")), None)
        por_pl[firma] += 1
        if _segmento_propio(seg):
            por_seg[seg] += 1

    def coincide(seg: str) -> str | None:
        fs = firmas_de_seg.get(seg) or set()
        if len(fs) != 1:
            return None
        (firma,) = fs
        return firma if segs_de_firma.get(firma) == {seg} else None

    segmentos = sorted(
        ({"segmento": k, "paginas": v, "de": base_seg.get(k, v),
          "pct": round(100 * v / max(1, base_seg.get(k, v)), 1),
          "plantilla": coincide(k)}
         for k, v in por_seg.items()),
        key=lambda d: (-d["pct"], -d["paginas"]))
    ya_dichas = {s["plantilla"] for s in segmentos if s["plantilla"]}
    plantillas = sorted(
        ({"plantilla": k, "paginas": v, "de": base_pl.get(k, v),
          "pct": round(100 * v / max(1, base_pl.get(k, v)), 1)}
         for k, v in por_pl.items() if k not in ya_dichas),
        key=lambda d: (-d["pct"], -d["paginas"]))

    def salta(grupos):
        return any(p["paginas"] >= min_paginas
                   and p["pct"] >= pct_plantilla * 100 for p in grupos)

    pct = len(filas) / de
    if umbral_absoluto is not None:
        # Una lista (decision 128): cada URL la eligio alguien, y el piso
        # de 20 impedia alertar en una lista de 50 aunque fallaran 10.
        salta_sitio = len(filas) >= umbral_absoluto
        salta_segmento = salta_plantilla = False
    else:
        salta_sitio = len(filas) >= min_paginas and pct >= pct_sitio
        salta_segmento = salta(segmentos)
        salta_plantilla = salta(plantillas)
    if not (salta_sitio or salta_segmento or salta_plantilla):
        return None
    return {
        "regla": regla,
        "severidad": severidad,
        "que_decide_google": que_decide,
        "paginas": len(filas),
        "de": de,
        "pct": round(pct * 100, 1),
        "por": ("lista" if umbral_absoluto is not None
                else "sitio" if salta_sitio
                else "segmento" if salta_segmento else "plantilla"),
        "segmentos": segmentos[:5],
        "plantillas": plantillas[:5],
        "ejemplos": [_sin_grupo(f) for f in filas[:MUESTRA]],
    }


_ORDEN_SEVERIDAD = {"critical": 0, "warning": 1, "info": 2}


def _ordenar_alertas(alertas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(alertas, key=lambda d: (_ORDEN_SEVERIDAD[d["severidad"]], -d["paginas"]))


def _alertas(afectadas, bases, umbral_absoluto=None, umbrales=None) -> list[dict[str, Any]]:
    """Las reglas de página que superan el umbral (ver `_alerta`).

    `umbrales` son los de un cliente (decision 135, `shared.reglas`): por regla,
    `activa` y los tres umbrales. Lo que no trae se queda con lo de serie.
    """
    salida = []
    for regla, (severidad, que_decide) in REGLAS.items():
        # En una lista (decision 128) mandan su umbral absoluto y todas las
        # reglas: el veredicto de un QA de despliegue no puede depender de que
        # alguien apagara una regla ruidosa para los censos completos.
        u = {} if umbral_absoluto is not None else ((umbrales or {}).get(regla) or {})
        if u.get("activa") is False:
            continue
        al = _alerta(regla, severidad, que_decide, afectadas[regla],
                     bases[BASE_DE_LA_REGLA[regla]], umbral_absoluto,
                     pct_sitio=u.get("pct_sitio", PCT_ALERTA),
                     min_paginas=u.get("min_paginas", MINIMO_PAGINAS),
                     pct_plantilla=u.get("pct_plantilla", PCT_ALERTA_PLANTILLA))
        if al is not None:
            salida.append(al)
    return _ordenar_alertas(salida)


# Tipos que van UNO POR PLANTILLA anclados en una URL elegida entre las del
# grupo (decision 122: la de URL menor). Entre dos censos el ancla se mueve en
# cuanto se rastrea otra pagina de la serie sin que el hallazgo cambie, asi que
# se casan por (tipo, host, group_key) y no por la URL; sin esto la misma serie
# salia «resuelta» en /cat/page/3/ y «nueva» en /cat/page/2/. Repite
# `analysis.avisos_de_paginacion.TIPOS_DE_PLANTILLA` (la imagen de la API no
# lleva `analysis/`; un test comprueba que coinciden). Otros avisos por grupo
# (imagenes, cabeceras por host) tienen el mismo riesgo y no se tocan aqui:
# cambiar como casan es otra decision, con su propia medida.
ANCLADOS_POR_GRUPO = frozenset({
    # Logs del servidor (decision 213): la plantilla, no el ejemplo.
    "indexable_sin_visitas_googlebot",
    "googlebot_recibe_error",
    # Trampas de rastreo (decision 214): la plantilla, no el ejemplo.
    "trampa_de_rastreo",
    "paginacion_canonical_a_la_primera",
    "paginacion_noindex",
    "solo_enlazada_desde_paginacion_profunda",
    "paginacion_sin_enlace",
    "paginacion_siguiente_rota",
    "paginacion_rel_incorrecto",
    # Una fila por host con las plantillas que responden 200 a una URL que no
    # existe (decision 190): se ancla en la URL menor de sus paginas, que
    # cambia de un censo a otro.
    "soft_404_plantilla",
}) | TIPOS_AXE


# Los avisos de axe (decision 174) son de una MUESTRA por plantilla: uno por
# (regla, plantilla), anclado en la URL menor de las paginas muestreadas, y la
# muestra cambia de un rastreo a otro con la concurrencia. Por eso casan por
# grupo (arriba), y ademas «nueva» solo se afirma si el censo ANTERIOR evaluo
# esa plantilla con axe, y «resuelta» si la evaluo el NUEVO: con axe apagado,
# o sin muestra de esa plantilla, que un aviso falte no dice nada (67, 89).
# Cuentan aparte, en `no_afirmables_por_muestra`.
TIPOS_POR_MUESTRA = TIPOS_AXE


# Avisos que salen del TRAFICO de la ventana y de un ranking con tope (decision
# 157): que una oportunidad pase del puesto 100 al 101, o que los clics de una
# busqueda se muevan, no es que el sitio haya cambiado. No entran en «nuevas»
# ni en «resueltas»: ninguna de las dos se puede afirmar.
NO_COMPARABLES = frozenset({
    "oportunidad_posicion",
    "ctr_bajo_para_posicion",
    "canibalizacion_por_consulta",
    # Los de backlinks (decision 212) dependen del CSV que haya subido el
    # cliente al analizar cada censo, no del sitio: subir uno nuevo no es «el
    # sitio empeoro».
    "backlinks_a_error",
    "backlinks_a_noindex",
    "backlinks_a_bloqueada_robots",
    # Los de logs (decision 213), igual: dependen del log subido.
    "indexable_sin_visitas_googlebot",
    "googlebot_recibe_error",
})


def incidencias_de_censo(db, job_id) -> list[dict[str, Any]]:
    """Las incidencias de un censo con lo que las identifica entre censos.

    «El mismo hallazgo» es `(issue_type, url, group_key)` (#32). Con tipo y
    URL no basta: un hreflang mal escrito emite una incidencia por código de
    idioma, y un título duplicado pertenece a un grupo. La URL va por su
    TEXTO, no por `urls.id`, que cambia entre censos.
    """
    from shared.models import Issue, Url

    filas = (
        db.query(Issue.issue_type, Issue.severity, Issue.group_key, Url.url)
        .join(Url, Url.id == Issue.url_id)
        .filter(Issue.job_id == job_id)
        .all()
    )
    salida = [
        {"issue_type": f.issue_type, "severity": f.severity,
         "group_key": f.group_key, "url": f.url}
        for f in filas
    ]
    # Los de axe llevan su plantilla (de los detalles): la comparacion mira si
    # el otro censo la evaluo. Pocas filas: una por regla y plantilla.
    if any(i["issue_type"] in TIPOS_POR_MUESTRA for i in salida):
        plantilla = {}
        for f in (db.query(Issue.issue_type, Issue.group_key, Url.url, Issue.details)
                  .join(Url, Url.id == Issue.url_id)
                  .filter(Issue.job_id == job_id,
                          Issue.issue_type.in_(sorted(TIPOS_POR_MUESTRA)))
                  .all()):
            if isinstance(f.details, dict):
                plantilla[(f.issue_type, f.url, f.group_key)] = f.details.get("plantilla")
        for i in salida:
            if i["issue_type"] in TIPOS_POR_MUESTRA:
                i["plantilla"] = plantilla.get((i["issue_type"], i["url"], i["group_key"]))
    return salida


def comparar_incidencias(
    incidencias_a: list[dict[str, Any]],
    incidencias_b: list[dict[str, Any]],
    *,
    mapa_hosts: dict[str, str] | None = None,
    puede_afirmar_resueltas: bool = True,
    urls_del_nuevo: set[str] | None = None,
    urls_del_anterior: set[str] | None = None,
    analisis_a: str | None = None,
    analisis_b: str | None = None,
    mapa_rutas=None,
    plantillas_axe_a: set[str] | None = None,
    plantillas_axe_b: set[str] | None = None,
) -> dict[str, Any]:
    """Qué se arregló, qué apareció y qué sigue, entre dos censos.

    Es lo que convierte una auditoría suelta en un seguimiento: «qué arregló
    el cliente desde la vez pasada» no se puede contestar comparando páginas.

    `puede_afirmar_resueltas` es la decisión 2 de #32 llevada a las
    incidencias: si el censo ANTERIOR está truncado, que un hallazgo no
    aparezca ahora puede ser que no se llegara a su página. Se cuentan aparte
    y no se llaman «resueltas».

    `urls_del_nuevo` cierra el mismo agujero por el otro lado, y hace falta
    aunque los dos censos terminen enteros: **una incidencia en una página que
    ya no está en el censo no está resuelta, no se sabe**. Medido con dos
    censos reales de progym en los que desaparecieron 1.205 URLs: sin esto el
    informe decía **4.794 resueltas** y las tres primeras clases —1.152
    `noindex_page`, 1.146 `canonical_missing`, 938 `hreflang_missing_return`—
    eran páginas que sencillamente no se volvieron a visitar. Decírselo así a
    un cliente es felicitarle por un trabajo que no ha hecho.

    `urls_del_anterior` (decision 131) separa las NUEVAS en dos preguntas
    distintas: una incidencia nueva en una URL que ya existia es algo que se
    ha ROTO (una regresion: la pagina estaba y ahora tiene el problema), y una
    en una URL nueva es algo que se ha PUBLICADO mal. Mezcladas, «300 nuevas»
    no dice si alguien ha estropeado lo que habia o si la seccion recien
    lanzada viene sin description. Son las URLs del censo anterior ya con los
    mapeos aplicados y sin los muros: una pagina que antes fue un muro no se
    vio, y su incidencia no es una regresion que se pueda afirmar.

    `mapa_rutas` reescribe las URLs de las incidencias del ANTERIOR, igual que
    en `comparar_censos`: tras una migracion, el titulo duplicado de
    `/es/hoteles/x.html` es el de `/es/hotel/x/`.

    `plantillas_axe_a` y `plantillas_axe_b` (decision 174): las plantillas que
    cada censo evaluo con axe (vacio con axe apagado; None si no se sabe). Un
    aviso de axe solo es «nuevo» si el anterior evaluo su plantilla, y
    «resuelto» si la evaluo el nuevo; si no, va a `no_afirmables_por_muestra`.
    """
    # Dos censos analizados con codigo distinto NO se comparan por incidencias.
    # Un aviso no basta: no impide que la cifra sea falsa ni que alguien la
    # copie a un informe. Medido el 2026-10-13, el dia que se anadio
    # `group_key`: el censo de referencia de Lopesan tenia 11.414 incidencias
    # y CERO claves, y el siguiente las tendria todas. Ningun hallazgo
    # agrupado —duplicados, hreflang, imagenes, datos estructurados— habria
    # casado, y los miles afectados habrian salido como "resuelto" y "nuevo" a
    # la vez. Es la misma regla que las ausencias de un censo truncado
    # (decision 67): lo que no se puede afirmar, no se afirma.
    #
    # Desconocido tampoco vale. Un censo anterior al sello (decision 72) pudo
    # analizarse con cualquier cosa, y callarse equivale a afirmar que fue con
    # el mismo codigo.
    if not (analisis_a and analisis_b and analisis_a == analisis_b):
        cual = (f"{analisis_a or 'desconocida'} y {analisis_b or 'desconocida'}")
        return {
            "comparable": False,
            "motivo": (
                f"los dos censos se analizaron con versiones distintas del "
                f"codigo ({cual}), asi que un hallazgo puede aparecer como "
                f"resuelto solo porque la regla que lo emitia ha cambiado. "
                f"Para compararlos, vuelve a analizar el mas antiguo con el "
                f"codigo de hoy."
            ),
        }

    mapa_hosts = mapa_hosts or {}
    reglas_rutas = compilar_mapa_rutas(mapa_rutas)

    def url_de(i, rutas=None):
        u = _aplicar_mapa(i.get("url") or "", mapa_hosts)
        if rutas:
            u = _aplicar_rutas(u, rutas)[0]
        return _norm(u)

    def clave(i, rutas=None):
        if i["issue_type"] in ANCLADOS_POR_GRUPO and i.get("group_key"):
            # El hallazgo es la plantilla del listado en ese host, y la URL
            # donde se ancla puede cambiar entre censos (decision 122).
            return (i["issue_type"], urlsplit(url_de(i, rutas)).hostname or "", i["group_key"])
        return (i["issue_type"], url_de(i, rutas), i.get("group_key"))

    a = {clave(i, reglas_rutas): i for i in incidencias_a if i["issue_type"] not in NO_COMPARABLES}
    b = {clave(i): i for i in incidencias_b if i["issue_type"] not in NO_COMPARABLES}

    def evaluada(i, plantillas) -> bool:
        return plantillas is not None and i.get("plantilla") in plantillas

    nuevas, por_muestra = [], []
    for k in b.keys() - a.keys():
        if b[k]["issue_type"] in TIPOS_POR_MUESTRA and not evaluada(b[k], plantillas_axe_a):
            por_muestra.append(b[k])     # el anterior no miro esa plantilla
        else:
            nuevas.append(b[k])
    siguen = [b[k] for k in a.keys() & b.keys()]

    idas, sin_pagina = [], []
    for k in a.keys() - b.keys():
        if a[k]["issue_type"] in TIPOS_POR_MUESTRA:
            # De plantilla: si el nuevo evaluo la plantilla, aunque fuera en
            # otra pagina, el aviso se fue; si no, no se sabe.
            (idas if evaluada(a[k], plantillas_axe_b) else por_muestra).append(a[k])
        elif urls_del_nuevo is not None and url_de(a[k], reglas_rutas) not in urls_del_nuevo:
            sin_pagina.append(a[k])      # su pagina no se volvio a visitar
        else:
            idas.append(a[k])

    def por_tipo(lista):
        cuenta: dict[str, dict[str, Any]] = {}
        for i in lista:
            fila = cuenta.setdefault(
                i["issue_type"], {"tipo": i["issue_type"],
                                  "severidad": i.get("severity"), "total": 0})
            fila["total"] += 1
        orden = {"error": 0, "warning": 1, "info": 2}
        return sorted(cuenta.values(),
                      key=lambda f: (orden.get(f["severidad"], 3), -f["total"]))

    resultado = {
        "comparable": True,
        "nuevas": {"total": len(nuevas), "por_tipo": por_tipo(nuevas),
                   "ejemplos": [i["url"] for i in nuevas[:MUESTRA]]},
        "siguen": {"total": len(siguen), "por_tipo": por_tipo(siguen)},
    }
    if urls_del_anterior is not None:
        # Las ancladas por grupo (decision 122) cuentan por la URL donde se
        # anclan hoy: es la pagina del listado en la que se ve el problema.
        existentes = [i for i in nuevas if url_de(i) in urls_del_anterior]
        en_nueva = [i for i in nuevas if url_de(i) not in urls_del_anterior]
        resultado["nuevas"]["en_url_existente"] = {
            "total": len(existentes), "por_tipo": por_tipo(existentes),
            "ejemplos": [i["url"] for i in existentes[:MUESTRA]]}
        resultado["nuevas"]["en_url_nueva"] = {
            "total": len(en_nueva), "por_tipo": por_tipo(en_nueva),
            "ejemplos": [i["url"] for i in en_nueva[:MUESTRA]]}
        # Con el anterior truncado, una URL que «no estaba» puede ser una que
        # no se alcanzo: la regresion se puede afirmar (la URL estaba y ahora
        # tiene el problema), la novedad de la URL no (decision 67).
        resultado["nuevas"]["url_nueva_afirmable"] = puede_afirmar_resueltas
    resultado["sin_pagina_en_el_nuevo"] = len(sin_pagina)
    resultado["no_afirmables_por_muestra"] = {
        "total": len(por_muestra), "por_tipo": por_tipo(por_muestra)}
    if puede_afirmar_resueltas:
        resultado["resueltas"] = {
            "total": len(idas), "por_tipo": por_tipo(idas),
            "ejemplos": [i["url"] for i in idas[:MUESTRA]]}
        resultado["resueltas_no_afirmables"] = 0
    else:
        # Ni se enumeran: una lista de "quizas resueltas" se lee como una
        # lista de resueltas en cuanto alguien la copia a un informe.
        resultado["resueltas"] = None
        resultado["resueltas_no_afirmables"] = len(idas) + len(sin_pagina)
        resultado["sin_pagina_en_el_nuevo"] = 0
    return resultado


# --- Acceso a base de datos -------------------------------------------------
#
# Las dos consultas viven aqui y no en el router de la API porque las necesitan
# los DOS: el endpoint y el worker, que compara cada rastreo recien terminado
# con el anterior del mismo sitio. Tenerlas por duplicado es como se llega a un
# desacuerdo silencioso entre dos cifras que dicen medir lo mismo (decisiones
# 23 y 39).


def paginas_de_censo(db, job_id) -> list[dict[str, Any]]:
    """Las páginas HTML de un censo con los campos que se comparan.

    Solo HTML: comparar el `title` de un PDF o de una imagen no dice nada, y
    el ruido taparía los cambios que sí importan.
    """
    from sqlalchemy import func, or_

    from shared.models import Heading, HtmlMeta, Url

    filas = (
        db.query(
            Url.id, Url.segmento,
            Url.url, Url.status_code, Url.indexability_status, Url.word_count,
            Url.response_class,
            Url.unique_inlinks_count, Url.click_depth, Url.pagerank_score, Url.in_sitemap,
            Url.content_hash,
            HtmlMeta.canonical_href, HtmlMeta.title,
            HtmlMeta.canonical_distintos, HtmlMeta.meta_description,
        )
        .outerjoin(HtmlMeta, HtmlMeta.url_id == Url.id)
        .filter(Url.job_id == job_id, Url.is_internal.is_(True), Url.is_html.is_(True))
        .all()
    )
    # El primer h1 que se PINTA de cada página (decisión 46: los ocultos se
    # guardan pero no cuentan).
    h1s = dict(
        db.query(Url.url, func.min(Heading.text))
        .join(Heading, Heading.url_id == Url.id)
        .filter(
            Url.job_id == job_id, Heading.tag == "h1",
            or_(Heading.oculto.is_(False), Heading.oculto.is_(None)),
        )
        .group_by(Url.url)
        .all()
    )
    extraido = extraido_de_censo(db, job_id)
    tipos, idiomas = _tipos_e_idiomas_de_censo(db, job_id)
    return [
        {
            "url": f.url, "status_code": f.status_code,
            "indexability_status": f.indexability_status,
            "canonical_href": f.canonical_href, "title": f.title,
            "canonical_distintos": f.canonical_distintos,
            "h1": h1s.get(f.url), "word_count": f.word_count,
            "response_class": f.response_class,
            "segmento": f.segmento,
            "extraido": extraido.get(f.id) or {},
            # Decision 131. `inlinks` son las paginas DISTINTAS que la enlazan.
            "inlinks": f.unique_inlinks_count,
            "click_depth": f.click_depth,
            "pagerank_score": f.pagerank_score,
            "meta_description": f.meta_description,
            # El trafico entre censos (decision 158) agrupa por «sale del sitemap».
            "in_sitemap": f.in_sitemap,
            # Y por «cambia el contenido», mejor por el hash del contenido
            # principal que por las palabras (decision 158, #167).
            "content_hash": f.content_hash,
            "sd_tipos": tipos.get(f.id, []),
            "hreflang": idiomas.get(f.id, []),
        }
        for f in filas
    ]


def _tipos_e_idiomas_de_censo(db, job_id) -> tuple[dict[int, list], dict[int, list]]:
    """Tipos de datos estructurados y codigos hreflang de cada pagina del censo.

    Las dos tablas cuelgan de `url_id` y no llevan `job_id`, asi que se une con
    `urls`: son decenas de filas por pagina, no los cientos de millones de
    `links` que prohiben unir (decision 37). Los tipos sin nombre (un nodo
    que solo es una referencia, decision 51) no cuentan, ni los de un JSON-LD
    que Google descarta por no ser JSON estricto (80), y el hreflang del
    `<body>` tampoco, porque Google no lo lee (decision 56).

    Un `@type` lista (`["Organization", "LocalBusiness"]`) se guarda como un
    solo `schema_type` unido con ", " (extractors._tipo_normalizado), asi que
    aqui se parte en tipos sueltos: comparado como atomo, una pagina que pasa
    de `Organization` a `["Organization", "LocalBusiness"]` «perderia»
    Organization aunque siga ahi, y cambiar el orden del array «perderia» los
    dos. Un nombre de schema.org no lleva coma, asi que partir es seguro.
    """
    from sqlalchemy import or_

    from shared.models import Hreflang, StructuredData, Url

    tipos: dict[int, set] = defaultdict(set)
    for url_id, tipo in (db.query(StructuredData.url_id, StructuredData.schema_type)
                         .join(Url, Url.id == StructuredData.url_id)
                         # Un JSON-LD que no es JSON estricto Google lo tira
                         # entero (decision 80): aunque el lector permisivo
                         # saque su tipo, para el resultado enriquecido no esta.
                         .filter(Url.job_id == job_id, StructuredData.schema_type.isnot(None),
                                 StructuredData.json_invalido.is_(None))
                         .distinct()):
        for suelto in tipo.split(","):
            suelto = suelto.strip()
            if suelto:
                tipos[url_id].add(suelto)
    idiomas: dict[int, set] = defaultdict(set)
    for url_id, lang in (db.query(Hreflang.url_id, Hreflang.lang)
                         .join(Url, Url.id == Hreflang.url_id)
                         .filter(Url.job_id == job_id,
                                 or_(Hreflang.en_body.is_(False), Hreflang.en_body.is_(None)))
                         .distinct()):
        idiomas[url_id].add((lang or "").strip().lower())
    return ({k: sorted(v) for k, v in tipos.items()},
            {k: sorted(v) for k, v in idiomas.items()})


def extraido_de_censo(db, job_id) -> dict[int, dict[str, dict[str, Any]]]:
    """{url_id: {regla: {clase, estado, valor, num}}} de la extraccion a medida.

    Por `custom_extraction.job_id`, sin unir con `urls` (decision 37): el indice
    `ix_cext_job_nombre_estado` empieza por el job. `valor_clave` y no `valor`:
    ya va con los espacios colapsados y recortado a 256, que es lo que hace
    falta para comparar sin arrastrar el contexto entero de una busqueda.
    """
    from shared.models import CustomExtraction as C

    salida: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for f in (db.query(C.url_id, C.nombre, C.clase, C.estado, C.valor_clave,
                       C.valor_num, C.render)
              .filter(C.job_id == job_id)
              .yield_per(5000)):
        salida[f.url_id][f.nombre] = {"clase": f.clase, "estado": f.estado,
                                      "valor": f.valor_clave, "num": f.valor_num,
                                      "render": f.render}
    return salida


def resumen_de_job(job) -> dict[str, Any]:
    """Lo que la comparación necesita saber del rastreo, no de sus páginas."""
    return {
        "semilla": (job.seeds or [None])[0],
        # Las semillas ENTERAS, no solo la primera: dos rastreos del mismo host
        # pueden tener dos alcances distintos, y entonces lo que "falta" puede
        # no haber estado nunca en el alcance (decisión 70).
        "semillas": list(job.seeds or []),
        "render_js": (job.config or {}).get("render_js"),
        # 0 es una lista (decision 128): no sigue enlaces, y su grafo no se
        # compara con el de un censo (decision 131).
        "max_depth": (job.config or {}).get("max_depth"),
        # movil o escritorio, por el UA del job (decision 119)
        "perfil": perfil_de_ua((job.config or {}).get("user_agent")),
        "status": job.status,
        "finish_reason": job.finish_reason,
        "crawler_version": job.crawler_version,
        "analisis_version": getattr(job, "analisis_version", None),
        # Para no comparar un censo bloqueado como si fuera el sitio (103).
        "salud": getattr(job, "health", None),
        "nombre": job.name,
        "fecha": job.started_at.isoformat() if job.started_at else None,
        # Que reglas a medida se aplicaron y como: solo se compara una que
        # exista igual en los dos censos (decision 127).
        "reglas_a_medida": reglas_a_medida(job.config),
    }


def censo_anterior(db, job):
    """Con qué censo hay que comparar este, si hay alguno.

    **Si el rastreo lo lanzó una programación, se compara con el anterior de
    ESA programación**, no con lo último que pasara por ese host. La regla del
    host sola elige mal en cuanto alguien lanza algo a mano: comprobado el
    2026-10-09 en producción, el segundo canario de Lopesan se comparó con el
    primero —117 URLs en común de 250— en vez de con el censo completo. Llevado
    a un rastreo semanal de 5.000 páginas, se compararía contra un canario de
    250 que alguien lanzó el martes.

    Y no es cosmético: **las alertas se miden sobre las páginas que están en
    los dos censos**. Si la referencia cubre 250 páginas y el fallo afecta a
    2.319 que no están entre ellas, la alerta NO salta. El guardia de alcance
    (decisión 70) evita afirmar ausencias falsas, pero no evita ese silencio, y
    un silencio se lee igual que «no ha cambiado nada».

    Para un rastreo lanzado a mano se mantiene la regla del host: es lo único
    que se sabe de él.
    """
    from shared.models import Job

    if not job.seeds or not job.started_at:
        return None

    # Un censo con UA de movil y otro de escritorio no ven la misma pagina en
    # un sitio con servido dinamico o m-dot (decisiones 119 y 173): comparar
    # uno con otro atribuiria al sitio lo que es del dispositivo, y las alertas
    # saltarian por eso. Solo es referencia un censo del MISMO perfil; si no
    # hay ninguno, no se compara (como con una lista frente a un censo).
    yo_perfil = perfil_de_ua((job.config or {}).get("user_agent"))

    def mismo_perfil(c) -> bool:
        return perfil_de_ua((c.config or {}).get("user_agent")) == yo_perfil

    programacion = getattr(job, "programacion_id", None)
    if programacion:
        de_la_serie = next((
            c for c in db.query(Job)
            .filter(Job.id != job.id, Job.programacion_id == programacion,
                    Job.status == "completed", Job.started_at.isnot(None),
                    Job.started_at < job.started_at)
            .order_by(Job.started_at.desc())
            .yield_per(50)
            if mismo_perfil(c)), None)
        if de_la_serie is not None:
            return de_la_serie
        # Primera ejecución de la serie: se cae a la regla del host, que ahora
        # elige por ALCANCE y no solo por fecha. Ver abajo.

    host = _host(job.seeds[0])
    if not host:
        return None
    # Se recorre de más reciente a más antiguo. En lotes y no con un `limit`:
    # con un tope fijo, en una instalación con varios clientes los rastreos de
    # los demás se comen la ventana y el censo anterior de ESTE sitio queda
    # fuera — y la ausencia de alerta se lee igual que «no ha cambiado nada».
    # El host no se puede filtrar en SQL sin atarse a Postgres: `seeds` es JSON
    # y la primera semilla no es una columna.
    #
    # Y entre los del mismo host se prefiere el que ABARQUE lo mismo, no el más
    # reciente. Medido en producción el 2026-10-13: el primer censo semanal de
    # Lopesan (3.040 semillas) eligió como referencia un **rastreo de prueba de
    # 40 URLs** de cuatro días antes, porque era el más reciente de ese host.
    # Resultado: 40 URLs en común de 3.884. Los guardias hicieron su trabajo
    # —no concluyente, sin alertas, nada falso afirmado— pero con 40 páginas en
    # común no se habría visto nada **aunque el sitio se hubiera roto**, y eso
    # se lee igual que «no ha cambiado nada», que es contra lo que existen las
    # decisiones 67 a 78.
    #
    # «Abarcar lo mismo» es la contención de la decisión 70: que las semillas
    # del candidato cubran las de este censo. Si ninguno la cumple se devuelve
    # el más reciente, que es lo de antes: comparar con algo del mismo sitio
    # sigue siendo mejor que no comparar con nada.
    consulta = (
        db.query(Job)
        .filter(Job.id != job.id, Job.status == "completed",
                Job.started_at.isnot(None), Job.started_at < job.started_at)
        .order_by(Job.started_at.desc())
    )
    mias = {_norm(u) for u in (job.seeds or [])}
    from shared.modo_lista import es_lista

    yo_lista = es_lista(job.config)
    mas_reciente = None
    for c in consulta.yield_per(200):
        if not c.seeds or _host(c.seeds[0]) != host:
            continue
        # Una lista (decision 128) no es referencia de un rastreo que sigue
        # enlaces: la de QA suele llevar la home, asi que «abarca» a un censo
        # sembrado en la home y, siendo la mas reciente, ganaba.
        if es_lista(c.config) and not yo_lista:
            continue
        if not mismo_perfil(c):
            continue
        if mas_reciente is None:
            mas_reciente = c
        if mias and mias <= {_norm(u) for u in c.seeds}:
            return c
    return mas_reciente


REANALIZAR_LA_REFERENCIA = os.getenv("REANALIZAR_LA_REFERENCIA", "1") != "0"


def _poner_al_dia_el_anterior(db, anterior, job, reanalizar) -> tuple[bool, str | None]:
    """Re-analiza el censo de referencia si se analizó con otro código.

    Sin esto, la decisión 91 deja la comparación de incidencias **inservible en
    la práctica**: se despliega a diario, así que entre dos rastreos de una
    serie semanal casi siempre habrá cambiado el analizador, y entonces no se
    dan cifras. Visto en el primer rastreo automático de Lopesan, el
    2026-10-14: los dos censos salieron con `6ae6004` y `c5d863e` y el diff se
    calló. Callarse es mejor que mentir, pero no es una función que sirva.

    Volver a analizar el anterior es barato —246 s en ese censo— y lo deja
    comparable. Lo que NO es gratis es que **cambia sus cifras guardadas**: si
    alguien exportó un CSV de ese censo, ya no cuadrará. Por eso se registra en
    el log y viaja en el resultado como `anterior_reanalizado`, y por eso se
    puede apagar con `REANALIZAR_LA_REFERENCIA=0`.

    `reanalizar` es la función que analiza un job (`run_analysis`) y la pasa
    QUIEN LLAMA. Este módulo no importa `analysis/`: lo carga también la API,
    cuya imagen no lo lleva (decisiones 69 y 71). Sin ella no se re-analiza.

    Un censo con los enlaces **archivados** (decisión 95) se re-analiza
    igual: `run_analysis` los devuelve a `links`, analiza y los vuelve a
    archivar bajo el candado del job (decisión 150). Desde la 150 la
    referencia siempre está archivada, y restaurar cuesta una fracción del
    propio análisis.

    Devuelve `(se re-analizó, por qué no)`. El motivo solo va cuando hacía
    falta re-analizar y no se hizo: es lo que el diff de incidencias dirá en
    lugar del genérico «vuelve a analizar el más antiguo».
    """
    actual = getattr(job, "analisis_version", None)
    previa = getattr(anterior, "analisis_version", None)
    if not actual or previa == actual:
        return False, None
    if not REANALIZAR_LA_REFERENCIA:
        return False, ("el re-analisis automatico del censo anterior esta "
                       "apagado (REANALIZAR_LA_REFERENCIA=0).")
    if reanalizar is None:
        return False, None
    inicio = time.time()
    logger.info(
        "El censo de referencia %s se analizo con %s y este con %s: se vuelve "
        "a analizar para poder comparar las incidencias",
        anterior.id, previa or "(desconocida)", actual)
    try:
        reanalizar(str(anterior.id))
    except Exception:
        logger.exception(
            "No se pudo re-analizar %s; la comparacion de incidencias se "
            "quedara sin hacer, pero las alertas de pagina siguen", anterior.id)
        db.rollback()
        return False, "el re-analisis del censo anterior ha fallado (ver el log del worker)."
    # Que la llamada vuelva no quiere decir que haya analizado: si otro proceso
    # tiene el candado del job (otro analisis, o el archivado de la decision 95
    # en curso) `run_analysis` se retira sin hacer nada. Lo que manda es el
    # sello que deja `run_all` al terminar.
    db.expire(anterior)
    db.refresh(anterior)
    if anterior.analisis_version != actual:
        logger.warning("El censo de referencia %s no se ha re-analizado (sigue "
                       "con %s)", anterior.id, anterior.analisis_version)
        return False, ("el censo anterior no se ha podido re-analizar: otro "
                       "proceso lo estaba analizando o archivando.")
    logger.info("Censo de referencia %s re-analizado en %.0f s",
                anterior.id, time.time() - inicio)
    return True, None


def paginas_para_comparar(db, anterior, job) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Las paginas de los dos censos tal como se comparan: una lista (decision
    128) solo en sus URLs. Lo usan la comparacion y el trafico que se completa
    despues (decision 158), para no acotar en un sitio y en el otro no."""
    from shared.modo_lista import acotar_a_la_lista

    paginas_ant, _ = acotar_a_la_lista(paginas_de_censo(db, anterior.id), resumen_de_job(anterior), job)
    return paginas_ant, paginas_de_censo(db, job.id)


def comparar_con_el_anterior(db, job, reanalizar=None) -> dict[str, Any] | None:
    """Compara un rastreo recién terminado con el anterior del mismo sitio.

    Es lo que convierte la comparación en una alerta: nadie va a entrar a
    elegir dos censos en un desplegable para enterarse de que media sección se
    ha ido del índice. En Lopesan eso pasó y se entregó como un aviso `info`
    entre 315.119 incidencias.

    `reanalizar` (el `run_analysis` del analizador) lo pasa el worker para
    poner al dia el censo de referencia (decision 93); sin ella no se toca.
    """
    anterior = censo_anterior(db, job)
    if anterior is None:
        return None
    reanalizado, sin_reanalizar = _poner_al_dia_el_anterior(
        db, anterior, job, reanalizar)
    resumen_anterior = resumen_de_job(anterior)
    from shared.modo_lista import acotar_a_la_lista, umbral_absoluto

    # Una lista (decision 128) se compara SOLO en sus URLs: del anterior —que
    # puede ser un censo completo— lo que no esta en la lista no ha
    # «desaparecido», es que no se pidio.
    paginas_ant, resumen_ant_cmp = acotar_a_la_lista(
        paginas_de_censo(db, anterior.id), resumen_anterior, job)
    # Una sola lectura del censo nuevo: con los tipos de datos estructurados y
    # el hreflang (decision 131) ya no es una consulta barata para repetirla.
    paginas_nuevas = paginas_de_censo(db, job.id)
    # Las reglas del cliente (decision 135): apagar una regla o mover sus
    # umbrales. Sin cliente, las de serie.
    from shared.reglas import reglas_de_job, umbrales_de_comparacion

    try:
        reglas = reglas_de_job(db, job) or {}
        umbrales = umbrales_de_comparacion(reglas) or None
        ignorar = reglas.get("ignorar_en_textos") or None  # decision 230
    except Exception:
        # Unas reglas ilegibles no pueden llevarse por delante la comparacion
        # ni su alerta critica: se compara con lo de serie.
        logger.exception("Reglas del cliente ilegibles en el job %s; se usan las de serie",
                         job.id)
        umbrales = ignorar = None
    r = comparar_censos(
        paginas_ant,
        paginas_nuevas,
        job_a=resumen_ant_cmp,
        job_b=resumen_de_job(job),
        umbral_absoluto=umbral_absoluto(job.config),
        umbrales=umbrales,
        ignorar=ignorar,
    )
    incidencias = None
    if r.get("comparable"):
        # El diff de incidencias va aparte y NO puede tumbar el de paginas: las
        # alertas criticas —media seccion fuera del indice— son lo que hay que
        # entregar aunque el recuento de "que se arreglo" falle. Antes de esto,
        # cualquier problema con `issues` habria dejado `comparacion` a NULL
        # por el best-effort del worker, y con ella las alertas.
        try:
            # «Resuelta» solo se puede afirmar si el censo ANTERIOR esta
            # entero: si paro por `max_urls`, que un hallazgo no aparezca ahora
            # puede ser que no se llegara a su pagina.
            anterior_entero = not _truncado(
                resumen_anterior.get("status"),
                resumen_anterior.get("finish_reason"))
            from shared.accesibilidad import plantillas_evaluadas

            incidencias = comparar_incidencias(
                incidencias_de_censo(db, anterior.id),
                incidencias_de_censo(db, job.id),
                puede_afirmar_resueltas=anterior_entero,
                # Una pagina que ahora es un muro no se ha visto: sus
                # incidencias de antes «no se sabe», no «resueltas» (103).
                urls_del_nuevo={_norm(p["url"]) for p in paginas_nuevas
                                if p.get("response_class") not in NO_VALIDAS},
                # Nueva en una URL que ya estaba (regresion) o en una URL
                # nueva (publicada mal), decision 131.
                urls_del_anterior={_norm(p["url"]) for p in paginas_ant
                                   if p.get("response_class") not in NO_VALIDAS},
                analisis_a=resumen_anterior.get("analisis_version"),
                analisis_b=getattr(job, "analisis_version", None),
                # Los avisos de axe solo se afirman donde los dos censos
                # evaluaron la plantilla (decision 174).
                plantillas_axe_a=plantillas_evaluadas(db, anterior.id),
                plantillas_axe_b=plantillas_evaluadas(db, job.id),
            )
        except Exception:
            logger.exception(
                "No se pudo comparar las incidencias de %s con %s; las alertas "
                "de pagina siguen", job.id, anterior.id)
        # Si hacia falta poner al dia la referencia y no se pudo, el motivo
        # concreto sustituye al consejo generico de la 91: con los enlaces
        # archivados, «vuelve a analizar el mas antiguo» fallaria tal cual.
        if (sin_reanalizar and incidencias is not None
                and incidencias.get("comparable") is False):
            incidencias["motivo"] = f"{incidencias['motivo']} {sin_reanalizar}"
    # El trafico de Google entre los dos censos, agrupado por lo que cambio en
    # esas paginas (decision 158). Aparte y con su try, como las incidencias:
    # no puede llevarse por delante las alertas de pagina.
    trafico = None
    if r.get("comparable"):
        try:
            from shared.trafico_entre_censos import comparar_trafico

            # En un savepoint: un error SQL dejaria la transaccion abortada y el
            # commit de la comparacion —con sus alertas criticas— fallaria.
            with db.begin_nested():
                trafico = comparar_trafico(db, anterior, job, paginas_ant, paginas_nuevas,
                                           concluyente=r.get("concluyente") is not False,
                                           motivo_no_concluyente=r.get("motivo"))
        except Exception:
            logger.exception("No se pudo comparar el trafico de %s con %s", job.id, anterior.id)
    # Lo que se guarda es el veredicto, no el censo entero: los ejemplos y las
    # plantillas ya van dentro de cada alerta.
    return {
        "incidencias": incidencias,
        # Si el censo anterior se volvio a analizar para poder comparar, se
        # dice: sus cifras han cambiado respecto a lo que se viera antes, y
        # quien mire un informe viejo de ese censo tiene derecho a saberlo.
        "anterior_reanalizado": reanalizado,
        "anterior_sin_reanalizar": sin_reanalizar,
        "comparado_con": str(anterior.id),
        # Con que version del analisis estaban los dos censos al compararse
        # (decision 191). Si uno de los dos se vuelve a analizar despues (el
        # siguiente censo de la serie re-analiza a este como referencia, 93),
        # sus incidencias ya no son las que se compararon y la diferencia por
        # tipo que ensena Problemas no se puede dar como del sitio.
        "analisis_version": getattr(job, "analisis_version", None),
        "analisis_version_anterior": getattr(anterior, "analisis_version", None),
        "nombre_anterior": anterior.name,
        "fecha_anterior": resumen_de_job(anterior)["fecha"],
        "comparable": r.get("comparable", False),
        "motivo": r.get("motivo"),
        "concluyente": r.get("concluyente"),
        "bloqueado": r.get("bloqueado"),
        "avisos": r.get("avisos", []),
        "urls": r.get("urls"),
        "alertas": r.get("alertas", []),
        # Lo que cambio en la extraccion a medida, regla a regla (decision 127).
        "extraido": r.get("extraido"),
        "trafico": trafico,
    }
