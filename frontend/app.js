/* ===== SEO Crawler Frontend — Alpine.js App ===== */

const API = '/api';

// Autenticacion (decision 134): un 401 de la API es que la sesion no existe o
// ha caducado. Se envuelve `fetch` y no solo `api()` porque hay descargas y
// subidas que lo llaman directamente; sin esto la pagina se quedaba en blanco
// con errores en la consola. `/api/sesion` no cuenta: es por donde se entra.
const _fetchSinSesion = window.fetch.bind(window);
window.fetch = async function (recurso, opciones) {
  const res = await _fetchSinSesion(recurso, opciones);
  const url = typeof recurso === 'string' ? recurso : (recurso && recurso.url) || '';
  if (res.status === 401 && /^(\/|https?:\/\/[^/]+\/)api\//.test(url)
      && !/\/api\/sesion/.test(url)) {
    irAEntrar();
  }
  return res;
};

function irAEntrar() {
  const volver = location.hash && location.hash.startsWith('#/') ? location.hash : '';
  location.replace('/entrar' + (volver ? '?volver=' + encodeURIComponent(volver) : ''));
}

async function salirDeLaSesion() {
  try { await _fetchSinSesion(API + '/sesion', { method: 'DELETE' }); } catch (_) { /* se sale igual */ }
  location.replace('/entrar');
}

/* ===== User-Agent presets ===== */
// Las cadenas de los bots son las que publica cada proveedor (comprobadas el
// 2026-10-16; decision 98). Google y Bing escriben `Chrome/W.X.Y.Z` y lo
// sustituyen por la version de Chromium/Edge que usan en cada momento: aqui va
// la estable de Chrome de esa fecha. Para robots.txt solo cuenta el TOKEN
// (`UA_TOKEN_ROBOTS`), que no cambia con la version.
const CHROME_EVERGREEN = '155.0.8059.84';
const UA_PRESETS = {
  // Los dos Chrome con la version de la huella TLS de serie (`chrome150`,
  // decision 132): `UA_POR_DEFECTO` de `shared/perfiles.py`, comprobado por test.
  chrome_win:  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
  chrome_mac:  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36',
  safari_mac:  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
  // Firefox con la version de un perfil de curl_cffi (`firefox147`): con la 124
  // la huella automatica salia de la 133 y el UA de la 124 (decision 132).
  firefox_win: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0',
  edge_win:    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0',
  // Un movil que es un navegador y no un bot (decision 173): `UA_CHROME_ANDROID`
  // de `shared/perfiles.py`, con la version de su huella TLS (`chrome131_android`)
  // para que la huella automatica case. Con el, el contexto de render es de
  // movil (412x915, DPR 2,625, tactil). Comprobado por test.
  chrome_android: 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36',
  // developers.google.com/search/docs/crawling-indexing/google-common-crawlers
  googlebot_mobile: `Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${CHROME_EVERGREEN} Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)`,
  // La cadena antigua de escritorio, sin Chrome: se conserva para que los
  // configs guardados con ella sigan casando con un preset.
  googlebot:   'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
  // blogs.bing.com/webmaster/april-2022/Announcing-user-agent-change-for-Bing-crawler-bingbot
  bingbot:     `Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm) Chrome/${CHROME_EVERGREEN} Safari/537.36`,
  // developers.openai.com/api/docs/bots
  gptbot:      'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; GPTBot/1.4; +https://openai.com/gptbot',
  oai_searchbot: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36; compatible; OAI-SearchBot/1.4; +https://openai.com/searchbot',
  // Anthropic publica el token (support.claude.com, articulo 8896518), no la
  // cadena entera: esta es la que se ve en los logs.
  claudebot:   'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; ClaudeBot/1.0; +claudebot@anthropic.com)',
  // docs.perplexity.ai/guides/bots
  perplexitybot: 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; PerplexityBot/1.0; +https://perplexity.ai/perplexitybot)',
};
// Los presets que llevan `CHROME_EVERGREEN` dentro. Al subir la constante, un
// cliente o un perfil guardado con la version anterior tiene que seguir
// reconociendose como ese preset —y relanzarse con la version de hoy, que es
// lo que hace el bot de verdad—, no caer a «Personalizado» con una cadena
// congelada. Es el mismo motivo por el que se conserva el `googlebot` antiguo.
const UA_PRESETS_EVERGREEN = ['googlebot_mobile', 'bingbot'];
const RE_VERSION_CHROME = /Chrome\/[0-9.]+/;
function presetDeUserAgent(ua) {
  if (!ua) return null;
  const exacto = Object.keys(UA_PRESETS).find(k => UA_PRESETS[k] === ua);
  if (exacto) return exacto;
  const sinVersion = s => s.replace(RE_VERSION_CHROME, 'Chrome/*');
  return UA_PRESETS_EVERGREEN.find(k => sinVersion(UA_PRESETS[k]) === sinVersion(ua)) || null;
}
const UA_LABELS = {
  chrome_win:  'Chrome - Windows',
  chrome_mac:  'Chrome - macOS',
  safari_mac:  'Safari - macOS',
  firefox_win: 'Firefox - Windows',
  edge_win:    'Edge - Windows',
  chrome_android: 'Chrome - Android (móvil)',
  googlebot_mobile: 'Googlebot smartphone',
  googlebot:   'Googlebot escritorio (cadena antigua)',
  bingbot:     'Bingbot',
  gptbot:      'GPTBot (OpenAI, entrenamiento)',
  oai_searchbot: 'OAI-SearchBot (búsqueda de ChatGPT)',
  claudebot:   'ClaudeBot (Anthropic)',
  perplexitybot: 'PerplexityBot',
  custom:      'Personalizado',
};
// El token de producto con que robots.txt agrupa las reglas de cada bot. Es lo
// que casa el parser (Protego) dentro de la cadena entera; se usa para avisar
// en el formulario y en `test_ua_presets.py`, que lo comprueba con el
// middleware de robots de verdad.
const UA_TOKEN_ROBOTS = {
  googlebot_mobile: 'Googlebot',
  googlebot:   'Googlebot',
  bingbot:     'bingbot',
  gptbot:      'GPTBot',
  oai_searchbot: 'OAI-SearchBot',
  claudebot:   'ClaudeBot',
  perplexitybot: 'PerplexityBot',
};

// El token de bot que lleva un User-Agent (de preset o escrito a mano), o ''.
function tokenDeBot(ua) {
  const texto = (ua || '').toLowerCase();
  const tokens = [...new Set(Object.values(UA_TOKEN_ROBOTS))];
  return tokens.find(t => texto.includes(t.toLowerCase())) || '';
}

/* ===== Traducciones ===== */
const STATUS_LABEL = {
  pending:   'Pendiente',
  running:   'En curso',
  analyzing: 'Analizando',
  completed: 'Completado',
  failed:    'Fallido',
  cancelled: 'Cancelado',
  deleting:  'Borrándose',
  vaciado:   'Vaciado',
};

const ISSUE_LABEL = {
  '4xx_error': 'Error 4xx',
  '5xx_error': 'Error 5xx',
  'connection_error': 'Error de conexión',
  'title_missing': 'Sin título',
  'title_too_short': 'Título muy corto',
  'title_too_long': 'Título muy largo',
  'title_duplicate': 'Título duplicado',
  'description_missing': 'Sin meta descripción',
  'description_too_short': 'Descripción muy corta',
  'description_too_long': 'Descripción muy larga',
  'description_duplicate': 'Descripción duplicada',
  'h1_missing': 'Sin H1',
  'h1_multiple': 'Múltiples H1',
  'h1_duplicate': 'H1 duplicado',
  'canonical_missing': 'Sin canonical',
  'canonical_cross_domain': 'Canonical externo',
  'canonical_broken': 'Canonical roto',
  'hreflang_missing_return': 'Hreflang sin retorno',
  'hreflang_invalid_lang': 'Hreflang idioma inválido',
  'hreflang_broken_target': 'Hreflang destino roto',
  'structured_data_error': 'Error datos estructurados',
  'structured_data_warning': 'Aviso datos estructurados',
  'structured_data_info': 'Resultado enriquecido retirado',
  'noindex_page': 'Página noindex',
  'robots_invalid_syntax': 'Meta robots mal escrito',
  'duplicate_content': 'Contenido duplicado',
  'near_duplicate_content': 'Contenido casi duplicado',
  'redirect_loop': 'Bucle de redirección',
  'redirect_chain': 'Cadena de redirecciones',
  'image_missing_alt': 'Imagen sin alt',
  'http_url': 'URL sin HTTPS',
  'mixed_content': 'Contenido mixto',
  'missing_hsts': 'Sin cabecera HSTS',
  'missing_csp': 'Sin política CSP',
  'missing_x_content_type_options': 'Sin X-Content-Type-Options',
  'missing_x_frame_options': 'Sin X-Frame-Options',
  'unsafe_crossorigin': 'Crossorigin inseguro',
  'low_word_count': 'Pocas palabras',
  'soft_404': 'Soft 404',
  'soft_404_candidato': 'Posible soft 404',
  'soft_404_plantilla': 'Plantillas que responden 200 a URLs que no existen',
  'very_low_text_ratio': 'Ratio texto muy bajo',
  'low_text_ratio': 'Ratio texto bajo',
  'url_too_long': 'URL muy larga',
  'url_non_ascii': 'URL con caracteres no ASCII',
  'url_uppercase': 'URL con mayúsculas',
  'url_underscores': 'URL con guiones bajos',
  'url_multiple_slashes': 'URL con barras múltiples',
  'url_has_parameters': 'URL con parámetros',
  'url_non_seo_friendly': 'URL no SEO-friendly',
  'url_cms_faceted': 'URL de filtro/CMS (crawl budget)',
  'orphan_page': 'Página huérfana',
  'high_outlink_count': 'Demasiados enlaces salientes',
  'sitemap_orphan': 'Huérfana (solo en sitemap)',
  'solo_enlazada_por_redireccion': 'Solo se llega por una redirección',
  'not_reachable_from_home': 'Sin camino de enlaces desde la home',
  'solo_enlazada_con_nofollow': 'Solo enlazada con nofollow',
  'pagina_nofollow': 'Página indexable con nofollow',
  'enlace_interno_nofollow': 'Enlaces internos nofollow',
  'not_in_sitemap': 'No incluida en el sitemap',
  'sitemap_no_indexable': 'En el sitemap sin ser indexable',
  'sitemap_supera_limite': 'Sitemap por encima del límite de Google',
  'lastmod_futuro': 'Sitemap con lastmod en el futuro',
  'en_varios_sitemaps': 'URL en varios ficheros de sitemap',
};

const SEVERITY_LABEL = { error: 'Error', warning: 'Aviso', info: 'Info' };

// Las categorias de la Puntuacion por su clave (revision de UX del 25-oct,
// 3.9): con tilde y sin emoji aunque la API sea anterior.
const NOMBRE_CATEGORIA = {
  crawlability: 'Rastreabilidad', content: 'Contenido', links: 'Enlaces', security: 'Seguridad',
  structured_data: 'Datos estructurados', i18n: 'Internacionalización',
};

const POSITION_LABEL = {
  nav: 'Navegación', footer: 'Pie de página', content: 'Contenido',
  header: 'Cabecera', sidebar: 'Lateral',
};

// Pestana Enlaces (revision de UX del 25-oct, 2.8; decision 195): filtros
// que entiende GET /links y /links/destinos, y como se dice el estado del
// destino. `sin_dato` no es «bien»: nadie lo comprobo.
const ENLACES_SIN_FILTROS = {
  destino: '', exacto: false, destino_hash: '', origen: '', ancla: '',
  tipo: '', follow: '', posicion: '', estado: '', codigo: '',
};
const ESTADO_DESTINO = {
  roto:           { texto: 'Roto', clase: 'badge-failed', tip: 'El destino responde con error (4xx o 5xx) o, si es externo, la sonda lo dio por roto.' },
  redireccion:    { texto: 'Redirige', clase: 'badge-cancelled', tip: 'El destino redirige a otra URL: el enlace debería apuntar a la final.' },
  no_concluyente: { texto: 'No concluyente', clase: 'badge-pending', tip: 'Se pidió, pero la respuesta no permite afirmar nada: un 403 o un 429 de un cortafuegos, un error del servidor que puede ser pasajero, un tiempo agotado.' },
  sin_dato:       { texto: 'Sin comprobar', clase: 'badge-pending', tip: 'Ni está en el censo ni se comprobó con la sonda de enlaces externos: fuera del alcance, excluida, bloqueada por robots.txt o con la sonda apagada.' },
  ok:             { texto: 'Bien', clase: 'badge-completed', tip: 'El destino responde bien (2xx).' },
};
const ESTADOS_DESTINO = ['roto', 'redireccion', 'no_concluyente', 'sin_dato', 'ok'];
// Lo que dijo la sonda de un enlace externo (shared/sondas.py, decision 123).
const VEREDICTO_SONDA = {
  ok: 'responde bien', roto: 'no existe (404 o 410)', redirige_a_error: 'redirige a una página de error',
  error_servidor: 'error del servidor, puede ser pasajero', no_verificable: 'el servidor no deja comprobarlo (403, 429…)',
  prohibido_por_robots: 'su robots.txt no deja comprobarlo', dominio_inexistente: 'el dominio no existe',
  sin_conexion: 'no acepta conexiones', tiempo_agotado: 'no respondió a tiempo', tls_invalido: 'certificado no válido',
};

// Pestanas de la ficha <-> tramo de la URL (#/rastreos/<id>/<tramo>)
const TAB_SLUG = {
  overview: 'resumen', issues: 'problemas', links: 'enlaces', insights: 'puntuacion',
  semantic: 'semantico', diff: 'comparar', enriquecido: 'ia', cleaning: 'limpieza',
  // Sin pestana propia: se llega desde el menu «…» del censo o desde Comparar
  // (revision de UX del 25-oct, 2.13).
  migracion: 'migracion',
};
// `informe` era el tramo de la pestana Puntuacion antes de la revision de UX
// del 25-oct, y `enriquecido` el de la pestana IA (2.9): los enlaces
// guardados siguen abriendolas.
const SLUG_TAB = { ...Object.fromEntries(Object.entries(TAB_SLUG).map(([k, v]) => [v, k])),
                   informe: 'insights', enriquecido: 'enriquecido' };

// Que tipo de problema contesta cada pregunta de la IA (revision de UX del
// 25-oct, 2.9): la linea «Revisado con IA» de Problemas. Solo las parejas en
// las que la pregunta juzga justo ese problema: los pares de la canibalizacion
// salen de los avisos `canibalizacion_por_consulta` (enriquecido_canibalizacion)
// y el soft 404 pregunta a sus candidatos, aunque tambien a paginas con poco
// texto que no estan en el aviso: por eso `porUrl` cruza URL a URL y cuenta
// solo las paginas del problema. Lo que no esta aqui no se relaciona: seria
// inventar que una respuesta habla de un problema que no pregunta.
// Que pregunta cada modulo del analisis enriquecido y a que paginas, para el
// lanzador (revision de UX del 25-oct, 2.9). Las claves son los nombres de
// shared/enriquecido.py; tests/test_ia_frontend.py comprueba que estan todos.
const EXPLICACION_MODULO_IA = {
  pagina_legal: 'Si la página es un aviso legal, de privacidad, de cookies o de condiciones. Es una pregunta de prueba, para comprobar que todo funciona, no para decidir nada. Pregunta a todas las indexables.',
  soft_404: 'Si la página dice que algo no existe (un error, un producto retirado, una búsqueda sin resultados, un «próximamente») aunque responda bien. Solo pregunta a las sospechosas: las que ya marcó el crawler y las de muy poco texto. Las respuestas son orientativas y no entran en ningún informe.',
  pagina_de_utilidad: 'Si la página es un paso de un proceso que nadie busca en Google: acceso, registro, «gracias», confirmación, baja, carrito. Pregunta a las mismas sospechosas que el soft 404. Orientativo: no entra en ningún informe.',
  canibalizacion: 'En las búsquedas para las que Search Console muestra varias páginas del sitio, compara esas páginas de dos en dos: si a quien busca le vale cualquiera y, si es así, qué hacer (unirlas, diferenciarlas, quedarse con una o dejarlas). Solo las búsquedas con más clics. Orientativo.',
  intencion_pagina: 'Qué resuelve cada página (informarse, comparar, comprar, llegar a una marca o a un local) y en qué momento de la compra está quien llega (descubriendo, comparando, decidiendo o ya cliente). Pregunta a las páginas con título, encabezado o texto. Orientativo.',
  intencion_busquedas: 'Qué buscaba la gente que llegó desde Google a cada página (sus búsquedas con más clics) y, junto con la anterior, si la página encaja con lo que buscan. Una búsqueda ya preguntada no se vuelve a pagar. Solo clientes con Search Console. Orientativo.',
  tipo_pagina: 'Qué es cada plantilla: portada, listado, ficha de producto o servicio, página comercial, artículo, contacto, ayuda, legal… Pregunta por unas pocas páginas de cada plantilla y propone la respuesta para toda ella. Orientativo: no se aplica a nada.',
  categoria_cliente: 'A cuál de las categorías de negocio del cliente pertenece cada plantilla, con unas pocas páginas de cada una. Si el cliente no tiene sus categorías en la configuración, no pregunta nada. Orientativo.',
  title_contenido: 'Si el title dice de qué va la página, en cuatro niveles. No pregunta por lo que ya resuelve una regla (sin title, title de relleno o repetido) ni por las páginas con muy poco texto, y tiene un tope por plantilla. Orientativo.',
  title_generico: 'Si el title, quitado el nombre de la marca, no dice qué página es («Detalle noticia», «SAT»). Solo pregunta por titles muy cortos, sin la portada ni los de relleno que ya detecta una regla, y con un tope por plantilla. Orientativo.',
  schema_visible: 'Si lo que se ve en la página contradice el precio, la valoración, la fecha o la disponibilidad de sus datos estructurados. Solo páginas con algo visible con lo que comparar, con un tope por plantilla. Que un dato no se vea no cuenta como contradicción. Orientativo.',
};

const PROBLEMA_PREGUNTA_IA = {
  canibalizacion_por_consulta: { pregunta: 'paginas_sustitutas', porUrl: false, unidad: ['par', 'pares'],
                                 si: 'compiten por la misma búsqueda', no: 'no compiten' },
  soft_404_candidato: { pregunta: 'es_soft_404', porUrl: true, unidad: ['página', 'páginas'],
                        si: 'sí es soft 404', no: 'no lo es' },
};

// Pestanas de la ficha del cliente (revision de UX del 25-oct, 2.1): Estado
// (la de entrada), Historial, Alertas y Configuracion. Los tramos viejos
// siguen abriendo: `rastreos` era la de las graficas y la tabla (hoy
// Historial) y `config` el nombre interno.
const CLIENTE_TAB_SLUG = { estado: 'estado', historial: 'historial', alertas: 'alertas', config: 'configuracion' };
const CLIENTE_TAB_ETIQUETA = { estado: 'Estado', historial: 'Historial', alertas: 'Alertas', config: 'Configuración' };
const CLIENTE_SLUG_TAB = { ...Object.fromEntries(Object.entries(CLIENTE_TAB_SLUG).map(([k, v]) => [v, k])),
                           rastreos: 'historial', config: 'config' };

// Helpers
// Respuestas de los choice del enriquecido, en castellano: el tipo de pagina
// (decision 178) y la intencion y el embudo (decision 176), que llegan en
// ingles como en el catalogo de preguntas.
const RESPUESTA_ENRIQ = {
  home: 'portada', listado: 'listado o categoría', ficha_producto: 'ficha de producto o servicio',
  landing_comercial: 'landing comercial', articulo: 'artículo', perfil: 'perfil (autor, persona)',
  corporativa: 'corporativa',
  contacto_ubicacion: 'contacto o ubicación', ayuda: 'ayuda, documentación o herramienta', legal: 'legal',
  utilidad: 'utilidad', otro: 'otro', ninguna: 'ninguna',
  informational: 'informacional', commercial: 'comercial', transactional: 'transaccional',
  navigational: 'navegacional (portada o marca)', local: 'local', unclear: 'no está claro',
  existing_users: 'para quien ya es cliente o alumno', corporate: 'corporativa / institucional',
  tofu: 'TOFU', mofu: 'MOFU', bofu: 'BOFU', post_purchase: 'postventa',
  out_of_funnel: 'fuera del embudo', sin_respuesta: 'sin respuesta',
};

const fmt = {
  // `useGrouping: 'always'`: en es-ES Intl no agrupa los numeros de cuatro
  // cifras, asi que la misma columna mezclaba `4319` con `15.026` (UX-14).
  num: n => n == null ? '—' : Number(n).toLocaleString('es-ES', { useGrouping: 'always' }),
  // Decimales fijos con coma y miles con punto: «841,2», «1.234,5». Los
  // porcentajes con espacio antes del signo, «32,1 %» (V42 y UX-14; revision
  // de UX del 25-oct, 3.9): salian «32.1%» y «841.2 KB» junto a cifras ya en
  // castellano. `pct` recibe el porcentaje (32.1) y `pctDe` la fraccion (0.321).
  dec: (n, d = 1) => n == null || n === '' || isNaN(n) ? '—'
    : Number(n).toLocaleString('es-ES', { minimumFractionDigits: d, maximumFractionDigits: d, useGrouping: 'always' }),
  pct: (n, d = 1) => n == null || n === '' || isNaN(n) ? '—' : fmt.dec(n, d) + ' %',
  pctDe: (x, d = 1) => x == null || x === '' || isNaN(x) ? '—' : fmt.pct(100 * x, d),
  // «1 página», «3 páginas»: la cifra con su nombre en singular o plural
  // (revision de UX del 25-oct, 3.9). Salia «1 rastreos no tienen cliente».
  n: (n, uno, varios) => fmt.num(n) + ' ' + (Number(n) === 1 ? uno : varios),
  // Tiempos de respuesta (milisegundos de una peticion).
  ms:  n => n == null ? '—' : n < 1000 ? Math.round(n) + ' ms' : (n/1000).toFixed(1).replace('.', ',') + ' s',
  // Lo que dura un rastreo. Antes salia por `ms` y un censo se leia
  // `14787.1s`: hay que hacer la division de cabeza para saber que son 4 h.
  lapso: ms => {
    if (ms == null || isNaN(ms) || ms < 0) return '—';
    const s = Math.round(ms / 1000);
    if (s < 60) return s + ' s';
    const m = Math.floor(s / 60);
    if (m < 60) return m + ' min' + (s % 60 ? ' ' + String(s % 60).padStart(2, '0') + ' s' : '');
    const h = Math.floor(m / 60);
    if (h < 24) return h + ' h' + (m % 60 ? ' ' + String(m % 60).padStart(2, '0') + ' min' : '');
    return Math.floor(h / 24) + ' d ' + (h % 24) + ' h';
  },
  date: d => d ? new Date(d).toLocaleString('es-ES', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—',
  dia: d => d ? new Date(d).toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric' }) : '—',
  // «19 oct» (y el año solo si no es el de hoy): la referencia de «frente al
  // anterior» se nombra por su fecha (revision de UX del 25-oct, 2.3).
  diaCorto: d => {
    if (!d) return '—';
    const f = new Date(d);
    const o = { day: 'numeric', month: 'short' };
    if (f.getFullYear() !== new Date().getFullYear()) o.year = 'numeric';
    return f.toLocaleDateString('es-ES', o);
  },
  ago: d => {
    if (!d) return '—';
    const s = Math.floor((Date.now() - new Date(d).getTime()) / 1000);
    if (s < 0)     return 'ahora';
    if (s < 60)    return 'hace ' + s + ' s';
    if (s < 3600)  return 'hace ' + Math.floor(s/60) + ' min';
    if (s < 86400) return 'hace ' + Math.floor(s/3600) + ' h';
    const dias = Math.floor(s/86400);
    if (dias === 1) return 'ayer';
    if (dias < 30) return 'hace ' + dias + ' días';
    return fmt.dia(d);
  },
  // La hora estimada de fin de un rastreo, redondeada a 5 min: una
  // estimacion con minutos exactos aparenta una precision que no tiene
  // (revision de UX del 25-oct, 2.12).
  hacia: d => {
    if (!d) return '';
    const r = new Date(Math.round(new Date(d).getTime() / 300000) * 300000);
    const hora = r.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
    const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
    const dia = new Date(r); dia.setHours(0, 0, 0, 0);
    const dias = Math.round((dia - hoy) / 86400000);
    if (dias <= 0) return 'hacia las ' + hora;
    if (dias === 1) return 'mañana hacia las ' + hora;
    return 'hacia el ' + r.toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'short' }) + ', a las ' + hora;
  },
  // «dentro de 3 h», «dentro de 6 días»: lo que falta para un disparo.
  dentroDe: d => {
    if (!d) return '';
    const s = Math.floor((new Date(d).getTime() - Date.now()) / 1000);
    if (s < 60) return 'en un momento';
    if (s < 3600) return 'dentro de ' + Math.floor(s / 60) + ' min';
    if (s < 86400) return 'dentro de ' + Math.floor(s / 3600) + ' h';
    // A partir de un dia, por dias de calendario (como fmt.hacia), no
    // redondeando horas: 28 h desde las 23:00 de un lunes es el miercoles,
    // no «mañana» (revision de 2.12).
    const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
    const dia = new Date(d); dia.setHours(0, 0, 0, 0);
    const dias = Math.round((dia - hoy) / 86400000);
    return dias === 1 ? 'mañana' : 'dentro de ' + dias + ' días';
  },
  // Una fecha en la zona horaria de la programacion, no en la del navegador:
  // «lun, 2 nov, 03:00». Va siempre con fmt.zona al lado (V44).
  enZona: (d, zona) => {
    if (!d) return '—';
    const op = { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' };
    try { return new Date(d).toLocaleString('es-ES', { ...op, timeZone: zona || 'Europe/Madrid' }); }
    catch (_) { return new Date(d).toLocaleString('es-ES', op); }
  },
  // «hora de Madrid» para Europe/Madrid; para otra zona, su ciudad.
  zona: z => {
    const zona = z || 'Europe/Madrid';
    if (zona === 'UTC' || zona === 'Etc/UTC') return 'hora UTC';
    return 'hora de ' + zona.split('/').pop().replaceAll('_', ' ');
  },
  // Por que se lanzo o no la ultima vez (`programaciones.ultimo_motivo`, que
  // escribe el worker con `toca_lanzar`). «toca» a secas no se entendia como
  // estado (V44); lo que no se reconoce se ensena tal cual.
  motivo: m => {
    if (!m) return '';
    if (m === 'toca') return 'lanzado a su hora';
    if (m.startsWith('toca (con ')) {
      const r = m.match(/con (?:(\d+) days?, )?(\d+):(\d+):\d+/);
      if (!r) return 'lanzado con retraso';
      const min = (+(r[1] || 0)) * 1440 + (+r[2]) * 60 + (+r[3]);
      return 'lanzado con ' + (min < 60 ? min + ' min' : fmt.lapso(min * 60000)) + ' de retraso';
    }
    if (m.startsWith('disparo perdido')) return 'no se lanzó: el worker llegó tarde a la hora y se espera al siguiente';
    if (m.startsWith('el rastreo anterior')) return 'no se lanzó: el rastreo anterior de esta programación seguía sin terminar';
    // revision de UX del 25-oct, 2.2: el vivo puede ser otro rastreo del perfil
    if (m.startsWith('su perfil ya tiene un rastreo')) return 'no se lanzó: su perfil ya tenía otro rastreo sin terminar (lanzado a mano o por otra programación)';
    if (m === 'todavia no toca') return 'todavía no le toca';
    if (m === 'sin proxima ejecucion calculada') return 'no se lanzó: no tenía calculada la próxima ejecución';
    // Colgadas de un perfil (decision 193)
    if (m === 'su perfil ya no existe') return 'no se lanzó: su perfil ya no existe';
    if (m === 'el perfil esta desactivado') return 'no se lanzó: el perfil está desactivado';
    if (m === 'el perfil no tiene semillas') return 'no se lanzó: el perfil no tiene semillas';
    // decision 209
    if (m === 'lanzada a mano') return 'lanzada a mano con «Lanzar ahora»';
    if (m.startsWith('no se pudo encolar')) return 'no se lanzó: la cola de rastreos no respondía';
    return m;
  },
  // Una expresion cron en castellano. Solo los patrones que se usan de
  // verdad (diario, semanal, quincenal, mensual, cada N horas); lo demas se
  // devuelve tal cual, que es mejor que una traduccion inventada.
  cron: expr => {
    if (!expr) return '—';
    const p = expr.trim().split(/\s+/);
    if (p.length !== 5) return expr;
    const [mi, h, dm, mes, ds] = p;
    const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];
    const num = x => /^\d+$/.test(x);
    if (!num(mi)) return expr;
    if (/^\*\/\d+$/.test(h) && dm === '*' && mes === '*' && ds === '*')
      return 'cada ' + h.slice(2) + ' h, en el minuto ' + mi;
    if (!num(h)) return expr;
    const hora = h.padStart(2, '0') + ':' + mi.padStart(2, '0');
    if (mes !== '*') return expr;
    if (dm === '*' && ds === '*') return 'cada día a las ' + hora;
    if (dm === '*' && /^[0-7](,[0-7])*$/.test(ds)) {
      const ds_ = ds.split(',').map(d => DIAS[+d]);
      return (ds_.length === 1 ? 'cada ' : '') + ds_.join(', ') + ' a las ' + hora;
    }
    if (dm === '*' && ds === '1-5') return 'de lunes a viernes a las ' + hora;
    if (ds === '*' && /^\d+(,\d+)*$/.test(dm))
      return 'el día ' + dm.split(',').join(' y ') + ' de cada mes a las ' + hora;
    return expr;
  },
  // Se corta en MB para el tamano de una pagina, pero un censo son cientos
  // de MB y la base entera 57 GB: con el tope en MB se leia «57344.0 MB», y
  // esa division la tenia que hacer de cabeza quien mira el panel.
  bytes: b => {
    if (b == null) return '—';
    if (b < 1024) return b + ' B';
    if (b < 1048576) return fmt.dec(b/1024) + ' KB';
    if (b < 1073741824) return fmt.dec(b/1048576) + ' MB';
    if (b < 1099511627776) return fmt.dec(b/1073741824) + ' GB';
    return fmt.dec(b/1099511627776) + ' TB';
  },
  status: s => STATUS_LABEL[s] || s,
  issue: t => ISSUE_LABEL[t] || ISSUE_LABEL_EXTRA[t] || t.replaceAll('_', ' '),
  // `issues.details` en castellano, para la tabla de Problemas. Antes se
  // pintaba el JSON tal cual («status_code: 404», «duplicate_urls: 276074»).
  detalles: d => {
    if (!d || typeof d !== 'object') return '';
    const partes = [];
    const corta = u => String(u).replace(/^https?:\/\/[^/]+/, '') || '/';
    // Sin etiqueta, el nombre del campo sin guiones bajos: mejor un nombre
    // tecnico que esconder el dato, pero no «content_word_count».
    const etiq = k => DETALLE_LABEL[k] || k.replaceAll('_', ' ');
    for (const [k, v] of Object.entries(d)) {
      if (v == null || v === '' || k === 'otro_dominio_registrable' || k === 'paginas_del_host') continue;
      // Accesibilidad (decision 174): el impacto ya va en castellano y el enlace, en la ficha.
      if (k === 'impacto_axe' || k === 'url_ayuda') continue;
      // Revision de UX del 25-oct, 2.7: claves que salian en crudo
      // («reparto_por clics», «urls: 2», «pct 100»). Lo interno no se ensena;
      // las listas dicen que hay dentro, no cuantas son.
      if (['reparto_por', 'content_hash', 'verdict', 'fuente'].includes(k)) continue;
      if (Array.isArray(v) && !v.length) continue;
      const pctDe = x => (x * 100).toFixed(x < 0.1 ? 2 : 1).replace('.', ',').replace(/,0+$/, '') + ' %';
      if ((k === 'urls' || k === 'compite_con') && Array.isArray(v) && v.length && typeof v[0] === 'object') {
        // canibalizacion_por_consulta: las URLs que compiten, con su parte
        const de = d.reparto_por === 'impresiones' ? 'de las impresiones' : 'de los clics';
        const una = (x, i) => corta(x.url) + (x.parte != null ? ` (${pctDe(x.parte)}${i === 0 ? ' ' + de : ''}`
          + (x.posicion != null ? ', posición ' + String(x.posicion).replace('.', ',') : '') + ')' : '');
        partes.push((k === 'urls' ? 'compiten ' : 'compite con ') + v.slice(0, 3).map(una).join(', ')
          + (v.length > 3 ? ` y ${v.length - 3} más` : ''));
        continue;
      }
      if (k === 'parte_propia') {
        partes.push('esta página se lleva el ' + pctDe(v) + (d.reparto_por === 'impresiones' ? ' de las impresiones' : ' de los clics'));
        continue;
      }
      if (k === 'ventana' && Array.isArray(v) && v.length === 2) {
        partes.push('del ' + fmt.diaCorto(v[0]) + ' al ' + fmt.diaCorto(v[1]));
        continue;
      }
      if (k === 'consulta' && typeof v === 'string') { partes.push('búsqueda «' + v + '»'); continue; }
      if (k === 'consultas' && Array.isArray(v)) {
        const c = v.map(x => x && (x.consulta || x)).filter(x => typeof x === 'string');
        if (c.length) partes.push('búsquedas «' + c.slice(0, 2).join('», «') + '»' + (c.length > 2 ? ` y ${c.length - 2} más` : ''));
        continue;
      }
      if (k === 'anclas' && Array.isArray(v)) {
        const a = v.filter(x => x && x.ancla != null);
        if (a.length) partes.push((a.length === 1 ? 'ancla ' : 'anclas ') + a.slice(0, 3).map(x => '«' + x.ancla + '»'
          + (x.paginas ? ` en ${fmt.num(x.paginas)} ${x.paginas === 1 ? 'página' : 'páginas'}` : '')).join(', ')
          + (a.length > 3 ? ` y ${a.length - 3} más` : ''));
        continue;
      }
      // ancla_generica: «3 de 3» ya lo dice; el % solo si falta alguno
      if (k === 'pct' && typeof v === 'number') { if (d.con_ancla_generica == null) partes.push(fmt.num(Math.round(v)) + ' %'); continue; }
      if (['ctr', 'ctr_esperado', 'ctr_top3_del_sitio'].includes(k) && typeof v === 'number') {
        partes.push(etiq(k) + ' ' + pctDe(v)); continue;
      }
      if (k === 'tipo' && TIPO_SIN_ANCLA[v]) { partes.push(TIPO_SIN_ANCLA[v]); continue; }
      if (k === 'motivos' && Array.isArray(v)) {
        partes.push(v.map(m => MOTIVO_DETALLE[m] || String(m).replaceAll('_', ' ')).join(', ')); continue;
      }
      if (k === 'fuentes' && Array.isArray(v)) {
        partes.push(`${fmt.num(v.length)} ${v.length === 1 ? 'página que podría enlazarla' : 'páginas que podrían enlazarla'}`); continue;
      }
      if (k === 'cadena' && Array.isArray(v)) { partes.push(`${v.length - 1} saltos`); continue; }
      if (k === 'ejemplo_origen') { partes.push('p. ej. desde ' + corta(v)); continue; }
      if (k === 'plantillas' && Array.isArray(v) && v.length && v[0] && 'sonda' in v[0]) {
        // soft_404_plantilla (decision 190): que plantillas responden 200.
        const nombres = [...new Set(v.map(p => nombreDePlantilla(p.plantilla)))];
        partes.push(fmt.num(v.length) + (v.length === 1 ? ' plantilla responde' : ' plantillas responden') + ' 200 a URLs que no existen: '
          + nombres.slice(0, 3).join(', ') + (nombres.length > 3 ? ` y ${nombres.length - 3} más` : ''));
        continue;
      }
      if ((k === 'plantillas_afectadas' || k === 'raiz') && Array.isArray(d.plantillas)) continue;
      if (k === 'validation_issues' && Array.isArray(v)) {
        partes.push(v[0] + (v.length > 1 ? ` (y ${v.length - 1} más)` : ''));
      } else if (k === 'duplicate_urls' && Array.isArray(v)) {
        if (d.duplicate_count == null) partes.push(`${fmt.num(v.length + 1)} páginas en el grupo`);
      } else if (k === 'matches' && Array.isArray(v)) {
        if (v.length) partes.push('se parece a ' + corta(v[0].url || v[0]) + (v.length > 1 ? ` y ${v.length - 1} más` : ''));
      } else if (k === 'chain' && Array.isArray(v)) {
        partes.push(`${v.length - 1} saltos`);
      } else if (k === 'closest_similarity' || k === 'similarity') {
        partes.push(`similitud ${Math.round(v * 100)} %`);
      } else if (k === 'threshold') {
        continue;
      } else if (k === 'alcance') {
        partes.push(v === 'plantilla' ? 'de plantilla' : 'en esta página');
      } else if (k === 'tipo' && TIPO_NO_RASTREABLE[v]) {
        partes.push(TIPO_NO_RASTREABLE[v]);
      } else if (k === 'por_tipo' && typeof v === 'object') {
        partes.push(Object.entries(v).map(([t, n]) => `${TIPO_NO_RASTREABLE[t] || t} ${fmt.num(n)}`).join(', '));
      } else if (k === 'destino_rastreado' || k === 'destino_indexable') {
        if (v === false) partes.push(k === 'destino_rastreado' ? 'destino sin rastrear' : 'destino no indexable');
        else if (v === true && k === 'destino_indexable') partes.push('destino indexable');
      } else if (['ejemplos', 'paginas_ejemplo', 'ejemplos_origen'].includes(k) && Array.isArray(v)) {
        const e = v[0];
        if (e == null) continue;
        const txt = typeof e === 'string' ? corta(e)
          : e.url ? corta(e.url) + (e.status_code ? ` (${e.status_code})` : '')
          : (e.destino ? corta(e.destino) : (e.href || ''));
        if (txt) partes.push('p. ej. ' + (txt.length > 70 ? txt.slice(0, 70) + '…' : txt));
      } else if (['canonical', 'href', 'image_url', 'target', 'redirect_url', 'destino', 'href_ejemplo', 'destino_ejemplo'].includes(k)) {
        partes.push(etiq(k) + ' ' + (String(v).length > 70 ? String(v).slice(0, 70) + '…' : v));
      } else if (k === 'canonical_host') {
        if (!d.canonical) partes.push('a ' + v);
      } else if (k === 'inspeccionada' || k === 'ultimo_rastreo_google') {
        // Fechas de la inspeccion de Google: «19 oct», no el ISO entero.
        partes.push(etiq(k) + ' ' + (/^\d{4}-\d\d-\d\d/.test(v) ? fmt.diaCorto(v) : v));
      } else if (k === 'target_status') {
        partes.push(`el destino responde ${v}`);
      } else if (k === 'clase') {
        partes.push(fmt.claseRespuesta(v));
      } else if (k === 'codigos' && typeof v === 'object' && !Array.isArray(v)) {
        // respuesta_no_valida: lo que distingue un 429 de un 403 (decision 103)
        const cods = Object.entries(v).map(([c, n]) => `${c === 'null' ? 'sin código' : c} × ${fmt.num(n)}`);
        if (cods.length) partes.push('códigos ' + cods.join(', '));
      } else if (Array.isArray(v)) {
        partes.push(`${etiq(k)}: ${v.length}`);
      } else if (typeof v === 'object') {
        continue;
      } else if (typeof v === 'boolean') {
        if (v) partes.pushetiq(k);
      } else {
        partes.push(`${etiq(k)} ${typeof v === 'number' ? fmt.num(v) : v}`);
      }
    }
    return partes.join(' · ');
  },
  // Analisis enriquecido (#40)
  // Con coma decimal, como el resto de cifras (revision de UX del 25-oct, 2.9).
  usd: n => n == null ? '—' : (n === 0 ? '0 $' : Number(n).toLocaleString('es-ES',
    n < 0.01 ? { maximumSignificantDigits: 2 } : { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: 'always' }) + ' $'),
  duracion: s => s == null ? '—' : s < 60 ? s + ' s' : s < 3600 ? Math.ceil(s / 60) + ' min' : fmt.dec(s / 3600) + ' h',
  estadoEnriq: e => ({ pendiente: 'En cola', en_curso: 'En curso', cancelando: 'Cancelando…',
    completada: 'Completada', parcial: 'Parcial (presupuesto)', cancelada: 'Cancelada', fallida: 'Fallida' })[e] || e,
  colorEnriq: e => ({ completada: 'var(--green)', parcial: 'var(--orange)', fallida: 'var(--red)',
    cancelada: 'var(--text-dim)', cancelando: 'var(--orange)' })[e] || 'var(--accent)',
  motivoEnriq: m => ({ presupuesto_ejecucion: 'se agotó el presupuesto de la ejecución',
    presupuesto_cliente: 'se agotó el tope mensual del cliente', presupuesto_global: 'se agotó el tope mensual de todos los clientes',
    presupuesto_sin_contador: 'sin contador de gasto no se puede garantizar el tope', max_llamadas: 'tope de llamadas',
    sin_credito: 'sin crédito en OpenRouter', clave_invalida: 'clave de OpenRouter inválida',
    desactivado: 'capa desactivada en el worker', cancelada: 'cancelada a mano' })[m] || m,
  // Sin recorte, cada modulo pregunta a SUS candidatas (el soft 404, a las
  // sospechosas); «todas las indexables» decia 3.216 para 17 URLs (V32).
  alcanceEnriq: a => {
    const partes = [];
    if (a && a.carpeta) partes.push('carpeta ' + a.carpeta);
    if (a && a.muestra) partes.push('muestra de ' + fmt.num(a.max_urls));
    else if (a && a.max_urls) partes.push('máx. ' + fmt.num(a.max_urls) + ' URLs');
    return partes.join(', ') || 'las candidatas de cada módulo';
  },
  respuestaEnriq: r => r === 'true' ? 'sí' : r === 'false' ? 'no' : (RESPUESTA_ENRIQ[r] || r),
  estadoPlantillaEnriq: e => ({ propagable: 'propagable', orientativa: 'orientativa',
    mixta: 'mixta: las muestras no coinciden', sin_respuesta: 'sin respuesta' })[e] || e,
  // Lo que cuenta `total`: una fila de `intencion_busqueda` es una busqueda de
  // una pagina (decision 176); el resto, respuestas (un grupo en la 175).
  unidadEnriq: r => r.ambito === 'busqueda' ? 'búsquedas (página × búsqueda)' : 'respuestas',
  // Por que no se afirma el desajuste de una pagina (decision 176).
  sinAfirmarEnriq: m => ({
    pagina_de_marca: 'Página de marca: sus búsquedas (las de marca) no cuentan, no se puede comparar.',
    manda_la_marca: 'La mayoría de sus clics son de marca: no se afirma desajuste.',
    pagina_sin_intencion: 'Sin intención de página clara.',
    pagina_sin_equivalente: 'Página para usuarios existentes o corporativa: ninguna búsqueda tiene esa intención, no se compara.',
    sin_clics_que_cuenten: 'Ningún clic de búsquedas que cuenten.',
  })[m] || '',
  campoDiff: c => ({
    status_code: 'Código de respuesta',
    indexability_status: 'Indexabilidad',
    canonical_href: 'Canonical',
    title: 'Título',
    h1: 'H1',
    word_count: 'Palabras (cambio de más del 20 %)',
    // Decision 131: con los mismos umbrales que las alertas
    meta_description: 'Meta description',
    sd_tipos: 'Tipos de datos estructurados',
    hreflang: 'Idiomas del hreflang',
    inlinks: 'Páginas que la enlazan (la mitad, y 10 o más)',
    click_depth: 'Clics desde la home (2 o más, o sin camino)',
    pagerank_score: 'PageRank 0-100 (25 puntos o más, una década)',
  }[c] || c),
  // Si lo que llego era la pagina o un muro delante (decision 103).
  claseRespuesta: c => ({
    contenido: 'La página',
    challenge_waf: 'Desafío de un WAF',
    captcha: 'Captcha',
    rate_limited: 'Límite de peticiones (429)',
    respuesta_binaria: 'Cuerpo binario ilegible',
    login_requerido: 'Pide iniciar sesión',
    desconocido: 'Cuerpo vacío',
  }[c] || (c ? c : '—')),
  // El titular de cada alerta, en castellano llano: quien abre esto quiere
  // saber que ha pasado, no el nombre de la regla.
  reglaDiff: r => ({
    canonical_a_otro_host: 'El canonical se ha ido a otro host',
    canonical_a_otra_url: 'Páginas canonicalizadas a otra URL',
    rotas: 'Páginas que ahora responden con error',
    salen_del_indice: 'Páginas que han salido del índice',
    redirigidas: 'Páginas que ahora redirigen',
    pierden_contenido: 'Páginas que han perdido texto',
    cambia_el_titulo: 'Páginas que han cambiado de título',
    desaparecen: 'Páginas que ya no se encuentran en el sitio',
    entran_en_el_indice: 'Páginas que han entrado en el índice',
    // Decision 131
    se_alejan_de_la_home: 'Páginas que se han alejado de la home',
    pierden_enlaces_internos: 'Páginas que han perdido enlaces internos',
    pierden_pagerank: 'Páginas que han perdido PageRank',
    pierden_datos_estructurados: 'Páginas que han perdido datos estructurados',
    pierden_hreflang: 'Páginas que han perdido idiomas del hreflang',
    cambia_la_description: 'Páginas que han cambiado de meta description',
    // Extraccion a medida (decision 127): el nombre de la regla va al lado
    extraido_cambia: 'Cambia el valor extraído',
    extraido_desaparece: 'El valor extraído ya no aparece',
    extraido_aparece: 'Aparece un valor extraído que antes no estaba',
    busqueda_deja_de_contener: 'Páginas que ya no contienen lo buscado',
    busqueda_pasa_a_contener: 'Páginas que ahora contienen lo buscado',
  }[r] || r),
  // Titulo de una alerta de la comparacion: la regla y, si es de la
  // extraccion a medida, sobre que regla del consultor (decision 127).
  tituloAlerta: al => fmt.reglaDiff(al.regla) + (al.extraccion ? ' · «' + al.extraccion + '»' : ''),
  // Lo que resume una alerta de extraccion en una linea: la variacion de un
  // numero o las transiciones de un texto («InStock → OutOfStock: 2.300»).
  detalleAlerta: al => {
    if (al.variacion) {
      const v = al.variacion;
      return 'Suben ' + fmt.num(v.suben) + ', bajan ' + fmt.num(v.bajan)
        + (v.mediana_pct !== null && v.mediana_pct !== undefined ? ' · variación mediana ' + (v.mediana_pct > 0 ? '+' : '') + fmt.num(v.mediana_pct) + ' %' : '');
    }
    if (al.transiciones && al.transiciones.length) {
      return al.transiciones.slice(0, 3).map(t => (t.antes || '—') + ' → ' + (t.ahora || '—') + ': ' + fmt.num(t.paginas)).join(' · ');
    }
    return '';
  },
  // El color de una alerta sale de SU severidad. La tarjeta de la ficha
  // llevaba el rojo fijo, asi que un aviso se pintaba como una critica: si
  // todo es rojo, el rojo no significa nada.
  colorSeveridad: s => ({
    critical: 'var(--red,#d32f2f)',
    warning: 'var(--orange,#e67e22)',
    info: 'var(--blue,#2979b5)',
  }[s] || 'var(--text-dim)'),
  severity: s => SEVERITY_LABEL[s] || s,
  position: p => POSITION_LABEL[p] || p || '—',
};

// El `detail` de un error de validacion de FastAPI (422) es una LISTA de
// objetos, no una cadena: `new Error(lista)` daba literalmente
// "[object Object]". Le pasaba a cualquier error de validacion de toda la
// aplicacion, asi que el mensaje que el servidor se molesta en redactar
// —«'todos los lunes' no es una expresion cron valida…»— no llegaba nunca a
// quien lo necesitaba.
function mensajeDeError(err) {
  const d = err && err.detail;
  if (!d) return 'Error en la peticion';
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    return d.map(e => {
      // `loc` es ['body', 'cron']: interesa el campo, no que venga del cuerpo.
      const campo = (e.loc || []).filter(x => x !== 'body').join('.');
      const texto = (e.msg || '').replace(/^Value error,\s*/, '');
      return campo ? `${campo}: ${texto}` : texto;
    }).join(' · ');
  }
  return typeof d === 'object' ? JSON.stringify(d) : String(d);
}


// Lo que dice una API anterior cuando aun no tiene una ruta: FastAPI
// responde «Not Found» o «Method Not Allowed», y el servidor de estaticos
// devuelve la pagina (HTML) a una ruta de /api que no conoce. Salia en
// pantalla «Method Not Allowed» o «Unexpected token '<'…» (revision del
// 27-oct): se dice en castellano. `sinRuta` deja al que llama distinguirlo.
const SIN_RUTA = 'Este servidor todavía no tiene esta función: es una versión anterior.';

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const crudo = typeof (err && err.detail) === 'string' ? err.detail : '';
    if (res.status === 405 || (res.status === 404 && (crudo === 'Not Found' || !crudo))) {
      const e = new Error(SIN_RUTA);
      e.sinRuta = true;
      throw e;
    }
    throw new Error(mensajeDeError(err));
  }
  if (res.status === 204) return null;
  const tipo = (res.headers && res.headers.get && res.headers.get('content-type')) || '';
  if (tipo.includes('text/html')) {
    const e = new Error(SIN_RUTA);
    e.sinRuta = true;
    throw e;
  }
  return res.json();
}


// --- Cuando se repite una programacion, en lenguaje llano (revision de UX
// del 25-oct, 2.2 y V44) ----------------------------------------------------
// El formulario pide frecuencia, dia y hora; la expresion cron solo se ve en
// «Otra frecuencia», para lo que no cabe en las cuatro de siempre.
const DIAS_PROGRAMACION = [[1, 'lunes'], [2, 'martes'], [3, 'miércoles'], [4, 'jueves'],
                     [5, 'viernes'], [6, 'sábado'], [0, 'domingo']];

function _cuandoDesdeCron(cron) {
  const c = (cron || '').trim();
  const p = c.split(/\s+/);
  const base = { frecuencia: 'avanzada', dia: 1, diaMes: 1, hora: '03:00', cron: c };
  if (p.length !== 5 || !/^\d+$/.test(p[0]) || !/^\d+$/.test(p[1]) || p[3] !== '*') return base;
  const hora = p[1].padStart(2, '0') + ':' + p[0].padStart(2, '0');
  if (p[2] === '*' && p[4] === '*') return { ...base, frecuencia: 'diaria', hora };
  if (p[2] === '*' && /^[0-7]$/.test(p[4])) return { ...base, frecuencia: 'semanal', dia: (+p[4]) % 7, hora };
  if (p[2] === '1,15' && p[4] === '*') return { ...base, frecuencia: 'quincenal', hora };
  if (/^\d+$/.test(p[2]) && +p[2] >= 1 && +p[2] <= 28 && p[4] === '*')
    return { ...base, frecuencia: 'mensual', diaMes: +p[2], hora };
  return base;
}

function _cronDesdeCuando(f) {
  if (f.frecuencia === 'avanzada') return (f.cron || '').trim();
  const [h, m] = (f.hora || '03:00').split(':').map(x => String(+x || 0));
  if (f.frecuencia === 'diaria') return `${m} ${h} * * *`;
  if (f.frecuencia === 'semanal') return `${m} ${h} * * ${f.dia}`;
  if (f.frecuencia === 'quincenal') return `${m} ${h} 1,15 * *`;
  return `${m} ${h} ${f.diaMes || 1} * *`;
}

function _mismasSemillas(a, b) {
  const A = new Set((a || []).map(s => s.trim()).filter(Boolean));
  const B = new Set((b || []).map(s => s.trim()).filter(Boolean));
  return A.size > 0 && A.size === B.size && [...A].every(x => B.has(x));
}


/* ===== Main App ===== */
function app() {
  return {
    ...extraccionUI(),   // pestaña «Extracción» del modal (#34, decision 166)
    ...robotsPruebaUI(), // robots.txt de prueba en el resumen (decision 171)
    ...migracionUI(),    // «Validar migración» (revision de UX del 25-oct, 2.13; decision 192)
    // Navegacion
    view: 'jobs',
    programaciones: [],
    // Produccion (revision de UX del 25-oct, 2.12): lo que corre, lo que
    // espera y lo que va a dispararse, en una sola vista. `cola` es el orden
    // real de Redis (GET /jobs/cola) o null si no se sabe; `muestras` guarda
    // por job las cuentas vistas en cada refresco, para medir el ritmo.
    prod: { estado: 'cargando', error: '', enCurso: [], enCola: [], cola: null,
            progreso: {}, muestras: {}, sinCliente: null },
    prodTimer: null,
    programarAbierto: false,
    programarNombre: '',
    programarCron: '0 3 * * 1',
    programarZona: 'Europe/Madrid',
    programarError: '',
    // Formulario de una programacion colgada de un perfil (revision de UX del
    // 25-oct, 2.2): nueva o editada, desde Programados o desde el perfil.
    progForm: null,
    diasProgramacion: DIAS_PROGRAMACION,
    // Las programaciones del cliente abierto, para enseñarlas en sus perfiles.
    clienteProgramaciones: [],
    // Alta guiada de cliente (2.14): nombre y dominio; al crearlo, su id
    // queda en `altaReciente` para que Estado enseñe el siguiente paso.
    altaForm: null,
    altaReciente: null,
    // «canario» o «censo» cuando el modal de lanzar se abre desde el
    // siguiente paso: destaca el boton que toca.
    createSugerencia: '',
    cadencias: [
      { etiqueta: 'Cada día',      cron: '0 3 * * *' },
      { etiqueta: 'Cada lunes',    cron: '0 3 * * 1' },
      { etiqueta: 'Cada 15 días',  cron: '0 3 1,15 * *' },
      { etiqueta: 'Cada mes',      cron: '0 3 1 * *' },
    ],
    theme: document.documentElement.dataset.theme || 'light',
    menuAbierto: '',
    dialogo: null,            // { titulo, mensaje, aceptar, peligro, escribir, entrada, solo_aviso }
    editarJob: null,          // { name, tipo, cliente_id } mientras el dialogo esta abierto
    editarError: '',          // '' | 'app' | 'exportar' | 'mas'
    urlDetailId: null,
    // Ultima consulta del Explorador de este rastreo ({ job, qs }): la pestana
    // URLs y la miga «URLs» vuelven a ella con sus filtros y su pagina
    // (revision de UX del 25-oct, 2.6).
    _expUltimo: null,
    _aplicandoRuta: false,
    _rutaNueva: false,
    loading: false,
    error: null,

    // Toast notifications
    toasts: [],

    // Lista de trabajos
    jobs: [],
    jobsPage: 1,
    jobsPages: 1,
    jobsTotal: 0,
    jobsFilter: '',
    jobsBuscar: '',
    jobsCliente: '',          // id de cliente | 'ninguno' | ''
    jobsTipo: '',

    // Borrado en masa (decision 96). La seleccion se guarda por id y NO se
    // limpia al cambiar de pagina o de filtro: la limpieza tipica es «todas
    // las pruebas viejas», que no caben en una pagina de 20. Lo que evita
    // borrar a ciegas no es olvidar la seleccion, es que el dialogo liste
    // nombre a nombre lo que se va.
    jobsSel: {},
    borrado: null,            // {paso, previa, resultado, escribir, forzar, vueltas}
    almacenamiento: null,
    verAlmacenamiento: false,

    // Clientes (#36)
    clientes: [],
    panelClientes: null,
    clientesEstado: 'cargando',  // 'cargando' | 'ok' | 'error'
    clientesError: '',
    clienteSerie: [],
    serieSoloCensos: true,
    // Evolucion por perfil (decision 130): la respuesta de /evolucion y la
    // serie elegida en el desplegable.
    clienteEvolucion: null,
    evolucionClave: null,
    // Ultimo trafico de Google entre censos de cada perfil (decision 165):
    // GET /clients/{id}/trafico, con las frases ya redactadas por el servidor.
    clienteTrafico: [],
    cliente: null,
    clienteTab: 'estado',
    // Pestana Estado (revision de UX del 25-oct, 2.1): el ultimo censo con
    // sus cifras, lo primero que arreglar y lo que cambio frente al anterior.
    // `alertasAbiertas` va aparte de `incidentes` (la lista de la pestana
    // Alertas, que puede estar en «Cerrados»).
    estadoCliente: null,      // { jobId, job, stats, principales, error }
    alertasAbiertas: null,    // GET /clients/{id}/incidentes?estado=vivos
    _reglasDe: null,          // cliente cuyas reglas estan cargadas en `reglasForm`
    // Reglas de alerta y resumen semanal del cliente (decision 135)
    reglasCliente: null,      // GET /clients/{id}/reglas
    reglasForm: null,         // copia editable de `efectivas`
    _reglasFoto: '',          // `reglasForm` tal cual se cargo o guardo (cambios sin guardar, 3.5)
    incidentes: null,         // GET /clients/{id}/incidentes (decision 139)
    // Search Console del cliente (decision 141)
    gsc: { estado: null, llaves: [], llave: '', nombreNueva: '', propiedades: null, propiedad: '', error: '', ocupado: false },
    // Backlinks del cliente en CSV (#31, decision 212)
    backlinks: { lista: null, fichero: null, fecha: '', ocupado: false, error: '', ultimo: null },
    // Logs del servidor (#35, decision 213)
    logsSrv: { lista: null, fichero: null, formato: 'combined', regex: '', host: '', ocupado: false, error: '' },
    // Slack del cliente (decision 149)
    slack: { estado: null, tokens: [], token: '', nombreNuevo: '', tokenTexto: '', canales: null, canal: '', canalNombre: '',
             alertas: true, resumen: true, informe: true, error: '', ocupado: false, prueba: null },
    incidentesVer: 'vivos',
    reglasError: '',
    reglasPrueba: null,       // POST /clients/{id}/reglas/probar
    resumenes: [],
    resumenPrevia: null,
    clienteForm: _formCliente(null),
    clienteError: '',
    clientePerfiles: [],
    clienteJobs: [],
    perfilForm: null,
    perfilError: '',
    _perfilFoto: '',          // el formulario del perfil al abrirlo (cambios sin guardar, 3.5)
    _perfilCfgBase: null,     // la config propia del perfil al abrirlo
    guardandoCambios: false,  // la barra «Cambios sin guardar · Guardar» esta guardando

    // Modal de creacion
    showCreate: false,
    createPerfiles: [],
    createForm: _freshForm(),
    creating: false,
    createError: null,
    createExtraccionAbierta: false,
    // Configuracion en tres niveles (decision 196): una instancia del mismo
    // formulario por nivel (`cfgNuevo`).
    cfgRastreo: null,
    cfgCliente: null,
    cfgPerfil: null,
    cfgClienteGuardando: false,
    asiPerfiles: {},          // perfil -> { nivel: 'vista', resuelta } de «Así rastreará»
    // Ajustes de la agencia (revision de UX del 25-oct, 2.5)
    ajustes: null,
    // «Revisar a Jev» (#8, decision 211): a ciegas, lo de Jev se ve al guardar.
    revision: { resumen: [], pregunta: '', items: [], resultado: null, nota: '', autor: '', cargando: false, enviando: false },

    // Detalle del trabajo
    job: null,
    detailTab: 'overview',
    stats: null,
    progressTimer: null,
    progress: null,

    // Pestana Puntuacion (antes «Informe SEO»)
    insights: null,
    insightsLoading: false,
    expandedCategories: {},
    recUrls: {},      // { "rec-title": { loading, urls, loaded } }
    recUrlsOpen: {},  // { "rec-title": bool }

    // Pestana URLs
    urls: [], urlsPage: 1, urlsPages: 1, urlsTotal: 0,
    urlFilters: { status_group: '', is_internal: '', resource_type: '' },

    // Pestana Problemas
    issues: [], issuesPage: 1, issuesPages: 1, issuesTotal: 0,
    issuesResumen: null,      // una fila por tipo (/issues/resumen)
    // Version del analisis del censo con el que se comparo (2.10): { jobId,
    // version, error }. Hace falta para saber si la diferencia por tipo sigue
    // siendo la de los dos censos tal como estan ahora.
    versionAnterior: null,
    // Cuenta por tipo de este censo sin filtro de seccion ({ jobId, porTipo }):
    // para comprobar que sus incidencias siguen siendo las comparadas (2.10).
    cuentaSinFiltro: null,
    informe: null,            // GET /jobs/{id}/informe (decision 138)
    compartido: null,         // modo /c/<token> (decision 143): {token, cliente, censos, elegido}
    enlaces: null,            // enlaces de solo lectura del cliente (decision 143)
    enlaceNuevo: null,        // el que se acaba de crear: el unico momento en que se ve el token
    informeCargando: false,
    // 'prioridad' (gravedad x importancia de las paginas, decision 136) o
    // 'gravedad'. De serie, prioridad: es el orden de «Qué arreglar primero»
    // del Resumen, y los dos sitios tienen que decir lo mismo (revision de UX
    // del 25-oct, 1.2).
    issuesOrden: 'prioridad',
    principales: null,        // { jobId, filas }: «Qué arreglar primero» del Resumen
    _fichaPendiente: null,    // { jobId, url }: abrirFichaDeCenso
    issuesSegmento: '',       // segmento elegido en Problemas (decision 125)
    issuesVista: 'tipos',     // 'tipos' | 'lista'
    grupoAbierto: {},
    ISSUE_INFO,
    ESTADOS_DESTINO, POSITION_LABEL,
    issueFilters: { severity: '', issue_type: '' },

    // Pestana Enlaces
    links: [], linksPage: 1, linksPages: 1, linksTotal: 0,
    // Filtros en el servidor y vista por destino (revision de UX del 25-oct,
    // 2.8; decision 195). `linksFiltra`: null = aun no se sabe, false = la
    // API no filtra (una anterior a la 195): se avisa y se ensena la lista.
    linksVista: 'destinos',
    linksFiltros: { ...ENLACES_SIN_FILTROS },
    linksOrden: '',
    linksPorEstado: null,
    linksFiltra: null,
    linksCargando: false,
    linksError: '',
    linksDestinoUrl: '',
    _linksPet: 0,
    _linksTecla: null,
    // «Externas» del Explorador (V25): destinos externos enlazados, que el
    // censo no rastrea. null = no se sabe (API anterior o aun cargando).
    expExternasEnlazadas: null,

    // Pestana Semantico
    semanticResults: null,
    semanticLoading: false,
    semanticError: null,
    semanticSubTab: 'rings',
    semanticProgress: null,
    semanticPollTimer: null,
    semanticAlpha: 0.6,
    semanticBeta: 0.4,
    semanticThreshold: 0.92,
    gscAccounts: [],
    geminiAccounts: [],
    semanticGeminiAccountId: '',
    showGeminiModal: false,
    geminiFormName: '',
    geminiFormKey: '',
    geminiFormError: null,
    semanticGscAccountId: '',
    semanticGscProps: [],
    semanticGscProp: '',
    semanticGscDays: '90',
    gscPropsLoading: false,
    gscFetchLoading: false,
    gscFetchResult: null,
    showGscUploadModal: false,
    gscUploadName: '',
    gscUploadFile: null,
    cannibalPairs: [],
    cannibalLoading: false,
    cannibalBrand: '',
    cannibalHasQueryData: false,
    cannibalFilter: 'all',
    driftData: [],
    driftLoading: false,
    gapTopic: '',
    gapExclude: '',
    gapResults: null,
    gapLoading: false,
    targetTheme: '',
    targetResults: null,
    targetLoading: false,

    // Pestana Limpieza
    cleaningGroups: [],
    cleaningGroupsLoading: false,
    cleaningSelectedGroup: null,
    cleaningRules: [{ type: 'line_exact', value: '' }],
    cleaningVerTodasLineas: false,
    cleaningTargets: 'both',
    cleaningUrlRegex: '',
    cleaningPreview: null,
    cleaningPreviewLoading: false,
    cleaningApplying: false,
    cleaningReverting: false,
    cleaningRulesets: [],
    cleaningError: null,
    cleaningMessage: null,

    // Vista detalle de URL
    urlDetail: null,
    robotsBots: null,
    // Accesibilidad con axe por muestra de plantilla (decision 174)
    accesibilidad: null,
    urlDetailTab: 'general',
    urlDetailLoading: false,
    urlProblemas: [],          // problemas de la URL agrupados por tipo (2.7)
    urlTiposJob: null,         // { job, por: {tipo: paginas} } para «Ver las N paginas»
    contentViewMode: 'markdown',

    // ------- Init -------
    init() {
      // Enlace de solo lectura de un cliente (decision 143): `/c/<token>` es
      // la misma aplicacion, sin barra ni datos de la agencia, solo su informe.
      const compartido = location.pathname.match(/^\/c\/([A-Za-z0-9_-]{20,64})\/?$/);
      if (compartido) {
        this.iniciarCompartido(compartido[1]);
        this.$nextTick(() => lucide.createIcons());
        this._vigilarIconos();
        return;
      }
      // La ruta manda (UX-03): un enlace pegado, una recarga o el boton atras
      // llevan a la misma vista. Sin hash, la lista de rastreos.
      // Sin hash, el panel de clientes (UX-07): la pregunta del dia a dia es
      // «como estan mis clientes», no «cual fue el ultimo rastreo».
      const inicial = location.hash && location.hash !== '#/' ? location.hash : '#/clientes';
      history.replaceState(null, '', inicial);
      this._irARuta(inicial);
      // Con cambios sin guardar, salir pregunta antes (revision de UX del 25-oct, 3.5).
      window.addEventListener('popstate', () => this._alCambiarRuta());
      window.addEventListener('beforeunload', e => {
        if (this.cambiosSinGuardar().length) { e.preventDefault(); e.returnValue = ''; }
      });
      // Cualquier cambio de vista, rastreo, pestana o filtro se refleja en la
      // URL. Un solo vigilante en vez de acordarse en cada metodo.
      // Si solo cambia lo que va despues del «?» (un filtro, el orden, la
      // pagina) se sustituye la entrada: cada tecla en un filtro no puede ser
      // un paso del boton atras.
      // `_rutaNueva`: un cambio tras el «?» que SI es otra vista (de un destino
      // a «quien la enlaza», revision de UX del 25-oct, 2.8) pide su propio
      // paso, para que el boton atras vuelva a la lista de destinos.
      this.$watch('_ruta()', h => {
        if (this.view === 'explorer' && this.job) this._expUltimo = { job: this.job.id, qs: this._estadoExplorador() };
        const nueva = this._rutaNueva;
        this._rutaNueva = false;
        if (!h || location.hash === h) return;
        const mismaVista = location.hash.split('?')[0] === h.split('?')[0];
        if (this._aplicandoRuta || (mismaVista && !nueva)) history.replaceState(null, '', h);
        else history.pushState(null, '', h);
      });

      // Keyboard shortcut: 'n' to open create modal
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.menuAbierto) { this.menuAbierto = ''; return; }
        if (e.key === 'n' && !this.showCreate && !['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)) {
          this.openCreate(this._presetDelContexto());
        }
      });

      this.$nextTick(() => lucide.createIcons());
      this._vigilarIconos();
    },

    // Lucide convierte los <i data-lucide> que hay en el DOM CUANDO se le
    // llama. Todo lo que Alpine monta despues (un x-if, un x-for, una vista
    // nueva) se quedaba con el hueco del icono salvo que ese metodo concreto
    // se acordase de llamarle: asi salian vacios los botones de la ficha de
    // cliente (UX-15). Un observador lo hace para todos, una vez por frame.
    _vigilarIconos() {
      if (!window.MutationObserver || !window.lucide) return;
      let pendiente = false;
      const pintar = () => { pendiente = false; lucide.createIcons(); };
      new MutationObserver(muts => {
        if (pendiente) return;
        for (const m of muts) {
          for (const n of m.addedNodes) {
            if (n.nodeType === 1 && (n.matches('i[data-lucide]') || n.querySelector('i[data-lucide]'))) {
              pendiente = true;
              requestAnimationFrame(pintar);
              return;
            }
          }
        }
      }).observe(document.body, { childList: true, subtree: true });
    },

    // ------- Rutas (UX-03) -------
    // #/rastreos                       lista de rastreos (?estado=)
    // #/rastreos/<id>[/<pestana>]      ficha; pestanas en castellano (TAB_SLUG)
    // #/rastreos/<id>/problemas?tipo=&gravedad=
    // #/rastreos/<id>/explorador      pestana URLs (tambien /urls)
    // #/rastreos/<id>/url/<url_id>
    // #/clientes · #/clientes/<id> · #/clientes/nuevo · #/programados
    _ruta() {
      const v = this.view;
      if (v === 'jobs') {
        const q = new URLSearchParams();
        if (this.jobsBuscar.trim()) q.set('buscar', this.jobsBuscar.trim());
        if (this.jobsCliente) q.set('cliente', this.jobsCliente);
        if (this.jobsTipo) q.set('tipo', this.jobsTipo);
        if (this.jobsFilter) q.set('estado', this.jobsFilter);
        if (this.jobsPage > 1) q.set('pagina', this.jobsPage);
        return '#/rastreos' + (q.toString() ? '?' + q : '');
      }
      if (v === 'clients') return '#/clientes';
      if (v === 'client') {
        if (!this.cliente) return '#/clientes/nuevo';
        const t = this.clienteTab;
        return '#/clientes/' + this.cliente.id + (t && t !== 'estado' ? '/' + (CLIENTE_TAB_SLUG[t] || t) : '');
      }
      if (v === 'programados') return '#/programados';
      if (v === 'produccion') return '#/produccion';
      if (v === 'ajustes') return '#/ajustes';
      if (!this.job) return '';
      const base = '#/rastreos/' + this.job.id;
      if (v === 'explorer') {
        const q = this._estadoExplorador();
        return base + '/explorador' + (q ? '?' + q : '');
      }
      if (v === 'url-detail') return this.urlDetailId ? base + '/url/' + this.urlDetailId : base;
      if (v !== 'detail') return '';
      const t = this.detailTab;
      if (t === 'overview') return base;
      let h = base + '/' + (TAB_SLUG[t] || t);
      if (t === 'issues') {
        const q = new URLSearchParams();
        if (this.issueFilters.issue_type) q.set('tipo', this.issueFilters.issue_type);
        if (this.issueFilters.severity) q.set('gravedad', this.issueFilters.severity);
        if (this.issuesVista === 'lista' && !this.issueFilters.issue_type) q.set('vista', 'lista');
        if (q.toString()) h += '?' + q.toString();
      }
      if (t === 'links') {
        // Los filtros de Enlaces en la URL: «mira esto» con un enlace (2.8).
        const q = new URLSearchParams();
        const f = this.linksFiltros;
        if (this.linksVista === 'enlaces') q.set('vista', 'enlaces');
        for (const k of ['destino', 'origen', 'ancla', 'tipo', 'follow', 'posicion', 'estado', 'codigo']) {
          const v = (f[k] ?? '').toString().trim();
          if (v) q.set(k, v);
        }
        if (f.destino && f.exacto) q.set('exacto', '1');
        if (f.destino_hash && this.linksVista === 'enlaces') q.set('hacia', f.destino_hash);
        if (this.linksOrden) q.set('orden', this.linksOrden);
        if (this.linksPage > 1) q.set('pagina', this.linksPage);
        if (q.toString()) h += '?' + q.toString();
      }
      if (t === 'diff' && this.diffOtro && this.diffOtro !== (this.job.comparacion || {}).comparado_con) {
        h += '?con=' + this.diffOtro;
      }
      // La validacion de una migracion se comparte con un enlace: los dos
      // censos, el paso y como cambian las URLs (2.13).
      if (t === 'migracion') {
        const q = this.migRutaQuery();
        if (q) h += '?' + q;
      }
      return h;
    },

    async _irARuta(hash) {
      const [ruta, qs] = (hash || '').replace(/^#/, '').split('?');
      const q = new URLSearchParams(qs || '');
      const p = ruta.split('/').filter(Boolean);
      this._aplicandoRuta = true;
      try {
        // El titulo del informe es el nombre del PDF al guardarlo (decision
        // 138); fuera de el, el de siempre.
        if (p[2] !== 'informe-cliente' && document.title.startsWith('Informe SEO')) document.title = 'SEO Crawler';
        if (!p.length) {
          p.push('clientes');
          history.replaceState(null, '', '#/clientes');
        }
        if (p[0] === 'rastreos' && p.length === 1) {
          const f = { estado: q.get('estado') || '', buscar: q.get('buscar') || '',
                      cliente: q.get('cliente') || '', tipo: q.get('tipo') || '', pagina: +(q.get('pagina') || 1) };
          const igual = this.jobsFilter === f.estado && this.jobsBuscar === f.buscar
            && this.jobsCliente === f.cliente && this.jobsTipo === f.tipo && this.jobsPage === f.pagina;
          if (this.view !== 'jobs' || !igual || !this.jobs.length) {
            this._salirDeJob();
            this.view = 'jobs';
            this.jobsFilter = f.estado; this.jobsBuscar = f.buscar;
            this.jobsCliente = f.cliente; this.jobsTipo = f.tipo; this.jobsPage = f.pagina;
            await this.loadJobs();
          }
        } else if (p[0] === 'clientes') {
          if (!p[1]) await this.verClientes();
          else if (p[1] === 'nuevo') this.nuevoCliente();
          else {
            // `#/clientes/<id>[/estado|historial|alertas|configuracion]`; los
            // tramos viejos (`rastreos`) siguen abriendo (revision de UX del 25-oct, 2.1).
            const tab = CLIENTE_SLUG_TAB[p[2]] || 'estado';
            if (!this.cliente || this.cliente.id !== p[1] || this.view !== 'client') {
              await this.abrirCliente(p[1], tab);
            } else if (this.clienteTab !== tab) {
              this.cambiarTabCliente(tab);
            }
          }
        } else if (p[0] === 'programados') {
          await this.verProgramados();
        } else if (p[0] === 'produccion') {
          await this.verProduccion();
        } else if (p[0] === 'ajustes') {
          await this.verAjustes();
        } else if (p[0] === 'revision') {
          await this.verRevision(q.get('pregunta') || '');
        } else if (p[0] === 'rastreos') {
          if (!this.job || this.job.id !== p[1]) await this.openJob(p[1]);
          if (!this.job) return;
          const sub = p[2];
          // `urls` es el nombre de la pestana (2.6): lleva al Explorador.
          if (sub === 'explorador' || sub === 'urls') {
            const pre = this._preajusteExplorador(q);
            if (this.view !== 'explorer' || this._estadoExplorador() !== new URLSearchParams(qs || '').toString()) {
              this.openExplorer(pre);
            }
          } else if (sub === 'informe-cliente') {
            if (this.view !== 'informe' || !this.informe || this.informe.job.id !== this.job.id) await this.abrirInforme();
          } else if (sub === 'url' && p[3]) {
            if (this.view !== 'url-detail' || String(this.urlDetailId) !== p[3]) await this.openUrlDetail(+p[3]);
          } else {
            if (this.view === 'explorer') this._unbindExplorerKeyNav();
            this.view = 'detail';
            let tab = SLUG_TAB[sub] || 'overview';
            // Un enlace a Comparar con el mapeo de una migracion (lo que hacia
            // la casilla que ya no esta) abre «Validar migración» con lo mismo.
            if (tab === 'diff' && (q.get('map_host') || q.get('map_rutas'))) {
              const casos = {};
              const par = (q.get('map_host') || '').split(',')[0].split('=');
              if (par.length === 2 && par[0].trim() && par[1].trim()) Object.assign(casos, { dominio: true, hostDe: par[0].trim(), hostA: par[1].trim() });
              let rutas = '';
              try { rutas = (JSON.parse(q.get('map_rutas') || '[]') || []).map(r => r[0] + ' => ' + r[1]).join('\n'); } catch (e) { rutas = ''; }
              this._migDesdeRuta = { antes: q.get('con') || '', despues: '', casos, rutas, paso: 2 };
              tab = 'migracion';
            } else if (tab === 'migracion') {
              this.migLeerRuta(q);
            }
            if (tab === 'issues') {
              const tipo = q.get('tipo') || '', grav = q.get('gravedad') || '';
              const vista = tipo || q.get('vista') === 'lista' ? 'lista' : 'tipos';
              if (tipo !== this.issueFilters.issue_type || grav !== this.issueFilters.severity || vista !== this.issuesVista) {
                this.issueFilters.issue_type = tipo;
                this.issueFilters.severity = grav;
                this.issuesVista = vista;
                this.issues = [];
                this.issuesPage = 1;
              }
            }
            if (tab === 'links') {
              const f = { ...ENLACES_SIN_FILTROS };
              for (const k of ['destino', 'origen', 'ancla', 'tipo', 'follow', 'posicion', 'estado', 'codigo']) f[k] = q.get(k) || '';
              f.exacto = !!f.destino && q.get('exacto') === '1';
              f.destino_hash = q.get('hacia') || '';
              const vista = q.get('vista') === 'enlaces' || f.destino_hash ? 'enlaces' : 'destinos';
              const orden = q.get('orden') || '';
              const pagina = +(q.get('pagina') || 1);
              if (JSON.stringify(f) !== JSON.stringify(this.linksFiltros) || vista !== this.linksVista
                  || orden !== this.linksOrden || pagina !== this.linksPage) {
                this.linksFiltros = f; this.linksVista = vista; this.linksOrden = orden; this.linksPage = pagina;
                if (!f.destino_hash) this.linksDestinoUrl = '';
                this.links = [];
                if (this.detailTab === 'links' && this.view === 'detail') this.loadLinks();
              }
            }
            if (tab === 'diff' && q.get('con') && q.get('con') !== this.diffOtro) {
              this.diffOtro = q.get('con');
              this.cargarDiff();
            }
            await this.switchTab(tab);
          }
        } else {
          history.replaceState(null, '', '#/rastreos');
          await this._irARuta('#/rastreos');
        }
      } finally {
        // El vigilante de la ruta corre en un microtask: se suelta el
        // indicador despues, para que lo que dispare esta navegacion
        // reemplace la entrada del historial en vez de apilar otra.
        await this.$nextTick();
        this._aplicandoRuta = false;
      }
    },

    // La vista del Explorador en la URL (pestaña, busqueda, problema, orden,
    // pagina y filtros): «mira esto» con un enlace.
    _estadoExplorador() {
      const q = new URLSearchParams();
      if (this.expTab && this.expTab !== 'all') q.set('pestana', this.expTab);
      if (this.expSearch) q.set('buscar', this.expSearch);
      if (this.expProblema) q.set('problema', this.expProblema);
      if (this.expGravedad) q.set('gravedad', this.expGravedad);
      if (this.expSort) { q.set('orden', this.expSort); q.set('dir', this.expSortDir); }
      if (this.expPage > 1) q.set('pagina', this.expPage);
      if (this.expAgrupar) q.set('agrupar', this.expAgruparPor);
      if (this.expPlantilla) q.set('plantilla', this.expPlantilla);
      if (this.expSegmento) q.set('segmento', this.expSegmento);
      if (this.expWp) q.set('wordpress', this.wpSolo.tipo || 'todo');
      const f = Object.fromEntries(Object.entries(this.expColumnFilters).filter(([, v]) =>
        v && (v.op === 'vacio' || v.op === 'con_valor' || (v.value ?? '').toString().trim() !== '')));
      if (Object.keys(f).length) q.set('filtros', JSON.stringify(f));
      return q.toString();
    },

    _preajusteExplorador(q) {
      let filtros = {};
      try { filtros = JSON.parse(q.get('filtros') || '{}') || {}; } catch (_) { filtros = {}; }
      return {
        tab: q.get('pestana') || 'all', buscar: q.get('buscar') || '',
        problema: q.get('problema') || '', gravedad: q.get('gravedad') || '',
        orden: q.get('orden') || null, dir: q.get('dir') === 'desc' ? 'desc' : 'asc',
        pagina: +(q.get('pagina') || 1), filtros,
        agrupar: ['plantilla', 'segmento'].includes(q.get('agrupar')),
        agruparPor: q.get('agrupar') === 'segmento' ? 'segmento' : 'plantilla',
        plantilla: q.get('plantilla') || '', segmento: q.get('segmento') || '',
        wordpress: q.get('wordpress') || '',
      };
    },

    // Seccion de la barra superior que se marca como activa.
    // Un rastreo con cliente cuelga de Clientes, no de Rastreos: se llega
    // casi siempre desde la ficha del cliente (revision de UX del 25-oct, 1.4).
    // La barra tiene dos secciones, Clientes y Produccion; Programados y la
    // lista de todos los rastreos son apartados de Produccion (revision de UX
    // del 25-oct, 2.12). Un rastreo sin cliente cuelga de Produccion.
    seccion() {
      if (this.view === 'ajustes') return 'ajustes';
      if (this.view === 'revision') return 'revision';
      if (['clients', 'client'].includes(this.view)) return 'clientes';
      if (['detail', 'explorer', 'url-detail', 'informe'].includes(this.view) && this.job && this.job.cliente_id) return 'clientes';
      return 'produccion';
    },

    // El cliente (y el perfil) de lo que se esta mirando, para que «Nuevo
    // rastreo» abra ya con el: lanzado «Sin cliente» no hereda nada ni cuenta
    // en la evolucion de nadie.
    _presetDelContexto() {
      // Con el perfil principal del cliente, si lo hay: el rastreo sale con sus
      // semillas y su configuracion (revision de UX del 25-oct, 2.4).
      if (this.view === 'client' && this.cliente) {
        const p = this.perfilSiguientePaso();
        return { cliente_id: this.cliente.id, profile_id: p ? p.id : '' };
      }
      if (['detail', 'explorer', 'url-detail', 'informe'].includes(this.view) && this.job && this.job.cliente_id) {
        return { cliente_id: this.job.cliente_id, profile_id: this.job.profile_id || '' };
      }
      return null;
    },

    // Miga de pan: donde estoy y por donde vuelvo.
    migas() {
      const m = [];
      const v = this.view;
      if (v === 'ajustes') return [{ texto: 'Ajustes de la agencia' }];
      if (v === 'revision') return this.revision.pregunta
        ? [{ texto: 'Revisar a Jev', href: '#/revision' }, { texto: this.revision.pregunta }]
        : [{ texto: 'Revisar a Jev' }];
      if (v === 'client') {
        m.push({ texto: 'Clientes', href: '#/clientes' });
        if (this.cliente) {
          m.push({ texto: this.cliente.nombre, href: '#/clientes/' + this.cliente.id });
          m.push({ texto: CLIENTE_TAB_ETIQUETA[this.clienteTab] || 'Estado' });
        } else {
          m.push({ texto: 'Nuevo cliente' });
        }
      }
      if (['detail', 'explorer', 'url-detail', 'informe'].includes(v) && this.job) {
        if (this.job.cliente_id) {
          m.push({ texto: 'Clientes', href: '#/clientes' });
          m.push({ texto: this.job.cliente_nombre || this.job.client_id, href: '#/clientes/' + this.job.cliente_id });
        } else {
          m.push({ texto: 'Todos los rastreos', href: '#/rastreos' });
        }
        m.push({ texto: this.job.name, href: '#/rastreos/' + this.job.id });
        // El Explorador es la pestana URLs de la ficha, y la ficha de una URL
        // cuelga de ella (revision de UX del 25-oct, 2.6): sin boton «Volver»,
        // la miga es el camino de vuelta, con los filtros que habia.
        if (v === 'explorer') m.push({ texto: 'URLs' });
        if (v === 'informe') m.push({ texto: 'Informe para el cliente' });
        // Sin pestana propia (2.13): la miga dice donde se esta.
        if (v === 'detail' && this.detailTab === 'migracion') m.push({ texto: 'Validar migración' });
        if (v === 'url-detail') {
          m.push({ texto: 'URLs', href: this._rutaUrls() });
          const u = this.urlDetail && this.urlDetail.url;
          m.push({ texto: u ? u.replace(/^https?:\/\/[^/]+/, '') || '/' : 'URL' });
        }
      }
      return m;
    },

    // Lo que hay que parar al dejar la ficha de un rastreo.
    _salirDeJob() {
      this._stopProgress();
      this._stopSemanticPoll();
      this._pararEnriq();
      if (this.view === 'explorer') this._unbindExplorerKeyNav();
      // Primero la vista y luego el job: la cabecera del censo tambien se
      // pinta en URLs y en la ficha de URL, y si job pasa a null antes que la
      // vista, Alpine evalua sus expresiones (job.status...) con null antes de
      // retirar la plantilla. Quien llama pone la vista definitiva justo despues.
      if (['detail', 'explorer', 'url-detail'].includes(this.view)) this.view = '';
      this.job = null;
    },

    // ------- Tema (terminal / claro) -------
    toggleTheme() {
      this.theme = this.theme === 'terminal' ? 'light' : 'terminal';
      document.documentElement.dataset.theme = this.theme;
      try { localStorage.setItem('seo-crawler-theme', this.theme); } catch (_) { /* sin storage */ }
    },

    // Los layouts de Plotly vienen del servidor con fondo blanco; en el tema
    // terminal se vuelven transparentes y con texto verde.
    plotLayout(layout) {
      if (this.theme !== 'terminal') return layout;
      const css = getComputedStyle(document.documentElement);
      const text = css.getPropertyValue('--text').trim();
      const grid = css.getPropertyValue('--border').trim();
      const axis = (a) => ({ ...(a || {}), gridcolor: grid, zerolinecolor: grid, linecolor: grid });
      return {
        ...layout,
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        font: { ...(layout && layout.font), color: text, family: 'IBM Plex Mono, monospace' },
        xaxis: axis(layout && layout.xaxis),
        yaxis: axis(layout && layout.yaxis),
      };
    },

    // El bot que declara el User-Agent del formulario, para el aviso de WAF y
    // de robots.txt (decision 98).
    // ------- Toast notifications -------
    showToast(msg, type = 'success') {
      const id = Date.now();
      this.toasts.push({ id, msg, type });
      setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id); }, 3500);
    },

    // ------- Lista de trabajos -------
    async loadJobs() {
      this.loading = true;
      this.error = null;
      try {
        const q = new URLSearchParams({ page: this.jobsPage, page_size: 20 });
        if (this.jobsFilter) q.set('status', this.jobsFilter);
        if (this.jobsBuscar.trim()) q.set('buscar', this.jobsBuscar.trim());
        if (this.jobsTipo) q.set('tipo', this.jobsTipo);
        if (this.jobsCliente === 'ninguno') q.set('sin_cliente', 'true');
        else if (this.jobsCliente) q.set('client_id', this.jobsCliente);
        if (!this.clientes.length) api('/clients').then(c => { this.clientes = c; }).catch(() => {});
        const data = await api(`/jobs?${q}`);
        this.jobs = data.items;
        this.jobsPages = data.pages;
        this.jobsTotal = data.total;
        if (!this.almacenamiento) this.cargarAlmacenamiento();
      } catch (e) { this.error = e.message; }
      this.loading = false;
    },

    // ------- Borrado en masa (decision 96) -------
    // Lo que libera espacio son los censos viejos, y de uno en uno —entrar en
    // la ficha, teclear «eliminar», volver— no se borran nunca.
    get seleccionados() {
      return Object.keys(this.jobsSel).filter(id => this.jobsSel[id]);
    },

    alternarSeleccion(id) {
      this.jobsSel = { ...this.jobsSel, [id]: !this.jobsSel[id] };
    },

    get paginaSeleccionada() {
      return this.jobs.length > 0 && this.jobs.every(j => this.jobsSel[j.id]);
    },

    alternarPagina() {
      const todos = this.paginaSeleccionada;
      const sel = { ...this.jobsSel };
      this.jobs.forEach(j => { sel[j.id] = !todos; });
      this.jobsSel = sel;
    },

    limpiarSeleccion() {
      this.jobsSel = {};
    },

    // Paso 1: la vista previa. La pide al MISMO endpoint con `simular`, así
    // que los guardias que se ven aquí son exactamente los que se aplicarán.
    async abrirBorrado() {
      const ids = this.seleccionados;
      if (!ids.length) return;
      this.borrado = { paso: 'cargando', ids, previa: null, resultado: null,
                       escribir: '', forzar: false };
      await this.recargarPrevia();
    },

    // Marcar «borrarlos igualmente» REHACE la vista previa. Si no, la tabla
    // seguiria enseñando los que sí se iban y el borrado se llevaria además
    // los protegidos: la lista que se lee y lo que pasa tienen que ser lo
    // mismo.
    async recargarPrevia() {
      const b = this.borrado;
      if (!b) return;
      b.paso = 'cargando';
      try {
        b.previa = await api('/jobs/eliminar', {
          method: 'POST', body: JSON.stringify({ ids: b.ids, simular: true, forzar: b.forzar }) });
        b.paso = 'previa';
      } catch (e) {
        this.borrado = null;
        this.avisar('No se pudo preparar el borrado', e.message);
      }
    },

    get borradoBytes() {
      const p = this.borrado && (this.borrado.resultado || this.borrado.previa);
      return p ? p.bytes_aprox : null;
    },

    // Paso 2: borrar de verdad, en tantas peticiones como haga falta. El
    // servidor devuelve `pendientes` cuando se le agota su presupuesto de
    // tiempo (un censo de millones de enlaces no cabe en una petición), así
    // que esto es un bucle con barra de avance y no una espera a ciegas.
    async confirmarBorrado() {
      const b = this.borrado;
      if (!b || b.escribir.trim() !== 'eliminar') return;
      const total = b.previa.eliminados.length;
      let pendientes = b.previa.eliminados.map(e => e.id);
      // Lo liberado se suma con lo que midió la VISTA PREVIA, de antes de
      // empezar: un censo que necesita varias pasadas llega a la última con
      // casi todo borrado, y lo que el servidor mide entonces es el resto, no
      // lo que ocupaba.
      const medidaPrevia = Object.fromEntries(b.previa.eliminados.map(e => [e.id, e]));
      const acumulado = { eliminados: [], omitidos: [], filas: {}, bytes_aprox: 0,
                          bytes_incompletos: false, archivo_bytes: 0, archivo_incompleto: false,
                          capturas_bytes: 0, sin_terminar: 0, nota: b.previa.nota };
      b.paso = 'borrando';
      b.hechos = 0;
      b.total = total;

      // Tope de vueltas: si el servidor devolviera siempre los mismos
      // pendientes sin borrar nada, esto sería un bucle infinito contra la
      // API. Mejor pararse y decirlo.
      for (let vuelta = 0; pendientes.length && vuelta < 200; vuelta++) {
        let r;
        try {
          r = await api('/jobs/eliminar', {
            method: 'POST', body: JSON.stringify({ ids: pendientes, forzar: b.forzar }) });
        } catch (e) {
          b.paso = 'previa';
          this.avisar('El borrado se ha interrumpido',
            `${acumulado.eliminados.length} de ${total} rastreos se habían borrado ya. ` +
            `Lo que quedó a medias se puede terminar repitiendo la operación.\n\n${e.message}`);
          await this.loadJobs();
          return;
        }
        acumulado.eliminados.push(...r.eliminados);
        acumulado.omitidos.push(...r.omitidos);
        let filasBorradas = 0;
        for (const [tabla, n] of Object.entries(r.filas || {})) {
          acumulado.filas[tabla] = (acumulado.filas[tabla] || 0) + n;
          filasBorradas += n;
        }
        for (const e of r.eliminados) {
          const m = medidaPrevia[e.id] || e;
          if (m.bytes != null) acumulado.bytes_aprox += m.bytes;
          else acumulado.bytes_incompletos = true;
          acumulado.capturas_bytes += m.capturas_bytes || 0;
          if (m.archivado && m.archivo_bytes == null) acumulado.archivo_incompleto = true;
          else acumulado.archivo_bytes += m.archivo_bytes || 0;
        }
        b.hechos = acumulado.eliminados.length;
        pendientes = r.pendientes;
        // Avanzar es terminar algún censo O borrar filas: un censo de decenas
        // de millones de enlaces pasa muchas vueltas sin terminar, borrando
        // en cada una. Atascado es una vuelta que no hace ninguna de las dos.
        if (pendientes.length && !r.eliminados.length && !filasBorradas) {
          this.showToast('El borrado no avanza; quedan ' + pendientes.length, 'error');
          break;
        }
      }
      if (pendientes.length) {
        // Se acabaron las vueltas o se atascó: lo que queda se ve en la lista
        // como «Borrándose» y se termina repitiendo la operación.
        acumulado.sin_terminar = pendientes.length;
      }

      this.borrado.resultado = acumulado;
      this.borrado.paso = 'hecho';
      this.jobsSel = {};
      await this.loadJobs();
      if (this.verAlmacenamiento || this.almacenamiento) this.cargarAlmacenamiento();
    },

    cerrarBorrado() {
      this.borrado = null;
    },

    // ------- Espacio en disco -------
    async cargarAlmacenamiento() {
      try { this.almacenamiento = await api('/almacenamiento'); } catch (_) { this.almacenamiento = null; }
    },

    setJobsPage(p) {
      if (p < 1 || p > this.jobsPages) return;
      this.jobsPage = p;
      this.loadJobs();
    },

    filterJobs(status) {
      this.jobsFilter = this.jobsFilter === status ? '' : status;
      this.jobsPage = 1;
      this.loadJobs();
    },

    // ------- Crear trabajo -------
    // `preset` = { cliente_id, profile_id } cuando se lanza desde la ficha de
    // un cliente: el modal se abre ya con lo heredado.
    async openCreate(preset = null) {
      this.createForm = _freshForm();
      this.createError = null;
      this.createSugerencia = (preset && preset.sugerencia) || '';
      this.extraccionPrueba = { url: '', cargando: false, error: null, resultado: null };
      this.createPerfiles = [];
      this.cfgRastreo = null;
      this.showCreate = true;
      this.$nextTick(() => lucide.createIcons());
      try {
        if (!this.clientes.length) this.clientes = await api('/clients');
      } catch (_) { /* sin clientes: el desplegable queda con «Sin cliente» */ }
      if (preset && preset.cliente_id) {
        this.createForm.cliente_id = preset.cliente_id;
        await this.cambiarClienteModal(preset.profile_id || '');
      } else {
        await this.aplicarHerencia();
      }
    },

    // Al elegir cliente (o perfil) en el modal, el formulario de configuracion
    // se rehace sobre lo que heredaria el rastreo (decision 196): lo que se ve
    // con «del cliente» o «del perfil» no se manda, lo hereda el servidor; lo
    // cambiado aqui si. Lo que ya se habia cambiado en este rastreo se conserva.
    async cambiarClienteModal(profileId = '') {
      const f = this.createForm;
      if (f.cliente_id === '__nuevo__') {
        this.showCreate = false;
        this.nuevoCliente();
        return;
      }
      f.profile_id = profileId;
      this.createPerfiles = [];
      if (!f.cliente_id) {
        // Sin cliente el servidor no hereda nada: lo que la pestaña enseñaba
        // como heredado pasa a ser propio y se manda (revision de #233).
        _extraccionSinCliente(f);
        await this.aplicarHerencia();
        return;
      }
      try {
        this.createPerfiles = await api(`/clients/${f.cliente_id}/profiles`);
      } catch (e) { this.createError = e.message; return; }
      await this.aplicarHerencia();
    },

    async aplicarHerencia() {
      const f = this.createForm;
      const propia = this.cfgRastreo ? this.cfgRastreo.propia : {};
      try {
        const { inst, r } = await this.cfgCargar('rastreo', { cliente_id: f.cliente_id, profile_id: f.profile_id }, propia);
        if (f.cliente_id) {
          const nuevo = _freshForm();
          _extraccionDesdeConfig(nuevo, r.config_heredada || {});
          // Se conserva lo que no es configuracion: nombre, cliente y perfil.
          nuevo.name = f.name;
          nuevo.cliente_id = f.cliente_id;
          nuevo.profile_id = f.profile_id;
          nuevo.tipo = f.tipo;
          nuevo.seeds = (r.seeds && r.seeds.length) ? r.seeds.join('\n') : f.seeds;
          // Las reglas propias no son herencia: cambiar de cliente o de perfil
          // no las borra (revision de #233). Con el nombre de una heredada, la
          // propia la sustituye, como en el servidor.
          _extraccionConservarPropias(nuevo, f);
          if (!nuevo.name) {
            const perfil = this.createPerfiles.find(p => p.id === f.profile_id);
            const cliente = this.clientes.find(c => c.id === f.cliente_id);
            const base = perfil ? `${cliente ? cliente.nombre + ' · ' : ''}${perfil.nombre}` : (cliente ? cliente.nombre : '');
            nuevo.name = base ? `${base} · ${new Date().toISOString().slice(0, 10)}` : '';
          }
          this.createForm = nuevo;
          this.extraccionMarcarOrigen();
        }
        this.cfgRastreo = inst;
        this.cfgResolver(this.cfgRastreo);
      } catch (e) { this.createError = e.message; }
    },

    // Una linea con lo que se va a usar, junto a «Configuración» plegada
    // (UX-19): lo de «Así rastreará» en corto.
    resumenConfig() {
      const i = this.cfgRastreo;
      if (!i) return '';
      const n = CAMPOS_CONFIG.filter(c => cfgTiene(i, c.ruta)).length;
      // Sin lo de serie (API anterior a la decision 196, `base` vacia) un valor
      // que no se ha fijado no se sabe: no se pinta. Salia «undefined a la vez
      // por dominio» y «sin tope de URLs» sin saberlo (revision del 27-oct).
      const partes = partesResumenConfig(i, ['max_urls', 'concurrent_requests_per_domain', 'render_js']);
      if (i.resueltaError && !partes.length) partes.push('lo de serie del servidor');
      if (n) partes.push(n === 1 ? '1 cambio en este rastreo' : n + ' cambios en este rastreo');
      return partes.join(' · ');
    },

    // El tipo con el que sale el rastreo del modal (revision de UX del 25-oct,
    // 1.6; decision 203): el elegido o, sin elegir, censo con perfil y prueba
    // sin el. Un rastreo puntual sin marcar contaba como censo en la portada.
    tipoRastreoModal() {
      const f = this.createForm || {};
      return f.tipo || (f.profile_id ? 'censo' : 'prueba');
    },

    // El mismo rastreo con 250 URLs y «CANARY» en el nombre: se reconoce
    // como canario (tipo deducido) y no entra en la evolucion del cliente.
    async lanzarCanario() {
      const original = this.createForm.name;
      const host = (this.createForm.seeds.split('\n')[0] || '').replace(/^https?:\/\//, '').split('/')[0];
      // Sin repetir el prefijo si el nombre ya lo trae.
      this.createForm.name = /^CANARY\b/i.test(original || '') ? original : 'CANARY - ' + (original || host);
      await this.submitCreate({ max_urls: 250 }, 'canario');
      if (this.showCreate) this.createForm.name = original;  // fallo: se deja como estaba
    },

    // Se manda lo que fija ESTE rastreo (`cfgRastreo.propia`): lo heredado lo
    // pone el servidor (create_job con exclude_unset). Sin cliente, lo mismo
    // sobre lo de serie. `extra` es lo que pone el boton (el tope del canario).
    async submitCreate(extra = null, tipoForzado = null) {
      this.createError = null;
      const i = this.cfgRastreo;
      const mal = cfgListoParaGuardar(i);
      if (mal) {
        this.createError = mal;
        return;
      }
      this.creating = true;
      try {
        const f = this.createForm;
        const seeds = f.seeds.split('\n').map(s => s.trim()).filter(Boolean);
        const config = JSON.parse(JSON.stringify((i && i.propia) || {}));
        Object.assign(config, extra || {});
        const ce = _extraccionAConfig(f);
        if (ce) config.custom_extraction = ce;
        const tipo = tipoForzado || this.tipoRastreoModal();
        const payload = { name: f.name, seeds, config, tipo };
        if (f.cliente_id) payload.cliente_id = f.cliente_id;
        if (f.profile_id) payload.profile_id = f.profile_id;

        const creado = await api('/jobs', { method: 'POST', body: JSON.stringify(payload) });
        // Una API anterior a la decision 203 no lee `tipo` al crear: se marca
        // despues, con lo que ya existia para cambiarlo (UX-07/08).
        if (creado && creado.id && creado.tipo !== tipo) {
          try { await api(`/jobs/${creado.id}`, { method: 'PATCH', body: JSON.stringify({ tipo }) }); }
          catch (e) { this.showToast('El rastreo ha salido, pero no se ha podido marcar como ' + tipo + ': ' + e.message); }
        }
        this.showCreate = false;
        this.jobsPage = 1;
        await this.loadJobs();
        if (this.view === 'client' && this.cliente) await this.abrirCliente(this.cliente.id, this.clienteTab);
        this.showToast('Rastreo iniciado correctamente');
      } catch (e) {
        this.createError = e.message;
        if (/custom_extraction/.test(e.message)) this.createExtraccionAbierta = true;
      }
      this.creating = false;
    },

    // ------- Configuracion en tres niveles (decision 196) -------
    // La plantilla del formulario, una sola para los tres sitios: se inserta
    // con x-html (Alpine 3 inicializa lo insertado) en un contenedor que
    // define `i`, la instancia de ese nivel.
    plantillaCfg() {
      // Fuera del estado de Alpine: guardarla en `this` dentro del efecto de
      // x-html lo volvia a disparar y montaba el formulario dos veces.
      if (_TPL_CFG === null) {
        const t = document.getElementById('tpl-config-niveles');
        _TPL_CFG = t ? t.innerHTML : '';
      }
      return _TPL_CFG;
    },

    // La instancia de un nivel con su base: lo de arriba ya resuelto por la
    // API (`config-resuelta`), con de donde sale cada valor.
    async cfgCargar(nivel, ctx, propia) {
      ctx = ctx || {};
      let r;
      if (ctx.cliente_id) {
        const q = nivel === 'rastreo' && ctx.profile_id ? `?profile_id=${ctx.profile_id}` : '';
        r = await api(`/clients/${ctx.cliente_id}/config-resuelta${q}`);
      } else {
        try {
          r = await api('/clients/config-resuelta', { method: 'POST', body: JSON.stringify({ config: {} }) });
        } catch (e) {
          // Sin lo de serie (una API anterior a la decision 196) el formulario
          // sigue sirviendo: lo cambiado aqui se manda igual.
          const inst = cfgNuevo(nivel, { base: {}, propia, ctx });
          inst.resueltaError = e.message;
          return { inst, r: {} };
        }
      }
      const serie = r.serie || r.config;
      const inst = cfgNuevo(nivel, {
        base: nivel === 'cliente' ? serie : r.config,
        origen: nivel === 'cliente' ? {} : (r.origen || {}),
        origenClave: nivel === 'cliente' ? {} : (r.origen_por_clave || {}),
        serie, propia, ctx,
      });
      return { inst, r };
    },

    cfgProgramar(i) {
      if (!i) return;
      clearTimeout(i._temporizador);
      i._temporizador = setTimeout(() => this.cfgResolver(i), 350);
    },

    // «Así rastreará»: la API resuelve el borrador de este nivel (y valida
    // como al guardar). Con un campo con error no se pregunta.
    async cfgResolver(i) {
      if (!i || cfgHayErrores(i)) return;
      i.resolviendo = true;
      const cuerpo = { cliente_id: i.ctx.cliente_id || null, profile_id: i.ctx.profile_id || null,
                       nivel: i.nivel, config: i.propia };
      try {
        const r = await api('/clients/config-resuelta', { method: 'POST', body: JSON.stringify(cuerpo) });
        i.resuelta = r;
        i.resueltaError = '';
      } catch (e) {
        i.resueltaError = e.message;
      }
      i.resolviendo = false;
    },

    cfgCambiarCampo(i, ruta, valor) {
      cfgCambiar(i, ruta, valor);
      this.cfgProgramar(i);
    },

    cfgVolver(i, ruta) {
      cfgHeredar(i, ruta);
      if (ruta === 'user_agent') i.uaPersonalizado = false;
      this.cfgProgramar(i);
    },

    // El user agent: un preset o «Personalizado», que abre el campo de texto.
    cfgElegirUa(i, preset) {
      if (preset === 'custom') { i.uaPersonalizado = true; return; }
      i.uaPersonalizado = false;
      this.cfgCambiarCampo(i, 'user_agent', UA_PRESETS[preset]);
    },

    cfgUaPersonalizado(i) {
      return !!i.uaPersonalizado || cfgTextoCampo(i, 'user_agent') === 'custom';
    },

    cfgAplicar(i) {
      clearTimeout(i._temporizadorJson);
      if (cfgAplicarJson(i)) this.cfgProgramar(i);
    },

    cfgEscribirJson(i) {
      cfgJsonEscrito(i);
      clearTimeout(i._temporizadorJson);
      i._temporizadorJson = setTimeout(() => { if (i.jsonSucio) this.cfgAplicar(i); }, 800);
    },

    cfgOpcionesHuella(i) {
      const heredada = i.origenBase.impersonate;
      return [['', heredada ? 'La heredada (' + cfgLlano('impersonate', cfgHeredado(i, 'impersonate')) + ')'
                            : 'Automática: la del navegador con el que se presenta'], ...HUELLAS_TLS];
    },

    cfgTextoProgramacion(p) {
      return `La programación «${p.nombre}» cambia además: `
        + p.claves.map(k => (CAMPO_CONFIG[k] || { etiqueta: k }).etiqueta.toLowerCase()).join(', ') + '.';
    },

    // ------- Clientes (#36) -------
    async verClientes() {
      this.view = 'clients';
      await this.cargarClientes();
    },

    // `clientesEstado` separa «cargando», «error» y «vacio de verdad»: antes
    // la portada decia «Todavia no hay clientes» mientras cargaba y cuando la
    // API fallaba (revision de UX del 25-oct, 1.5).
    async cargarClientes() {
      if (!this.clientes.length) this.clientesEstado = 'cargando';
      try {
        const [clientes, panel] = await Promise.all([api('/clients'), api('/clients/panel')]);
        this.clientes = clientes;
        this.panelClientes = panel;
        this.clientesEstado = 'ok';
      } catch (e) {
        this.clientesEstado = 'error';
        this.clientesError = e.message;
      }
    },

    // Las alertas que salto la comparacion del ultimo censo y no constan
    // abiertas: un censo lanzado a mano (sin perfil ni programacion) no abre
    // alertas (shared/incidentes.serie_de_job), y sin esto la portada lo
    // callaba con un «—» (revision de UX del 25-oct, 2.3). Si hay alertas
    // abiertas, esas mandan: lo que salto el ultimo censo ya esta entre ellas
    // o ya se cerro.
    alertasSinAbrirPanel(p) {
      if (!p || p.incidentes_vivos || !p.ultimo || !p.ultimo.alertas) return null;
      return { total: p.ultimo.alertas, criticas: p.ultimo.alertas_criticas || 0 };
    },

    // Las filas de la portada, primero las que piden atencion: alertas
    // abiertas (la cifra de su columna; revision de UX del 25-oct, 2.3), las
    // que salto el ultimo censo sin abrirse (criticas antes) y luego el censo
    // mas reciente.
    filasPanelOrdenadas() {
      const filas = [...((this.panelClientes && this.panelClientes.clientes) || [])];
      const sa = p => this.alertasSinAbrirPanel(p) || { total: 0, criticas: 0 };
      return filas.sort((a, b) =>
        (b.incidentes_vivos || 0) - (a.incidentes_vivos || 0)
        || sa(b).criticas - sa(a).criticas
        || sa(b).total - sa(a).total
        || String((b.ultimo || {}).created_at || '').localeCompare(String((a.ultimo || {}).created_at || ''))
        || String(a.nombre).localeCompare(String(b.nombre)));
    },

    // `guardado`: las secciones que se acaban de guardar (las demas, si
    // estaban a medias, se conservan al recargar la ficha del mismo cliente).
    async abrirCliente(id, tab = 'estado', { guardado = [] } = {}) {
      // Recargar la ficha del mismo cliente (guardar o eliminar un perfil,
      // lanzar un rastreo, guardar una seccion) no se lleva por delante lo
      // editado y sin guardar en los datos o en las integraciones (revision
      // de UX del 25-oct, 3.5; decision 200).
      const pendiente = {};
      if (this.view === 'client' && this.cliente && this.cliente.id === id) {
        if (!guardado.includes('datos') && this.datosClienteCambiados())
          for (const k of ['nombre', 'slug', 'dominios', 'zona_horaria', 'notas']) pendiente[k] = this.clienteForm[k];
        if (!guardado.includes('integraciones') && this.integracionesCambiadas())
          pendiente.integraciones = this.clienteForm.integraciones;
      }
      this.view = 'client';
      // El tramo de la URL o el nombre interno: un nombre viejo («rastreos»)
      // o desconocido no puede dejar la ficha sin pestana (revision de UX del
      // 25-oct, 2.1: tras guardar un perfil se quedaba en blanco).
      tab = CLIENTE_SLUG_TAB[tab] || 'estado';
      this.clienteTab = tab;
      this.clienteError = '';
      if (!this.cliente || this.cliente.id !== id) { this.estadoCliente = null; this.alertasAbiertas = null; this.incidentesVer = 'vivos'; this.clienteProgramaciones = []; }
      // Lo de «Así rastreará» y el formulario de configuracion son del cliente
      // y de lo guardado: al volver a abrirlo se piden otra vez (decision 196).
      this.asiPerfiles = {};
      if (!this.cliente || this.cliente.id !== id) this.cfgCliente = null;
      this.altaForm = null;
      try {
        const [c, perfiles, jobs, serie] = await Promise.all([
          api(`/clients/${id}`),
          api(`/clients/${id}/profiles`),
          api(`/jobs?client_id=${id}&page_size=100`),
          api(`/clients/${id}/serie`),
        ]);
        this.cliente = c;
        this.clientePerfiles = perfiles;
        this.clienteJobs = jobs.items || [];
        this.clienteSerie = serie || [];
        this.clienteForm = Object.assign(_formCliente(c), pendiente);
      } catch (e) { this.error = e.message; }
      // Lo de cada pestana, y lo que necesita Estado (que es la de entrada y
      // la que cuenta las alertas abiertas de la pestana Alertas).
      this.cargarAlertasAbiertas();
      this.cargarEstadoCliente();
      this.cargarProgramacionesCliente();
      this._cargarTabCliente(tab);
      // Aparte: si la evolucion falla (o la tabla aun no existe), la ficha se
      // abre igual, sin graficas.
      try {
        this.clienteEvolucion = await api(`/clients/${id}/evolucion`);
        const s = this.clienteEvolucion.series || [];
        if (!s.find(x => x.clave === this.evolucionClave))
          this.evolucionClave = (s.find(x => x.comparables >= 2) || s[0] || {}).clave || null;
      } catch (e) { this.clienteEvolucion = null; }
      // Aparte tambien: sin Search Console la lista viene vacia y no se pinta.
      this.clienteTrafico = [];
      try {
        const t = await api(`/clients/${id}/trafico`);
        if (this.cliente && this.cliente.id === id) this.clienteTrafico = t || [];
      } catch (e) { this.clienteTrafico = []; }
    },

    // Cambiar de pestana en la ficha del cliente. Las reglas de alertas viven
    // en Configuracion y la lista de alertas en Alertas (revision de UX del
    // 25-oct, 2.1): antes el editor ocupaba 2.124 px de la pestana Alertas.
    cambiarTabCliente(tab) {
      this.clienteTab = tab;
      this._cargarTabCliente(tab);
    },

    _cargarTabCliente(tab) {
      if (!this.cliente) return;
      if (tab === 'alertas') this.cargarIncidentes();
      if (tab === 'config' && this._reglasDe !== this.cliente.id) this.cargarReglas();
    },

    // El ultimo censo completado del cliente: el primero de su serie que es
    // censo (ni canario ni prueba). Mismo criterio que la portada.
    ultimoCensoCliente() {
      return (this.clienteSerie || []).find(j => j.tipo === 'censo' && j.status === 'completed') || null;
    },

    // /serie corta en 30 (su limite por defecto): si viene llena y sin censo,
    // puede haberlo mas atras y Estado no dice «todavia no hay ninguno».
    serieTruncadaCliente() {
      return (this.clienteSerie || []).length >= 30;
    },

    // Lo mas reciente si esta en marcha: «hay uno rastreando» en Estado.
    rastreoEnCursoCliente() {
      return (this.clienteSerie || []).find(j => ['pending', 'running'].includes(j.status)) || null;
    },

    // Pestana Estado: la ficha del ultimo censo (su comparacion), sus cifras
    // (/stats trae las paginas con error, revision 1.11) y los cinco primeros
    // problemas por prioridad, con la misma consulta que «Que arreglar
    // primero» del Resumen del censo. Cada parte falla por su cuenta: lo que
    // no se sabe no se afirma, pero tampoco tira lo demas.
    async cargarEstadoCliente() {
      const u = this.ultimoCensoCliente();
      if (!u) { this.estadoCliente = { jobId: null }; return; }
      if (this.estadoCliente && this.estadoCliente.jobId === u.id && !this.estadoCliente.error) return;
      const jobId = u.id;
      const e = { jobId, job: null, stats: null, principales: null, error: '' };
      this.estadoCliente = e;
      const [job, stats, filas] = await Promise.all([
        api(`/jobs/${jobId}`).catch(err => { e.error = err.message; return null; }),
        api(`/jobs/${jobId}/stats`).catch(() => null),
        api(`/jobs/${jobId}/issues/resumen?orden=prioridad&ejemplos=0`).catch(() => null),
      ]);
      if (!this.estadoCliente || this.estadoCliente.jobId !== jobId) return;
      // El censo de referencia, solo para saber si leyo sus sitemaps entero
      // (decision 205): `undefined` mientras se pregunta, true si no se pudo.
      const refId = job && job.comparacion && job.comparacion.comparado_con;
      this.estadoCliente = {
        ...e, job, stats,
        principales: filas ? filasPorTipo(filas.filter(r => r.severity !== 'info'), filas).slice(0, 5) : null,
        principalesError: filas === null,
        refDudaSitemaps: refId ? undefined : false,
      };
      if (refId) {
        const duda = await api(`/jobs/${refId}`).then(a => !!dudaSitemaps(a)).catch(() => true);
        if (this.estadoCliente && this.estadoCliente.jobId === jobId) this.estadoCliente = { ...this.estadoCliente, refDudaSitemaps: duda };
      }
    },

    // «N incidencias nuevas y M resueltas» del Estado: los totales de la
    // comparacion sin «No incluida en el sitemap» si cualquiera de los dos
    // censos leyo sus sitemaps a medias (decision 205; V13 solo estaba en
    // Problemas y el Estado de Lopesan decia «240 nuevas y 775 resueltas»
    // con 370 de 396 ficheros vacios). null mientras no se sepa.
    incidenciasEstado() {
      const e = this.estadoCliente, c = this.cmpEstado();
      const inc = c && c.incidencias;
      if (!e || !inc || !inc.comparable) return null;
      const aqui = !!dudaSitemaps(e.job);
      if (!aqui && e.refDudaSitemaps === undefined) return null;
      return incidenciasAfirmables(inc, aqui || e.refDudaSitemaps);
    },

    // Las incidencias del informe (decision 205). Una API con la decision ya
    // las da sin «No incluida en el sitemap» cuando toca (`sin_sitemap`). Con
    // una anterior, en la app el censo esta cargado y su comparacion trae el
    // desglose por tipo: se quita aqui. En el enlace compartido, tal cual.
    incidenciasInforme() {
      const i = this.informe && this.informe.comparacion && this.informe.comparacion.incidencias;
      if (!i) return null;
      if ('sin_sitemap' in i) return i;
      const j = this.job;
      if (this.compartido || !j || !this.informe.job || this.informe.job.id !== j.id
          || !j.comparacion || !j.comparacion.incidencias) return i;
      const va = this.versionAnterior && this.versionAnterior.jobId === j.id ? this.versionAnterior : null;
      const aqui = !!dudaSitemaps(j);
      if (!aqui && (!va || va.version === undefined)) return null;
      const a = incidenciasAfirmables(j.comparacion.incidencias, aqui || !!va.error || !!va.dudaSitemaps);
      return { ...i, nuevas: a.nuevas, resueltas: i.resueltas == null ? null : a.resueltas, siguen: a.siguen, sin_sitemap: a.sinSitemap };
    },

    // Las alertas abiertas del cliente: los incidentes vivos (abiertos o
    // vistos) de sus perfiles y programaciones (decision 139).
    //
    // Es LA cifra de «alertas» de la portada, de la ficha y de la pestana
    // (revision de UX del 25-oct, 2.3). Antes la portada decia «3 alertas»
    // (las que salto la comparacion del ultimo censo) junto a «5 incidentes»
    // (lo abierto), y eran dos palabras para casi lo mismo con dos cifras.
    // Lo abierto es lo que hay que mirar: sigue ahi hasta que un rastreo
    // posterior que puede comprobarlo ya no lo ve, y no desaparece porque un
    // censo intermedio no fuese comparable. Las alertas que salto UNA
    // comparacion son otra cosa (lo que cambio entre dos censos) y se dicen
    // con su fecha: «frente al 19 oct: 3 alertas».
    async cargarAlertasAbiertas() {
      if (!this.cliente) return;
      const id = this.cliente.id;
      try {
        const r = await api(`/clients/${id}/incidentes?estado=vivos`);
        if (this.cliente && this.cliente.id === id) this.alertasAbiertas = r || [];
      } catch (_) {
        if (this.cliente && this.cliente.id === id) this.alertasAbiertas = null;
      }
    },

    // El censo con el que se comparo `j` (`comparacion.comparado_con`): el
    // anterior de su misma programacion, o del mismo sitio si se lanzo a mano
    // (`shared.comparacion.censo_anterior`). Es la UNICA referencia de «frente
    // al anterior» (revision de UX del 25-oct, 2.3): la de sus alertas, la de
    // la tarjeta del censo y la de las graficas de su serie. Antes la tabla
    // restaba la fila de debajo y, con dos programaciones semanales, el 26 oct
    // salia «85 ▲2» frente al 21 oct (de la otra programacion) mientras la
    // grafica decia «85 ▼4» frente al 19 oct.
    referenciaDe(j) {
      if (!j || !j.comparado_con) return null;
      return (this.clienteSerie || []).find(x => x.id === j.comparado_con) || null;
    },

    // La portada con una API anterior a la decision 202: alguna fila sin
    // `paginas_con_error`; la columna pasa a decir que son incidencias.
    panelSinPaginasError() {
      return this.filasPanelOrdenadas().some(p => p.ultimo && p.ultimo.paginas_con_error == null);
    },

    // Tipos distintos de error o aviso del censo: el contador de la pestaña
    // Problemas (V16; decision 202).
    tiposQueMirar(stats) {
      return new Set(((stats && stats.issues_by_type) || [])
        .filter(i => i.severity === 'error' || i.severity === 'warning').map(i => i.issue_type)).size;
    },

    // Paginas con error de una fila de la serie o de la portada (decision
    // 202): la misma cifra que la tarjeta del censo y el Estado. Con una API
    // anterior la fila no la trae; en la ficha del cliente sale de la
    // evolucion (`urls_con_error` del mismo rastreo, misma cuenta) y, si
    // tampoco, null: entonces se pintan las incidencias de error, dicho.
    paginasConError(j) {
      if (!j) return null;
      if (j.paginas_con_error != null) return j.paginas_con_error;
      for (const s of ((this.clienteEvolucion && this.clienteEvolucion.series) || [])) {
        const p = s.puntos.find(x => x.job_id === j.id && x.urls_con_error != null);
        if (p) return p.urls_con_error;
      }
      return null;
    },

    // La fecha de la referencia de una fila: la del censo de la serie o, si
    // no esta (de otro cliente, o mas alla de los 30 de /serie), la que trae
    // la propia fila (`fecha_anterior`). Sin ninguna de las dos (API sin
    // desplegar) la celda dice «frente a otro censo», nunca una cifra suelta.
    fechaReferenciaDe(j) {
      const r = this.referenciaDe(j);
      return (r && r.created_at) || (j && j.fecha_anterior) || null;
    },

    // «frente al 19 oct: saltaron 3 alertas». «Saltaron» porque son las de
    // ESA comparacion; las abiertas son otra cifra, con su propio adjetivo
    // (revision de UX del 25-oct, 2.3).
    textoFrenteAlAnterior(j) {
      const f = this.fechaReferenciaDe(j);
      const ref = f ? 'frente al ' + fmt.diaCorto(f) : 'frente a otro censo';
      if (j.alertas === null || j.alertas === undefined) return ref + ': no comparable';
      if (!j.alertas) return ref + ': no saltó ninguna';
      return ref + ': ' + (j.alertas === 1 ? 'saltó 1 alerta' : 'saltaron ' + fmt.num(j.alertas) + ' alertas');
    },

    // La comparacion automatica del ultimo censo, para «Que ha cambiado».
    cmpEstado() {
      return (this.estadoCliente && this.estadoCliente.job && this.estadoCliente.job.comparacion) || null;
    },

    // El punto comparable anterior al ultimo de la serie elegida: contra el
    // que se miden las flechas de las graficas. Se nombra por su fecha.
    referenciaSerie() {
      const s = this.serieEvolucion();
      const c = s ? s.puntos.filter(p => p.comparable) : [];
      return c.length > 1 ? c[c.length - 2] : null;
    },

    // La pestana Alertas con las cerradas: lo que salto un censo y un rastreo
    // posterior ya vio resuelto (revision de UX del 25-oct, 2.3).
    verAlertasCerradas() {
      this.incidentesVer = 'cerrados';
      if (this.clienteTab === 'alertas') this.cargarIncidentes();
      else this.cambiarTabCliente('alertas');
    },

    // --- Reglas de alerta (decision 135) -------------------------------------
    // Decision 139
    async cargarIncidentes() {
      if (!this.cliente) return;
      const id = this.cliente.id;
      this.incidentes = null;
      try {
        const r = await api(`/clients/${id}/incidentes?estado=${this.incidentesVer}`);
        if (this.cliente && this.cliente.id === id) this.incidentes = r;
      } catch (e) { this.incidentes = []; this.reglasError = e.message; }
    },

    // Los grupos de la pestaña Alertas: `aFavor` las de tipo info, que van
    // aparte en «Cambios a favor» (1.12).
    gruposIncidentes(aFavor) {
      return agruparIncidentes(this.incidentes || []).filter(g => (g.severidad === 'info') === !!aFavor);
    },
    async cambiarGrupoIncidentes(g, cambio, estadoDesde) {
      for (const i of g.items) {
        if (i.estado === 'cerrado' || (estadoDesde && i.estado !== estadoDesde)) continue;
        await this.cambiarIncidente(i, cambio);
      }
    },

    async cambiarIncidente(i, cambio) {
      try {
        const r = await api(`/clients/${this.cliente.id}/incidentes/${i.id}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cambio),
        });
        Object.assign(i, r);
        this.cargarAlertasAbiertas();
      } catch (e) { this.reglasError = e.message; }
    },

    // El titular: el de la regla de la comparacion si lo es (fmt.tituloAlerta)
    // y, si no, el texto de la regla del cliente.
    tituloIncidente(i) {
      const d = i.detalle || {};
      if (i.regla && !i.regla.startsWith('cliente:') && d.regla) {
        return fmt.tituloAlerta(d) + (d.paginas != null ? ` · ${fmt.num(d.paginas)} de ${fmt.num(d.de)} páginas (${fmt.num(d.pct)} %)` : '');
      }
      return i.titulo;
    },

    async cargarReglas() {
      if (!this.cliente) return;
      // Sin esto, el formulario del cliente anterior seguia en pantalla (y se
      // podia guardar sobre este) mientras llegaban las reglas nuevas.
      this.reglasCliente = null; this.reglasForm = null; this.resumenes = [];
      this.reglasError = ''; this.reglasPrueba = null; this.resumenPrevia = null;
      try {
        const [r, res] = await Promise.all([
          api(`/clients/${this.cliente.id}/reglas`),
          api(`/clients/${this.cliente.id}/resumenes`).catch(() => []),
        ]);
        this.reglasCliente = r;
        this.reglasForm = _formReglas(r.efectivas);
        this._reglasFoto = _fotoReglas(this.reglasForm);
        this.resumenes = res || [];
        this._reglasDe = this.cliente && this.cliente.id;
      } catch (e) { this.reglasError = e.message; }
    },

    reglaNueva() {
      const ids = new Set(this.reglasForm.propias.map(r => r.id));
      let n = this.reglasForm.propias.length + 1;
      while (ids.has('regla-' + n)) n++;
      this.reglasForm.propias.push({
        id: 'regla-' + n, nombre: '', medida: 'urls_4xx', segmento: '', modo: 'valor',
        operador: '>', umbral: 20, severidad: 'warning', avisar: false, activa: true,
      });
    },

    // Lo que se guarda es PARCIAL sobre lo de serie: solo lo que cambia, para
    // que una regla nueva de serie llegue tambien a este cliente.
    _cuerpoReglas() {
      const f = this.reglasForm, serie = this.reglasCliente.de_serie;
      const comparacion = {};
      const numero = (v, que) => {
        // `Number('')` es 0: un campo vaciado se guardaba como umbral 0.
        if (v === '' || v === null || v === undefined || Number.isNaN(Number(v)))
          throw new Error('«' + que + '»: falta el número');
        return Number(v);
      };
      for (const [regla, c] of Object.entries(f.comparacion)) {
        const d = serie.comparacion[regla] || {}, cambios = {};
        for (const k of ['activa', 'avisar', 'pct_sitio', 'min_paginas', 'pct_plantilla']) {
          const v = ['activa', 'avisar'].includes(k) ? !!c[k] : numero(c[k], fmt.reglaDiff(regla));
          if (v !== d[k]) cambios[k] = v;
        }
        if (Object.keys(cambios).length) comparacion[regla] = cambios;
      }
      const propias = f.propias.map(r => ({
        ...r, umbral: numero(r.umbral, (r.nombre || '').trim() || this.fraseRegla(r)), segmento: (r.segmento || '').trim() || null,
        nombre: (r.nombre || '').trim(),
      }));
      const cuerpo = {};
      if (Object.keys(comparacion).length) cuerpo.comparacion = comparacion;
      if (JSON.stringify(propias) !== JSON.stringify(serie.propias)) cuerpo.propias = propias;
      if (f.silenciado_hasta) cuerpo.silenciado_hasta = f.silenciado_hasta;
      const rs = {}, drs = serie.resumen_semanal;
      for (const k of ['activo', 'dia', 'hora']) {
        const v = k === 'activo' ? !!f.resumen_semanal[k] : Number(f.resumen_semanal[k]);
        if (v !== drs[k]) rs[k] = v;
      }
      if (Object.keys(rs).length) cuerpo.resumen_semanal = rs;
      const ignorar = (f.ignorar_texto || '').split('\n').map(x => x.trim()).filter(Boolean);
      if (JSON.stringify(ignorar) !== JSON.stringify(serie.ignorar_en_textos || [])) cuerpo.ignorar_en_textos = ignorar;
      return cuerpo;
    },

    async guardarReglas() {
      this.reglasError = '';
      try {
        const r = await api(`/clients/${this.cliente.id}/reglas`,
                            { method: 'PUT', body: JSON.stringify(this._cuerpoReglas()) });
        this.reglasCliente = r;
        this.reglasForm = _formReglas(r.efectivas);
        this._reglasFoto = _fotoReglas(this.reglasForm);
        this.showToast('Reglas guardadas: valen para los rastreos que terminen desde ahora');
        return true;
      } catch (e) { this.reglasError = e.message; }
      return false;
    },

    async restablecerReglas() {
      const ok = await this.preguntar({
        titulo: 'Volver a las reglas de serie',
        mensaje: 'Se borran los cambios de este cliente (umbrales, reglas propias, silencio y resumen) y vuelven las de serie.',
        aceptar: 'Restablecer', peligro: true,
      });
      if (!ok) return;
      try {
        const r = await api(`/clients/${this.cliente.id}/reglas`, { method: 'PUT', body: 'null' });
        this.reglasCliente = r;
        this.reglasForm = _formReglas(r.efectivas);
        this._reglasFoto = _fotoReglas(this.reglasForm);
        this.showToast('Reglas de serie restablecidas');
      } catch (e) { this.reglasError = e.message; }
    },

    async probarReglas() {
      this.reglasError = ''; this.reglasPrueba = null;
      try {
        this.reglasPrueba = await api(`/clients/${this.cliente.id}/reglas/probar`,
                                      { method: 'POST', body: JSON.stringify(this._cuerpoReglas()) });
      } catch (e) { this.reglasError = e.message; }
    },

    async verResumenPrevio() {
      this.reglasError = '';
      try { this.resumenPrevia = await api(`/clients/${this.cliente.id}/resumenes/vista-previa`); }
      catch (e) { this.reglasError = e.message; }
    },

    fraseRegla(r) { return fraseReglaPropia(r, this.reglasCliente && this.reglasCliente.catalogo); },

    serieEvolucion() {
      const s = (this.clienteEvolucion && this.clienteEvolucion.series) || [];
      return s.find(x => x.clave === this.evolucionClave) || s[0] || null;
    },

    etiquetaMetrica(k) {
      // «URLs con error» de la API son paginas: las mismas que «páginas con
      // error» de la tarjeta (decision 202), y con el mismo nombre.
      if (k === 'urls_con_error') return 'Páginas con error';
      const m = this.clienteEvolucion && this.clienteEvolucion.metricas && this.clienteEvolucion.metricas[k];
      return m ? m.etiqueta : k;
    },

    graficaEvolucion(metrica) {
      const serie = this.serieEvolucion();
      if (!serie) return '';
      const mejor = (((this.clienteEvolucion || {}).metricas || {})[metrica] || {}).mejor || 'baja';
      return svgGrafica(modeloGrafica(serie.puntos, metrica, { etiqueta: this.etiquetaMetrica(metrica), mejor }));
    },

    // El ultimo valor comparable de una metrica y la flecha frente al
    // anterior comparable (sin flecha si cambio la version del analisis).
    resumenMetrica(metrica) {
      const serie = this.serieEvolucion();
      const c = serie ? serie.puntos.filter(p => p.comparable && p[metrica] != null) : [];
      if (!c.length) return { valor: '—', tendencia: null };
      const ultimo = c[c.length - 1], previo = c.length > 1 ? c[c.length - 2] : null;
      let tendencia = null;
      if (previo) {
        const mejor = ((this.clienteEvolucion.metricas || {})[metrica] || {}).mejor || 'baja';
        const delta = ultimo[metrica] - previo[metrica];
        tendencia = textoTendencia({
          direccion: ultimo.cambio_version && ultimo.cambio_version.analisis ? 'no_comparable'
            : delta > 0 ? 'sube' : delta < 0 ? 'baja' : 'igual',
          delta: Math.round(delta * 100) / 100, antes: previo[metrica], fecha_antes: previo.fecha,
          mejora: delta === 0 ? null : ((delta > 0 ? 'sube' : 'baja') === mejor),
          cambio_version: ultimo.cambio_version,
          motivo: 'Entre los dos últimos censos cambió la versión del análisis: el salto puede ser nuestro, no del sitio.',
        });
      }
      return { valor: _valorMetrica(ultimo[metrica], metrica), tendencia };
    },

    noComparables(serie) {
      return serie ? serie.puntos.filter(p => !p.comparable) : [];
    },

    nuevoCliente() {
      this.view = 'client';
      this.cliente = null;
      this.clientePerfiles = [];
      this.clienteJobs = [];
      this.clienteProgramaciones = [];
      this.clienteForm = _formCliente(null);
      this.clienteTab = 'config';
      this.clienteError = '';
      // Alta guiada (revision de UX del 25-oct, 2.14): solo nombre y dominio.
      // Lo demas (configuracion, Search Console, Slack, reglas) se rellena
      // despues en Configuracion, cuando ya hay algo que rastrear.
      this.altaForm = { nombre: '', dominio: '', error: '', guardando: false };
    },

    altaHome() {
      const d = ((this.altaForm && this.altaForm.dominio) || '').trim().toLowerCase()
        .replace(/^[a-z][a-z0-9+.-]*:\/\//, '').split('/')[0].split(':')[0];
      return d ? 'https://' + d + '/' : '';
    },

    async crearClienteGuiado() {
      const f = this.altaForm;
      if (!f) return;
      f.error = '';
      if (!f.nombre.trim()) { f.error = 'Falta el nombre del cliente.'; return; }
      if (!this.altaHome()) { f.error = 'Falta el dominio principal (por ejemplo, www.cliente.com).'; return; }
      f.guardando = true;
      try {
        const c = await api('/clients', { method: 'POST', body: JSON.stringify({
          nombre: f.nombre.trim(), dominios: [f.dominio.trim()], zona_horaria: 'Europe/Madrid', perfil_principal: true }) });
        this.clientes = await api('/clients');
        this.altaReciente = c.id;
        await this.abrirCliente(c.id, 'estado');
      } catch (e) { f.error = e.message; f.guardando = false; }
    },

    // El perfil con el que seguir cuando el cliente aun no tiene censo: el
    // «Sitio principal» del alta guiada o, si no, el primero que sea propio.
    perfilSiguientePaso() {
      const ps = (this.clientePerfiles || []).filter(p => p.activo && p.rol !== 'competidor');
      return ps.find(p => p.nombre === 'Sitio principal') || ps[0] || null;
    },

    lanzarDesdeSiguientePaso(tipo) {
      const p = this.perfilSiguientePaso();
      if (!p) return;
      this.openCreate({ cliente_id: this.cliente.id, profile_id: p.id, sugerencia: tipo });
    },

    // --- Search Console (decision 141) ---------------------------------
    // ------- Logs del servidor (#35, decision 213) -------
    // Se suben aqui y los lee el worker: un log de un mes son gigas. Mientras
    // haya uno leyendose, la lista se refresca sola.
    async cargarLogsSrv() {
      if (!this.cliente) return;
      const id = this.cliente.id;
      try {
        const lista = await api(`/clients/${id}/logs`);
        if (!this.cliente || this.cliente.id !== id) return;
        this.logsSrv.lista = lista;
        if (!this.logsSrv.host) this.logsSrv.host = (this.cliente.dominios || [])[0] || '';
        clearTimeout(this._logsTimer);
        if (lista.some(l => ['pendiente', 'procesando'].includes(l.estado))) {
          this._logsTimer = setTimeout(() => { if (this.view === 'client') this.cargarLogsSrv(); }, 5000);
        }
      } catch (e) { this.logsSrv.error = e.message; }
    },

    async subirLogSrv() {
      const l = this.logsSrv;
      if (!this.cliente || !l.fichero || l.ocupado) return;
      l.ocupado = true; l.error = '';
      try {
        const fd = new FormData();
        fd.append('fichero', l.fichero);
        fd.append('formato', l.formato);
        if (l.formato === 'propio') fd.append('regex', l.regex || '');
        if (l.host) fd.append('host', l.host);
        const res = await fetch(`${API}/clients/${this.cliente.id}/logs`, { method: 'POST', body: fd });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(mensajeDeError(err));
        }
        l.fichero = null;
        await this.cargarLogsSrv();
        this.showToast('Log subido: se lee en segundo plano y se aplica en el próximo análisis');
      } catch (e) {
        l.error = 'No se pudo subir: ' + e.message;
      } finally {
        l.ocupado = false;
      }
    },

    async borrarLogSrv(i) {
      if (!await this.preguntar({ titulo: 'Quitar este log', mensaje: i.en_uso ? 'Es el que usa el análisis: el próximo usará el anterior, si lo hay.' : 'El análisis no lo usa.', aceptar: 'Quitar', peligro: true })) return;
      try {
        await api(`/clients/${this.cliente.id}/logs/${i.id}`, { method: 'DELETE' });
        await this.cargarLogsSrv();
      } catch (e) { this.logsSrv.error = 'No se pudo quitar: ' + e.message; }
    },

    // ------- Backlinks del cliente (#31, decision 212) -------
    // Un CSV de Ahrefs, Semrush o Majestic. Se aplica al analizar: el proximo
    // censo lo lleva solo, y uno ya hecho, re-analizandolo.
    async cargarBacklinks() {
      if (!this.cliente) return;
      const id = this.cliente.id;
      try {
        const lista = await api(`/clients/${id}/backlinks`);
        if (this.cliente && this.cliente.id === id) this.backlinks.lista = lista;
      } catch (e) { this.backlinks.error = e.message; }
    },

    async subirBacklinks() {
      const b = this.backlinks;
      if (!this.cliente || !b.fichero || b.ocupado) return;
      b.ocupado = true; b.error = ''; b.ultimo = null;
      try {
        const fd = new FormData();
        fd.append('fichero', b.fichero);
        if (b.fecha) fd.append('fecha_dato', b.fecha);
        const res = await fetch(`${API}/clients/${this.cliente.id}/backlinks`, { method: 'POST', body: fd });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(mensajeDeError(err));
        }
        b.ultimo = await res.json();
        b.fichero = null;
        await this.cargarBacklinks();
        this.showToast('Backlinks subidos: se aplican en el próximo análisis');
      } catch (e) {
        b.error = 'No se pudieron subir: ' + e.message;
      } finally {
        b.ocupado = false;
      }
    },

    async borrarBacklinks(i) {
      if (!await this.preguntar({ titulo: 'Quitar estos backlinks',
        mensaje: i.en_uso ? 'Es la importación que usa el análisis: el próximo usará la anterior, si la hay.' : 'Es una importación anterior: el análisis no la usa.',
        aceptar: 'Quitar', peligro: true })) return;
      try {
        await api(`/clients/${this.cliente.id}/backlinks/${i.id}`, { method: 'DELETE' });
        await this.cargarBacklinks();
      } catch (e) { this.backlinks.error = 'No se pudo quitar: ' + e.message; }
    },

    async cargarGsc() {
      if (!this.cliente) return;
      const id = this.cliente.id;
      this.gsc = { estado: null, llaves: [], llave: '', propiedades: null, propiedad: '', error: '', ocupado: false };
      try {
        const [estado, llaves] = await Promise.all([api(`/clients/${id}/gsc`), api('/credenciales?tipo=gsc')]);
        if (!this.cliente || this.cliente.id !== id) return;
        this.gsc.estado = estado;
        this.gsc.llaves = llaves;
        const actual = estado.find(e => e.credencial);
        this.gsc.llave = actual ? actual.credencial : (llaves[0] ? llaves[0].nombre : '');
        this.gsc.propiedad = actual && actual.propiedad ? actual.propiedad : '';
      } catch (e) { this.gsc.error = e.message; }
    },

    async verPropiedadesGsc() {
      if (!this.gsc.llave) return;
      this.gsc.error = ''; this.gsc.propiedades = null; this.gsc.ocupado = true;
      try {
        this.gsc.propiedades = await api(`/credenciales/${this.gsc.llave}/propiedades`);
        if (!this.gsc.propiedad && this.gsc.propiedades.length === 1) this.gsc.propiedad = this.gsc.propiedades[0].propiedad;
      } catch (e) { this.gsc.error = e.message; this.gsc.propiedades = []; }
      this.gsc.ocupado = false;
    },

    // Escribe la integracion `gsc` en el formulario, guarda el cliente y pide
    // la primera sincronizacion: desde ahi la hace el worker cada noche.
    async conectarGsc() {
      if (!this.gsc.llave || !this.gsc.propiedad) return;
      let integ = this.clienteForm.integraciones.find(i => i.tipo === 'gsc');
      if (!integ) {
        this.agregarIntegracion();
        integ = this.clienteForm.integraciones[this.clienteForm.integraciones.length - 1];
      }
      integ.credencial_env = this.gsc.llave;
      integ.parametros = 'propiedad=' + this.gsc.propiedad;
      integ.activa = true;
      await this.guardarCliente(['integraciones']);
      if (this.clienteError) { this.gsc.error = this.clienteError; return; }
      await this.sincronizarGsc();
    },

    async sincronizarGsc() {
      try {
        await api(`/clients/${this.cliente.id}/gsc/sincronizar`, { method: 'POST' });
        this.showToast('Sincronización pedida: el worker la empieza en menos de un minuto');
        await this.cargarGsc();
      } catch (e) { this.gsc.error = e.message; }
    },

    // --- Slack (decision 149) ----------------------------------------------
    async cargarSlack() {
      if (!this.cliente) return;
      const id = this.cliente.id;
      this.slack = { estado: null, tokens: [], token: '', canales: null, canal: '', canalNombre: '', alertas: true, resumen: true, informe: true,
                     error: '', ocupado: false, prueba: null };
      try {
        const [estado, tokens] = await Promise.all([api(`/clients/${id}/slack`), api('/credenciales?tipo=slack')]);
        if (!this.cliente || this.cliente.id !== id) return;
        this.slack.estado = estado;
        this.slack.tokens = tokens;
        const actual = (estado.canales || [])[0];
        if (actual) {
          Object.assign(this.slack, { token: actual.credencial || '', canal: actual.canal || '', canalNombre: actual.canal_nombre || '',
                                      alertas: actual.alertas, resumen: actual.resumen, informe: actual.informe });
        } else if (tokens.length) {
          // Un token suele servir a todos los clientes: el de la agencia.
          this.slack.token = (tokens.find(t => t.valida) || tokens[0]).nombre;
        }
      } catch (e) { this.slack.error = e.message; }
    },

    async verCanalesSlack() {
      if (!this.slack.token) return;
      this.slack.error = ''; this.slack.canales = null; this.slack.ocupado = true;
      try {
        this.slack.canales = await api(`/credenciales/${this.slack.token}/canales`);
      } catch (e) { this.slack.error = e.message; this.slack.canales = []; }
      this.slack.ocupado = false;
    },

    elegirCanalSlack(id) {
      const c = (this.slack.canales || []).find(x => x.id === id);
      this.slack.canal = id;
      this.slack.canalNombre = c ? '#' + c.nombre : '';
    },

    // El manifiesto de la app de Slack (decision 149): pegarlo en «Create New
    // App → From an app manifest» deja los permisos bien sin tocar nada mas.
    // Sin rotacion de token: con ella el token caduca a las 12 horas.
    manifiestoSlack() {
      return ['display_information:',
              '  name: Crawler SEO',
              '  description: Alertas, resumen semanal e informes del crawler SEO',
              'features:',
              '  bot_user:',
              '    display_name: Crawler SEO',
              '    always_online: false',
              'oauth_config:',
              '  scopes:',
              '    bot:',
              '      - chat:write',
              '      - channels:read',
              '      - groups:read',
              'settings:',
              '  org_deploy_enabled: false',
              '  socket_mode_enabled: false',
              '  token_rotation_enabled: false'].join('\n');
    },

    copiarManifiestoSlack() {
      if (navigator.clipboard) navigator.clipboard.writeText(this.manifiestoSlack());
      this.showToast('Manifiesto copiado');
    },

    botSlack() {
      const t = (this.slack.tokens || []).find(x => x.nombre === this.slack.token);
      return t && t.bot ? t.bot : 'el bot';
    },

    async guardarSlack() {
      if (!this.slack.token || !this.slack.canal) return;
      this.slack.error = ''; this.slack.ocupado = true; this.slack.prueba = null;
      try {
        await api(`/clients/${this.cliente.id}/slack`, { method: 'PUT', body: JSON.stringify({
          credencial: this.slack.token, canal: this.slack.canal.trim(), canal_nombre: this.slack.canalNombre || null,
          alertas: this.slack.alertas, resumen: this.slack.resumen, informe: this.slack.informe }) });
        // La integracion vive en el cliente: que el formulario generico no la
        // pise con la copia de antes al guardar otra cosa.
        this._recargarFormCliente(await api(`/clients/${this.cliente.id}`));
        this.showToast('Slack guardado');
        await this.probarSlack();
        const prueba = this.slack.prueba;
        await this.cargarSlack();
        this.slack.prueba = prueba;
      } catch (e) { this.slack.error = e.message; }
      this.slack.ocupado = false;
    },

    async probarSlack() {
      this.slack.error = '';
      try {
        this.slack.prueba = await api(`/clients/${this.cliente.id}/slack/probar`, { method: 'POST' });
      } catch (e) { this.slack.error = e.message; }
    },

    async quitarSlack() {
      const ok = await this.preguntar({ titulo: 'Quitar Slack', mensaje: 'Las alertas, el resumen y los informes de este cliente dejarán de llegar a su canal.', aceptar: 'Quitar', peligro: true });
      if (!ok) return;
      try {
        await api(`/clients/${this.cliente.id}/slack`, { method: 'DELETE' });
        this._recargarFormCliente(await api(`/clients/${this.cliente.id}`));
        await this.cargarSlack();
      } catch (e) { this.slack.error = e.message; }
    },

    textoEnviosSlack(c) {
      const e = [c.alertas && 'alertas', c.resumen && 'resumen semanal', c.informe && 'informe de cada rastreo programado'].filter(Boolean);
      return e.length ? e.join(', ') : 'nada (todo desactivado)';
    },

    textoEstadoGsc(e) {
      return ({ ok: 'Sincronizado', error: 'Error', en_curso: 'Descargando…', pendiente: 'Pendiente de la primera descarga',
                sin_configurar: 'Sin configurar' })[e.estado] || e.estado;
    },

    agregarIntegracion() {
      this.clienteForm.integraciones.push({
        tipo: 'gsc', etiqueta: '', parametros: '', credencial_env: '', activa: true, configurada: null,
      });
    },

    quitarIntegracion(i) {
      this.clienteForm.integraciones.splice(i, 1);
    },

    // El prefijo que exige el servidor para la variable de cada tipo: se
    // muestra como pista, la validacion de verdad es la de la API.
    prefijoIntegracion(tipo) {
      return ({ gsc: 'GSC_', dataforseo: 'DATAFORSEO_', ahrefs: 'AHREFS_', semrush: 'SEMRUSH_',
                majestic: 'MAJESTIC_', pagespeed: 'PAGESPEED_', slack: 'SLACK_' })[tipo] || '';
    },

    // Guardar por secciones (revision de UX del 25-oct, 2.4): cada seccion
    // plegable manda solo lo suyo, para que guardar los datos no se lleve
    // tambien un borrador de la configuracion a medio hacer, ni al reves.
    // `partes`: 'datos', 'config', 'integraciones' (sin nada, todo).
    async guardarCliente(partes = null) {
      this.clienteError = '';
      const f = this.clienteForm;
      const quiere = k => !partes || partes.includes(k);
      const cuerpo = {};
      if (quiere('datos')) {
        Object.assign(cuerpo, {
          nombre: f.nombre,
          dominios: f.dominios.split('\n').map(s => s.trim()).filter(Boolean),
          zona_horaria: f.zona_horaria || null,
          notas: f.notas || null,
        });
        if (f.slug) cuerpo.slug = f.slug;
      }
      if (quiere('config') && this.cfgCliente) {
        const mal = cfgListoParaGuardar(this.cfgCliente);
        if (mal) {
          this.clienteError = mal;
          return false;
        }
        cuerpo.config_defecto = this.cfgCliente.propia;
      }
      if (quiere('integraciones')) {
        cuerpo.integraciones = f.integraciones.map(i => ({
          tipo: i.tipo,
          etiqueta: i.etiqueta || null,
          parametros: _parseKV(i.parametros, '='),
          credencial_env: (i.credencial_env || '').trim() || null,
          activa: !!i.activa,
        }));
      }
      this.cfgClienteGuardando = true;
      try {
        const c = await api(`/clients/${this.cliente.id}`, { method: 'PATCH', body: JSON.stringify(cuerpo) });
        this.clientes = await api('/clients');
        await this.abrirCliente(c.id, 'config', { guardado: partes || ['datos', 'integraciones', 'config'] });
        if (quiere('config')) await this.cargarCfgCliente();
        this.showToast(partes && partes.length === 1
          ? ({ datos: 'Datos guardados', config: 'Configuración guardada', integraciones: 'Integraciones guardadas' })[partes[0]]
          : 'Cliente guardado');
        this.cfgClienteGuardando = false;
        return true;
      } catch (e) { this.clienteError = e.message; }
      this.cfgClienteGuardando = false;
      return false;
    },

    // La config del cliente con el mismo formulario que el perfil y el
    // rastreo (decision 196): base = lo de serie.
    async cargarCfgCliente() {
      if (!this.cliente) return;
      const id = this.cliente.id;
      try {
        const { inst } = await this.cfgCargar('cliente', { cliente_id: id }, this.cliente.config_defecto || {});
        if (!this.cliente || this.cliente.id !== id) return;
        if (this.cfgCliente) inst.abiertos = this.cfgCliente.abiertos;
        this.cfgCliente = inst;
        this.cfgResolver(this.cfgCliente);
      } catch (e) { this.clienteError = e.message; }
    },

    cfgClienteCambiada() {
      return !!(this.cfgCliente && this.cliente)
        && !_cfgIgual(this.cfgCliente.propia, this.cliente.config_defecto || {});
    },

    irASeccionConfig(id) {
      const ir = () => {
        const el = document.getElementById(id);
        if (!el) return;
        if (el.tagName === 'DETAILS') el.open = true;
        el.scrollIntoView({ block: 'start' });
      };
      if (this.clienteTab !== 'config') { this.cambiarTabCliente('config'); this.$nextTick(() => setTimeout(ir, 50)); }
      else ir();
    },

    // ------- Cambios sin guardar (revision de UX del 25-oct, 3.5) -------
    // Lo editado y no guardado de la vista: en la ficha del cliente, la
    // configuracion, los datos, las integraciones y las reglas de alertas; en
    // Ajustes, un token de Slack pegado y sin guardar. Una barra fija lo dice
    // con un solo «Guardar» y salir de la vista pregunta antes de perderlo
    // (antes cada seccion tenia su boton al final y nada avisaba).
    datosClienteCambiados() {
      if (!this.cliente) return false;
      const a = this.clienteForm, b = _formCliente(this.cliente);
      return ['nombre', 'slug', 'dominios', 'zona_horaria', 'notas'].some(k => (a[k] || '').trim() !== (b[k] || '').trim());
    },
    integracionesCambiadas() {
      if (!this.cliente) return false;
      const sin = l => JSON.stringify((l || []).map(({ configurada, ...i }) => i));
      return sin(this.clienteForm.integraciones) !== sin(_formCliente(this.cliente).integraciones);
    },
    reglasCambiadas() {
      return !!(this.reglasForm && this._reglasFoto) && this._reglasDe === (this.cliente && this.cliente.id)
        && _fotoReglas(this.reglasForm) !== this._reglasFoto;
    },
    // Slack vive en las integraciones del cliente: tras guardarlo o quitarlo
    // se refrescan, pero los datos a medias se conservan (3.5).
    _recargarFormCliente(c) {
      const datos = this.datosClienteCambiados()
        ? Object.fromEntries(['nombre', 'slug', 'dominios', 'zona_horaria', 'notas'].map(k => [k, this.clienteForm[k]])) : {};
      this.cliente = c;
      this.clienteForm = Object.assign(_formCliente(c), datos);
    },
    cambiosSinGuardar() {
      const c = [];
      if (this.view === 'client' && this.cliente) {
        if (this.cfgClienteCambiada()) c.push({ id: 'config', texto: 'cómo se rastrea' });
        if (this.datosClienteCambiados()) c.push({ id: 'datos', texto: 'los datos del cliente' });
        if (this.integracionesCambiadas()) c.push({ id: 'integraciones', texto: 'las integraciones' });
        if (this.reglasCambiadas()) c.push({ id: 'reglas', texto: 'las reglas de alertas' });
      }
      if (this.view === 'ajustes' && this.ajustes && this.ajustes.slack && (this.ajustes.slack.tokenTexto || '').trim())
        c.push({ id: 'slack', texto: 'el token del bot de Slack' });
      return c;
    },
    textoCambiosSinGuardar() {
      const c = this.cambiosSinGuardar().map(x => x.texto);
      if (!c.length) return '';
      return 'Cambios sin guardar en ' + (c.length === 1 ? c[0] : c.slice(0, -1).join(', ') + ' y ' + c[c.length - 1]);
    },
    // Un solo «Guardar» para todo lo pendiente: primero las reglas (no
    // recargan la ficha) y luego lo del cliente en un solo PATCH.
    async guardarCambiosPendientes() {
      const ids = this.cambiosSinGuardar().map(x => x.id);
      if (!ids.length || this.guardandoCambios) return;
      this.guardandoCambios = true;
      try {
        if (ids.includes('slack')) { await this.subirTokenSlackAgencia(); return; }
        if (ids.includes('reglas') && !await this.guardarReglas()) {
          this.irASeccionConfig('reglas-alertas'); return;
        }
        const partes = ids.filter(x => ['config', 'datos', 'integraciones'].includes(x));
        if (partes.length) await this.guardarCliente(partes);
      } catch (e) {
        this.reglasError = e.message;
      } finally { this.guardandoCambios = false; }
    },
    descartarCambiosPendientes() {
      if (this.cliente) {
        this.clienteForm = _formCliente(this.cliente);
        if (this.cfgClienteCambiada()) this.cargarCfgCliente();
        if (this.reglasCliente && this.reglasCambiadas()) {
          this.reglasForm = JSON.parse(JSON.stringify(this.reglasCliente.efectivas));
          this.reglasForm.propias.forEach(x => { x.segmento = x.segmento || ''; });
          this._reglasFoto = _fotoReglas(this.reglasForm);
        }
      }
      if (this.ajustes && this.ajustes.slack) this.ajustes.slack.tokenTexto = '';
    },
    // ¿La ruta `destino` deja atras lo que esta sin guardar? Cambiar de
    // pestaña dentro del mismo cliente no: los formularios siguen ahi y la
    // barra tambien.
    _saleDeLosCambios(destino) {
      const ruta = (destino || '').replace(/^#/, '').split('?')[0];
      if (this.view === 'client' && this.cliente) return !ruta.startsWith('/clientes/' + this.cliente.id);
      if (this.view === 'ajustes') return ruta !== '/ajustes';
      return true;
    },
    // Atras, adelante o un enlace con cambios sin guardar: se vuelve a la
    // ruta de antes y se pregunta. Si se aceptan perder, se descartan y se va.
    async _alCambiarRuta() {
      const destino = location.hash;
      if (this.cambiosSinGuardar().length && this._saleDeLosCambios(destino)) {
        const aqui = this._ruta();
        if (aqui && aqui !== destino) history.pushState(null, '', aqui);
        const ok = await this.preguntar({
          titulo: 'Hay cambios sin guardar',
          mensaje: this.textoCambiosSinGuardar() + '. Si sales ahora, se pierden.',
          aceptar: 'Salir sin guardar', peligro: true,
        });
        if (!ok) return;
        this.descartarCambiosPendientes();
        history.pushState(null, '', destino);
      }
      await this._irARuta(destino);
    },
    // El modal del perfil: cerrar con cambios pregunta antes (3.5).
    perfilCambiado() {
      if (!this.perfilForm) return false;
      return JSON.stringify(this.perfilForm) !== this._perfilFoto
        || !!(this.cfgPerfil && !_cfgIgual(this.cfgPerfil.propia, this._perfilCfgBase || {}));
    },
    async cerrarPerfil() {
      // Escape con la pregunta abierta la cierra a ella, no abre otra.
      if (this.dialogo) return;
      if (this.perfilCambiado() && !await this.preguntar({
        titulo: 'Descartar los cambios del perfil',
        mensaje: 'Lo que has cambiado en este perfil no se ha guardado y se perderá.',
        aceptar: 'Descartar', peligro: true,
      })) return;
      this.perfilForm = null;
      this.cfgPerfil = null;
    },
    // El nombre de una regla en llano, para «sin evaluar»: las propias por su
    // nombre y las de la comparacion por su frase (fmt.reglaDiff).
    nombreRegla(id) {
      const p = ((this.reglasForm && this.reglasForm.propias) || []).find(r => r.id === id);
      if (p) return p.nombre || this.fraseRegla(p);
      return fmt.reglaDiff(id);
    },
    // La pregunta de la IA que corresponde a un tipo de Problemas, al reves
    // que PROBLEMA_PREGUNTA_IA: la salida de la pestaña IA a Problemas (V32).
    problemaDePreguntaIA(preg) {
      const e = Object.entries(PROBLEMA_PREGUNTA_IA).find(([, v]) => v.pregunta === preg);
      return e ? e[0] : null;
    },
    // Un boton principal por vista (revision de UX del 25-oct, 3.5): el
    // «Nuevo rastreo» de arriba solo es el verde donde la vista no tiene uno
    // propio (Nuevo cliente, Nueva programacion, Informe para el cliente).
    principalPropia() {
      return ['clients', 'programados', 'detail', 'client'].includes(this.view);
    },

    // Una linea junto al titulo de cada seccion plegada: su estado.
    resumenSeccionConfig(id) {
      const c = this.cliente;
      if (!c) return '';
      if (id === 'cfg-perfiles') {
        const n = (this.clientePerfiles || []).length;
        const prog = (this.clienteProgramaciones || []).filter(g => g.activa).length;
        return (n === 1 ? '1 perfil' : fmt.num(n) + ' perfiles') + ' · '
          + (prog ? (prog === 1 ? '1 programación activa' : fmt.num(prog) + ' programaciones activas') : 'nada programado');
      }
      if (id === 'cfg-rastreo') {
        const i = this.cfgCliente;
        const n = i ? CAMPOS_CONFIG.filter(x => cfgTiene(i, x.ruta)).length : Object.keys(c.config_defecto || {}).length;
        if (!i) return '';
        const partes = partesResumenConfig(i, ['concurrent_requests_per_domain', 'render_js']);
        partes.push(n ? (n === 1 ? '1 cambio sobre lo de serie' : n + ' cambios sobre lo de serie') : 'lo de serie');
        const fuera = cfgClavesFuera(i);
        if (fuera.length) partes.push('además ' + fuera.join(', ') + ' en «Avanzado»');
        return partes.join(' · ');
      }
      if (id === 'cfg-datos') return (c.dominios || []).join(', ') || 'sin dominios';
      if (id === 'cfg-gsc') {
        const e = ((this.gsc && this.gsc.estado) || []).find(x => x.propiedad);
        if (e) return this.textoEstadoGsc(e) + ' · ' + e.propiedad;
        return (c.integraciones || []).some(i => i.tipo === 'gsc') ? '' : 'sin conectar';
      }
      if (id === 'cfg-logs') {
        const l = ((this.logsSrv && this.logsSrv.lista) || [])[0];
        if (!l) return 'sin subir';
        if (l.estado !== 'hecho') return TEXTO_ESTADO_LOG[l.estado] || l.estado;
        return 'del ' + fmt.dia(l.desde) + ' al ' + fmt.dia(l.hasta);
      }
      if (id === 'cfg-backlinks') {
        const u = ((this.backlinks && this.backlinks.lista) || [])[0];
        return u ? fmt.num(u.filas) + ' backlinks de ' + (FUENTE_BACKLINKS[u.fuente] || u.fuente) + ' · subidos el ' + fmt.dia(u.subido) : 'sin subir';
      }
      if (id === 'cfg-slack') {
        const canal = ((this.slack && this.slack.estado && this.slack.estado.canales) || [])[0];
        if (canal) return (canal.canal_nombre || canal.canal) + ' · ' + this.textoEnviosSlack(canal);
        return (c.integraciones || []).some(i => i.tipo === 'slack') ? '' : 'sin conectar';
      }
      if (id === 'cfg-enlace') {
        const vivos = (this.enlaces || []).filter(e => !e.revocado_en).length;
        return vivos ? (vivos === 1 ? '1 enlace activo' : vivos + ' enlaces activos') : 'ninguno activo';
      }
      if (id === 'cfg-integraciones') {
        const otras = (c.integraciones || []).filter(i => !['gsc', 'slack'].includes(i.tipo)).length;
        return otras ? (otras === 1 ? '1 integración' : otras + ' integraciones') : 'ninguna';
      }
      if (id === 'reglas-alertas') {
        if (!this.reglasCliente) return '';
        return this.reglasCliente.guardadas ? 'reglas propias sobre las de serie' : 'las de serie';
      }
      return '';
    },

    async borrarCliente() {
      if (!this.cliente) return;
      // Se pide el slug escrito: un borrado que se lleva perfiles e
      // integraciones no puede salir de un clic suelto. Los rastreos NO se
      // borran desde aqui: son censos entregados y quedan sin cliente.
      const ok = await this.preguntar({
        titulo: `Borrar el cliente «${this.cliente.nombre}»`,
        mensaje: `Se borran el cliente y sus perfiles. Sus ${this.cliente.n_jobs} rastreos NO se borran: quedan sin cliente.`,
        aceptar: 'Borrar cliente', peligro: true, escribir: this.cliente.slug,
      });
      if (!ok) return;
      const slug = this.cliente.slug;
      try {
        await api(`/clients/${this.cliente.id}?confirmar=${encodeURIComponent(slug)}`, { method: 'DELETE' });
        this.cliente = null;
        await this.verClientes();
        this.showToast('Cliente borrado');
      } catch (e) { this.clienteError = e.message; }
    },

    async nuevoPerfil() {
      this.perfilError = '';
      this.cfgPerfil = null;
      this.perfilForm = { id: null, nombre: '', rol: 'propio', seeds: '', notas: '', activo: true };
      this._perfilFoto = JSON.stringify(this.perfilForm); this._perfilCfgBase = {};
      await this._cargarCfgPerfil(null, {});
    },

    async editarPerfil(p) {
      this.perfilError = '';
      this.cfgPerfil = null;
      this.perfilForm = {
        id: p.id, nombre: p.nombre, rol: p.rol, seeds: (p.seeds || []).join('\n'),
        notas: p.notas || '', activo: p.activo,
      };
      this._perfilFoto = JSON.stringify(this.perfilForm); this._perfilCfgBase = p.config || {};
      await this._cargarCfgPerfil(p.id, p.config || {});
    },

    // La config del perfil con el mismo formulario que el cliente y el
    // rastreo (decision 196): base = el cliente ya resuelto.
    async _cargarCfgPerfil(profileId, propia) {
      try {
        const { inst } = await this.cfgCargar('perfil', { cliente_id: this.cliente.id, profile_id: profileId }, propia);
        if (!this.perfilForm) return;
        this.cfgPerfil = inst;
        this.cfgResolver(this.cfgPerfil);
      } catch (e) { this.perfilError = e.message; }
    },

    // «Así rastreará» en la tarjeta del perfil: lo guardado, resuelto por la
    // API (GET config-resuelta con el perfil), con su procedencia y avisos.
    async cargarAsiPerfil(p) {
      if (!this.cliente) return;
      try {
        const r = await api(`/clients/${this.cliente.id}/config-resuelta?profile_id=${p.id}`);
        this.asiPerfiles = { ...this.asiPerfiles, [p.id]: { nivel: 'vista', resuelta: r } };
      } catch (e) {
        this.asiPerfiles = { ...this.asiPerfiles, [p.id]: { nivel: 'vista', error: e.message } };
      }
    },

    async guardarPerfil() {
      this.perfilError = '';
      const f = this.perfilForm;
      const i = this.cfgPerfil;
      const mal = cfgListoParaGuardar(i);
      if (mal) {
        this.perfilError = mal;
        return;
      }
      const cuerpo = {
        nombre: f.nombre, rol: f.rol,
        seeds: f.seeds.split('\n').map(s => s.trim()).filter(Boolean),
        notas: f.notas || null, activo: !!f.activo,
      };
      // Sin la config cargada (fallo al pedirla) no se manda: no se pisa la
      // guardada con un {} vacio.
      if (i) cuerpo.config = i.propia;
      const base = `/clients/${this.cliente.id}/profiles`;
      try {
        if (f.id) await api(`${base}/${f.id}`, { method: 'PATCH', body: JSON.stringify(cuerpo) });
        else await api(base, { method: 'POST', body: JSON.stringify(cuerpo) });
        this.perfilForm = null;
        this.cfgPerfil = null;
        await this.abrirCliente(this.cliente.id, 'config');
      } catch (e) { this.perfilError = e.message; }
    },

    async borrarPerfil(p) {
      if (!await this.preguntar({ titulo: `Eliminar el perfil «${p.nombre}»`,
        mensaje: 'Se quita también su programación, si la tiene. Sus rastreos NO se borran: quedan colgados del cliente.', aceptar: 'Eliminar perfil', peligro: true })) return;
      try {
        await api(`/clients/${this.cliente.id}/profiles/${p.id}`, { method: 'DELETE' });
        await this.abrirCliente(this.cliente.id, 'config');
      } catch (e) { this.clienteError = e.message; }
    },

    serieVisible() {
      return this.serieSoloCensos ? this.clienteSerie.filter(j => j.tipo === 'censo') : this.clienteSerie;
    },

    nombreDePerfil(id) {
      const p = this.clientePerfiles.find(x => x.id === id);
      return p ? p.nombre : '';
    },

    // ------- Detalle del trabajo -------
    async openJob(id) {
      this._stopSemanticPoll();
      this.view = 'detail';
      this.detailTab = 'overview';
      this.stats = null;
      this.progress = null;
      this.insights = null;
      this.expandedCategories = {};
      this.semanticResults = null;
      this.semanticError = null;
      this.semanticProgress = null;
      this.cannibalPairs = [];
      this.cannibalHasQueryData = false;
      this.cannibalFilter = 'all';
      this.driftData = [];
      this.gapResults = null;
      this.gapTopic = '';
      this.targetResults = null;
      this.targetTheme = '';
      this.gscFetchResult = null;
      this.cleaningGroups = [];
      this.cleaningSelectedGroup = null;
      this.cleaningPreview = null;
      this.cleaningRulesets = [];
      this.cleaningError = null;
      this.cleaningMessage = null;
      this._pararEnriq();
      this.enriqRuns = []; this.enriqRun = null; this.enriqDecisiones = null; this.enriqPlantillas = null; this.enriqIntencion = null;
      this.iaProblemas = null; this.iaUrl = null; this._decisionesIA = {};
      this.urls = []; this.issues = []; this.links = [];
      this.issueFilters = { severity: '', issue_type: '' };
      this.issuesResumen = null; this.issuesVista = 'tipos'; this.grupoAbierto = {};
      this.versionAnterior = null; this.cuentaSinFiltro = null;
      this.principales = null;
      this.segmentosJob = null; this.issuesSegmento = '';
      this.linksPage = 1; this.issuesPage = 1;
      this._reiniciarEnlaces();
      this.diff = null; this.diffOtro = ''; this.diffCandidatos = []; this._diffPedido++;
      this._migReiniciar();
      this.veredicto = null;
      this.urlsTotal = 0; this.issuesTotal = 0; this.linksTotal = 0;
      this.loading = true;
      try {
        this.job = await api(`/jobs/${id}`);
        this._registrarAMedida(this.job);
        await this.loadStats();
        this._startProgress();
        this.cargarEjecuciones();
        this.cargarResumenAMedida();
        this.cargarVeredicto();
      } catch (e) { this.error = e.message; }
      this.loading = false;
      window.scrollTo({ top: 0, behavior: 'smooth' });
      this.$nextTick(() => lucide.createIcons());
      // Una ficha pedida desde fuera del censo (Google del Estado del cliente).
      const pend = this._fichaPendiente;
      this._fichaPendiente = null;
      if (pend && this.job && this.job.id === pend.jobId) this.abrirFichaPorUrl(pend.url);
    },

    // La ficha de una URL de otro censo (las frases de Google del Estado del
    // cliente, 3.3): se abre el censo y, al cargarlo, su ficha. Si ese censo
    // ya esta cargado (se abrio antes y se volvio a la ficha del cliente, que
    // no limpia `job`), el enrutador no llama a openJob: se abre la ficha
    // directamente. Antes se quedaba en el Resumen y la peticion pendiente
    // abria esa ficha mas tarde, al cargar el censo desde otro (revision del 27-oct).
    abrirFichaDeCenso(jobId, url) {
      if (this.job && this.job.id === jobId) { this._fichaPendiente = null; return this.abrirFichaPorUrl(url); }
      this._fichaPendiente = { jobId, url };
      location.hash = '#/rastreos/' + jobId;
    },

    backToJobs() {
      this._salirDeJob();
      this.view = 'jobs';
      this.loadJobs();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    async loadStats() {
      if (!this.job) return;
      try {
        this.stats = await api(`/jobs/${this.job.id}/stats`);
      } catch { this.stats = null; }
      if (this.view === 'explorer') this.loadExplorerBadges();
      // Que bloquea cada bot por host (decision 129). Aparte: sin la tabla
      // robots_txt (un censo viejo) la ficha sale igual.
      try {
        this.robotsBots = await api(`/jobs/${this.job.id}/robots`);
      } catch { this.robotsBots = null; }
      // axe por muestra de plantilla (decision 174): solo pinta algo si el
      // job lo pidio o trae capturas; si falla, la ficha sale igual.
      try {
        this.accesibilidad = await api(`/jobs/${this.job.id}/accesibilidad`);
      } catch { this.accesibilidad = null; }
    },

    // ------- Polling de progreso -------
    _startProgress() {
      this._stopProgress();
      // 'analyzing' is a non-terminal phase after the crawl while the analyzer
      // populates issues/indexability/pagerank — keep polling through it.
      if (!this.job || !['pending','running','analyzing'].includes(this.job.status)) return;
      const poll = async () => {
        try {
          this.progress = await api(`/jobs/${this.job.id}/progress`);
          if (this.progress.status !== this.job.status) {
            this.job.status = this.progress.status;
            if (['completed','failed','cancelled'].includes(this.progress.status)) {
              this._stopProgress();
              this.job = await api(`/jobs/${this.job.id}`);
              // Analysis just finished: drop cached tab data so the active
              // tab refetches fresh issues/insights instead of the empty/
              // partial snapshot loaded mid-analysis. Antes de loadStats: la
              // barra del Explorador se recuenta ahi y no debe leer el
              // resumen de problemas de mitad de rastreo (revision de UX del
              // 25-oct, 3.4).
              this._invalidateResultCaches();
              await this.loadStats();
              this.cargarVeredicto();
              this._reloadActiveTab();
              if (this.view === 'explorer') this.loadExplorerUrls();
            }
          }
        } catch {}
      };
      poll();
      this.progressTimer = setInterval(poll, 2000);
    },

    _invalidateResultCaches() {
      this.insights = null;
      this.principales = null;  // «Qué arreglar primero»: lo que se pidio con el censo a medias
      this.issues = []; this.issuesPage = 1;
      this.links = []; this.linksPage = 1;
      this.urls = []; this.urlsPage = 1;
      // Lo contado con el rastreo a medias: la barra del Explorador y el
      // resumen de problemas del que saca sus ambitos (revision de UX del
      // 25-oct, 3.4).
      this.issuesResumen = null;
      this._expContadores = null;
    },

    _reloadActiveTab() {
      const t = this.detailTab;
      if (t === 'overview') this.cargarPrincipales();
      if (t === 'issues' && !this.issuesResumen) this.loadIssuesResumen();
      if (t === 'urls') this.loadUrls();
      else if (t === 'issues') this.loadIssues();
      else if (t === 'links') this.loadLinks();
      else if (t === 'insights') this.loadInsights();
    },

    _stopProgress() {
      if (this.progressTimer) { clearInterval(this.progressTimer); this.progressTimer = null; }
    },

    _stopSemanticPoll() {
      if (this.semanticPollTimer) { clearInterval(this.semanticPollTimer); this.semanticPollTimer = null; }
    },

    // ------- Dialogos propios (UX-21) -------
    // Sustituyen a confirm(), alert() y prompt(): los nativos bloquean la
    // pagina entera (y las pruebas automaticas), no se pueden leer con calma
    // y no dicen que es irreversible con el peso que merece.
    // `escribir`: texto que hay que teclear para habilitar el boton (borrados
    // que se llevan mucho por delante). Devuelve true/false.
    // `pedir`: etiqueta de un campo de texto libre; entonces devuelve el texto
    // escrito (o false si se cancela).
    preguntar({ titulo, mensaje, aceptar = 'Aceptar', peligro = false, escribir = '', solo_aviso = false, pedir = '', valor = '' }) {
      return new Promise(resolver => {
        this.dialogo = { titulo, mensaje, aceptar, peligro, escribir, entrada: valor, solo_aviso, pedir, resolver };
        this.$nextTick(() => {
          const el = document.querySelector('.dialogo [data-foco]');
          if (el) el.focus();
        });
      });
    },
    avisar(titulo, mensaje) {
      return this.preguntar({ titulo, mensaje, aceptar: 'Entendido', solo_aviso: true });
    },
    cerrarDialogo(respuesta) {
      const d = this.dialogo;
      if (!d) return;
      if (respuesta && d.escribir && d.entrada.trim() !== d.escribir) return;
      if (respuesta && d.pedir && !d.entrada.trim()) return;
      this.dialogo = null;
      d.resolver(d.pedir ? (respuesta ? d.entrada.trim() : false) : !!respuesta);
    },

    // ------- Nombre, tipo y cliente (UX-07/08) -------
    async abrirEditarJob() {
      if (!this.job) return;
      this.editarError = '';
      try { if (!this.clientes.length) this.clientes = await api('/clients'); } catch (_) {}
      this.editarJob = {
        name: this.job.name,
        tipo: this.job.tipo_efectivo || 'censo',
        cliente_id: this.job.cliente_id || '',
      };
    },

    async guardarJob() {
      const e = this.editarJob;
      const cuerpo = { name: e.name, cliente_id: e.cliente_id || null };
      // Solo se marca a mano si cambia lo deducido: asi un rastreo que se
      // llama «CANARY» y se deja como canario sigue deduciendose del nombre.
      if (e.tipo !== this.job.tipo_efectivo || this.job.tipo) cuerpo.tipo = e.tipo;
      try {
        this.job = await api(`/jobs/${this.job.id}`, { method: 'PATCH', body: JSON.stringify(cuerpo) });
        this.editarJob = null;
        this.panelClientes = null;
        this.showToast('Rastreo actualizado');
      } catch (err) { this.editarError = err.message; }
    },

    // ------- Cancelar / Eliminar -------
    async cancelJob() {
      if (!this.job || !await this.preguntar({ titulo: 'Cancelar este rastreo',
        mensaje: 'El crawler se detendrá en cuanto procese la señal. Lo rastreado hasta ahora se conserva y se puede reanudar.',
        aceptar: 'Cancelar el rastreo', peligro: true })) return;
      try {
        this.job = await api(`/jobs/${this.job.id}/cancel`, { method: 'PATCH' });
        this._stopProgress();
      } catch (e) { this.avisar('No se pudo cancelar', e.message); }
    },

    async deleteJob() {
      if (!this.job || !await this.preguntar({ titulo: 'Eliminar este rastreo',
        mensaje: `Se borran «${this.job.name}» y todos sus datos: URLs, enlaces, incidencias y comparaciones. No se puede deshacer. Si es un censo entregado, descarga antes el backup (Exportar → Backup completo).`,
        aceptar: 'Eliminar para siempre', peligro: true, escribir: 'eliminar' })) return;
      try {
        await api(`/jobs/${this.job.id}`, { method: 'DELETE' });
        this.showToast('Trabajo eliminado', 'info');
        this.backToJobs();
      } catch (e) { this.avisar('No se pudo eliminar', e.message); }
    },

    // ------- Pestanas -------
    // ------- Comparar con otro censo (#32) -------
    // Solo el seguimiento entre censos: el mapeo de una migracion es una
    // accion aparte, «Validar migración» (revision de UX del 25-oct, 2.13).
    diff: null,
    diffOtro: '',
    diffCandidatos: [],
    diffCargando: false,
    _diffPedido: 0,

    // Lo que se pinta en Comparar (V21). El diff pedido si ya ha llegado; si
    // no, y se compara con el censo de la comparacion automatica, lo que esta
    // guardado de ella (`job.comparacion`: alertas, URLs, incidencias,
    // avisos), al instante. Lo que no se guarda (que cambio pagina a pagina,
    // la extraccion a medida, los ejemplos) llega con el diff, con un
    // indicador de carga a la vista. Las incidencias guardadas solo se
    // ensenan si se puede afirmar que siguen valiendo: los dos censos con la
    // version del analisis con la que se compararon (decision 191). Si
    // cualquiera de los dos se volvio a analizar, ya no son las que se
    // compararon (`_incidenciasViejas`); si la comparacion es de antes de la
    // 191 (sin sello) o aun no se sabe la version del anterior, se esperan al
    // diff (`_incidenciasPendientes`; revision de UX del 25-oct, 2.13,
    // hallazgo de la revision).
    diffVista() {
      if (this.diff && this.diff._para === this.diffOtro) return this.diff;
      const j = this.job, c = j && j.comparacion;
      if (!c || !this.diffOtro || c.comparado_con !== this.diffOtro) return null;
      const va = this.versionAnterior && this.versionAnterior.jobId === j.id ? this.versionAnterior : null;
      const firmaVa = va ? String(va.version) + '|' + (va.error ? 'e' : '') : '';
      // Fuera del estado de Alpine: escribir estado reactivo mientras se pinta
      // volveria a disparar el pintado.
      if (_diffGuardadoCache.jobId === j.id && _diffGuardadoCache.c === c && _diffGuardadoCache.va === firmaVa) {
        return _diffGuardadoCache.valor;
      }
      let viejas = null;
      if (c.analisis_version && j.analisis_version && c.analisis_version !== j.analisis_version) viejas = 'este';
      else if (c.analisis_version_anterior && va && va.version && va.version !== c.analisis_version_anterior) viejas = 'anterior';
      const vigentes = !viejas && !!(c.analisis_version && c.analisis_version === j.analisis_version
        && c.analisis_version_anterior && va && !va.error && va.version === c.analisis_version_anterior);
      const valor = {
        ...c, _clave: 'g-' + j.id, _jobId: j.id, _guardada: true, _incidenciasViejas: viejas,
        _incidenciasPendientes: !viejas && !vigentes && !!c.incidencias,
        incidencias: vigentes ? c.incidencias : null, cambios: null, extraido: null,
        antes: { fecha: c.fecha_anterior, nombre: c.nombre_anterior },
        ahora: { fecha: j.started_at || j.created_at, nombre: j.name },
      };
      Object.assign(_diffGuardadoCache, { jobId: j.id, c, va: firmaVa, valor });
      return valor;
    },

    // Las nuevas de un tipo, separadas entre URL que ya estaba (algo se ha
    // roto) y URL nueva (algo se ha publicado mal), decision 131.
    nuevasPorUrl(tipo, d = this.diff) {
      const n = d && d.incidencias && d.incidencias.nuevas;
      if (!n || !n.en_url_existente) return null;
      const de = l => ((l.por_tipo || []).find(f => f.tipo === tipo) || {}).total || 0;
      return { existente: de(n.en_url_existente), nueva: de(n.en_url_nueva) };
    },

    // Las tres columnas (resueltas / nuevas / siguen) en una sola fila por
    // tipo: tres tablas separadas obligan a cruzarlas a ojo, que es lo que
    // nadie hace.
    tiposDeIncidencia(d = this.diff) {
      const inc = d && d.incidencias;
      if (!inc) return [];
      const filas = {};
      const meter = (lista, campo) => (lista || []).forEach(f => {
        const fila = filas[f.tipo] || (filas[f.tipo] = {
          tipo: f.tipo, severidad: f.severidad,
          resueltas: 0, nuevas: 0, siguen: 0,
        });
        fila[campo] = f.total;
      });
      meter(inc.resueltas && inc.resueltas.por_tipo, 'resueltas');
      meter(inc.nuevas && inc.nuevas.por_tipo, 'nuevas');
      meter(inc.siguen && inc.siguen.por_tipo, 'siguen');
      const orden = { error: 0, warning: 1, info: 2 };
      return Object.values(filas).sort((a, b) =>
        (orden[a.severidad] ?? 3) - (orden[b.severidad] ?? 3)
        || (b.nuevas + b.resueltas) - (a.nuevas + a.resueltas));
    },
    // --- Rastreos programados ---
    // Desde la ficha de un rastreo (revision de UX del 25-oct, 2.2): si tiene
    // cliente, se propone programar su PERFIL (el suyo, o el del cliente con
    // las mismas semillas), que hereda los cambios en cada disparo. La copia
    // fija de antes queda como segunda opcion dentro del formulario, y es la
    // unica para un rastreo sin cliente.
    abrirProgramar() {
      if (this.job && this.job.cliente_id) {
        this.abrirNuevaProgramacion({ cliente_id: this.job.cliente_id, profile_id: this.job.profile_id || '',
                                      desdeJob: this.job });
        return;
      }
      this.abrirCopiaFija();
    },

    abrirCopiaFija() {
      // El nombre por defecto quita la fecha del rastreo de origen: la
      // programacion le pone la suya a cada ejecucion.
      this.progForm = null;
      this.programarNombre = (this.job.name || '').replace(/\s*[·-]\s*\d{4}-\d{2}-\d{2}.*$/, '');
      this.programarError = '';
      this.programarAbierto = true;
    },

    // Nueva programacion colgada de un perfil. `preset`: { cliente_id,
    // profile_id, cron, desdeJob }.
    async abrirNuevaProgramacion(preset = {}) {
      this.progForm = {
        id: null, hereda: true, cliente_id: preset.cliente_id || '', profile_id: preset.profile_id || '',
        nombre: '', ..._cuandoDesdeCron(preset.cron || '0 3 * * 1'), zona: 'Europe/Madrid',
        perfiles: [], existentes: [], error: '', guardando: false, creandoPerfil: false,
        desdeJob: preset.desdeJob || null, avisosPerfil: [],
      };
      this.$nextTick(() => window.lucide && lucide.createIcons());
      try { if (!this.clientes.length) this.clientes = await api('/clients'); } catch (_) { /* sin lista */ }
      if (this.progForm && this.progForm.cliente_id) await this.progCambiarCliente(preset.profile_id || '');
    },

    editarProgramacion(p) {
      this.progForm = {
        id: p.id, hereda: !!p.hereda_perfil, cliente_id: p.cliente_id || '', profile_id: p.profile_id || '',
        nombre: p.nombre, ..._cuandoDesdeCron(p.cron), zona: p.zona_horaria || 'Europe/Madrid',
        perfiles: [], existentes: [], error: '', guardando: false, creandoPerfil: false, desdeJob: null,
        // Con una API anterior (sin n_semillas ni cliente_nombre) se cuentan
        // las semillas y se usa el slug: no decir «0 semillas» ni «Sin cliente».
        perfilNombre: p.perfil_nombre, clienteNombre: p.cliente_nombre || p.client_id,
        n_semillas: p.n_semillas ?? (p.seeds || []).length,
      };
      this.$nextTick(() => window.lucide && lucide.createIcons());
    },

    async progCambiarCliente(profileId = '') {
      const f = this.progForm;
      if (!f) return;
      f.perfiles = []; f.existentes = []; f.profile_id = profileId; f.error = '';
      if (!f.cliente_id) return;
      const id = f.cliente_id;
      try {
        const [perfiles, existentes] = await Promise.all([
          api(`/clients/${id}/profiles`), api(`/programaciones?cliente_id=${id}&resumen=true`)]);
        if (this.progForm !== f || f.cliente_id !== id) return;
        f.perfiles = perfiles;
        // Una API anterior ignora `?cliente_id=` y las devuelve todas: se
        // filtra tambien aqui (revision del 27-oct).
        f.existentes = existentes.filter(p => p.cliente_id === id);
      } catch (e) { f.error = e.message; return; }
      if (!f.profile_id && f.desdeJob) {
        const igual = f.perfiles.find(p => _mismasSemillas(p.seeds, f.desdeJob.seeds));
        if (igual) f.profile_id = igual.id;
      }
      // Desde un rastreo no se elige un perfil que no tiene sus semillas:
      // se ofrece crear uno (o la copia fija) en vez de programar otra cosa.
      if (!f.profile_id && !f.desdeJob && f.perfiles.length === 1) f.profile_id = f.perfiles[0].id;
    },

    // Las horas del desplegable, de cuarto en cuarto; si la programacion
    // tiene otro minuto (las 11:07), tambien esa, para no cambiarla al editar.
    progHoras() {
      const h = [];
      for (let i = 0; i < 96; i++) h.push(String(Math.floor(i / 4)).padStart(2, '0') + ':' + String((i % 4) * 15).padStart(2, '0'));
      const actual = this.progForm && this.progForm.hora;
      if (actual && !h.includes(actual)) { h.push(actual); h.sort(); }
      return h;
    },

    progPerfil() {
      const f = this.progForm;
      return f ? (f.perfiles.find(p => p.id === f.profile_id) || null) : null;
    },

    progCron() { return this.progForm ? _cronDesdeCuando(this.progForm) : ''; },

    // Las activas del mismo perfil que ya hay: se avisa antes de guardar
    // otra (V06: Lopesan tuvo dos semanales activas a la vez).
    progYaProgramadas() {
      const f = this.progForm;
      if (!f || !f.profile_id) return [];
      return (f.existentes || []).filter(p => p.activa && p.id !== f.id && p.profile_id === f.profile_id);
    },

    // Desde un rastreo cuyo cliente no tiene un perfil con sus semillas: se
    // crea uno con ellas y con lo que la config del rastreo tiene de distinto
    // respecto al cliente (`desde_job_id`; revision de UX del 25-oct, 2.2: sin
    // eso, un censo con exclusiones propias se programaba sin ellas).
    async progCrearPerfilDesdeJob() {
      const f = this.progForm;
      if (!f || !f.desdeJob) return;
      f.creandoPerfil = true; f.error = '';
      const usados = new Set(f.perfiles.map(p => p.nombre));
      let nombre = 'Sitio completo', n = 2;
      while (usados.has(nombre)) nombre = 'Sitio completo ' + (n++);
      try {
        const p = await api(`/clients/${f.cliente_id}/profiles`, { method: 'POST',
          body: JSON.stringify({ nombre, seeds: f.desdeJob.seeds, desde_job_id: f.desdeJob.id }) });
        await this.progCambiarCliente(p.id);
        if (this.progForm === f) f.avisosPerfil = p.avisos || [];
        this.showToast('Perfil «' + p.nombre + '» creado con la configuración de este rastreo');
      } catch (e) { f.error = e.message; }
      f.creandoPerfil = false;
    },

    async guardarProgForm() {
      const f = this.progForm;
      if (!f) return;
      f.error = '';
      const cron = this.progCron();
      if (!cron) { f.error = 'Falta cuándo se repite.'; return; }
      f.guardando = true;
      try {
        if (f.id) {
          const cuerpo = { cron, zona_horaria: f.zona || 'Europe/Madrid' };
          if (f.nombre && f.nombre.trim()) cuerpo.nombre = f.nombre.trim();
          await api('/programaciones/' + f.id, { method: 'PATCH', body: JSON.stringify(cuerpo) });
        } else {
          if (!f.profile_id) { f.error = 'Elige el perfil que se repite.'; f.guardando = false; return; }
          const cuerpo = { profile_id: f.profile_id, cron, zona_horaria: f.zona || 'Europe/Madrid' };
          if (f.nombre && f.nombre.trim()) cuerpo.nombre = f.nombre.trim();
          await api('/programaciones', { method: 'POST', body: JSON.stringify(cuerpo) });
        }
        const cliente = f.cliente_id;
        this.progForm = null;
        this.showToast(f.id ? 'Programación guardada' : 'Programado: ' + fmt.cron(cron));
        if (this.view === 'programados' || this.view === 'produccion') await this.cargarProgramaciones();
        if (this.view === 'client' && this.cliente && this.cliente.id === cliente) await this.cargarProgramacionesCliente();
      } catch (e) {
        // El mensaje se queda EN el modal (como en la copia fija).
        f.error = e.message;
      }
      if (this.progForm) this.progForm.guardando = false;
    },

    async cargarProgramacionesCliente() {
      if (!this.cliente) return;
      const id = this.cliente.id;
      try {
        const l = await api(`/programaciones?cliente_id=${id}&resumen=true`);
        // Una API anterior ignora `?cliente_id=` y devuelve las de todos: en
        // «Programaciones sin perfil» de Lopesan salia la de workoholics.es.
        // Se filtra tambien aqui por el cliente de cada una (revision del 27-oct).
        if (this.cliente && this.cliente.id === id) this.clienteProgramaciones = l.filter(p => p.cliente_id === id);
      } catch (_) { this.clienteProgramaciones = []; }
    },

    programacionesDePerfil(pid) {
      return (this.clienteProgramaciones || []).filter(p => p.profile_id === pid);
    },

    // Las de copia fija del cliente que no cuelgan de ningun perfil: se
    // enseñan aparte para que no queden escondidas (V06).
    programacionesSinPerfil() {
      return (this.clienteProgramaciones || []).filter(p => !p.profile_id);
    },

    // Grupos de programaciones activas que se repiten, para el aviso de
    // Programados: cada pareja una sola vez.
    gruposRepetidos() {
      const vistos = new Set(), grupos = [];
      for (const p of this.programaciones) {
        if (!p.activa || !(p.repetida_con || []).length || vistos.has(p.id)) continue;
        const ids = [p.id, ...p.repetida_con.map(r => r.id)];
        ids.forEach(i => vistos.add(i));
        grupos.push({ cliente: p.cliente_nombre || p.client_id || 'sin cliente', motivo: p.repetida_con[0].motivo,
                      nombres: ids.map(i => (this.programaciones.find(x => x.id === i) || {}).nombre).filter(Boolean),
                      cuando: ids.map(i => this.programaciones.find(x => x.id === i)).filter(Boolean).map(x => fmt.cron(x.cron)) });
      }
      return grupos;
    },

    async guardarProgramacion() {
      this.programarError = '';
      try {
        await api('/programaciones', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            nombre: this.programarNombre,
            client_id: this.job.client_id,
            cliente_id: this.job.cliente_id || null,
            profile_id: this.job.profile_id || null,
            seeds: this.job.seeds,
            config: this.job.config || {},
            cron: this.programarCron,
            zona_horaria: this.programarZona,
          }),
        });
        this.programarAbierto = false;
        await this.verProgramados();
      } catch (e) {
        // El mensaje se queda EN el modal: si se cierra, quien escribio una
        // expresion mal no ve por que no se guardo.
        this.programarError = e.message;
      }
    },
    // ------- Revisar a Jev (#8, decision 211) -------
    // Lo que Jev respondio sin seguridad («incierto»), para etiquetarlo a mano.
    // A CIEGAS: la fila no trae lo que dijo Jev; se ensena al guardar, porque
    // verlo antes empuja la etiqueta (decision 179). Con estas etiquetas se
    // calcula el umbral de cada pregunta (`evaluar_decisiones.py etiquetas`).
    async verRevision(pregunta) {
      this._salirDeJob();
      this.view = 'revision';
      if (!this.revision.autor) {
        try { this.revision.autor = localStorage.getItem('seo-crawler-revisor') || ''; } catch (_) { /* sin storage */ }
      }
      this.revision.pregunta = pregunta;
      this.revision.resultado = null;
      this.revision.nota = '';
      await this.cargarResumenRevision();
      if (pregunta) await this.cargarPendientesRevision();
    },

    async cargarResumenRevision() {
      try {
        this.revision.resumen = await api('/decisiones/revision/resumen');
      } catch (e) {
        this.revision.resumen = [];
        this.error = 'No se pudo cargar la revisión: ' + e.message;
      }
    },

    async cargarPendientesRevision() {
      this.revision.cargando = true;
      this.revision.items = [];
      try {
        this.revision.items = await api('/decisiones/revision?limite=20&pregunta=' + encodeURIComponent(this.revision.pregunta));
      } catch (e) {
        this.revision.items = [];
        this.error = 'No se pudieron cargar las respuestas: ' + e.message;
      } finally {
        this.revision.cargando = false;
      }
    },

    get revisionActual() {
      return this.revision.resultado ? this.revision.resultado.item : (this.revision.items[0] || null);
    },

    async etiquetarRevision(valor) {
      const item = this.revision.items[0];
      // Dos pulsaciones seguidas mandaban dos PUT: la guardada era la segunda
      // y la pantalla ensenaba la primera.
      if (!item || this.revision.resultado || this.revision.enviando || this.revision.cargando) return;
      this.revision.enviando = true;
      try {
        try { localStorage.setItem('seo-crawler-revisor', this.revision.autor || ''); } catch (_) { /* sin storage */ }
        const r = await api('/decisiones/' + item.decision_id + '/etiqueta', {
          method: 'PUT',
          body: JSON.stringify({ etiqueta: valor, nota: this.revision.nota || null, autor: this.revision.autor || null }),
        });
        this.revision.resultado = { ...r, item };
      } catch (e) {
        this.error = 'No se pudo guardar la etiqueta: ' + e.message;
      } finally {
        this.revision.enviando = false;
      }
    },

    async siguienteRevision() {
      this.revision.resultado = null;
      this.revision.nota = '';
      this.revision.items = this.revision.items.slice(1);
      if (!this.revision.items.length) {
        await this.cargarPendientesRevision();
        await this.cargarResumenRevision();
      }
    },

    // Saltar no guarda nada: la fila vuelve a salir otro dia.
    saltarRevision() {
      if (this.revision.resultado) return this.siguienteRevision();
      this.revision.items = this.revision.items.slice(1).concat(this.revision.items.slice(0, 1));
      this.revision.nota = '';
    },

    teclaRevision(ev) {
      if (this.view !== 'revision' || !this.revision.pregunta || this.dialogo || this.revision.cargando) return;
      // Cmd/Ctrl+1 es cambiar de pestana, no etiquetar.
      if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
      const t = ev.target && ev.target.tagName;
      if (t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || (ev.target && ev.target.isContentEditable)) return;
      if (this.revision.resultado && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); this.siguienteRevision(); return; }
      const item = this.revision.items[0];
      const n = Number(ev.key);
      if (item && !this.revision.resultado && n >= 1 && n <= item.opciones.length) {
        ev.preventDefault();
        this.etiquetarRevision(item.opciones[n - 1].valor);
      }
    },

    textoOpcionRevision(item, valor) {
      const o = (item && item.opciones || []).find(x => x.valor === valor);
      return o ? o.texto : (valor == null ? '—' : String(valor));
    },

    async verProgramados() {
      this._salirDeJob();
      this.view = 'programados';
      await this.cargarProgramaciones();
    },

    // ------- Produccion (revision de UX del 25-oct, 2.12) -------
    // Para decidir si esperar, lanzar otro o desplegar (que corta lo que esta
    // en marcha) y saber cuando estara el censo. Se refresca sola cada 10 s
    // mientras se mira; el temporizador se para solo al salir de la vista.
    // ------- Ajustes de la agencia (revision de UX del 25-oct, 2.5) -------
    // Lo que vale para todos los clientes: el bot de Slack, las llaves de
    // Search Console, las claves de los modelos, importar un backup y el tema.
    // NUNCA un secreto: de una llave se ve su email; de un token, el bot y el
    // espacio; de las claves del entorno, solo si estan puestas.
    async verAjustes() {
      this._salirDeJob();
      this.view = 'ajustes';
      await this.cargarAjustes();
    },

    async cargarAjustes() {
      const previo = this.ajustes || {};
      this.ajustes = {
        estado: 'cargando', error: '', modelos: null, gemini: null,
        slack: { tokens: null, nombreNuevo: 'SLACK_BOT', tokenTexto: '', ocupado: false, error: '' },
        gsc: { llaves: null, nombreNueva: 'GSC_AGENCIA', ocupado: false, error: '' },
        guiaSlack: previo.guiaSlack || false,
      };
      const a = this.ajustes;
      // Cada bloque por su lado: que falle uno (Slack sin red) no vacia los demas.
      const [modelos, slack, gsc, gemini] = await Promise.allSettled([
        api('/ajustes'), api('/credenciales?tipo=slack'), api('/credenciales?tipo=gsc'), api('/semantic/gemini-accounts')]);
      a.modelos = modelos.status === 'fulfilled' ? modelos.value.modelos : null;
      a.modelosError = modelos.status === 'rejected' ? modelos.reason.message : '';
      a.slack.tokens = slack.status === 'fulfilled' ? slack.value : [];
      if (slack.status === 'rejected') a.slack.error = slack.reason.message;
      a.gsc.llaves = gsc.status === 'fulfilled' ? gsc.value : [];
      if (gsc.status === 'rejected') a.gsc.error = gsc.reason.message;
      a.gemini = gemini.status === 'fulfilled' ? gemini.value : null;
      a.estado = 'ok';
    },

    async subirTokenSlackAgencia() {
      const s = this.ajustes.slack;
      const contenido = (s.tokenTexto || '').trim();
      if (!contenido) return;
      s.error = ''; s.ocupado = true;
      try {
        const r = await api('/credenciales', { method: 'POST',
          body: JSON.stringify({ tipo: 'slack', nombre: s.nombreNuevo, contenido }) });
        s.tokenTexto = '';
        s.tokens = await api('/credenciales?tipo=slack');
        this.showToast('Bot conectado: ' + (r.bot || '') + ' en ' + (r.equipo || 'Slack'));
      } catch (e) { s.error = e.message; }
      s.ocupado = false;
    },

    async subirLlaveGscAgencia(ev) {
      const g = this.ajustes.gsc;
      const fichero = ev.target.files && ev.target.files[0];
      ev.target.value = '';
      if (!fichero) return;
      g.error = ''; g.ocupado = true;
      try {
        const contenido = await fichero.text();
        const r = await api('/credenciales', { method: 'POST',
          body: JSON.stringify({ tipo: 'gsc', nombre: g.nombreNueva, contenido }) });
        g.llaves = await api('/credenciales?tipo=gsc');
        this.showToast('Llave subida: ' + r.client_email);
      } catch (e) { g.error = e.message; }
      g.ocupado = false;
    },

    async quitarCredencial(tipo, c) {
      const bloque = tipo === 'slack' ? this.ajustes.slack : this.ajustes.gsc;
      const uso = (c.en_uso_por || []);
      const ok = await this.preguntar({
        titulo: tipo === 'slack' ? `Quitar el bot ${c.nombre}` : `Quitar la llave ${c.nombre}`,
        mensaje: uso.length
          ? 'La usan ' + uso.join(', ') + '. Quítala antes de sus fichas, en Configuración, o dejarán de recibir datos.'
          : 'Se borra del servidor. No la usa ningún cliente.',
        aceptar: 'Quitar', peligro: true });
      if (!ok) return;
      bloque.error = '';
      try {
        await api(`/credenciales/${encodeURIComponent(c.nombre)}`, { method: 'DELETE' });
        if (tipo === 'slack') bloque.tokens = await api('/credenciales?tipo=slack');
        else bloque.llaves = await api('/credenciales?tipo=gsc');
      } catch (e) { bloque.error = e.message; }
    },

    async verProduccion() {
      this._salirDeJob();
      this.view = 'produccion';
      await this.cargarProduccion();
      if (this.prodTimer) clearInterval(this.prodTimer);
      this.prodTimer = setInterval(() => {
        if (this.view !== 'produccion') { clearInterval(this.prodTimer); this.prodTimer = null; return; }
        if (!document.hidden) this.cargarProduccion(true);
      }, 10000);
    },

    async cargarProduccion(refresco = false) {
      if (!refresco) this.prod.estado = 'cargando';
      try {
        const lista = s => api(`/jobs?status=${s}&page_size=100`).then(d => d.items || []);
        const [corriendo, analizando, esperando] = await Promise.all([
          lista('running'), lista('analyzing'), lista('pending')]);
        if (!refresco || !this.programaciones.length) this.cargarProgramaciones();
        // Sin cliente: solo el total, para el aviso con enlace a la lista.
        api('/jobs?sin_cliente=true&page_size=1').then(d => { this.prod.sinCliente = d.total; }).catch(() => {});

        // El progreso de cada rastreo en marcha, del mismo endpoint que la
        // ficha (crawled_count de la BD y pending_count del planificador).
        const progreso = {};
        await Promise.all(corriendo.map(j => api(`/jobs/${j.id}/progress`)
          .then(p => { progreso[j.id] = p; }).catch(() => {})));
        const ahora = Date.now();
        const muestras = {};
        for (const j of corriendo) {
          const hechas = Math.max((progreso[j.id] || {}).crawled_count || 0, j.total_urls_crawled || 0);
          // Las ultimas 10 min como mucho: el ritmo de ahora, no el de la
          // primera hora.
          muestras[j.id] = [...(this.prod.muestras[j.id] || []), { t: ahora, n: hechas }]
            .filter(m => ahora - m.t <= 600000);
        }

        // La posicion solo con el orden real de la cola (Redis, FIFO). Sin
        // el (API anterior a 2.12, Redis caido) se ordena por cuando se
        // crearon y NO se dice el puesto: una reanudacion vuelve al final de
        // la cola aunque el job sea de hace dias. Solo se pregunta si hay
        // alguien esperando.
        let cola = null;
        if (esperando.length) {
          try {
            const c = await api('/jobs/cola');
            if (c && c.disponible && Array.isArray(c.orden)) cola = c.orden;
          } catch (_) { cola = null; }
        }
        esperando.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
        if (cola) {
          const pos = id => { const i = cola.indexOf(id); return i < 0 ? Infinity : i; };
          esperando.sort((a, b) => pos(a.id) - pos(b.id));
        }
        this.prod = { ...this.prod, estado: 'ok', error: '', enCurso: [...corriendo, ...analizando],
                      enCola: esperando, cola, progreso, muestras };
      } catch (e) {
        // En un refresco fallido se queda lo ultimo bueno: vaciar la vista
        // diria «no hay nada en marcha», que es justo lo que no se sabe.
        if (!refresco || this.prod.estado !== 'ok') { this.prod.estado = 'error'; this.prod.error = e.message; }
      }
    },

    // «1.º en la cola», o null si no se puede afirmar: sin el orden de Redis,
    // o un pendiente que no esta en la lista (arrancando en este momento, o
    // perdido tras un reinicio hasta que el worker lo recupere).
    puestoEnCola(j) {
      if (!this.prod.cola) return null;
      const i = this.prod.cola.indexOf(j.id);
      return i < 0 ? null : i + 1;
    },

    // Lo que se puede decir de un rastreo en marcha: hechas, total estimado,
    // porcentaje y hora de fin. Cada cifra solo si hay base para ella.
    //  - Total: lo rastreado + lo que el planificador tiene en cola (es una
    //    cota baja: la cola crece al descubrir enlaces, de ahi el «~»), sin
    //    pasar del tope max_urls. Sin la cola, solo el tope, como maximo.
    //  - Ritmo: medido en esta pagina entre refrescos (1 min como minimo).
    //    No se usa started_at: al reanudar un job el worker lo pone a la hora
    //    de la reanudacion y la cuenta de paginas no vuelve a cero, asi que
    //    hechas/minutos saldria inflado y la hora de fin demasiado pronto. Lo
    //    que no se puede afirmar no se afirma: hasta tener medida propia,
    //    «calculando…» (hallazgo de la revision de 2.12).
    //  - Hora de fin: solo con ritmo y con un total que no sea solo el tope.
    //  - Terminando: lo hecho ya llega al total (la cola del planificador en 0,
    //    o el tope alcanzado). Ahi no hay hora que calcular.
    //  - Sin avance: 2 min o mas de muestras sin una pagina nueva.
    estimacion(j) {
      const p = this.prod.progreso[j.id] || {};
      const hechas = Math.max(p.crawled_count || 0, j.total_urls_crawled || 0);
      const tope = (j.config && j.config.max_urls) || null;
      let total = null, tipo = null;
      if (p.pending_exacto && p.pending_count != null) {
        total = hechas + p.pending_count; tipo = 'aprox';
        if (tope && total >= tope) { total = tope; tipo = 'tope'; }
      } else if (tope) {
        total = tope; tipo = 'maximo';
      }
      const pct = total ? Math.min(100, (hechas / total) * 100) : null;
      const terminando = total != null && hechas >= total;

      let ritmo = null, sinAvanceMin = null;  // ritmo en paginas por minuto
      const m = this.prod.muestras[j.id] || [];
      if (m.length >= 2) {
        const lapso = m[m.length - 1].t - m[0].t;
        const dn = m[m.length - 1].n - m[0].n;
        if (lapso >= 60000 && dn > 0) ritmo = dn / (lapso / 60000);
        else if (lapso >= 120000 && dn <= 0) sinAvanceMin = Math.floor(lapso / 60000);
      }

      let fin = null;
      if (ritmo && total && tipo !== 'maximo' && !terminando) {
        fin = new Date(Date.now() + ((total - hechas) / ritmo) * 60000);
      }
      return { hechas, total, tipo, pct, ritmo, fin, terminando, sinAvanceMin };
    },

    // «1.374 / ~4.000 · termina hacia las 14:20»
    textoEstimacion(j) {
      const e = this.estimacion(j);
      let t = fmt.num(e.hechas);
      // Las filas pueden pasar del tope (cada salto de una redireccion es una
      // fila): «5.600 / 1.000» no se entiende, se dice el tope aparte.
      if (e.terminando && e.hechas > e.total)
        return t + ' páginas · ' + (e.tipo === 'aprox' ? 'no queda nada en cola' : 'llegó al tope de ' + fmt.num(e.total)) + ', terminando';
      if (e.tipo === 'aprox') t += ' / ~' + fmt.num(e.total);
      else if (e.tipo === 'tope') t += ' / ' + fmt.num(e.total) + ' (el tope)';
      else if (e.tipo === 'maximo') t += ' de ' + fmt.num(e.total) + ' como mucho';
      else t += ' páginas';
      if (e.terminando) t += e.tipo === 'aprox' ? ' · no queda nada en cola, terminando' : ' · llegó al tope, terminando';
      else if (e.sinAvanceMin) t += ' · sin páginas nuevas en los últimos ' + e.sinAvanceMin + ' min';
      else if (e.fin) t += ' · termina ' + fmt.hacia(e.fin);
      else if (e.tipo !== 'maximo' && e.total) t += ' · calculando la hora de fin…';
      return t;
    },

    // La frase de arriba: los que rastrean, los que ya solo se analizan y los
    // que esperan, por separado (un analisis no es un rastreo «en marcha»,
    // aunque desplegar tambien lo corte).
    get resumenProduccion() {
      const n = (x, uno, varios) => x === 1 ? uno : fmt.num(x) + ' ' + varios;
      const rastreando = this.prod.enCurso.filter(j => j.status === 'running').length;
      const analizando = this.prod.enCurso.length - rastreando;
      const partes = [];
      if (rastreando) partes.push(n(rastreando, '1 rastreo en marcha', 'rastreos en marcha'));
      if (analizando) partes.push(n(analizando, '1 analizándose', 'analizándose'));
      if (this.prod.enCola.length) partes.push(n(this.prod.enCola.length, '1 esperando', 'esperando'));
      if (partes.length < 2) return partes.join('');
      return partes.slice(0, -1).join(', ') + ' y ' + partes[partes.length - 1];
    },

    // Los proximos disparos de las programaciones activas, el mas cercano primero.
    get proximosDisparos() {
      return this.programaciones.filter(p => p.activa && p.proxima_ejecucion)
        .sort((a, b) => new Date(a.proxima_ejecucion) - new Date(b.proxima_ejecucion));
    },

    // «Fallidas» solo si alguna fila de la pagina tiene alguna: una columna
    // de ceros no dice nada y ocupa sitio (revision de UX del 25-oct, V38).
    get hayFallidas() {
      return this.jobs.some(j => (j.total_urls_failed || 0) > 0);
    },

    async cargarProgramaciones() {
      try {
        this.programaciones = await api('/programaciones?resumen=true');
      } catch (e) {
        this.programaciones = [];
        this.error = 'No se pudieron cargar las programaciones: ' + e.message;
      }
    },

    async alternarProgramacion(p) {
      try {
        await api('/programaciones/' + p.id, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ activa: !p.activa }),
        });
        if (this.view === 'client') await this.cargarProgramacionesCliente();
        else await this.cargarProgramaciones();
      } catch (e) {
        this.error = 'No se pudo cambiar: ' + e.message;
      }
    },

    // «Lanzar ahora» (decision 209): el mismo rastreo que lanzaria a su hora,
    // sin esperar. Si hay uno vivo, el servidor dice por que no (409).
    async lanzarProgramacionAhora(p) {
      if (!await this.preguntar({ titulo: `Lanzar ahora «${p.nombre}»`,
        mensaje: 'Lanza ya el rastreo que haría a su hora. La próxima ejecución no cambia.', aceptar: 'Lanzar' })) return;
      try {
        const r = await api('/programaciones/' + p.id + '/ejecutar', { method: 'POST' });
        this.showToast('Lanzado: ' + r.nombre);
        if (this.view === 'client') await this.cargarProgramacionesCliente();
        else await this.cargarProgramaciones();
      } catch (e) {
        // El 409 dice por que con el texto de `ultimo_motivo`, que esta en
        // pasado («seguía»): aqui el rastreo sigue vivo AHORA.
        this.error = 'No se pudo lanzar: ' + fmt.motivo(e.message).replace(/^no se lanzó: /, '').replace('seguía sin terminar', 'sigue sin terminar').replace('ya tenía otro', 'ya tiene otro');
      }
    },

    async borrarProgramacion(p) {
      // Se avisa de lo que NO se borra: los rastreos que ya lanzo son
      // censos entregados o comparables, y tirarlos por cambiar de idea
      // sobre la hora seria perder el historico del cliente.
      if (!await this.preguntar({ titulo: `Eliminar la programación «${p.nombre}»`,
        mensaje: 'Deja de lanzarse sola. Los rastreos que ya ha lanzado NO se borran.', aceptar: 'Eliminar', peligro: true })) return;
      try {
        await api('/programaciones/' + p.id, { method: 'DELETE' });
        if (this.view === 'client') await this.cargarProgramacionesCliente();
        else await this.cargarProgramaciones();
      } catch (e) {
        this.error = 'No se pudo borrar: ' + e.message;
      }
    },

    async cargarCandidatosDiff() {
      // Solo rastreos COMPLETADOS del mismo host: comparar con uno truncado
      // se puede, pero el resultado no afirma ausencias, y comparar con otro
      // sitio lo rechaza el servidor (una migracion de dominio va por
      // «Validar migración», 2.13). Del mismo cliente si lo tiene: antes se
      // miraban los 100 ultimos de toda la agencia y uno viejo no salia.
      if (!this.job) return;
      const jobId = this.job.id;
      const miHost = _hostDe(this.job);
      const q = new URLSearchParams({ page: 1, page_size: 100, status: 'completed' });
      if (this.job.cliente_id) q.set('client_id', this.job.cliente_id);
      else if (miHost) q.set('buscar', miHost);
      const d = await api('/jobs?' + q);
      if (!this.job || this.job.id !== jobId) return;
      this.diffCandidatos = (d.items || []).filter(j => j.id !== jobId && j.status === 'completed' && _hostDe(j) === miHost);
    },

    // Los candidatos en grupos por tipo (censo, canario, prueba), no por
    // tamano (V22): la «réplica julio» salia entre los censos por tener su tamano.
    gruposDiff() { return censosPorTipo(this.diffCandidatos); },

    async cargarDiff() {
      const pedido = ++this._diffPedido;
      if (!this.job || !this.diffOtro) { this.diff = null; this.diffCargando = false; return; }
      const otro = this.diffOtro, jobId = this.job.id;
      this.diffCargando = true;
      try {
        const r = await api(`/jobs/${jobId}/diff/${otro}`);
        if (pedido !== this._diffPedido) return;
        this.diff = { ...r, _para: otro, _clave: 'd' + pedido };
      } catch (e) {
        if (pedido !== this._diffPedido) return;
        this.diff = { comparable: false, motivo: 'No se pudo comparar: ' + (e.message || e), _para: otro, _clave: 'd' + pedido };
      } finally {
        if (pedido === this._diffPedido) {
          this.diffCargando = false;
          this.$nextTick(() => lucide.createIcons());
        }
      }
    },

    async switchTab(tab) {
      // Desde URLs (Explorador o ficha de una URL) las demas pestanas vuelven
      // a la ficha del censo: comparten cabecera y fila de pestanas.
      if (this.view === 'explorer') this._unbindExplorerKeyNav();
      if (['explorer', 'url-detail'].includes(this.view)) {
        this.view = 'detail';
        window.scrollTo({ top: 0 });
      }
      this.detailTab = tab;
      if (tab === 'urls' && this.urls.length === 0) this.loadUrls();
      if (tab === 'issues') {
        if (!this.issuesResumen) this.loadIssuesResumen();
        if ((this.issueFilters.issue_type || this.issuesVista === 'lista') && this.issues.length === 0) this.loadIssues();
      }
      if (tab === 'links' && this.links.length === 0 && !this.linksCargando) this.loadLinks();
      if (tab === 'insights' && !this.insights) this.loadInsights();
      if (tab === 'semantic') this.loadSemantic();
      if (tab === 'cleaning') this.loadCleaning();
      if (tab === 'diff') {
        if (!this.diffCandidatos.length) this.cargarCandidatosDiff();
        // Se abre con la comparacion que el worker hizo al cerrar el rastreo
        // (UX-12): un desplegable vacio obligaba a saber con cual comparar.
        // Lo guardado se pinta ya (`diffVista`) y el detalle llega despues (V21).
        const auto = this.job && this.job.comparacion && this.job.comparacion.comparado_con;
        if (auto) this.cargarVersionAnterior();
        if (auto && !this.diffOtro) { this.diffOtro = auto; this.cargarDiff(); }
      }
      if (tab === 'migracion') this.prepararMigracion();
      if (tab === 'enriquecido') this.cargarEjecuciones();
      this.$nextTick(() => lucide.createIcons());
    },

    // ------- Informe SEO -------
    async loadInsights() {
      if (!this.job) return;
      this.insightsLoading = true;
      try {
        this.insights = await api(`/jobs/${this.job.id}/insights`);
      } catch (e) { this.error = e.message; }
      this.insightsLoading = false;
    },

    toggleCategory(key) {
      this.expandedCategories[key] = !this.expandedCategories[key];
    },

    isCategoryExpanded(key) {
      return !!this.expandedCategories[key];
    },

    scoreColor(score) {
      if (score >= 80) return 'var(--green)';
      if (score >= 50) return 'var(--orange)';
      return 'var(--red)';
    },

    scoreClass(score) {
      if (score >= 80) return 'score-good';
      if (score >= 50) return 'score-ok';
      return 'score-bad';
    },

    scoreLabel(score) {
      if (score >= 80) return 'Bueno';
      if (score >= 50) return 'Mejorable';
      return 'Crítico';
    },

    priorityClass(p) {
      return 'priority-' + p;
    },

    priorityLabel(p) {
      return { alta: 'Alta', media: 'Media', baja: 'Baja' }[p] || p;
    },

    // ------- Recommendation URL drill-down -------
    async toggleRecUrls(rec) {
      const key = rec.title;
      this.recUrlsOpen[key] = !this.recUrlsOpen[key];
      // Already loaded? Just toggle visibility
      if (this.recUrls[key]?.loaded) return;
      // Load URLs
      this.recUrls[key] = { loading: true, urls: [], loaded: false };
      try {
        if (rec.issue_types && rec.issue_types.length > 0) {
          // Fetch from issue_types (merge results from each type)
          let all = [];
          for (const it of rec.issue_types) {
            const data = await api(`/jobs/${this.job.id}/issues/urls?issue_type=${encodeURIComponent(it)}&limit=50`);
            all = all.concat(data);
          }
          // Dedup by url id
          const seen = new Set();
          this.recUrls[key].urls = all.filter(u => { if (seen.has(u.id)) return false; seen.add(u.id); return true; });
        } else if (rec.url_filter && Object.keys(rec.url_filter).length > 0) {
          // Fetch from urls endpoint with filters
          let params = 'page=1&page_size=50';
          for (const [k, v] of Object.entries(rec.url_filter)) params += `&${k}=${v}`;
          const data = await api(`/jobs/${this.job.id}/urls?${params}`);
          this.recUrls[key].urls = data.items.map(u => ({ id: u.id, url: u.url, status_code: u.status_code }));
        }
        this.recUrls[key].loaded = true;
      } catch (e) { this.error = e.message; }
      this.recUrls[key].loading = false;
      this.$nextTick(() => lucide.createIcons());
    },

    recHasUrls(rec) {
      return (rec.issue_types && rec.issue_types.length > 0) || (rec.url_filter && Object.keys(rec.url_filter).length > 0);
    },

    openRecInExplorer(rec) {
      if (rec.url_filter && Object.keys(rec.url_filter).length > 0) {
        // Find matching explorer tab or use 'all' with manual filter
        this.openExplorer();
        // Apply the filter by finding the right tab
        const f = rec.url_filter;
        let matched = EXP_TABS.find(t => t.filter && JSON.stringify(t.filter) === JSON.stringify(f));
        if (matched) {
          this.setExplorerTab(matched.key);
        }
      } else if (rec.issue_types && rec.issue_types.length > 0) {
        // Navigate to issues tab filtered by issue type
        this.detailTab = 'issues';
        this.issueFilters.issue_type = rec.issue_types[0];
        this.issuesPage = 1;
        this.loadIssues();
      }
    },

    // SVG ring dasharray for score circle
    ringDash(score, radius) {
      const circ = 2 * Math.PI * radius;
      return `${(score / 100) * circ} ${circ}`;
    },

    // ------- Semantico -------
    async loadSemantic() {
      if (!this.job) return;
      // Load GSC + Gemini accounts in parallel
      try {
        const [gsc, gemini] = await Promise.all([
          api('/semantic/gsc-accounts'),
          api('/semantic/gemini-accounts'),
        ]);
        this.gscAccounts = gsc;
        this.geminiAccounts = gemini;
        if (gemini.length === 1 && !this.semanticGeminiAccountId) {
          this.semanticGeminiAccountId = gemini[0].id;
        }
      } catch (_) {}
      // Check if analysis exists
      try {
        const status = await api(`/jobs/${this.job.id}/semantic/status`);
        if (status.status === 'completed') {
          const results = await api(`/jobs/${this.job.id}/semantic/results`);
          this.semanticResults = results;
          this.semanticError = null;
          this.$nextTick(() => this.renderSemanticChart('rings'));
        } else if (status.status === 'running') {
          this.semanticLoading = true;
          this.semanticProgress = { stage: status.stage, progress: status.progress };
          this._pollSemanticStatus();
        } else if (status.status === 'failed') {
          this.semanticError = status.error_message || 'El análisis falló.';
        }
      } catch (_) {}
    },

    _pollSemanticStatus() {
      if (this.semanticPollTimer) clearInterval(this.semanticPollTimer);
      this.semanticPollTimer = setInterval(async () => {
        try {
          const status = await api(`/jobs/${this.job.id}/semantic/status`);
          this.semanticProgress = { stage: status.stage, progress: status.progress };
          if (status.status === 'completed') {
            clearInterval(this.semanticPollTimer);
            this.semanticPollTimer = null;
            this.semanticLoading = false;
            const results = await api(`/jobs/${this.job.id}/semantic/results`);
            this.semanticResults = results;
            this.semanticError = null;
            this.$nextTick(() => this.renderSemanticChart('rings'));
          } else if (status.status === 'failed') {
            clearInterval(this.semanticPollTimer);
            this.semanticPollTimer = null;
            this.semanticLoading = false;
            this.semanticError = status.error_message || 'El análisis falló.';
          }
        } catch (_) {}
      }, 2000);
    },

    async runSemanticAnalysis() {
      if (!this.job) return;
      if (!this.semanticGeminiAccountId) {
        this.semanticError = 'Elige una clave de Gemini antes de lanzar el análisis.';
        return;
      }
      this.semanticLoading = true;
      this.semanticError = null;
      this.semanticResults = null;
      this.semanticProgress = { stage: 'starting', progress: 0 };
      try {
        await api(`/jobs/${this.job.id}/semantic/analyze`, {
          method: 'POST',
          body: JSON.stringify({
            gemini_account_id: this.semanticGeminiAccountId,
            alpha: this.semanticAlpha,
            beta: this.semanticBeta,
            cannibal_threshold: this.semanticThreshold,
          }),
        });
        this._pollSemanticStatus();
      } catch (e) {
        this.semanticLoading = false;
        this.semanticError = e.message;
      }
    },

    async saveGeminiAccount() {
      this.geminiFormError = null;
      const name = (this.geminiFormName || '').trim();
      const key = (this.geminiFormKey || '').trim();
      if (!key) {
        this.geminiFormError = 'La clave no puede estar vacía.';
        return;
      }
      try {
        const created = await api('/semantic/gemini-accounts', {
          method: 'POST',
          body: JSON.stringify({ name: name || 'Gemini account', api_key: key }),
        });
        this.geminiAccounts = await api('/semantic/gemini-accounts');
        this.semanticGeminiAccountId = created.id;
        this.geminiFormName = '';
        this.geminiFormKey = '';
        this.showGeminiModal = false;
      } catch (e) {
        this.geminiFormError = e.message;
      }
    },

    async deleteGeminiAccount(id) {
      if (!await this.preguntar({ titulo: 'Eliminar esta API key',
        mensaje: 'Los análisis pasados conservan su resultado, pero no podrán volver a calcular embeddings de consultas.', aceptar: 'Eliminar', peligro: true })) return;
      try {
        await api(`/semantic/gemini-accounts/${id}`, { method: 'DELETE' });
        this.geminiAccounts = await api('/semantic/gemini-accounts');
        if (this.semanticGeminiAccountId === id) this.semanticGeminiAccountId = '';
      } catch (e) {
        this.semanticError = e.message;
      }
    },

    semanticStageLabel(stage) {
      const labels = {
        starting: 'Iniciando...',
        loading_data: 'Cargando datos de la BD...',
        filtering: 'Filtrando páginas...',
        embedding: 'Generando embeddings (esto puede tardar)...',
        weighting: 'Calculando pesos...',
        centroid: 'Calculando centroide...',
        dimensionality_reduction: 'Reduccion dimensional (PCA + UMAP)...',
        clustering: 'Clustering HDBSCAN...',
        classification: 'Clasificando anillos...',
        cannibalization: 'Detectando canibalización...',
        done: 'Completado',
      };
      return labels[stage] || stage || 'Procesando...';
    },

    async renderSemanticChart(type) {
      if (!this.job) return;
      await this.$nextTick();
      try {
        if (type === 'rings') {
          const data = await api(`/jobs/${this.job.id}/semantic/ring-data`);
          await this.$nextTick();
          const el = document.getElementById('semantic-ring-chart');
          if (el && window.Plotly) Plotly.newPlot(el, data.data, this.plotLayout(data.layout), { responsive: true });
        } else if (type === 'scatter') {
          const data = await api(`/jobs/${this.job.id}/semantic/scatter-data`);
          await this.$nextTick();
          const el = document.getElementById('semantic-scatter-chart');
          if (el && window.Plotly) Plotly.newPlot(el, data.data, this.plotLayout(data.layout), { responsive: true });
        }
      } catch (e) { this.error = e.message; }
    },

    async loadCannibalization() {
      if (!this.job) return;
      this.cannibalLoading = true;
      try {
        const brand = encodeURIComponent(this.cannibalBrand.trim());
        const data = await api(`/jobs/${this.job.id}/semantic/cannibalization?brand=${brand}`);
        this.cannibalPairs = data.pairs || [];
        this.cannibalHasQueryData = data.has_query_data || false;
      } catch (e) { this.error = e.message; }
      this.cannibalLoading = false;
    },

    async loadDrift() {
      if (!this.job || this.driftData.length > 0) return;
      this.driftLoading = true;
      try {
        const data = await api(`/jobs/${this.job.id}/semantic/drift`);
        this.driftData = data.drift || [];
      } catch (e) { this.error = e.message; }
      this.driftLoading = false;
    },

    async runGapAnalysis() {
      if (!this.job || !this.gapTopic.trim()) return;
      this.gapLoading = true;
      this.gapResults = null;
      try {
        this.gapResults = await api(`/jobs/${this.job.id}/semantic/gap-analysis`, {
          method: 'POST',
          body: JSON.stringify({ topic: this.gapTopic.trim() }),
        });
      } catch (e) { this.error = e.message; }
      this.gapLoading = false;
    },

    async analyzeTarget() {
      if (!this.job || !this.targetTheme.trim()) return;
      this.targetLoading = true;
      this.targetResults = null;
      try {
        this.targetResults = await api(`/jobs/${this.job.id}/semantic/target-rings`, {
          method: 'POST',
          body: JSON.stringify({ target_theme: this.targetTheme.trim() }),
        });
        this.$nextTick(() => {
          const el = document.getElementById('semantic-target-ring-chart');
          if (el && window.Plotly && this.targetResults.ring_map) {
            Plotly.newPlot(el, this.targetResults.ring_map.data, this.plotLayout(this.targetResults.ring_map.layout), { responsive: true });
          }
        });
      } catch (e) { this.error = e.message; }
      this.targetLoading = false;
    },

    async loadGscProperties() {
      if (!this.semanticGscAccountId) return;
      this.gscPropsLoading = true;
      try {
        const data = await api(`/semantic/gsc-accounts/${this.semanticGscAccountId}/properties`);
        this.semanticGscProps = data.properties || [];
      } catch (e) { this.error = e.message; }
      this.gscPropsLoading = false;
    },

    async fetchGscData() {
      if (!this.job || !this.semanticGscAccountId || !this.semanticGscProp) return;
      this.gscFetchLoading = true;
      this.gscFetchResult = null;
      try {
        this.gscFetchResult = await api(`/jobs/${this.job.id}/semantic/fetch-gsc`, {
          method: 'POST',
          body: JSON.stringify({
            gsc_account_id: this.semanticGscAccountId,
            property_url: this.semanticGscProp,
            days: parseInt(this.semanticGscDays) || 90,
          }),
        });
      } catch (e) { this.error = e.message; }
      this.gscFetchLoading = false;
    },

    async uploadGscAccount() {
      if (!this.gscUploadFile || !this.gscUploadName.trim()) return;
      try {
        const text = await this.gscUploadFile.text();
        const json = JSON.parse(text);
        await api('/semantic/gsc-accounts', {
          method: 'POST',
          body: JSON.stringify({ name: this.gscUploadName.trim(), credentials_json: json }),
        });
        this.gscAccounts = await api('/semantic/gsc-accounts');
        this.showGscUploadModal = false;
        this.gscUploadName = '';
        this.gscUploadFile = null;
        this.showToast('Cuenta GSC guardada');
      } catch (e) { this.error = e.message; }
    },

    exportSemanticCsv() {
      if (!this.job) return;
      window.open(`${API}/jobs/${this.job.id}/semantic/export`, '_blank');
    },

    // ------- URLs -------
    async loadUrls() {
      this.loading = true;
      try {
        let f = '';
        if (this.urlFilters.status_group) f += `&status_group=${this.urlFilters.status_group}`;
        if (this.urlFilters.is_internal)  f += `&is_internal=${this.urlFilters.is_internal}`;
        if (this.urlFilters.resource_type) f += `&resource_type=${this.urlFilters.resource_type}`;
        const data = await api(`/jobs/${this.job.id}/urls?page=${this.urlsPage}&page_size=50${f}`);
        this.urls = data.items;
        this.urlsPages = data.pages;
        this.urlsTotal = data.total;
      } catch (e) { this.error = e.message; }
      this.loading = false;
    },

    applyUrlFilters() { this.urlsPage = 1; this.loadUrls(); },
    setUrlsPage(p) { if (p >= 1 && p <= this.urlsPages) { this.urlsPage = p; this.loadUrls(); } },

    // ------- Detalle de URL individual -------
    // Cuantas paginas, y si son hallazgos de plantilla (una fila por hallazgo
    // con `paginas_afectadas`, decisiones 53, 64 y 73): esos cuelgan de una
    // pagina de ejemplo, asi que «1 pagina» seria falso.
    textoAlcanceInforme(r) {
      const hallazgos = n => fmt.num(n) + (n === 1 ? ' hallazgo de plantilla' : ' hallazgos de plantilla')
        + ' (cada uno se repite en muchas páginas y se arregla una vez)';
      if (r.agregadas && r.agregadas >= r.incidencias) return hallazgos(r.agregadas);
      const pags = fmt.num(r.paginas) + (r.paginas === 1 ? ' página' : ' páginas');
      return r.agregadas ? pags + ' · ' + hallazgos(r.agregadas) : pags;
    },

    // --- Enlace de solo lectura (decision 143) ---------------------------
    async iniciarCompartido(token) {
      document.body.classList.add('modo-compartido');
      this.compartido = { token, cliente: null, censos: [], elegido: '', error: '' };
      this.view = 'informe';
      this.informeCargando = true;
      try {
        const r = await api(`/publico/${token}`);
        this.compartido.cliente = r.cliente;
        this.compartido.censos = r.censos;
        if (!r.censos.length) { this.compartido.error = 'Todavía no hay ningún informe.'; this.informeCargando = false; return; }
        await this.verInformeCompartido(r.censos[0].id);
      } catch (e) {
        this.compartido.error = e.message;
        this.informeCargando = false;
      }
    },

    async verInformeCompartido(jobId) {
      this.compartido.elegido = jobId;
      this.informe = null;
      this.informeCargando = true;
      try {
        this.informe = await api(`/publico/${this.compartido.token}/informe/${jobId}`);
        document.title = `Informe SEO · ${this.informe.job.sitio}`;
      } catch (e) { this.compartido.error = e.message; }
      this.informeCargando = false;
    },

    async cargarEnlaces() {
      if (!this.cliente) return;
      const id = this.cliente.id;
      this.enlaceNuevo = null;
      try {
        const r = await api(`/clients/${id}/enlaces`);
        if (this.cliente && this.cliente.id === id) this.enlaces = r;
      } catch (e) { this.enlaces = []; this.clienteError = e.message; }
    },

    async crearEnlace(nombre, dias) {
      try {
        this.enlaceNuevo = await api(`/clients/${this.cliente.id}/enlaces`, {
          method: 'POST', body: JSON.stringify({ nombre: nombre || null, dias: dias ? Number(dias) : null }) });
        this.enlaceNuevo.url = location.origin + this.enlaceNuevo.ruta;
        const r = await api(`/clients/${this.cliente.id}/enlaces`);
        this.enlaces = r;
      } catch (e) { this.clienteError = e.message; }
    },

    async revocarEnlace(e) {
      const ok = await this.preguntar({ titulo: 'Revocar el enlace', mensaje: `Quien tenga el enlace «${e.nombre || e.prefijo + '…'}» dejará de ver los informes. No se puede deshacer.`, aceptar: 'Revocar', peligro: true });
      if (!ok) return;
      try {
        await api(`/clients/${this.cliente.id}/enlaces/${e.id}`, { method: 'DELETE' });
        await this.cargarEnlaces();
      } catch (err) { this.clienteError = err.message; }
    },

    // Decision 138: el informe para el cliente, en una pagina imprimible.
    async abrirInforme() {
      if (this.view === 'explorer') this._unbindExplorerKeyNav();
      this.view = 'informe';
      this.informe = null;
      this.informeCargando = true;
      try {
        this.informe = await api(`/jobs/${this.job.id}/informe`);
        this.cargarVersionAnterior();
        document.title = `Informe SEO · ${this.informe.job.sitio}`;
      } catch (e) { this.error = e.message; }
      this.informeCargando = false;
      window.scrollTo({ top: 0 });
      this.$nextTick(() => window.lucide && lucide.createIcons());
    },

    // La ficha de una URL de la que solo se sabe la direccion (las paginas del
    // trafico entre censos; revision de UX del 25-oct, 3.3). Se pide la URL
    // exacta (`url_exacta`); una API que aun no lo entiende lo ignora y
    // devuelve las que la contienen: entonces se recorren ordenadas hasta
    // encontrarla. Con /es casaban 1.272 y la exacta no salia entre las 20
    // primeras. Solo se dice que no esta si se ha mirado entera.
    async abrirFichaPorUrl(url) {
      if (!this.job || !url) return;
      const base = `/jobs/${this.job.id}/urls?url_exacta=${encodeURIComponent(url)}&url_contains=${encodeURIComponent(url)}&sort_by=url&sort_dir=asc&page_size=200&ligero=true`;
      try {
        for (let pagina = 1; pagina <= 30; pagina++) {
          const r = await api(`${base}&page=${pagina}`);
          const items = r.items || [];
          const fila = items.find(u => u.url === url);
          if (fila) { this.openUrlDetail(fila.id); return; }
          if (!items.length || pagina * 200 >= (r.total || 0)) {
            this.showToast('Esa URL no está en este censo', 'info');
            return;
          }
        }
        this.showToast('No se encontró la URL entre las primeras 6.000 parecidas; búscala en la pestaña URLs', 'info');
      } catch (e) { this.showToast('No se pudo buscar la URL: ' + e.message, 'error'); }
    },

    async openUrlDetail(urlId) {
      this.urlDetailLoading = true;
      this.urlDetailTab = 'seo';
      this.urlDetail = null;
      if (this.view === 'explorer') this._unbindExplorerKeyNav();
      this.urlDetailId = urlId;
      this.view = 'url-detail';
      this.urlProblemas = [];
      try {
        const d = await api(`/jobs/${this.job.id}/urls/${urlId}`);
        this.urlProblemas = this._agruparProblemasUrl(d.issues, d.url);
        this.cargarPaginasPorTipo(this.urlProblemas.map(g => g.tipo));
        this.urlDetail = d;
        this.cargarIAUrl();
      } catch (e) { this.error = e.message; }
      this.urlDetailLoading = false;
      window.scrollTo({ top: 0, behavior: 'smooth' });
      this.$nextTick(() => lucide.createIcons());
    },

    // El panel lateral de URLs con los problemas agrupados como la ficha
    // (revision de UX del 25-oct, 2.7). Se guarda por respuesta: el x-for y
    // el contador de la pestaña lo piden varias veces.
    expProblemasAgrupados() {
      const d = this.expUrlDetail;
      if (!d) return [];
      const crudo = _crudo(d);
      if (crudo._problemasAgrupados) return crudo._problemasAgrupados;
      const g = this._agruparProblemasUrl(d.issues, d.url);
      Object.defineProperty(crudo, '_problemasAgrupados', { value: g, enumerable: false });
      return g;
    },
    // «200 de 4.720» o «200+»: la API manda como mucho 200 enlaces de cada
    // lado (V26). Con menos, la cifra de la lista es la de verdad.
    cuentaEnlacesPanel(d, lado) {
      const lista = (d && d[lado]) || [];
      if (lista.length < 200) return fmt.num(lista.length);
      const total = lado === 'inlinks' ? d.inlinks_count : d.outlinks_count;
      if (total == null) return fmt.num(lista.length) + '+';
      return total > lista.length ? fmt.num(lista.length) + ' de ' + fmt.num(total) : fmt.num(lista.length);
    },

    // Los problemas de la URL agrupados por tipo (revision de UX del 25-oct,
    // 2.7; V27): antes salia el mismo tipo cuatro veces, con el JSON en crudo
    // y sin enlace a su tipo. Un grupo por tipo con su gravedad mas alta, los
    // detalles legibles y sin repetir, y si es de plantilla o de servidor: un
    // hallazgo con `paginas_afectadas` (decisiones 53, 64 y 73) o con
    // `alcance` cuelga de una pagina de anclaje y se arregla una vez.
    _agruparProblemasUrl(issues, propia) {
      const ORDEN = { error: 0, warning: 1, info: 2 };
      const por = new Map();
      for (const i of issues || []) {
        let g = por.get(i.issue_type);
        if (!g) {
          g = { tipo: i.issue_type, severity: i.severity, n: 0, dePlantilla: 0, deServidor: 0,
                paginasAfectadas: 0, detalles: new Map() };
          por.set(i.issue_type, g);
        }
        g.n++;
        if ((ORDEN[i.severity] ?? 3) < (ORDEN[g.severity] ?? 3)) g.severity = i.severity;
        const d = i.details || {};
        const pa = +d.paginas_afectadas || 0;
        if (d.alcance === 'host' || (d.host && d.paginas_del_host != null)) g.deServidor++;
        else if (d.alcance === 'plantilla' || pa > 1) g.dePlantilla++;
        g.paginasAfectadas = Math.max(g.paginasAfectadas, pa);
        const txt = this.detalleEnFicha(d, propia);
        if (txt) g.detalles.set(txt, (g.detalles.get(txt) || 0) + 1);
      }
      return [...por.values()].map(g => ({
        ...g,
        // «servidor» o «plantilla» solo si lo son TODAS las del tipo en esta
        // pagina; si solo algunas, «en parte» (no se afirma de las demas).
        alcance: g.deServidor === g.n ? 'servidor'
          : g.dePlantilla + g.deServidor === g.n ? 'plantilla'
          : g.dePlantilla + g.deServidor ? 'parte' : null,
        detalles: [...g.detalles].map(([texto, n]) => ({ texto, n })),
      })).sort((a, b) => (ORDEN[a.severity] ?? 3) - (ORDEN[b.severity] ?? 3) || b.n - a.n);
    },

    // El detalle de una incidencia en la ficha de SU url: sin lo que ya dice
    // la cabecera del grupo (plantilla, paginas afectadas, ejemplos, que aqui
    // empezaban por la propia pagina).
    detalleEnFicha(d, propia) {
      if (!d || typeof d !== 'object') return '';
      const c = { ...d };
      // Canibalizacion: con quien compite esta pagina, que es lo que hay que
      // arreglar; ella misma, solo con su parte.
      if (Array.isArray(c.urls) && propia && c.urls.some(x => x && x.url === propia)) {
        const yo = c.urls.find(x => x.url === propia);
        c.compite_con = c.urls.filter(x => x && x.url !== propia);
        if (yo.parte != null) c.parte_propia = yo.parte;
        delete c.urls;
        // primero la busqueda y con quien compite; las cifras, despues
        const { consulta, compite_con, parte_propia, ...resto } = c;
        return this.detalleEnFicha({ consulta, compite_con, parte_propia, ...resto }, null);
      }
      for (const k of ['alcance', 'paginas_afectadas', 'apariciones', 'paginas_ejemplo', 'paginas_del_host',
                       'verdict', 'ventana_dias']) delete c[k];
      for (const k of ['destinos_internos_distintos', 'destinos_fuera_del_censo']) if (!c[k]) delete c[k];
      // «posición nav» → «en Navegación»: el nombre que usa la pestana Enlaces.
      if (typeof c.posicion === 'string' && POSITION_LABEL[c.posicion]) {
        c.en = POSITION_LABEL[c.posicion].toLowerCase(); delete c.posicion;
      }
      const pa = +d.paginas_afectadas || 0;
      return [fmt.detalles(c), pa > 1 ? 'en ' + fmt.num(pa) + ' páginas' : ''].filter(Boolean).join(' · ');
    },

    // Paginas con cada tipo en el censo, para «Ver las N paginas con este
    // problema»: el `total` de la misma consulta que lista la pestana URLs
    // (`/urls?issue_type=`), una por tipo de la ficha y guardada por censo.
    // Antes se sumaban las filas de /issues/resumen por gravedad y una
    // pagina con el tipo en aviso y en info contaba dos veces: «196 paginas»
    // y URLs listaba 167. Si falla, el enlace sale sin cifra.
    async cargarPaginasPorTipo(tipos) {
      const job = this.job && this.job.id;
      if (!job) return;
      if (!this.urlTiposJob || this.urlTiposJob.job !== job) this.urlTiposJob = { job, por: {} };
      const faltan = (tipos || []).filter(t => !(t in this.urlTiposJob.por));
      await Promise.all(faltan.map(async t => {
        try {
          const r = await api(`/jobs/${job}/urls?issue_type=${encodeURIComponent(t)}&page_size=1`);
          if (this.urlTiposJob && this.urlTiposJob.job === job)
            this.urlTiposJob = { job, por: { ...this.urlTiposJob.por, [t]: r.total } };
        } catch (_) { /* sin cifra */ }
      }));
    },

    // Texto del enlace a URLs filtrada por el tipo; si empieza por «Solo» no
    // hay a donde ir y se pinta sin enlace.
    textoVerPaginasTipo(g) {
      const n = this.urlTiposJob && this.job && this.urlTiposJob.job === this.job.id
        ? this.urlTiposJob.por[g.tipo] : null;
      // Un hallazgo de plantilla se anota en una pagina de ejemplo: URLs
      // lista esas, no las miles a las que afecta.
      if (g.alcance === 'plantilla' || g.alcance === 'servidor') {
        if (n === 1) return 'Solo se anota en esta página';
        return n ? 'Ver en URLs las ' + fmt.num(n) + (n === 1 ? ' página donde se anota' : ' páginas donde se anota')
          : 'Ver en URLs las páginas donde se anota';
      }
      if (!n) return 'Ver las páginas con este problema';
      return n === 1 ? 'Solo esta página tiene este problema' : 'Ver las ' + fmt.num(n) + ' páginas con este problema';
    },

    // Tarjeta «Google (90 dias)» (revision de UX del 25-oct, 2.7; V28): lo
    // que ya guarda la URL de Search Console (`gsc_*`, decision 142) y la
    // canonical que elige Google segun su inspeccion (decision 189). NULL no
    // es 0: sin datos se dice por que, sin ceros que parezcan datos.
    googleDeUrl() {
      const u = this.urlDetail;
      if (!u) return null;
      const r = this.job && this.job.gsc_resumen;
      const g = { ventana: r && r.desde && r.hasta ? 'del ' + fmt.diaCorto(r.desde) + ' al ' + fmt.diaCorto(r.hasta) : '',
                  cifras: null, frase: '', canonical: null, inspeccion: null, canonicalFrase: '', parcial: '' };
      if (u.gsc_clics != null || u.gsc_impresiones != null) {
        // El analisis solo escribe 0 si Search Console cubre la ventana entera.
        if (!u.gsc_impresiones) g.frase = 'No ha salido en ninguna búsqueda de Google en estos 90 días.';
        else g.cifras = { clics: u.gsc_clics || 0, impresiones: u.gsc_impresiones, posicion: u.gsc_posicion };
        // Con Search Console conectado hace menos de 90 dias, las cifras son
        // de los dias que hay, no de 90 (revision de la 2.7): se dice.
        if (g.cifras && r && r.cubre_la_ventana === false) {
          if (r.datos_desde) g.ventana = 'del ' + fmt.diaCorto(r.datos_desde) + ' al ' + fmt.diaCorto(r.hasta);
          g.parcial = 'Search Console no cubre los 90 días enteros' + (r.datos_desde ? ': solo hay datos desde el ' + fmt.diaCorto(r.datos_desde) : '')
            + '. Las cifras son de esos días.';
        }
      } else if (!r) {
        g.frase = 'Este censo no tiene datos de Search Console: el cliente no lo tiene conectado o el censo se analizó antes de conectarlo.';
      } else if (u.is_internal === false) {
        g.frase = 'Es una URL de fuera del sitio: Search Console solo da datos de las del sitio.';
      } else if (!r.cubre_la_ventana) {
        g.frase = 'Search Console no cubre los 90 días enteros' + (r.datos_desde ? ' (hay datos desde el ' + fmt.diaCorto(r.datos_desde) + ')' : '')
          + ': no se puede decir cuánto tráfico trae esta URL.';
      } else {
        g.frase = 'Search Console no tiene datos de esta URL.';
      }
      if (!r || !r.inspeccion) return g;  // el cliente no tiene inspecciones
      const insp = u.google_inspeccion;
      const TIPOS = ['google_elige_otro_canonical', 'google_tiene_canonical_antiguo', 'indexable_no_indexada_por_google'];
      const aviso = (u.issues || []).find(i => TIPOS.includes(i.issue_type));
      const corta = x => String(x).replace(/^https?:\/\/(www\.)?/, '');
      // Google vio declarada otra canonical que la de este censo. Si la que
      // elige ya es la del censo, Google ya la sigue y no hay nada que
      // esperar; si no, PUEDE cambiar en su proxima visita (no se afirma que
      // vaya a cambiar). La del censo, no «la de hoy»: el censo puede ser viejo.
      const vistoOtra = (visto, yaSigue) => yaSigue
        ? 'Ya es la que declara la página en este censo, aunque en su última visita Google la vio declarar otra'
          + (visto ? ' (' + corta(visto) + ')' : '') + '.'
        : 'Google la eligió cuando la página declaraba otra canonical' + (visto ? ' (' + corta(visto) + ')' : '')
          + '; en este censo declara otra distinta: puede cambiar en la próxima visita de Google.';
      if (insp) {
        g.inspeccion = { fecha: insp.fecha, visita: insp.ultimo_rastreo, cobertura: insp.cobertura };
        if (insp.canonical_google) {
          g.canonical = insp.canonical_google;
          if (insp.en_ventana_del_censo === false) {
            // Inspeccion lejos de la fecha del censo (fuera de la ventana de
            // la decision 144): no se compara con lo que declaraba entonces.
            g.canonicalFrase = 'La inspección es de otra fecha que este censo, así que no se compara con la canonical que declaraba la página en él'
              + (insp.google_acepta === true ? '; Google eligió la misma que vio declarada.'
                : insp.google_acepta === false ? '; Google eligió otra distinta de la que vio declarada.' : '.');
          } else if (insp.visto_igual_que_censo === false) {
            g.canonicalFrase = insp.google_igual_que_censo == null
              ? 'Google la eligió cuando la página declaraba otra canonical que la de este censo.'
              : vistoOtra(insp.canonical_visto, insp.google_igual_que_censo);
          } else {
            g.canonicalFrase = insp.google_acepta ? 'La misma que declara la página.'
              : insp.google_acepta === false ? 'No es la que declara la página: Google no le hace caso a su canonical.' : '';
          }
        }
      } else if (insp === undefined && aviso) {
        // Una API sin `google_inspeccion` (anterior a la decision 189): lo que
        // dicen los avisos de la inspeccion, que solo salen si algo no cuadra
        // y ya van con la ventana del censo. «Ya la sigue» solo si las dos URL
        // son identicas: con una copia de `misma_url` en JS acabarian
        // discrepando, y en la duda se dice «puede cambiar».
        const d = aviso.details || {};
        g.inspeccion = { fecha: d.inspeccionada, visita: d.ultimo_rastreo_google, cobertura: d.cobertura };
        if (d.canonical_de_google) {
          g.canonical = d.canonical_de_google;
          g.canonicalFrase = aviso.issue_type === 'google_elige_otro_canonical'
            ? 'No es la que declara la página: Google no le hace caso a su canonical.'
            : vistoOtra(d.canonical_visto_por_google, !!d.canonical_hoy && d.canonical_hoy === d.canonical_de_google);
        }
      } else if (insp === null) {
        g.canonicalFrase = 'Search Console aún no ha inspeccionado esta URL (inspecciona unas cuantas cada día): no se sabe qué canonical elige Google.';
      } else {
        g.canonicalFrase = 'Qué canonical elige Google: no consta para esta URL.';
      }
      return g;
    },

    // ------- Problemas -------
    async loadIssues() {
      this.loading = true;
      try {
        let f = '';
        if (this.issueFilters.severity)   f += `&severity=${this.issueFilters.severity}`;
        if (this.issueFilters.issue_type) f += `&issue_type=${this.issueFilters.issue_type}`;
        // El segmento elegido en la vista por tipos sigue mandando en la lista:
        // si no, el recuento de la tarjeta y la lista hablarian de cosas distintas.
        if (this.issuesSegmento) f += `&segmento=${encodeURIComponent(this.issuesSegmento)}`;
        const data = await api(`/jobs/${this.job.id}/issues?page=${this.issuesPage}&page_size=50${f}`);
        this.issues = data.items;
        this.issuesPages = data.pages;
        this.issuesTotal = data.total;
      } catch (e) { this.error = e.message; }
      this.loading = false;
    },

    async loadIssuesResumen() {
      if (!this.job) return;
      const jobId = this.job.id;
      this.cargarVersionAnterior();
      try {
        // Los segmentos antes que el resumen: con segmentos de negocio
        // (decision 125) el reparto de cada tipo se pide entero, para poder
        // decir cuantas paginas caen fuera de toda seccion (revision de UX
        // del 25-oct, 2.10). Sin ellos, los 8 con mas paginas, como antes.
        if (!this.segmentosJob) await this.cargarSegmentos();
        if (!this.job || this.job.id !== jobId) return;
        const conNegocio = this.segmentosParaElegir().regla.length > 0;
        const q = new URLSearchParams({ por_segmento: 'true', segmentos_max: conNegocio ? String(SEGMENTOS_MAX_NEGOCIO) : '8' });
        if (this.issuesSegmento) q.set('segmento', this.issuesSegmento);
        q.set('orden', this.issuesOrden);
        const filas = await api(`/jobs/${jobId}/issues/resumen?${q}`);
        if (!this.job || this.job.id !== jobId) return;
        this.issuesResumen = filas;
        if (!this.issuesSegmento) {
          const porTipo = {};
          for (const f of filas) porTipo[f.issue_type] = (porTipo[f.issue_type] || 0) + (f.incidencias || 0);
          this.cuentaSinFiltro = { jobId, porTipo };
        }
      } catch (e) { this.error = e.message; this.issuesResumen = []; }
    },

    // ---- Diferencia frente al censo anterior, por tipo (2.10) ----
    // La referencia es la de todo lo demas: `job.comparacion.comparado_con`,
    // el censo con el que se comparo al terminar (2.3). Las cifras son las
    // que ya guarda esa comparacion (`incidencias.nuevas/resueltas/siguen`,
    // por tipo), no se recalcula nada.
    async cargarVersionAnterior() {
      const j = this.job, c = j && j.comparacion;
      if (!c || !c.comparado_con) return;
      if (this.versionAnterior && this.versionAnterior.jobId === j.id) return;
      const jobId = j.id;
      this.versionAnterior = { jobId, version: undefined };
      try {
        const ant = await api(`/jobs/${c.comparado_con}`);
        // Si ese censo leyo sus sitemaps a medias, la diferencia de «No incluida
        // en el sitemap» tampoco se puede afirmar (decision 205).
        if (this.job && this.job.id === jobId) this.versionAnterior = { jobId, version: ant.analisis_version || null, dudaSitemaps: !!dudaSitemaps(ant) };
      } catch (e) {
        // Lo que no se ha podido comprobar no se afirma (decisiones 67 y 91).
        if (this.job && this.job.id === jobId) this.versionAnterior = { jobId, version: null, error: e.message };
      }
    },

    // null si el censo no tiene comparacion; si no, { ok, ref, motivo, ... }.
    // `ok: false` cuando la diferencia no se puede dar como del sitio: otro
    // sitio u otro alcance, un censo truncado o bloqueado, o los dos censos
    // analizados con versiones distintas, tambien si uno se volvio a analizar
    // despues de compararse (decisiones 67, 70, 89, 91 y 191).
    diffProblemas() {
      const j = this.job, c = j && j.comparacion;
      if (!c || !c.comparado_con) return null;
      const dia = fmt.diaCorto(c.fecha_anterior);
      const base = { ref: 'frente al ' + dia, dia, nombre: c.nombre_anterior || '', jobAnterior: c.comparado_con };
      const no = motivo => ({ ...base, ok: false, motivo });
      if (c.comparable === false) return no('no se puede comparar con el censo anterior' + (c.motivo ? ' (' + c.motivo + ')' : ''));
      if (c.bloqueado) return no('uno de los dos censos se dio por bloqueado: no comparable');
      if (c.concluyente === false) return no('uno de los dos censos está truncado o tiene otro alcance: no comparable');
      const inc = c.incidencias;
      if (!inc) return no('la comparación de incidencias no se llegó a hacer');
      if (inc.comparable === false) return no('versión del análisis distinta: no comparable');
      if (!inc.resueltas) return no('el censo anterior está truncado: lo que ya no aparece no se puede dar por resuelto');
      if (c.analisis_version && j.analisis_version && c.analisis_version !== j.analisis_version) {
        return no('este censo se volvió a analizar después de compararse (versión del análisis distinta): no comparable');
      }
      const va = this.versionAnterior;
      if (!va || va.jobId !== j.id || va.version === undefined) return { ...base, ok: null };
      if (va.error) return no('no se ha podido comprobar con qué versión del análisis está el censo anterior');
      const esperada = c.analisis_version_anterior || j.analisis_version;
      if (!va.version || va.version !== esperada) {
        return no('el censo del ' + dia + ' se volvió a analizar después (versión del análisis distinta): no comparable');
      }
      const porTipo = {};
      const sumar = (lista, campo) => {
        for (const f of (lista || [])) {
          const d = porTipo[f.tipo] || (porTipo[f.tipo] = { nuevas: 0, resueltas: 0, siguen: 0, en_url_existente: 0, por_muestra: 0, severidad: f.severidad });
          d[campo] += f.total || 0;
        }
      };
      sumar((inc.nuevas || {}).por_tipo, 'nuevas');
      sumar((inc.resueltas || {}).por_tipo, 'resueltas');
      sumar((inc.siguen || {}).por_tipo, 'siguen');
      sumar(((inc.nuevas || {}).en_url_existente || {}).por_tipo, 'en_url_existente');
      sumar((inc.no_afirmables_por_muestra || {}).por_tipo, 'por_muestra');
      // Las incidencias de hoy tienen que ser las que se compararon: por cada
      // tipo, nuevas + siguen (+ las de axe sin muestra) = las que tiene ahora.
      // Los censos de antes de la decision 191 no traen el sello de version de
      // la comparacion, y si los dos se volvieron a analizar despues con la
      // misma version nueva, las versiones casan pero las cifras son de la
      // vieja; el cuadre lo destapa (medido en Lopesan, 26-oct: cuadran los 54
      // tipos comparables). Sin la cuenta sin filtro aun, se espera.
      const cs = this.cuentaSinFiltro;
      if (!cs || cs.jobId !== j.id) return { ...base, ok: null };
      const tipos = new Set([...Object.keys(porTipo), ...Object.keys(cs.porTipo)]);
      for (const t of tipos) {
        if (TIPOS_NO_COMPARABLES.includes(t)) continue;
        const d = porTipo[t] || { nuevas: 0, siguen: 0, por_muestra: 0 };
        if ((d.nuevas + d.siguen + d.por_muestra) !== (cs.porTipo[t] || 0)) {
          return no('las incidencias de este censo ya no son las que se compararon (alguno de los dos se volvió a analizar después): no comparable');
        }
      }
      // Sin leer todos los sitemaps, «No incluida en el sitemap» no se puede
      // afirmar (V13): tampoco su diferencia. Fuera de los totales y dicho.
      // Vale para los dos censos: si el parcial fue el de referencia, sus
      // «resueltas» tampoco se pueden afirmar (decision 205).
      const dudosos = (dudaSitemaps(j) || va.dudaSitemaps) ? TIPOS_DE_SITEMAP.filter(t => porTipo[t]) : [];
      const quitar = campo => dudosos.reduce((n, t) => n + (porTipo[t][campo] || 0), 0);
      const resueltosDelTodo = Object.entries(porTipo)
        .filter(([t]) => !dudosos.includes(t))
        .filter(([, d]) => d.resueltas && !d.siguen && !d.nuevas)
        .map(([tipo, d]) => ({ tipo, ...d }))
        .sort((a, b) => b.resueltas - a.resueltas);
      return {
        ...base, ok: true, porTipo, resueltosDelTodo, dudosos,
        nuevas: ((inc.nuevas || {}).total || 0) - quitar('nuevas'),
        resueltas: ((inc.resueltas || {}).total || 0) - quitar('resueltas'),
        sinPagina: inc.sin_pagina_en_el_nuevo || 0,
        avisos: (c.avisos || []).concat(dudosos.length ? [TEXTO_SIN_SITEMAP] : []),
      };
    },

    // La etiqueta de un tipo: «+12», «−5», «+3 · −1», «nuevo» o «igual».
    // Solo en la primera fila visible de su tipo: la comparacion cuenta por tipo con
    // todas sus gravedades juntas, y repetirla en las dos filas sumaria doble.
    cambioDeTipo(r, diff) {
      if (!diff || diff.ok !== true || this.issuesSegmento) return null;
      if ((diff.dudosos || []).includes(r.issue_type)) return null;
      const filas = this.issuesResumen || [];
      // La primera VISIBLE: con el filtro «Info» la fila de aviso del mismo
      // tipo esta oculta y la etiqueta no puede ir en ella.
      const primera = this.resumenIssues(this.issueFilters.severity).find(x => x.issue_type === r.issue_type);
      if (primera !== r) return null;
      const d = diff.porTipo[r.issue_type];
      if (!d) return null;
      const varias = filas.filter(x => x.issue_type === r.issue_type).length > 1;
      let texto, clase;
      if (d.nuevas && !d.siguen && !d.resueltas) { texto = 'nuevo'; clase = 'cambio-peor'; }
      else if (!d.nuevas && !d.resueltas) { texto = 'igual'; clase = 'cambio-igual'; }
      else {
        texto = [d.nuevas ? '+' + fmt.num(d.nuevas) : '', d.resueltas ? '−' + fmt.num(d.resueltas) : ''].filter(Boolean).join(' · ');
        clase = d.nuevas > d.resueltas ? 'cambio-peor' : (d.nuevas < d.resueltas ? 'cambio-mejor' : 'cambio-igual');
      }
      const partes = [fmt.num(d.nuevas) + (d.nuevas === 1 ? ' nueva' : ' nuevas'),
                      fmt.num(d.resueltas) + (d.resueltas === 1 ? ' resuelta' : ' resueltas'),
                      fmt.num(d.siguen) + ' siguen'];
      let title = 'Incidencias ' + diff.ref + ': ' + partes.join(', ') + '.';
      if (d.nuevas && d.en_url_existente) title += ' De las nuevas, ' + fmt.num(d.en_url_existente) + ' en páginas que ya existían.';
      if (varias) title += ' Cuenta todas sus gravedades juntas.';
      return { texto, clase, title };
    },

    // Los tipos de la vista con su gravedad elegida que ya no aparecen.
    resueltosDelTodo(diff) {
      if (!diff || diff.ok !== true || this.issuesSegmento) return [];
      const sev = this.issueFilters.severity;
      const hoy = new Set((this.issuesResumen || []).map(r => r.issue_type));
      return diff.resueltosDelTodo.filter(d => !hoy.has(d.tipo) && (!sev || d.severidad === sev));
    },

    // Lo que cuenta la fila de un tipo. De serie, paginas distintas; un
    // hallazgo de servidor por host (`soft_404_plantilla`, decision 190)
    // cuelga de UNA pagina de anclaje y «1 página» diria otra cosa: cuenta
    // plantillas, las que el analisis apunto en `jobs.soft404.resumen`.
    cuentaDeTipo(r) {
      // Con una seccion elegida, no: la cifra es del sitio entero y se leeria
      // como «esta seccion tiene 7 plantillas con soft 404»; la fila sale con
      // 0 paginas y dice que el hallazgo no se reparte, como los demas.
      if (r.issue_type === 'soft_404_plantilla' && !this.issuesSegmento) {
        const s4 = ((this.job && this.job.soft404) || {}).resumen || {};
        const n = s4.plantillas_responden_200;
        if (n) return { n, unidad: n === 1 ? 'plantilla' : 'plantillas', propia: true };
      }
      return { n: r.paginas, unidad: r.paginas === 1 ? 'página' : 'páginas', propia: false };
    },

    // ---- Secciones de negocio en Problemas (2.10) ----
    // Con segmentos de regla (decision 125) son el primer nivel: una fila por
    // seccion con sus URLs y cuantas tienen errores o avisos; las formas de
    // ruta quedan en el desplegable. Sin reglas, nada de esto se pinta.
    seccionesNegocio() {
      const lista = (this.segmentosJob && this.segmentosJob.segmentos) || [];
      const regla = lista.filter(x => x.de_regla);
      if (!regla.length) return null;
      const resto = lista.filter(x => !x.de_regla);
      return {
        secciones: regla,
        sinSeccion: resto.reduce((n, x) => n + (x.urls || 0), 0),
      };
    },

    // El reparto de un tipo con secciones de negocio: las secciones y, en una
    // linea, lo que cae fuera de todas (suma de las formas de ruta).
    // La API corta el reparto en los SEGMENTOS_MAX_NEGOCIO grupos con mas
    // paginas: si llega lleno, puede faltar alguna seccion pequena y lo de
    // fuera es «al menos», no la cifra entera (decision 67).
    repartoNegocio(r) {
      const reparto = r.por_segmento || [];
      const regla = new Set(((this.segmentosJob && this.segmentosJob.segmentos) || []).filter(x => x.de_regla).map(x => x.segmento));
      const dentro = reparto.filter(p => regla.has(p.segmento));
      const fuera = reparto.filter(p => !regla.has(p.segmento)).reduce((n, p) => n + p.paginas, 0);
      return { dentro, fuera, cortado: reparto.length >= SEGMENTOS_MAX_NEGOCIO };
    },

    // «Qué arreglar primero» del Resumen: los mismos tipos y el mismo orden
    // que la pestana Problemas por prioridad, en paginas afectadas y sin los
    // de tipo info. Antes eran los tipos con mas incidencias: el alt de las
    // imagenes y el sitemap por delante de 41 paginas en 4xx.
    async cargarPrincipales() {
      if (!this.job || (this.principales && this.principales.jobId === this.job.id)) return;
      const jobId = this.job.id;
      this.principales = { jobId, filas: null };
      try {
        const filas = await api(`/jobs/${jobId}/issues/resumen?orden=prioridad&ejemplos=0`);
        // Cinco, como el Estado del cliente y la propuesta (revision de UX del
        // 25-oct, fase 3), y una fila por tipo (decision 202).
        if (this.job && this.job.id === jobId) this.principales = { jobId, filas: filasPorTipo(filas.filter(r => r.severity !== 'info'), filas).slice(0, 5) };
      } catch (e) {
        // Un fallo no es «no hay errores»: lo que no se sabe no se afirma.
        if (this.job && this.job.id === jobId) this.principales = { jobId, filas: null, error: e.message };
      }
    },

    // Con «Todas», una fila por tipo (decision 202; filasPorTipo). Se guarda
    // por lista: cambioDeTipo y lineaIAProblema comparan la fila por
    // identidad y no puede ser otra en cada llamada.
    resumenIssues(severidad) {
      const r = this.issuesResumen || [];
      if (severidad) return r.filter(x => x.severity === severidad);
      const crudo = _crudo(r);
      let f = _cacheFilasTipo.get(crudo);
      if (!f) { f = filasPorTipo(crudo); _cacheFilasTipo.set(crudo, f); }
      return f;
    },

    verTipoDeIncidencia(tipo, severidad) {
      this.issueFilters.issue_type = tipo;
      this.issueFilters.severity = severidad || '';
      this.issuesVista = 'lista';
      this.applyIssueFilters();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    },

    volverAGrupos() {
      this.issueFilters.issue_type = '';
      this.issuesVista = 'tipos';
      this.issues = [];
    },

    applyIssueFilters() { this.issuesPage = 1; this.loadIssues(); },
    setIssuesPage(p) { if (p >= 1 && p <= this.issuesPages) { this.issuesPage = p; this.loadIssues(); } },

    // ------- Enlaces -------
    // Revision de UX del 25-oct, 2.8 (decision 195): la lista de ~926.000
    // filas sin filtros pasa a filtrarse en el servidor, con una vista por
    // destino («quien enlaza a X», «que externos estan rotos») y los destinos
    // rotos primero. Con una API anterior (sin `filtros` en la respuesta, o
    // sin /links/destinos) se ensena la lista de siempre y se dice por que.
    _reiniciarEnlaces() {
      this.links = []; this.linksPage = 1; this.linksPages = 1; this.linksTotal = 0;
      this.linksVista = 'destinos'; this.linksFiltros = { ...ENLACES_SIN_FILTROS };
      this.linksOrden = ''; this.linksPorEstado = null; this.linksFiltra = null;
      this.linksError = ''; this.linksDestinoUrl = ''; this.expExternasEnlazadas = null;
    },

    _linksQuery() {
      const q = new URLSearchParams();
      const f = this.linksFiltros;
      for (const k of ['destino', 'origen', 'ancla', 'tipo', 'follow', 'posicion', 'estado', 'codigo']) {
        const v = (f[k] ?? '').toString().trim();
        if (v) q.set(k, v);
      }
      if (f.destino && f.exacto) q.set('exacto', 'true');
      if (f.destino_hash && this.linksVista === 'enlaces') q.set('destino_hash', f.destino_hash);
      if (this.linksOrden) q.set('orden', this.linksOrden);
      q.set('page', this.linksPage);
      q.set('page_size', 50);
      return q.toString();
    },

    linksHayFiltros() {
      const f = this.linksFiltros;
      return Object.keys(ENLACES_SIN_FILTROS).some(k => k !== 'exacto' && (f[k] ?? '').toString().trim() !== '');
    },

    async loadLinks() {
      if (!this.job) return;
      const pet = ++this._linksPet;
      const jobId = this.job.id;
      const porDestino = this.linksVista === 'destinos' && this.linksFiltra !== false;
      this.linksCargando = true;
      this.linksError = '';
      try {
        const res = await fetch(`${API}/jobs/${jobId}/${porDestino ? 'links/destinos' : 'links'}?${this._linksQuery()}`,
                                { headers: { 'Content-Type': 'application/json' } });
        if (pet !== this._linksPet) return;
        const texto = await res.text();
        let data = null;
        try { data = JSON.parse(texto); } catch (_) { data = null; }
        // Una API sin /links/destinos contesta 404 «Not Found» (la ruta, no
        // «Job not found») o, detras del servidor de produccion, la pagina de
        // la aplicacion en HTML: en los dos casos, la lista de antes.
        if (porDestino && (data === null || (res.status === 404 && data.detail === 'Not Found'))) {
          this.linksFiltra = false; this.linksVista = 'enlaces';
          return this.loadLinks();
        }
        if (!res.ok || data === null) throw new Error(data ? mensajeDeError(data) : (res.statusText || 'Respuesta no válida del servidor'));
        if (pet !== this._linksPet || !this.job || this.job.id !== jobId) return;
        this.linksFiltra = data.filtros !== undefined;
        this.links = data.items || [];
        this.linksPages = data.pages || 1;
        this.linksTotal = data.total || 0;
        this.linksPorEstado = data.por_estado || null;
        // El destino de «quien la enlaza»: lo dice la primera fila.
        if (this.linksFiltros.destino_hash && this.links.length) this.linksDestinoUrl = this.links[0].to_url;
      } catch (e) {
        if (pet !== this._linksPet) return;
        this.links = []; this.linksTotal = 0;
        this.linksError = e.message || 'No se han podido cargar los enlaces.';
      }
      this.linksCargando = false;
    },

    setLinksPage(p) { if (p >= 1 && p <= this.linksPages) { this.linksPage = p; this.loadLinks(); } },

    // Un cambio de filtro vuelve a la pagina 1. Los de texto esperan a que se
    // deje de escribir: cada tecla no puede ser una consulta.
    aplicarFiltroEnlaces(campo, valor, { esperar = false } = {}) {
      if (campo) this.linksFiltros[campo] = valor;
      this.linksPage = 1;
      clearTimeout(this._linksTecla);
      if (esperar) this._linksTecla = setTimeout(() => this.loadLinks(), 450);
      else this.loadLinks();
    },

    quitarFiltrosEnlaces() {
      this.linksFiltros = { ...ENLACES_SIN_FILTROS };
      this.linksDestinoUrl = '';
      this.linksPage = 1;
      this.loadLinks();
    },

    cambiarVistaEnlaces(v) {
      if (this.linksVista === v) return;
      this._rutaNueva = true;
      this.linksVista = v;
      this.linksOrden = '';
      if (v === 'destinos') { this.linksFiltros.destino_hash = ''; this.linksDestinoUrl = ''; }
      this.links = []; this.linksPage = 1;
      this.loadLinks();
    },

    // Desde un destino: las paginas que lo enlazan.
    quienEnlaza(d) {
      this._rutaNueva = true;
      this.linksFiltros.destino_hash = d.to_url_hash;
      this.linksDestinoUrl = d.to_url;
      this.linksVista = 'enlaces';
      this.linksOrden = '';
      this.links = []; this.linksPage = 1;
      this.loadLinks();
      window.scrollTo({ top: 0 });
    },

    // Llevar a la pestaña Enlaces con unos filtros (Explorador, ficha de URL).
    irAEnlaces(filtros = {}, vista = 'destinos') {
      this._reiniciarEnlaces();
      Object.assign(this.linksFiltros, filtros);
      this.linksVista = vista;
      this.switchTab('links');
    },

    estadoDestino(e) { return ESTADO_DESTINO[e] || ESTADO_DESTINO.sin_dato; },

    // «404 · Roto», «Redirige (301)», «No concluyente: 403»: el codigo, si lo
    // hay, y en externos lo que dijo la sonda.
    textoEstadoDestino(fila) {
      const e = this.estadoDestino(fila.estado_destino);
      return fila.status_destino ? fila.status_destino + ' · ' + e.texto : e.texto;
    },

    tipEstadoDestino(fila) {
      const e = this.estadoDestino(fila.estado_destino);
      const ver = fila.veredicto_sonda || fila.estado_externo;
      return e.tip + (ver && VEREDICTO_SONDA[ver] ? ' Sonda: ' + VEREDICTO_SONDA[ver] + '.' : '');
    },

    textoAnclas(d) {
      if (!d.anclas || !d.anclas.length) return '—';
      return d.anclas.map(a => '«' + (a.texto || 'sin texto') + '» ' + fmt.num(a.veces)).join(' · ');
    },

    // Rotos, redirecciones... de la vista con los filtros de ahora (sin el de
    // estado): las cifras de los chips.
    cuentaEstadoEnlaces(g) {
      if (!this.linksPorEstado) return null;
      if (!g) return Object.values(this.linksPorEstado).reduce((a, b) => a + b, 0);
      return this.linksPorEstado[g] ?? 0;
    },

    // ------- Limpieza -------
    // Wrapper propio (en lugar de api()) para poder mostrar el detalle de los
    // errores 422 de FastAPI, que llegan como array de objetos y no como string.
    async _cleaningApi(path, opts = {}) {
      const res = await fetch(`${API}/jobs/${this.job.id}/cleaning${path}`, {
        headers: { 'Content-Type': 'application/json' },
        ...opts,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        let msg = err.detail;
        if (Array.isArray(msg)) msg = msg.map(d => d.msg || JSON.stringify(d)).join(' | ');
        throw new Error(msg || 'Error en la peticion');
      }
      return res.json();
    },

    loadCleaning() {
      if (!this.job) return;
      this.loadCleaningGroups();
      this.loadCleaningRulesets();
    },

    async loadCleaningGroups() {
      this.cleaningGroupsLoading = true;
      this.cleaningError = null;
      try {
        this.cleaningGroups = await this._cleaningApi('/groups');
      } catch (e) { this.cleaningError = e.message; }
      this.cleaningGroupsLoading = false;
      this.$nextTick(() => lucide.createIcons());
    },

    async loadCleaningRulesets() {
      try {
        this.cleaningRulesets = await this._cleaningApi('/rulesets');
      } catch (e) { this.cleaningError = e.message; }
    },

    // El editor se abre bajo la fila; otro clic en la misma fila lo cierra.
    // Al cambiar de grupo las reglas empiezan de cero: las del anterior,
    // aplicadas a otro grupo sin querer, quitarian lo que no toca
    // (revision de UX del 25-oct, 3.6).
    selectCleaningGroup(g) {
      const otro = this.cleaningSelectedGroup !== g.group_key;
      this.cleaningSelectedGroup = otro ? g.group_key : null;
      if (otro) { this.cleaningRules = [{ type: 'line_exact', value: '' }]; this.cleaningVerTodasLineas = false; }
      this.cleaningPreview = null;
      this.cleaningMessage = null;
      this.$nextTick(() => lucide.createIcons());
    },

    // «Quitar esta linea» de lo que mas se repite: una regla de linea exacta,
    // en el hueco vacio si lo hay.
    anadirLineaLimpieza(texto) {
      if (this.cleaningRules.some(r => r.type === 'line_exact' && r.value === texto)) return;
      const vacia = this.cleaningRules.find(r => !r.value.trim());
      if (vacia) { vacia.type = 'line_exact'; vacia.value = texto; }
      else this.cleaningRules.push({ type: 'line_exact', value: texto });
      this.cleaningPreview = null;
    },

    addCleaningRule() { this.cleaningRules.push({ type: 'line_contains', value: '' }); },
    removeCleaningRule(i) { this.cleaningRules.splice(i, 1); },

    _cleaningValidRules() {
      return this.cleaningRules.some(r => r.value.trim() !== '');
    },

    _cleaningPayload(withRules = true) {
      const payload = { group_key: this.cleaningSelectedGroup };
      if (this.cleaningUrlRegex.trim()) payload.url_regex = this.cleaningUrlRegex.trim();
      if (withRules) {
        payload.rules = this.cleaningRules
          .filter(r => r.value.trim() !== '')
          .map(r => ({ type: r.type, value: r.value }));
        payload.targets = this.cleaningTargets;
      }
      return payload;
    },

    async previewCleaning() {
      if (!this._cleaningValidRules()) { this.cleaningError = 'Añade al menos una regla con valor'; return; }
      this.cleaningPreviewLoading = true;
      this.cleaningError = null;
      this.cleaningMessage = null;
      try {
        this.cleaningPreview = await this._cleaningApi('/preview', {
          method: 'POST',
          body: JSON.stringify({ ...this._cleaningPayload(), sample_size: 5 }),
        });
      } catch (e) { this.cleaningError = e.message; }
      this.cleaningPreviewLoading = false;
      this.$nextTick(() => lucide.createIcons());
    },

    async applyCleaning() {
      if (!this._cleaningValidRules()) { this.cleaningError = 'Añade al menos una regla con valor'; return; }
      const group = this.cleaningGroups.find(g => g.group_key === this.cleaningSelectedGroup);
      const pages = group ? fmt.num(group.pages) : '?';
      if (!await this.preguntar({ titulo: 'Aplicar la limpieza',
        mensaje: `Se aplican las reglas al grupo «${this.cleaningSelectedGroup}» (${pages} páginas). Los originales se conservan y se puede revertir.`, aceptar: 'Aplicar' })) return;
      this.cleaningApplying = true;
      this.cleaningError = null;
      this.cleaningMessage = null;
      try {
        const res = await this._cleaningApi('/apply', {
          method: 'POST',
          body: JSON.stringify(this._cleaningPayload()),
        });
        this.cleaningMessage = `Limpieza aplicada: ${fmt.num(res.pages_updated)} páginas actualizadas, ${fmt.num(res.total_chars_removed)} caracteres eliminados`
          + (res.pages_skipped_safety ? ` (${fmt.num(res.pages_skipped_safety)} saltadas por la válvula de seguridad)` : '');
        this.showToast('Limpieza aplicada');
        this.cleaningPreview = null;
        await Promise.all([this.loadCleaningGroups(), this.loadCleaningRulesets()]);
      } catch (e) { this.cleaningError = e.message; }
      this.cleaningApplying = false;
    },

    async revertCleaning() {
      if (!await this.preguntar({ titulo: 'Revertir la limpieza',
        mensaje: `Se restaura el contenido original del grupo «${this.cleaningSelectedGroup}».`, aceptar: 'Revertir' })) return;
      this.cleaningReverting = true;
      this.cleaningError = null;
      this.cleaningMessage = null;
      try {
        const res = await this._cleaningApi('/revert', {
          method: 'POST',
          body: JSON.stringify(this._cleaningPayload(false)),
        });
        this.cleaningMessage = `Limpieza revertida: ${fmt.num(res.pages_updated)} páginas restauradas`;
        this.showToast('Limpieza revertida', 'info');
        this.cleaningPreview = null;
        await Promise.all([this.loadCleaningGroups(), this.loadCleaningRulesets()]);
      } catch (e) { this.cleaningError = e.message; }
      this.cleaningReverting = false;
    },

    // ------- Exportar -------
    exportCSV() {
      if (!this.job) return;
      window.open(`${API}/jobs/${this.job.id}/export`, '_blank');
    },

    exportLinksCSV() {
      if (!this.job) return;
      window.open(`${API}/jobs/${this.job.id}/links/export`, '_blank');
    },

    exportContentCSV() {
      if (!this.job) return;
      window.open(`${API}/jobs/${this.job.id}/content/export`, '_blank');
    },

    exportBackup() {
      if (!this.job) return;
      window.open(`${API}/jobs/${this.job.id}/backup`, '_blank');
    },

    // ------- Reanudar job fallido / cancelado -------
    showResumeModal: false,
    resuming: false,
    resumeForm: {
      max_runtime_hours: 6,
      autothrottle_enabled: true,
      concurrent_requests_per_domain: 8,
      concurrent_requests: 32,
    },

    openResumeDialog() {
      if (!this.job) return;
      const cfg = this.job.config || {};
      const cb = cfg.crawl_behavior || {};
      this.resumeForm = {
        max_runtime_hours: cb.max_runtime_hours || 6,
        autothrottle_enabled: cb.autothrottle_enabled !== false,
        concurrent_requests_per_domain: cfg.concurrent_requests_per_domain || 8,
        concurrent_requests: cfg.concurrent_requests || 32,
      };
      this.showResumeModal = true;
      this.$nextTick(() => lucide.createIcons());
    },

    async confirmResume() {
      if (!this.job || this.resuming) return;
      this.resuming = true;
      try {
        const overrides = {
          concurrent_requests: parseInt(this.resumeForm.concurrent_requests) || 32,
          concurrent_requests_per_domain: parseInt(this.resumeForm.concurrent_requests_per_domain) || 8,
          crawl_behavior: {
            max_runtime_hours: parseInt(this.resumeForm.max_runtime_hours) || 6,
            autothrottle_enabled: !!this.resumeForm.autothrottle_enabled,
          },
        };
        this.job = await api(`/jobs/${this.job.id}/resume`, {
          method: 'POST',
          body: JSON.stringify(overrides),
        });
        this.showResumeModal = false;
        this.showToast('Rastreo reanudado', 'info');
        // Restart progress polling
        this._startProgress();
      } catch (e) {
        this.avisar('No se pudo reanudar', e.message);
      }
      this.resuming = false;
    },

    // ------- Analisis enriquecido (#40, decision 85) -------
    // Lo unico de la interfaz que gasta dinero. El dialogo estima SIEMPRE
    // antes de dejar lanzar, y el token va en la cabecera de la peticion de
    // lanzar y en ningun otro sitio: sessionStorage (muere con la pestaña),
    // nunca localStorage ni la URL.
    enriqAbierto: false,
    enriqCatalogo: [],
    enriqLanzable: false,
    enriqForm: { modulos: [], tipo: 'todas', carpeta: '', max_urls: 500, presupuesto: 0.01 },
    enriqEstimacion: null,
    enriqEstimando: false,
    enriqLanzando: false,
    enriqError: null,
    enriqToken: '',
    enriqRuns: [],
    enriqRun: null,
    enriqDecisiones: null,
    enriqFiltro: { pregunta: null, respuesta: null, page: 1 },
    enriqPlantillas: null,
    enriqTimer: null,
    enriqIntencion: null,
    // Pestana IA (revision de UX del 25-oct, 2.9): llamadas, cache, tokens,
    // presupuesto y tope de todos los clientes, plegados en el lanzador.
    enriqAvanzado: false,
    // La linea «Revisado con IA» de cada tipo de problema y las respuestas de
    // la IA sobre la URL abierta. Solo lecturas de lo ya pagado.
    iaProblemas: null,
    iaUrl: null,
    _decisionesIA: {},

    _alcanceEnriq() {
      const f = this.enriqForm;
      if (f.tipo === 'carpeta') return { carpeta: (f.carpeta || '').trim() || null };
      if (f.tipo === 'max') return { max_urls: parseInt(f.max_urls) || null };
      if (f.tipo === 'muestra') return { muestra: true, max_urls: parseInt(f.max_urls) || 500 };
      return {};
    },

    // El catalogo de modulos: el lanzador lo necesita y la pestana IA lo usa
    // para nombrar los modulos del historial y ver si ya se pregunto lo mismo.
    async cargarCatalogoEnriq() {
      if (this.enriqCatalogo.length) return true;
      try {
        const cat = await api('/enrichment/modulos');
        this.enriqCatalogo = cat.modulos;
        this.enriqLanzable = cat.lanzamiento_activado;
        return true;
      } catch (e) { this.enriqError = e.message; return false; }
    },

    async abrirEnriquecido() {
      if (!this.job || this.job.status !== 'completed') return;
      this.enriqError = null;
      this.enriqEstimacion = null;
      this.enriqAvanzado = false;
      try { this.enriqToken = sessionStorage.getItem('enrichment-token') || ''; } catch { this.enriqToken = ''; }
      this.enriqCatalogo = [];
      if (!(await this.cargarCatalogoEnriq())) { this.showToast(this.enriqError, 'error'); return; }
      // Sin nada marcado: que el coste aparezca solo cuando alguien elige.
      // Con un unico modulo se marca para que la estimacion salga de entrada.
      if (!this.enriqForm.modulos.length && this.enriqCatalogo.length === 1) {
        this.enriqForm.modulos = [this.enriqCatalogo[0].nombre];
      }
      this.enriqAbierto = true;
      this.$nextTick(() => lucide.createIcons());
      this.estimarEnriquecido();
    },

    alternarModuloEnriq(nombre, marcado) {
      const m = this.enriqForm.modulos.filter(n => n !== nombre);
      if (marcado) m.push(nombre);
      this.enriqForm.modulos = m;
      this.estimarEnriquecido();
    },

    async estimarEnriquecido() {
      if (!this.job) return;
      this.enriqError = null;
      if (!this.enriqForm.modulos.length) { this.enriqEstimacion = null; return; }
      this.enriqEstimando = true;
      try {
        const e = await api(`/jobs/${this.job.id}/enrichment/estimate`, {
          method: 'POST',
          body: JSON.stringify({ modulos: this.enriqForm.modulos, alcance: this._alcanceEnriq() }),
        });
        this.enriqEstimacion = e;
        this.enriqForm.presupuesto = e.presupuesto_sugerido_usd;
      } catch (e) {
        this.enriqEstimacion = null;
        this.enriqError = e.message;
      }
      this.enriqEstimando = false;
    },

    async lanzarEnriquecido() {
      if (!this.job || this.enriqLanzando || !this.enriqEstimacion) return;
      this.enriqLanzando = true;
      this.enriqError = null;
      const token = (this.enriqToken || '').trim();
      try {
        const run = await api(`/jobs/${this.job.id}/enrichment`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Enrichment-Token': token },
          body: JSON.stringify({
            modulos: this.enriqForm.modulos,
            alcance: this._alcanceEnriq(),
            presupuesto_usd: parseFloat(this.enriqForm.presupuesto) || 0,
          }),
        });
        try { sessionStorage.setItem('enrichment-token', token); } catch {}
        this.enriqAbierto = false;
        this.showToast('Consulta a la IA en cola', 'info');
        this.switchTab('enriquecido');
        await this.cargarEjecuciones(run.id);
      } catch (e) {
        // Un token rechazado no se guarda: que la proxima vez se pida otra vez.
        if (/token/i.test(e.message)) { try { sessionStorage.removeItem('enrichment-token'); } catch {} }
        this.enriqError = this.textoErrorEnriq(e.message);
      }
      this.enriqLanzando = false;
    },

    async cargarEjecuciones(elegir = null) {
      if (!this.job) return;
      try {
        this.enriqRuns = await api(`/jobs/${this.job.id}/enrichment`);
      } catch { this.enriqRuns = []; return; }
      if (this.detailTab === 'enriquecido') this.cargarCatalogoEnriq();
      this.cargarIAProblemas();
      if (this.view === 'url-detail') this.cargarIAUrl();
      const id = elegir || (this.enriqRun && this.enriqRun.id) || (this.enriqRuns[0] && this.enriqRuns[0].id);
      if (id && this.detailTab === 'enriquecido') await this.verEjecucion(id);
    },

    async verEjecucion(id) {
      if (!this.job || !id) return;
      if (!this.enriqRun || this.enriqRun.id !== id) {
        this.enriqDecisiones = null;
        this.enriqPlantillas = null;
        this.enriqFiltro = { pregunta: null, respuesta: null, page: 1 };
      }
      try {
        this.enriqRun = await api(`/jobs/${this.job.id}/enrichment/${id}`);
      } catch (e) { this.error = e.message; return; }
      this.cargarIntencionEnriq();
      this._pararEnriq();
      if (['pendiente', 'en_curso', 'cancelando'].includes(this.enriqRun.estado)) {
        this.enriqTimer = setInterval(async () => {
          if (!this.job || !this.enriqRun) return this._pararEnriq();
          try {
            const r = await api(`/jobs/${this.job.id}/enrichment/${this.enriqRun.id}`);
            this.enriqRun = r;
            const i = this.enriqRuns.findIndex(x => x.id === r.id);
            if (i >= 0) this.enriqRuns[i] = { ...this.enriqRuns[i], estado: r.estado, gastado_usd: r.gastado_usd };
            if (!['pendiente', 'en_curso', 'cancelando'].includes(r.estado)) { this._pararEnriq(); this.cargarIntencionEnriq(); }
          } catch {}
        }, 3000);
      }
      this.$nextTick(() => lucide.createIcons());
    },

    _pararEnriq() {
      if (this.enriqTimer) { clearInterval(this.enriqTimer); this.enriqTimer = null; }
    },

    async cancelarEnriquecido() {
      if (!this.job || !this.enriqRun) return;
      try {
        this.enriqRun = await api(`/jobs/${this.job.id}/enrichment/${this.enriqRun.id}/cancel`, { method: 'PATCH' });
        this.showToast('Cancelación pedida: lo ya pagado se conserva', 'info');
        await this.cargarEjecuciones(this.enriqRun.id);
      } catch (e) { this.showToast(e.message, 'error'); }
    },

    // Intencion de la pagina frente a sus busquedas y embudo con trafico
    // (decision 176). Solo si la ejecucion hizo alguno de los dos modulos.
    async cargarIntencionEnriq() {
      this.enriqIntencion = null;
      const run = this.enriqRun;
      if (!this.job || !run || !(run.modulos || []).some(m => m.startsWith('intencion_'))) return;
      try {
        this.enriqIntencion = await api(`/jobs/${this.job.id}/enrichment/${run.id}/intencion?limite=50`);
      } catch { this.enriqIntencion = null; }
    },

    // Un score llega agrupado por nivel («0»...«3», en orden en `opciones`) y
    // se escribe con el nombre corto de cada nivel (`etiquetas`, decision 177);
    // lo demas, con el diccionario unico de `fmt.respuestaEnriq`.
    // El nombre de cada pregunta en castellano llano (revision de UX del
    // 25-oct, 1.14): la pestana pintaba «es_soft_404» tal cual.
    tituloPreguntaEnriq(preg) {
      return ({
        es_soft_404: '¿Es una página de error que responde 200 (soft 404)?',
        es_pagina_legal: '¿Es una página legal?',
        es_pagina_de_utilidad: '¿Es una página de utilidad (carrito, login, buscador)?',
        tipo_pagina: 'Tipo de página',
        categoria_cliente: 'Categoría del cliente',
        intencion_pagina: 'Intención de la página',
        intencion_busqueda: 'Intención de sus búsquedas',
        etapa_embudo: 'Etapa del embudo',
        paginas_sustitutas: '¿Las dos páginas compiten por la misma búsqueda?',
        recomendacion_canibalizacion: 'Qué hacer con la canibalización',
        title_describe_contenido: '¿El title describe el contenido?',
        title_es_generico: '¿El title es genérico?',
        schema_contradice_contenido: '¿El marcado contradice lo visible?',
      })[preg] || preg;
    },

    // Las descripciones de los modulos (shared/enriquecido.py) hablan de
    // «Sin evaluar (#8)» y «salen inciertas»: en pantalla, en llano.
    descripcionEnriq(t) {
      // Y sin las referencias internas («(decision 105)», «(#39, decision
      // 176)», «de #7»), que no le dicen nada a quien lanza (2.9).
      return String(t || '').replace(/Sin evaluar \(#8\)/g, 'Sin calibrar').replace(/Sin umbral \(#8[^)]*\)/g, 'Sin calibrar')
        .replace(/salen inciertas/g, 'son orientativas').replace(/todo incierto/g, 'todo orientativo')
        .replace(/\s*\((?:aviso de la )?(?:#\d+[^)]*|decisi[oó]n \d+[^)]*)\)/g, '').replace(/ de #\d+/g, '').replace(/Sin umbral\b/g, 'Sin calibrar');
    },

    // Una respuesta suelta: su estado en palabras.
    estadoUnaEnriq(est) {
      return ({ decidido: 'decidida', incierto: 'orientativa', sin_decidir: 'sin decidir' })[est] || est;
    },

    // Los estados de las respuestas, en palabras: «incierto» era jerga.
    estadoEnriq(est, n) {
      const t = ({ decidido: ['decidida', 'decididas'], incierto: ['orientativa', 'orientativas'],
                   sin_decidir: ['sin decidir', 'sin decidir'] })[est];
      return t ? fmt.num(n) + ' ' + t[n === 1 ? 0 : 1] : est + ': ' + fmt.num(n);
    },

    etiquetaEnriq(pregunta, resp) {
      const r = ((this.enriqRun && this.enriqRun.resultados) || {})[pregunta] || {};
      return (r.etiquetas || {})[resp] || fmt.respuestaEnriq(resp);
    },
    textoDecisionEnriq(d) {
      if (d.respuesta === null) return d.motivo || '—';
      const r = ((this.enriqRun && this.enriqRun.resultados) || {})[d.pregunta] || {};
      if (r.tipo === 'score') {
        const n = Number(d.respuesta);
        return this.etiquetaEnriq(d.pregunta, d.nivel) + (isNaN(n) ? '' : ' (' + fmt.dec(n, 2) + ')');
      }
      return this.etiquetaEnriq(d.pregunta, d.respuesta);
    },

    async cargarDecisionesEnriq(pregunta = undefined, respuesta = undefined) {
      if (!this.job || !this.enriqRun) return;
      if (pregunta !== undefined) this.enriqFiltro = { pregunta, respuesta, page: 1 };
      const f = this.enriqFiltro;
      const q = new URLSearchParams({ page: f.page, page_size: 50 });
      if (f.pregunta) q.set('pregunta', f.pregunta);
      if (f.respuesta) q.set('respuesta', f.respuesta);
      try {
        this.enriqDecisiones = await api(`/jobs/${this.job.id}/enrichment/${this.enriqRun.id}/decisions?${q}`);
      } catch (e) { this.error = e.message; }
    },

    // Respuestas de una pregunta. Un choice corto con sus opciones (la
    // intencion o el embudo, decision 176) se lee en el orden del catalogo, y
    // las que no esten en el, detras; uno largo (el tipo de pagina, decision
    // 178) o sin opciones, de la mas frecuente a la menos. Un score trae como
    // opciones sus niveles «0»...«n-1» (decision 177): sale en orden de nivel.
    respuestasEnriq(r) {
      const pares = Object.entries(r.por_respuesta || {});
      if (!r.opciones || r.opciones.length > 7) return pares.sort((a, b) => b[1] - a[1]);
      const pos = o => { const i = r.opciones.indexOf(o); return i < 0 ? 999 : i; };
      return pares.sort((a, b) => pos(a[0]) - pos(b[0]) || b[1] - a[1]);
    },

    // Propuesta por plantilla (decision 178): que responden las muestras de
    // cada plantilla. Solo lectura; sin umbral nada sale propagable.
    async cargarPlantillasEnriq(pregunta) {
      if (!this.job || !this.enriqRun) return;
      try {
        const q = new URLSearchParams({ pregunta });
        this.enriqPlantillas = await api(`/jobs/${this.job.id}/enrichment/${this.enriqRun.id}/plantillas?${q}`);
      } catch (e) { this.error = e.message; }
    },

    // Los mensajes de la API hablan de «token» y de ENRICHMENT_TOKEN: en
    // pantalla es la clave de autorizacion (revision de UX del 25-oct, 2.9).
    textoErrorEnriq(msg) {
      const m = String(msg || '');
      if (/incorrecto o ausente/i.test(m)) return 'La clave de autorización no es correcta. Pídesela a quien administra el crawler.';
      if (/ENRICHMENT_TOKEN/.test(m)) return 'Este servidor no tiene configurada la clave de autorización: se puede ver el coste, pero no lanzar.';
      return m.replace(/de la instancia/g, 'de todos los clientes');
    },

    // El nombre de cada modulo en castellano llano y con tildes: el catalogo
    // (shared/enriquecido.py) dice «Pagina legal (ejemplo)» o «Canibalizacion
    // por busqueda (juicio)». Uno nuevo sale con su titulo, sin el parentesis.
    tituloModuloEnriq(nombre) {
      const t = ({
        pagina_legal: 'Página legal (de prueba)', soft_404: 'Soft 404', pagina_de_utilidad: 'Páginas de utilidad',
        canibalizacion: 'Canibalización por búsqueda', intencion_pagina: 'Intención y embudo de la página',
        intencion_busquedas: 'Intención de las búsquedas de Search Console', tipo_pagina: 'Tipo de página (por plantilla)',
        categoria_cliente: 'Categoría del cliente (por plantilla)', title_contenido: 'El título frente al contenido',
        title_generico: 'Título genérico', schema_visible: 'Datos estructurados frente a lo visible',
      })[nombre];
      if (t) return t;
      const m = this.enriqCatalogo.find(x => x.nombre === nombre);
      return m ? m.titulo.replace(/\s*\([^)]*\)\s*$/, '') : nombre;
    },
    // En el lanzador, el nombre a secas. Antes llevaba «· solo a las
    // sospechosas» cuando el titulo del catalogo decia «candidatos», pero 10
    // de los 11 modulos eligen sus paginas (filtrar_urls), no solo esos dos:
    // a quien pregunta cada uno lo dice su explicacion (revision de UX del
    // 25-oct, 2.9).
    etiquetaModuloEnriq(m) {
      return this.tituloModuloEnriq(m.nombre);
    },
    // Lo que pregunta cada modulo y a que paginas, en castellano llano: el
    // catalogo (shared/enriquecido.py) lo dice sin tildes y con jerga
    // («score de 4 niveles», «placeholders», «TOFU, MOFU, BOFU»). Sin cifras
    // de topes, que viven en el modulo y cambiarian aqui sin avisar. Uno nuevo
    // sale con la descripcion del catalogo, limpia de referencias
    // (revision de UX del 25-oct, 2.9). Un test comprueba que no falta ninguno.
    explicacionModuloEnriq(m) {
      const t = EXPLICACION_MODULO_IA[m && m.nombre];
      return t || this.descripcionEnriq(m && m.descripcion);
    },
    // A cuantas URLs (o pares) pregunto de verdad, segun su estimacion: sin
    // recorte, «las candidatas» de un modulo pueden ser 17 de 3.216.
    urlsPreguntadasEnriq(run) {
      const pm = (run && run.estimacion && run.estimacion.por_modulo) || {};
      const v = Object.values(pm);
      if (!v.length) return null;
      const urls = v.filter(x => x.unidad !== 'grupos').reduce((a, x) => Math.max(a, x.urls || 0), 0);
      const grupos = v.filter(x => x.unidad === 'grupos').reduce((a, x) => a + (x.urls || 0), 0);
      return [urls ? fmt.num(urls) + (urls === 1 ? ' URL' : ' URLs') : '', grupos ? fmt.num(grupos) + (grupos === 1 ? ' par' : ' pares') : '']
        .filter(Boolean).join(' y ') || 'ninguna URL';
    },

    // Las preguntas que haria lo marcado en el lanzador, con las dependencias
    // que la estimacion haya anadido.
    _preguntasDeModulos(nombres) {
      const ps = new Set();
      for (const n of nombres || []) {
        const m = this.enriqCatalogo.find(x => x.nombre === n);
        (m ? m.preguntas : []).forEach(p => ps.add(p));
      }
      return ps;
    },
    // Antes de pagar otra vez (2.9): una ejecucion de este censo que ya hizo
    // todas las preguntas marcadas, con el mismo alcance o con otro (se dice).
    // Las fallidas y canceladas no cuentan: no dejaron respuestas completas.
    ejecucionRepetidaEnriq() {
      const marcadas = this._preguntasDeModulos((this.enriqEstimacion && this.enriqEstimacion.modulos) || this.enriqForm.modulos);
      if (!marcadas.size) return null;
      const alcance = JSON.stringify(this._normAlcanceEnriq(this._alcanceEnriq()));
      const run = this.enriqRuns.find(r => ['completada', 'parcial', 'en_curso', 'pendiente'].includes(r.estado)
        && [...marcadas].every(p => this._preguntasDeModulos(r.modulos).has(p)));
      if (!run) return null;
      return { run, mismoAlcance: JSON.stringify(this._normAlcanceEnriq(run.alcance)) === alcance };
    },
    _normAlcanceEnriq(a) {
      a = a || {};
      return { carpeta: a.carpeta || null, max_urls: a.max_urls || null, muestra: !!a.muestra };
    },
    verEjecucionDesdeLanzador(id) {
      this.enriqAbierto = false;
      this.switchTab('enriquecido');
      this.verEjecucion(id);
    },

    // Las respuestas de una ejecucion, de 500 en 500 y hasta 2.000: alcanza
    // para lo que se paga a mano. Mas alla `completo` es false y quien lo usa
    // no afirma que una URL no se pregunto.
    async _decisionesDeEjecucion(runId, pregunta = null) {
      const clave = runId + '|' + (pregunta || '');
      if (this._decisionesIA[clave]) return this._decisionesIA[clave];
      const items = [];
      let total = 0;
      for (let page = 1; page <= 4; page++) {
        const q = new URLSearchParams({ page, page_size: 500 });
        if (pregunta) q.set('pregunta', pregunta);
        const r = await api(`/jobs/${this.job.id}/enrichment/${runId}/decisions?${q}`);
        total = r.total;
        items.push(...r.items);
        if (items.length >= total || !r.items.length) break;
      }
      return (this._decisionesIA[clave] = { items, completo: items.length >= total });
    },

    // La ejecucion mas reciente que contesto una pregunta, ya terminada.
    _ultimaEjecucionCon(pregunta) {
      return this.enriqRuns.find(r => ['completada', 'parcial'].includes(r.estado)
        && this._preguntasDeModulos(r.modulos).has(pregunta));
    },

    // «Revisado con IA» por tipo de problema (2.9). Por pares: lo que dijo la
    // IA de los pares de ese aviso. Por URL: solo las paginas que tienen el
    // problema, cruzadas con las respuestas; si alguna de las dos listas no se
    // ha podido leer entera, no se dice nada (no se afirma lo que no se sabe).
    async cargarIAProblemas() {
      if (!this.job) return;
      const jobId = this.job.id;
      const clave = jobId + '|' + this.enriqRuns.map(r => r.id + r.estado).join(',');
      if (this.iaProblemas && this.iaProblemas.clave === clave) return;
      this.iaProblemas = { jobId, clave, porTipo: {} };
      if (!this.enriqRuns.length) return;
      if (!(await this.cargarCatalogoEnriq())) return;
      const porTipo = {};
      for (const [tipo, cfg] of Object.entries(PROBLEMA_PREGUNTA_IA)) {
        const run = this._ultimaEjecucionCon(cfg.pregunta);
        if (!run) continue;
        try {
          let si = 0, no = 0, otras = 0, decididas = 0;
          if (cfg.porUrl) {
            const iss = await api(`/jobs/${jobId}/issues?issue_type=${tipo}&page=1&page_size=200`);
            if (iss.total > iss.items.length) continue;
            const dec = await this._decisionesDeEjecucion(run.id, cfg.pregunta);
            if (!dec.completo) continue;
            const delProblema = new Set(iss.items.map(i => i.url));
            for (const d of dec.items) {
              if (!delProblema.has(d.url)) continue;
              if (d.respuesta === 'true') si++; else if (d.respuesta === 'false') no++; else otras++;
              if (d.estado === 'decidido') decididas++;
            }
          } else {
            const det = await api(`/jobs/${jobId}/enrichment/${run.id}`);
            const r = (det.resultados || {})[cfg.pregunta];
            if (!r) continue;
            si = (r.por_respuesta || {}).true || 0;
            no = (r.por_respuesta || {}).false || 0;
            otras = Math.max(0, r.total - si - no);
            decididas = (r.por_estado || {}).decidido || 0;
          }
          const n = si + no + otras;
          if (!n) continue;
          porTipo[tipo] = { run, pregunta: cfg.pregunta, si, no, otras, n, cfg,
                            orientativo: decididas < n };
        } catch { /* sin la linea: la fila del problema sale igual */ }
      }
      if (this.job && this.job.id === jobId) this.iaProblemas = { jobId, clave, porTipo };
    },
    // La linea de una fila de Problemas: solo en la primera fila del tipo
    // (un tipo puede salir con dos gravedades).
    lineaIAProblema(r) {
      // Con un segmento elegido la fila cuenta solo sus paginas y la linea
      // hablaria de todo el censo: no se mezcla.
      const x = !this.issuesSegmento && this.iaProblemas && this.iaProblemas.porTipo[r.issue_type];
      if (!x) return null;
      const primera = (this.resumenIssues(this.issueFilters.severity).find(y => y.issue_type === r.issue_type) || {}).severity;
      if (primera !== r.severity) return null;
      const u = n => n === 1 ? x.cfg.unidad[0] : x.cfg.unidad[1];
      const partes = [x.cfg.si + ' en ' + fmt.num(x.si), x.cfg.no + ' en ' + fmt.num(x.no)];
      if (x.otras) partes.push('sin respuesta clara en ' + fmt.num(x.otras));
      return {
        texto: 'Revisado con IA el ' + fmt.dia(x.run.created_at) + (x.cfg.porUrl ? ', ' + fmt.num(x.n) + ' ' + u(x.n) + ' de este problema' : ', ' + fmt.num(x.n) + ' ' + u(x.n))
          + ': ' + partes.join(', ') + (x.orientativo ? ' · orientativo' : ''),
        run: x.run, pregunta: x.pregunta,
      };
    },
    verResultadoIA(runId, pregunta) {
      this.switchTab('enriquecido');
      this.verEjecucion(runId).then(() => pregunta && this.cargarDecisionesEnriq(pregunta, null));
    },

    // Lo que contesto la IA sobre la URL abierta (2.9): las respuestas de las
    // tres ultimas ejecuciones terminadas, solo las que son de la pagina (no
    // las de un par o una busqueda, que solo cuelgan de ella).
    async cargarIAUrl() {
      this.iaUrl = null;
      if (!this.job || !this.urlDetail || !this.enriqRuns.length) return;
      const jobId = this.job.id, url = this.urlDetail.url;
      const filas = [];
      const vistas = new Set();
      for (const run of this.enriqRuns.filter(r => ['completada', 'parcial'].includes(r.estado)).slice(0, 3)) {
        try {
          const dec = await this._decisionesDeEjecucion(run.id);
          for (const d of dec.items) {
            if (d.url !== url || d.busqueda || d.rutas || vistas.has(d.pregunta)) continue;
            vistas.add(d.pregunta);
            filas.push({ run, d });
          }
        } catch { /* sin respuestas que ensenar */ }
      }
      if (this.job && this.job.id === jobId && this.urlDetail && this.urlDetail.url === url) this.iaUrl = filas;
    },

    // ------- Importar backup -------
    showImportModal: false,
    importFile: null,
    importing: false,
    importError: null,
    importResult: null,
    importPreserveId: false,

    closeImportModal() {
      this.showImportModal = false;
      this.importFile = null;
      this.importError = null;
      this.importResult = null;
      this.importPreserveId = false;
      // Refresh jobs list if we imported something
      if (this.view === 'jobs') this.loadJobs();
    },

    async submitImport() {
      if (!this.importFile) return;
      this.importing = true;
      this.importError = null;
      this.importResult = null;
      try {
        const formData = new FormData();
        formData.append('file', this.importFile);
        const params = this.importPreserveId ? '?preserve_job_id=true' : '';
        const res = await fetch(`${API}/jobs/import${params}`, {
          method: 'POST',
          body: formData,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(err.detail || 'Error al importar');
        }
        this.importResult = await res.json();
        this.showToast('Backup importado correctamente');
        // Refresh jobs list
        if (this.view === 'jobs') this.loadJobs();
      } catch (e) {
        this.importError = e.message;
      }
      this.importing = false;
    },

    // ------- Helpers -------
    statusColor(s) {
      return { pending:'badge-pending', running:'badge-running', analyzing:'badge-running', completed:'badge-completed', failed:'badge-failed', cancelled:'badge-neutral', deleting:'badge-neutral', vaciado:'badge-neutral' }[s] || 'badge-pending';
    },

    barColor(group) {
      return { '2xx':'var(--green)', '3xx':'var(--blue)', '4xx':'var(--orange)', '5xx':'var(--red)' }[group] || 'var(--text-dim)';
    },

    maxStatusCount() {
      if (!this.stats) return 1;
      return Math.max(1, ...this.stats.urls_by_status_group.map(s => s.count));
    },

    issueBarColor(sev) {
      return { error:'var(--red)', warning:'var(--orange)', info:'var(--blue)' }[sev] || 'var(--text-dim)';
    },

    get issueTypes() {
      if (!this.stats) return [];
      return [...new Set(this.stats.issues_by_type.map(i => i.issue_type))];
    },

    crawledPercent() {
      if (!this.progress) return 0;
      const hechas = this.progress.crawled_count || 0;
      const cola = this.progress.pending_count;
      // Sin tope de URLs el porcentaje se mide contra el trabajo real que
      // queda (rastreadas / (rastreadas + en cola)), no contra un numero
      // inventado de antemano. Con tope se sigue midiendo contra el, porque
      // ahi si marca el final del rastreo.
      const tope = this.job?.config?.max_urls;
      if (tope) return Math.min(100, (hechas / tope) * 100);
      if (cola === null || cola === undefined) return 0;
      const total = hechas + cola;
      return total > 0 ? Math.min(100, (hechas / total) * 100) : 0;
    },

    // URL detail helpers
    headingIndent(tag) {
      const level = parseInt(tag.replace('h', '')) || 1;
      return (level - 1) * 1.25;
    },

    headingColor(tag) {
      const colors = { h1: 'var(--accent)', h2: 'var(--green)', h3: 'var(--blue)', h4: 'var(--orange)', h5: 'var(--text-dim)', h6: 'var(--text-dim)' };
      return colors[tag] || 'var(--text-dim)';
    },

    renderMarkdown(md) {
      if (!md) return '';
      // El markdown viene del sitio rastreado, no es de confianza: marked@15 ya
      // no sanea, asi que pasamos su HTML por DOMPurify antes del x-html. Sin el
      // (p.ej. CDN caido), devolvemos texto escapado, nunca HTML crudo. Decision 206.
      const escapar = (t) => '<pre>' + String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>';
      try {
        const html = marked.parse(md);
        if (typeof DOMPurify === 'undefined' || !DOMPurify.sanitize) return escapar(md);
        return DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
      } catch {
        return escapar(md);
      }
    },

    securityScore() {
      if (!this.urlDetail?.security) return null;
      const s = this.urlDetail.security;
      // `has_unsafe_crossorigin` ya no cuenta: desde 2021 los navegadores
      // aplican `noopener` por defecto a target="_blank". El dato se sigue
      // guardando, pero no es un fallo que arreglar.
      let score = 0, total = 6;
      if (s.is_https) score++;
      if (!s.has_mixed_content) score++;
      if (s.has_hsts) score++;
      if (s.has_csp) score++;
      if (s.has_x_content_type_options) score++;
      if (s.has_x_frame_options) score++;
      return { score, total, pct: Math.round(score / total * 100) };
    },

    fmt,

    // ------- Reinit Lucide icons -------
    reinitIcons() {
      this.$nextTick(() => { if (window.lucide) lucide.createIcons(); });
    },

    // ===================================================================
    //      WORDPRESS (decisiones 161 y 168): inventario y «Solo en WordPress»
    // ===================================================================
    wpAssets: null,             // GET /jobs/{id}/wordpress/assets, al pintar la tarjeta
    wpAssetsJob: null,          // de qué job es `wpAssets`
    wpAssetsError: '',
    expWp: false,               // el Explorador enseña «Solo en WordPress» en vez de la tabla
    wpSolo: { items: [], total: 0, page: 1, pages: 1, tipo: '', buscar: '', cargando: false, error: '' },
    _wpBuscarTimer: null,
    _wpPedida: '',

    async cargarWpAssets() {
      if (!this.job || this.wpAssetsJob === this.job.id) return;
      const id = this.job.id;
      this.wpAssetsJob = id;
      this.wpAssets = null;
      this.wpAssetsError = '';
      try {
        const r = await api(`/jobs/${id}/wordpress/assets`);
        if (this.wpAssetsJob === id) this.wpAssets = r;
      } catch (e) {
        if (this.wpAssetsJob === id) this.wpAssetsError = e.message;
      }
    },

    // Desde la tarjeta del Resumen: el Explorador con la lista de ese tipo.
    verSoloWordPress(tipo = '') {
      this.openExplorer({ wordpress: tipo || 'todo' });
    },

    abrirSoloWordPress(tipo = '') {
      this.expWp = true;
      this.expDetailOpen = false;
      this.wpSolo = { ...this.wpSolo, items: [], total: 0, page: 1, pages: 1, tipo: tipo || '', buscar: '', error: '' };
      this.cargarSoloWordPress();
    },

    cerrarSoloWordPress() {
      this.expWp = false;
    },

    async cargarSoloWordPress() {
      if (!this.job) return;
      const w = this.wpSolo;
      const q = new URLSearchParams({ solo_no_rastreadas: 'true', page: String(w.page), page_size: '100' });
      if (w.tipo) q.set('tipo', w.tipo);
      if (w.buscar.trim()) q.set('buscar', w.buscar.trim());
      const pedida = q.toString();
      this._wpPedida = pedida;
      w.cargando = true;
      w.error = '';
      try {
        const r = await api(`/jobs/${this.job.id}/wordpress/entidades?${pedida}`);
        // Una respuesta lenta de una búsqueda anterior no pisa la última.
        if (this._wpPedida !== pedida) return;
        Object.assign(this.wpSolo, { items: r.items || [], total: r.total || 0, pages: r.pages || 1 });
      } catch (e) {
        this.wpSolo.error = e.message;
      } finally {
        this.wpSolo.cargando = false;
      }
    },

    elegirTipoSoloWordPress(tipo) {
      this.wpSolo.tipo = tipo;
      this.wpSolo.page = 1;
      this.cargarSoloWordPress();
    },

    buscarSoloWordPress() {
      clearTimeout(this._wpBuscarTimer);
      this._wpBuscarTimer = setTimeout(() => { this.wpSolo.page = 1; this.cargarSoloWordPress(); }, 400);
    },

    paginaSoloWordPress(n) {
      if (n < 1 || n > this.wpSolo.pages) return;
      this.wpSolo.page = n;
      this.cargarSoloWordPress();
    },

    // ===================================================================
    //                         EXPLORER VIEW
    // ===================================================================
    expTab: 'all',
    expSearch: '',
    expSort: null,
    expSortDir: 'asc',
    expUrls: [],
    expPage: 1,
    expPages: 1,
    expTotal: 0,
    expPageSize: 100,
    expLoading: false,
    expSelectedUrl: null,
    expSelectedIndex: -1,
    expUrlDetail: null,
    expDetailTab: 'resumen',
    expDetailOpen: false,
    expBadgeCounts: {},
    _expContadores: null,       // { job, valores, pidiendo }: cifras de la barra que no salen de /stats
    expColumnsByTab: {},        // { tabKey: [colKey, ...] } — persisted column selection per tab
    expColumnPickerOpen: false,
    expColumnFilters: {},       // { columnKey: { op: '>=', value: '0.5' } | { value: 'foo' } | { op: 'vacio' } }
    expProblema: '',            // issue_type (o varios separados por comas) del filtro «Con el problema…»
    expGravedad: '',            // severity del mismo filtro
    expBuscarColumna: '',       // buscador del selector de columnas
    expAgrupar: false,          // vista agrupada por plantilla (forma de ruta)
    expVistas: [],              // vistas guardadas del cliente del rastreo
    expPlantillas: null,        // respuesta de /urls/plantillas
    expPlantilla: '',           // plantilla elegida: filtra la tabla
    expAgruparPor: 'plantilla', // 'plantilla' (forma de ruta) o 'segmento' (decision 125)
    expSegmento: '',            // segmento elegido: filtra la tabla (?segmento=)
    segmentosJob: null,         // GET /jobs/{id}/segmentos
    expAMedida: [],             // reglas a medida del censo (decision 104): [{key, nombre, clase, etiqueta}]
    expAvisoRegla: '',          // 422 de una regla que este censo no tiene (vista guardada de otro)
    resumenAMedida: null,       // GET /jobs/{id}/extraccion
    veredicto: null,            // GET /jobs/{id}/veredicto, solo en modo lista (decision 128)
    EXP_GRUPOS_COLUMNAS,
    _expSearchTimer: null,
    _expFilterTimer: null,
    _expKeyHandler: null,

    // ---- Extraccion y busqueda a medida (#34, decision 104) ----
    // Las columnas `x.<nombre>` se inyectan en EXP_COLUMN_DEFS al abrir el
    // censo: asi todo lo que ya lee EXP_COLUMN_DEFS[col] (cabecera, filtro,
    // orden, celda, CSV) vale sin tocarlo. Las del censo anterior se quitan.
    _registrarAMedida(job) {
      for (const k of Object.keys(EXP_COLUMN_DEFS)) if (k.startsWith('x.')) delete EXP_COLUMN_DEFS[k];
      const defs = _defsAMedida(job);
      Object.assign(EXP_COLUMN_DEFS, defs);
      this.expAMedida = Object.entries(defs).map(([key, d]) => ({ key, nombre: d.nombre, clase: d.clase, etiqueta: d.label }));
      const grupos = this.EXP_GRUPOS_COLUMNAS || EXP_GRUPOS_COLUMNAS;
      const grupo = grupos.find(g => g[0] === "A medida");
      if (grupo) grupo[1] = Object.keys(defs);
      else grupos.push(["A medida", Object.keys(defs)]);
      const tab = EXP_TABS.find(t => t.key === 'a_medida');
      if (tab) tab.columns = ['url', 'status_code', ...Object.keys(defs)];
    },

    // Modo lista (decision 128): pasa / falla / no_concluyente, arriba en la
    // ficha como las alertas de la comparacion. Solo para listas: en un censo
    // normal el veredicto existe, pero lo que se mira son las alertas.
    async cargarVeredicto() {
      this.veredicto = null;
      if (!this.job || !esModoLista(this.job)) return;
      const id = this.job.id;
      try {
        const v = await api(`/jobs/${id}/veredicto`);
        if (this.job && this.job.id === id) this.veredicto = v;
      } catch (_) { /* sin veredicto: la ficha sale igual */ }
    },

    async cargarResumenAMedida() {
      this.resumenAMedida = null;
      if (!this.job || !this.expAMedida.length) return;
      try { this.resumenAMedida = await api(`/jobs/${this.job.id}/extraccion`); } catch (_) { /* sin resumen */ }
    },

    // Desde la ficha del job o la franja del Explorador: la pestaña a medida
    // con un filtro ya puesto. `op`: 'vacio' (sin coincidencia), 'no' / 'si'
    // (busqueda) o 'estado:<estado>'.
    verAMedida(nombre, op) {
      const key = 'x.' + nombre;
      let f = null;
      if (op === 'vacio') f = { op: 'vacio' };
      else if (op === 'si' || op === 'no') f = { value: op === 'si' ? 'true' : 'false' };
      else if (op && op.startsWith('estado:')) f = { op: 'estado', value: op.slice(7) };
      // El chip SUSTITUYE los filtros, desde la ficha y desde el Explorador:
      // su cifra es la del censo entero, y sumado a otro filtro (AND) la
      // tabla no la daba. Pulsar el chip activo lo quita.
      const activo = f && this.chipAMedidaActivo(nombre, op);
      if (this.view !== 'explorer') this.openExplorer({ tab: 'a_medida', filtros: f ? { [key]: f } : {} });
      else {
        this.expTab = 'a_medida';
        this.expColumnFilters = (f && !activo) ? { [key]: f } : {};
        this.expPage = 1;
        this.loadExplorerUrls();
      }
    },

    chipAMedidaActivo(nombre, op) {
      const filtros = Object.entries(this.expColumnFilters || {}).filter(([, v]) => v);
      if (this.view !== 'explorer' || filtros.length !== 1) return false;
      const [k, f] = filtros[0];
      if (k !== 'x.' + nombre) return false;
      if (op === 'vacio') return f.op === 'vacio';
      if (op === 'si' || op === 'no') return !f.op && f.value === (op === 'si' ? 'true' : 'false');
      if (op && op.startsWith('estado:')) return f.op === 'estado' && f.value === op.slice(7);
      return false;
    },

    // Un 422 por una regla que el censo no tiene: se quitan los filtros y el
    // orden `x.*` en vez de enseñar el censo entero como si nada.
    quitarFiltrosAMedida() {
      const f = { ...this.expColumnFilters };
      for (const k of Object.keys(f)) if (k.startsWith('x.') && !EXP_COLUMN_DEFS[k]) delete f[k];
      this.expColumnFilters = f;
      if (this.expSort && this.expSort.startsWith('x.') && !EXP_COLUMN_DEFS[this.expSort]) this.expSort = null;
      this.expAvisoRegla = '';
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    getExpCellTitle(row, col) {
      const def = EXP_COLUMN_DEFS[col];
      if (def && def.tip) { try { return def.tip(row, this.job); } catch { return ''; } }
      return this.getExpCellValue(row, col);
    },

    // `preajuste`: { tab, problema, gravedad, buscar, filtros, orden, dir, pagina }
    // Lo usan la ruta (#/rastreos/<id>/explorador?...) y «Ver en el Explorador»
    // de Problemas.
    openExplorer(preajuste = {}) {
      this.view = 'explorer';
      this.expTab = preajuste.tab || 'all';
      this.expSearch = preajuste.buscar || '';
      this.expSort = preajuste.orden || null;
      this.expSortDir = preajuste.dir || 'asc';
      this.expPage = preajuste.pagina || 1;
      this.expProblema = preajuste.problema || '';
      this.expGravedad = preajuste.gravedad || '';
      this.expAgrupar = !!preajuste.agrupar;
      this.expAgruparPor = preajuste.agruparPor || 'plantilla';
      this.expPlantilla = preajuste.plantilla || '';
      this.expSegmento = preajuste.segmento || '';
      if (preajuste.wordpress) this.abrirSoloWordPress(preajuste.wordpress === 'todo' ? '' : preajuste.wordpress);
      else this.expWp = false;
      if (!this.segmentosJob) this.cargarSegmentos();
      this.expPlantillas = null;
      this.expDetailOpen = false;
      this.expSelectedUrl = null;
      this.expSelectedIndex = -1;
      this.expUrlDetail = null;
      this.expColumnFilters = preajuste.filtros || {};
      this.expColumnPickerOpen = false;
      this.expColumnsByTab = this._loadExpColumnPrefs();
      if ((this.expProblema || EXP_TABS.find(t => t.key === this.expTab)?.ambito) && !this.issuesResumen) this.loadIssuesResumen();
      this.cargarVistas();
      this._bindExplorerKeyNav();
      this.loadExplorerBadges();
      this.loadExplorerUrls();
      this.$nextTick(() => lucide.createIcons());
    },

    // La ruta de la pestana URLs: la ultima consulta del Explorador de este
    // rastreo si la hay, para volver sin perder filtros ni pagina.
    _rutaUrls() {
      if (!this.job) return '';
      const u = this._expUltimo && this._expUltimo.job === this.job.id ? this._expUltimo.qs : '';
      return '#/rastreos/' + this.job.id + '/explorador' + (u ? '?' + u : '');
    },

    // Pestana activa de la fila del censo. «URLs» es el Explorador y la
    // ficha de una URL; las demas, la ficha con esa pestana (revision de UX
    // del 25-oct, 2.6; V29: antes la del Explorador nunca salia activa).
    pestanaActiva(t) {
      if (t === 'urls') return ['explorer', 'url-detail'].includes(this.view);
      return this.view === 'detail' && this.detailTab === t;
    },

    // El Explorador ocupa el alto que queda bajo la cabecera y las pestanas
    // del censo, que cambian de alto (pestanas en dos filas en movil, cifras
    // que llegan tarde): se mide donde empieza y se recalcula al cambiar el
    // tamano de la ventana o de la cabecera. Con 26rem de minimo: en una
    // pantalla baja la pagina se desplaza en vez de dejar la tabla en nada.
    ajustarAltoExplorador() {
      const fijar = () => {
        const el = document.querySelector('.explorer');
        if (!el) return;
        const top = el.getBoundingClientRect().top + window.scrollY;
        el.style.height = 'max(26rem, calc(100vh - ' + Math.round(top) + 'px))';
      };
      fijar();
      if (!this._altoExpObs) {
        window.addEventListener('resize', fijar);
        this._altoExpObs = window.ResizeObserver ? new ResizeObserver(fijar) : { observe() {}, disconnect() {} };
      }
      // La cabecera y las pestanas son otros nodos tras cada vuelta a la
      // ficha: se vuelven a observar (observar no cambia alturas, no hay bucle).
      this._altoExpObs.disconnect();
      document.querySelectorAll('.ficha-cabecera, .tabs-main').forEach(n => this._altoExpObs.observe(n));
    },

    // Pestana URLs (revision de UX del 25-oct, 2.6). En el Explorador no
    // hace nada; desde otra pestana o desde la ficha de una URL, vuelve a la
    // ultima consulta.
    irAUrls() {
      if (this.view === 'explorer') return;
      const u = this._expUltimo && this._expUltimo.job === this.job.id ? this._expUltimo.qs : '';
      this.openExplorer(u ? this._preajusteExplorador(new URLSearchParams(u)) : {});
    },

    loadExplorerBadges() {
      if (!this.stats) return;
      const b = {};
      b.all = this.stats.total_urls;
      // Resource types
      for (const rt of this.stats.urls_by_resource_type || []) {
        b[rt.resource_type] = rt.count;
      }
      // Internal / external
      b.internal = this.stats.internal_count || 0;
      b.external = this.stats.external_count || 0;
      // «Externas 0» (V25): el censo no guarda URLs externas —no se
      // rastrean—, pero sus enlaces si. Sin ninguna en el censo, la pestaña
      // cuenta los destinos externos enlazados y lleva a Enlaces; con una API
      // que no tiene /links/resumen, sin cifra (nunca un 0 que no es).
      if (!b.external) {
        b.external = this.expExternasEnlazadas;
        if (this.expExternasEnlazadas == null) this.cargarExternasEnlazadas();
      }
      // Status groups
      for (const sg of this.stats.urls_by_status_group || []) {
        b[sg.status_group] = sg.count;
      }
      // Contadores en todas las entradas, con «0» cuando es cero (revision
      // de UX del 25-oct, 3.4). Las cuentas de /stats agrupan el censo
      // entero: un tipo o un estado que no sale ahi es que no hay ninguno.
      for (const k of ['js', 'css', 'image', 'pdf', '2xx', '3xx', '4xx', '5xx']) if (b[k] == null) b[k] = 0;
      b.bloqueadas = b.blocked || 0;
      // Lo que /stats no cuenta con el mismo filtro que la pestaña se pide
      // aparte (cargarContadoresExplorador) y se guarda por censo.
      // Un rastreo que no ha terminado cambia de cifras: se vuelven a contar
      // cada vez que se entra, y otra vez al cambiar de estado o de analisis
      // (lo contado a medias no se queda en la barra cuando acaba).
      const clave = this._claveContadores();
      const e = this._expContadores;
      if (e && (e.job !== this.job.id || e.clave !== clave || (this._censoEnCurso() && !e.pidiendo))) this._expContadores = null;
      const c = this._expContadores ? this._expContadores.valores : {};
      this.expBadgeCounts = { ...b, ...c };
      this.cargarContadoresExplorador();
    },

    // El censo esta analizado y ya no cambia: sin eso, los ambitos SEO no
    // llevan cifra ni punto de color. Un censo cancelado o fallido antes del
    // analisis no tiene problemas calculados, no «0 problemas»: el mismo
    // criterio que la tarjeta «sin analizar todavía» del Resumen (revision
    // de UX del 25-oct, 3.4; lo que no se puede afirmar no se afirma).
    _censoEnCurso() {
      return !!this.job && ['pending', 'running', 'analyzing'].includes(this.job.status);
    },
    explorerAnalizado() {
      return !!this.job && !!this.job.analisis_version && !this._censoEnCurso();
    },
    _claveContadores() {
      return this.job ? this.job.status + '|' + (this.job.analisis_version || '') : '';
    },

    // Las entradas cuya cifra no sale de /stats: Páginas HTML, Indexables,
    // No indexables, la extraccion a medida y cada ambito SEO (paginas de la
    // vista con algun problema de su ambito, no la suma de incidencias: una
    // pagina con dos problemas del ambito cuenta una vez). Es el `total` de
    // /urls con el filtro de la pestaña, una consulta cada vez y en orden,
    // para no cargar la API. Si una falla, esa entrada se queda sin cifra:
    // nunca un 0 que no se ha contado. Un ambito sin ningun tipo en el
    // resumen de problemas es 0 sin preguntar, pero solo si el resumen trae
    // algo (vacio puede ser que fallo). Sin analizar, los ambitos y las
    // indexables sin cifra.
    async cargarContadoresExplorador() {
      const job = this.job;
      if (!job || !this.stats) return;
      const clave = this._claveContadores();
      if (!this._expContadores || this._expContadores.job !== job.id || this._expContadores.clave !== clave) {
        this._expContadores = { job: job.id, clave, valores: {}, pidiendo: false };
      }
      const cache = this._expContadores;
      if (cache.pidiendo) return;
      cache.pidiendo = true;
      // Una cuenta que se pidio antes de acabar el rastreo no pisa la nueva.
      const vigente = () => this.job && this.job.id === job.id && this._expContadores === cache;
      try {
        const analizado = this.explorerAnalizado();
        if (analizado && !this.issuesResumen) await this.loadIssuesResumen();
        const tipos = new Set((this.issuesResumen || []).map(r => r.issue_type));
        for (const tab of EXP_TABS) {
          if (!vigente()) return;
          if (tab.divider || tab.header || cache.valores[tab.key] != null) continue;
          const fuera = ['paginas_html', 'indexable', 'noindex', 'a_medida'];
          if (!tab.ambito && !fuera.includes(tab.key)) continue;
          // La indexabilidad tambien la calcula el analisis: sin el, «0».
          if ((tab.ambito || tab.key === 'indexable' || tab.key === 'noindex') && !analizado) continue;
          if (tab.requiere && !this.expAMedida.length) continue;
          if (tab.ambito && tipos.size && !this.issuesSegmento && !tab.ambito.some(t => tipos.has(t))) {
            cache.valores[tab.key] = 0;
          } else {
            const q = new URLSearchParams({ page: '1', page_size: '1', ligero: 'true' });
            for (const [k, v] of Object.entries(tab.filter || {})) q.set(k, String(v));
            if (tab.ambito) q.set('issue_type', tab.ambito.join(','));
            try {
              const r = await api(`/jobs/${job.id}/urls?${q}`);
              if (!vigente()) return;
              cache.valores[tab.key] = r.total;
            } catch (_) { continue; }
          }
          if (vigente()) this.expBadgeCounts = { ...this.expBadgeCounts, [tab.key]: cache.valores[tab.key] };
        }
      } finally { cache.pidiendo = false; }
    },

    // Desplegable de vistas del Explorador en movil (revision de UX del
    // 25-oct, 3.2): las mismas entradas que la barra lateral, con su cifra.
    textoVistaMovil(tab) {
      const n = this.expBadgeCounts[tab.key];
      return tab.label + (n != null ? ' · ' + fmt.num(n) : '');
    },

    elegirVistaMovil(valor) {
      if (valor === 'wp') return this.abrirSoloWordPress('');
      if (valor.startsWith('vista:')) {
        const v = this.expVistas.find(x => String(x.id) === valor.slice(6));
        if (v) this.abrirVista(v);
        return;
      }
      this.setExplorerTab(valor);
    },

    // «Agrupar ▾» en un solo boton (revision de UX del 25-oct, 3.4): sin
    // agrupar, por plantilla o por segmento.
    agruparCon(por) {
      this.menuAbierto = '';
      if (!por) { if (this.expAgrupar) this.alternarAgrupar(this.expAgruparPor); return; }
      if (this.expAgrupar && this.expAgruparPor === por) return;
      this.alternarAgrupar(por);
    },

    // Cambiar de pestaña ya no borra la busqueda ni los filtros: pasar de
    // «4xx» a «3xx» con el mismo «Inlinks ≥ 1» obligaba a reescribirlo. Los
    // filtros de columnas que la pestaña nueva no muestra siguen aplicandose
    // y se ven en el contador «N filtros», que los quita de golpe.
    async cargarExternasEnlazadas() {
      const jobId = this.job && this.job.id;
      if (!jobId) return;
      try {
        const r = await api(`/jobs/${jobId}/links/resumen`);
        if (!this.job || this.job.id !== jobId) return;
        this.expExternasEnlazadas = r.externos.destinos;
        if (!(this.stats && this.stats.external_count)) this.expBadgeCounts = { ...this.expBadgeCounts, external: r.externos.destinos };
      } catch (_) { /* API anterior: la pestaña sale sin cifra */ }
    },

    // Sin URLs externas en el censo, «Externas» son los enlaces a otros
    // sitios: se ven en Enlaces, por destino (V25).
    // Solo si la API tiene /links/resumen (expExternasEnlazadas no es null):
    // con la API anterior, Enlaces no filtra por tipo y llevar alli con
    // tipo=externo enseñaria todos los enlaces bajo un filtro que no se
    // aplica. Entonces, la pestaña de URLs externas de siempre.
    externasEnEnlaces() {
      return !(this.stats && this.stats.external_count) && this.expExternasEnlazadas != null;
    },

    setExplorerTab(tab) {
      if (tab === 'external' && this.externasEnEnlaces()) {
        this.irAEnlaces({ tipo: 'externo' });
        return;
      }
      const antes = EXP_TABS.find(t => t.key === this.expTab);
      this.expWp = false;
      this.expTab = tab;
      // Entre vistas de ambito, el problema elegido es de la anterior: fuera.
      if (antes && antes.ambito && this.expProblema && this.expProblema.split(',').every(t => antes.ambito.includes(t))) {
        this.expProblema = '';
      }
      // Un ambito abre las paginas con algun problema suyo: lo mismo que
      // cuenta su cifra en la barra («Títulos 307» abre 307, no las 3.772
      // páginas HTML). «Todas las páginas» sigue a un clic en los chips
      // (revision de UX del 25-oct, 3.4; decision 199). Sin analizar no hay
      // problemas que filtrar: todas.
      const nueva = EXP_TABS.find(t => t.key === tab);
      if (nueva && nueva.ambito && !this.expProblema && !this.expGravedad && this.explorerAnalizado()) {
        this.expProblema = nueva.ambito.join(',');
      }
      if (nueva && nueva.ambito && !this.issuesResumen && this.explorerAnalizado()) this.loadIssuesResumen();
      this.expPage = 1;
      this.expDetailOpen = false;
      this.expSelectedUrl = null;
      this.expSelectedIndex = -1;
      this.expColumnPickerOpen = false;
      this.loadExplorerUrls();
    },

    // ---- Vistas guardadas por cliente (#131) ----
    // Una vista es la consulta de la URL (#/rastreos/<id>/explorador?...),
    // guardada en el cliente: vale para cualquier censo suyo, y asi se repite
    // el mismo analisis cada mes.
    async cargarVistas() {
      this.expVistas = [];
      if (!this.job || !this.job.cliente_id) return;
      try { this.expVistas = await api(`/clients/${this.job.cliente_id}/vistas`); } catch (_) { /* sin vistas */ }
    },

    async guardarVista() {
      if (!this.job || !this.job.cliente_id) return;
      const nombre = await this.preguntar({
        titulo: 'Guardar esta vista',
        mensaje: `Se guarda en el cliente «${this.job.cliente_nombre || ''}» y se podrá abrir en cualquier censo suyo: pestaña, problema, filtros, orden y agrupación.`,
        aceptar: 'Guardar', pedir: 'Nombre de la vista',
        valor: (EXP_TABS.find(t => t.key === this.expTab) || {}).label || '',
      });
      if (!nombre) return;
      try {
        await api(`/clients/${this.job.cliente_id}/vistas`, {
          method: 'POST', body: JSON.stringify({ nombre, consulta: this._estadoExplorador() }),
        });
        await this.cargarVistas();
        this.showToast('Vista guardada');
      } catch (e) { this.avisar('No se pudo guardar', e.message); }
    },

    abrirVista(v) {
      this.openExplorer(this._preajusteExplorador(new URLSearchParams(v.consulta)));
    },

    async borrarVista(v) {
      if (!await this.preguntar({ titulo: `Borrar la vista «${v.nombre}»`, mensaje: 'Se borra para todos los censos del cliente.',
                                 aceptar: 'Borrar', peligro: true })) return;
      try {
        await api(`/clients/${this.job.cliente_id}/vistas/${v.id}`, { method: 'DELETE' });
        await this.cargarVistas();
      } catch (e) { this.avisar('No se pudo borrar', e.message); }
    },

    // ---- Agrupar por plantilla (#131) ----
    // En SEO tecnico se arregla una plantilla, no una URL: los 32 errores 4xx
    // de Lopesan son, en buena parte, dos fallos repetidos por idioma.
    async cargarPlantillas() {
      this.expLoading = true;
      try {
        const q = new URLSearchParams(this._buildExplorerParams());
        q.delete('page'); q.delete('page_size'); q.delete('ligero'); q.delete('plantilla');
        // Siempre con `agrupar`: el uso (api/uso.py) cuenta las dos agrupaciones,
        // y sin el valor por defecto en la URL no se podrian comparar.
        q.set('agrupar', this.expAgruparPor === 'segmento' ? 'segmento' : 'plantilla');
        if (this.expAgruparPor === 'segmento') q.delete('segmento');
        this.expPlantillas = await api(`/jobs/${this.job.id}/urls/plantillas?${q}`);
        this.expTotal = this.expPlantillas.urls;
      } catch (e) { this.error = e.message; }
      this.expLoading = false;
    },

    alternarAgrupar(por = 'plantilla') {
      // El mismo boton apaga; el otro cambia de agrupacion sin apagar.
      this.expAgrupar = !(this.expAgrupar && this.expAgruparPor === por);
      this.expAgruparPor = por;
      this.expPlantillas = null;
      this.expDetailOpen = false;
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    entrarEnPlantilla(forma) {
      if (this.expAgruparPor === 'segmento') {
        this.expSegmento = forma === '(sin segmentar)' ? '' : forma;
      } else this.expPlantilla = forma;
      this.expAgrupar = false;
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    // ---- Segmentos de negocio (decision 125) ----
    // `urls.segmento` lo materializa el analisis con `config.segmentos`; sin
    // reglas, cada URL lleva la forma de su ruta (empieza por «/»).
    async cargarSegmentos() {
      if (!this.job) return;
      try { this.segmentosJob = await api(`/jobs/${this.job.id}/segmentos`); }
      catch (_) { this.segmentosJob = { segmentos: [], reglas: [] }; }
    },

    // Los de regla primero (en su orden) y luego las formas de ruta con mas URLs.
    segmentosParaElegir() {
      const lista = (this.segmentosJob && this.segmentosJob.segmentos) || [];
      return { regla: lista.filter(x => x.de_regla), forma: lista.filter(x => !x.de_regla).slice(0, 60) };
    },

    elegirSegmento(valor) {
      this.expSegmento = valor;
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    async elegirSegmentoProblemas(valor) {
      this.issuesSegmento = valor;
      this.issuesResumen = null;
      if (this.issuesVista === 'lista' || this.issueFilters.issue_type) this.applyIssueFilters();
      await this.loadIssuesResumen();
      this.$nextTick(() => lucide.createIcons());
    },

    quitarPlantilla() {
      this.expPlantilla = '';
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    // Un tramo repetido (`null`) como filtro de URL.
    filtrarPorTramo(tramo) {
      this.expColumnFilters = { ...this.expColumnFilters, url: { value: '/' + tramo } };
      this.expAgrupar = false;
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    // Los tipos de incidencia del ambito de la pestaña, con sus paginas.
    tiposDelAmbito() {
      const tab = EXP_TABS.find(t => t.key === this.expTab);
      if (!tab || !tab.ambito) return [];
      const por = Object.fromEntries((this.issuesResumen || []).map(r => [r.issue_type, r]));
      return tab.ambito.filter(t => por[t]).map(t => por[t]);
    },

    // Gravedad mas alta del ambito: el punto de color de la barra lateral.
    gravedadDelAmbito(tab) {
      if (!tab.ambito || !this.issuesResumen || !this.explorerAnalizado()) return '';
      const sev = this.issuesResumen.filter(r => tab.ambito.includes(r.issue_type)).map(r => r.severity);
      return sev.includes('error') ? 'error' : sev.includes('warning') ? 'warning' : sev.includes('info') ? 'info' : 'ok';
    },

    elegirTipoDelAmbito(tipo) {
      const tab = EXP_TABS.find(t => t.key === this.expTab);
      // '' = todas las paginas; '*' = cualquier problema del ambito
      this.expProblema = tipo === '*' ? tab.ambito.join(',') : tipo;
      this.expGravedad = '';
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    // «Con el problema…»: '' | tipo | 'sev:error'
    setExpProblema(valor) {
      if (valor.startsWith('sev:')) { this.expGravedad = valor.slice(4); this.expProblema = ''; }
      else { this.expProblema = valor; this.expGravedad = ''; }
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    expValorProblema() {
      return this.expGravedad ? 'sev:' + this.expGravedad : this.expProblema;
    },

    // Desde un tipo de Problemas: esas URLs, con las columnas que lo explican.
    verProblemaEnExplorador(tipo) {
      this.openExplorer({ problema: tipo, segmento: this.issuesSegmento || '' });
    },

    // El CSV de LO QUE SE VE: mismos filtros, mismo orden, columnas visibles
    // (antes exportaba el censo entero con 83 columnas).
    exportarVista() {
      if (!this.job) return;
      const q = new URLSearchParams(this._buildExplorerParams(false));
      q.delete('page'); q.delete('page_size'); q.delete('ligero');
      q.set('columnas', this.getExpColumns().join(','));
      window.open(`${API}/jobs/${this.job.id}/urls/export?${q}`, '_blank');
    },

    // Todos los enlaces que apuntan a las URLs de esta vista (origen, ancla,
    // posicion, follow): la lista para corregir enlaces a 404 o redirecciones.
    exportarEnlacesEntrantes() {
      if (!this.job) return;
      const q = new URLSearchParams(this._buildExplorerParams(false));
      ['page', 'page_size', 'ligero', 'origenes', 'sort_by', 'sort_dir'].forEach(k => q.delete(k));
      window.open(`${API}/jobs/${this.job.id}/urls/enlaces-entrantes?${q}`, '_blank');
    },

    // Columnas del selector, por grupos y filtradas por el buscador.
    expGruposVisibles() {
      const t = this.expBuscarColumna.trim().toLowerCase();
      return EXP_GRUPOS_COLUMNAS
        .map(([nombre, claves]) => [nombre, claves.filter(k => !t || (EXP_COLUMN_DEFS[k]?.label || k).toLowerCase().includes(t))])
        .filter(([, claves]) => claves.length);
    },

    explorerSort(col) {
      if (this.expSort === col) {
        this.expSortDir = this.expSortDir === 'asc' ? 'desc' : 'asc';
      } else {
        this.expSort = col;
        this.expSortDir = 'asc';
      }
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    explorerSearchInput() {
      clearTimeout(this._expSearchTimer);
      this._expSearchTimer = setTimeout(() => {
        this.expPage = 1;
        this.loadExplorerUrls();
      }, 400);
    },

    /**
     * Build the query string parameters for the /urls endpoint based on tab,
     * sort, search and the inline per-column filters.
     */
    _buildExplorerParams(ligero = true) {
      const tabCfg = EXP_TABS.find(t => t.key === this.expTab) || EXP_TABS[0];
      const params = new URLSearchParams();
      params.set('page', String(this.expPage));
      params.set('page_size', String(this.expPageSize));
      // Sin el texto de cada pagina: era el 89% de 1,6 MB por pagina de la
      // tabla y no lo pinta nadie (el panel lo pide aparte).
      if (ligero) params.set('ligero', 'true');
      // Para medir el uso (api/uso.py): que pestaña se mira. Solo nombres.
      params.set('vista', 'explorador');
      params.set('pestana', this.expTab);
      if (this.expProblema) params.set('issue_type', this.expProblema);
      if (this.expPlantilla) params.set('plantilla', this.expPlantilla);
      if (this.expSegmento) params.set('segmento', this.expSegmento);
      if (this.getExpColumns().some(c => EXP_COLUMN_DEFS[c]?.calculada === 'origenes')) params.set('origenes', 'true');
      if (this.getExpColumns().some(c => EXP_COLUMN_DEFS[c]?.calculada === 'h1')) params.set('h1', 'true');
      if (this.getExpColumns().includes('cambio')) params.set('cambios', 'true');
      const xs = this.getExpColumns().filter(c => c.startsWith('x.') && EXP_COLUMN_DEFS[c]);
      if (xs.length) params.set('a_medida', xs.map(c => c.slice(2)).join(','));
      if (this.expGravedad) params.set('severity', this.expGravedad);
      const vacio = [], conValor = [];
      if (tabCfg.filter) {
        for (const [k, v] of Object.entries(tabCfg.filter)) params.set(k, String(v));
      }
      if (this.expSearch) params.set('search', this.expSearch);
      if (this.expSort) { params.set('sort_by', this.expSort); params.set('sort_dir', this.expSortDir); }

      // Inline column filters
      for (const [colKey, f] of Object.entries(this.expColumnFilters)) {
        if (!f) continue;
        const def = EXP_COLUMN_DEFS[colKey];
        if (!def && colKey.startsWith('x.')) {
          // Una regla que este censo no tiene (vista guardada de otro censo):
          // se manda igual para que la API dé el 422 y salga el aviso con
          // «Quitar el filtro». Descartarla aquí enseñaba el censo ENTERO
          // como si el filtro se hubiera aplicado (decision 104).
          const raw = (f.value ?? '').toString().trim();
          if (f.op === 'vacio') vacio.push(colKey);
          else if (f.op === 'con_valor') conValor.push(colKey);
          else if (f.op === 'estado') params.set(`${colKey}_estado`, raw);
          else if (['>=', '>', '='].includes(f.op)) params.set(`${colKey}_gte`, raw);
          else if (['<=', '<'].includes(f.op)) params.set(`${colKey}_lte`, raw);
          else params.set(colKey, raw);
          continue;
        }
        if (!def || !def.filterKey) continue;
        if (def.aMedida && f.op === 'estado') { if (f.value) params.set(`x.${def.nombre}_estado`, f.value); continue; }
        if (def.vacio && f.op === 'vacio') { vacio.push(def.vacio); continue; }
        if (def.vacio && f.op === 'con_valor') { conValor.push(def.vacio); continue; }
        const raw = (f.value ?? '').toString().trim();
        if (raw === '') continue;
        if (def.type === 'numeric') {
          if (def.exact && (f.op === '=' || !f.op)) {
            // status_code exact match — overrides any tab filter on status_code
            params.set(def.filterKey, raw);
          } else {
            const op = f.op || '>=';
            if (op === '=')        { params.set(`${def.filterKey}_gte`, raw); params.set(`${def.filterKey}_lte`, raw); }
            else if (op === '>=' ) { params.set(`${def.filterKey}_gte`, raw); }
            else if (op === '>')   { const n = parseFloat(raw); if (!isNaN(n)) params.set(`${def.filterKey}_gte`, String(n + 0.00001)); }
            else if (op === '<=')  { params.set(`${def.filterKey}_lte`, raw); }
            else if (op === '<')   { const n = parseFloat(raw); if (!isNaN(n)) params.set(`${def.filterKey}_lte`, String(n - 0.00001)); }
          }
        } else if (def.type === 'boolean') {
          params.set(def.filterKey, raw);
        } else {
          params.set(def.filterKey, raw);
        }
      }
      if (vacio.length) params.set('vacio', vacio.join(','));
      if (conValor.length) params.set('con_valor', conValor.join(','));
      return params.toString();
    },

    async loadExplorerUrls() {
      if (!this.job) return;
      if (this.expAgrupar) return this.cargarPlantillas();
      this.expLoading = true;
      try {
        const params = this._buildExplorerParams();
        this.expAvisoRegla = '';
        const data = await api(`/jobs/${this.job.id}/urls?${params}`);
        this.expUrls = data.items;
        this.expPages = data.pages;
        this.expTotal = data.total;
        // Keep current selection in sync with the new page
        if (this.expSelectedUrl) {
          const idx = this.expUrls.findIndex(u => u.id === this.expSelectedUrl.id);
          this.expSelectedIndex = idx;
          if (idx === -1) {
            this.expDetailOpen = false;
            this.expSelectedUrl = null;
            this.expUrlDetail = null;
          }
        } else {
          this.expSelectedIndex = -1;
        }
      } catch (e) {
        if (/no tiene la regla/.test(e.message || '')) { this.expAvisoRegla = e.message; this.expUrls = []; this.expTotal = 0; }
        else this.error = e.message;
      }
      this.expLoading = false;
    },

    async selectExplorerUrl(u, idx = null) {
      this.expSelectedUrl = u;
      this.expSelectedIndex = idx != null ? idx : this.expUrls.findIndex(x => x.id === u.id);
      this.expDetailOpen = true;
      this.expUrlDetail = null;
      try {
        this.expUrlDetail = await api(`/jobs/${this.job.id}/urls/${u.id}`);
      } catch (e) { this.error = e.message; }
      this.$nextTick(() => lucide.createIcons());
    },

    closeExplorerDetail() {
      this.expDetailOpen = false;
      this.expSelectedUrl = null;
      this.expSelectedIndex = -1;
      this.expUrlDetail = null;
    },

    setExpPage(p) {
      if (p < 1 || p > this.expPages) return;
      this.expPage = p;
      this.loadExplorerUrls();
    },

    /* ---------- column picker ---------- */
    getExpColumns() {
      const stored = this.expColumnsByTab[this.expTab];
      if (stored && stored.length) return stored;
      const tabCfg = EXP_TABS.find(t => t.key === this.expTab);
      return columnasPorDefecto((tabCfg && tabCfg.columns) || EXP_DEFAULT_COLUMNS, this.job);
    },

    getExpAllColumnKeys() {
      return Object.keys(EXP_COLUMN_DEFS);
    },

    isExpColumnActive(key) {
      return this.getExpColumns().includes(key);
    },

    toggleExpColumn(key) {
      const current = this.getExpColumns().slice();
      const idx = current.indexOf(key);
      if (idx >= 0) {
        if (current.length <= 1) return; // never leave the table without columns
        current.splice(idx, 1);
      } else {
        current.push(key);
      }
      this.expColumnsByTab = { ...this.expColumnsByTab, [this.expTab]: current };
      this._saveExpColumnPrefs();
    },

    resetExpColumns() {
      const next = { ...this.expColumnsByTab };
      delete next[this.expTab];
      this.expColumnsByTab = next;
      this._saveExpColumnPrefs();
    },

    _expColumnPrefsKey() {
      return `expCols:${this.job?.id || 'global'}`;
    },

    _loadExpColumnPrefs() {
      try {
        const raw = localStorage.getItem(this._expColumnPrefsKey());
        return raw ? JSON.parse(raw) : {};
      } catch { return {}; }
    },

    _saveExpColumnPrefs() {
      try { localStorage.setItem(this._expColumnPrefsKey(), JSON.stringify(this.expColumnsByTab)); }
      catch (_) { /* localStorage full / disabled */ }
    },

    /* ---------- inline column filters ---------- */
    expColumnFilterInput(colKey, patch) {
      const cur = this.expColumnFilters[colKey] || {};
      const next = { ...cur, ...patch };
      this.expColumnFilters = { ...this.expColumnFilters, [colKey]: next };
      clearTimeout(this._expFilterTimer);
      this._expFilterTimer = setTimeout(() => {
        this.expPage = 1;
        this.loadExplorerUrls();
      }, 400);
    },

    expClearColumnFilter(colKey) {
      const next = { ...this.expColumnFilters };
      delete next[colKey];
      this.expColumnFilters = next;
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    expClearAllColumnFilters() {
      this.expColumnFilters = {};
      this.expProblema = ''; this.expGravedad = ''; this.expPlantilla = '';
      this.expPage = 1;
      this.loadExplorerUrls();
    },

    expActiveFilterCount() {
      return Object.values(this.expColumnFilters).filter(f =>
        f && (f.op === 'vacio' || f.op === 'con_valor' || (f.value != null && f.value.toString().trim() !== ''))
      ).length + (this.expProblema || this.expGravedad ? 1 : 0) + (this.expPlantilla ? 1 : 0);
    },

    /**
     * Default operator shown when a numeric column has no filter yet.
     * status_code is "exact" so it defaults to '='.
     */
    expDefaultOp(col) {
      const def = EXP_COLUMN_DEFS[col];
      if (def?.type === 'string') return 'contiene';
      return def?.exact ? '=' : '>=';
    },

    expCurrentOp(col) {
      return this.expColumnFilters[col]?.op || this.expDefaultOp(col);
    },

    /** Dynamic placeholder so the user knows what the input expects right now. */
    expFilterPlaceholder(col) {
      const def = EXP_COLUMN_DEFS[col];
      if (!def) return '';
      if (def.type === 'numeric') {
        const op = this.expCurrentOp(col);
        return ({
          '>=': 'al menos…',
          '>':  'mayor que…',
          '=':  def.exact ? 'igual a… (301,302)' : 'igual a…',
          '<=': 'máximo…',
          '<':  'menor que…',
        })[op] || 'núm';
      }
      if (def.type === 'string') {
        const op = this.expCurrentOp(col);
        return op === 'vacio' ? '(vacío)' : op === 'con_valor' ? '(con valor)' : 'contiene… (a|b, !a)';
      }
      return '';
    },

    /** Tooltip for the operator selector explaining each option. */
    expOpTooltip(col) {
      const op = this.expCurrentOp(col);
      const colLabel = EXP_COLUMN_DEFS[col]?.label || col;
      const human = ({
        '>=': 'al menos',
        '>':  'mayor que',
        '=':  'igual a',
        '<=': 'como máximo',
        '<':  'menor que',
      })[op] || op;
      return `${colLabel} ${human}…  (clic para cambiar operador)`;
    },

    /* ---------- keyboard navigation ---------- */
    _bindExplorerKeyNav() {
      if (this._expKeyHandler) return;
      this._expKeyHandler = (e) => {
        if (this.view !== 'explorer') return;
        // Con «Solo en WordPress» abierto la tabla de URLs esta oculta: las
        // flechas desplazan esa lista y no abren a ciegas la ficha de una fila
        // que no se ve (aparecia abierta al volver a la tabla).
        if (this.expWp) return;
        // Don't hijack typing inside inputs/textareas/contenteditable
        const t = e.target;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
        if (!this.expUrls.length) return;
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          const idx = Math.min(this.expSelectedIndex + 1, this.expUrls.length - 1);
          if (idx !== this.expSelectedIndex && idx >= 0) {
            this.selectExplorerUrl(this.expUrls[idx], idx);
            this._scrollSelectedRowIntoView();
          }
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          const idx = Math.max((this.expSelectedIndex < 0 ? 0 : this.expSelectedIndex) - 1, 0);
          if (idx !== this.expSelectedIndex) {
            this.selectExplorerUrl(this.expUrls[idx], idx);
            this._scrollSelectedRowIntoView();
          }
        } else if (e.key === 'Escape' && this.expDetailOpen) {
          e.preventDefault();
          this.closeExplorerDetail();
        }
      };
      window.addEventListener('keydown', this._expKeyHandler);
    },

    _unbindExplorerKeyNav() {
      if (this._expKeyHandler) {
        window.removeEventListener('keydown', this._expKeyHandler);
        this._expKeyHandler = null;
      }
    },

    _scrollSelectedRowIntoView() {
      this.$nextTick(() => {
        const row = document.querySelector('.exp-table tr.exp-row-selected');
        if (row && row.scrollIntoView) row.scrollIntoView({ block: 'nearest' });
      });
    },

    getExpCellValue(row, col) {
      const def = EXP_COLUMN_DEFS[col];
      if (!def) return '';
      try { return def.fmt(row); } catch { return ''; }
    },

    expStatusClass(code) {
      if (!code) return '';
      if (code < 300) return 'exp-status-2xx';
      if (code < 400) return 'exp-status-3xx';
      if (code < 500) return 'exp-status-4xx';
      return 'exp-status-5xx';
    },

    openUrlFromExplorer(urlId) {
      this.openUrlDetail(urlId);
    },
  };
}


/* ===== Explorer Constants =====
 *
 * EXP_COLUMN_DEFS describes every column the explorer table can render.
 *
 *   type:        'string' | 'numeric' | 'boolean'
 *   filterKey:   query-param prefix used for inline filters
 *                  - numeric → emits `${filterKey}_gte` / `${filterKey}_lte`
 *                  - string  → emits `${filterKey}` directly (contains)
 *                  - boolean → emits `${filterKey}=true|false`
 *                Omit to make the column non-filterable.
 *   width:       suggested min width in px for the column.
 */
const EXP_COLUMN_DEFS = {
  // Ruta CON la query: sin ella, `?page=2` o `?variant=` salian como la URL
  // limpia y el buscador parecia no filtrar (salian 436 «iguales» a las demas).
  url:                  { label: 'URL',              type: 'string',  sortable: true,  filterKey: 'url_contains',          width: 320, fmt: r => rutaCorta(r.url) },
  status_code:          { label: 'Estado',           type: 'numeric', sortable: true,  filterKey: 'status_code', exact: true, width: 130, fmt: r => r.status_code ?? '' },
  status_text:          { label: 'Texto estado',     type: 'string',  sortable: false, filterKey: 'status_text_contains',    width: 150, fmt: r => r.status_text ?? '' },
  content_type:         { label: 'Tipo',             type: 'string',  sortable: false, filterKey: 'content_type_contains',   width: 160, fmt: r => r.content_type ? r.content_type.split(';')[0] : '' },
  content_length:       { label: 'Tamaño',           type: 'numeric', sortable: true,  filterKey: 'content_length',          width: 140, fmt: r => r.content_length != null ? fmt.bytes(r.content_length) : '' },
  transfer_size:        { label: 'Transferido',      type: 'numeric', sortable: true,  filterKey: 'transfer_size',           width: 140, fmt: r => r.transfer_size != null ? fmt.bytes(r.transfer_size) : '' },
  response_time_ms:     { label: 'Tiempo (ms)',      type: 'numeric', sortable: true,  filterKey: 'response_time_ms',        width: 140, fmt: r => r.response_time_ms != null ? Math.round(r.response_time_ms) + 'ms' : '' },
  // Tiempo del servidor hasta el primer byte y compresion servida (decision 109).
  ttfb_ms:              { label: 'TTFB (ms)',        type: 'numeric', sortable: true,  filterKey: 'ttfb_ms',                 width: 130, fmt: r => r.ttfb_ms != null ? Math.round(r.ttfb_ms) + 'ms' : '' },
  content_encoding:     { label: 'Compresión',       type: 'string',  sortable: false, filterKey: 'content_encoding_contains', width: 130, fmt: r => r.content_encoding ?? '' },
  // Search Console en los 90 dias del rastreo (decision 142)
  gsc_clics:            { label: 'Clics Google',     type: 'numeric', sortable: true,  filterKey: 'gsc_clics',               width: 140, fmt: r => r.gsc_clics != null ? fmt.num(r.gsc_clics) : '' },
  gsc_impresiones:      { label: 'Impresiones Google', type: 'numeric', sortable: true, filterKey: 'gsc_impresiones',       width: 170, fmt: r => r.gsc_impresiones != null ? fmt.num(r.gsc_impresiones) : '' },
  gsc_posicion:         { label: 'Posición Google',  type: 'numeric', sortable: true,  filterKey: 'gsc_posicion',            width: 150, fmt: r => r.gsc_posicion != null ? fmt.num(r.gsc_posicion) : '' },
  click_depth:          { label: 'Clics desde home', type: 'numeric', sortable: true,  filterKey: 'click_depth',             width: 160, fmt: r => r.click_depth ?? '' },
  crawl_depth:          { label: 'Prof. rastreo',    type: 'numeric', sortable: true,  filterKey: 'crawl_depth',             width: 140, fmt: r => r.crawl_depth ?? '' },
  folder_depth:         { label: 'Niveles',          type: 'numeric', sortable: true,  filterKey: 'folder_depth',            width: 130, fmt: r => r.folder_depth ?? '' },
  word_count:           { label: 'Palabras',         type: 'numeric', sortable: true,  filterKey: 'word_count',              width: 140, fmt: r => r.word_count != null ? fmt.num(r.word_count) : '' },
  content_word_count:   { label: 'Palabras contenido', type: 'numeric', sortable: true, filterKey: 'content_word_count',   width: 170, fmt: r => r.content_word_count != null ? fmt.num(r.content_word_count) : '' },
  text_ratio:           { label: '% texto', grupo: 'otros', type: 'numeric', sortable: true,  filterKey: 'text_ratio',              width: 130, fmt: r => r.text_ratio != null ? fmt.pct(r.text_ratio) : '' },
  url_length:           { label: 'Long. URL',        type: 'numeric', sortable: true,  filterKey: 'url_length',              width: 140, fmt: r => r.url_length ?? '' },
  inlinks_count:        { label: 'Inlinks',          type: 'numeric', sortable: true,  filterKey: 'inlinks_count',           width: 130, fmt: r => r.inlinks_count != null ? fmt.num(r.inlinks_count) : '' },
  unique_inlinks_count: { label: 'Inlinks únicos',   type: 'numeric', sortable: true,  filterKey: 'unique_inlinks_count',    width: 140, fmt: r => r.unique_inlinks_count != null ? fmt.num(r.unique_inlinks_count) : '' },
  outlinks_count:       { label: 'Outlinks',         type: 'numeric', sortable: true,  filterKey: 'outlinks_count',          width: 130, fmt: r => r.outlinks_count != null ? fmt.num(r.outlinks_count) : '' },
  external_outlinks_count: { label: 'Outlinks ext.', type: 'numeric', sortable: true,  filterKey: 'external_outlinks_count', width: 140, fmt: r => r.external_outlinks_count != null ? fmt.num(r.external_outlinks_count) : '' },
  // La que hay que leer y ordenar es `pagerank_score` (0-100 logaritmica,
  // decision 34): con la escala 0-10 lineal el 85% de las paginas de un censo
  // queda en 0,00xx y no se distingue la 250 de la 25.000. La 0-10 se queda por
  // compatibilidad con informes ya entregados.
  pagerank_score:       { label: 'PageRank (0-100)',  type: 'numeric', sortable: true,  filterKey: 'pagerank_score',          width: 160, fmt: r => r.pagerank_score != null ? String(r.pagerank_score) : '' },
  // Con los backlinks del cliente (decision 212): vacias sin CSV subido.
  pagerank_externo_score: { label: 'PageRank desde fuera', type: 'numeric', sortable: true, filterKey: 'pagerank_externo_score', width: 170, fmt: r => r.pagerank_externo_score != null ? String(r.pagerank_externo_score) : '' },
  googlebot_visitas:    { label: 'Visitas Googlebot', type: 'numeric', sortable: true,  filterKey: 'googlebot_visitas',       width: 150, fmt: r => r.googlebot_visitas != null ? fmt.num(r.googlebot_visitas) : '' },
  backlinks_externos:   { label: 'Backlinks',         type: 'numeric', sortable: true,  filterKey: 'backlinks_externos',      width: 110, fmt: r => r.backlinks_externos != null ? fmt.num(r.backlinks_externos) : '' },
  pagerank_raw:         { label: 'PageRank (x media)', grupo: 'otros', type: 'numeric', sortable: true, filterKey: 'pagerank_raw',            width: 170, fmt: r => r.pagerank_raw != null ? fmt.dec(r.pagerank_raw * 1e4, 2) : '' },
  pagerank:             { label: 'PageRank (0-10, antiguo)', grupo: 'otros', type: 'numeric', sortable: true,  filterKey: 'pagerank',                width: 140, fmt: r => r.pagerank != null ? fmt.dec(r.pagerank, 4) : '' },
  near_duplicate_count: { label: 'Casi duplicadas', type: 'numeric', sortable: true,  filterKey: 'near_duplicate_count',    width: 150, fmt: r => r.near_duplicate_count ?? '' },
  closest_similarity:   { label: 'Similitud máx.', type: 'numeric', sortable: true,  filterKey: 'closest_similarity',      width: 150, fmt: r => r.closest_similarity != null ? fmt.pctDe(r.closest_similarity) : '' },
  redirect_url:         { label: 'Redirige a',      type: 'string',  sortable: false, filterKey: 'redirect_url_contains', vacio: 'redirect_url',   width: 260, fmt: r => r.redirect_url ?? '' },
  redirect_type:        { label: 'Cód. redir.',     type: 'numeric', sortable: false, filterKey: 'redirect_type',            width: 130, fmt: r => r.redirect_type ?? '' },
  indexable:            { label: 'Indexable',        type: 'boolean', sortable: false, filterKey: 'indexable',               width: 130, fmt: r => r.indexable === true ? 'Sí' : r.indexable === false ? 'No' : '' },
  indexability_status:  { label: 'Razón noindex',   type: 'string',  sortable: false, filterKey: 'indexability_status_contains', width: 200, fmt: r => r.indexability_status ?? '' },
  is_internal:          { label: 'Interna',          type: 'boolean', sortable: false, filterKey: 'is_internal',             width: 130, fmt: r => r.is_internal === true ? 'Sí' : r.is_internal === false ? 'No' : '' },
  segmento:             { label: 'Segmento',         type: 'string',  sortable: true,  width: 200, fmt: r => r.segmento ?? '',
                          tip: r => r.segmento == null ? 'Sin segmentar: el censo se analizó antes de los segmentos (decisión 125)'
                            : r.segmento.startsWith('/') ? 'Ninguna regla casa: es la forma de la ruta' : 'Segmento de negocio: ' + r.segmento },
  host:                 { label: 'Host',             type: 'string',  sortable: true,  filterKey: 'host_contains',           width: 200, fmt: r => r.host ?? '' },
  // html_meta fields
  title:                { label: 'Título',          type: 'string',  sortable: true,  filterKey: 'title_contains', vacio: 'title',          width: 260, fmt: r => r.html_meta?.title ?? '' },
  title_len:            { label: 'Long. título',    type: 'numeric', sortable: true,  filterKey: 'title_len',               width: 140, fmt: r => r.html_meta?.title_len ?? '' },
  // Google corta por pixeles (~580 el titulo, ~985 la descripcion), no por
  // caracteres: decision 54. El dato llegaba en cada fila y no era columna.
  title_pixel_width:    { label: 'Título (px)',     type: 'numeric', sortable: true,  filterKey: 'title_pixel_width',       width: 130, fmt: r => r.html_meta?.title_pixel_width ?? '' },
  meta_description:     { label: 'Descripción',     type: 'string',  sortable: false, filterKey: 'description_contains', vacio: 'meta_description',    width: 300, fmt: r => r.html_meta?.meta_description ?? '' },
  meta_description_len: { label: 'Long. desc.',     type: 'numeric', sortable: true,  filterKey: 'meta_description_len',    width: 140, fmt: r => r.html_meta?.meta_description_len ?? '' },
  meta_description_pixel_width: { label: 'Descripción (px)', type: 'numeric', sortable: true, filterKey: 'meta_description_pixel_width', width: 150, fmt: r => r.html_meta?.meta_description_pixel_width ?? '' },
  canonical_href:       { label: 'Canonical',       type: 'string',  sortable: false, filterKey: 'canonical_contains', vacio: 'canonical_href',      width: 260, fmt: r => r.html_meta?.canonical_href ?? '' },
  meta_robots:          { label: 'Meta robots',     type: 'string',  sortable: false, filterKey: 'meta_robots_contains', vacio: 'meta_robots',    width: 180, fmt: r => r.html_meta?.meta_robots ?? '' },
  x_robots_tag:         { label: 'X-Robots-Tag',    type: 'string',  sortable: false, filterKey: 'x_robots_tag_contains', vacio: 'x_robots_tag',   width: 180, fmt: r => (r.html_meta?.x_robots_tag ?? '').replace(/\n/g, ' | ') },
  canonical_header:     { label: 'Canonical (cabecera)', type: 'string', sortable: false, filterKey: 'canonical_header_contains', width: 240, fmt: r => r.html_meta?.canonical_header ?? '' },
  rel_next:             { label: 'rel=next',        type: 'string',  sortable: false, width: 240, fmt: r => r.html_meta?.rel_next ?? '' },
  rel_prev:             { label: 'rel=prev',        type: 'string',  sortable: false, width: 240, fmt: r => r.html_meta?.rel_prev ?? '' },
  meta_refresh:         { label: 'Meta refresh',    type: 'string',  sortable: false, filterKey: 'meta_refresh_contains',   width: 200, fmt: r => r.html_meta?.meta_refresh ?? '' },
  // Segun el robots.txt guardado del host (decision 113); vacio = no evaluado.
  bloqueada_googlebot:  { label: 'Bloqueada Googlebot', type: 'boolean', sortable: false, filterKey: 'bloqueada_googlebot', width: 170, fmt: r => r.bloqueada_googlebot === true ? 'Sí' : r.bloqueada_googlebot === false ? 'No' : '' },
  // Decision 108: lo que el HTML declara de si mismo. La redireccion JS solo
  // se mide sin render y solo la incondicional (la pagina puente).
  redireccion_js:       { label: 'Redirección JS',  type: 'string',  sortable: false, filterKey: 'redireccion_js_contains', width: 240, fmt: r => r.html_meta?.redireccion_js ?? '' },
  viewport:             { label: 'Viewport',        type: 'string',  sortable: false, filterKey: 'viewport_contains',       width: 240, fmt: r => r.html_meta?.viewport ?? '' },
  html_lang:            { label: 'html lang',       type: 'string',  sortable: false, filterKey: 'html_lang_contains',      width: 110, fmt: r => r.html_meta?.html_lang ?? '' },
  in_sitemap:           { label: 'En el sitemap',   type: 'boolean', sortable: false, filterKey: 'in_sitemap',              width: 140, fmt: r => r.in_sitemap === true ? 'Sí' : r.in_sitemap === false ? 'No' : '' },
  og_title:             { label: 'OG title',        type: 'string',  sortable: false, filterKey: 'og_title_contains', vacio: 'og_title',       width: 220, fmt: r => r.html_meta?.og_title ?? '' },
  og_image:             { label: 'OG image',        type: 'string',  sortable: false, filterKey: 'og_image_contains', vacio: 'og_image',       width: 240, fmt: r => r.html_meta?.og_image ?? '' },
  og_type:              { label: 'OG type',         type: 'string',  sortable: false, filterKey: 'og_type_contains',        width: 140, fmt: r => r.html_meta?.og_type ?? '' },
  og_url:               { label: 'OG url',          type: 'string',  sortable: false, filterKey: 'og_url_contains',         width: 240, fmt: r => r.html_meta?.og_url ?? '' },
  twitter_card:         { label: 'Twitter card',    type: 'string',  sortable: false, filterKey: 'twitter_card_contains',   width: 150, fmt: r => r.html_meta?.twitter_card ?? '' },
  http_version:         { label: 'HTTP',            type: 'string',  sortable: false, filterKey: 'http_version_contains',   width: 130, fmt: r => r.html_meta?.http_version ?? r.http_version ?? '' },
  last_modified:        { label: 'Last-Modified',   type: 'string',  sortable: false, filterKey: 'last_modified_contains',  width: 180, fmt: r => r.last_modified ?? '' },
  // Calculadas en el servidor solo si estan visibles (?origenes=true): el
  // origen mas frecuente y cuantas paginas la enlazan. Para un 404 o una
  // redireccion es lo que dice DONDE hay que corregir.
  h1:                   { label: 'H1',               type: 'string',  sortable: false, calculada: 'h1', width: 260, fmt: r => r.h1 ?? '' },
  h1_count:             { label: 'Nº de H1',         type: 'numeric', sortable: false, calculada: 'h1', width: 110, fmt: r => r.h1_count ?? '' },
  // Frente al censo de la comparacion automatica (decision 71): «nueva»,
  // «200→404», «sale del índice», «título», «canonical», «palabras a→b».
  cambio:               { label: 'Cambio frente al anterior', type: 'string', sortable: false, calculada: 'cambios', width: 240, fmt: r => r.cambio ?? '' },
  enlazada_desde:       { label: 'Enlazada desde',  type: 'string',  sortable: false, calculada: 'origenes', width: 280, fmt: r => r.enlazada_desde ? rutaCorta(r.enlazada_desde) : '' },
  origenes:             { label: 'Páginas que la enlazan', type: 'numeric', sortable: false, calculada: 'origenes', width: 170, fmt: r => r.origenes ?? '' },
  last_crawled_at:      { label: 'Último rastreo',  type: 'string',  sortable: true,                                        width: 170, fmt: r => fmt.date(r.last_crawled_at) },
};

// El selector de columnas, agrupado: 50 casillas seguidas no se leen. «Otros»
// lleva lo que no conviene usar para decidir: la escala 0-10 del PageRank
// (decision 34) y el ratio de texto, que no es una señal de Google (decision 44).
const EXP_GRUPOS_COLUMNAS = [
  ['Respuesta',   ['url','segmento','status_code','status_text','content_type','redirect_url','redirect_type','response_time_ms','ttfb_ms','content_length','transfer_size','content_encoding','http_version','last_modified','host','is_internal']],
  ['Indexación',  ['indexable','indexability_status','bloqueada_googlebot','canonical_href','canonical_header','meta_robots','x_robots_tag','meta_refresh','redireccion_js','in_sitemap','rel_next','rel_prev']],
  ['Títulos y snippet', ['title','title_len','title_pixel_width','meta_description','meta_description_len','meta_description_pixel_width','h1','h1_count']],
  ['Contenido',   ['word_count','content_word_count','near_duplicate_count','closest_similarity']],
  ['Enlazado',    ['enlazada_desde','origenes','inlinks_count','unique_inlinks_count','outlinks_count','external_outlinks_count','pagerank_score','pagerank_externo_score','backlinks_externos','googlebot_visitas','click_depth','crawl_depth','folder_depth','url_length']],
  ['Redes sociales', ['og_title','og_image','og_type','og_url','twitter_card']],
  ['Móvil e idioma', ['viewport','html_lang']],
  ['Search Console (90 días)', ['gsc_clics','gsc_impresiones','gsc_posicion']],
  ['Frente al censo anterior', ['cambio']],
  ['Otros',       ['pagerank_raw','pagerank','text_ratio','last_crawled_at']],
];

// Las que deciden primero, junto a la URL: si se indexa y cuanto se enlaza
// (revision de UX del 25-oct, 3.4). Los clics de Google se anaden detras de
// los enlaces entrantes si el censo tiene Search Console (columnasPorDefecto).
const EXP_DEFAULT_COLUMNS = [
  'url','status_code','indexable','inlinks_count','title','title_len','meta_description','meta_description_len',
  'click_depth','word_count','pagerank_score','canonical_href',
  'content_type','content_length','response_time_ms','outlinks_count'
];

const HTML_INTERNO = { resource_type: 'html', is_internal: true };

// Columnas de las reglas a medida del censo (decision 104). Una celda que no
// es un resultado se pinta «—» y el motivo va en el tooltip: «no evaluada»
// (sin fila) no es «vacío» (sin coincidencia).
const ESTADOS_A_MEDIDA = {
  sin_coincidencia: 'sin coincidencia', incompleta: 'incompleta: la fuente pasaba de 2 MB',
  conversion_fallida: 'no se pudo leer como número', tiempo_agotado: 'la regex agotó su tiempo',
  presupuesto_pagina: 'sin tiempo en esta página', desactivada: 'regla desactivada (agotó su tiempo 3 veces)',
  pagina_bloqueada: 'página bloqueada por un WAF', error: 'error',
};

function _defsAMedida(job) {
  const cfg = (job && job.config) || {};
  const out = {};
  const render = !!cfg.render_js;
  const marca = (f) => (render && f && f.render === false) ? ' *' : '';
  const tip = (nombre) => (row) => {
    const f = (row.a_medida || {})[nombre];
    if (!f) return 'No evaluada: no es HTML 2xx o queda fuera de solo_urls';
    const base = f.estado === 'ok' ? (f.valor ?? '') : (ESTADOS_A_MEDIDA[f.estado] || f.estado);
    return base + (f.truncado ? ' (recortado)' : '') + (render && f.render === false ? ' · extraído SIN render' : '');
  };
  for (const [nombre, r] of Object.entries(cfg.custom_extraction || {})) {
    if (!r) continue;
    const numerica = r.valor === 'numero' || r.cuantos === 'recuento';
    const key = 'x.' + nombre;
    out[key] = {
      label: r.etiqueta || nombre, nombre, clase: 'extractor', aMedida: true, sortable: true, width: 160,
      type: numerica ? 'numeric' : 'string',
      filterKey: numerica ? key : key + '_contains', vacio: key, tip: tip(nombre),
      fmt: row => {
        const f = (row.a_medida || {})[nombre];
        if (!f || (f.estado !== 'ok' && f.estado !== 'conversion_fallida')) return '—';
        const v = numerica && f.valor_num != null ? fmt.num(f.valor_num) : (f.valor ?? '');
        return v + marca(f);
      },
    };
  }
  for (const [nombre, r] of Object.entries(cfg.custom_search || {})) {
    if (!r) continue;
    const key = 'x.' + nombre;
    out[key] = {
      label: r.etiqueta || nombre, nombre, clase: 'busqueda', aMedida: true, sortable: true, width: 140,
      type: 'boolean', filterKey: key, tip: tip(nombre),
      fmt: row => {
        const f = (row.a_medida || {})[nombre];
        if (!f) return '—';
        if (f.estado === 'ok') return 'sí (' + f.n + ')' + marca(f);
        if (f.estado === 'sin_coincidencia') return 'no' + marca(f);
        return '—';
      },
    };
  }
  return out;
}

const EXP_TABS = [
  { key: 'all',        label: 'Todas',       icon: 'layers',      filter: null,                                   columns: EXP_DEFAULT_COLUMNS },
  // V30 (revision de UX del 25-oct, 3.4): «HTML 3.772» en la barra y «3.731
  // paginas HTML» en la tarjeta eran dos cuentas distintas con el mismo
  // nombre: la tarjeta cuenta las internas que responden 2xx (lo indexable) y
  // la barra todo lo que responde HTML, tambien los 4xx y 5xx. Ahora son dos
  // entradas con nombre propio y la tarjeta abre la suya.
  { key: 'paginas_html', label: 'Páginas HTML', icon: 'file-text', filter: { resource_type: 'html', is_internal: true, status_group: '2xx' },
    titulo: 'Páginas HTML internas que responden 2xx: la misma cifra que la tarjeta «Páginas HTML» del Resumen',
    columns: ['url','status_code','indexable','inlinks_count','title','title_len','meta_description','meta_description_len','word_count','response_time_ms','content_length','outlinks_count','external_outlinks_count','pagerank_score','canonical_href','meta_robots'] },
  { key: 'html',       label: 'Todo el HTML', icon: 'file-text',  filter: { resource_type: 'html' },
    titulo: 'Todas las URLs que responden HTML, también las que dan error (4xx, 5xx)',
    columns: ['url','status_code','indexable','inlinks_count','title','title_len','meta_description','meta_description_len','word_count','response_time_ms','content_length','outlinks_count','external_outlinks_count','pagerank_score','canonical_href','meta_robots'] },
  { key: 'js',         label: 'JavaScript',  icon: 'file-code',   filter: { resource_type: 'js' },                columns: ['url','status_code','content_length','transfer_size','response_time_ms','last_modified'] },
  { key: 'css',        label: 'CSS',         icon: 'palette',     filter: { resource_type: 'css' },               columns: ['url','status_code','content_length','transfer_size','response_time_ms','last_modified'] },
  { key: 'image',      label: 'Imágenes',    icon: 'image',       filter: { resource_type: 'image' },             columns: ['url','status_code','content_length','transfer_size','response_time_ms'] },
  { key: 'pdf',        label: 'PDFs',        icon: 'file',        filter: { resource_type: 'pdf' },               columns: ['url','status_code','content_length','transfer_size','response_time_ms'] },
  { key: '_div1', divider: true },
  { key: 'internal',   label: 'Internas',    icon: 'home',        filter: { is_internal: true },                  columns: ['url','status_code','indexable','inlinks_count','title','title_len','meta_description','word_count','outlinks_count','external_outlinks_count','pagerank_score','click_depth','canonical_href'] },
  { key: 'external',   label: 'Externas',    icon: 'external-link', filter: { is_internal: false },               columns: ['url','status_code','host','content_type','content_length','response_time_ms'] },
  { key: '_div2', divider: true },
  { key: '2xx',        label: '2xx',         icon: 'check-circle', filter: { status_group: '2xx' },               columns: ['url','status_code','indexable','inlinks_count','title','title_len','meta_description','meta_description_len','word_count','response_time_ms','outlinks_count','pagerank_score','canonical_href'] },
  { key: '3xx',        label: '3xx',         icon: 'arrow-right', filter: { status_group: '3xx' },                columns: ['url','status_code','redirect_url','redirect_type','inlinks_count','origenes','enlazada_desde','click_depth'] },
  { key: '4xx',        label: '4xx',         icon: 'alert-triangle', filter: { status_group: '4xx' },             columns: ['url','status_code','inlinks_count','origenes','enlazada_desde','click_depth','content_type'] },
  { key: '5xx',        label: '5xx',         icon: 'alert-octagon', filter: { status_group: '5xx' },              columns: ['url','status_code','status_text','response_time_ms','click_depth','inlinks_count'] },
  { key: '_div3', divider: true },
  // Sobre las mismas paginas que la tarjeta «Indexables» del Resumen (HTML
  // internas con 2xx; revision de UX del 25-oct, 3.4; decision 202): la barra
  // decia «Indexables 3.407» (contaba tambien PDF e imagenes) y la tarjeta
  // «3.216 indexables», y la tarjeta abria una lista de «No indexables» con
  // las redirecciones y los errores dentro. Los PDF y las imagenes tienen su
  // entrada; las redirecciones y los errores, la suya por codigo.
  { key: 'indexable',  label: 'Páginas indexables',  icon: 'eye', filter: { resource_type: 'html', is_internal: true, status_group: '2xx', indexable: true },
    titulo: 'Páginas HTML internas que responden 2xx y se pueden indexar: la misma cifra que la tarjeta «Indexables» del Resumen',
    columns: ['url','status_code','inlinks_count','title','title_len','meta_description','word_count','pagerank_score','canonical_href'] },
  { key: 'noindex',    label: 'Páginas no indexables', icon: 'eye-off', filter: { resource_type: 'html', is_internal: true, status_group: '2xx', indexable: false },
    titulo: 'Páginas HTML internas que responden 2xx y no se pueden indexar (noindex, canonical a otra URL…): las «no indexables» de la tarjeta del Resumen',
    columns: ['url','status_code','indexability_status','title','meta_robots','canonical_href'] },
  // URLs que el sitio enlaza y robots.txt prohibe: no se piden, pero existen y
  // hay que decidir si el bloqueo es correcto o se esta tapando contenido.
  { key: 'bloqueadas', label: 'Bloqueadas robots', icon: 'slash',  filter: { status_group: 'blocked' },           columns: ['url','indexability_status','inlinks_count','click_depth'] },
  // Extraccion y busqueda a medida (decision 104): solo si el censo tiene
  // reglas. Sus columnas las rellena _registrarAMedida al abrir el censo.
  { key: 'a_medida',   label: 'Extracción a medida', icon: 'scan-search', filter: HTML_INTERNO, requiere: 'a_medida', columns: ['url','status_code'] },
  // Vistas por ambito SEO (#131), como las pestañas de Screaming Frog pero
  // construidas con lo que ya calcula el analizador: cada una son las paginas
  // HTML internas, sus columnas y, encima de la tabla, un chip por tipo de
  // incidencia de su ambito con cuantas paginas lo tienen.
  { key: '_h1', header: 'Por ámbito SEO' },
  { key: 'a_titulos',  label: 'Títulos',       icon: 'heading',      filter: HTML_INTERNO, ambito: ['title_missing','title_too_short','title_too_long','title_duplicate','title_multiple','title_generico'],
    columns: ['url','status_code','title','title_len','title_pixel_width','indexable','inlinks_count'] },
  { key: 'a_desc',     label: 'Descripciones', icon: 'align-left',   filter: HTML_INTERNO, ambito: ['description_missing','description_too_short','description_too_long','description_duplicate','description_multiple','description_igual_title'],
    columns: ['url','status_code','meta_description','meta_description_len','meta_description_pixel_width','indexable'] },
  { key: 'a_h1',       label: 'Encabezados',   icon: 'type',         filter: HTML_INTERNO, ambito: ['h1_missing','h1_vacio','h1_multiple','h1_duplicate','encabezado_salta_nivel'],
    columns: ['url','status_code','h1','h1_count','title','indexable'] },
  { key: 'a_canon',    label: 'Canonicals',    icon: 'link-2',       filter: HTML_INTERNO, ambito: ['canonical_missing','canonical_cross_domain','canonical_a_error','canonical_a_redireccion','canonical_a_no_indexable','canonical_encadenado','canonical_sin_enlazar','canonical_broken','canonical_multiple','canonical_in_body','canonical_a_http','canonical_html_y_cabecera_distintos','noindex_y_canonical_a_otra','canonical_relativo','canonical_con_fragmento','google_elige_otro_canonical','google_tiene_canonical_antiguo'],
    columns: ['url','status_code','canonical_href','canonical_header','indexable','indexability_status'] },
  // Las redirecciones no son HTML: el ambito va sobre las internas.
  { key: 'a_redir',    label: 'Redirecciones', icon: 'corner-down-right', filter: { is_internal: true }, ambito: ['redireccion_a_error','redireccion_a_noindex','redireccion_a_portada','meta_refresh_redireccion','redirect_chain','redirect_loop','redireccion_por_javascript'],
    columns: ['url','status_code','redirect_url','redirect_type','inlinks_count','origenes','click_depth'] },
  { key: 'a_robots',   label: 'Directivas',    icon: 'shield',       filter: HTML_INTERNO, ambito: ['noindex_page','noindex_y_canonical_a_otra','robots_invalid_syntax','pagina_nofollow','robots_txt_inaccesible','robots_difiere_para_googlebot','bot_busqueda_ia_bloqueado'],
    columns: ['url','status_code','indexable','indexability_status','bloqueada_googlebot','meta_robots','x_robots_tag','in_sitemap'] },
  // Decision 137: lo que decide si la pagina sale en el fragmento y en las
  // funciones de IA de la Busqueda, y si los buscadores de IA pueden entrar.
  { key: 'a_ia',       label: 'IA',            icon: 'sparkles',     filter: HTML_INTERNO, ambito: ['nosnippet_en_indexable','max_snippet_restrictivo','data_nosnippet_contenido_principal','data_nosnippet_ignorado','bot_busqueda_ia_bloqueado','contenido_solo_con_js'],
    columns: ['url','status_code','indexable','meta_robots','x_robots_tag','pagerank_score'] },
  // Decision 142: Search Console cruzado con el rastreo.
  { key: 'a_trafico',  label: 'Tráfico de Google', icon: 'trending-up', filter: { is_internal: true }, ambito: ['trafico_en_pagina_perdida','trafico_en_redireccion','huerfana_con_trafico','indexable_sin_impresiones','trafico_en_variante_con_parametros','indexable_no_indexada_por_google','google_elige_otro_canonical','google_tiene_canonical_antiguo','oportunidad_posicion','ctr_bajo_para_posicion','canibalizacion_por_consulta','sitemap_no_enviado_a_google','sitemap_no_leido_por_google','sitemap_con_errores_en_google'],
    columns: ['url','status_code','indexable','indexability_status','gsc_clics','gsc_impresiones','gsc_posicion','inlinks_count'] },
  // Decision 140: el HTML del servidor frente al render, por muestra de plantilla.
  { key: 'a_js',       label: 'JavaScript',    icon: 'code',         filter: HTML_INTERNO, ambito: ['noindex_solo_en_crudo','noindex_solo_al_renderizar','canonical_cambia_al_renderizar','nofollow_cambia_al_renderizar','contenido_solo_con_js','cambia_al_renderizar','respuesta_cambia_al_renderizar','redireccion_por_javascript'],
    columns: ['url','status_code','indexable','canonical_href','meta_robots','content_word_count'] },
  // Decision 174: axe-core por muestra de plantilla (una fila por regla y plantilla).
  { key: 'a_a11y',     label: 'Accesibilidad', icon: 'accessibility', filter: HTML_INTERNO, ambito: ['accesibilidad_grave','accesibilidad_menor'],
    columns: ['url','status_code','title','html_lang','indexable'] },
  { key: 'a_html',     label: 'HTML ignorado', icon: 'scissors',     filter: HTML_INTERNO, ambito: ['html_supera_2mb','head_cortado','meta_fuera_del_head'],
    columns: ['url','status_code','content_length','title','meta_robots','indexable'] },
  { key: 'a_hreflang', label: 'Hreflang',      icon: 'languages',    filter: HTML_INTERNO, ambito: ['hreflang_missing_return','hreflang_invalid_lang','hreflang_broken_target','hreflang_in_body','hreflang_sin_autorreferencia','hreflang_sin_x_default','hreflang_idioma_repetido','hreflang_destino_no_indexable','hreflang_retorno_incoherente','hreflang_fuentes_discrepan','html_lang_no_coincide_hreflang'],
    columns: ['url','status_code','title','indexable','inlinks_count'] },
  // Decision 108: lo que el HTML declara de si mismo. Casi todo de plantilla
  // o de servidor (una fila por grupo), y nada saca una pagina del indice.
  { key: 'a_declara',  label: 'Móvil, charset y OG', icon: 'smartphone', filter: HTML_INTERNO, ambito: ['viewport_ausente','viewport_incorrecto','html_lang_ausente','texto_mal_codificado','charset_incoherente','charset_ausente','og_ausente','og_image_relativa','og_image_pequena','og_image_rota','twitter_card_invalida','amphtml_incorrecto','alternate_movil_incorrecto'],
    columns: ['url','status_code','viewport','html_lang','og_title','og_image','indexable'] },
  { key: 'a_sd',       label: 'Datos estructurados', icon: 'braces', filter: HTML_INTERNO, ambito: ['structured_data_error','structured_data_warning','structured_data_info','portada_sin_entidad'],
    columns: ['url','status_code','title','indexable','pagerank_score'] },
  { key: 'a_enlazado', label: 'Enlazado',      icon: 'share-2',      filter: HTML_INTERNO, ambito: ['orphan_page','sitemap_orphan','solo_enlazada_por_redireccion','not_reachable_from_home','high_outlink_count','not_in_sitemap','enlace_no_rastreable','enlace_interno_a_error','enlace_interno_a_redireccion','utm_en_enlace_interno','enlace_sin_ancla','ancla_generica','solo_enlazada_con_nofollow','enlace_interno_nofollow','pagina_nofollow','solo_enlazada_desde_paginacion_excluida','enlace_externo_roto','dominio_externo_muerto'],
    columns: ['url','status_code','inlinks_count','origenes','click_depth','pagerank_score','in_sitemap','indexable'] },
  // Logs del servidor (decision 213).
  { key: 'a_logs', label: 'Logs', icon: 'scroll-text', filter: { is_internal: true }, ambito: ['indexable_sin_visitas_googlebot','googlebot_recibe_error'],
    columns: ['url','status_code','googlebot_visitas','pagerank_score','inlinks_count','indexable'] },
  // Backlinks del CSV del cliente (decision 212).
  { key: 'a_backlinks', label: 'Backlinks', icon: 'external-link', filter: { is_internal: true }, ambito: ['backlinks_a_error','backlinks_a_noindex','backlinks_a_bloqueada_robots'],
    columns: ['url','status_code','backlinks_externos','pagerank_externo_score','inlinks_count','pagerank_score','indexable'] },
  // Paginacion (decision 122): las paginas 2+ y lo que solo cuelga de ellas.
  { key: 'a_paginacion', label: 'Paginación', icon: 'list-ordered', filter: HTML_INTERNO, ambito: ['paginacion_canonical_a_la_primera','paginacion_noindex','solo_enlazada_desde_paginacion_excluida','solo_enlazada_desde_paginacion_profunda','paginacion_sin_enlace','paginacion_siguiente_rota','paginacion_rel_incorrecto'],
    columns: ['url','status_code','rel_next','rel_prev','canonical_href','indexable','inlinks_count'] },
  // Sin HTML_INTERNO: lo que el sitemap declara y no se puede indexar son
  // sobre todo saltos (resource_type 'redirect') y errores (decision 100). Y
  // sin in_sitemap en el filtro: dejaria vacio el chip de not_in_sitemap.
  { key: 'a_sitemap',  label: 'Sitemap',       icon: 'map',          filter: { is_internal: true }, ambito: ['sitemap_no_indexable','sitemap_orphan','not_in_sitemap','sitemap_supera_limite','lastmod_futuro','en_varios_sitemaps','video_sin_sitemap_de_video'],
    columns: ['url','status_code','indexable','indexability_status','redirect_url','canonical_href','inlinks_count','in_sitemap'] },
  // WordPress por su REST API (decision 161): casi todo agrupado por host o
  // por tipo; solo hay chips si el censo detecto un WordPress con la REST API
  // abierta.
  { key: 'a_wordpress', label: 'WordPress',    icon: 'layout-template', filter: { is_internal: true }, ambito: ['wp_publicado_no_rastreado','wp_adjunto_indexable','wp_taxonomia_anemica','wp_paginacion_sin_fin'],
    columns: ['url','status_code','indexable','inlinks_count','in_sitemap'] },
  { key: 'a_contenido', label: 'Contenido',    icon: 'file-text',    filter: HTML_INTERNO, ambito: ['low_word_count','duplicate_content','near_duplicate_content','soft_404','soft_404_candidato','soft_404_plantilla','broken_resource'],
    columns: ['url','status_code','title','content_word_count','near_duplicate_count','closest_similarity','indexable'] },
  // Paridad movil/escritorio (decision 119): solo hay chips si el censo se
  // rastreo con `crawl_behavior.paridad_movil_muestra`.
  { key: 'a_movil',    label: 'Móvil',         icon: 'smartphone',   filter: HTML_INTERNO, ambito: ['paridad_movil_indexacion','paridad_movil_contenido','paridad_movil_respuesta'],
    columns: ['url','status_code','title','canonical_href','meta_robots','content_word_count','indexable'] },
  { key: 'a_urls',     label: 'Forma de la URL', icon: 'link',       filter: { is_internal: true }, ambito: ['url_too_long','url_non_ascii','url_uppercase','url_underscores','url_multiple_slashes','url_has_parameters','url_non_seo_friendly','url_cms_faceted','trampa_de_rastreo'],
    columns: ['url','status_code','url_length','indexable','inlinks_count'] },
  // Lo del servidor (decisiones 109 y 110): tiempo hasta el primer byte,
  // compresion y certificado. Sobre las internas: un host con el certificado
  // roto no tiene ni una HTML 200.
  { key: 'a_servidor', label: 'Servidor',      icon: 'server',       filter: { is_internal: true }, ambito: ['respuesta_lenta','html_sin_comprimir','tls_certificado_invalido','tls_caduca_pronto','tls_version_antigua'],
    columns: ['url','status_code','status_text','ttfb_ms','response_time_ms','content_encoding','http_version'] },
];

// Las columnas de serie de una pestaña. Con Search Console en el censo, los
// clics de Google van detras de los enlaces entrantes (revision de UX del
// 25-oct, 3.4): sin el, una columna vacia no dice nada y no se pone.
function columnasPorDefecto(columnas, job) {
  if (!(job && job.gsc_resumen) || columnas.includes('gsc_clics')) return columnas;
  const i = columnas.indexOf('inlinks_count');
  if (i < 0) return columnas;
  return [...columnas.slice(0, i + 1), 'gsc_clics', ...columnas.slice(i + 1)];
}

// Un rastreo en modo lista: no sigue enlaces (decision 128, `es_lista`).
function esModoLista(job) {
  const p = (job && job.config || {}).max_depth;
  return p === 0 || p === '0';
}

// Las tarjetas de comprobaciones de la ficha (TLS, soft 404, sondas,
// sitemaps). Funciones puras sobre `job` para poder probarlas en Chromium sin
// montar Alpine (tests/test_resumenes_frontend.py). Cada una devuelve null si
// el job no trae ese dato: un rastreo anterior o con la sonda apagada no es
// «0 problemas».

// `jobs.tls` (decision 110): {hosts: {host: ficha de sonda_tls}}.
function filasTls(job) {
  const hosts = ((job && job.tls) || {}).hosts;
  if (!hosts || typeof hosts !== 'object') return null;
  const aviso = Number((((job.config || {}).analysis_thresholds) || {}).tls_dias_aviso) || 7;
  const filas = Object.entries(hosts).map(([host, t]) => {
    t = t || {};
    const dias = typeof t.dias_restantes === 'number' ? t.dias_restantes : null;
    let estado, nivel;
    if (t.omitida) { estado = 'Sin comprobar (' + t.omitida + ')'; nivel = 'dim'; }
    else if (t.verificado === false) { estado = 'No válido: ' + (t.motivo || 'otro'); nivel = 'red'; }
    else if (dias !== null && dias < 0) { estado = 'Caducado'; nivel = 'red'; }
    else if (dias !== null && dias <= aviso) { estado = 'Caduca pronto'; nivel = 'orange'; }
    else if (t.version_antigua) { estado = 'TLS antiguo'; nivel = 'orange'; }
    // A 30 dias o menos no es «Valido» sin mas, aunque el aviso del analisis
    // (7 de serie) no salte: Lopesan caducaba en 14 y la columna decia
    // «Valido» en verde (revision de UX del 25-oct, 3.6; V19).
    else if (t.verificado === true && dias !== null && Math.floor(dias) <= 30) {
      const n = Math.floor(dias);
      estado = 'Válido, caduca en ' + n + (n === 1 ? ' día' : ' días'); nivel = 'orange';
    }
    else if (t.verificado === true) { estado = 'Válido'; nivel = 'green'; }
    else if (t.error) { estado = 'Sin respuesta'; nivel = 'dim'; }
    else { estado = 'Sin verificar'; nivel = 'orange'; }
    return {
      host, estado, nivel,
      emisor: t.emisor || null,
      caduca: t.not_after || null,
      dias: dias === null ? null : Math.floor(dias),
      // A 30 dias o menos conviene renovarlo aunque el aviso del analisis
      // (tls_dias_aviso, 7 de serie) no haya saltado: la cifra va en naranja
      // (revision de UX del 25-oct, 1.16; Lopesan caducaba en 14 y salia en verde).
      renovar: dias !== null && dias >= 0 && Math.floor(dias) <= 30,
      version: t.version || null,
      detalle: t.detalle || t.error || t.error_certificado || null,
    };
  });
  filas.sort((a, b) => a.host.localeCompare(b.host));
  return filas.length ? filas : null;
}

// robots.txt por bot (decision 129) en una frase: que bots se bloquean y
// donde. Las tablas (doce bots por host, casi siempre «Permitida») van
// plegadas debajo (revision de UX del 25-oct, 1.16). `nivel`: red si se
// bloquea entero un buscador o un bot de busqueda de IA, orange si se
// bloquea algo, '' si nada; `sin_evaluar`: hosts sin datos por bot.
function resumenRobots(rb) {
  if (!rb || !Array.isArray(rb.hosts) || !rb.hosts.length) return null;
  const tipos = Object.fromEntries((rb.bots || []).map(b => [b.bot, b]));
  const bloqueos = [];
  let nivel = '', sinEvaluar = 0;
  for (const h of rb.hosts) {
    if (!h.bots) { sinEvaluar++; continue; }
    for (const [bot, r] of Object.entries(h.bots)) {
      if (!r || !['todo', 'parte'].includes(r.alcance)) continue;
      const b = tipos[bot] || { token: bot, tipo: '' };
      bloqueos.push(b.token + ' (' + (r.alcance === 'todo' ? 'todo' : 'una parte') + ' en ' + h.origen + ')');
      if (r.alcance === 'todo' && ['buscador', 'busqueda_ia'].includes(b.tipo)) nivel = 'red';
      else if (nivel !== 'red') nivel = 'orange';
    }
  }
  const evaluados = rb.hosts.length - sinEvaluar;
  let texto;
  if (!evaluados) texto = 'Sin evaluar por bot: censo analizado antes de la decisión 129 o robots.txt no procesado.';
  else if (!bloqueos.length) texto = 'Ningún bot bloqueado en la home ni en la muestra' + (evaluados > 1 ? ' de los ' + evaluados + ' hosts evaluados.' : (sinEvaluar ? ' del host evaluado.' : '.'));
  else texto = 'Bloqueados: ' + bloqueos.join(', ') + '.';
  // Un host sin evaluar puede ser un robots.txt inaccesible (5xx, 429): para
  // Google es «no rastrear nada». No se da por bueno (revision de la 1.16).
  if (evaluados && sinEvaluar) {
    texto += ' ' + sinEvaluar + (sinEvaluar === 1 ? ' host sin evaluar' : ' hosts sin evaluar') + ': mira su robots.txt en el detalle.';
    if (nivel !== 'red') nivel = 'orange';
  }
  return { texto, nivel, sin_evaluar: sinEvaluar, abrir: !!bloqueos.length || !!sinEvaluar };
}

// `jobs.soft404` (decision 105): `sondas` las escribe el spider (lista, una
// por host y por plantilla) y `resumen` el analisis.
// Copia de `shared.respuestas.NO_VALIDAS` y `TITULOS_DE_BLOQUEO` (decisiones
// 62 y 103) para los censos analizados antes de la decision 190, que no traen
// la lista de sondas que cuentan.
const SOFT404_CLASES_NO_VALIDAS = ['challenge_waf', 'captcha', 'rate_limited', 'respuesta_binaria'];
const SOFT404_TITULOS_DE_BLOQUEO = ['just a moment', 'access denied', 'pardon our interruption', 'attention required',
  'request unsuccessful', 'are you a robot', 'checking your browser', 'security check', '403 forbidden'];

// Copia de `shared.comparacion.NO_COMPARABLES`: tipos de Search Console que
// la comparacion entre censos no mira (cambian con el periodo de datos).
const TIPOS_NO_COMPARABLES = ['oportunidad_posicion', 'ctr_bajo_para_posicion', 'canibalizacion_por_consulta'];
// El tope de `segmentos_max` de /issues/resumen.
const SEGMENTOS_MAX_NEGOCIO = 200;

// Nombre legible de una plantilla de ruta (soft_404_plantilla, 2.11): sin el
// «(4n)» del numero de tramos, que es interno, y con «…» por cada tramo
// variable («/blog/category/:slug (3n)» -> «/blog/category/…»).
function nombreDePlantilla(p) {
  if (!p) return 'la raíz del sitio';
  return String(p).replace(/ \(\d+n\)$/, '').replace(/:[a-z_]+/gi, '…');
}

function resumenSoft404(job) {
  const s = job && job.soft404;
  if (!s || typeof s !== 'object') return null;
  const sondas = Array.isArray(s.sondas) ? s.sondas : [];
  const r = (s.resumen && typeof s.resumen === 'object') ? s.resumen : null;
  if (!sondas.length && !r) return null;
  const detalle = {};
  for (const d of ((r || {}).detalle_sondas || [])) if (d && d.url) detalle[d.url] = d;
  const filas = sondas.map(x => {
    x = x || {};
    const d = detalle[x.url] || null;
    const st = x.status;
    let lectura, nivel;
    if (x.error) { lectura = x.error === 'bloqueada_por_robots' ? 'Bloqueada por robots.txt' : 'Error: ' + x.error; nivel = 'dim'; }
    else if (st === 404 || st === 410) { lectura = 'Responde ' + st + ', como debe'; nivel = 'green'; }
    else if (x.redirige_a) { lectura = 'Redirige'; nivel = 'orange'; }
    else if (st >= 200 && st < 300) { lectura = 'Responde ' + st + ' a una URL que no existe'; nivel = 'red'; }
    else { lectura = 'Responde ' + (st == null ? '—' : st); nivel = 'orange'; }
    return {
      clave: x.clave || x.url, host: x.host || '', plantilla: x.plantilla || null,
      url: x.url, status: st == null ? null : st, redirige_a: x.redirige_a || null,
      lectura, nivel,
      coincidencias: d ? d.coincidencias : null, alcance: d ? d.alcance : null,
      ambigua: d ? !!d.ambigua : false, devuelve_portada: d ? !!d.devuelve_portada : false,
      _cruda: x,
    };
  });
  // Las plantillas que responden 200 a lo que no existe (revision de UX del
  // 25-oct, 2.11). Con un analisis de la decision 190, las que el analisis
  // conto (`sondas_responden_200`); antes, el mismo filtro que
  // `_sonda_responde_200` de analysis/soft404.py: 2xx sin redireccion ni
  // error, sin muro de WAF (clase de respuesta o titulo de bloqueo) y una por
  // host y plantilla. Un muro servido con 200 no es la respuesta del sitio.
  let responden200;
  if (r && Array.isArray(r.sondas_responden_200)) {
    const contadas = new Set(r.sondas_responden_200);
    responden200 = filas.filter(f => f.nivel === 'red' && contadas.has(f.url));
  } else {
    const vistas = new Set();
    responden200 = filas.filter(f => {
      const x = f._cruda;
      if (f.nivel !== 'red' || x.redirige_a || x.error) return false;
      if (SOFT404_CLASES_NO_VALIDAS.includes(x.response_class)) return false;
      const titulo = String(x.titulo || '').trim().toLowerCase();
      if (SOFT404_TITULOS_DE_BLOQUEO.some(t => titulo.includes(t))) return false;
      const clave = (f.host || '').toLowerCase() + '|' + (f.plantilla || '');
      if (vistas.has(clave)) return false;
      vistas.add(clave);
      return true;
    });
  }
  return {
    filas,
    sondas: r && r.sondas != null ? r.sondas : filas.length,
    con_huella: r ? r.sondas_con_huella : null,
    soft_404: r ? r.soft_404 : null,
    indexables: r ? r.soft_404_indexables : null,
    candidatos: r ? r.candidatos : null,
    analizado: !!r,
    // Sondas que responden 2xx a una URL que no existe (revision de UX del
    // 25-oct, 2.11): con «0 paginas» en verde al lado se leia como «sin
    // soft 404». En los censos analizados con la decision 190 van ademas como
    // un aviso agrupado en Problemas (`soft_404_plantilla`).
    responden200,
    plantillas_200: responden200.length,
    aviso_en_problemas: !!(r && r.plantillas_responden_200),
    // Analizado con la decision 190 (aunque no haya emitido nada).
    con_aviso_190: !!(r && Array.isArray(r.sondas_responden_200)),
  };
}

// `jobs.sondas_resumen` (decisiones 123 y 124). «comprobados < distintos» se
// dice: que no haya aviso no significa que no haya nada roto.
function resumenSondas(job) {
  const s = job && job.sondas_resumen;
  if (!s || typeof s !== 'object') return null;
  const bloque = (b, etiqueta) => {
    if (!b || typeof b !== 'object' || !Object.keys(b).length) return null;
    const distintos = b.distintos == null ? null : b.distintos;
    return {
      etiqueta,
      distintos, comprobados: b.comprobados == null ? null : b.comprobados,
      rotos: b.rotos || 0, dominios_muertos: b.dominios_muertos == null ? null : b.dominios_muertos,
      parcial: distintos != null && b.comprobados != null && b.comprobados < distintos,
      por_veredicto: Object.entries(b.por_veredicto || {}).sort((a, c) => c[1] - a[1]),
    };
  };
  const filas = [bloque(s.enlaces_externos, 'Enlaces externos'), bloque(s.recursos, 'Recursos embebidos')]
    .filter(Boolean);
  return filas.length ? filas : null;
}

// «Hosts más frecuentes» en una frase cuando uno se lleva el 95 % o mas de
// las URLs (revision de UX del 25-oct, 3.6; V19): dos barras, una llena y
// otra vacia, no dicen mas que esto. null si hay reparto de verdad.
function hostDominante(hosts) {
  const h = (hosts || []).filter(x => x && x.count);
  // La API da los 20 primeros: con 20 puede haber mas y el total no se sabe.
  if (h.length < 2 || h.length >= 20) return null;
  const total = h.reduce((n, x) => n + x.count, 0);
  if (h[0].count / total < 0.95) return null;
  const resto = h.slice(1, 4).map(x => x.host + ' (' + fmt.num(x.count) + ')').join(', ') + (h.length > 4 ? ' y ' + fmt.num(h.length - 4) + ' más' : '');
  return 'Casi todo en ' + h[0].host + ': ' + fmt.num(h[0].count) + ' de ' + fmt.num(total) + ' URLs. El resto, en ' + resto + '.';
}

// Sobre que paginas se cuenta cada alerta de la comparacion (revision de UX
// del 25-oct, 3.6; V20). Es `BASE_DE_LA_REGLA` de shared/comparacion.py en
// palabras; una regla que no esta aqui (las de la extraccion a medida) sale
// sin frase, no con una inventada.
const BASE_ALERTA_REGLA = {
  canonical_a_otro_host: 'todas_las_comunes', canonical_a_otra_url: 'era_indexable', rotas: 'era_indexable',
  salen_del_indice: 'era_indexable', redirigidas: 'era_indexable', pierden_contenido: 'era_indexable',
  cambia_el_titulo: 'era_indexable', entran_en_el_indice: 'no_era_indexable',
  desaparecen: 'era_indexable_en_el_primero', se_alejan_de_la_home: 'era_indexable',
  pierden_enlaces_internos: 'era_indexable', pierden_pagerank: 'era_indexable',
  pierden_datos_estructurados: 'indexable_con_datos_estructurados', pierden_hreflang: 'indexable_con_hreflang',
  cambia_la_description: 'era_indexable',
};
// [una pagina, varias]
const BASE_ALERTA_TEXTO = {
  era_indexable: ['que era indexable en el censo anterior y está en los dos', 'que eran indexables en el censo anterior y están en los dos'],
  no_era_indexable: ['que no era indexable en el censo anterior y está en los dos', 'que no eran indexables en el censo anterior y están en los dos'],
  era_indexable_en_el_primero: ['que era indexable en el censo anterior', 'que eran indexables en el censo anterior'],
  todas_las_comunes: ['que está en los dos censos', 'que están en los dos censos'],
  indexable_con_datos_estructurados: ['indexable que tenía datos estructurados en el censo anterior', 'indexables que tenían datos estructurados en el censo anterior'],
  indexable_con_hreflang: ['indexable que tenía hreflang en el censo anterior', 'indexables que tenían hreflang en el censo anterior'],
};
function baseAlerta(al) {
  const t = al && BASE_ALERTA_TEXTO[BASE_ALERTA_REGLA[al.regla]];
  if (!t || al.de == null) return '';
  return al.de === 1 ? 'Sobre la única página ' + t[0] + '.' : 'Sobre las ' + fmt.num(al.de) + ' páginas ' + t[1] + '.';
}

// ---- Limpieza (revision de UX del 25-oct, 3.6; decision 198) ----
// El texto repetido de un grupo, como se lee en su celda: «38 % · 1.250
// caracteres por página»; sin medir, «sin medir», nunca «0 %».
function textoRepetidoGrupo(g) {
  if (!g || g.repetido_parte == null) return 'sin medir';
  if (!g.repetido_parte) return 'nada';
  return (g.repetido_parte < 0.01 ? 'menos del 1 %' : fmt.pct(100 * g.repetido_parte, 0)) + ' · ' + fmt.num(g.repetido_chars_medio) + ' caracteres por página';
}
// Lo que quitan las lineas propuestas frente a la cifra del grupo: la cifra
// es de todas las repetidas y las propuestas tienen tope (40). Se mide sobre
// el texto que leen los analisis, no sobre el markdown.
function notaLineasLimpieza(g) {
  if (!g || !(g.lineas_repetidas || []).length || g.repetido_parte_lineas == null) return '';
  const n = g.lineas_repetidas.length, total = g.lineas_repetidas_total || n;
  const parte = g.repetido_parte_lineas < 0.01 ? 'menos del 1 %' : fmt.pct(100 * g.repetido_parte_lineas, 0);
  if (total > n) return `Hay ${fmt.num(total)} líneas repetidas; aquí van las ${fmt.num(n)} que más texto ocupan, que son el ${parte} del texto.`;
  return n > 1 ? `Quitar estas ${fmt.num(n)} líneas deja el texto un ${parte} más corto.` : `Quitar esta línea deja el texto un ${parte} más corto.`;
}
const limpiezaConRepetido = gs => (gs || []).some(g => g && g.repetido_parte != null);
const limpiezaConLimpiadas = gs => (gs || []).some(g => g && g.cleaned_pages);
// Como van ordenados, para que nadie lea «por profundidad». Una API anterior
// a la decision 198 los da por paginas y sin cifra de texto repetido.
function textoOrdenLimpieza(gs) {
  if (!(gs || []).length) return '';
  return limpiezaConRepetido(gs)
    ? 'Primero los que más texto repetido tienen (en una muestra de cada grupo): son los que más gana la limpieza. Pulsa una fila para ver lo que se repite y escribir sus reglas.'
    : 'Por número de páginas. Pulsa una fila para escribir sus reglas.';
}

// ---- Bloque «Google» del Resumen y del Estado del cliente ----
// Revision de UX del 25-oct, 3.3 (V46): tres cifras con la fecha de su
// ventana al lado, una frase que solo dice lo que se sabe y las paginas que
// mas cambian, una vez cada una. Funciones puras sobre `job` para probarlas
// en Chromium (tests/test_google_limpieza_frontend.py).

// «2026-10-06» como fecha local: `new Date('2026-10-06')` es medianoche UTC
// y en un navegador al oeste de Greenwich salia el dia anterior.
function diaIso(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null;
}

// «del 6 al 12 oct», «del 29 jul al 23 oct» o «del 28 dic de 2025 al 3 ene».
function rangoDias(desde, hasta) {
  const a = diaIso(desde), b = diaIso(hasta);
  if (!a || !b) return '';
  const hoy = new Date().getFullYear();
  const mes = d => d.toLocaleDateString('es-ES', { month: 'short' }).replace('.', '');
  const ano = d => d.getFullYear() !== hoy || a.getFullYear() !== b.getFullYear() ? ' de ' + d.getFullYear() : '';
  const fin = b.getDate() + ' ' + mes(b) + ano(b);
  if (a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear()) return 'del ' + a.getDate() + ' al ' + fin;
  return 'del ' + a.getDate() + ' ' + mes(a) + ano(a) + ' al ' + fin;
}

// La frase del trafico entre censos: si los clics suben o bajan, cuanto, y la
// ventana de cada cifra. Sin comparacion, o esperando a los datos, lo dice y
// no saca conclusiones de los 90 dias solos.
function conclusionTrafico(t) {
  if (!t) return [{ texto: 'Sin comparación con el censo anterior: estas cifras solas no dicen si el tráfico sube o baja.', nivel: 'dim' }];
  const va = t.ventana_anterior || [], vn = t.ventana_nueva || [];
  if (t.pendiente) {
    return [{ nivel: 'dim', texto: 'Todavía no se puede decir si los clics suben o bajan frente al censo anterior: '
      + 'la comparación de los clics ' + rangoDias(vn[0], vn[1]) + ' con los ' + rangoDias(va[0], va[1]) + ' espera a que Search Console tenga datos hasta el '
      + fmt.diaCorto(diaIso(vn[1])) + '.' }];
  }
  if (!t.comparable) return [{ texto: t.motivo || 'El tráfico no se pudo comparar con el censo anterior.', nivel: 'dim' }];
  const ant = fmt.num(t.clics_anterior) + ' clics ' + rangoDias(va[0], va[1]);
  const nue = fmt.num(t.clics_nuevo) + ' ' + rangoDias(vn[0], vn[1]);
  const dias = t.dias ? ' frente a los ' + t.dias + ' días anteriores' : ' frente al periodo anterior';
  const salida = [];
  if (t.variacion == null) {
    salida.push({ nivel: '', texto: 'Sin clics en el periodo anterior (' + rangoDias(va[0], va[1]) + '): no hay porcentaje que dar. Ahora, ' + nue + '.' });
  } else {
    const p = 100 * t.variacion;
    const verbo = Math.abs(p) < 1 ? 'Los clics se mantienen' : (p < 0 ? 'Los clics bajan un ' : 'Los clics suben un ') + fmt.pct(Math.abs(p), 0);
    salida.push({ nivel: t.general ? 'orange' : '',
      texto: verbo + dias + ': ' + fmt.num(t.clics_nuevo) + ' ' + rangoDias(vn[0], vn[1]) + ' frente a ' + ant + '.' });
  }
  // Que la caida es de todo el sitio o parece estacional lo dice la frase
  // siguiente del servidor (`textos`, con la cifra del año anterior): dicho
  // tambien aqui salia dos veces seguidas.
  return salida;
}

// Las paginas que mas cambian, una vez cada una con todo lo que cambio en
// ella: la misma pagina estaba en dos grupos y salia dos veces (V46). Solo
// las que el servidor da como ejemplo (hasta 5 por grupo): `cortadas` dice
// si hay mas.
function paginasTrafico(t, max = 10) {
  if (!t || !t.comparable) return { paginas: [], cortadas: false };
  const por = new Map();
  let cortadas = false;
  for (const g of [...(t.caidas || []), ...(t.subidas || [])]) {
    const ej = g.ejemplos || [];
    if ((g.paginas || 0) > ej.length) cortadas = true;
    for (const e of ej) {
      let p = por.get(e.url);
      if (!p) { p = { url: e.url, antes: e.clics_antes, despues: e.clics_despues, cambios: [] }; por.set(e.url, p); }
      if (g.texto && !p.cambios.includes(g.texto)) p.cambios.push(g.texto);
    }
  }
  const paginas = [...por.values()].sort((a, b) => Math.abs(b.despues - b.antes) - Math.abs(a.despues - a.antes) || a.url.localeCompare(b.url));
  return { paginas: paginas.slice(0, max), cortadas: cortadas || paginas.length > max };
}

// «/es/hoteles/» de «https://www.lopesan.com/es/hoteles/»: lo que se lee
// en una frase; la URL entera va en el title.
function rutaCorta(url) {
  try { const u = new URL(url); return (u.pathname + u.search) || url; } catch (_) { return url; }
}

// Las paginas de una frase del trafico (revision de UX del 25-oct, 3.3): las
// frases las escribe el servidor (`shared.trafico_entre_censos.textos`) sin
// sus URLs; aqui se busca el grupo del que sale cada una por lo que la frase
// dice (el cambio que cita, o el caso especial, el sentido y el numero de
// paginas). Solo si sale UN grupo: si dos encajan, la frase va sin enlaces
// (no se adivina). Devuelve sus ejemplos, que son paginas de verdad.
function paginasDeFraseTrafico(texto, t) {
  if (!t || !t.comparable || !texto) return [];
  const m = /^(\d[\d.]*) p[aá]ginas? /.exec(texto);
  if (!m) return [];
  const n = Number(m[1].replace(/\./g, ''));
  const sube = /\s(ganó|ganaron)\s/.test(texto);
  const grupos = sube ? (t.subidas || []) : (t.caidas || []);
  const especial = /que pasan a su canonical/.test(texto) ? 'trasvase'
    : /sin cambio técnico/.test(texto) ? 'sin_cambio'
    : /en el rastreo anterior: no hay con qué comparar/.test(texto) ? 'sin_dato_anterior' : null;
  const candidatos = grupos.filter(g => (g.paginas || 0) === n && (especial
    ? g.cambio === especial
    : g.texto && !['trasvase', 'sin_cambio', 'sin_dato_anterior'].includes(g.cambio) && texto.includes(g.texto)));
  if (candidatos.length !== 1) return [];
  return (candidatos[0].ejemplos || []).map(e => e.url).filter(Boolean).slice(0, 3);
}

// La autoridad que entra de fuera (#31, decision 212), de
// `jobs.pagerank_resumen.externo`. null sin backlinks subidos. El reparto es
// de lo que llega DESDE FUERA (lo casado): donde cae de entrada.
function bloqueBacklinks(job) {
  const e = job && job.pagerank_resumen && job.pagerank_resumen.externo;
  if (!e) return null;
  const pct = x => fmt.pct(100 * (x || 0), 0);
  const entra = e.entra_en || {};
  const frases = [];
  frases.push(fmt.num(e.casados) + ' de ' + fmt.num(e.backlinks) + ' backlinks (' + pct(e.parte_casada) + ') llegan a ' + fmt.num(e.paginas_con_backlinks)
    + (e.paginas_con_backlinks === 1 ? ' página de este rastreo.' : ' páginas de este rastreo.'));
  const perdida = (entra.error || 0) + (entra.sin_respuesta || 0);
  if (perdida > 0) frases.push(pct(perdida) + ' de la autoridad que entra de fuera cae en páginas con error o sin respuesta: se pierde.');
  if ((entra.no_indexable || 0) > 0) frases.push(pct(entra.no_indexable) + ' cae en páginas no indexables (noindex o canonicalizadas).');
  if ((entra.redireccion || 0) > 0) frases.push(pct(entra.redireccion) + ' llega a redirecciones, que la pasan a su destino.');
  return {
    fuente: (FUENTE_BACKLINKS[e.fuente] || e.fuente),
    fecha: e.fecha_dato || e.subido,
    frases,
    // Por debajo del 90 % el cruce falla (otro dominio, URLs muy viejas) o el
    // rastreo no cubre lo que tiene enlaces (criterio de #31).
    poco_casado: e.parte_casada != null && e.parte_casada < 0.9,
    no_rastreadas: e.no_rastreadas || [],
    beta: e.beta,
  };
}

// Los campos del estado que vio Jev, para la revision (#8): el texto tal
// cual y lo demas (listas, objetos) en JSON legible.
function camposDeEstado(estado) {
  if (!estado || typeof estado !== 'object') return [];
  return Object.entries(estado).map(([k, v]) => ({
    clave: k,
    valor: typeof v === 'string' ? v : JSON.stringify(v, null, 1),
    largo: typeof v !== 'string' || v.length > 160,
  }));
}

// Lo que lee la plantilla mientras el x-if que la envuelve aun no ha
// reaccionado a un job que pasa a null.
const BLOQUE_GOOGLE_VACIO = Object.freeze({ cifras: [], conclusiones: [], inspeccion: null, textos: [], paginas: [], cortadas: false, trafico: null, limites: [] });

// Lo que Search Console no cuenta, dicho junto a sus cifras (#163,
// `docs/INVESTIGACION_SEARCH_CONSOLE.md`). Dos avisos siempre (la API no
// separa la IA y calla las busquedas raras, con la parte MEDIDA en el sitio
// cuando hay serie de busquedas) y dos solo si la ventana cruza las fechas
// en que Google cambio lo que cuenta: impresiones infladas del 13-05-2025 al
// 27-04-2026 y el fin de `num=100` en septiembre de 2025.
function textoSinBusqueda(sb) {
  if (!sb || !sb.clics_paginas) return 'Google anonimiza las búsquedas raras o sensibles (en muchos sitios, entre el 40 y el 50 % de los clics): las cifras por búsqueda nunca suman el total.';
  const dias = 'del ' + fmt.dia(sb.desde) + ' al ' + fmt.dia(sb.hasta);
  if (sb.parte < 0.01) return 'Casi todos los clics ' + dias + ' llegan con su búsqueda: aquí las cifras por búsqueda cuadran con el total.';
  return 'El ' + fmt.pct(100 * sb.parte, 0) + ' de los clics ' + dias + ' llega sin su búsqueda'
    + (sb.con_dias_cortados
      ? '. La cifra mezcla dos cosas: las búsquedas que Google anonimiza (las raras o sensibles) y los días en que la descarga de búsquedas se cortó en su tope de 50.000 filas.'
      : ': Google anonimiza las búsquedas raras o sensibles.')
    + ' Por eso las cifras por búsqueda (canibalización, CTR por búsqueda) no suman el total.';
}
const GSC_INFLADAS = ['2025-05-13', '2026-04-27'];
const GSC_NUM100 = ['2025-09-01', '2025-09-30'];
function limitesGoogle(g) {
  if (!g) return [];
  const desde = g.datos_desde || g.desde, hasta = g.datos_hasta || g.hasta;
  const cruza = ([a, b]) => !!(desde && hasta && desde <= b && hasta >= a);
  const sb = g.oportunidades && g.oportunidades.sin_busqueda;
  const salida = [
    'La API de Search Console no separa los clics que vienen de AI Overviews ni de AI Mode (AI Mode cuenta dentro de Web): estas cifras no dicen qué parte llega desde las respuestas de IA.',
    textoSinBusqueda(sb),
  ];
  if (cruza(GSC_INFLADAS)) salida.push('Las impresiones del 13 de mayo de 2025 al 27 de abril de 2026 están infladas por un error de Google que no corrigió el histórico: no compares impresiones ni CTR a través de esas fechas.');
  if (cruza(GSC_NUM100)) salida.push('En septiembre de 2025 Google dejó de servir 100 resultados por página (num=100): cayeron las impresiones de escritorio y subió la posición media sin que el sitio cambiara.');
  return salida;
}

// Todo el bloque. null si el job no trae ni Search Console ni trafico entre
// censos (sin GSC conectado no se pinta nada).
function bloqueGoogle(job) {
  const g = job && job.gsc_resumen;
  const t = job && job.comparacion && job.comparacion.trafico;
  if (!g && !t) return null;
  const cifras = [];
  if (g) {
    // La ventana de la cifra es la de los DATOS: el 26-oct la ventana llegaba
    // al 26 y los datos al 23.
    const hasta = g.datos_hasta && g.hasta && g.datos_hasta < g.hasta ? g.datos_hasta : g.hasta;
    const desde = g.datos_desde && g.desde && g.datos_desde > g.desde ? g.datos_desde : g.desde;
    const ventana = rangoDias(desde, hasta);
    cifras.push({ etiqueta: 'Clics', valor: fmt.num(g.clics), ventana });
    cifras.push({ etiqueta: 'Impresiones', valor: fmt.num(g.impresiones), ventana });
    cifras.push({ etiqueta: 'CTR medio', valor: g.impresiones ? fmt.pct(100 * g.clics / g.impresiones) : '—', ventana });
  }
  const ins = g && g.inspeccion;
  const inspeccion = ins && ins.inspeccionadas
    ? 'De las ' + fmt.num(ins.inspeccionadas) + ' URLs inspeccionadas, Google dice que ' + fmt.num(ins.indexadas || 0)
      + ' están indexadas' + (ins.no_indexadas ? ' y ' + fmt.num(ins.no_indexadas) + ' no' : '') + '.'
    : null;
  // La primera frase del servidor son los totales, que ya dice la conclusion.
  const textos = t && t.comparable ? (t.textos || []).slice(1) : [];
  return { cifras, conclusiones: conclusionTrafico(t), inspeccion, textos, ...paginasTrafico(t), trafico: t || null, limites: limitesGoogle(g) };
}

// `jobs.sitemaps` (decision 126), solo en la ficha del job.
function resumenSitemaps(job) {
  const s = job && job.sitemaps;
  if (!s || typeof s !== 'object') return null;
  const ficheros = Array.isArray(s.ficheros) ? s.ficheros : [];
  const formatos = {};
  let declaradas = 0, devueltas = 0, cortados = 0, fallidos = 0;
  // Revision de UX del 25-oct, 3.6 (V13): «64 entradas de 459 declaradas»
  // sumaba los 395 ficheros hijos de un indice como si fueran URLs, y «396 de
  // 396 leidos» callaba que 370 respondieron 200 vacios. Lo que se lee de un
  // indice son ficheros; las URLs, de los urlset; y un fichero que responde
  // 200 sin un sitemap reconocible es un fichero del que no se sabe nada.
  let urls = 0, conUrls = 0, indices = 0, hijos = 0, ilegibles = 0, vacios = 0;
  for (const f of ficheros) {
    if (!f) continue;
    if (f.formato) formatos[f.formato] = (formatos[f.formato] || 0) + 1;
    declaradas += Number(f.declaradas) || 0;
    devueltas += Number(f.devueltas) || 0;
    if (f.cortado) cortados++;
    if (f.status != null && f.status !== 200) fallidos++;
    if (f.formato === 'sitemapindex') { indices++; hijos += Number(f.hijos) || 0; }
    else if (f.formato && f.formato !== 'desconocido') {
      urls += Number(f.devueltas) || 0;
      if (Number(f.devueltas)) conUrls++;
    } else if (f.status === 200) {
      ilegibles++;
      if (f.bytes === 0) vacios++;
    }
  }
  const leidos = s.leidos == null ? ficheros.length : s.leidos;
  return {
    ficheros, pedidos: s.pedidos == null ? ficheros.length : s.pedidos,
    leidos,
    parcial: !!s.parcial, recortadas: !!s.entradas_recortadas,
    tope: s.tope_entradas || null, guardadas: s.entradas_guardadas,
    formatos: Object.entries(formatos), declaradas, devueltas, cortados, fallidos,
    urls, conUrls, indices, hijos, ilegibles, vacios,
    // Con algun fichero que no se pudo leer (parcial, no 200 o ilegible),
    // «No incluida en el sitemap» no se puede afirmar: la pagina puede estar
    // en el fichero que falta. Es presentacion: el analisis no cambia.
    dudoso: !!s.parcial || fallidos > 0 || ilegibles > 0,
  };
}

// Alertas del cliente agrupadas en pantalla (revision de UX del 25-oct, 1.12;
// V08; decision 204): la misma regla vista por dos series o en dos censos
// salia en dos filas iguales («Páginas que ya no se encuentran» del 19 y del
// 21 oct). Un grupo por `clave` con todas sus alertas, la gravedad mas alta y
// la mas reciente para el titular. No cambia nada guardado: cada alerta sigue
// siendo suya (decision 139) y las acciones se aplican a todas las del grupo.
const ORDEN_SEV_ALERTA = { critical: 0, warning: 1, info: 2 };
function agruparIncidentes(lista) {
  const por = new Map();
  for (const i of lista || []) {
    const k = i.clave || i.regla || i.id;
    if (!por.has(k)) por.set(k, { clave: k, items: [] });
    por.get(k).items.push(i);
  }
  const t = x => new Date(x.abierto_en || 0).getTime();
  const grupos = [...por.values()].map(g => {
    g.items.sort((a, b) => t(a) - t(b));
    g.ultimo = g.items[g.items.length - 1];
    g.severidad = g.items.reduce((m, x) => ((ORDEN_SEV_ALERTA[x.severidad] ?? 3) < (ORDEN_SEV_ALERTA[m] ?? 3) ? x.severidad : m), g.ultimo.severidad);
    g.estados = [...new Set(g.items.map(x => x.estado))];
    g.series = [...new Set(g.items.map(x => x.nombre_serie || x.serie).filter(Boolean))];
    return g;
  });
  return grupos.sort((a, b) => (ORDEN_SEV_ALERTA[a.severidad] ?? 3) - (ORDEN_SEV_ALERTA[b.severidad] ?? 3) || t(b.ultimo) - t(a.ultimo));
}

// Una fila por tipo en Problemas y en el desplegable de URLs (revision de UX
// del 25-oct, 1.7; V14; decision 202). La API da una fila por tipo y
// gravedad, y «Canibalizacion» salia dos veces (39 aviso, 157 info): se
// juntan en una con su gravedad mas alta y el desglose en `partes`. Las
// paginas del tipo son `paginas_tipo` (distintas, de la API) solo si estan
// todas sus gravedades; si no (se quitaron las info, o la API es anterior y
// no lo trae) son null: sumar las de cada gravedad contaria dos veces la
// pagina que tenga las dos, y eso no se afirma. `todas` son las filas de la
// API sin filtrar, para saber si estan todas las gravedades.
const ORDEN_GRAVEDAD = { error: 0, warning: 1, info: 2 };
function filasPorTipo(filas, todas) {
  const por = new Map();
  const salida = [];
  for (const r of filas || []) {
    const g = por.get(r.issue_type);
    if (g) { g.partes.push(r); continue; }
    const nueva = { ...r, partes: [r] };
    por.set(r.issue_type, nueva);
    salida.push(nueva);
  }
  const deTodas = {};
  for (const r of (todas || filas || [])) deTodas[r.issue_type] = (deTodas[r.issue_type] || 0) + 1;
  for (const g of salida) {
    if (g.partes.length < 2) continue;
    const partes = [...g.partes].sort((a, b) => (ORDEN_GRAVEDAD[a.severity] ?? 3) - (ORDEN_GRAVEDAD[b.severity] ?? 3));
    const suma = k => partes.reduce((n, p) => n + (p[k] || 0), 0);
    const ejemplos = [];
    const vistos = new Set();
    for (const p of partes) for (const e of (p.ejemplos || [])) {
      if (vistos.has(e.url_id)) continue;
      vistos.add(e.url_id);
      ejemplos.push(e);
    }
    Object.assign(g, {
      partes,
      severity: partes[0].severity,
      incidencias: suma('incidencias'),
      agregadas: suma('agregadas') || null,
      paginas: g.paginas_tipo != null && deTodas[g.issue_type] === partes.length ? g.paginas_tipo : null,
      ejemplos: ejemplos.slice(0, Math.max(3, (partes[0].ejemplos || []).length)),
      prioridad: Math.max(...partes.map(p => p.prioridad || 0)),
      importancia: Math.max(...partes.map(p => p.importancia || 0)),
      // El % y el reparto por segmento son de cada gravedad: el de la mas
      // alta, y la fila lo dice (no se suman).
      pct_paginas: null,
      por_segmento: partes[0].por_segmento,
    });
  }
  return salida;
}
// «39 aviso · 157 info»: el desglose de una fila con varias gravedades.
function desgloseGravedad(r) {
  return (r.partes || [r]).map(p => fmt.num(p.paginas) + ' ' + fmt.severity(p.severity).toLowerCase()).join(' · ');
}
const _cacheFilasTipo = new WeakMap();
// El objeto sin el proxy de Alpine (para guardar cosas por identidad); sin
// Alpine cargado (los tests que ejecutan app.js sueltos), el mismo.
function _crudo(x) { return (typeof Alpine !== 'undefined' && Alpine.raw) ? Alpine.raw(x) : x; }

// La frase que matiza «No incluida en el sitemap» cuando la lectura de los
// sitemaps no fue completa (revision de UX del 25-oct, 3.6; V13). null si se
// leyo todo: entonces el aviso se puede afirmar.
// Los totales de `comparacion.incidencias` (nuevas, resueltas, siguen) sin
// «No incluida en el sitemap» cuando `dudoso` (decision 205): lo mismo que
// shared/sitemaps_lectura.sin_tipos_de_sitemap del informe y de Slack.
const TIPOS_DE_SITEMAP = ['not_in_sitemap'];
const TEXTO_SIN_SITEMAP = 'Sin contar «No incluida en el sitemap»: no se leyeron todos los sitemaps y su diferencia no se puede afirmar.';
function incidenciasAfirmables(inc, dudoso) {
  if (!inc) return null;
  const r = { sinSitemap: false };
  for (const campo of ['nuevas', 'resueltas', 'siguen']) {
    const b = inc[campo];
    if (!b || typeof b !== 'object') { r[campo] = null; continue; }
    const quitar = dudoso ? (b.por_tipo || []).filter(f => f && TIPOS_DE_SITEMAP.includes(f.tipo))
      .reduce((n, f) => n + (Number(f.total) || 0), 0) : 0;
    if (quitar) r.sinSitemap = true;
    r[campo] = b.total == null ? null : b.total - quitar;
  }
  return r;
}

function dudaSitemaps(job) {
  const sm = resumenSitemaps(job);
  if (!sm || !sm.dudoso) return null;
  const de = ' de los ' + fmt.num(sm.pedidos) + ' ficheros de sitemap ';
  const partes = [];
  if (sm.ilegibles) partes.push(fmt.num(sm.ilegibles) + (partes.length ? ' ' : de)
    + (sm.ilegibles === 1 ? 'respondió 200 ' : 'respondieron 200 ')
    + (sm.vacios === sm.ilegibles ? (sm.ilegibles === 1 ? 'vacío' : 'vacíos') : 'sin un sitemap que se pueda leer'));
  if (sm.fallidos) partes.push(fmt.num(sm.fallidos) + (partes.length ? ' ' : de)
    + (sm.fallidos === 1 ? 'no respondió 200' : 'no respondieron 200'));
  const lead = partes.length ? partes.join(' y ') : 'La lectura de los sitemaps fue parcial';
  return lead + ': una página «no incluida» puede estar en ellos, así que no se puede afirmar que falte.';
}

// ---- WordPress por su REST API (decisiones 161 y 168) ----
// La tarjeta del Resumen, la casilla del modal, «Solo en WordPress» del
// Explorador y la entidad en la ficha de la URL. Funciones puras sobre `job`
// para probarlas en Chromium (tests/test_wordpress_frontend.py).
const WP_REST_TEXTO = {
  abierta: ['abierta', 'green'],
  cerrada: ['cerrada', 'orange'],
  limitada: ['limitada (429 o 503): no se sabe si está abierta', 'orange'],
  bloqueada_por_robots: ['prohibida por robots.txt: no se leyó', 'orange'],
  raiz_fuera_del_sitio: ['anunciada fuera del sitio: no se leyó', 'orange'],
};
const WP_CLASE_TEXTO = { entrada: 'Contenido', termino: 'Taxonomía', medio: 'Medios' };
const WP_ORDEN_CLASE = { entrada: 0, termino: 1, medio: 2 };
const WP_TIPO_TEXTO = {
  post: 'Entrada', page: 'Página', attachment: 'Adjunto', category: 'Categoría',
  post_tag: 'Etiqueta', product: 'Producto', product_cat: 'Categoría de producto',
  product_tag: 'Etiqueta de producto',
};
// Namespaces del núcleo de WordPress: no dicen nada de los plugins.
const WP_NS_NUCLEO = new Set(['wp', 'oembed', 'wp-site-health', 'wp-block-editor', 'wp-abilities', 'batch']);

function tipoWp(tipo) {
  return WP_TIPO_TEXTO[tipo] || tipo || '—';
}

// Decision 174: nombre y color del impacto de axe en la tarjeta.
const IMPACTO_AXE = {
  critical: ['Crítico', 'red'], serious: ['Grave', 'orange'],
  moderate: ['Moderado', ''], minor: ['Leve', 'text-dim'],
};

function impactoAxe(impacto) {
  return IMPACTO_AXE[impacto] || ['—', 'text-dim'];
}

// null si el job no trae el resumen del adaptador (rastreo anterior o con el
// adaptador apagado) o si no hubo ni rastro de WordPress: entonces la tarjeta
// no sale, y «no sale» no quiere decir «no es WordPress» en un rastreo viejo.
function resumenWordPress(job) {
  const wp = job && job.adapters && job.adapters.wordpress;
  if (!wp || typeof wp !== 'object') return null;
  const evidencia = Array.isArray(wp.evidencia) ? wp.evidencia : [];
  if (!wp.detectado && !evidencia.length) return null;
  const analisis = wp.analisis && typeof wp.analisis === 'object' ? wp.analisis : null;
  const porTipo = (analisis && analisis.por_tipo && typeof analisis.por_tipo === 'object') ? analisis.por_tipo : {};
  const tipos = (wp.tipos && typeof wp.tipos === 'object') ? wp.tipos : {};
  const filas = [...new Set([...Object.keys(tipos), ...Object.keys(porTipo)])].map(t => {
    const d = tipos[t] || {};
    const a = porTipo[t] || null;
    const leidas = a ? Number(a.leidas) || 0 : (d.leidas ?? null);
    const enCenso = a ? Number(a.en_el_censo) || 0 : null;
    return {
      tipo: t, nombre: tipoWp(t), clase: d.clase || null, clase_texto: WP_CLASE_TEXTO[d.clase] || '—',
      publicadas: d.total ?? null, leidas, en_el_censo: enCenso,
      solo_wp: enCenso == null || leidas == null ? null : Math.max(0, leidas - enCenso),
      recortado: !!d.recortado, status: d.status ?? null,
    };
  }).sort((x, y) => ((WP_ORDEN_CLASE[x.clase] ?? 3) - (WP_ORDEN_CLASE[y.clase] ?? 3))
    || ((y.publicadas ?? y.leidas ?? 0) - (x.publicadas ?? x.leidas ?? 0)) || x.tipo.localeCompare(y.tipo));
  const [restTexto, restNivel] = WP_REST_TEXTO[wp.rest] || [wp.rest ? String(wp.rest) : 'sin confirmar', 'orange'];
  // Un plugin que registra rutas en la REST API lo hace con su namespace
  // (`yoast/v1`, `wc/store/v1`): el primer tramo, sin repetir. No todos los
  // plugins registran rutas, así que no es la lista entera.
  const namespaces = [...new Set((Array.isArray(wp.namespaces) ? wp.namespaces : [])
    .filter(n => typeof n === 'string').map(n => n.split('/')[0]).filter(n => n && !WP_NS_NUCLEO.has(n)))];
  const nr = analisis && analisis.wp_publicado_no_rastreado && typeof analisis.wp_publicado_no_rastreado === 'object'
    ? analisis.wp_publicado_no_rastreado : null;
  return {
    version: wp.version || null, plugin_seo: wp.plugin_seo || null,
    nombre: wp.nombre || null, raiz: wp.raiz || null,
    detectado: !!wp.detectado, evidencia, rest: wp.rest || null,
    rest_texto: restTexto + (wp.codigo && wp.rest && wp.rest !== 'abierta' ? ` (${wp.codigo})` : ''),
    rest_nivel: restNivel, abierta: wp.rest === 'abierta',
    cortada: wp.cortada || null, peticiones: wp.peticiones ?? null,
    reanudacion: wp.reanudacion || null,
    analizado: !!analisis, filas, namespaces,
    no_rastreadas: nr ? (Number(nr.no_rastreadas) || 0) : null,
    no_afirmable: nr ? (nr.no_afirmable || null) : null,
    sin_afirmar: nr ? (Number(nr.sin_afirmar) || 0) : null,
    emitidos: nr ? (Number(nr.emitidos) || 0) : null,
  };
}

// La entidad de WordPress de la ficha de una URL, en una línea.
function textoEntidadWp(w) {
  if (!w) return '';
  const partes = [tipoWp(w.tipo), 'ID ' + (w.id ?? '—')];
  if (w.estado && w.estado !== 'publish' && w.estado !== 'inherit') partes.push(w.estado);
  if (w.cuenta != null) partes.push(w.cuenta + (w.cuenta === 1 ? ' entrada' : ' entradas'));
  if (w.modificado) partes.push('modificada ' + String(w.modificado).slice(0, 10));
  return partes.join(' · ');
}

// El veredicto del modo lista con sus textos (decision 128).
const VEREDICTO_TEXTO = {
  pasa: ['La lista pasa', 'green'],
  aviso: ['La lista pasa con avisos', 'blue'],
  falla: ['La lista falla', 'red'],
  no_concluyente: ['No concluyente', 'orange'],
};

// El formulario de Nuevo rastreo: lo que no es configuracion. La
// configuracion va en `cfgRastreo`, el mismo formulario que el del cliente y
// el del perfil (decision 196; revision de UX del 25-oct, 2.4).
function _freshForm() {
  return {
    name: '',
    seeds: '',
    cliente_id: '',
    profile_id: '',
    tipo: '',            // '' = el de serie (tipoRastreoModal); decision 203
    extraccion: [],      // reglas a medida (decision 166): ver _extraccionAConfig
  };
}

// ---------------------------------------------------------------------------
// Configuracion en tres niveles (decision 196; revision de UX del 25-oct, 2.4)
// ---------------------------------------------------------------------------
// El MISMO formulario para el cliente, el perfil y el rastreo. Cada nivel
// guarda solo lo que fija (`propia`); lo de arriba (`base`, ya resuelto por la
// API con `origen`) se ve con su procedencia: «del cliente», «del perfil» o
// «de serie». Escribir lo mismo que lo heredado no lo fija en este nivel: asi
// un cambio del cliente sigue llegando al perfil. Los limites son los de
// `JobConfig` (api/schemas.py), comprobados por `tests/test_config_niveles_frontend.py`.
const GRUPOS_CONFIG = [
  ['principal', 'Lo principal'],
  ['alcance', 'Qué se rastrea'],
  ['ritmo', 'Ritmo, tiempos e identidad'],
  ['sondas', 'Comprobaciones extra (fuera del censo)'],
  ['contenido', 'Qué se guarda de cada página'],
  ['http', 'Cabeceras, cookies y acceso'],
  ['umbrales', 'Umbrales del análisis'],
];

// Huellas TLS de curl_cffi que se ofrecen (decision 132); las comprueba
// `tests/test_huella_y_ua.py` contra las que tiene el curl_cffi instalado.
const HUELLAS_TLS = [
  ['chrome150', 'Chrome 150'],
  ['chrome124', 'Chrome 124 (la de serie hasta octubre de 2026)'],
  ['firefox147', 'Firefox 147'],
  ['safari260', 'Safari 26'],
  ['chrome131_android', 'Chrome 131 Android'],
  ['edge101', 'Edge 101'],
];

const SI_NO = 'si_no';
const CAMPOS_CONFIG = [
  // --- Lo principal: lo que mas se cambia, siempre a la vista
  { ruta: 'max_urls', grupo: 'principal', etiqueta: 'Máximo de URLs', tipo: 'entero', min: 1, max: 5000000,
    nulo: 'Sin tope', ayuda: 'Vacío = sin tope: rastrea hasta agotar el sitio. Con tope, el censo queda truncado si no cabe.' },
  { ruta: 'max_depth', grupo: 'principal', etiqueta: 'Profundidad (clics desde las semillas)', tipo: 'entero', min: 0, max: 1000,
    ayuda: '0 = modo lista: solo las semillas, sin seguir enlaces ni leer el sitemap.' },
  { ruta: 'concurrent_requests_per_domain', grupo: 'principal', etiqueta: 'Peticiones a la vez por dominio', tipo: 'entero', min: 1, max: 64,
    ayuda: 'Lo que más nota el sitio. Bájalo si un WAF bloquea.' },
  { ruta: 'concurrent_requests', grupo: 'principal', etiqueta: 'Peticiones a la vez en total', tipo: 'entero', min: 1, max: 256 },
  { ruta: 'render_js', grupo: 'principal', etiqueta: 'Renderizar JavaScript', tipo: SI_NO,
    ayuda: 'Abre cada página en un navegador: ve lo que monta el JavaScript, pero es varias veces más lento.' },
  { ruta: 'robots_mode', grupo: 'principal', etiqueta: 'robots.txt', tipo: 'opciones',
    opciones: [['respect', 'Respetarlo'], ['audit', 'No respetarlo, pero anotar lo que bloquearía'], ['ignore', 'No leerlo']] },
  { ruta: 'user_agent', grupo: 'principal', etiqueta: 'Se presenta como', tipo: 'ua' },
  { ruta: 'exclude_patterns', grupo: 'principal', etiqueta: 'No rastrear las URLs que casen con', tipo: 'lineas',
    ejemplo: '/carrito/\n\\?orden=', ayuda: 'Una expresión por línea, sobre la URL entera.' },

  // --- Que se rastrea
  { ruta: 'include_patterns', grupo: 'alcance', etiqueta: 'Rastrear solo las URLs que casen con', tipo: 'lineas',
    ejemplo: '/blog/', ayuda: 'Vacío = todas. Una expresión por línea.' },
  { ruta: 'use_sitemap', grupo: 'alcance', etiqueta: 'Leer el sitemap', tipo: SI_NO,
    ayuda: 'Siembra las URLs del sitemap y permite ver huérfanas y páginas que faltan en él.' },
  { ruta: 'sitemap_urls', grupo: 'alcance', etiqueta: 'Sitemaps además de los de robots.txt', tipo: 'lineas',
    ejemplo: 'https://www.cliente.com/sitemap_index.xml' },
  { ruta: 'follow_external', grupo: 'alcance', etiqueta: 'Seguir enlaces a otros sitios', tipo: SI_NO },
  { ruta: 'crawl_behavior.crawl_subdomains', grupo: 'alcance', etiqueta: 'Rastrear subdominios', tipo: SI_NO },
  { ruta: 'crawl_behavior.follow_nofollow', grupo: 'alcance', etiqueta: 'Seguir enlaces nofollow', tipo: SI_NO },
  { ruta: 'topes_por_carpeta', grupo: 'alcance', etiqueta: 'Topes por carpeta o subdominio', tipo: 'topes',
    ejemplo: '/blog/ = 500\n* = 300',
    ayuda: 'Una línea por regla: «regla = tope». «*» = cada carpeta de primer nivel; «blog.cliente.com/*» = el host entero.' },
  { ruta: 'url_filters.max_url_length', grupo: 'alcance', etiqueta: 'Longitud máxima de URL (0 = sin límite)', tipo: 'entero', min: 0, max: 10000 },
  { ruta: 'url_filters.max_folder_depth', grupo: 'alcance', etiqueta: 'Carpetas como mucho (0 = sin límite)', tipo: 'entero', min: 0, max: 100 },
  { ruta: 'resource_types.crawl_images', grupo: 'alcance', etiqueta: 'Pedir imágenes', tipo: SI_NO },
  { ruta: 'resource_types.crawl_css', grupo: 'alcance', etiqueta: 'Pedir CSS', tipo: SI_NO },
  { ruta: 'resource_types.crawl_js', grupo: 'alcance', etiqueta: 'Pedir JavaScript', tipo: SI_NO },
  { ruta: 'resource_types.crawl_pdfs', grupo: 'alcance', etiqueta: 'Pedir PDF', tipo: SI_NO },
  { ruta: 'resource_types.crawl_fonts', grupo: 'alcance', etiqueta: 'Pedir fuentes', tipo: SI_NO },
  { ruta: 'resource_types.crawl_svg', grupo: 'alcance', etiqueta: 'Pedir SVG', tipo: SI_NO },
  { ruta: 'resource_types.crawl_other', grupo: 'alcance', etiqueta: 'Pedir otros ficheros', tipo: SI_NO },

  // --- Ritmo, tiempos e identidad
  { ruta: 'crawl_behavior.request_delay', grupo: 'ritmo', etiqueta: 'Pausa entre peticiones (segundos)', tipo: 'decimal', min: 0, max: 30 },
  { ruta: 'crawl_behavior.autothrottle_enabled', grupo: 'ritmo', etiqueta: 'Ajustar el ritmo solo (según lo que tarda el sitio)', tipo: SI_NO },
  { ruta: 'crawl_behavior.autothrottle_target_concurrency', grupo: 'ritmo', etiqueta: 'Peticiones a la vez que busca el ajuste', tipo: 'decimal', min: 1, max: 100 },
  { ruta: 'crawl_behavior.download_timeout', grupo: 'ritmo', etiqueta: 'Espera máxima por página (segundos)', tipo: 'entero', min: 5, max: 120 },
  { ruta: 'crawl_behavior.retry_count', grupo: 'ritmo', etiqueta: 'Reintentos', tipo: 'entero', min: 0, max: 10 },
  { ruta: 'crawl_behavior.render_wait_ms', grupo: 'ritmo', etiqueta: 'Espera tras cargar con render (ms)', tipo: 'entero', min: 0, max: 60000,
    nulo: 'La del servidor', ayuda: 'Vacío = la del servidor (2.000 ms).' },
  { ruta: 'crawl_behavior.max_runtime_hours', grupo: 'ritmo', etiqueta: 'Duración máxima (horas)', tipo: 'entero', min: 1, max: 720 },
  { ruta: 'crawl_behavior.stall_timeout_minutes', grupo: 'ritmo', etiqueta: 'Darlo por atascado tras (minutos sin avanzar; 0 = nunca)', tipo: 'entero', min: 0, max: 1440 },
  { ruta: 'crawl_behavior.parar_si_bloqueado', grupo: 'ritmo', etiqueta: 'Pararse si el sitio lo bloquea', tipo: SI_NO },
  { ruta: 'crawl_behavior.respetar_retry_after', grupo: 'ritmo', etiqueta: 'Esperar lo que pida el sitio con un 429 o un 503', tipo: SI_NO },
  // Rastreo incremental (decision 220): solo lo leen los programados de un perfil.
  { ruta: 'incremental.activo', grupo: 'ritmo', etiqueta: 'Rastreo incremental en los programados', tipo: SI_NO,
    ayuda: 'Cada ciclo pide solo lo que toca (lo que cambia a menudo, lo nuevo, portadas y hubs, y una muestra al azar) y copia el resto del censo anterior. Un rastreo puntual lo ignora.' },
  { ruta: 'incremental.completo_cada', grupo: 'ritmo', etiqueta: 'Un rastreo completo cada (ciclos)', tipo: 'entero', min: 1, max: 52,
    ayuda: 'El completo es el único que confirma que una página ha desaparecido. También sale completo si cambia la configuración, las semillas o el robots.txt.' },
  { ruta: 'incremental.muestra_control', grupo: 'ritmo', etiqueta: 'Muestra al azar de lo que no toca (0-1)', tipo: 'decimal', min: 0, max: 1,
    ayuda: 'Si en la muestra cambia más del 20 %, el ciclo siguiente es completo.' },
  { ruta: 'retencion.activo', grupo: 'ritmo', etiqueta: 'Vaciar los rastreos viejos del perfil', tipo: SI_NO,
    ayuda: 'Al acabar cada rastreo, los más antiguos que los últimos completados se vacían: se borran sus URLs, enlaces e incidencias y se queda su punto en la evolución.' },
  { ruta: 'retencion.conservar', grupo: 'ritmo', etiqueta: 'Rastreos completados que se conservan enteros', tipo: 'entero', min: 2, max: 200,
    ayuda: 'Con los semanales, 8 son dos meses.' },
  { ruta: 'impersonate', grupo: 'ritmo', etiqueta: 'Huella TLS', tipo: 'huella',
    ayuda: 'Va con el navegador con el que se presenta. Lo normal es dejarla automática.' },

  // --- Comprobaciones extra (sondas): fuera del censo y de max_urls
  { ruta: 'crawl_behavior.comprobar_enlaces_externos', grupo: 'sondas', etiqueta: 'Comprobar los enlaces a otros sitios', tipo: SI_NO },
  { ruta: 'crawl_behavior.enlaces_externos_max', grupo: 'sondas', etiqueta: 'Enlaces externos: como mucho', tipo: 'entero', min: 0, max: 100000 },
  { ruta: 'crawl_behavior.comprobar_recursos', grupo: 'sondas', etiqueta: 'Comprobar imágenes, CSS y JS del sitio', tipo: SI_NO },
  { ruta: 'resource_types.check_external_resources', grupo: 'sondas', etiqueta: 'Comprobar también los de otros sitios (un CDN)', tipo: SI_NO },
  { ruta: 'crawl_behavior.recursos_max', grupo: 'sondas', etiqueta: 'Recursos: como mucho', tipo: 'entero', min: 0, max: 500000 },
  { ruta: 'crawl_behavior.sondas_por_host', grupo: 'sondas', etiqueta: 'Por sitio externo, como mucho (0 = sin tope)', tipo: 'entero', min: 0, max: 10000 },
  { ruta: 'crawl_behavior.og_image_muestra', grupo: 'sondas', etiqueta: 'og:image que se miden (0 = no)', tipo: 'entero', min: 0, max: 5000 },
  { ruta: 'crawl_behavior.axe_muestra', grupo: 'sondas', etiqueta: 'Accesibilidad: páginas que se pasan por axe (0 = no)', tipo: 'entero', min: 0, max: 500 },
  { ruta: 'crawl_behavior.axe_por_plantilla', grupo: 'sondas', etiqueta: 'Accesibilidad: por plantilla', tipo: 'entero', min: 1, max: 20 },
  { ruta: 'crawl_behavior.paridad_movil_muestra', grupo: 'sondas', etiqueta: 'Móvil frente a escritorio: páginas (0 = no)', tipo: 'entero', min: 0, max: 500 },
  { ruta: 'crawl_behavior.paridad_movil_por_plantilla', grupo: 'sondas', etiqueta: 'Móvil frente a escritorio: por plantilla', tipo: 'entero', min: 1, max: 50 },
  { ruta: 'crawl_behavior.paridad_movil_ua', grupo: 'sondas', etiqueta: 'Móvil frente a escritorio: como', tipo: 'opciones',
    opciones: [['chrome_android', 'Chrome Android'], ['googlebot_smartphone', 'Googlebot smartphone']] },
  { ruta: 'crawl_behavior.capturas_muestra', grupo: 'sondas', etiqueta: 'Capturas de pantalla: páginas (0 = no)', tipo: 'entero', min: 0, max: 50 },
  { ruta: 'crawl_behavior.capturas_por_plantilla', grupo: 'sondas', etiqueta: 'Capturas: por plantilla', tipo: 'entero', min: 1, max: 5 },
  { ruta: 'crawl_behavior.capturas_ambos_perfiles', grupo: 'sondas', etiqueta: 'Capturas en móvil y en escritorio', tipo: SI_NO },
  { ruta: 'crawl_behavior.soft404_sondas', grupo: 'sondas', etiqueta: 'URLs inventadas para ver si hay soft 404', tipo: 'entero', min: 0, max: 100 },
  { ruta: 'crawl_behavior.sonda_tls', grupo: 'sondas', etiqueta: 'Mirar el certificado TLS', tipo: SI_NO },
  { ruta: 'adapters.wordpress.modo', grupo: 'sondas', etiqueta: 'WordPress: leer su REST API', tipo: 'opciones',
    opciones: [['auto', 'Si el sitio es un WordPress'], ['on', 'Siempre'], ['off', 'No']] },

  // --- Que se guarda de cada pagina
  { ruta: 'extraction.extract_structured_data', grupo: 'contenido', etiqueta: 'Datos estructurados', tipo: SI_NO },
  { ruta: 'extraction.extract_hreflang', grupo: 'contenido', etiqueta: 'hreflang', tipo: SI_NO },
  { ruta: 'extraction.extract_security_headers', grupo: 'contenido', etiqueta: 'Cabeceras de seguridad', tipo: SI_NO },
  { ruta: 'extraction.extract_page_content', grupo: 'contenido', etiqueta: 'Texto de la página', tipo: SI_NO },
  { ruta: 'extraction.strip_promo_blocks', grupo: 'contenido', etiqueta: 'Quitar banners y bloques promocionales del texto', tipo: SI_NO },
  { ruta: 'extraction.store_raw_html', grupo: 'contenido', etiqueta: 'Guardar el HTML entero', tipo: SI_NO },

  // --- Cabeceras, cookies y acceso
  { ruta: 'http.accept_language', grupo: 'http', etiqueta: 'Idioma que pide (Accept-Language)', tipo: 'texto', ejemplo: 'es-ES,es;q=0.9' },
  { ruta: 'http.custom_headers', grupo: 'http', etiqueta: 'Cabeceras propias', tipo: 'kv', sep: ':', ejemplo: 'X-Prueba: 1',
    ayuda: 'Una por línea, «Nombre: valor». Solo van a los hosts de las semillas.' },
  { ruta: 'http.cookies', grupo: 'http', etiqueta: 'Cookies', tipo: 'kv', sep: '=', ejemplo: 'consentimiento=si',
    ayuda: 'Una por línea, «nombre=valor». Solo van a los hosts de las semillas.' },
  { ruta: 'http.conservar_cookies', grupo: 'http', etiqueta: 'Guardar las cookies que pone el sitio entre páginas', tipo: SI_NO },
  // La contrasena del Basic solo en un rastreo: en un cliente o un perfil se
  // guardaria en la base de datos (decision 83; `validar_config_parcial`).
  { ruta: 'http.basic_auth_user', grupo: 'http', etiqueta: 'Usuario (autenticación básica)', tipo: 'texto', niveles: ['rastreo'] },
  { ruta: 'http.basic_auth_password', grupo: 'http', etiqueta: 'Contraseña (autenticación básica)', tipo: 'clave', niveles: ['rastreo'] },

  // --- Umbrales del analisis
  { ruta: 'analysis_thresholds.title_min_length', grupo: 'umbrales', etiqueta: 'Título: caracteres como mínimo', tipo: 'entero', min: 0, max: 200 },
  { ruta: 'analysis_thresholds.title_max_length', grupo: 'umbrales', etiqueta: 'Título: caracteres como máximo', tipo: 'entero', min: 1, max: 500 },
  { ruta: 'analysis_thresholds.description_min_length', grupo: 'umbrales', etiqueta: 'Descripción: caracteres como mínimo', tipo: 'entero', min: 0, max: 500 },
  { ruta: 'analysis_thresholds.description_max_length', grupo: 'umbrales', etiqueta: 'Descripción: caracteres como máximo', tipo: 'entero', min: 1, max: 1000 },
  { ruta: 'analysis_thresholds.min_word_count', grupo: 'umbrales', etiqueta: 'Palabras como mínimo', tipo: 'entero', min: 0, max: 10000 },
  { ruta: 'analysis_thresholds.max_redirect_chain_length', grupo: 'umbrales', etiqueta: 'Redirecciones seguidas aceptables', tipo: 'entero', min: 1, max: 20 },
  { ruta: 'analysis_thresholds.max_outlinks', grupo: 'umbrales', etiqueta: 'Enlaces salientes como mucho', tipo: 'entero', min: 1, max: 10000 },
  { ruta: 'analysis_thresholds.tls_dias_aviso', grupo: 'umbrales', etiqueta: 'Avisar del certificado a estos días de caducar', tipo: 'entero', min: 1, max: 90 },
];
let _TPL_CFG = null;
const CAMPO_CONFIG = Object.fromEntries(CAMPOS_CONFIG.map(c => [c.ruta, c]));

// Las secciones plegables de Configuracion del cliente, en orden (revision de
// UX del 25-oct, 2.4): el indice de arriba lleva a cada una y la abre.
const TEXTO_ESTADO_LOG = { pendiente: 'en cola', procesando: 'leyéndose', hecho: 'leído', error: 'con error' };
const NOMBRE_BOT_LOG = {
  googlebot: 'Googlebot', 'googlebot-imagen': 'Googlebot imágenes', 'googlebot-video': 'Googlebot vídeo',
  'google-inspeccion': 'Inspección de URLs', googleother: 'GoogleOther', 'adsbot-google': 'AdsBot',
  bingbot: 'Bingbot', 'oai-searchbot': 'OAI-SearchBot', 'chatgpt-user': 'ChatGPT-User', gptbot: 'GPTBot',
  'claude-searchbot': 'Claude-SearchBot', 'claude-user': 'Claude-User', claudebot: 'ClaudeBot',
  perplexitybot: 'PerplexityBot', 'perplexity-user': 'Perplexity-User', applebot: 'Applebot',
};

// Que limito la velocidad del rastreo (#275, decision 227), de `jobs.ritmo`.
function fraseRitmo(job) {
  const r = job && job.ritmo;
  if (!r || !r.techo) return null;
  const v = (x) => fmt.num(Math.round(x * 100) / 100);
  let porque;
  if (r.limita === 'pausa') {
    porque = 'lo marca la pausa de ' + v(r.pausa_s) + ' s entre peticiones (una por pausa, haya la concurrencia que haya): quitarla o bajarla es lo que lo acelera';
  } else if (r.limita === 'servidor') {
    porque = 'lo marca el servidor: ' + fmt.num(r.concurrencia) + ' peticiones a la vez y ' + v(r.latencia_s) + ' s de respuesta media; más rápido solo con más concurrencia, si el sitio la aguanta';
  } else {
    porque = 'va por debajo de lo que permiten la pausa y el servidor: lo frena el propio rastreo (el procesado de cada página) o el reparto entre hosts';
  }
  return 'Ritmo: ' + v(r.urls_s) + ' URL/s; el techo era ' + v(r.techo) + ' URL/s y ' + porque + '.';
}

// Googlebot en los logs del cliente (#35, decision 213), de `jobs.logs_resumen`.
function bloqueLogs(job) {
  const r = job && job.logs_resumen;
  if (!r) return null;
  const pct = (a, b) => b ? fmt.pct(100 * a / b, 0) : '—';
  const rep = r.reparto || {};
  const total = r.visitas || 0;
  const frases = [];
  frases.push(fmt.n(total, 'visita', 'visitas') + ' de Googlebot verificado del ' + fmt.dia(r.desde) + ' al ' + fmt.dia(r.hasta)
    + ' (' + fmt.n(Math.round(r.dias), 'día', 'días') + ')' + (r.parte_movil != null ? ', el ' + fmt.pct(100 * r.parte_movil, 0) + ' con el de móvil.' : '.'));
  frases.push('Visitó ' + fmt.num(r.indexables_visitadas) + ' de las ' + fmt.num(r.indexables) + ' páginas indexables del rastreo (' + pct(r.indexables_visitadas, r.indexables) + ').');
  const gasto = [['indexables', 'indexables'], ['no_indexables', 'no indexables'], ['redirecciones', 'redirecciones'],
    ['errores', 'errores'], ['no_en_censo', 'URLs que el rastreo no encontró']]
    .filter(([k]) => rep[k]).map(([k, t]) => pct(rep[k], total) + ' en ' + t);
  if (gasto.length) frases.push('En qué se va: ' + gasto.join(', ') + '.');
  if (rep.con_parametros) frases.push(pct(rep.con_parametros, total) + ' de las visitas son a URLs con parámetros.');
  if (r.falsas) frases.push(fmt.n(r.falsas, 'visita', 'visitas') + ' más dicen ser de Googlebot y vienen de IPs que no son de Google: no cuentan.');
  if (!r.afirmable_ausencia && r.no_se_afirma) frases.push('No se afirma qué páginas no visita: ' + r.no_se_afirma + '.');
  const bots = Object.entries(r.otros_bots || {}).filter(([, d]) => d.visitas)
    .sort((a, b) => b[1].visitas - a[1].visitas).slice(0, 8)
    .map(([b, d]) => ({ bot: NOMBRE_BOT_LOG[b] || b, visitas: d.visitas, verificadas: d.verificadas, falsas: d.falsas, sin_comprobar: d.sin_comprobar }));
  // El reparto por plantilla (#35 con #12): la de mas visitas primero.
  const plantillas = (r.por_plantilla || []).map(p => ({
    ...p, pct: p.parte != null ? fmt.pct(100 * p.parte, 1) : '—',
    cobertura: p.indexables ? pct(p.indexables_visitadas, p.indexables) : '—',
  }));
  return { frases, no_en_censo: r.no_en_censo || [], bots, plantillas };
}

const FUENTE_BACKLINKS = { ahrefs: 'Ahrefs', semrush: 'Semrush', majestic: 'Majestic', generico: 'un CSV' };

const SECCIONES_CONFIG_CLIENTE = [
  ['cfg-perfiles', 'Perfiles'], ['cfg-rastreo', 'Cómo se rastrea'], ['cfg-datos', 'Datos'],
  ['cfg-gsc', 'Search Console'], ['cfg-backlinks', 'Backlinks'], ['cfg-logs', 'Logs'], ['cfg-slack', 'Slack'], ['cfg-enlace', 'Enlace para el cliente'],
  ['cfg-integraciones', 'Otras integraciones'], ['reglas-alertas', 'Reglas de alertas'],
];

const ORIGEN_TEXTO = { cliente: 'del cliente', perfil: 'del perfil', rastreo: 'de este rastreo', serie: 'de serie' };

function cfgLeer(obj, ruta) {
  let o = obj;
  for (const p of ruta.split('.')) {
    if (o === null || o === undefined || typeof o !== 'object') return undefined;
    o = o[p];
  }
  return o;
}

// `in` antes que hasOwnProperty: el proxy reactivo de Alpine registra `in`
// (trampa `has`) y no hasOwnProperty, y sin eso la etiqueta «cambiado aquí»
// no se repintaba al fijar una clave nueva.
function _cfgPropia(o, k) {
  return !!o && typeof o === 'object' && (k in o) && Object.prototype.hasOwnProperty.call(o, k);
}

function cfgTieneRuta(obj, ruta) {
  const partes = ruta.split('.');
  let o = obj;
  for (const p of partes.slice(0, -1)) {
    if (!_cfgPropia(o, p)) return false;
    o = o[p];
  }
  return _cfgPropia(o, partes[partes.length - 1]);
}

function cfgPoner(obj, ruta, valor) {
  const partes = ruta.split('.');
  let o = obj;
  for (const p of partes.slice(0, -1)) {
    if (!o[p] || typeof o[p] !== 'object') o[p] = {};
    o = o[p];
  }
  o[partes[partes.length - 1]] = valor;
}

// Quita la clave y los padres que se queden vacios: un `{"crawl_behavior": {}}`
// no fija nada, pero ensuciaria el JSON de «Avanzado».
function cfgQuitar(obj, ruta) {
  const partes = ruta.split('.');
  const pila = [obj];
  for (const p of partes.slice(0, -1)) {
    const o = pila[pila.length - 1];
    if (!o || typeof o[p] !== 'object' || o[p] === null) return;
    pila.push(o[p]);
  }
  delete pila[pila.length - 1][partes[partes.length - 1]];
  for (let i = partes.length - 2; i >= 0; i--) {
    if (Object.keys(pila[i + 1]).length) break;
    delete pila[i][partes[i]];
  }
}

// Una instancia del formulario. `base` = la config resuelta de los niveles de
// arriba (completa), `origen` = de que nivel sale cada ruta de `base`, `serie`
// = los valores de JobConfig, `propia` = lo que fija este nivel.
function cfgNuevo(nivel, d) {
  d = d || {};
  const propia = JSON.parse(JSON.stringify(d.propia || {}));
  return {
    nivel, base: d.base || {}, origenBase: d.origen || {}, origenClave: d.origenClave || {},
    serie: d.serie || d.base || {},
    propia, textos: {}, errores: {}, abiertos: {},
    json: JSON.stringify(propia, null, 2), jsonError: '', jsonSucio: false,
    ctx: d.ctx || {}, resuelta: null, resueltaError: '', resolviendo: false, cargada: !!d.base,
  };
}

function cfgTiene(inst, ruta) {
  return cfgTieneRuta(inst.propia, ruta);
}

function cfgHeredado(inst, ruta) {
  const v = cfgLeer(inst.base, ruta);
  return v === undefined ? cfgLeer(inst.serie, ruta) : v;
}

// El valor con el que saldria el rastreo con este nivel tal como esta.
function cfgEfectivo(inst, ruta) {
  const c = CAMPO_CONFIG[ruta] || {};
  if (cfgTiene(inst, ruta)) {
    const v = cfgLeer(inst.propia, ruta);
    if (v === null) return cfgLeer(inst.serie, ruta) ?? null;
    if (c.tipo === 'kv' || c.tipo === 'topes') return { ...(cfgHeredado(inst, ruta) || {}), ...v };
    return v;
  }
  // Modo lista (decision 128): sin que nadie fije el sitemap, una lista no lo lee.
  if (ruta === 'use_sitemap' && !inst.origenBase.use_sitemap && Number(cfgEfectivo(inst, 'max_depth')) === 0) return false;
  return cfgHeredado(inst, ruta);
}

// El resumen en corto de una configuracion: solo lo que se sabe. Un valor
// `undefined` es que ni se fijo ni llego lo de serie (API anterior).
function partesResumenConfig(inst, claves) {
  const partes = [];
  for (const k of claves) {
    const v = cfgEfectivo(inst, k);
    if (v === undefined) continue;
    if (k === 'max_urls') partes.push(v ? fmt.num(v) + ' URLs' : 'sin tope de URLs');
    else if (k === 'concurrent_requests_per_domain') { if (v != null) partes.push(fmt.num(v) + ' a la vez por dominio'); }
    else if (k === 'render_js') { if (v != null) partes.push(v ? 'con render JS' : 'sin render JS'); }
  }
  return partes;
}

function cfgOrigen(inst, ruta) {
  if (cfgTiene(inst, ruta)) return 'aqui';
  return inst.origenBase[ruta] || 'serie';
}

// El valor en llano, para «Así rastreará» y para «el heredado es…».
function cfgLlano(ruta, v) {
  const c = CAMPO_CONFIG[ruta] || { tipo: typeof v === 'boolean' ? SI_NO : 'texto' };
  if (v === null || v === undefined || v === '') {
    if (c.nulo) return c.nulo.toLowerCase();
    return c.tipo === 'lineas' || c.tipo === 'kv' || c.tipo === 'topes' ? 'ninguna' : '—';
  }
  if (c.tipo === SI_NO) return v ? 'sí' : 'no';
  if (c.tipo === 'opciones') return ((c.opciones || []).find(o => o[0] === v) || [v, v])[1];
  if (c.tipo === 'huella') return ((HUELLAS_TLS.find(o => o[0] === v)) || [v, v])[1];
  if (c.tipo === 'ua') { const p = presetDeUserAgent(v); return p ? UA_LABELS[p] : 'personalizado'; }
  if (c.tipo === 'entero' || c.tipo === 'decimal') return fmt.num(v);
  if (c.tipo === 'clave') return 'puesta';
  if (Array.isArray(v)) return v.length ? v.join(', ') : 'ninguna';
  if (typeof v === 'object') {
    const n = Object.keys(v).length;
    return n ? Object.entries(v).map(([k, x]) => (c.sep === ':' ? `${k}: ${x}` : `${k} ${c.sep || '='} ${x}`)).join(', ') : 'ninguna';
  }
  return String(v);
}

// El texto del campo: lo que se esta escribiendo (con error) o el valor.
function cfgTextoCampo(inst, ruta) {
  if (_cfgPropia(inst.textos, ruta)) return inst.textos[ruta];
  const c = CAMPO_CONFIG[ruta];
  const v = cfgEfectivo(inst, ruta);
  if (c.tipo === 'huella') {
    // Sin que nadie la fije, la deduce la API del user agent (decision 132).
    return cfgTiene(inst, ruta) || inst.origenBase.impersonate ? (v || '') : '';
  }
  if (c.tipo === 'ua') return presetDeUserAgent(v) || 'custom';
  if (v === null || v === undefined) return '';
  if (c.tipo === 'lineas') return (v || []).join('\n');
  if (c.tipo === 'kv') return Object.entries(v || {}).map(([k, x]) => `${k}${c.sep === ':' ? ': ' : '='}${x}`).join('\n');
  if (c.tipo === 'topes') return Object.entries(v || {}).filter(([, x]) => x !== null).map(([k, x]) => `${k} = ${x}`).join('\n');
  if (c.tipo === 'decimal') return String(v).replace('.', ',');
  return String(v);
}

// Del texto al valor, con los limites de JobConfig. {valor} o {error}.
function cfgParsear(c, texto) {
  if (c.tipo === SI_NO) return { valor: !!texto };
  if (c.tipo === 'opciones' || c.tipo === 'huella') return { valor: texto };
  if (c.tipo === 'texto' || c.tipo === 'clave') return { valor: String(texto || '').trim() };
  if (c.tipo === 'lineas') return { valor: String(texto || '').split('\n').map(s => s.trim()).filter(Boolean) };
  if (c.tipo === 'kv') {
    const salida = {};
    for (const linea of String(texto || '').split('\n').map(s => s.trim()).filter(Boolean)) {
      const i = linea.indexOf(c.sep);
      if (i < 1) return { error: `Falta «${c.sep}» en «${linea}»` };
      salida[linea.slice(0, i).trim()] = linea.slice(i + 1).trim();
    }
    return { valor: salida };
  }
  if (c.tipo === 'topes') {
    const salida = {};
    for (const linea of String(texto || '').split('\n').map(s => s.trim()).filter(Boolean)) {
      const i = linea.lastIndexOf('=');
      const n = i > 0 ? linea.slice(i + 1).trim() : '';
      if (!/^\d+$/.test(n)) return { error: `«${linea}»: escribe «regla = número»` };
      salida[linea.slice(0, i).trim()] = parseInt(n, 10);
    }
    return { valor: salida };
  }
  let t = String(texto ?? '').trim();
  if (c.tipo === 'entero' && t.includes('.')) {
    // El punto solo es de miles si lo parece (5.000, 1.200.000): «1.5» como
    // 15 sin decir nada era facil de colar en el maximo de URLs (revision
    // del 26-oct de la decision 196).
    if (!/^\d{1,3}(\.\d{3})+$/.test(t)) return { error: 'Tiene que ser un número entero (los miles, como 5.000)' };
    t = t.replace(/\./g, '');
  }
  t = t.replace(',', '.');
  if (t === '') return c.nulo ? { valor: null } : { error: 'Hace falta un número' };
  const n = Number(t);
  if (!Number.isFinite(n)) return { error: 'Tiene que ser un número' };
  if (c.tipo === 'entero' && !Number.isInteger(n)) return { error: 'Tiene que ser un número entero' };
  if ((c.min !== undefined && n < c.min) || (c.max !== undefined && n > c.max)) {
    return { error: `Entre ${fmt.num(c.min)} y ${fmt.num(c.max)}` };
  }
  return { valor: n };
}

// Igualdad sin depender del orden de las claves: un objeto que vuelve de la
// API puede traerlas en otro orden que el borrador.
function _cfgOrdenado(v) {
  if (Array.isArray(v)) return v.map(_cfgOrdenado);
  if (v && typeof v === 'object') {
    return Object.fromEntries(Object.keys(v).sort().map(k => [k, _cfgOrdenado(v[k])]));
  }
  return v;
}

function _cfgIgual(a, b) {
  return JSON.stringify(_cfgOrdenado(a ?? null)) === JSON.stringify(_cfgOrdenado(b ?? null));
}

// Cambia un campo en este nivel. Devuelve el error, o ''.
function cfgCambiar(inst, ruta, texto) {
  // Lo escrito en «Avanzado» y aun sin aplicar entra antes: si no, reescribir
  // `json` con `propia` lo borraria (revision del 26-oct de la decision 196).
  if (inst.jsonSucio) cfgAplicarJson(inst);
  const c = CAMPO_CONFIG[ruta];
  const r = c.tipo === 'ua'
    ? { valor: texto }
    : cfgParsear(c, texto);
  if (r.error) {
    inst.errores[ruta] = r.error;
    inst.textos[ruta] = texto;
    return r.error;
  }
  delete inst.errores[ruta];
  delete inst.textos[ruta];
  const heredado = cfgHeredado(inst, ruta);
  if (c.tipo === 'kv' || c.tipo === 'topes') {
    // Se fusionan por clave con lo heredado: aqui solo lo nuevo o distinto.
    // Quitar una heredada no se puede desde un nivel de abajo (un null aqui
    // no lo admite la API): se dice en vez de perderla en silencio.
    const her = heredado || {};
    const faltan = Object.keys(her).filter(k => !(k in r.valor));
    if (faltan.length) {
      // Cada clave con su nivel: cabeceras y cookies se fusionan por clave, y
      // la del cliente no esta en el perfil aunque el perfil ponga otra
      // (revision del 26-oct de la decision 196).
      const pc = inst.origenClave[ruta] || {};
      const grupos = {};
      for (const k of faltan) (grupos[pc[k] || inst.origenBase[ruta] || ''] ||= []).push(k);
      inst.errores[ruta] = Object.entries(grupos)
        .map(([o, ks]) => `«${ks.join('», «')}» ${ks.length > 1 ? 'vienen' : 'viene'} ${ORIGEN_TEXTO[o] || 'de arriba'}`)
        .join('; ') + (faltan.length > 1 ? ': quítalas allí' : ': quítala allí');
      inst.textos[ruta] = texto;
      return inst.errores[ruta];
    }
    const propias = Object.fromEntries(Object.entries(r.valor).filter(([k, v]) => !_cfgIgual(her[k], v)));
    if (Object.keys(propias).length) cfgPoner(inst.propia, ruta, propias); else cfgQuitar(inst.propia, ruta);
  } else if (c.tipo === 'huella' && r.valor === '') {
    cfgQuitar(inst.propia, ruta);
  } else if (_cfgIgual(r.valor, ruta === 'use_sitemap' ? cfgEfectivoSinPropia(inst, ruta) : heredado)) {
    // Lo mismo que lo heredado no se fija aqui: si cambia arriba, llega.
    cfgQuitar(inst.propia, ruta);
  } else {
    cfgPoner(inst.propia, ruta, r.valor);
  }
  if (!inst.jsonSucio) {
    inst.json = JSON.stringify(inst.propia, null, 2);
    inst.jsonError = '';
  }
  return '';
}

function cfgEfectivoSinPropia(inst, ruta) {
  const copia = { ...inst, propia: JSON.parse(JSON.stringify(inst.propia)) };
  cfgQuitar(copia.propia, ruta);
  return cfgEfectivo(copia, ruta);
}

// «volver al heredado»
function cfgHeredar(inst, ruta) {
  if (inst.jsonSucio) cfgAplicarJson(inst);
  cfgQuitar(inst.propia, ruta);
  delete inst.errores[ruta];
  delete inst.textos[ruta];
  if (!inst.jsonSucio) inst.json = JSON.stringify(inst.propia, null, 2);
}

// «Avanzado»: el JSON de este nivel, para lo que el formulario no tiene
// (plantillas, segmentos, marcas…). Se valida en la API al guardar.
function cfgAplicarJson(inst) {
  let d;
  try {
    d = (inst.json || '').trim() ? JSON.parse(inst.json) : {};
  } catch (e) {
    inst.jsonError = 'No es JSON válido: ' + e.message;
    return false;
  }
  if (!d || typeof d !== 'object' || Array.isArray(d)) {
    inst.jsonError = 'Tiene que ser un objeto: { … }';
    return false;
  }
  inst.propia = d;
  inst.errores = {};
  inst.textos = {};
  inst.jsonError = '';
  inst.jsonSucio = false;
  return true;
}

// Antes de guardar o lanzar: lo escrito en «Avanzado» sin aplicar se aplica
// (antes se mandaba `propia` sin ello y salia «Configuración guardada» con el
// cambio perdido en silencio; revision del 26-oct de la decision 196). El
// texto del error, o '' si se puede seguir.
function cfgListoParaGuardar(inst) {
  if (!inst) return '';
  if (inst.jsonSucio && !cfgAplicarJson(inst)) {
    return 'El JSON de «Avanzado» no es válido: corrígelo o vacíalo. ' + inst.jsonError;
  }
  if (inst.jsonError) return 'El JSON de «Avanzado» no es válido: corrígelo o vacíalo. ' + inst.jsonError;
  if (cfgHayErrores(inst)) return 'Hay campos de la configuración con error: corrígelos o vuelve al heredado.';
  return '';
}

// Lo que este nivel fija y el formulario no tiene (plantillas, marcas…): se
// dice en el resumen para que «lo de serie» no lo esconda.
function cfgClavesFuera(inst) {
  const fuera = [];
  const bajar = (o, ruta) => {
    for (const [k, v] of Object.entries(o || {})) {
      const r = ruta ? ruta + '.' + k : k;
      if (CAMPO_CONFIG[r]) continue;
      if (v && typeof v === 'object' && !Array.isArray(v) && CAMPOS_CONFIG.some(c => c.ruta.startsWith(r + '.'))) bajar(v, r);
      else fuera.push(r);
    }
  };
  bajar(inst.propia, '');
  return fuera;
}

function cfgHayErrores(inst) {
  return !!inst && (Object.keys(inst.errores).length > 0 || !!inst.jsonError);
}

// Lo que se esta escribiendo en «Avanzado»: queda pendiente y se aplica solo
// al dejar de escribir (o antes de guardar, con `cfgListoParaGuardar`).
function cfgJsonEscrito(inst) {
  inst.jsonSucio = true;
}

function cfgCamposDe(inst, grupo) {
  return CAMPOS_CONFIG.filter(c => c.grupo === grupo && (!c.niveles || c.niveles.includes(inst.nivel)));
}

// Junto al titulo de un grupo plegado: lo que se ha cambiado en ESTE nivel.
function cfgResumenGrupo(inst, grupo) {
  const n = cfgCamposDe(inst, grupo).filter(c => cfgTiene(inst, c.ruta)).length;
  const errores = cfgCamposDe(inst, grupo).filter(c => inst.errores[c.ruta]).length;
  if (errores) return errores === 1 ? '· 1 campo con error' : `· ${errores} campos con error`;
  if (!n) return '';
  return n === 1 ? '· 1 cambiado aquí' : `· ${n} cambiados aquí`;
}

// La procedencia de un campo, en llano.
// Los niveles de los que sale lo heredado de un campo: uno, o varios en los
// dicts que se fusionan por clave (cabeceras, cookies, topes).
function cfgCapasHeredadas(inst, ruta) {
  const pc = inst.origenClave[ruta];
  const capas = pc ? Object.values(pc) : [inst.origenBase[ruta] || 'serie'];
  return ['cliente', 'perfil', 'rastreo', 'serie'].filter(o => capas.includes(o));
}

function cfgTextoCapas(capas, nivel) {
  return capas.map(o => (o === nivel ? (nivel === 'rastreo' ? 'de este rastreo' : 'de aquí') : (ORIGEN_TEXTO[o] || o)))
    .join(' y ');
}

function cfgEtiquetaOrigen(inst, ruta) {
  const o = cfgOrigen(inst, ruta);
  if (o === 'aqui') {
    return 'cambiado aquí · ' + cfgTextoCapas(cfgCapasHeredadas(inst, ruta)) + ': ' + cfgLlano(ruta, cfgHeredado(inst, ruta));
  }
  if (inst.origenClave[ruta]) return cfgTextoCapas(cfgCapasHeredadas(inst, ruta));
  if (ruta === 'impersonate' && !inst.origenBase.impersonate) return 'automática';
  if (ruta === 'use_sitemap' && !inst.origenBase.use_sitemap && Number(cfgEfectivo(inst, 'max_depth')) === 0) {
    return 'en modo lista no se lee';
  }
  return ORIGEN_TEXTO[o] || o;
}

// Las lineas de «Así rastreará»: lo principal siempre y, del resto, lo que no
// es de serie. Con la config que devuelve la API (la de verdad, deducciones
// incluidas) y la procedencia que dice ella.
function cfgAsiLineas(inst) {
  const r = inst.resuelta;
  if (!r) return [];
  const origen = r.origen || {};
  const porClave = r.origen_por_clave || {};
  // Un dict fusionado por clave puede venir de varios niveles a la vez:
  // «cliente+perfil» (revision del 26-oct de la decision 196).
  const de = ruta => {
    const capas = porClave[ruta] ? ['cliente', 'perfil', 'rastreo'].filter(o => Object.values(porClave[ruta]).includes(o)) : [];
    return capas.length > 1 ? capas.join('+') : (origen[ruta] || 'serie');
  };
  return CAMPOS_CONFIG
    .filter(c => (!c.niveles || c.niveles.includes(inst.nivel))
      && (c.grupo === 'principal' || origen[c.ruta]) && c.tipo !== 'clave')
    .map(c => ({ ruta: c.ruta, etiqueta: c.etiqueta, valor: cfgLlano(c.ruta, cfgLeer(r.config, c.ruta)),
                 origen: de(c.ruta) }));
}

function cfgOrigenAsi(origen, nivel) {
  if (origen.includes('+')) return cfgTextoCapas(origen.split('+'), nivel);
  if (origen === nivel) return nivel === 'rastreo' ? 'de este rastreo' : 'cambiado aquí';
  return ORIGEN_TEXTO[origen] || origen;
}

function _parseKV(text, separator) {
  const obj = {};
  if (!text) return obj;
  text.split('\n').forEach(line => {
    line = line.trim();
    if (!line) return;
    const idx = line.indexOf(separator);
    if (idx < 1) return;
    const key = line.substring(0, idx).trim();
    const val = line.substring(idx + separator.length).trim();
    if (key) obj[key] = val;
  });
  return obj;
}

function _kvTexto(obj, sep) {
  return Object.entries(obj || {}).map(([k, v]) => `${k}${sep}${v}`).join('\n');
}

// El formulario de la ficha de un cliente. `c` = la respuesta de la API, o
// null para uno nuevo. Las integraciones traen `configurada` del servidor:
// si la variable existe en su entorno, nunca su valor.
function _formCliente(c) {
  return {
    nombre: c ? c.nombre : '',
    slug: c ? c.slug : '',
    dominios: c ? (c.dominios || []).join('\n') : '',
    zona_horaria: c ? (c.zona_horaria || '') : 'Europe/Madrid',
    notas: c ? (c.notas || '') : '',
    integraciones: c ? (c.integraciones || []).map(i => ({
      tipo: i.tipo,
      etiqueta: i.etiqueta || '',
      parametros: _kvTexto(i.parametros, '='),
      credencial_env: i.credencial_env || '',
      activa: i.activa !== false,
      configurada: i.configurada,
    })) : [],
  };
}

// ---------------------------------------------------------------------------
// Evolucion de un perfil (decision 130): graficas SVG propias, sin librerias.
// ---------------------------------------------------------------------------
// Por que un punto no entra en la linea: lo devuelve la API en `motivo`.
const MOTIVO_NO_COMPARABLE = {
  failed: 'rastreo fallido', stalled: 'rastreo estancado', truncado: 'censo truncado',
  canario: 'canario', prueba: 'prueba', lista: 'lista de URLs (modo lista)',
  desfasado: 'agregado de otra versión del análisis: pasa rellenar_evolucion.py',
  sin_agregado: 'sin agregar: pasa rellenar_evolucion.py',
};

// Lo que se grafica en la ficha del cliente, en este orden. Las etiquetas y el
// sentido («mejor si baja») vienen de `shared.evolucion.METRICAS`.
// Paginas con error y no incidencias (decision 202): la misma cifra que la
// tarjeta del censo, la tabla de debajo y la portada.
const METRICAS_GRAFICADAS = ['urls_con_error', 'urls_4xx', 'urls_5xx', 'indexables',
  'pagerank_desperdiciado', 'click_depth_medio'];

// Lo minimo que abarca el eje vertical de una grafica, como fraccion de su
// valor mas alto (revision de UX del 25-oct, 3.1). Con 0,2, pasar de 3.197 a
// 3.222 indexables ocupa un 4 % del alto y no la grafica entera.
const RANGO_MINIMO_EJE = 0.2;

// El suelo del eje en un numero redondo (2.500 y no 2.577,6): hacia abajo, al
// multiplo de la potencia de 10 de la amplitud (de 1 en 1 si son enteros).
function _sueloRedondo(v, amplitud, enteros) {
  let paso = Math.pow(10, Math.floor(Math.log10(amplitud || 1)));
  if (enteros) paso = Math.max(1, paso);
  return Math.floor(v / paso) * paso;
}

function _escSvg(t) {
  return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _valorMetrica(v, metrica) {
  if (v == null) return '—';
  if (metrica === 'pagerank_desperdiciado') return String(v).replace('.', ',') + ' %';
  if (metrica === 'click_depth_medio') return Number(v).toFixed(1).replace('.', ',');
  return fmt.num(v);
}

// El modelo de una grafica: posiciones y textos, sin pintar nada. Separado del
// SVG para poder comprobarlo. Reglas (decisiones 67, 72 y 91):
// - x por orden, con TODOS los puntos: un hueco tambien es informacion;
// - la escala y la linea, solo con los comparables: un rastreo bloqueado de 3
//   URLs en una serie de 5.000 hundiria la escala y se leeria como «el sitio
//   se ha caido». Los no comparables van abajo, con una ×, y su motivo;
// - entre dos puntos con distinta version del analisis, el tramo es
//   discontinuo y hay un corte vertical: el salto puede ser nuestro.
function modeloGrafica(puntos, metrica, opciones) {
  const o = Object.assign({ ancho: 300, alto: 120, margen: 14 }, opciones || {});
  const lista = puntos || [];
  const n = lista.length;
  const izq = o.margen + 26, der = o.ancho - o.margen, arriba = o.margen, abajo = o.alto - o.margen - 10;
  const x = i => n <= 1 ? (izq + der) / 2 : izq + (der - izq) * i / (n - 1);
  const valores = lista.filter(p => p.comparable && p[metrica] != null).map(p => p[metrica]);
  let min = valores.length ? Math.min(...valores) : 0;
  let max = valores.length ? Math.max(...valores) : 1;
  if (min === max) { min = min - (min ? Math.abs(min) * .1 : 1); max = max + (max ? Math.abs(max) * .1 : 1); }
  if (min < 0 && valores.every(v => v >= 0)) min = 0;
  // Rango minimo (revision de UX del 25-oct, 3.1): el eje abarca al menos un
  // RANGO_MINIMO_EJE del valor mas alto, para que una variacion pequena se vea
  // pequena (indexables 3.197 → 3.222 se dibujaba de suelo a techo, como un
  // desplome o un despegue). Se alarga hacia abajo, sin bajar de 0 si todo es
  // positivo; la leyenda de la ficha lo dice.
  const amplitud = Math.abs(max) * RANGO_MINIMO_EJE;
  if (max - min < amplitud) {
    min = _sueloRedondo(max - amplitud, amplitud, valores.every(v => Number.isInteger(v)));
    if (min < 0 && valores.every(v => v >= 0)) min = 0;
  }
  const y = v => abajo - (abajo - arriba) * (v - min) / (max - min);
  const m = { ancho: o.ancho, alto: o.alto, metrica, etiqueta: o.etiqueta || metrica, min, max, base: abajo + 6,
              izq, der, arriba, abajo, puntos: [], fuera: [], tramos: [], cortes: [] };
  let anterior = null;
  lista.forEach((p, i) => {
    const titulo = fmt.dia(p.fecha) + ' · ' + (p.name || '') + ' · ';
    if (!p.comparable || p[metrica] == null) {
      m.fuera.push({ x: x(i), job_id: p.job_id,
        titulo: titulo + (p.comparable ? 'sin dato' : 'no comparable: ' + (MOTIVO_NO_COMPARABLE[p.motivo] || p.motivo)) });
      return;
    }
    const punto = { x: x(i), y: y(p[metrica]), valor: p[metrica], job_id: p.job_id,
                    titulo: titulo + _valorMetrica(p[metrica], metrica) };
    const cambio = p.cambio_version || null;
    if (anterior) {
      m.tramos.push({ x1: anterior.x, y1: anterior.y, x2: punto.x, y2: punto.y,
                      discontinuo: !!(cambio && cambio.analisis) });
      if (cambio && (cambio.analisis || cambio.rastreo)) {
        const desc = v => v || 'desconocida';
        m.cortes.push({ x: (anterior.x + punto.x) / 2, analisis: !!cambio.analisis,
          titulo: cambio.analisis
            ? 'Cambió la versión del análisis (' + desc(cambio.analisis_antes) + ' → ' + desc(cambio.analisis_despues)
              + '): el salto puede ser nuestro, no del sitio'
            : 'Cambió la versión del rastreo (' + desc(cambio.rastreo_antes) + ' → ' + desc(cambio.rastreo_despues) + ')' });
      }
    }
    m.puntos.push(punto);
    anterior = punto;
  });
  m.ultimo = m.puntos.length ? m.puntos[m.puntos.length - 1].valor : null;
  // Cada tramo, del color de lo que significa (revision de UX del 25-oct, 1.13
  // y 3.1): rojo si empeora segun `opciones.mejor` ('baja' o 'sube'), verde si
  // mejora y neutro si no cambia. Antes salia siempre del verde de la marca,
  // tambien con 41 URLs en 4xx frente a 35. Un tramo discontinuo (cambio de
  // version del analisis) no se juzga.
  for (const t of m.tramos) {
    if (t.discontinuo || !o.mejor || t.y2 === t.y1) continue;
    const sube = t.y2 < t.y1;  // en SVG la y crece hacia abajo
    t.sentido = (sube ? 'sube' : 'baja') === o.mejor ? 'mejora' : 'empeora';
  }
  return m;
}

function svgGrafica(m) {
  const partes = [`<svg class="evo-svg" viewBox="0 0 ${m.ancho} ${m.alto}" role="img" `
    + `aria-label="${_escSvg(m.etiqueta + ': ' + m.puntos.length + ' censos comparables')}">`];
  partes.push(`<line x1="${m.izq}" y1="${m.abajo}" x2="${m.der}" y2="${m.abajo}" style="stroke:var(--border)"/>`);
  partes.push(`<text x="${m.izq - 4}" y="${m.arriba + 4}" text-anchor="end" class="evo-eje">${_escSvg(_valorMetrica(+m.max.toFixed(2), m.metrica))}</text>`);
  partes.push(`<text x="${m.izq - 4}" y="${m.abajo}" text-anchor="end" class="evo-eje">${_escSvg(_valorMetrica(+m.min.toFixed(2), m.metrica))}</text>`);
  for (const c of m.cortes) {
    partes.push(`<line x1="${c.x}" y1="${m.arriba - 4}" x2="${c.x}" y2="${m.abajo}" class="${c.analisis ? 'evo-corte' : 'evo-corte-rastreo'}"><title>${_escSvg(c.titulo)}</title></line>`);
    if (c.analisis) partes.push(`<text x="${c.x}" y="${m.arriba - 5}" text-anchor="middle" class="evo-corte-txt"><title>${_escSvg(c.titulo)}</title>v</text>`);
  }
  for (const t of m.tramos) {
    partes.push(`<line x1="${t.x1}" y1="${t.y1}" x2="${t.x2}" y2="${t.y2}" class="evo-linea${t.discontinuo ? ' discontinua' : ''}${t.sentido ? ' ' + t.sentido : ''}"/>`);
  }
  for (const p of m.puntos) {
    partes.push(`<a href="#/rastreos/${_escSvg(p.job_id)}"><circle cx="${p.x}" cy="${p.y}" r="3.2" class="evo-punto"><title>${_escSvg(p.titulo)}</title></circle></a>`);
  }
  for (const f of m.fuera) {
    partes.push(`<a href="#/rastreos/${_escSvg(f.job_id)}"><text x="${f.x}" y="${m.base + 3}" text-anchor="middle" class="evo-fuera"><title>${_escSvg(f.titulo)}</title>×</text></a>`);
  }
  partes.push('</svg>');
  return partes.join('');
}

// La linea pequena del panel de cartera: solo valores, sin ejes.
// `cortes`: indices donde cambio la version del analisis; la linea se parte
// ahi (con un tramo gris discontinuo) en vez de unir los dos lados.
function sparkline(valores, cortes, opciones) {
  const o = Object.assign({ ancho: 80, alto: 22 }, opciones || {});
  const v = (valores || []).filter(x => x != null);
  if (v.length < 2) return '';
  // El mismo rango minimo que las graficas de la ficha (3.1): 89 → 85 errores
  // no puede ir de suelo a techo.
  const max = Math.max(...v);
  let min = Math.min(...v);
  if (max - min < Math.abs(max) * RANGO_MINIMO_EJE) {
    min = max - Math.abs(max) * RANGO_MINIMO_EJE;
    if (min < 0 && v.every(x => x >= 0)) min = 0;
  }
  const rango = (max - min) || 1;
  const pts = v.map((y, i) => [2 + (o.ancho - 4) * i / (v.length - 1),
                               o.alto - 2 - (o.alto - 4) * (y - min) / rango]);
  const txt = ps => ps.map(p => p.map(n => n.toFixed(1)).join(',')).join(' ');
  const partes = [];
  let desde = 0;
  // Con `opciones.mejor` ('baja' o 'sube') cada tramo lleva su sentido, como
  // en la ficha (3.1); sin el, la linea es neutra.
  const sentido = i => !o.mejor || v[i] === v[i - 1] ? ''
    : ((v[i] > v[i - 1] ? 'sube' : 'baja') === o.mejor ? ' mejora' : ' empeora');
  for (const c of [...(cortes || []).filter(c => c > 0 && c < pts.length), pts.length]) {
    const tramo = pts.slice(desde, c);
    if (tramo.length > 1 && !o.mejor) partes.push(`<polyline points="${txt(tramo)}" class="evo-linea"/>`);
    if (tramo.length > 1 && o.mejor) {
      for (let i = desde + 1; i < c; i++)
        partes.push(`<polyline points="${txt([pts[i - 1], pts[i]])}" class="evo-linea${sentido(i)}"/>`);
    }
    if (c < pts.length)
      partes.push(`<polyline points="${txt([pts[c - 1], pts[c]])}" class="evo-linea discontinua"/>`);
    desde = c;
  }
  const ultimo = pts[pts.length - 1];
  return `<svg class="evo-spark" viewBox="0 0 ${o.ancho} ${o.alto}" width="${o.ancho}" height="${o.alto}" aria-hidden="true">`
    + partes.join('')
    + `<circle cx="${ultimo[0].toFixed(1)}" cy="${ultimo[1].toFixed(1)}" r="2" class="evo-punto"/></svg>`;
}

// La tendencia de errores en palabras: flecha, color y por que. A traves de un
// cambio de version del analisis no hay flecha (decision 91).
function textoTendencia(t) {
  if (!t) return null;
  if (t.direccion === 'no_comparable')
    return { texto: '≠ versión', clase: 'neutra', titulo: t.motivo || 'Cambió la versión del análisis' };
  if (t.direccion == null) return null;
  const desde = fmt.dia(t.fecha_antes) + ': ' + fmt.num(t.antes);
  // En el panel, el censo de la tendencia no tiene por que ser el de la
  // columna «último censo» (ese puede estar truncado o ser de otro perfil):
  // el titulo dice de que censo sale la cifra de ahora.
  const hasta = t.fecha_ahora ? ' → ' + fmt.dia(t.fecha_ahora) + ': ' + fmt.num(t.ahora) : '';
  if (t.direccion === 'igual') return { texto: '=', clase: '', titulo: 'Igual que el ' + desde + hasta };
  return { texto: (t.direccion === 'sube' ? '▲ ' : '▼ ') + fmt.num(Math.abs(t.delta)),
           clase: t.mejora ? 'mejor' : 'peor',
           titulo: 'Frente al censo comparable anterior (' + desde + hasta + ')'
             + (t.cambio_version && t.cambio_version.rastreo ? '. Ojo: rastreado con otra versión del crawler' : '') };
}


// La regla propia en castellano, igual que `shared.reglas.frase` (decision 135).
const MODOS_REGLA = { valor: 'el valor del rastreo', cambio: 'el cambio frente al anterior',
                      cambio_pct: 'el cambio en % frente al anterior' };
function etiquetaMedida(medida, catalogo) {
  const m = catalogo && catalogo.medidas && catalogo.medidas[medida];
  if (m) return m.etiqueta;
  if ((medida || '').startsWith('incidencia:')) return 'Páginas con «' + fmt.issue(medida.slice(11)) + '»';
  return medida;
}
// Revision de UX del 25-oct, 3.9: la frase sin simbolos («es menor o igual
// que −10 %» y no «<= -10%») ni claves internas de las incidencias.
const OPERADOR_REGLA = { '>': 'es mayor que', '>=': 'es mayor o igual que', '<': 'es menor que', '<=': 'es menor o igual que' };
function fraseReglaPropia(r, catalogo) {
  let que = etiquetaMedida(r.medida, catalogo);
  if (r.segmento) que += ' en «' + r.segmento + '»';
  const umbral = r.umbral === '' || r.umbral == null || isNaN(r.umbral) ? '…' : fmt.num(Number(r.umbral)).replace(/^-/, '−');
  return que + ': ' + (MODOS_REGLA[r.modo] || r.modo) + ' ' + (OPERADOR_REGLA[r.operador] || r.operador) + ' '
       + umbral + (r.modo === 'cambio_pct' ? ' %' : '');
}
// Lo que se compara para saber si las reglas tienen cambios sin guardar: los
// numeros de un campo editado llegan como texto («20» frente a 20).
// Las reglas efectivas como formulario: el segmento vacio como '' y los
// patrones a ignorar (decision 230) como un texto, uno por linea.
function _formReglas(efectivas) {
  const f = JSON.parse(JSON.stringify(efectivas));
  f.propias.forEach(x => { x.segmento = x.segmento || ''; });
  f.ignorar_texto = (f.ignorar_en_textos || []).join('\n');
  delete f.ignorar_en_textos;
  return f;
}
function _fotoReglas(f) {
  return JSON.stringify(f, (k, v) => (typeof v === 'string' && v.trim() !== '' && !isNaN(v) ? Number(v) : v));
}
const DIAS_SEMANA = ['', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo'];


// ===== Extraccion a medida en el modal de Nuevo rastreo (#34, decision 166) =====
// Una fila por regla. Las heredadas (cliente o perfil) guardan su firma de
// origen: sin tocar no se mandan (se heredan en el servidor), cambiadas se
// mandan enteras (sustituyen por nombre) y quitadas van como `null`. Los
// campos que el formulario no edita (solo_urls, separador_decimal, grupo...)
// viajan tal cual dentro de `extra`.
const XM_CAMPOS = ['tipo', 'expresion', 'devuelve', 'atributo', 'cuantos', 'valor'];
const XM_NOMBRE = /^[a-z][a-z0-9_]{0,39}$/;
let _xmId = 0;

function _xmFila(nombre, regla, heredada) {
  const r = regla || {};
  const extra = {};
  for (const [k, v] of Object.entries(r)) if (!XM_CAMPOS.includes(k)) extra[k] = v;
  const fila = {
    _id: ++_xmId, nombre: nombre || '', heredada: !!heredada, quitada: false, origen: 'cliente',
    tipo: r.tipo || 'css', expresion: r.expresion || '', devuelve: r.devuelve || 'texto',
    atributo: r.atributo || '', cuantos: r.cuantos || 'primero', valor: r.valor || 'texto', extra,
  };
  fila._firma = heredada ? JSON.stringify(_xmRegla(fila)) : null;
  fila._original = heredada ? JSON.parse(JSON.stringify(fila)) : null;
  return fila;
}

// La regla tal como la espera `ExtractorAMedida`, sin los campos vacios.
function _xmRegla(fila) {
  const r = { ...fila.extra, tipo: fila.tipo, expresion: (fila.expresion || '').trim(),
              cuantos: fila.cuantos };
  if (fila.tipo !== 'regex') {
    r.devuelve = fila.devuelve;
    if (fila.devuelve === 'atributo') r.atributo = (fila.atributo || '').trim();
    else delete r.atributo;
  } else {
    delete r.devuelve; delete r.atributo;
  }
  if (fila.cuantos !== 'recuento') r.valor = fila.valor; else delete r.valor;
  return r;
}

function _extraccionDesdeConfig(f, cfg) {
  const ce = (cfg && cfg.custom_extraction) || {};
  f.extraccion = Object.entries(ce).filter(([, r]) => r && typeof r === 'object')
    .map(([n, r]) => _xmFila(n, r, true));
}

// Al volver a «Sin cliente»: las heredadas se quedan como propias (se ven y
// se mandan) y las quitadas desaparecen.
function _extraccionSinCliente(f) {
  f.extraccion = (f.extraccion || []).filter(fila => !(fila.heredada && fila.quitada))
    .map(fila => (fila.heredada
      ? { ...fila, heredada: false, quitada: false, _firma: null, _original: null }
      : fila));
}

// Lleva a `nuevo` (recien heredado) las reglas propias de `viejo`.
function _extraccionConservarPropias(nuevo, viejo) {
  const propias = (viejo.extraccion || []).filter(fila => !fila.heredada);
  const nombres = new Set(propias.map(fila => (fila.nombre || '').trim()).filter(Boolean));
  nuevo.extraccion = [
    ...(nuevo.extraccion || []).filter(fila => !nombres.has((fila.nombre || '').trim())),
    ...propias,
  ];
}

// Lo que se manda en `config.custom_extraction`, o null si no hay nada que
// mandar (todo heredado y sin tocar, o sin reglas). Sin cliente no hay
// herencia en el servidor: una fila marcada heredada se manda como propia.
function _extraccionAConfig(f) {
  const salida = {};
  const hereda = !!f.cliente_id;
  for (const fila of (f.extraccion || [])) {
    const nombre = (fila.nombre || '').trim();
    if (!nombre) continue;
    if (fila.heredada && hereda) {
      if (fila.quitada) salida[nombre] = null;
      else if (JSON.stringify(_xmRegla(fila)) !== fila._firma) salida[nombre] = _xmRegla(fila);
    } else if (!fila.quitada) {
      salida[nombre] = _xmRegla(fila);
    }
  }
  return Object.keys(salida).length ? salida : null;
}

/* ===== Validar una migracion (revision de UX del 25-oct, 2.13; decision 192) =====
   Antes era una casilla dentro de Comparar que pedia expresiones regulares de
   Python (V23). Ahora es una accion aparte, con un asistente: los dos censos,
   como cambian las URLs (casos comunes sin regex; las regex, plegadas en
   «Avanzado») y el resultado, que es el mismo GET /diff de siempre con
   `map_host` y `map_rutas` (decision 131): aqui no se calcula nada nuevo. */

// Los casos comunes se traducen a reglas `patron => reemplazo` de `map_rutas`.
// El servidor aplica SOLO la primera regla que casa con cada URL (como un mapa
// de redirecciones), asi que dos casos a la vez (carpeta y extension) no se
// pueden mandar como dos reglas: la URL que tiene las dos cosas solo cambiaria
// una. Se genera una regla por combinacion de casos, de la mas completa a la
// mas simple, y cada URL cae en la que le toca. Las partes de cada regla
// (texto o grupo) sirven a la vez para escribir el reemplazo de Python y para
// la vista previa del navegador: las dos salen de lo mismo y no pueden
// discrepar (lo comprueba tests/test_migracion_frontend.py contra
// `shared.comparacion._aplicar_rutas`).
const MIG_FINALES = [
  { valor: 'igual', texto: 'Igual' },
  { valor: 'quitar_ext', texto: 'Se quita la extensión (/hotel.html → /hotel)' },
  { valor: 'quitar_ext_barra', texto: 'Se quita la extensión y acaba en barra (/hotel.html → /hotel/)' },
  { valor: 'poner_barra', texto: 'Se añade la barra final (/hotel → /hotel/)' },
  { valor: 'quitar_barra', texto: 'Se quita la barra final (/hotel/ → /hotel)' },
];

function migCasosVacios() {
  return { dominio: false, hostDe: '', hostA: '', prefijo: false, prefDe: '/es/', prefA: '/',
           texto: false, textoDe: '', textoA: '', final: 'igual', ext: '.html' };
}

function _escRx(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

// [{patron, partes}] de los casos elegidos. `partes`: texto o {g: grupo}.
function reglasDeMigracion(c) {
  if (!c) return [];
  const rasgos = [];
  if (c.prefijo && c.prefDe) rasgos.push('prefijo');
  if (c.texto && c.textoDe) rasgos.push('texto');
  const conExt = ['quitar_ext', 'quitar_ext_barra'].includes(c.final);
  if (c.final && c.final !== 'igual' && (!conExt || c.ext)) rasgos.push('final');
  const combinaciones = [];
  for (let m = (1 << rasgos.length) - 1; m > 0; m--) combinaciones.push(rasgos.filter((_, i) => m & (1 << i)));
  // La mas completa primero. Una URL que casa con dos del mismo tamano tiene
  // los rasgos de las dos, y la que los junta va antes. Salvo en un borde:
  // cuando la ruta acaba JUSTO en la carpeta o el trozo, estos ya se comen la
  // barra o la extension, la regla con el final no casa y ganaria la del
  // final solo, sin cambiar la carpeta (/blog/ con «/blog/ → /» y «quitar la
  // barra» quedaba en /blog y no en /). Para eso cada combinacion con final
  // lleva antes su regla de borde: el final se aplica al texto que entra,
  // como si los cambios se hicieran uno detras de otro (revision de UX del
  // 25-oct, 2.13, hallazgo de la revision).
  combinaciones.sort((a, b) => b.length - a.length);
  const reglas = [];
  for (const s of combinaciones) {
    for (const borde of _bordesDeCasos(c, s)) reglas.push(_reglaDeCasos(c, s, borde));
    reglas.push(_reglaDeCasos(c, s));
  }
  return reglas;
}

// El final aplicado al texto que entra (lo que queda al final de la ruta
// cuando esta acaba en la carpeta o el trozo).
function _finalSobreTexto(c, t) {
  if (c.final === 'quitar_ext') return t.endsWith(c.ext) ? t.slice(0, -c.ext.length) : t;
  if (c.final === 'quitar_ext_barra') return t.endsWith(c.ext) ? t.slice(0, -c.ext.length) + '/' : t;
  if (c.final === 'poner_barra') return t.endsWith('/') ? t : t + '/';
  if (c.final === 'quitar_barra') return t.length > 1 && t.endsWith('/') ? t.slice(0, -1) : t;
  return t;
}

// Las reglas de borde de una combinacion: [{t, mas}], donde `t` es lo que
// sustituye a la carpeta o al trozo del final y `mas` pide algo delante del
// trozo. Sin final, o sin texto que entre (vacio: el final caeria en lo de
// delante, que no se conoce al escribir la regla), no hay borde.
function _bordesDeCasos(c, s) {
  if (!s.includes('final') || !(s.includes('prefijo') || s.includes('texto'))) return [];
  const ultimo = s.includes('texto') ? 'texto' : 'prefijo';
  const t = (ultimo === 'texto' ? c.textoA : c.prefA) || '';
  if (!t) return [];
  if (c.final === 'quitar_barra' && t === '/') {
    // La portada «/» se queda como esta: la carpeta que pasa a la raiz
    // (/blog/ → /) da la portada, no una ruta vacia.
    if (ultimo === 'prefijo') return [{ t: '/' }];
    // El trozo que pasa a «/» detras de algo pierde la barra; si no hay
    // nada delante, es la portada.
    if (s.includes('prefijo') && c.prefA) return [{ t: '' }];
    return [{ t: '', mas: true }, { t: '/' }];
  }
  return [{ t: _finalSobreTexto(c, t) }];
}

function _reglaDeCasos(c, s, borde) {
  let patron = '^', g = 0;
  const partes = [];
  const grupo = expr => { patron += expr; g += 1; partes.push({ g }); };
  const ultimo = s.includes('texto') ? 'texto' : 'prefijo';
  if (s.includes('prefijo')) {
    patron += _escRx(c.prefDe);
    partes.push(borde && ultimo === 'prefijo' ? borde.t : (c.prefA || ''));
  }
  if (!(borde && ultimo === 'prefijo')) grupo(borde && borde.mas ? '(.+?)' : '(.*?)');
  if (s.includes('texto')) {
    patron += _escRx(c.textoDe);
    partes.push(borde ? borde.t : (c.textoA || ''));
    if (!borde) grupo('(.*?)');
  }
  if (s.includes('final') && !borde) {
    if (c.final === 'quitar_ext') patron += _escRx(c.ext);
    else if (c.final === 'quitar_ext_barra') { patron += _escRx(c.ext); partes.push('/'); }
    // Solo si no acaba ya en barra; la portada «/» se queda como esta.
    else if (c.final === 'poner_barra') { patron += '(?<=[^/])'; partes.push('/'); }
    else if (c.final === 'quitar_barra') patron += '(?<=.)/';
  }
  grupo('(\\?.*)?');
  patron += '$';
  return { patron, partes };
}

// El reemplazo en la sintaxis de `re.sub` de Python: `\g<1>` (y no `\1`, que
// pegado a una cifra del texto seria otro grupo) y las barras invertidas dobladas.
function reemplazoPython(partes) {
  return partes.map(p => typeof p === 'string' ? p.replace(/\\/g, '\\\\') : '\\g<' + p.g + '>').join('');
}

// Lo que se manda a /diff: `[[patron, reemplazo], ...]`.
function reglasParaApi(reglas) {
  return reglas.map(r => [r.patron, r.reemplazo !== undefined ? r.reemplazo : reemplazoPython(r.partes)]);
}

// Una regla escrita a mano (Python) para la vista previa del navegador. Lo que
// JavaScript no entiende no se previsualiza: lo valida el servidor al calcular.
function _reglaJsDePython(patron, reemplazo) {
  let fuente = String(patron), flags = '';
  const inline = fuente.match(/^\(\?([aiLmsux]+)\)/);
  if (inline) {
    if (/[aLux]/.test(inline[1])) return { error: 'usa opciones de Python que el navegador no entiende' };
    flags = inline[1];
    fuente = fuente.slice(inline[0].length);
  }
  fuente = fuente.replace(/\(\?P</g, '(?<').replace(/\(\?P=(\w+)\)/g, '\\k<$1>').replace(/\\A/g, '^').replace(/\\Z/g, '$');
  let re;
  try { re = new RegExp(fuente, flags); } catch (e) { return { error: 'el navegador no puede leer el patrón: ' + e.message }; }
  const partes = [];
  let lit = '';
  const s = String(reemplazo);
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch !== '\\' || i === s.length - 1) { lit += ch; continue; }
    const sig = s[i + 1];
    let m;
    if (sig === 'g' && (m = s.slice(i).match(/^\\g<(\w+)>/))) {
      if (lit) { partes.push(lit); lit = ''; }
      partes.push({ g: /^\d+$/.test(m[1]) ? +m[1] : m[1] });
      i += m[0].length - 1;
    } else if (/\d/.test(sig)) {
      const n = s.slice(i + 1).match(/^\d{1,2}/)[0];
      if (lit) { partes.push(lit); lit = ''; }
      partes.push({ g: +n });
      i += n.length;
    } else if (sig === '\\') { lit += '\\'; i += 1; }
    else if (sig === 'n') { lit += '\n'; i += 1; }
    else if (sig === 't') { lit += '\t'; i += 1; }
    else { lit += ch; }
  }
  if (lit) partes.push(lit);
  return { re, partes };
}

// Lo mismo que `shared.comparacion._aplicar_mapa` y `_aplicar_rutas`: el host
// por el mapa y la RUTA (con su `?query`) por la primera regla que casa.
// Devuelve { url, regla } (regla = indice o null) o { error }.
function aplicarMigracion(url, reglas, mapaHost) {
  let u = String(url || '');
  let h = '';
  try { h = new URL(u).hostname.toLowerCase(); } catch (e) { h = ''; }
  if (h && mapaHost && mapaHost[h]) u = u.replace('//' + h, '//' + mapaHost[h]);
  const m = u.match(/^([a-zA-Z][a-zA-Z0-9+.-]*:\/\/[^/?#]*)([^?#]*)(\?[^#]*)?/);
  if (!m || !reglas || !reglas.length) return { url: u, regla: null };
  const origen = m[1];
  const ruta = m[2] + (m[3] && m[3] !== '?' ? m[3] : '');
  for (let i = 0; i < reglas.length; i++) {
    const r = reglas[i];
    let re = r.re, partes = r.partes;
    if (!re) {
      if (r.reemplazo !== undefined) {
        const js = _reglaJsDePython(r.patron, r.reemplazo);
        if (js.error) return { error: 'Regla ' + (i + 1) + ': ' + js.error };
        re = js.re; partes = js.partes;
      } else {
        re = new RegExp(r.patron);
      }
    }
    const x = re.exec(ruta);
    if (!x) continue;
    const grupos = x.length - 1;
    let fuera = null;
    const nuevo = partes.map(p => {
      if (typeof p === 'string') return p;
      if (typeof p.g === 'number') {
        if (p.g > grupos) fuera = p.g;
        return x[p.g] ?? '';
      }
      if (!x.groups || !(p.g in x.groups)) fuera = p.g;
      return (x.groups || {})[p.g] ?? '';
    }).join('');
    if (fuera !== null) return { error: 'Regla ' + (i + 1) + ': el reemplazo usa el grupo ' + fuera + ' y el patrón no lo tiene' };
    return { url: origen + ruta.slice(0, x.index) + nuevo + ruta.slice(x.index + x[0].length), regla: i };
  }
  return { url: u, regla: null };
}

// `viejo.com=nuevo.com` (lo que espera `map_host`) -> { 'viejo.com': 'nuevo.com' }.
function mapaDeHosts(texto) {
  const mapa = {};
  for (const par of String(texto || '').split(',')) {
    const i = par.indexOf('=');
    if (i > 0) mapa[par.slice(0, i).trim().toLowerCase()] = par.slice(i + 1).trim().toLowerCase();
  }
  return mapa;
}

// Censos en grupos por TIPO (V22): la «réplica julio» de 5.000 URLs no es un
// censo de la serie aunque tenga su tamano. El tipo es el marcado o el que
// dice el nombre (`tipo_efectivo`, `shared.clientes.tipo_de_rastreo`).
const GRUPOS_DE_TIPO = [
  { tipo: 'censo', etiqueta: 'Censos' },
  { tipo: 'canario', etiqueta: 'Canarios' },
  { tipo: 'prueba', etiqueta: 'Pruebas' },
];
// La comparacion guardada de un censo puesta en la forma del diff (V21), una
// vez por censo.
const _diffGuardadoCache = { jobId: null, c: null, va: '', valor: null };

function censosPorTipo(lista) {
  const grupos = GRUPOS_DE_TIPO.map(g => ({ ...g, items: [] }));
  for (const j of lista || []) {
    const t = j.tipo_efectivo || j.tipo || 'censo';
    (grupos.find(g => g.tipo === t) || grupos[0]).items.push(j);
  }
  return grupos.filter(g => g.items.length);
}

function _hostDe(j) {
  return ((j && j.seeds && j.seeds[0]) || '').replace(/^https?:\/\//, '').split('/')[0].toLowerCase();
}

function migracionUI() {
  return {
    migPaso: 1,
    migAntes: '',
    migDespues: '',
    migCandidatos: [],
    migCandCargando: false,
    migCandError: '',
    migCasos: migCasosVacios(),
    migAvanzado: false,
    migReglasTexto: '',
    migMuestra: [],          // URLs reales del censo de antes, para la vista previa
    migMuestraDe: '',
    migMuestraCargando: false,
    migExiste: {},           // URL ya reescrita -> true / false / 'cargando' / 'error'
    _migExisteDe: '',
    _migTemporizador: null,
    migDiff: null,
    migCargando: false,
    _migPedido: 0,
    _migDesdeRuta: null,     // lo que trae el enlace (#/rastreos/<id>/migracion?...)

    // Al abrir otro censo: lo elegido era para el anterior.
    _migReiniciar() {
      clearTimeout(this._migTemporizador);
      this._migPedido++;
      Object.assign(this, { migPaso: 1, migAntes: '', migDespues: '', migCandidatos: [], migCandError: '',
        migCasos: migCasosVacios(), migAvanzado: false, migReglasTexto: '', migMuestra: [], migMuestraDe: '',
        migExiste: {}, _migExisteDe: '', migDiff: null, migCargando: false });
    },

    // Desde el menú «…» del censo o desde Comparar.
    abrirMigracion() {
      this.menuAbierto = '';
      this.switchTab('migracion');
    },

    async prepararMigracion() {
      if (!this.job) return;
      const r = this._migDesdeRuta;
      this._migDesdeRuta = null;
      if (r) {
        this.migDiff = null; this.migMuestraDe = ''; this.migExiste = {};
        this.migCasos = migCasosVacios(); this.migAvanzado = false; this.migReglasTexto = '';
        this.migAntes = r.antes || '';
        this.migDespues = r.despues || this.job.id;
        if (r.casos) this.migCasos = { ...migCasosVacios(), ...r.casos };
        if (r.rutas) { this.migAvanzado = true; this.migReglasTexto = r.rutas; }
        this.migPaso = r.paso || 1;
      }
      if (!this.migDespues) this.migDespues = this.job.id;
      if (!this.migAntes) {
        const auto = this.job.comparacion && this.job.comparacion.comparado_con;
        if (auto && auto !== this.migDespues) this.migAntes = auto;
      }
      if (!this.migCandidatos.length || this.migCandidatos._de !== this.job.id) await this.cargarCandidatosMig();
      if (!this.migAntes) {
        const desp = this.migJob(this.migDespues);
        const previo = this.migCandidatos.find(j => j.id !== this.migDespues
          && (!desp || String(j.created_at) < String(desp.created_at)));
        if (previo) this.migAntes = previo.id;
      }
      this.migElegido(false);
      if (this.migPaso === 3 && !this.migDiff && !this.migCargando) this.calcularMigracion();
      else if (this.migPaso === 2) this.cargarMuestraMig();
    },

    // Cualquier rastreo completado del cliente (o, sin cliente, de los
    // ultimos), de cualquier dominio: una migracion cambia a menudo de dominio.
    async cargarCandidatosMig() {
      const jobId = this.job.id;
      this.migCandCargando = true;
      this.migCandError = '';
      try {
        const q = new URLSearchParams({ page: 1, page_size: 100, status: 'completed' });
        if (this.job.cliente_id) q.set('client_id', this.job.cliente_id);
        const d = await api('/jobs?' + q);
        if (!this.job || this.job.id !== jobId) return;
        const lista = d.items || [];
        // El censo abierto, aunque no este completado, para poder elegirlo.
        if (!lista.some(j => j.id === this.job.id)) lista.unshift(this.job);
        lista._de = jobId;
        this.migCandidatos = lista;
      } catch (e) {
        this.migCandError = 'No se pudieron cargar los rastreos: ' + e.message;
      } finally {
        this.migCandCargando = false;
      }
    },

    migJob(id) { return this.migCandidatos.find(j => j.id === id) || (this.job && this.job.id === id ? this.job : null); },
    migGrupos() { return censosPorTipo(this.migCandidatos); },
    migEtiqueta(j) {
      return j.name + ' · ' + fmt.num(j.total_urls_crawled) + ' URLs · ' + fmt.dia(j.started_at || j.created_at);
    },
    migFecha(j) { return j ? String(j.started_at || j.created_at || '') : ''; },

    // Que hay de malo en la pareja elegida, o '' si nada.
    migProblemaPareja() {
      if (!this.migAntes || !this.migDespues) return 'Elige los dos censos.';
      if (this.migAntes === this.migDespues) return 'Son el mismo censo: elige uno de antes y otro de después de la migración.';
      const a = this.migJob(this.migAntes), d = this.migJob(this.migDespues);
      if (a && d && this.migFecha(a) && this.migFecha(d) && this.migFecha(a) > this.migFecha(d)) {
        return 'El censo de «antes» es posterior al de «después». El mapeo de URLs se aplica siempre al más antiguo.';
      }
      return '';
    },
    migIntercambiar() {
      [this.migAntes, this.migDespues] = [this.migDespues, this.migAntes];
      this.migElegido(true);
    },

    // Al cambiar de censo: si son de dominios distintos, el cambio de dominio
    // se propone ya relleno (sin el, el servidor rechaza dos origenes).
    migElegido(cambio = true) {
      const a = this.migJob(this.migAntes), d = this.migJob(this.migDespues);
      const ha = _hostDe(a), hd = _hostDe(d);
      if (ha && hd && ha !== hd && (cambio || !this.migCasos.hostDe)) {
        this.migCasos.dominio = true;
        this.migCasos.hostDe = ha;
        this.migCasos.hostA = hd;
      } else if (!this.migCasos.hostDe && ha) {
        this.migCasos.hostDe = ha;
        this.migCasos.hostA = hd || ha;
      }
      if (cambio) { this.migDiff = null; this.migMuestra = []; this.migMuestraDe = ''; this.migExiste = {}; }
    },
    migHostsDistintos() {
      const ha = _hostDe(this.migJob(this.migAntes)), hd = _hostDe(this.migJob(this.migDespues));
      return !!(ha && hd && ha !== hd);
    },

    // Las reglas que se van a mandar: las de los casos o, en «Avanzado», las
    // escritas a mano (una por linea, `patron => reemplazo`).
    migReglas() {
      if (this.migAvanzado) {
        return (this.migReglasTexto || '').split('\n').map(l => l.trim()).filter(Boolean).map(l => {
          const i = l.indexOf(' => ');
          return i < 0 ? { patron: l, reemplazo: '' } : { patron: l.slice(0, i).trim(), reemplazo: l.slice(i + 4).trim() };
        });
      }
      return reglasDeMigracion(this.migCasos);
    },
    migMapHost() {
      const c = this.migCasos;
      if (!c.dominio) return '';
      const de = (c.hostDe || '').trim().toLowerCase(), a = (c.hostA || '').trim().toLowerCase();
      return de && a && de !== a ? de + '=' + a : '';
    },
    migSinCambios() { return !this.migMapHost() && !this.migReglas().length; },

    // Pasar de los casos a las regex, con lo elegido ya escrito.
    migEditarRegex() {
      this.migReglasTexto = reglasParaApi(reglasDeMigracion(this.migCasos)).map(([p, r]) => p + ' => ' + r).join('\n');
      this.migAvanzado = true;
      this.migProgramarComprobacion();
    },
    migVolverACasos() {
      this.migAvanzado = false;
      this.migProgramarComprobacion();
    },

    migIrAPaso(n) {
      if (n >= 2 && this.migProblemaPareja()) return;
      this.migPaso = n;
      window.scrollTo({ top: 0 });
      if (n === 2) this.cargarMuestraMig();
      if (n === 3) this.calcularMigracion();
    },

    // Unas URLs reales del censo de antes: paginas HTML internas.
    async cargarMuestraMig() {
      const id = this.migAntes;
      if (!id || this.migMuestraDe === id) { this.migProgramarComprobacion(); return; }
      this.migMuestraCargando = true;
      try {
        const q = new URLSearchParams({ page: 1, page_size: 200, ligero: 'true', is_internal: 'true', resource_type: 'html' });
        const d = await api(`/jobs/${id}/urls?` + q);
        if (this.migAntes !== id) return;
        this.migMuestra = (d.items || []).map(u => u.url).filter(Boolean);
        this.migMuestraDe = id;
      } catch (e) {
        this.migMuestra = [];
      } finally {
        this.migMuestraCargando = false;
      }
      this.migProgramarComprobacion();
    },

    // Cinco URLs con como quedan: primero las que alguna regla cambia (de
    // tramos distintos de la lista, para que no salgan cinco iguales), y si no
    // hay bastantes, las primeras.
    migVistaPrevia() {
      const reglas = this.migReglas(), mapa = mapaDeHosts(this.migMapHost());
      const filas = [];
      for (const u of this.migMuestra) {
        const r = aplicarMigracion(u, reglas, mapa);
        if (r.error) return [{ antes: u, error: r.error }];
        filas.push({ antes: u, despues: r.url, regla: r.regla, cambia: r.url !== u });
      }
      const cambian = filas.filter(f => f.cambia), quietas = filas.filter(f => !f.cambia);
      const elegidas = [];
      if (cambian.length) {
        const paso = Math.max(1, Math.floor(cambian.length / 5));
        for (let i = 0; i < cambian.length && elegidas.length < 5; i += paso) elegidas.push(cambian[i]);
      }
      for (const f of quietas) { if (elegidas.length >= 5) break; elegidas.push(f); }
      return elegidas;
    },
    migCuantasCambian() {
      const reglas = this.migReglas(), mapa = mapaDeHosts(this.migMapHost());
      let n = 0;
      for (const u of this.migMuestra) { const r = aplicarMigracion(u, reglas, mapa); if (!r.error && r.url !== u) n++; }
      return n;
    },

    // ¿Existe la URL ya reescrita en el censo de después? Se busca y se mira
    // que este tal cual: la busqueda casa por trozo. Con un retardo, para no
    // pedir nada mientras se escribe. Ordenada por URL, la exacta va antes que
    // las que empiezan por ella; aun asi, si la busqueda trae mas de lo que
    // cabe en una pagina y la exacta no esta, no se afirma que falte: se dice
    // que no se ha podido comprobar (lo que no se puede afirmar no se afirma;
    // revision de UX del 25-oct, 2.13, hallazgo de la revision).
    migProgramarComprobacion() {
      clearTimeout(this._migTemporizador);
      this._migTemporizador = setTimeout(() => this.comprobarVistaPrevia(), 450);
    },
    async comprobarVistaPrevia() {
      const desp = this.migDespues;
      if (!desp || this.migPaso !== 2) return;
      if (this._migExisteDe !== desp) { this.migExiste = {}; this._migExisteDe = desp; }
      for (const f of this.migVistaPrevia()) {
        if (f.error || !f.despues || this.migExiste[f.despues] !== undefined) continue;
        this.migExiste = { ...this.migExiste, [f.despues]: 'cargando' };
        try {
          const q = new URLSearchParams({ page: 1, page_size: 200, ligero: 'true', sort_by: 'url',
                                          sort_dir: 'asc', search: f.despues });
          const d = await api(`/jobs/${desp}/urls?` + q);
          const sin = x => String(x).split('#')[0];
          const items = d.items || [];
          const esta = items.some(x => sin(x.url) === sin(f.despues))
            || ((d.total || 0) > items.length ? 'sin_comprobar' : false);
          if (this.migDespues === desp) this.migExiste = { ...this.migExiste, [f.despues]: esta };
        } catch (e) {
          if (this.migDespues === desp) this.migExiste = { ...this.migExiste, [f.despues]: 'error' };
        }
      }
    },
    migTextoExiste(f) {
      const v = this.migExiste[f.despues];
      if (v === undefined || v === 'cargando') return 'buscando en el censo de después…';
      if (v === 'error') return 'no se ha podido comprobar';
      if (v === 'sin_comprobar') return 'no se ha podido comprobar (hay demasiadas URLs parecidas en el censo de después)';
      if (v) return 'está en el censo de después';
      const d = this.migJob(this.migDespues);
      // Lo que no se puede afirmar no se afirma: un censo incompleto puede no
      // haberla visto.
      return 'no aparece tal cual en el censo de después' + (d && (d.status !== 'completed' || d.finish_reason !== 'finished') ? ' (que no terminó entero)' : '');
    },

    // El resultado es el GET /diff de siempre con el mapeo (decision 131).
    async calcularMigracion() {
      if (this.migProblemaPareja()) { this.migPaso = 1; return; }
      const pedido = ++this._migPedido;
      this.migCargando = true;
      this.migDiff = null;
      try {
        const q = new URLSearchParams();
        const host = this.migMapHost();
        if (host) q.set('map_host', host);
        const reglas = reglasParaApi(this.migReglas());
        if (reglas.length) q.set('map_rutas', JSON.stringify(reglas));
        const qs = q.toString();
        const r = await api(`/jobs/${this.migDespues}/diff/${this.migAntes}` + (qs ? '?' + qs : ''));
        if (pedido !== this._migPedido) return;
        this.migDiff = { ...r, _clave: 'm' + pedido, _migracion: true };
      } catch (e) {
        if (pedido !== this._migPedido) return;
        // Un 422 de una regex que no compila dice cual: se ensena tal cual.
        this.migDiff = { comparable: false, motivo: 'No se pudo calcular: ' + (e.message || e), _clave: 'm' + pedido, _migracion: true };
      } finally {
        if (pedido === this._migPedido) this.migCargando = false;
      }
    },

    // Cuantas URLs de antes tienen pareja despues: con reglas lo da
    // `mapeo_rutas`; sin ellas (solo dominio), `urls`.
    migEmparejadas() {
      const d = this.migDiff;
      if (!d || !d.comparable) return null;
      const m = d.mapeo_rutas;
      if (m) return { de: m.urls_del_anterior, si: m.emparejadas, pct: m.pct_emparejadas };
      const u = d.urls || {};
      const de = (u.en_ambos || 0) + (u.desaparecidas ?? u.desaparecidas_no_afirmables ?? 0);
      return { de, si: u.en_ambos || 0, pct: u.pct_emparejadas_del_anterior ?? (de ? Math.round(1000 * (u.en_ambos || 0) / de) / 10 : null) };
    },
    migRutaQuery() {
      const q = new URLSearchParams();
      if (this.migAntes) q.set('antes', this.migAntes);
      if (this.migDespues && this.job && this.migDespues !== this.job.id) q.set('despues', this.migDespues);
      if (this.migPaso > 1) q.set('paso', this.migPaso);
      if (this.migAvanzado) {
        if (this.migReglasTexto.trim()) q.set('rutas', this.migReglasTexto.trim());
      } else {
        const c = this.migCasos, v = migCasosVacios();
        // Los dominios solo si se ha marcado el cambio: si no, son el relleno.
        const dif = Object.fromEntries(Object.entries(c).filter(([k, x]) => x !== v[k]
          && (c.dominio || !['hostDe', 'hostA'].includes(k))));
        if (Object.keys(dif).length) q.set('casos', JSON.stringify(dif));
      }
      if (this.migAvanzado && this.migCasos.dominio) q.set('casos', JSON.stringify({ dominio: true, hostDe: this.migCasos.hostDe, hostA: this.migCasos.hostA }));
      return q.toString();
    },
    migLeerRuta(q) {
      let casos = null;
      try { casos = q.get('casos') ? JSON.parse(q.get('casos')) : null; } catch (e) { casos = null; }
      if (casos && typeof casos !== 'object') casos = null;
      const paso = Math.min(3, Math.max(1, +(q.get('paso') || 1) || 1));
      this._migDesdeRuta = { antes: q.get('antes') || '', despues: q.get('despues') || '', casos, rutas: q.get('rutas') || '', paso };
    },
  };
}

function extraccionUI() {
  return {
    extraccionPrueba: { url: '', cargando: false, error: null, resultado: null },

    extraccionActivas() {
      return ((this.createForm && this.createForm.extraccion) || []).filter(r => !r.quitada).length;
    },
    extraccionNueva() {
      this.createForm.extraccion.push(_xmFila('', null, false));
      this.$nextTick(() => window.lucide && lucide.createIcons());
    },
    extraccionQuitar(i) {
      const fila = this.createForm.extraccion[i];
      if (fila.heredada) fila.quitada = true;
      else this.createForm.extraccion.splice(i, 1);
    },
    extraccionRestaurar(i) {
      const fila = this.createForm.extraccion[i];
      if (!fila._original) return;
      const copia = JSON.parse(JSON.stringify(fila._original));
      this.createForm.extraccion.splice(i, 1, { ...copia, _id: ++_xmId, origen: fila.origen,
                                                _original: fila._original });
    },
    extraccionTocada(fila) {
      return !!fila.heredada && JSON.stringify(_xmRegla(fila)) !== fila._firma;
    },
    // Lo que se puede decir sin preguntar al servidor; el resto es su 422.
    extraccionErrorNombre(fila, i) {
      if (fila.quitada) return '';
      const n = (fila.nombre || '').trim();
      if (!n) return 'Falta el nombre';
      if (!XM_NOMBRE.test(n)) return 'Nombre: minúsculas, cifras y _, empezando por letra';
      if (this.createForm.extraccion.some((o, j) => j !== i && !o.quitada && (o.nombre || '').trim() === n)) {
        return 'Nombre repetido';
      }
      return '';
    },
    // ¿Cliente o perfil? config-resuelta da la fusion; el perfil se mira aparte.
    extraccionMarcarOrigen() {
      const f = this.createForm;
      const perfil = (this.createPerfiles || []).find(p => p.id === f.profile_id);
      const delPerfil = (perfil && perfil.config && perfil.config.custom_extraction) || {};
      for (const fila of f.extraccion) {
        if (!fila.heredada) continue;
        fila.origen = Object.prototype.hasOwnProperty.call(delPerfil, fila.nombre) ? 'perfil' : 'cliente';
        fila._original.origen = fila.origen;
      }
      if (!this.extraccionPrueba.url) {
        this.extraccionPrueba.url = (f.seeds || '').split('\n').map(x => x.trim()).filter(Boolean)[0] || '';
      }
    },
    async probarExtraccion() {
      const p = this.extraccionPrueba;
      const f = this.createForm;
      p.cargando = true; p.error = null; p.resultado = null;
      try {
        if (!p.url) p.url = (f.seeds || '').split('\n').map(x => x.trim()).filter(Boolean)[0] || '';
        const cuerpo = { url: (p.url || '').trim(), custom_extraction: _extraccionAConfig(f) || {} };
        if (f.cliente_id) cuerpo.cliente_id = f.cliente_id;
        if (f.profile_id) cuerpo.profile_id = f.profile_id;
        // El user agent y la huella solo si este rastreo los cambia: si no,
        // la API usa los heredados del cliente y el perfil (decision 196).
        const i = this.cfgRastreo;
        if (i && cfgTiene(i, 'user_agent')) cuerpo.user_agent = cfgEfectivo(i, 'user_agent');
        if (i && cfgTiene(i, 'impersonate')) cuerpo.impersonate = cfgEfectivo(i, 'impersonate');
        p.resultado = await api('/extraccion/probar', { method: 'POST', body: JSON.stringify(cuerpo) });
      } catch (e) {
        p.error = e.message;
      }
      p.cargando = false;
    },
  };
}


/* ===== robots.txt de prueba (decision 171) =====
   Pega un robots.txt (o carga el guardado de un host del censo), unas URLs y
   unos agentes, y el servidor dice el veredicto y la linea que decide con la
   MISMA logica que el crawler (`shared/robots_regla.py`). No descarga nada. */
function robotsPruebaUI() {
  return {
    robotsPrueba: { texto: '', urls: '/', agentes: 'Googlebot\nOAI-SearchBot\nGPTBot',
                    modo: 'google', cargando: false, error: null, resultado: null },

    async robotsPruebaCargar(origen) {
      const p = this.robotsPrueba;
      p.error = null;
      try {
        const r = await api(`/jobs/${this.job.id}/robots/cuerpo?origen=${encodeURIComponent(origen)}`);
        p.texto = r.cuerpo || '';
      } catch (e) { p.error = e.message; }
    },

    async robotsPruebaEvaluar() {
      const p = this.robotsPrueba;
      const lineas = t => (t || '').split('\n').map(x => x.trim()).filter(Boolean);
      p.error = null; p.resultado = null; p.cargando = true;
      try {
        p.resultado = await api('/robots/probar', {
          method: 'POST',
          body: JSON.stringify({ robots_txt: p.texto, urls: lineas(p.urls),
                                 agentes: lineas(p.agentes), modo: p.modo }),
        });
      } catch (e) { p.error = e.message; }
      finally { p.cargando = false; }
    },

    robotsPruebaMotivo(m) {
      return ({ directiva_desconocida: 'directiva que no se lee',
                regla_sin_user_agent: 'regla antes de cualquier User-agent: no es de ningún grupo',
                regla_tras_user_agent_vacio: 'regla tras un User-agent vacío: no es de ningún grupo',
                no_es_directiva: 'no es una directiva' })[m] || m;
    },
  };
}
