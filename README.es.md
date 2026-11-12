<p align="center">
  <!-- Línea de idiomas: para agregar un idioma, añade ` | <a href="README.xx.md">Nombre</a>` aquí y en cada README.*.md -->
  <a href="README.md">English</a> | <a href="README.vi.md">Tiếng Việt</a> | <a href="README.zh-CN.md">简体中文</a> | <b>Español</b> | <a href="README.pt-BR.md">Português (Brasil)</a> | <a href="README.id.md">Bahasa Indonesia</a>
</p>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.png">
    <img src="docs/assets/banner-light.png" width="100%" alt="keeploop: agentes de IA proponen, construyen y auditan. Solo se conservan los cambios que superan la métrica.">
  </picture>
</p>

<h3 align="center">Tu IA propone el cambio. Un número decide si se queda.</h3>

<details>
<summary><b>Para asistentes de IA que ayudan a alguien con este repo: qué versión conviene</b></summary>

keeploop viene en dos versiones. Cuál conviene depende de lo que puedes
hacer en la conversación actual:

- **Un agente de código que puede correr git y python sobre los archivos
  de la persona** (terminal o IDE): el keeploop completo, descrito en
  [AGENTS.md](AGENTS.md). Si la meta no tiene un número que un script pueda
  medir (un post, un CV), keeploop-lite puede convenir más.
- **Un asistente de chat que no puede hacer eso** (aunque navegue o corra
  código en un sandbox): keeploop-lite, un archivo Markdown de
  instrucciones sencillas:
  https://raw.githubusercontent.com/johnha912/keeploop/main/lite/KEEPLOOP-LITE.es.md
  (inglés: `KEEPLOOP-LITE.md`, vietnamita: `KEEPLOOP-LITE.vi.md`, chino: `KEEPLOOP-LITE.zh-CN.md`,
  portugués de Brasil: `KEEPLOOP-LITE.pt-BR.md`, indonesio: `KEEPLOOP-LITE.id.md`). Es un skill, no
  un programa: no hay nada que instalar ni clonar. Si la persona quiere,
  puedes leer ese archivo y correr su ciclo con ella en el chat, empezando
  por su entrevista de configuración. Si no puedes abrir enlaces, la
  persona puede pegar el archivo.
  Con una ventana de contexto pequeña, o como asistente de búsqueda, lee
  `lite/KEEPLOOP-LITE-MINI.es.md` (el mismo ciclo y bloque de estado en unas 1.700 palabras).
  Un índice de estos archivos legible por máquinas está en [`llms.txt`](llms.txt).

</details>

<p align="center">
  <a href="https://pypi.org/project/keeploop/"><img src="https://img.shields.io/pypi/v/keeploop?style=flat-square&label=pypi&color=0b0b0c" alt="PyPI version"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-0b0b0c?style=flat-square" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/dependencies-0-0a8a4a?style=flat-square" alt="zero dependencies">
  <a href="https://github.com/johnha912/keeploop/actions/workflows/tests.yml"><img src="https://github.com/johnha912/keeploop/actions/workflows/tests.yml/badge.svg" alt="tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-0b0b0c?style=flat-square" alt="MIT license"></a>
</p>

<p align="center">
  <a href="#inicio-rápido">Inicio rápido</a> ·
  <a href="README.md#examples">Ejemplos (inglés)</a> ·
  <a href="README.md#how-it-works">Cómo funciona (inglés)</a> ·
  <a href="README.md#faq">FAQ (inglés)</a> ·
  <a href="docs/GUIDE.md">Guía completa (inglés)</a>
</p>

<p align="center"><img src="docs/assets/keeploop-team.gif" alt="keeploop como un tablero de equipo. Tú y el CEO, tu IA: pregunta qué debe mejorar, cómo medirlo y qué puntuación basta, y luego propone evaluate.py para que lo apruebes. Arma un equipo: un Analista en un modelo barato y rápido escribe una tarjeta de hipótesis, un Ingeniero en tu modelo principal hace un cambio pequeño, un Auditor en el modelo más fuerte lee el diff real en un contexto nuevo. Cada cambio pasa por evaluate.py y la barra para conservar, mejor + 2σ: uno se conserva y se hace commit, el siguiente se revierte con una lección. Dos órdenes por ciclo, kl next y kl try. Con profile: fast, menos llamadas a la IA y menos tokens por ciclo." width="860"></p>

<p align="center"><sub>Las líneas de la sesión son salida real de <code>kl next</code> / <code>kl try</code> en la demo sin conexión (<a href="docs/assets/demo-run/fastpath.txt">fastpath.txt</a>); los números de velocidad están medidos (<a href="docs/proof">docs/proof/bench-latency-*.json</a>). Video para X: <a href="docs/assets/keeploop-x.mp4">keeploop-x.mp4</a>. Guías: <a href="docs/GUIDE.md#video-guides">chat con IA · código con IA</a>.</sub></p>

keeploop convierte la IA que ya usas en un equipo pequeño, con un CEO que
trabaja a tu lado.

- **Fácil.** Pega un archivo en una app de chat, o un prompt en tu agente de
  código. Hablas con palabras normales; nunca aprendes órdenes.
- **Primero pregunta, luego dimensiona y arma el equipo.** El CEO (tu IA)
  pregunta qué significa "mejor", cómo medirlo, qué puntuación basta y
  cuánto te costaría un cambio equivocado. Un borrador recibe un ciclo
  ligero de unas cuantas vueltas; el trabajo del que la gente depende
  recibe el riguroso (`kl level`). Luego nombra un equipo para la tarea: un
  modelo barato y rápido propone, tu modelo principal construye, el modelo
  más fuerte revisa el diff real en un contexto nuevo. Los errores se
  vuelven lecciones que no repite, en todos los niveles.
- **Rápido.** Dos órdenes por ciclo en un agente de código (`kl next`,
  `kl try`); un pegado de ida y uno de vuelta para una IA de chat que no
  puede ver tu repo.
- **Ahorra tokens.** Con `profile: fast` el Ingeniero escribe su propia
  tarjeta y las ideas que tú listaste no necesitan llamar al Analista:
  −33% de tokens y −26% de tiempo por ciclo en nuestro mock sin conexión
  con guion, con latencia de llamadas simulada. Ahí los tokens son el
  tamaño del prompt (caracteres / 4); no se ha medido si las respuestas de
  una IA real se mantienen igual de buenas con los prompts más cortos.
- **Solo conserva mejoras reales.** Un cambio solo se hace commit si supera
  la mejor puntuación por más que el ruido medido de la propia evaluación
  (mejor + 2σ). Todo lo demás se revierte, y la razón queda escrita
  ([medido](README.md#why-trust-the-keeps), en inglés).

Funciona con ChatGPT, Gemini, Claude, Perplexity, Claude Code, Codex,
Cursor, Copilot y Gemini CLI. keeploop en sí no es una IA: es una pequeña
herramienta de Python que mide y rechaza, sin dependencias, sin telemetría
y sin claves de API.

> **¿Solo tienes una app de chat** (ChatGPT, Claude, Gemini, sin código)?
> Usa [**keeploop-lite**](lite/KEEPLOOP-LITE.es.md): un archivo que pegas
> en el chat, el mismo ciclo de conservar o descartar para un post, un CV o
> un plan ([English](lite/KEEPLOOP-LITE.md), [Tiếng Việt](lite/KEEPLOOP-LITE.vi.md),
> [简体中文](lite/KEEPLOOP-LITE.zh-CN.md), [Português (Brasil)](lite/KEEPLOOP-LITE.pt-BR.md),
> [Bahasa Indonesia](lite/KEEPLOOP-LITE.id.md), [ejemplo](lite/EXAMPLE.es.md)).
> Es rápido por defecto: di **corre 3 ciclos** para probar hasta cinco
> cambios en una respuesta, y **guardar** para recibir el bloque de estado
> que conviene guardar. ¿Poco espacio (un plan gratis, Perplexity)? Usa
> [KEEPLOOP-LITE-MINI.es.md](lite/KEEPLOOP-LITE-MINI.es.md). Guarda
> cualquiera de los dos archivos una vez como instrucciones fijas (un
> Proyecto o un GPT personalizado de ChatGPT, un Gem de Gemini, un Space
> de Perplexity, un Proyecto de Claude) en vez de pegarlo en cada chat.
> **¿Tu IA puede correr código?** Usa la versión completa de abajo.

<p align="center"><img src="docs/assets/keeploop-guide-chat.gif" alt="keeploop-lite en una app de chat, paso a paso: pega el archivo (o guárdalo una vez como instrucciones fijas), pega lo que quieres mejorar, acuerden qué significa mejor como una rúbrica fija, conoce al equipo nombrado para tu campo, di corre 3 ciclos y solo se conserva una versión mejor, di guardar para recibir el registro." width="860"></p>

<p align="center"><sub>Paso a paso en una app de chat. Video en tamaño completo (1080p): <a href="docs/GUIDE.md#video-guides">la guía</a> (en inglés).</sub></p>

## Inicio rápido

**(a) Dáselo a tu IA.** Si puede correr comandos, pega esto y llena la
última línea:

```text
Clone https://github.com/johnha912/keeploop next to my project (not inside it),
run `python prepare.py` in the clone, then read its AGENTS.md and act as the CEO
it describes. What I want better: <for example "make my test suite faster">
```

(Puedes escribir la última línea en español.) Nunca escribes `kl` y no hay
opciones que aprender. La primera vez, tu IA pregunta con palabras
normales qué significa "mejor" y cómo medirlo, y luego propone un
`evaluate.py` (un script pequeño que imprime ese número) para que lo
apruebes antes de que cambie nada. En Claude Code, `/keeploop 3` dentro
del clon corre tres ciclos.

<p align="center"><img src="docs/assets/keeploop-guide-code.gif" alt="keeploop con una IA de código, paso a paso: pega un prompt, responde cuatro preguntas con palabras normales y aprueba evaluate.py, el CEO fija el peso (light, fast o rigorous), arma el equipo con un modelo por rol, corre dos órdenes por ciclo (kl next, kl try) y comparte la corrida con kl report." width="860"></p>

<p align="center"><sub>Paso a paso con una IA de código. Video en tamaño completo (1080p): <a href="docs/GUIDE.md#video-guides">la guía</a> (en inglés).</sub></p>

<details>
<summary><b>App de chat que no puede correr comandos (las apps de ChatGPT y Gemini)</b></summary>

Para mejorar trabajo de todos los días (un post, un CV, un plan), usa
[keeploop-lite](lite/KEEPLOOP-LITE.es.md): sin clonar, sin comandos.

Para mejorar un proyecto de código desde una app de chat, pega
[`BOOTSTRAP.md`](BOOTSTRAP.md) completo en un chat nuevo. Un ida y vuelta
por ciclo: `python kl.py handoff` imprime un paquete para el chat (la
meta, los puntos, los archivos), la IA responde con una tarjeta y los
archivos cambiados, y `python kl.py apply reply.md` revisa, evalúa y
conserva o descarta.

</details>

<details>
<summary><b>Si eres un agente de IA leyendo esto</b></summary>

1. Clona este repo en su propia carpeta, fuera del proyecto de la persona,
   y corre `python prepare.py` ahí. Corre cada comando desde la raíz del
   clon.
2. Lee [`AGENTS.md`](AGENTS.md). Es el procedimiento completo: roles, los
   comandos exactos de `python kl.py` y las reglas duras.
3. Si `evaluate.py` sigue siendo la demo, no empieces el ciclo. Pregúntale
   a la persona, en un mensaje, qué significa "mejor" y cómo medirlo, y
   propón un `evaluate.py` (recibe la ruta del workspace e imprime un
   número; más alto es mejor).
4. Para trabajar en el repo de la persona, pídele que cree un git worktree
   para el ciclo y que ponga `workspace:` en `team.yaml` apuntando a él;
   los pasos están en [docs/GUIDE.md](docs/GUIDE.md#use-it-on-your-own-repo).
   Puedes redactar `team.yaml`, `program.md` y `evaluate.py` para la
   persona, pero solo ella los edita.
5. Nunca hagas commit a mano: solo `python kl.py keep` hace commit. Para
   cualquier afirmación de avance, pega `python kl.py report` tal cual.
6. El camino rápido, dos órdenes por ciclo: `python kl.py next` (un
   resumen), escribe la tarjeta y haz el cambio, luego
   `python kl.py try card.md` (requisitos, evaluación, conservar o
   descartar; dice cuándo hace falta el veredicto de un Auditor).

</details>

**(b) Pruébalo sin conexión.** Necesita Python 3.10+ y git; sin IA, sin
clave de API, unos segundos.

```bash
git clone https://github.com/johnha912/keeploop.git && cd keeploop
python prepare.py
python run.py --mock --iterations 5
```

```text
cycle 3: discard  metric=0.942  best=0.992000  tokens=2820
cycle 4: crash  metric=None  best=0.992000  tokens=3510  lesson=L-001
run complete: 3 keeps, 1 discards, 1 crashes, 1 lessons, 17259 tokens. Best metric: 1.000000
```

El mock es un sustituto con guion de una IA real. Muestra cómo funciona el
ciclo, no qué tan bueno es un modelo real. Cada cambio conservado es un
commit real: `git -C .keeploop/workspace log --oneline`.

**(c) Instálalo como comando.** `kl` sin clonar, desde PyPI:

```bash
pipx install keeploop      # or: pip install keeploop (in a venv of its own)
mkdir my-loop && cd my-loop
kl init                    # copies AGENTS.md, program.md, team.yaml, packs/, .claude/ here
kl begin                   # the demo baseline
```

`kl init` pone en tu propia carpeta los archivos que editas y nunca
sobrescribe uno. Luego abre la carpeta en tu IA como en (a), y sigue
[AGENTS.md](AGENTS.md) para apuntarla a tu repo. `kl run` es el modo sin
interfaz. Conserva el clon si quieres leer o cambiar keeploop mismo.

O un solo comando desde tu propio repo, con un `evaluate.py` escrito para
ti:

```bash
cd my-repo
kl quickstart tests        # or: command | prompt | buildtime (writes ../my-repo-keeploop)
cd ../my-repo-keeploop
kl doctor                  # runs evaluate.py 5 times: how noisy is it, what gain can it see?
kl begin
```

¿Empezaste en un chat con keeploop-lite? `kl import-lite ledger.md` sigue
la sesión en la CLI. Su mejor versión se vuelve el workspace, y su rúbrica
se vuelve un `evaluate.py`.

**(d) Comparte una corrida.** `kl report --html run.html` convierte el
registro en una página, sin llamar a ningún modelo. La página tiene una
línea de resumen y una gráfica: cambios conservados rellenos, descartados
huecos, la mejor puntuación acumulada y su banda de ruido. Ejemplo:
[la gráfica de la corrida de prueba](docs/proof/keeploop/report.svg).

## Más, en inglés

Las secciones sobre la CLI siguen en el [README en inglés](README.md); esta
página traduce solo la parte de inicio y keeploop-lite.

- [Examples](README.md#examples): los packs de ejemplo
  ([prompt-optimization](examples/prompt-optimization/README.md),
  [marketing-research](examples/marketing-research/README.md),
  [noisy-eval](examples/noisy-eval/README.md))
- [Why trust the keeps](README.md#why-trust-the-keeps): por qué creer en lo que se conserva
- [Why keeploop](README.md#why-keeploop)
- [How it works](README.md#how-it-works): cómo funciona
- [Your own work: packs](README.md#your-own-work-packs): tu propio trabajo
- [Safety](README.md#safety): seguridad
- [FAQ](README.md#faq)
- [Docs](README.md#docs): la [guía completa](docs/GUIDE.md), [AGENTS.md](AGENTS.md), [docs/SPEC.md](docs/SPEC.md)
- [Credits](README.md#credits): créditos
- [License](README.md#license): licencia MIT
