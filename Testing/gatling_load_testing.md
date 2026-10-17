# Нагрузочное тестирование с помощью Gatling

**Актуально для:** Gatling 3.15.x (Community) / Gatling Enterprise 1.15.x / Scala 2.13 / Java 17+

## Определения

**Gatling** — open-source инструмент нагрузочного тестирования на JVM. Сценарии пишутся на **Scala (Domain Specific Language)** либо — в версии Enterprise — через No-Code UI, а также на **Java** и **Kotlin** (с 3.7+). Ключевые преимущества: высокая производительность генератора (Netty/actor-модель), асинхронная обработка запросов, детальные HTML-отчёты и открытая модель нагрузки. Актуальная стабильная ветка Community — **3.15.x** (Apache-2.0 для открытой части; Enterprise-модули проприетарные).

**Gatling Enterprise** — коммерческая плацформа: распределённая нагрузка, CI/CD-интеграция, LDAP/SAML-аутентификация, централизованное хранилище отчётов, дашборды.

**Scenario / Simulation** — сценарий (низкоуровневый, последовательность запросов) и симуляция (высокоуровневый тест-класс на Scala/Java, оборачивающий один или несколько сценариев с профилем нагрузки и assertions).

**Protocol** — конфигурация HTTP-клиента Gatling (baseUrl, headers, SSL, connection pool).

## Архитектура и принцип работы

### Модель исполнения: Akka actors + Netty

Gatling построен на **Akka actors + Netty**: каждый виртуальный пользователь (VU) — это лёгкий асинхронный поток исполнения, который не блокирует OS-thread при ожидании ответа. Благодаря этому один узел может генерировать десятки тысяч одновременных пользователей с малым потреблением памяти.

В отличие от JMeter (1 поток = 1 пользователь, `Thread Group`), в Gatling **user ≠ thread** — отсюда значительно меньшие накладные расходы (context switching, memory) на высоких нагрузках. Один экземпляр Gatling может генерировать ~50 000–200 000 VU в зависимости от сложности сценария и latency цели.

### Pipeline выполнения

1. **Compiler** — Scala/Java-симуляция компилируется в байткод; Gatling проверяет syntax и ссылается на симуляцию по имени (`-s`).
2. **Injector** — создает VU-ы согласно профилю (`inject`/`setUp`); управляет ramp-up, constant, spike.
3. **Request engine** — Netty-клиент асинхронно отправляет HTTP-запросы, собирает ответы, выполняет `checks` (assertions на статус, тело, таймаут).
4. **Metrics collector** — агрегирует statistics (latency, RPS, errors) и пишет в `.json`/HTML-отчёт.

### Модель нагрузки — open loop

Gatling использует **Open Loop-модель** по умолчанию: `constantUsersPerSec` и `rampUsersPerSec` задают фиксированную частоту запросов в секунду, независимо от того, завершился ли предыдущий запрос. Это исключает **Coordinated Omission** — методологическую ошибку, при которой в Closed Loop-модели (как в JMeter по умолчанию) фактический RPS падает при деградации, а перцентили искажаются.

Подробнее о различиях моделей нагрузки: [Методология тестирования производительности](./performance_testing_methodology.md#модели-нагрузки-workload-models).

## Практические сценарии

### Сценарий 1: Установка и быстрый старт

**Prerequisites:** Java 17+ (JDK), Scala не требуется (Gatling bundle уже включает runtime), доступ к Maven/Gradle-репозиториям.

```bash
# Скачивание библиотекарного bundle
curl -s https://repo.maven.apache.org/maven2/io/gatling/highcharts/gatling-toolchain-bundle/3.15.0/gatling-toolchain-bundle-3.15.0-bundle.zip -o gatling.zip
unzip gatling.zip && cd gatling-3.15.0

# Запуск примера
./bin/gatling.sh -s computerdatabase.BasicSimulation
```

```bash
# С Maven
mvn archetype:generate \
  -DarchetypeGroupId=io.gatling.archetypes \
  -DarchetypeArtifactId=gatling-maven-plugin-demo \
  -DgatlingVersion=3.15.0
cd gatling-project && mvn gatling:test
```

**Валидация:**

```bash
ls target/gatling/BasicSimulation-*  # → HTML report directory
# Отчёт открывается в браузере: file://$(pwd)/target/gatling/.../index.html
```

### Сценарий 2: Минимальная симуляция (Scala DSL)

Пример простейшей симуляции с assertion на p95 и error rate:

```scala
import io.gatling.core.Predef._
import io.gatling.http.Predef._

class BasicSimulation extends Simulation {
  val httpProtocol = http
    .baseUrl("https://api.example.com")
    .acceptHeader("application/json")

  val scn = scenario("GetResource")
    .exec(http("get /v1/resource")
      .get("/v1/resource")
      .check(status.is(200)))
    .pause(1)

  setUp(
    scn.inject(
      rampUsers(100).during(30),
      constantUsersPerSec(50).during(120)
    ).protocols(httpProtocol)
  ).assertions(
    global.responseTime.percentile3.lt(800),   // p95 < 800ms
    global.successfulRequests.percent.gt(99)
  )
}
```

Запуск:

```bash
# с Maven-плагином gatling-maven-plugin
mvn gatling:test

# с отдельным bundle
gatling.sh -s BasicSimulation
```

**Валидация:**

```bash
# assertion passed → exit code 0
# assertion failed → non-zero exit code (для CI/CD gates)
echo $?  # → 0 (success) or 1 (assertion failed)
```

### Сценарий 3: Тест с авторизацией (correlation)

Сценарий с OAuth2 token-корреляцией:

```scala
val auth = scenario("Auth")
  .exec(
    http("POST /token")
      .post("/oauth/token")
      .formParam("grant_type", "client_credentials")
      .check(jsonPath("$.access_token").saveAs("token"))
  )
  .exec(
    http("GET /data")
      .get("/data")
      .header("Authorization", "Bearer ${token}")
      .check(status.is(200))
  )
```

`saveAs` — аналог JSON Extractor из JMeter; сохраняет значение в session для последующего использования.

**Валидация:**

```bash
# Если токен не сохраняется — 401 на втором запросе:
grep "failed" target/gatling/*/jsession.js  | head -5
```

### Сценарий 4: Интеграция с CI/CD (GitLab CI)

Gatling Maven-плагин поддерживает:

- `-Dgatling.simulationClass` — выбор симуляции;
- `-Dgatling.dataFolder` / `-Dgatling.resultsFolder` — управление артефактами;
- порог assertions встроен в саму симуляцию (fail → non-zero exit code);
- плагин `gatling-enterprise-maven-plugin` для выгрузки результатов в Enterprise.

Пример GitLab job:

```yaml
load-test:
  stage: perf
  image: maven:3.9-eclipse-temurin-17
  script:
    - mvn -q gatling:test -Dgatling.simulationClass=BasicSimulation
  artifacts:
    when: always
    paths:
      - target/gatling/
```

Регрессионное сравнение строится через парсинг JSON-отчёта и пороги в assertions (см. [Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md)).

**Валидация:**

```bash
# Pipeline job fails if assertions fail:
grep -o '"allOk\":[^,}]*' target/gatling/*/jsession.js  # → true (pass)
```

### Сценарий 5: Профиль сотен тысяч одновременных пользователей

Комбинирование нескольких `inject`-блоков в одной `setUp`:

```scala
setUp(
  scn.inject(
    rampUsersPerSec(1).to(500).during(5.minutes),
    constantUsersPerSec(500).during(10.minutes),
    rampUsersPerSec(500).to(50).during(2.minutes)
  )
).protocols(httpProtocol)
```

Для распределённой генерации в Community используется кастомное развёртывание нескольких инстансов с shared-корпусом. **Gatling Enterprise** предоставляет встроенный распределённый запуск ( initiator/agent architecture).

**Валидация:**

```bash
# Мониторинг нагрузки на Gatling-узел:
top -b -n1 | head -5  # CPU < 80%, memory растёт линейно
```

## Операции и команды

| Категория | Команда | Описание |
| :--- | :--- | :--- |
| Запуск simulation | `./bin/gatling.sh -s com.example.MySimulation` | Запуск по классу |
| Запуск simulation | `mvn gatling:test -Dgatling.simulationClass=BasicSimulation` | Запуск через Maven |
| Выбор simulation | `-s` / `-Dgatling.simulationClass=` | Явный выбор класса симуляции |
| Duration override | `-Dgatling.simulationClass=... -Dgatling.simulationDuration=300` | Ограничить длительность |
| Data/results folder | `-DdataFolder=...` / `-DresultsFolder=...` | Управление артефактами |
| Assertions report | `target/gatling/*/jsession.js` | `allOk: true/false` |
| HTML report | `target/gatling/<simulation>-<timestamp>/` | Отчёт в браузер |
| Heap/tuning JVM | `-J-Xmx4g -J-XX:+UseG1GC` | Тюнинг памяти |
| Headless mode | `mvn gatling:test -Dgatling.consoleWriter=ror` | Нет interactive output |
| Stop после assertions | `-- simulations` зависят от exit code | 0 = pass, ≠0 = fail |
| Log config | `gatling.conf` / `logback.xml` | Настройка verbosity |
| Replay crash | `gatling.sh -s MySimulation -rd <runId>` | Повторный прогон |

### Параметры JVM для производительности

```bash
# Рекомендуется для high-load сценариев (>10k VU)
./bin/gatling.sh -J-Xmx4g -J-Xms2g -J-XX:+UseG1GC -J-XX:MaxGCPauseMillis=100 -s MySimulation
```

## Типичные ошибки и диагностика

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `Could not build Simulation` | Синтаксис DSL / версия Gatling | `gatling-maven-plugin` vs `gatling` версия mismatch | Проверить совместимость версий плагина и gatling |
| HTTP errors (connection reset) | Keep-alive timeout / server limits | `checks` в сессии; `gatling.conf` | Увеличить `gatling.http.ahc.maxRetries`, `requestTimeout` |
| 4xx на втором запросе | Нет корреляции токена | `saveAs` не сработал | Проверить `check(jsonPath)` |
| Потеря результатов в CI | Artifacts не сохраняются из-за path | `find target/gatling/` | Указать `-DresultsFolder=target/gatling` |
| Assertions FAIL при хорошем RPS | Порог слишком строгий | p99 из HTML-report | Пересчитать пороги на стабильном baseline |
| Memory: OOM на высокой нагрузке | Мало heap / много VU | `java.lang.OutOfMemoryError` в логе | `-J-Xmx8g`; добавить pause/think-time |
| `No simulation found` | Неправильный `-s` / classpath | `gatling-maven-plugin` scanning | Указать полный FQN класса: `-s com.pkg.Simulation` |
| `akka.actor.ActorKilledException` | Дисбаланс нагрузки / target overload | latency spikes в отчёте | Уменьшить RPS; добавить retry/backoff |
| Высокая latency на Gatling-узле | CPU saturation | `top`, `vmstat` | Добавить Gatling-агенты; распределить нагрузку |
| Не хватает file descriptors | Много соединений | `ulimit -n` | Увеличить до 65535: `ulimit -n 65535` |
| `gatling-maven-plugin` не находит зависимости | Локальный repo / proxy | `mvn dependency:resolve` | Убедиться в доступности репо в CI-окружении |

### Диагностический чек-лист (SRE-first)

1. **Утилизация:** `top` (CPU), `free -h` (RAM), `iostat -x 1` (disk), `sar -n DEV 1` (network).
2. **Saturation:** `uptime` (load avg), `cat /proc/pressure/*` (PSI), `vmstat 1` (swap, iowait).
3. **Ошибки:** `dmesg -T | tail -50` (OOM, hardware), `cat /proc/<pid>/limits` (fd limit).
4. **Процессы:** `pidstat 1`, `ps aux --sort=-%cpu | head`, `jstack <pid>` (thread dump для Akka actors).
5. **Сеть:** `ss -s` (состояние сокетов), `netstat -s | grep -i retrans` (retransmit), `ulimit -n` (fd limit).

## Лучшие практики

### Проектирование сценариев

- **Open Loop-модель**: используйте `constantUsersPerSec` / `rampUsersPerSec` вместо `rampUsers` для исключения Coordinated Omission.
- **Think time**: всегда добавляйте `.pause(duration)` между запросами — имитирует реальное поведение пользователя, предотвращает артефакты нагрузки.
- **Параметризация**: выносите URL, токены, тела запросов в переменные окружения (`-DbaseUrl=${TARGET_URL}`) и feeders (CSV). Никогда не хардкодьте секреты.
- **Warm-up**: прогревайте кэши (JIT, TLS, connection pool) 30–60 секунд перед steady state. Метрии cold start нерелевантны для SLA.
- **Cool-down**: всегда дожимайтесь завершения всех активных запросов перед остановкой теста.

### Distributed load generation

- **Gatling Enterprise**: используйте для production-grade distributed load с централизованной агрегацией результатов.
- **Community**: для распределённости используйте Kubernetes-оркестрацию: каждый под запускает `gatling.sh` с `--simulationClass` и индивидуальным профилем; агрегируйте результаты через `gatling-aggregator` или ручную сборку JSON.

### CI/CD integration

- **Quality Gates**: assertions в симуляции задают пороги (p95 < Xms, error rate < Y%); non-zero exit code автоматически фейлит job.
- **Baseline comparison**: сохраняйте `jsession.js` с baseline; сравнивайте `percentiles` и `meanNumberOfRequestsPerSecond` в CI.
- **Запуск**: на MR (коротко, 2–5 мин) + nightly (длинно, 30+ мин); не на каждый коммит.

### Environment isolation

- **Production-like стенд**: JVM-версия, GC-настройки, kernel params (`net.core.somaxconn`, `net.ipv4.ip_local_port_range`), cgroup limits — все должно совпадать с prod.
- **Выделенные раннеры**: self-hosted runners с выделенными CPU/RAM; избегайте noisy neighbors в shared infrastructure.

### Baseline и regression detection

- **Многократный запуск**: baseline из 3+ прогонов в одинаковых условиях.
- **Относительные пороги**: `current_p95 < baseline_p95 * 1.1` более устойчив к шуму, чем абсолютные пороги.
- **Хранилище baseline**: артефакты CI с `expire_in: 30d` или version-controlled JSON.

### Безопасность

- **Секреты**: никогда не хардкодьте API-ключи, токены в сценариях. Используйте `__ENV` переменные CI (`$TOKEN`).
- **mTLS**: для production-like стены используйте клиентские сертификаты вместо `insecureSkipTLSVerify`.

## Ограничения и крайние случаи

- **Gatling Community не имеет distributed mode**: только Enterprise или кастомная оркестрация через K8s.
- **Scala/Java DSL требует компиляции**: unlike k6 (JS), каждое изменение сценария требует перекомпиляции; медленнее для итераций.
- **Single-threaded request engine per VU**: Akka-актор обрабатывает запросы последовательно внутри одного VU; для параллельных запросов используйте `exec(...).parallel` или несколько сценариев.
- **Memory pressure при высокой нагрузке**: если VU > 100k и response body сохраняется в памяти (через проверки body), может быть OOM — используйте `.check(bodyString.saveAs("resp"))` с осторожностью.
- **Не подходит для non-HTTP протоколов**: в отличие от JMeter (JDBC, JMS, FTP, gRPC), Gatling ограничен HTTP/HTTPS (соединениями WebSocket через плагины).
- **Отчётность в CI**: HTML-отчёты не масштабируются для automated parsing в CI; используйте `-DconsoleWriter=ror` или парсинг `jsession.js`.
- **Coordinated Omission при Closed Loop сценариях**: если используете `atOnceUsers`/`rampUsers` (количество VU, а не RPS), при деградации сервера latency будет искажаться.
- **Не подходит для functional testing**: Gatling — load generator, а не assertion framework для бизнес-логики.

## Очистка

- **HTML reports**: удаляйте старые отчёты `rm -rf target/gatling/*` для экономии disk space; артефакты CI должны сохранять только последние 3 запуска.
- **Gatling logs**: `rm -f target/gatling/*/jsession.js` после архивации метрик.
- **Maven cache**: `mvn dependency:purge-local-repository` для очистки загруженных Gatling-зависимостей (экономит ~500MB).
- **JVM heap dumps**: если тест падает с OOM, `jmap -dump:format=b,file=heap.hprof <pid>`; удалять после анализа.
- **CI cleanup**: в `after_script:` добавить `rm -rf target/gatling/* target/.gatling` и `mvn clean` для очистки workspace.
- **Docker cleanup**: если используется container: `docker system prune -f` для удаления неиспользуемых образов и томов.
- **Gatling Enterprise**: через UI очищайте старые запуски по retention policy (настраивается в `application.conf`).

## Дополнительная информация

### Связь с другими типами тестирования

Gatling дополняет и сравним с другими генераторами нагрузки. Методология (SLI/SLO, Open/Closed Loop, Coordinated Omission) универсальна — см. [Методология тестирования производительности](./performance_testing_methodology.md).

| Критерий | Gatling | k6 | JMeter |
| :--- | :--- | :--- | :--- |
| Сценарии | Scala/Java/Kotlin DSL | JS/TS | GUI (JMX), Groovy |
| Модель нагрузки | Open loop (по умолчанию) | constant-arrival-rate (встроена) | Closed loop (по умолчанию) |
| Протоколы | HTTP/1.1, HTTP/2, WebSocket, JMS, JDBC | HTTP/1.1-3, gRPC, WS | HTTP, JDBC, JMS, FTP, LDAP (+плагины) |
| Distributed | Enterprise only | K8s operator | Built-in master/agent |
| Экосистема | JVM-сообщество, Maven/Gradle | Grafana/Grafana Cloud | Множество плагинов |
| CI/CD | Maven plugin, assertions | CLI, thresholds, Docker | non-GUI + JTL |
| Кому выбрать | JVM-команды, enterprise, code-driven | DevOps, developer-driven | Legacy, enterprise, non-web protocols |

### Нагрузочное тестирование в CI/CD

Gatling интегрируется в CI/CD через Maven/Gradle плагины с assertions-as-gates (non-zero exit code при failure). Для baseline comparison и Quality Gates — см. [Нагрузочное тестирование в CI/CD](../CI-CD/Testing/load_testing_ci_cd.md) и [Интеграция тестов в CI/CD](./testing_cicd_integration.md#нагрузочное-тестирование-в-ci-k6-и-quality-gates).

### См. также

- **[Методология тестирования производительности](./performance_testing_methodology.md)** — SLI/SLO, Open/Closed Loop, Coordinated Omission, PTLC, SRE-практики.
- **[Нагрузочное тестирование с помощью k6](./k6_load_testing.md)** — современная Performance-as-Code альтернатива.
- **[Нагрузочное тестирование с помощью Apache JMeter](./jmeter_load_testing.md)** — сравнение «Gatling vs JMeter» по модели исполнения.
- **[Нагрузочное тестирование с помощью Yandex.Tank и Taurus](./yandex_tank_taurus.md)** — Taurus как YAML-обёртка над Gatling (executor: `gatling`).
- **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — Quality Gates, Regression Detection, автоматизация в GitLab CI/GitHub Actions.

### Внешние ресурсы

- [Gatling Documentation](https://docs.gatling.io/) — официальная документация (reference, tutorials, recorder).
- [Gatling GitHub](https://github.com/gatling/gatling) — исходный код, issues.
- [Gatling Release Notes](https://docs.gatling.io/release-notes/) — актуальная версия и изменения (3.15.x).
- [Gatling Maven Plugin](https://docs.gatling.io/integrations/build-tools/maven-plugin/) — документация Maven-плагина.