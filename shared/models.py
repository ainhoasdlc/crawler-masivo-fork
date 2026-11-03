import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, Float, Text, DateTime, Date,
    ForeignKey, Index, JSON, UniqueConstraint, text as sql_text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from shared.database import Base


def _utcnow():
    return datetime.now(timezone.utc)


def _uuid():
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Clientes y perfiles de rastreo (#36, F1)
# ---------------------------------------------------------------------------
class Client(Base):
    """El cliente como entidad, en vez de un texto libre en cada job.

    Antes `jobs.client_id` era lo que se escribiera en el modal: una errata
    creaba otro cliente y no habia donde guardar nada que fuera DEL cliente y
    no de un rastreo concreto (sus dominios, su configuracion por defecto, sus
    integraciones con GSC o DataForSEO).

    `config_defecto` es un dict PARCIAL de `JobConfig`: solo lo que el cliente
    fija. Guardar el `JobConfig` entero rellenaria todos los valores por
    defecto y, al heredar, pisaria lo que el perfil o el job quisieran cambiar.

    `integraciones` no guarda NINGUN secreto (decision 83): la API no tiene
    autenticacion, asi que lo que se guarda aqui lo puede leer cualquiera que
    llegue al puerto. Se guarda el tipo, los parametros publicos y el NOMBRE de
    la variable de entorno que tiene la clave.
    """

    __tablename__ = "clients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    nombre = Column(String(256), nullable=False)
    # Lo que casa dos instalaciones (backup/importacion) y lo que se escribia
    # antes como `client_id`. Unico: dos clientes con el mismo slug son una
    # errata, no dos clientes.
    slug = Column(String(128), nullable=False, unique=True, index=True)
    dominios = Column(JSON, nullable=False, default=list)
    zona_horaria = Column(String(64), nullable=True, default="Europe/Madrid")
    config_defecto = Column(JSON, nullable=False, default=dict)
    integraciones = Column(JSON, nullable=False, default=list)
    # Capa de decisiones (#7): `{"presupuesto_mensual_usd": 5.0}`. NULL o sin
    # la clave = sin tope propio del cliente (sigue mandando el global,
    # `ENRICHMENT_MAX_USD_MES`). Es un presupuesto, no un secreto: la clave de
    # OpenRouter va en el entorno (decision 84).
    decisiones = Column(JSON, nullable=True)
    notas = Column(Text, nullable=True)
    # Vistas guardadas del Explorador (#131): `[{id, nombre, consulta, creada}]`.
    # `consulta` es la parte de despues del «?» de `#/rastreos/<id>/explorador`,
    # asi que una vista vale para cualquier censo del cliente: es como se repite
    # el mismo analisis cada mes.
    vistas_explorador = Column(JSON, nullable=True)
    # Reglas de alerta del cliente (decision 135, `shared/reglas.py`): PARCIAL
    # sobre las de serie. NULL = las de serie, que son el comportamiento de
    # antes: no configurar nada no cambia lo que se avisa.
    reglas_alerta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    perfiles = relationship(
        "CrawlProfile", back_populates="cliente",
        cascade="all, delete-orphan", passive_deletes=True,
    )


class CrawlProfile(Base):
    """Un rastreo de un cliente: el sitio principal, el blog, un competidor.

    En F1 es «que semillas y que configuracion»: lanzar un job desde un perfil
    hereda cliente -> perfil -> lo que se cambie en el modal, y lo resuelto se
    copia en `jobs.config`. El modo incremental (decision 220) va en su
    `config.incremental`, y su estado por URL en `url_state`.
    """

    __tablename__ = "crawl_profiles"
    __table_args__ = (
        UniqueConstraint("cliente_id", "nombre", name="uq_profile_cliente_nombre"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    # `cliente_id` y no `client_id`: en este esquema `client_id` es el texto
    # libre de siempre (jobs, programaciones) y `cliente_id` la FK de verdad.
    # Llamar igual a las dos cosas es como se acaba filtrando por la que no es.
    cliente_id = Column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    nombre = Column(String(256), nullable=False)
    # propio | competidor. Un competidor no abrira incidentes en F2: sus
    # cambios son informacion, no problemas.
    rol = Column(String(16), nullable=False, default="propio")
    seeds = Column(JSON, nullable=False, default=list)
    config = Column(JSON, nullable=False, default=dict)
    notas = Column(Text, nullable=True)
    activo = Column(Boolean, nullable=False, default=True)
    # `use_alter`: jobs.profile_id apunta aqui y esto apunta a jobs. Sin el,
    # create_all no sabe en que orden crear las dos tablas.
    last_job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL", use_alter=True,
                   name="fk_profiles_last_job"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    cliente = relationship("Client", back_populates="perfiles")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
class ResumenSemanal(Base):
    """El resumen de la semana de un cliente (decision 135).

    Lo escribe el worker el dia y la hora que diga `reglas_alerta.resumen_semanal`
    (de serie, lunes a las 8:00 en la zona del cliente), y se lee en su panel.
    Una fila por (cliente, semana) con restriccion unica: con dos replicas del
    worker, la segunda que llega choca y no manda otro aviso.
    """

    __tablename__ = "resumenes_semanales"
    __table_args__ = (
        UniqueConstraint("cliente_id", "semana", name="uq_resumen_cliente_semana"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    cliente_id = Column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # El dia en que se cierra la semana (el del envio), en la zona del cliente.
    semana = Column(Date, nullable=False)
    desde = Column(DateTime(timezone=True), nullable=False)
    hasta = Column(DateTime(timezone=True), nullable=False)
    contenido = Column(JSON, nullable=False)
    texto = Column(Text, nullable=False)
    enviado = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class Incidente(Base):
    """Una alerta con estado (Ola 5.1, decision 139).

    Sin estado, el mismo fallo avisaba cada semana mientras durase, y un aviso
    que llega cada lunes con lo mismo se deja de leer (decision 77). Un
    incidente es (serie, clave): la serie es el perfil o la programacion que
    repite el rastreo, la clave la regla que salto. Lo abre el primer rastreo
    de la serie que la dispara, lo mantienen los siguientes y lo CIERRA solo el
    primero que, pudiendo afirmarlo, ya no la ve. Solo el rastreo mas reciente
    de la serie abre o cierra: re-analizar uno viejo no toca nada.

    `visto` lo pone una persona y no cierra nada: dice que alguien lo esta
    mirando. Un unico incidente vivo por (serie, clave), con indice unico
    parcial: con dos replicas del worker, la segunda choca.
    """

    __tablename__ = "incidentes"
    __table_args__ = (
        Index("uq_incidente_vivo", "serie", "clave", unique=True,
              postgresql_where=sql_text("estado <> 'cerrado'"),
              sqlite_where=sql_text("estado <> 'cerrado'")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    cliente_id = Column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    # «perfil:<uuid>» o «programacion:<uuid>»: lo que se repite.
    serie = Column(String(128), nullable=False, index=True)
    nombre_serie = Column(String(512), nullable=True)
    # La regla, y en las de un campo extraido tambien su nombre.
    clave = Column(String(256), nullable=False)
    regla = Column(String(128), nullable=False)
    severidad = Column(String(16), nullable=False)
    titulo = Column(Text, nullable=False)
    estado = Column(String(16), nullable=False, default="abierto")  # abierto | visto | cerrado
    # La alerta tal como la vio el ultimo rastreo que la disparo.
    detalle = Column(JSON, nullable=True)
    veces = Column(Integer, nullable=False, default=1)
    abierto_job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    ultimo_job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    cerrado_job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    abierto_en = Column(DateTime(timezone=True), default=_utcnow)
    visto_en = Column(DateTime(timezone=True), nullable=True)
    cerrado_en = Column(DateTime(timezone=True), nullable=True)
    # Por que se cerro sin un rastreo que lo comprobara (decision 188):
    # «serie_pausada» o «serie_borrada». NULL = lo cerro `cerrado_job_id`.
    motivo_cierre = Column(String(32), nullable=True)
    actualizado_en = Column(DateTime(timezone=True), default=_utcnow)
    # Sin aviso hasta ese dia (incluido); el incidente se sigue llevando.
    silenciado_hasta = Column(Date, nullable=True)


class GscPagina(Base):
    """Search Console por URL y dia, de un cliente (decision 141, Ola 4.1).

    Por cliente y dia, NO por job (`docs/INVESTIGACION_SEARCH_CONSOLE.md`): es
    una serie del sitio, que se cruza con un censo por ventana de fechas al
    analizarlo. Se guardan TODAS las URLs que da Google, tambien las que el
    rastreo no encontro: son de las mas interesantes (huerfanas, fuera del
    alcance). `url_clave` es `shared.indexabilidad.clave_url` en SHA-256, la
    misma regla con la que se empareja con `urls` (decision 39).
    """

    __tablename__ = "gsc_paginas"
    __table_args__ = (
        UniqueConstraint("cliente_id", "propiedad", "fecha", "url_clave", name="uq_gsc_pagina_dia"),
        Index("ix_gsc_paginas_cliente_clave", "cliente_id", "url_clave"),
        Index("ix_gsc_paginas_cliente_fecha", "cliente_id", "fecha"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    propiedad = Column(String(512), nullable=False)
    fecha = Column(Date, nullable=False)
    url = Column(Text, nullable=False)
    url_clave = Column(String(64), nullable=False)
    clics = Column(Integer, nullable=False, default=0)
    impresiones = Column(Integer, nullable=False, default=0)
    # Posicion media ponderada por impresiones, la que da Google.
    posicion = Column(Float, nullable=True)


class GscEstado(Base):
    """Como va la sincronizacion de Search Console de un cliente (decision 141).

    Una fila por (cliente, propiedad). Lo que la interfaz ensena: con que
    cuenta, que dias hay, cuando fue bien la ultima vez y, si fallo, por que en
    castellano («la cuenta X no tiene acceso a la propiedad Y»). `pedida_en`
    lo pone el boton «Sincronizar ahora».
    """

    __tablename__ = "gsc_estado"
    __table_args__ = (
        UniqueConstraint("cliente_id", "propiedad", name="uq_gsc_estado"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    propiedad = Column(String(512), nullable=False)
    cuenta = Column(String(512), nullable=True)
    estado = Column(String(16), nullable=False, default="pendiente")  # pendiente | en_curso | ok | error
    motivo = Column(Text, nullable=True)
    ultimo_intento = Column(DateTime(timezone=True), nullable=True)
    ultimo_ok = Column(DateTime(timezone=True), nullable=True)
    pedida_en = Column(DateTime(timezone=True), nullable=True)
    primer_dia = Column(Date, nullable=True)
    ultimo_dia = Column(Date, nullable=True)
    filas = Column(BigInteger, nullable=True)
    # Dias en los que Google corto en el tope de filas (50.000/dia): ahi no se
    # puede afirmar que una URL no tuvo impresiones.
    dias_truncados = Column(JSON, nullable=True)
    # Inspeccion de URLs (decision 144): la ultima tanda del dia.
    inspeccion_ultima = Column(DateTime(timezone=True), nullable=True)
    inspeccion_hechas = Column(Integer, nullable=True)
    inspeccion_motivo = Column(Text, nullable=True)
    # Busquedas y sitemaps (decision 157): su propia serie, con su primer y
    # ultimo dia y sus dias truncados, porque se rellena hacia atras aparte de
    # la de paginas. {"consultas": {...}, "sitemaps": n, "ultimo": iso,
    # "motivo": texto}.
    detalle = Column(JSON, nullable=True)


class GscConsulta(Base):
    """Search Console por URL, busqueda y dia, de un cliente (decision 157).

    Lo que piden la canibalizacion por busqueda y las oportunidades: que
    busquedas trae cada pagina y cuantas URLs del sitio comparten una. Sin la
    URL en texto (esta en `gsc_paginas` con la misma `url_clave`) ni indice
    unico: un dia se reescribe entero, y son ~29.000 filas al dia en Lopesan.
    Las busquedas anonimizadas no las da Google: la suma por busqueda nunca
    cuadra con el total de la pagina.
    """

    __tablename__ = "gsc_consultas"
    __table_args__ = (
        Index("ix_gsc_consultas_cliente_fecha", "cliente_id", "fecha"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    propiedad = Column(String(512), nullable=False)
    fecha = Column(Date, nullable=False)
    url_clave = Column(String(64), nullable=False)
    consulta = Column(Text, nullable=False)
    clics = Column(Integer, nullable=False, default=0)
    impresiones = Column(Integer, nullable=False, default=0)
    posicion = Column(Float, nullable=True)


class GscSitemap(Base):
    """Un sitemap segun Google (Sitemaps API, decision 157): cuando se envio,
    cuando lo descargo Google y si tiene errores. `contents[].indexed` esta
    obsoleto desde 2019 y no se guarda."""

    __tablename__ = "gsc_sitemaps"
    __table_args__ = (
        UniqueConstraint("cliente_id", "propiedad", "path", name="uq_gsc_sitemap"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    propiedad = Column(String(512), nullable=False)
    path = Column(Text, nullable=False)
    enviado = Column(DateTime(timezone=True), nullable=True)       # lastSubmitted
    descargado = Column(DateTime(timezone=True), nullable=True)    # lastDownloaded
    pendiente = Column(Boolean, nullable=True)                     # isPending
    es_indice = Column(Boolean, nullable=True)                     # isSitemapsIndex
    avisos = Column(Integer, nullable=True)                        # warnings
    errores = Column(Integer, nullable=True)                       # errors
    enviadas = Column(JSON, nullable=True)                         # [{type, submitted}]
    visto_en = Column(DateTime(timezone=True), nullable=False)


class GscInspeccion(Base):
    """Lo que Google dice de una URL concreta (URL Inspection API, decision 144).

    Una fila por (cliente, propiedad, URL): la ultima inspeccion. Google da
    2.000 al dia por propiedad, asi que es una MUESTRA rotatoria, no un censo:
    primero las URLs con trafico en riesgo, despues las que mas impresiones
    tienen y las que no tienen ninguna, y las demas por antiguedad. Lo que
    importa: si Google la tiene indexada (`verdict`, `cobertura` en castellano)
    y que canonical ha elegido Google frente al que declara la pagina.
    """

    __tablename__ = "gsc_inspecciones"
    __table_args__ = (
        UniqueConstraint("cliente_id", "propiedad", "url_clave", name="uq_gsc_inspeccion"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    propiedad = Column(String(512), nullable=False)
    url = Column(Text, nullable=False)
    url_clave = Column(String(64), nullable=False)
    fecha = Column(DateTime(timezone=True), nullable=False)
    verdict = Column(String(24), nullable=True)            # PASS | NEUTRAL | FAIL | PARTIAL
    cobertura = Column(Text, nullable=True)                # coverageState, en castellano
    indexacion = Column(String(64), nullable=True)         # indexingState
    robots = Column(String(32), nullable=True)             # robotsTxtState
    descarga = Column(String(48), nullable=True)           # pageFetchState
    canonical_google = Column(Text, nullable=True)
    canonical_usuario = Column(Text, nullable=True)
    ultimo_rastreo = Column(DateTime(timezone=True), nullable=True)
    rastreada_como = Column(String(16), nullable=True)
    error = Column(Text, nullable=True)


class EnlaceCliente(Base):
    """Un enlace de solo lectura para un cliente (decision 143, Ola 6.1).

    `/c/<token>` ensena el informe de sus censos y nada mas, sin la sesion de
    la agencia. Se guarda el SHA-256 del token, nunca el token: se ensena una
    vez al crearlo, y quien lea la base de datos (o un backup) no puede entrar.
    Se revoca y puede caducar.
    """

    __tablename__ = "enlaces_cliente"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    # Los primeros caracteres, para reconocerlo en la lista sin ensenarlo.
    prefijo = Column(String(8), nullable=False)
    nombre = Column(String(256), nullable=True)
    creado_en = Column(DateTime(timezone=True), default=_utcnow)
    caduca_en = Column(DateTime(timezone=True), nullable=True)
    revocado_en = Column(DateTime(timezone=True), nullable=True)
    ultimo_uso = Column(DateTime(timezone=True), nullable=True)
    usos = Column(Integer, nullable=False, default=0)


class Programacion(Base):
    """Un rastreo que se repite: cuando toca y que lanzar.

    Dos formas (decision 193, revision de UX del 25-oct, 2.2):

    - **Colgada de un perfil** (`hereda_perfil`): en cada disparo hereda lo
      del MOMENTO, cliente -> perfil -> lo propio de la programacion. Las
      semillas son las del perfil (`seeds` queda vacia) y `config` guarda solo
      lo propio (p. ej. un tope de URLs), no una copia. Cambiar el perfil o el
      cliente llega al siguiente censo.
    - **Copia fija** (las de antes): lleva sus propias `seeds` y `config`
      completas, copiadas del rastreo del que se creo. Siguen funcionando
      igual hasta que `scripts/migrar_programaciones_a_perfiles.py` las cuelga
      de un perfil. No apuntan a `projects/<cliente>/config.json`: esos
      ficheros viven en la maquina de quien lanza y el worker no los tiene.
    """

    __tablename__ = "programaciones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    nombre = Column(String(512), nullable=False)
    client_id = Column(String(128), nullable=True, index=True)
    # El cliente y el perfil, si se conocen. La programacion sigue llevando
    # sus propias `seeds` y `config` (autosuficiente, ver arriba): esto solo
    # dice de quien es, para que los jobs que dispare salgan colgados de el.
    cliente_id = Column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    profile_id = Column(
        UUID(as_uuid=True), ForeignKey("crawl_profiles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    seeds = Column(JSON, nullable=False)
    config = Column(JSON, nullable=True)
    # Si hereda del perfil en cada disparo (decision 193). Falso en las de
    # copia fija: asi las viejas no cambian de comportamiento sin migrarlas.
    hereda_perfil = Column(Boolean, nullable=False, default=False,
                           server_default=sql_text("false"))

    # Expresion de cinco campos (`m h dom mes dsem`) y la zona en la que se
    # lee: un "todos los lunes a las 3:00" sin zona se desplaza una hora en
    # verano y nadie lo nota hasta que falta un censo.
    cron = Column(String(128), nullable=False)
    zona_horaria = Column(String(64), nullable=True)
    activa = Column(Boolean, default=True, nullable=False)

    # En UTC. Se recalcula cada vez que se dispara, y tambien al activar o
    # editar: si se quedara con la de antes, un cambio de horario no tendria
    # efecto hasta el siguiente disparo.
    proxima_ejecucion = Column(DateTime(timezone=True), nullable=True, index=True)
    ultima_ejecucion = Column(DateTime(timezone=True), nullable=True)
    ultimo_job_id = Column(UUID(as_uuid=True), nullable=True)
    # Por que no se disparo la ultima vez que tocaba, si no se disparo. Una
    # programacion que deja de lanzarse sin decir por que es indistinguible de
    # una que nadie miro.
    ultimo_motivo = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name = Column(String(512), nullable=False)
    # El texto libre de siempre. Se conserva como etiqueta: los scripts lo
    # siguen enviando (`lanzar_job.py`) y los jobs viejos lo tienen como unica
    # pista de su cliente. Lo que manda es `cliente_id`.
    client_id = Column(String(128), nullable=True, index=True)
    # FK de verdad a `clients` (#36). NULL = job sin cliente. Borrar el
    # cliente deja el job sin cliente, no lo borra: es un censo entregado.
    cliente_id = Column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # De que perfil salio, si salio de uno. NULL = rastreo puntual.
    profile_id = Column(
        UUID(as_uuid=True), ForeignKey("crawl_profiles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    owner_id = Column(String(128), nullable=True)
    # Que programacion lo lanzo, si lo lanzo alguna. Es lo que permite
    # compararlo con el anterior de SU serie en vez de con lo ultimo que
    # pasara por ese host (decision 78).
    programacion_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # censo | canario | prueba. NULL = no se ha dicho: se deduce del nombre
    # (`shared.clientes.tipo_de_rastreo`). Separa en la interfaz los censos
    # que se entregan de las pruebas de 26 URLs (UX-07).
    tipo = Column(String(16), nullable=True)

    # pending | running | analyzing | completed | failed | cancelled | stalled
    # | deleting (un borrado por trozos en curso o a medias, decision 96)
    status = Column(String(20), nullable=False, default="pending", index=True)

    # Por que termino el rastreo: "finished" (frontera agotada, dato completo)
    # o "max_urls_reached" (cortado por el tope, dato PARCIAL). Sin esto, un
    # crawl truncado quedaba como "completed" igual que uno terminado, y no
    # habia forma de saber que el grafo de enlaces —y por tanto el PageRank—
    # se calculo sobre una parte del sitio.
    finish_reason = Column(String(32), nullable=True)
    # Con que version del codigo se hizo este rastreo. Sin esto, comparar dos
    # censos del mismo sitio no puede distinguir "lo cambio el sitio" de "lo
    # cambiamos nosotros" (decision 66).
    crawler_version = Column(String(64), nullable=True)

    # Resultado de la comprobacion automatica de render JS por plantilla. Se
    # rellena al cerrar un rastreo SIN render_js: dice si alguna plantilla
    # esconde enlaces (el grafo y el PageRank no serian fiables) y cuanto
    # contenido carga en cliente. NULL = no se llego a comprobar.
    js_check = Column(JSON, nullable=True)
    # Que cambio respecto al censo anterior del mismo sitio, calculado al
    # cerrar el rastreo. Es la alerta que nadie tiene que ir a buscar.
    comparacion = Column(JSON, nullable=True)
    # Las reglas propias del cliente evaluadas al cerrar el rastreo (decision
    # 135): `{evaluadas, disparadas, sin_evaluar, motivo, comparado_con}`.
    alertas_cliente = Column(JSON, nullable=True)
    # Search Console en la ventana del rastreo (decision 142): totales, cuanto
    # cae en el censo y las URLs con clics que el rastreo no encontro.
    gsc_resumen = Column(JSON, nullable=True)
    # Con que version se ANALIZO, que no es lo mismo que con cual se rastreo:
    # un re-analisis cambia las cifras sin que cambie el sitio (decision 66).
    analisis_version = Column(String(64), nullable=True)

    # Resumen del PageRank (ver analysis/pagerank.py): que fraccion acaba en
    # cada tipo de URL (indexable, redireccion, error...) y cuanta se
    # desperdicia en errores. NULL = analisis anterior a este modelo.
    pagerank_resumen = Column(JSON, nullable=True)
    # Lo que Googlebot visito segun los logs del cliente (decision 213): de
    # que importacion, el periodo, cobertura y reparto. NULL sin logs.
    logs_resumen = Column(JSON, nullable=True)
    # Salud del rastreo (decision 103): respuestas por clase de
    # `urls.response_class`, cuantas no eran la pagina y la causa si el rastreo
    # se paro o se dio por bloqueado. NULL = rastreo anterior a la columna.
    health = Column(JSON, nullable=True)
    # Observabilidad de la capa de decisiones (#7): llamadas, tokens, coste
    # real, aciertos de cache, 429, latencia y distribucion de respuestas.
    # NULL = nunca se le pregunto nada a un modelo sobre este job, que con
    # este PR es lo normal: nada se dispara solo (decision 84).
    decisiones_resumen = Column(JSON, nullable=True)
    # Enlaces archivados en Parquet (decision 95): filas, apariciones,
    # internos, nofollow internos, fichero, bytes y fecha. NULL = los enlaces
    # estan en `links`. Con valor, `links` no tiene filas de este job.
    enlaces_archivados = Column(JSON, nullable=True)
    # Segundos por fase del ultimo analisis: {"fases": [[nombre, s], ...],
    # "total": s} (#281, decision 226). Para saber donde se va el tiempo.
    analisis_fases = Column(JSON, nullable=True)
    # Ritmo del ultimo tramo del rastreo y su techo (pausa o servidor):
    # `shared/ritmo.resumen` (#275, decision 227).
    ritmo = Column(JSON, nullable=True)
    # Soft 404 (decision 105): `sondas` las escribe el spider (lo que responde
    # el sitio a una URL que no existe, por host y por plantilla) y `resumen`
    # el analisis. NULL = rastreo anterior a las sondas o con ellas apagadas.
    # Las sondas NO son URLs del censo: no estan en `urls` ni cuentan en nada.
    soft404 = Column(JSON, nullable=True)
    # Certificado TLS por host (decision 110): `{"hosts": {host: {...}}}`
    # con la caducidad, los dias que le quedaban EL DIA DEL RASTREO, la
    # version negociada y si la verificacion fallo y por que. Lo escribe la
    # sonda del spider, una vez por host https interno; no son URLs del censo.
    tls = Column(JSON, nullable=True)
    # Con que reglas y cuando se materializo `urls.segmento`, y cuantas URLs
    # casaron con cada regla o no se pudieron juzgar (decision 125).
    segmentacion = Column(JSON, nullable=True)
    # Sondas de respuesta (decisiones 123 y 124), lo escribe el analisis:
    # cuantos destinos externos y recursos distintos habia, cuantos se
    # comprobaron, rotos y dominios muertos. NULL = analisis anterior o sin
    # sondas. Con «comprobados < distintos» que no haya aviso no dice nada.
    sondas_resumen = Column(JSON, nullable=True)
    # Los ficheros de sitemap que se leyeron (decision 126), lo escribe el
    # spider al cerrar: `{"ficheros": [{url, formato, declaradas, devueltas,
    # bytes, cortado, hijos, entradas_guardadas, leido_at}], "pedidos",
    # "leidos", "parcial", "tope_entradas", "entradas_guardadas",
    # "entradas_recortadas"}`. NULL = rastreo anterior o sin sitemap. Las
    # entradas, una por (fichero, URL), van a `sitemap_entries`.
    sitemaps = Column(JSON, nullable=True)
    # Lo que leyeron los adaptadores de CMS (decision 161), lo escribe el
    # spider: `{"wordpress": {detectado, rest, raiz, plugin_seo, namespaces,
    # totales por tipo, peticiones, cortada, sondas...}}`. NULL = rastreo
    # anterior o adaptador apagado. Las entidades van a `adapter_entities`.
    adapters = Column(JSON, nullable=True)
    # Topes por subdominio o carpeta (decision 172), lo escribe el spider al
    # cerrar: `{"reglas": [{regla, tope, grupos, grupos_cortados, rastreadas,
    # sin_rastrear, lista_completa}], "cortados": [{regla, grupo, tope,
    # rastreadas, sin_rastrear}], "sin_rastrear", "recuento_aproximado"}`.
    # NULL = el job no tenia topes. Con `sin_rastrear` > 0 el censo esta
    # truncado en esos grupos: el analisis no afirma ausencias ahi.
    topes_carpeta = Column(JSON, nullable=True)
    # Rastreo incremental (#36 F4, decision 220), lo escribe
    # `shared/incremental.py`: `{modo: completo|incremental, motivo, ciclo,
    # ciclos_desde_completo, prev_job_id, seleccion, arrastre, estado,
    # forzar_completo}`. NULL = el job no es de un perfil con
    # `incremental.activo`, que es rastrear todo como siempre. En un
    # incremental, lo que no se pidio se copia del censo `prev_job_id` antes
    # del analisis (`analysis/arrastre.py`): el job sigue siendo una foto
    # completa, y `urls.fetch_mode` dice de cada fila si se pidio o no.
    incremental = Column(JSON(none_as_null=True), nullable=True)

    seeds = Column(JSON, nullable=False)  # list of seed URLs
    config = Column(JSON, nullable=False, default=dict)

    total_urls_discovered = Column(Integer, default=0)
    total_urls_crawled = Column(Integer, default=0)
    total_urls_failed = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    urls = relationship("Url", back_populates="job", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
class Url(Base):
    __tablename__ = "urls"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    url = Column(Text, nullable=False)
    url_hash = Column(String(64), nullable=False)  # sha256 for dedup
    host = Column(String(512))
    path = Column(Text)
    scheme = Column(String(10))

    is_internal = Column(Boolean, default=True)
    crawl_depth = Column(Integer, nullable=True)
    # Clics desde la home (raiz del host y portadas de idioma), calculada por
    # el analisis. NULL = sin camino desde la home. crawl_depth es otra cosa:
    # saltos del rastreador desde las semillas, la que aplica max_depth.
    click_depth = Column(Integer, nullable=True)
    # Search Console en los 90 dias que acaban el dia del rastreo (decision
    # 142). NULL = sin datos del cliente o ventana sin cubrir; 0 = medido.
    gsc_clics = Column(Integer, nullable=True)
    gsc_impresiones = Column(Integer, nullable=True)
    gsc_posicion = Column(Float, nullable=True)

    content_type = Column(String(256))
    content_length = Column(BigInteger, nullable=True)
    status_code = Column(Integer, nullable=True)
    status_group = Column(String(10))  # 2xx, 3xx, 4xx, 5xx, timeout, dns_error
    response_time_ms = Column(Float, nullable=True)
    # Tiempo del servidor hasta el primer byte, en ms (decision 109): sin
    # DNS, TCP ni TLS. `response_time_ms` NO es esto: es la peticion entera
    # (y con render, la espera del navegador). Sin render lo mide curl
    # (STARTTRANSFER - PRETRANSFER); con render, Navigation Timing
    # (responseStart - requestStart). NULL en los censos anteriores, en las
    # paginas sin respuesta y cuando no se pudo medir.
    ttfb_ms = Column(Float, nullable=True)
    # `Content-Encoding` que sirvio el servidor (decision 109): gzip, br,
    # zstd, deflate... Los handlers lo quitan al descomprimir, asi que antes
    # se perdia. `identity` = se midio y llego sin comprimir; NULL = no se
    # sabe (censo anterior, error, o con render sin el dato).
    content_encoding = Column(String(32), nullable=True)

    is_html = Column(Boolean, default=False)
    resource_type = Column(String(20))  # html, image, css, js, pdf, other

    redirect_url = Column(Text, nullable=True)

    indexable = Column(Boolean, nullable=True)
    # Directiva `noindex` de la propia pagina (meta robots o X-Robots-Tag),
    # separada de `indexable` —que tambien es False por canonical o por codigo—
    # porque de esto depende si sus enlaces cuentan como entrantes (C3 de #24).
    noindex = Column(Boolean, nullable=True)
    body_hash = Column(String(64), nullable=True)  # for duplicate content detection

    first_seen_at = Column(DateTime(timezone=True), default=_utcnow)
    last_crawled_at = Column(DateTime(timezone=True), default=_utcnow)

    # --- Screaming Frog extended fields ---
    url_length = Column(Integer)                             # character count of URL
    folder_depth = Column(Integer)                           # number of path segments
    word_count = Column(Integer, nullable=True)              # words in body text
    # Palabras del contenido principal (sin menu ni pie). Es la cifra con la
    # que se juzga el thin content: word_count incluye la plantilla.
    content_word_count = Column(Integer, nullable=True)
    # SHA-256 del contenido principal normalizado. `body_hash` es el de los
    # bytes: con un token CSRF o un nonce dentro, dos paginas identicas nunca
    # coincidian y los duplicados exactos no se detectaban en ningun CMS.
    content_hash = Column(String(64), nullable=True, index=True)
    # Bytes del HTML DESCOMPRIMIDO tal como lo sirvio el servidor, antes del
    # render: lo que mide el limite de 2 MB de Googlebot (decision 102). Sin
    # render es `content_length`; con render, `content_length` es el DOM ya
    # montado y esto sale de Navigation Timing (`decodedBodySize`). NULL en
    # los censos anteriores y cuando el navegador no lo da.
    html_bytes_servidos = Column(Integer, nullable=True)
    text_ratio = Column(Float, nullable=True)                # text/HTML ratio percentage
    redirect_type = Column(Integer, nullable=True)           # HTTP redirect code (301, 302, 307, 308)
    status_text = Column(String(64), nullable=True)          # "OK", "Not Found", "Moved Permanently"
    last_modified = Column(String(128), nullable=True)       # Last-Modified header
    # `ETag` de la respuesta, para pedirla condicional en el siguiente rastreo
    # incremental (decision 220). NULL = no la mando o censo anterior.
    etag = Column(String(256), nullable=True)
    # Como llego la fila a un job incremental (decision 220): `fetched` (se
    # pidio y respondio), `not_modified` (304: el servidor dijo que no habia
    # cambiado y el arrastre la completo con el censo anterior) o `carried`
    # (no tocaba pedirla: copiada del censo anterior, con su
    # `last_crawled_at`). NULL = rastreo completo, como todos los de antes.
    fetch_mode = Column(String(16), nullable=True)
    http_version = Column(String(16), nullable=True)         # "HTTP/1.1", "HTTP/2"
    # Bytes que viajan por el cable (comprimidos): es el peso que cuenta para el
    # presupuesto de rastreo y para las Core Web Vitals. `content_length` es el
    # recurso ya descomprimido. Estaban cambiados: en un sitio con gzip,
    # content_length daba el tamano comprimido (dividido por 4 o 5).
    transfer_size = Column(BigInteger, nullable=True)
    indexability_status = Column(String(64), nullable=True)  # reason: "Canonicalised", "Noindex", etc.
    blocked_by_robots = Column(Boolean, nullable=True)       # only set in robots_mode="audit"
    # Si la respuesta es la pagina o un muro delante (`shared/respuestas.py`):
    # contenido, challenge_waf, captcha, rate_limited, respuesta_binaria,
    # login_requerido, desconocido. NULL = sin respuesta, salto de una
    # redireccion o rastreo anterior a la columna (decision 103).
    response_class = Column(String(32), nullable=True)
    # Si Googlebot puede pedirla segun el robots.txt guardado del host
    # (`robots_txt`, decision 113). NULL = no evaluado: censo anterior, host sin
    # robots.txt guardado, robots.txt inaccesible o con un muro delante. Lo
    # escribe el analisis; `blocked_by_robots` es lo que hizo el rastreo.
    bloqueada_googlebot = Column(Boolean, nullable=True)
    inlinks_count = Column(Integer, default=0)               # total inlinks to this URL
    outlinks_count = Column(Integer, default=0)              # outlinks INTERNOS (los externos, aparte)
    external_outlinks_count = Column(Integer, default=0)     # external outlinks count
    unique_inlinks_count = Column(Integer, default=0)        # unique source pages linking in
    # Tres columnas porque son tres preguntas distintas, y meterlas en una
    # era el problema (C4 de #24):
    #
    #   pagerank_raw    ¿cuanta autoridad interna tiene del total? Es la
    #                   probabilidad: todas las paginas suman 1. Multiplicada
    #                   por el numero de nodos da "veces la pagina media", que
    #                   SI es comparable entre sitios de tamaño distinto.
    #   pagerank_score  ¿esta arriba o abajo? 0-100 en escala logaritmica, el
    #                   equivalente al Link Score de Screaming Frog. Es la que
    #                   hay que leer y la que se ordena en un informe.
    #   pagerank        la escala 0-10 lineal de siempre, que se mantiene por
    #                   compatibilidad con informes ya entregados. No la uses
    #                   para decidir: la home vale 10 y el resto del sitio se
    #                   apelotona en 0,00xx, asi que no distingue la pagina
    #                   250 de la 25.000.
    pagerank = Column(Float, nullable=True, default=None)    # 0-10 lineal (compatibilidad)
    pagerank_raw = Column(Float, nullable=True, default=None)    # probabilidad, suma 1
    pagerank_score = Column(Integer, nullable=True, default=None)  # 0-100 logaritmico
    # Con la autoridad que entra de fuera (#31, decision 212): la misma escala
    # 0-100, otro teletransporte. NULL = el cliente no tiene backlinks subidos.
    # Nunca sustituye a `pagerank_score`: son dos preguntas (como reparte el
    # sitio, y por donde entra la autoridad).
    pagerank_externo_score = Column(Integer, nullable=True, default=None)
    # Backlinks dofollow del CSV que caen en esta URL, y lo que aportan.
    backlinks_externos = Column(Integer, nullable=True, default=None)
    # Cuantos de esos marca el proveedor como spam (no aportan autoridad).
    backlinks_spam = Column(Integer, nullable=True, default=None)
    autoridad_externa = Column(Float, nullable=True, default=None)
    # Visitas de Googlebot VERIFICADO segun los logs del cliente (decision
    # 213); NULL sin logs, 0 = el periodo del log no la vio.
    googlebot_visitas = Column(Integer, nullable=True, default=None)
    googlebot_ultima = Column(DateTime(timezone=True), nullable=True, default=None)
    # Casi duplicados (MinHash). NULL = no se midio (sin contenido, o texto
    # por debajo del minimo de palabras); 0 = se midio y no tiene ninguna.
    near_duplicate_count = Column(Integer, nullable=True, default=None)
    closest_similarity = Column(Float, nullable=True, default=None)
    # True/False once a sitemap was ingested for the job; NULL = no sitemap data.
    in_sitemap = Column(Boolean, nullable=True, default=None)
    # Segmento de negocio (decision 125, `shared/segmentos.py`): el nombre de la
    # primera regla de `config.segmentos` que casa o, si ninguna, la forma de la
    # ruta (empieza por `/`). Lo escribe el analisis y el re-segmentado; NULL =
    # censo anterior a la columna o aun sin analizar.
    segmento = Column(Text, nullable=True)

    job = relationship("Job", back_populates="urls")
    html_meta = relationship("HtmlMeta", back_populates="url_rel", uselist=False, cascade="all, delete-orphan")
    headings = relationship("Heading", back_populates="url_rel", cascade="all, delete-orphan")
    hreflangs = relationship("Hreflang", back_populates="url_rel", cascade="all, delete-orphan")
    structured_data = relationship("StructuredData", back_populates="url_rel", cascade="all, delete-orphan")
    resources = relationship("Resource", back_populates="url_rel", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="url_rel", cascade="all, delete-orphan")
    security = relationship("SecurityHeaders", back_populates="url_rel", uselist=False, cascade="all, delete-orphan")
    page_content = relationship("PageContent", back_populates="url_rel", uselist=False, cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("job_id", "url_hash", name="uq_job_url"),
        Index("ix_urls_job_status", "job_id", "status_code"),
        Index("ix_urls_job_host", "job_id", "host"),
    )


# ---------------------------------------------------------------------------
# HTML Metadata
# ---------------------------------------------------------------------------
class HtmlMeta(Base):
    __tablename__ = "html_meta"

    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), primary_key=True)

    title = Column(Text, nullable=True)
    title_len = Column(Integer, nullable=True)
    # Cuantos `<title>` / meta description hay, vacios incluidos: con dos no se
    # sabe cual usa Google (`title_multiple`, `description_multiple`). NULL =
    # rastreo anterior a la columna.
    title_count = Column(Integer, nullable=True)
    meta_description = Column(Text, nullable=True)
    meta_description_len = Column(Integer, nullable=True)
    meta_description_count = Column(Integer, nullable=True)
    meta_keywords = Column(Text, nullable=True)
    meta_robots = Column(String(256), nullable=True)
    # `<meta name="googlebot">`. Sin guardarlo, el analyzer recalculaba la
    # indexabilidad sin el y una pagina noindex solo para Google volvia a
    # "Indexable" al analizar (#26).
    meta_robots_googlebot = Column(String(256), nullable=True)
    # Una cabecera por linea (SEPARADOR_CABECERAS en shared/indexabilidad.py).
    x_robots_tag = Column(String(256), nullable=True)

    canonical_href = Column(Text, nullable=True)
    # Cuantos `rel=canonical` lleva la pagina y si alguno esta en el body.
    # Con varios, Google los ignora TODOS; los del body los ignora siempre.
    # Antes se guardaba el primero en silencio y la pagina salia canonicalizada
    # a una URL que Google no usa.
    canonical_count = Column(Integer, nullable=True)
    canonical_in_body = Column(Boolean, nullable=True)
    # Cuantos DESTINOS distintos declaran los canonicals del head (con la clave
    # de `misma_url`): `/a` y `https://x.com/a` son uno. Con mas de uno Google
    # los ignora todos y la pagina no esta canonicalizada (decision 115). NULL =
    # rastreo anterior a la columna: se cae a `canonical_count`.
    canonical_distintos = Column(Integer, nullable=True)
    canonical_header = Column(Text, nullable=True)

    og_title = Column(Text, nullable=True)
    og_description = Column(Text, nullable=True)
    og_image = Column(Text, nullable=True)
    og_url = Column(Text, nullable=True)
    og_type = Column(String(64), nullable=True)

    twitter_card = Column(String(64), nullable=True)
    twitter_title = Column(Text, nullable=True)
    twitter_description = Column(Text, nullable=True)

    rel_next = Column(Text, nullable=True)
    rel_prev = Column(Text, nullable=True)

    # --- Screaming Frog extended fields ---
    title_pixel_width = Column(Integer, nullable=True)             # SERP pixel width at Arial 20px
    meta_description_pixel_width = Column(Integer, nullable=True)  # SERP pixel width at Arial 14px
    meta_refresh = Column(Text, nullable=True)                     # meta refresh content if present
    # OJO: cuenta cualquier <meta> en el body por lxml, incluidos los
    # `itemprop` de microdatos, que son validos ahi. Salta en el 99,6% de las
    # paginas de penguin: no sirve como incidencia (decision 102). Lo que si
    # dice algo son las dos columnas de abajo.
    has_meta_outside_head = Column(Boolean, nullable=True)
    # Donde corta el navegador el head (`crawler/seo_crawler/head_html.py`,
    # decision 102): la etiqueta que lo cerro antes de su </head> («img»,
    # «div», «#texto»), NULL si acabo donde debia. Solo sin render: el DOM
    # serializado ya no conserva el corte.
    head_cortado_por = Column(String(64), nullable=True)
    # Metadatos que quedan en el body, separados por comas, de entre
    # canonical, description, googlebot, hreflang, robots y title. Cadena
    # vacia = medido y no hay ninguno; NULL = no medido (censo anterior).
    fuera_del_head = Column(String(128), nullable=True)

    # --- Lo que el HTML declara de si mismo (decision 108) ---
    # `content` del ULTIMO `<meta name=viewport>`, el que aplica el navegador
    # ("" si lo tiene vacio), y
    # cuantos hay. `viewport_count` es la marca de «medido» de todo el bloque:
    # 0 = no hay viewport; NULL = rastreo anterior a la columna, y entonces el
    # analizador no afirma que falte nada (decisiones 67 y 89).
    viewport = Column(Text, nullable=True)
    viewport_count = Column(Integer, nullable=True)
    # `<html lang>` (o `xml:lang`): "" = atributo vacio, NULL = no esta.
    html_lang = Column(String(35), nullable=True)
    # Cabecera `Content-Language`, tal cual.
    content_language = Column(String(64), nullable=True)
    # El href del canonical tal como se escribio: `canonical_href` va resuelto
    # y la forma (relativa, con fragmento) se perdia al extraer.
    canonical_crudo = Column(Text, nullable=True)
    # Forma de la og:image (`shared.metadatos_html.forma_de_href`).
    og_image_forma = Column(String(24), nullable=True)
    twitter_image = Column(Text, nullable=True)
    # Destino de un `location = "..."` a nivel superior de un script (la
    # pagina puente), absoluto y normalizado, sin render. Lo condicional no se
    # guarda.
    redireccion_js = Column(Text, nullable=True)
    # Charset del meta en los 1.024 primeros bytes ("" = no hay) y del BOM,
    # normalizados; si el cuerpo es solo ASCII, y si el titulo o el texto
    # llevan U+FFFD (bytes que no casan con la codificacion). Solo sin
    # render: con render los bytes originales se pierden, todo NULL.
    charset_meta = Column(String(40), nullable=True)
    charset_bom = Column(String(40), nullable=True)
    cuerpo_solo_ascii = Column(Boolean, nullable=True)
    texto_mal_codificado = Column(Boolean, nullable=True)
    # Decision 155: los videos de la pagina (`extract_videos`: tipo, id, src,
    # decorativo), como mucho 20. `[]` = medido y sin videos; NULL = rastreo
    # anterior. Es tambien la marca de «medido» de `amphtml` y
    # `alternate_movil` (decision 156): con `videos` NULL, que esas dos esten
    # a NULL no dice que la pagina no las anuncie.
    # `none_as_null`: un None es NULL de SQL, no el JSON `null`, para que el
    # analisis pueda filtrar «no medido» en la consulta.
    videos = Column(JSON(none_as_null=True), nullable=True)
    # Decision 156: la version AMP (`<link rel="amphtml">`) y la movil
    # (`<link rel="alternate" media="...max-width...">`) que la pagina
    # anuncia en su head, resueltas.
    amphtml = Column(Text, nullable=True)
    alternate_movil = Column(Text, nullable=True)
    # Decision 170: lo que `data-nosnippet` esconde al fragmento
    # (`shared/data_nosnippet.medir`): `{elementos, ignorados,
    # etiquetas_ignoradas, palabras, h1, principal}`. `{"elementos": 0, ...}` =
    # medido y sin el atributo; NULL = rastreo anterior o fallo al medir.
    data_nosnippet = Column(JSON(none_as_null=True), nullable=True)

    url_rel = relationship("Url", back_populates="html_meta")


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------
class Heading(Base):
    __tablename__ = "headings"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False, index=True)
    tag = Column(String(4), nullable=False)  # h1, h2, h3 …
    position = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    # El titular esta en la pagina pero no se pinta (hidden, display:none,
    # clase de utilidad, aria-hidden, dentro de template/noscript/svg). Se
    # guarda igual: lo que no se guarda no se puede auditar. Los checks de h1
    # cuentan solo los que SI se pintan, que es lo que ve el usuario.
    oculto = Column(Boolean, nullable=True)

    url_rel = relationship("Url", back_populates="headings")


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------
class Link(Base):
    __tablename__ = "links"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    from_url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False)
    to_url = Column(Text, nullable=False)
    to_url_hash = Column(String(64), nullable=False)
    anchor_text = Column(Text, nullable=True)
    rel = Column(String(128), nullable=True)
    is_internal = Column(Boolean, default=True)
    link_position = Column(String(20), nullable=True)  # nav, footer, content

    # --- Screaming Frog extended fields ---
    follow = Column(Boolean, default=True)                # whether link passes equity (derived from rel)
    target = Column(String(20), nullable=True)            # _blank, _self, etc.
    alt_text = Column(Text, nullable=True)                # for image links
    link_type = Column(String(20), default="hyperlink")   # hyperlink, image, redirect, canonical
    # Cuantas apariciones IDENTICAS de este enlace hay en la pagina (decision
    # 94): el megamenu repetido para escritorio y movil es una fila, no tres.
    # Un conteo "por instancia" (inlinks, outlinks) es SUM(repeticiones), no
    # COUNT(*). Los rastreos anteriores tienen 1 en todas: una fila por
    # aparicion, que suma lo mismo.
    repeticiones = Column(Integer, nullable=False, default=1, server_default="1")

    from_url_rel = relationship("Url", foreign_keys=[from_url_id])

    __table_args__ = (
        Index("ix_links_from", "from_url_id"),
        Index("ix_links_to_hash", "job_id", "to_url_hash"),
    )


# ---------------------------------------------------------------------------
# Hreflang
# ---------------------------------------------------------------------------
class Hreflang(Base):
    __tablename__ = "hreflang"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False, index=True)
    lang = Column(String(20), nullable=False)
    href = Column(Text, nullable=False)
    return_tag_ok = Column(Boolean, nullable=True)
    lang_valid = Column(Boolean, nullable=True)
    # Anotacion fuera del `<head>`: Google la ignora, asi que no cuenta como
    # retorno de nadie y se avisa con `hreflang_in_body`. NULL = rastreo
    # anterior a la columna (no se sabe; se trata como del head).
    en_body = Column(Boolean, nullable=True)
    # `html` (el `<head>` o el body) o `cabecera` (HTTP `Link`, la unica fuente
    # de un PDF). El del sitemap NO va aqui: es de una URL que puede no
    # haberse rastreado, y vive en `sitemap_entries.hreflang` (decision 167).
    # NULL = rastreo anterior, del HTML.
    origen = Column(String(16), nullable=True)

    url_rel = relationship("Url", back_populates="hreflangs")


# ---------------------------------------------------------------------------
# Structured Data
# ---------------------------------------------------------------------------
class StructuredData(Base):
    __tablename__ = "structured_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False, index=True)
    raw = Column(JSON, nullable=True)
    format = Column(String(20), nullable=False)  # jsonld, microdata, rdfa
    schema_type = Column(String(128), nullable=True)
    validation_status = Column(String(10), nullable=True)  # ok, info, warning, error
    validation_issues = Column(JSON, nullable=True)
    # Por que el bloque JSON-LD no es JSON estricto (coma final, comentario):
    # Google lo descarta entero, aunque un lector permisivo lo lea y `raw`
    # parezca bueno. NULL = JSON valido, o bloque que no es JSON-LD, o rastreo
    # anterior a la columna (#28, decision 80).
    json_invalido = Column(String(200), nullable=True)

    url_rel = relationship("Url", back_populates="structured_data")


# ---------------------------------------------------------------------------
# Resources (images, CSS, JS, PDFs)
# ---------------------------------------------------------------------------
class Resource(Base):
    __tablename__ = "resources"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False, index=True)
    resource_url = Column(Text, nullable=False)
    resource_type = Column(String(20), nullable=False)  # image, css, js, pdf, font, other
    alt_text = Column(Text, nullable=True)
    # Sin rellenar: el rastreo no descarga el cuerpo de los recursos. El dato
    # existiria uniendo resource_url con urls.content_length cuando el recurso
    # se haya rastreado como URL; hasta entonces la columna no se expone.
    size_bytes = Column(BigInteger, nullable=True)

    # --- Screaming Frog extended fields ---
    width = Column(Integer, nullable=True)              # width attribute from HTML
    height = Column(Integer, nullable=True)             # height attribute from HTML
    is_mixed_content = Column(Boolean, nullable=True)   # HTTP resource on HTTPS page

    url_rel = relationship("Url", back_populates="resources")


# ---------------------------------------------------------------------------
# Security Headers (1:1 with Url)
# ---------------------------------------------------------------------------
class PageContent(Base):
    __tablename__ = "page_content"

    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), primary_key=True)
    content_text = Column(Text, nullable=True)
    content_length = Column(Integer, nullable=True)
    content_markdown = Column(Text, nullable=True)

    # HTML tal como lo vio el extractor. Solo con `extraction.store_raw_html`,
    # y por algo viene apagado: medido en un censo real, 170 kB de media por
    # pagina — 29.808 paginas son 4,9 GB antes de que Postgres lo comprima.
    # Sirve para re-extraer contenido sin volver a rastrear y para auditar por
    # que una pagina salio vacia. OJO con render: ahi es el DOM renderizado y
    # YA limpio de banners, no el HTML de origen (es lo que vio el extractor,
    # que es justo lo que hace falta para re-extraer).
    raw_html = Column(Text, nullable=True)

    # El texto visible que sigue al primer h1, hasta 1.000 caracteres: en una
    # ficha, la caja de compra (decision 187). Solo en las paginas cuyo marcado
    # declara valores verificables (precio, valoracion, fecha, disponibilidad);
    # NULL en las demas y en lo rastreado antes. Aparte de `content_text`
    # porque trafilatura tira a veces la caja de compra de una ficha.
    texto_tras_h1 = Column(Text, nullable=True)

    # Post-crawl cleaning: originals kept for revert; cleaned_at marks state.
    content_text_original = Column(Text, nullable=True)
    content_markdown_original = Column(Text, nullable=True)
    cleaned_at = Column(DateTime(timezone=True), nullable=True)

    url_rel = relationship("Url", back_populates="page_content")


class CleaningRuleset(Base):
    """History of post-crawl cleaning rule applications (per job + URL group)."""

    __tablename__ = "cleaning_rulesets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    group_key = Column(Text, nullable=True)
    url_regex = Column(Text, nullable=True)
    rules = Column(JSON, nullable=False)
    targets = Column(String(20), nullable=False, default="both")  # text | markdown | both
    pages_updated = Column(Integer, default=0)
    pages_skipped = Column(Integer, default=0)
    chars_removed = Column(BigInteger, default=0)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class SecurityHeaders(Base):
    __tablename__ = "security_headers"

    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), primary_key=True)

    is_https = Column(Boolean)
    has_mixed_content = Column(Boolean)
    has_hsts = Column(Boolean)                                  # Strict-Transport-Security header present
    has_csp = Column(Boolean)                                   # Content-Security-Policy header present
    has_x_content_type_options = Column(Boolean)                # X-Content-Type-Options present
    has_x_frame_options = Column(Boolean)                       # X-Frame-Options present
    referrer_policy = Column(String(64), nullable=True)         # Referrer-Policy header value
    has_unsafe_crossorigin = Column(Boolean)                    # target=_blank without rel=noopener

    url_rel = relationship("Url", back_populates="security")


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------
class Issue(Base):
    __tablename__ = "issues"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False)
    issue_type = Column(String(64), nullable=False)
    severity = Column(String(10), nullable=False)  # error, warning, info
    details = Column(JSON, nullable=True)
    # Que distingue dos hallazgos del MISMO tipo en la MISMA URL: el codigo de
    # hreflang, el grupo de un duplicado, la imagen sin alt. Sin ella no se
    # puede decir "esto se arreglo" entre dos censos (#32). NULL en las reglas
    # que emiten como mucho una incidencia por URL.
    group_key = Column(String(64), nullable=True)
    detected_at = Column(DateTime(timezone=True), default=_utcnow)

    url_rel = relationship("Url", back_populates="issues")

    __table_args__ = (
        Index("ix_issues_job", "job_id"),
        Index("ix_issues_job_type", "job_id", "issue_type"),
        # url_id es FK con ON DELETE CASCADE y sin indice Postgres tiene que
        # recorrer la tabla entera por CADA fila de `urls` que se borra. Medido
        # en produccion con 1,76 M de incidencias: borrar 16 rastreos (26.597
        # URLs) pasaba de mas de 14 minutos sin terminar a 15 segundos.
        # Tambien lo usa el join de GET /issues/urls.
        Index("ix_issues_url_id", "url_id"),
    )


# ---------------------------------------------------------------------------
# Extraccion y busqueda a medida (#34, decision 104)
# ---------------------------------------------------------------------------
class CustomExtraction(Base):
    """Una fila por (URL, regla) EVALUADA.

    Sin fila = «no evaluada» (no es HTML 2xx, cae fuera de `solo_urls`, o el
    censo es anterior a la regla), que NO es «vacio»: «no contiene» es
    exactamente `estado='sin_coincidencia'`. Las definiciones de las reglas
    viajan en `jobs.config` (`custom_extraction` / `custom_search`).

    `job_id` va en la fila a proposito: filtrar, borrar y pesar por censo sin
    unir con `urls` (decision 37).
    """

    __tablename__ = "custom_extraction"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(40), nullable=False)
    clase = Column(String(10), nullable=False)        # extractor | busqueda
    # ok, sin_coincidencia, incompleta, conversion_fallida, tiempo_agotado,
    # presupuesto_pagina, desactivada, pagina_bloqueada, error
    estado = Column(String(24), nullable=False)
    # Coincidencias reales antes de recortar. NULL salvo en ok,
    # sin_coincidencia y conversion_fallida: en los demas no se llego a contar.
    n = Column(Integer, nullable=True)
    # `primero`: el valor; `todos`: unidos con " | "; busqueda: ~120
    # caracteres de contexto de la primera coincidencia.
    valor = Column(Text, nullable=True)
    # `valor` con los espacios colapsados y recortado a 256: para ordenar,
    # agrupar y comparar sin pasarse del limite de una clave de B-tree.
    valor_clave = Column(String(256), nullable=True)
    valor_num = Column(Float, nullable=True)
    valores = Column(JSON, nullable=True)              # solo con `todos`
    truncado = Column(Boolean, nullable=False, default=False)
    # True = se extrajo del DOM renderizado (y ya sin banners); False = del HTML
    # de la respuesta: job sin render, o pagina que cayo en `_sin_render`.
    render = Column(Boolean, nullable=True)
    detalle = Column(String(200), nullable=True)       # motivo del error, sin datos de la pagina

    __table_args__ = (
        UniqueConstraint("url_id", "nombre", name="uq_cext_url_nombre"),
        Index("ix_cext_job_nombre_estado", "job_id", "nombre", "estado"),
        Index("ix_cext_job_nombre_num", "job_id", "nombre", "valor_num"),
        Index("ix_cext_job_nombre_clave", "job_id", "nombre", "valor_clave"),
    )


# ---------------------------------------------------------------------------
# Enlaces que Google no puede seguir (decision 106)
# ---------------------------------------------------------------------------
class EnlaceNoRastreable(Base):
    """Un enlace que una persona puede pulsar y Google no puede seguir.

    `href="javascript:..."`, `<a onclick>` sin href, `<a routerLink>`,
    `<span href>`, la tarjeta con `onclick="location=..."` y la ruta en el
    fragmento (`#/x`). Tabla APARTE de `links` a proposito: `links` es el grafo
    —entrantes, PageRank, profundidad, la comparacion y el archivo en Parquet
    la leen en mas de veinte consultas— y una fila que no es una arista
    obligaria a filtrarla en todas; la que se olvide cambia el PageRank sin
    avisar (decisiones 23 y 39: dos criterios acaban discrepando).

    `job_id` en la fila para filtrar, borrar y pesar por censo sin unir con
    `urls` (decision 37). Una fila por enlace distinto de la pagina, con
    `repeticiones` (decision 94).
    """

    __tablename__ = "enlaces_no_rastreables"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    from_url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False)
    # javascript_href, onclick_sin_href, a_sin_href, href_fuera_de_a,
    # onclick_en_otra_etiqueta, fragmento_como_ruta (shared/enlaces_no_rastreables.py)
    crawlability = Column(String(32), nullable=False)
    etiqueta = Column(String(20), nullable=True)       # a, span, div, button...
    href = Column(Text, nullable=True)                 # el atributo (o el onclick), recortado
    # A donde iria, si el codigo lo dice; NULL = no se sabe, que no es «a ningun sitio».
    destino = Column(Text, nullable=True)
    destino_interno = Column(Boolean, nullable=True)
    # El de `urls.url_hash`: para saber si el destino esta en el censo.
    destino_hash = Column(String(64), nullable=True)
    anchor_text = Column(Text, nullable=True)
    link_position = Column(String(20), nullable=True)
    repeticiones = Column(Integer, nullable=False, default=1, server_default="1")

    __table_args__ = (
        Index("ix_enr_job", "job_id"),
        Index("ix_enr_from", "from_url_id"),
    )


class CapturaAlternativa(Base):
    """La misma URL pedida con otro perfil, comparada con la del censo (decision 119).

    Hoy, el perfil movil (Ola 7.4): una muestra por plantilla pedida con el UA
    y el dispositivo de un movil durante el rastreo, como sonda fuera de
    `max_urls` (patron de la decision 105). Pensada tambien para la Ola 7.1
    (`perfil='crudo'`, la respuesta sin render frente al render).

    Una fila por URL muestreada y perfil AUNQUE no haya diferencias: «no
    difiere» es un dato y «sin fila» es «no evaluada» (como la decision 104).
    `estado` dice que se pudo comparar: `comparada`, `redirige` (la otra
    version manda a otra URL: m-dot o servido distinto, sin comparar campos),
    `respuesta_distinta` (otro codigo) o `no_evaluada` (un muro, un error,
    robots). `diferencias` son las de `shared.paridad.diferencias` sin los
    campos `volatiles`: los que tambien cambian entre dos peticiones con el
    perfil del censo (decision 13), que no se afirman.

    `job_id` en la fila para filtrar y borrar por censo sin unir con `urls`
    (decision 37).
    """

    __tablename__ = "capturas_alternativas"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=False)
    # movil | escritorio (la alternativa de un censo rastreado con UA movil);
    # crudo | render (decision 140); axe (decision 174: `medidas` es el
    # resumen de axe-core y `estado` evaluada | no_evaluada)
    perfil = Column(String(20), nullable=False)
    # render | sin_render: las dos capturas van SIEMPRE en el mismo modo
    modo = Column(String(12), nullable=True)
    estado = Column(String(24), nullable=False)
    # Con que se agrupo la muestra: `config.templates` o `firma_de_ruta`
    plantilla = Column(Text, nullable=True)
    user_agent = Column(Text, nullable=True)
    status_code = Column(Integer, nullable=True)
    response_class = Column(String(32), nullable=True)
    redirige_a = Column(Text, nullable=True)
    # Cabecera `Vary` de la respuesta del censo y de la alternativa
    vary_base = Column(Text, nullable=True)
    vary = Column(Text, nullable=True)
    medidas = Column(JSON, nullable=True)
    diferencias = Column(JSON, nullable=True)
    volatiles = Column(JSON, nullable=True)
    # Lo que no es un campo: el destino de un m-dot y su anotacion, el error...
    detalle = Column(JSON, nullable=True)
    capturada_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_capalt_job_perfil", "job_id", "perfil"),
        Index("ix_capalt_url", "url_id"),
    )


# ---------------------------------------------------------------------------
# robots.txt de cada host del censo (decisiones 112 y 113)
# ---------------------------------------------------------------------------
class RobotsTxt(Base):
    """Lo que respondio el robots.txt de un host durante el rastreo.

    Una fila por (job, URL del robots.txt): Google trata aparte cada esquema,
    host y puerto. La escribe `RobotsTxtRegistroMiddleware` con la respuesta
    FINAL (tras reintentos y redirecciones) de la misma descarga con la que
    Scrapy decide que se pide, y el analisis la evalua para Googlebot (y para
    los bots de la Ola 7.3). Sin fila = «no evaluado», nunca «sin robots.txt».

    El cuerpo solo se guarda de un 2xx, recortado a los 500 KiB que lee Google
    (`recortado`); `bytes` y `sha256` son del cuerpo entero, para ver si cambio
    entre censos (#36). `comprobacion` es la segunda peticion al acabar el
    rastreo cuando la primera fallo: separa un fallo pasajero de uno que dura.
    """

    __tablename__ = "robots_txt"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    host = Column(String(512), nullable=False)
    url = Column(Text, nullable=False)                  # https://host/robots.txt pedido
    url_final = Column(Text, nullable=True)             # si redirigio, a donde
    status_code = Column(Integer, nullable=True)        # NULL = no hubo respuesta
    error = Column(String(200), nullable=True)          # tipo de excepcion: timeout, DNS...
    response_class = Column(String(32), nullable=True)  # shared/respuestas.py (decision 103)
    intentos = Column(Integer, nullable=True)           # con los reintentos de Scrapy
    bytes = Column(Integer, nullable=True)
    sha256 = Column(String(64), nullable=True)
    cuerpo = Column(Text, nullable=True)
    recortado = Column(Boolean, nullable=True)
    # {status_code, error, response_class, fecha} de la comprobacion al cerrar.
    comprobacion = Column(JSON, nullable=True)
    # Lo que escribe el analisis: por bot, URLs evaluadas y bloqueadas.
    evaluacion = Column(JSON, nullable=True)
    fecha = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("job_id", "url", name="uq_robots_txt_job_url"),
        Index("ix_robots_txt_job_host", "job_id", "host"),
    )


class SitemapEntry(Base):
    """Una URL declarada en UN fichero de sitemap (decision 126).

    Una fila por (fichero, URL) y no por URL: la misma URL en tres ficheros
    son tres filas, que es lo que dice `en_varios_sitemaps` y de donde sale el
    «viene de» de la ficha. Solo URLs internas, las mismas que marcan
    `urls.in_sitemap`. `url_hash` es el de `urls.url_hash` (compute_url_hash
    de la URL normalizada), asi que una URL del sitemap que no se llego a
    rastrear tiene fila aqui y no en `urls`; por eso va tambien `url`.

    `lastmod` tal cual lo escribe el sitemap (recortado a 64): se juzga en el
    analisis (`shared/sitemaps.py`) para que re-analizar cambie el criterio sin
    re-rastrear. Lo que se sabe de cada FICHERO (tamano, cuantas declara, si se
    corto) esta en `jobs.sitemaps`. Con tope de filas por censo
    (`SITEMAP_ENTRIES_MAX`): pasado el tope, `jobs.sitemaps` lo dice.

    `job_id` en la fila para filtrar, borrar y pesar por censo sin unir con
    `urls` (decision 37).
    """

    __tablename__ = "sitemap_entries"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    url_hash = Column(String(64), nullable=False)
    url = Column(Text, nullable=False)
    fichero = Column(Text, nullable=False)
    lastmod = Column(String(64), nullable=True)
    # Cuantos `<video:video>` declara la entrada (decision 155). 0 = ninguno;
    # NULL = leida antes de la columna, que no es «sin video».
    videos = Column(Integer, nullable=True)
    # Los `<xhtml:link rel="alternate" hreflang>` de la entrada (decision 167),
    # como [[idioma, href], ...], el href del mismo origen sin el
    # (`shared/sitemaps.compactar_hreflang`). [] = ninguno; NULL = no se sabe
    # (leida antes de la columna o pasado el tope `SITEMAP_HREFLANG_MAX`).
    hreflang = Column(JSON(none_as_null=True), nullable=True)

    __table_args__ = (
        Index("ix_sment_job_hash", "job_id", "url_hash"),
    )


class UrlState(Base):
    """Lo que se sabe de cada URL de un perfil entre rastreos (decision 220).

    Una fila por (perfil, URL), con lo necesario para decidir si se pide en el
    siguiente incremental sin tocar `urls`: cada cuantos ciclos cambia
    (intervalo adaptativo), en que ciclo toca, sus cabeceras condicionales y
    sus firmas. La escribe `shared/incremental.actualizar_estado` despues del
    analisis de cada job del perfil, completo o incremental. Las URLs que
    desaparecen del censo salen de aqui en esa misma pasada.

    Va por perfil y por `url_hash`, nunca por `urls.id`: el id cambia en cada
    job.
    """

    __tablename__ = "url_state"

    profile_id = Column(
        UUID(as_uuid=True), ForeignKey("crawl_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    url_hash = Column(String(64), primary_key=True)
    url = Column(Text, nullable=False)
    # La profundidad del ultimo rastreo: lo que toca se pide con ella, no
    # como semilla (si no, el analisis la veria a profundidad 0).
    profundidad = Column(Integer, nullable=True)
    etag = Column(String(256), nullable=True)
    last_modified = Column(String(128), nullable=True)
    # `urls.content_hash` (contenido principal normalizado) y una firma de lo
    # SEO (estado, title, description, canonical, robots, H1 y enlaces).
    firma_contenido = Column(String(64), nullable=True)
    firma_seo = Column(String(64), nullable=True)
    # Cada cuantos ciclos se pide, en ciclos del perfil (un ciclo = un job).
    intervalo = Column(Float, nullable=False, default=1.0)
    # El ciclo en que vuelve a tocar.
    proximo_ciclo = Column(Integer, nullable=False, default=0)
    # Se pide en todos los ciclos: semillas, portadas y hubs.
    fijo = Column(Boolean, nullable=False, default=False)
    sin_cambios = Column(Integer, nullable=False, default=0)
    ultimo_cambio_ciclo = Column(Integer, nullable=True)
    ultima_peticion = Column(DateTime(timezone=True), nullable=True)
    last_job_id = Column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True,
    )

    __table_args__ = (
        Index("ix_url_state_toca", "profile_id", "proximo_ciclo"),
    )


class JobFrontera(Base):
    """Lo que un job incremental tiene que pedir (decision 220).

    La rellena `shared/incremental.preparar_job` al crear el job, desde
    `url_state`: lo que toca, lo fijo y una muestra de control al azar de lo
    que no toca. El spider no sabe de perfiles: lee esto y su job.
    """

    __tablename__ = "job_frontera"

    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"),
                    primary_key=True)
    url_hash = Column(String(64), primary_key=True)
    url = Column(Text, nullable=False)
    profundidad = Column(Integer, nullable=True)
    etag = Column(String(256), nullable=True)
    last_modified = Column(String(128), nullable=True)
    # toca | fijo | control
    motivo = Column(String(16), nullable=False)


class SitemapArrastre(Base):
    """URLs del censo anterior que estan en el sitemap de ESTE job sin haberse
    pedido en el (decision 220).

    El spider marca `in_sitemap` al cerrar, cuando las filas arrastradas
    todavia no existen: deja aqui sus hashes y el arrastre les aplica despues
    la misma regla `True/False/NULL` que a las demas. Sin esto saldrian con
    el sitemap de la semana pasada o a NULL, y sus `not_in_sitemap`
    desaparecerian como «resueltas».
    """

    __tablename__ = "sitemap_arrastre"

    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"),
                    primary_key=True)
    url_hash = Column(String(64), primary_key=True)


class LogImport(Base):
    """Un log del servidor subido para un cliente (#35, decision 213).

    Por cliente, como los backlinks y Search Console. El fichero va al
    volumen de archivo, lo lee el worker en streaming y se borra al acabar: de
    el solo queda lo agregado de los bots en `log_urls`.
    """

    __tablename__ = "log_imports"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    fichero = Column(String(255), nullable=True)
    ruta_disco = Column(Text, nullable=True)
    bytes = Column(BigInteger, nullable=True)
    formato = Column(String(16), nullable=False, default="combined")
    regex = Column(Text, nullable=True)
    formato_fecha = Column(String(64), nullable=True)
    # El host del sitio: el log guarda rutas, no URLs.
    host = Column(String(255), nullable=False)
    # pendiente | procesando | hecho | error
    estado = Column(String(16), nullable=False, default="pendiente", index=True)
    motivo = Column(Text, nullable=True)
    lineas_ok = Column(BigInteger, nullable=True)
    lineas_error = Column(BigInteger, nullable=True)
    # Las primeras lineas que no casaron: casi siempre otro formato.
    errores = Column(JSON, nullable=True)
    personas = Column(BigInteger, nullable=True)
    desde = Column(DateTime(timezone=True), nullable=True)
    hasta = Column(DateTime(timezone=True), nullable=True)
    # Por bot: visitas verificadas, falsas y sin comprobar.
    bots = Column(JSON, nullable=True)
    progreso = Column(BigInteger, nullable=True)
    # Lo actualiza el worker mientras lee: sin latido, la lectura se corto.
    latido_at = Column(DateTime(timezone=True), nullable=True)
    # Lo que se aparto al leer: de otro host, fuera del tope de rutas, otros metodos.
    resumen = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    terminado_at = Column(DateTime(timezone=True), nullable=True)


class LogUrl(Base):
    """Las visitas de un bot a una ruta en un log, agregadas (decision 213).
    Una fila por (ruta, bot, verificado). `verificado` None = no se pudo
    comprobar (el proveedor no publica rangos)."""

    __tablename__ = "log_urls"
    __table_args__ = (Index("ix_log_urls_import", "import_id"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(BigInteger, ForeignKey("log_imports.id", ondelete="CASCADE"), nullable=False)
    ruta = Column(Text, nullable=False)
    clave = Column(Text, nullable=False)
    bot = Column(String(32), nullable=False)
    verificado = Column(Boolean, nullable=True)
    visitas = Column(Integer, nullable=False, default=0)
    codigos = Column(JSON, nullable=True)
    movil = Column(Integer, nullable=True)
    primero = Column(DateTime(timezone=True), nullable=True)
    ultimo = Column(DateTime(timezone=True), nullable=True)


class BacklinkImport(Base):
    """Un CSV de backlinks subido para un cliente (#31, decision 212).

    Por cliente y no por censo, como Search Console (decision 141): los
    backlinks son del sitio, no de cuando lo rastreamos. El analisis de un
    censo usa la importacion mas reciente de su cliente y dice cual.
    """

    __tablename__ = "backlink_imports"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    fuente = Column(String(16), nullable=False)        # ahrefs | semrush | majestic | generico
    fichero = Column(String(255), nullable=True)
    # La fecha del dato del proveedor (cuando lo exporto), no la de subida:
    # el censo es de hoy y el indice de backlinks, de cuando sea.
    fecha_dato = Column(Date, nullable=True)
    filas = Column(Integer, nullable=False, default=0)
    # Lo que se tiro al leer: nofollow/ugc/sponsored, perdidos, sin URL.
    descartadas = Column(JSON, nullable=True)
    # Dofollow que el proveedor marca como spam (se guardan, no aportan).
    # NULL = el export no trae esa columna.
    spam = Column(Integer, nullable=True)
    columnas = Column(JSON, nullable=True)
    cortado = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)


class ExternalLink(Base):
    """Un backlink dofollow de una importacion (decision 212).

    Se guardan TODOS, tambien los que no casan con ningun censo: las URLs
    antiguas con enlaces son de lo mas valioso (un 404 con autoridad).
    """

    __tablename__ = "external_links"
    __table_args__ = (Index("ix_external_links_import", "import_id"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_id = Column(BigInteger, ForeignKey("backlink_imports.id", ondelete="CASCADE"), nullable=False)
    url_to = Column(Text, nullable=False)
    url_from = Column(Text, nullable=False)
    dominio_from = Column(String(255), nullable=True)
    aportacion = Column(Float, nullable=False, default=1.0)
    # «Is spam» de Ahrefs: True no aporta autoridad; NULL, sin el dato.
    spam = Column(Boolean, nullable=True)


class AdapterEntity(Base):
    """Una entidad que un CMS dice que publica, leida de su API (decision 161).

    Hoy solo WordPress (`adaptador='wordpress'`): una fila por entrada, pagina,
    entrada de un tipo propio, adjunto o termino de la REST API publica, y una
    por cada sonda del adaptador (`tipo='sonda_paginacion'` o
    `'sonda_adjunto'`: lo que respondio la pagina N+1 de un archivo o la pagina
    de un adjunto). Las sondas NO son URLs del censo: no estan en `urls`.

    Sin clave foranea a `urls`: que la entidad no tenga fila alli es justo el
    hallazgo, y el emparejamiento se hace al analizar, por `(job_id,
    url_hash)` (el indice unico de `urls`), o por `url_hash_alt` (la misma URL
    con el otro esquema: un WordPress con `home` en http servido por https).
    `en_alcance` = la URL pasaba los filtros del job (patrones, longitud,
    carpetas): si no, que no este en el censo no dice nada. Cada proceso de
    Scrapy vuelve a leer la REST API entera y borra antes lo que hubiera.
    """

    __tablename__ = "adapter_entities"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    adaptador = Column(String(32), nullable=False)
    tipo = Column(String(64), nullable=False)
    id_externo = Column(String(64), nullable=True)
    url = Column(Text, nullable=True)
    url_hash = Column(String(64), nullable=True)
    url_hash_alt = Column(String(64), nullable=True)
    en_alcance = Column(Boolean, nullable=True)
    # `publish`, `inherit` (adjuntos)... de la REST API.
    estado = Column(String(32), nullable=True)
    # Sondas: el codigo HTTP que respondio la URL.
    status_code = Column(Integer, nullable=True)
    # Terminos: cuantas entradas publicadas tiene (`count`).
    cuenta = Column(Integer, nullable=True)
    # `modified_gmt` tal cual lo da la API.
    modificado = Column(String(40), nullable=True)
    # El resto: taxonomia, padre, fichero del adjunto, y de una sonda la
    # redireccion, el content-type, robots y canonical.
    datos = Column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_adent_job_tipo", "job_id", "tipo"),
        Index("ix_adent_job_hash", "job_id", "url_hash"),
        # La ficha de una URL busca por los dos hashes (decision 168): sin este
        # el OR no puede ir por indice y filtra todas las entidades del job.
        Index("ix_adent_job_hash_alt", "job_id", "url_hash_alt"),
    )


class ProfileRun(Base):
    """Lo que dejo una ejecucion, en una fila: la evolucion de un perfil o un
    cliente a lo largo de sus rastreos (#36 F3, decision 130).

    Una fila por job TERMINADO, escrita al acabar el analisis y al cerrar el
    rastreo (`shared/evolucion.py`, best-effort) y rellenada hacia atras con
    `scripts/rellenar_evolucion.py`. Sale de `urls`, `issues` y
    `jobs.pagerank_resumen`, **nunca de `links`** (decision 37): asi una ficha
    con 50 ejecuciones lee 50 filas y no 50 censos.

    Solo cifras. De quien es (cliente, perfil, programacion), su tipo y si es
    comparable se leen de `jobs` al pedir la evolucion: el cliente y el tipo de
    un job se pueden cambiar despues (`PATCH /api/jobs/{id}`), y copiarlos aqui
    los dejaria desfasados. `analisis_version` SI se copia: es la version con
    la que se contaron ESTAS incidencias, y si ya no coincide con la del job el
    agregado esta desfasado (alguien re-analizo sin pasar por aqui).
    """

    __tablename__ = "profile_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"),
                    nullable=False, unique=True)
    # Version de la DEFINICION de este agregado (`shared.evolucion.CRITERIO`):
    # si cambia lo que se cuenta, las filas viejas se rehacen con el script.
    criterio = Column(Integer, nullable=False, default=1)
    analisis_version = Column(String(64), nullable=True)
    crawler_version = Column(String(64), nullable=True)
    # Foto del estado al calcular (informativo; el que manda es el de `jobs`).
    status = Column(String(20), nullable=True)
    finish_reason = Column(String(32), nullable=True)
    # Host de la primera semilla, para la serie de los rastreos sin perfil ni
    # programacion. Copiado aqui porque las semillas no cambian y leerlas al
    # pedir la evolucion cuesta cientos de kB por job (un censo sembrado desde
    # el sitemap: 3.040 semillas, 233 kB).
    host = Column(String(255), nullable=True)

    # URLs internas del censo, por grupo de estado.
    urls = Column(Integer, nullable=False, default=0)
    urls_2xx = Column(Integer, nullable=False, default=0)
    urls_3xx = Column(Integer, nullable=False, default=0)
    urls_4xx = Column(Integer, nullable=False, default=0)
    urls_5xx = Column(Integer, nullable=False, default=0)
    urls_bloqueadas = Column(Integer, nullable=False, default=0)
    # Paginas HTML internas con 2xx, y de ellas las indexables: el mismo
    # criterio que `/stats` y la serie del cliente.
    paginas_html = Column(Integer, nullable=False, default=0)
    indexables = Column(Integer, nullable=False, default=0)
    # Clics desde la home (decision 90) de las indexables con camino, y
    # cuantas indexables no tienen camino. NULL = sin ninguna con camino.
    click_depth_medio = Column(Float, nullable=True)
    indexables_sin_camino = Column(Integer, nullable=False, default=0)

    incidencias = Column(Integer, nullable=False, default=0)
    errores = Column(Integer, nullable=False, default=0)
    avisos = Column(Integer, nullable=False, default=0)
    info = Column(Integer, nullable=False, default=0)
    urls_con_error = Column(Integer, nullable=False, default=0)
    # `[{"tipo", "severidad", "n"}]`, los 10 tipos con mas filas.
    top_tipos = Column(JSON, nullable=True)

    # De `jobs.pagerank_resumen`: fraccion (0-1) que acaba en errores y
    # sin respuesta, y la que acaba en indexables. NULL = sin PageRank.
    pagerank_desperdiciado = Column(Float, nullable=True)
    pagerank_indexable = Column(Float, nullable=True)

    segundos = Column(Float, nullable=True)
    calculado_at = Column(DateTime(timezone=True), default=_utcnow)


class RespuestaSondeada(Base):
    """Lo que respondio una URL que el rastreo pidio SIN que sea del censo.

    Enlaces externos (decision 123) y recursos embebidos (decision 124): se
    piden con una sonda (`crawler/seo_crawler/sonda_respuestas.py`) que no
    gasta `max_urls`, no escribe en `urls` y no cuenta para la salud del
    rastreo. Una fila por URL distinta del job, con `job_id` para filtrar y
    borrar por censo sin unir con nada (decision 37). Sin fila = no se
    comprobo (sondas apagadas, tope alcanzado, host con su tope), que no es lo
    mismo que «responde bien» (decision 104).

    `veredicto` y sus valores viven en `shared/sondas.py`. `status_code` es lo
    que respondio la URL enlazada; `final_url`/`final_status`, a donde llevo
    si redirigia. `host_caido`: el spider dio el origen por inalcanzable
    (DNS que no existe, confirmado con el resolver, o dos fallos de conexion
    seguidos) y las demas URLs suyas ya no se pidieron (`metodo` NULL).
    """

    __tablename__ = "respuestas_sondeadas"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    # El de `links.to_url_hash` (compute_url_hash de la URL normalizada).
    url_hash = Column(String(64), nullable=False)
    url = Column(Text, nullable=False)
    host = Column(String(255), nullable=True)
    # enlace | recurso | og_image: por que se pidio (la primera vez que se vio).
    uso = Column(String(10), nullable=False)
    interno = Column(Boolean, nullable=False, default=False)
    # HEAD | GET (el ultimo usado); NULL = no se pidio (robots, host caido).
    metodo = Column(String(8), nullable=True)
    status_code = Column(Integer, nullable=True)
    final_url = Column(Text, nullable=True)
    final_status = Column(Integer, nullable=True)
    saltos = Column(Integer, nullable=True)
    veredicto = Column(String(32), nullable=False)
    response_class = Column(String(32), nullable=True)
    host_caido = Column(Boolean, nullable=True)
    content_type = Column(String(255), nullable=True)
    # Bytes del recurso por el cable (`Content-Range` o `Content-Length`).
    content_length = Column(BigInteger, nullable=True)
    error = Column(Text, nullable=True)
    # Dimensiones de la imagen, solo en `uso='og_image'` (decision 154): las
    # de la cabecera del fichero (`shared/dimensiones_imagen.py`). NULL = no
    # se pudo leer (formato raro, respuesta que no es una imagen), nunca 0.
    ancho = Column(Integer, nullable=True)
    alto = Column(Integer, nullable=True)
    fecha = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint("job_id", "url_hash", name="uq_rsond_job_hash"),
    )


# ---------------------------------------------------------------------------
# Decisiones de un modelo (#7, decision 84)
# ---------------------------------------------------------------------------
class Decision(Base):
    """Una respuesta de Jev a una pregunta sobre un estado.

    Es a la vez el registro de lo decidido y la cache DURADERA: un recrawl
    busca aqui por `(clave, pregunta, version_pregunta, modelo)` antes de
    pagar otra vez (la de Redis es la que comparten las replicas durante una
    ejecucion y caduca).

    `clave` es el hash del estado NORMALIZADO y no depende de `url_id`, que
    cambia de un job a otro: es lo que permite al rastreo incremental (#36 F4)
    arrastrar decisiones de un job al siguiente sin llamar a nadie.

    `run_id` es la ejecucion de enriquecimiento de #40 (`enrichment_runs`), y
    NULL para lo que no venga de una (el juego de evaluacion de #8). SET NULL
    al borrar la ejecucion: la decision sigue valiendo como cache.
    """

    __tablename__ = "decisions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    # Nullable: el juego de evaluacion de #8 pregunta sin job.
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"),
                    nullable=True)
    url_id = Column(BigInteger, ForeignKey("urls.id", ondelete="CASCADE"), nullable=True)
    run_id = Column(UUID(as_uuid=True),
                    ForeignKey("enrichment_runs.id", ondelete="SET NULL"), nullable=True)
    # url | bloque | enlace | par | job
    ambito = Column(String(10), nullable=False, default="url")
    clave = Column(String(64), nullable=False)
    pregunta = Column(String(64), nullable=False)
    version_pregunta = Column(Integer, nullable=False)
    # decidido | incierto | sin_decidir
    estado = Column(String(12), nullable=False)
    # modelo | cache | arrastre | regla | humano
    origen = Column(String(10), nullable=False)
    # Para `noul` la probabilidad de si en texto ("0.98"): una sola columna
    # para los tres tipos, y los numeros siguen en `probabilidades`.
    respuesta = Column(Text, nullable=True)
    probabilidades = Column(JSON, nullable=True)
    confianza = Column(Float, nullable=True)
    # El modelo PEDIDO (fijado en el catalogo), que es el que forma la clave
    # de cache, y el que respondio (`typesafe/jev-1.13-20260917`), que puede
    # no coincidir y es el que hay que mirar al comparar resultados.
    modelo = Column(String(64), nullable=False)
    modelo_respuesta = Column(String(96), nullable=True)
    proveedor = Column(String(64), nullable=True)
    tokens_entrada = Column(Integer, nullable=True)
    # La parte de la llamada que corresponde a esta pregunta (el coste de una
    # llamada con varias preguntas se reparte a partes iguales). 0 en lo
    # servido de cache: es lo que no se ha vuelto a pagar.
    coste_usd = Column(Float, nullable=True)
    coste_estimado = Column(Boolean, nullable=True)
    # Por que quedo sin decidir: presupuesto_agotado, sin_credito, red...
    motivo = Column(String(32), nullable=True)
    # Lo que VIO el modelo: la revision de #8 tiene que ensenar eso y no lo
    # que hay hoy en la pagina. Es contenido que ya esta en nuestra BD.
    estado_enviado = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        Index("ix_decisions_job_pregunta", "job_id", "pregunta"),
        # FK con ON DELETE CASCADE: sin indice, borrar un rastreo recorre la
        # tabla entera por cada fila de `urls` (la leccion de `ix_issues_url_id`).
        Index("ix_decisions_url_id", "url_id"),
        Index("ix_decisions_cache", "clave", "pregunta", "version_pregunta", "modelo"),
        Index("ix_decisions_run_id", "run_id"),
        # La revision humana (decision 211); en una base ya creada lo pone
        # `init_db.migrar_enriquecido`.
        Index("ix_decisions_revision", "pregunta", "version_pregunta", "estado",
              postgresql_where=sql_text("origen IN ('modelo', 'cache')")),
    )


class DecisionLabel(Base):
    """La etiqueta HUMANA de una respuesta de Jev (#8, decision 211).

    Lo que cuenta en un juego de evaluacion: nunca la etiqueta de Jev. Una por
    (estado, pregunta, version, variante): el mismo estado en dos URLs o dos
    censos es la misma entrada para Jev y se etiqueta una vez; una version
    nueva de la pregunta se etiqueta otra vez (decision 180).

    Copia lo que se juzgo (`estado_enviado`, las opciones) y lo que dijo Jev:
    la etiqueta vale aunque se borre el censo del que salio, que es cuando
    `decision_id` pasa a NULL. Es contenido que ya esta en nuestra BD.
    """

    __tablename__ = "decision_labels"
    __table_args__ = (
        UniqueConstraint("clave", "pregunta", "version_pregunta", "variante",
                         name="uq_decision_label"),
        Index("ix_decision_labels_pregunta", "pregunta", "version_pregunta"),
    )

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    decision_id = Column(BigInteger, ForeignKey("decisions.id", ondelete="SET NULL"),
                         nullable=True, index=True)
    clave = Column(String(64), nullable=False)
    pregunta = Column(String(64), nullable=False)
    version_pregunta = Column(Integer, nullable=False)
    # La huella de las opciones del cliente (`Pregunta.variante`, decision
    # 178); "" en las del catalogo.
    variante = Column(String(16), nullable=False, default="")
    ambito = Column(String(10), nullable=False, default="url")
    estado_enviado = Column(JSON, nullable=True)
    opciones = Column(JSON, nullable=True)
    respuesta_jev = Column(Text, nullable=True)
    confianza_jev = Column(Float, nullable=True)
    # El modelo que dio `respuesta_jev`: la etiqueta humana vale para cualquier
    # modelo, pero su respuesta no. Al exportar solo va la del modelo actual.
    modelo_jev = Column(String(64), nullable=True)
    # En el vocabulario de la pregunta (`normalizar_etiqueta`): "true"/"false",
    # la opcion o el indice del nivel.
    etiqueta = Column(Text, nullable=False)
    nota = Column(Text, nullable=True)
    autor = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# ---------------------------------------------------------------------------
# Ejecuciones del analisis enriquecido (#40, decision 85)
# ---------------------------------------------------------------------------
class EnrichmentRun(Base):
    """Una pulsacion del boton «Analisis enriquecido»: que se pidio, sobre que
    URLs, con cuanto dinero y en que quedo.

    Es lo UNICO que dispara la capa de decisiones despues de un rastreo: la
    crea la API (con token, decision 85) y la ejecuta el worker desde su
    propia cola. Nunca se crea sola —ni al terminar un rastreo ni desde una
    programacion—.

    `modulos` guarda la lista YA RESUELTA, con las dependencias anadidas, para
    que reanudar tras un reinicio haga exactamente lo que se confirmo aunque
    el registro de modulos cambie entre medias. `estimacion` es lo que se
    enseño en el dialogo al confirmar: comparar con `gastado_usd` es la
    validacion del ±30% de #40.

    Estados: pendiente -> en_curso -> completada | parcial | cancelada |
    fallida. `cancelando` es la peticion de cancelar mientras corre: el worker
    la ve entre lotes y cierra como `cancelada` conservando lo pagado.
    `parcial` = se corto por presupuesto (de la ejecucion o mensual).
    """

    __tablename__ = "enrichment_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"),
                    nullable=False, index=True)
    modulos = Column(JSON, nullable=False, default=list)
    # {"carpeta": "/blog/", "max_urls": 500, "muestra": true}; vacio = todas
    # las HTML internas, 200 e indexables.
    alcance = Column(JSON, nullable=False, default=dict)
    estimacion = Column(JSON, nullable=True)
    presupuesto_usd = Column(Float, nullable=True)
    # Suma de `usage.cost` de lo que se ha pagado en esta ejecucion (o de la
    # estimacion por tokens si la respuesta no lo trae, marcado en
    # `decisions.coste_estimado`).
    gastado_usd = Column(Float, nullable=False, default=0.0)
    estado = Column(String(16), nullable=False, default="pendiente", index=True)
    # {"modulo": ..., "procesadas": n, "total": N, "por_modulo": {...}}
    progreso = Column(JSON, nullable=True)
    errores = Column(JSON, nullable=True)
    # Por que se paro (presupuesto_ejecucion, presupuesto_cliente, sin_credito...)
    motivo = Column(String(32), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    # Latido del worker: lo que distingue una ejecucion viva de una que se
    # quedo en `en_curso` porque un despliegue recreo el contenedor.
    latido_at = Column(DateTime(timezone=True), nullable=True)
