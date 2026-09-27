# Нагрузочное тестирование с помощью Gatling

## Определения

**Gatling** — open-source инструмент нагрузочного тестирования на JVM. Сценарии пишутся на **Scala (Domain Specific Language)** либо — в версии Enterprise — через No-Code UI. Ключевые преимущества: высокая производительность генератора (Netty/actor-модель), асинхронная обработка запросов, детальные HTML-отчёты и открытая модель нагрузки. Актуальная стабильная версия — **3.15.x** (Apache-2.0 для открытой части; Enterprise-модули проприетарные).

**Gatling Enterprise** — коммерческая платформа (конкурент k6-Cloud/Loader.io): управление испытаниями, кластерная нагрузка, интеграции, дашборды.

**Scenario / Simulation** — сценарий (низкоуровневый) и симуляция (высокоуровневый тест-класс на Scala).

## Основные концепции

### Модель исполнения: async events

Gatling построен на **Akka actors + Netty**: каждый виртуальный пользователь (user) — это лёгкий асинхронный «фиктивный пользователь», который не блокирует поток (thread) при ожидании ответа. Благодаря этому один узел может генерировать десятки тысяч одновременных пользователей с малым потреблением памяти.

В отличие от JMeter (поток на пользователя), в Gatling **пользователь ≠ поток** — отсюда и значительно меньшие накладные расходы на высоких нагрузках.

### Сущности сценария

- **Scenario** — последовательность шагов (HTTP-запрос target, loop, pause, errors).
- **Simulation** — обвязка: параметры нагрузки (users, ramp, duration), профиль.
- **Protocol** — базовые HTTP-настройки (baseUrl, headers, SSL-профиль, connection).
- **Checks** — статус-код, JSONPath/Regex-материя, время ответа.
- **Feeders** — источники данных (CSV, Iterator, random), аналог Parameterized Data в JMeter.
- **Assertions** — пороговые проверки (p95 < X, failures < N%).
- **Reports** — автоматический HTML-отчёт (дашборд, перцентили, распределения).

### Пример симуляции (Scala DSL)

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
    global.responseTime.percentile3.lt(800), // p95
    global.successfulRequests.percent.gt(99)
  )
}
```

Запуск:

```bash
# с Maven-плагином gatling-maven-plugin
mvn gatling:test

# с отдельным бандлом
gatling.sh -s BasicSimulation
```

### Open model injections — «точно по времени»

Инъекции-«качества» задаются из «кожи», а не из числа потоков:

- `rampUsers(n).during(d)` — линейный рост.
- `constantUsersPerSec(r).during(d)` — фиксированный RPS.
- `rampUsersPerSec(from).to(to).during(d)` — рост RPS.
- `atOnceUsers(n)` — одновременный наплыв.
- `stressPeakUsers(n).during(d)` — пиковая нагрузка.

Это открытая модель (open loop) по умолчанию, что отлично согласуется с методологией без Coordinated Omission — детали в [Методология тестирования производительности](./performance_testing_methodology.md).

### Feeder и разграничение данных

```scala
val usersCsv = csv("users.csv").circular
scn = scn.feed(usersCsv).exec(
  http("login").post("/auth/login")
    .formParam("login", "${login}")
    .formParam("password", "${password}")
)
```

Feeders бывают `queue`, `random`, `circular`, `shuffle` — влияют на переиспользование данных между пользователями.

### Отчётность

HTML-отчёт (в `target/gatling/`) содержит:

- сводку «Global Information»: перцентили response time, throughput, ошибки;
- перцентильную турудину (ex. 50/75/95/99);
- timeline-графики RPS и latency;
- «response time distribution» и «number of requests per second».

Эти данные удобно использовать в качестве входных для Gating в CI/CD.

## Практические сценарии

### Сценарий 1: Быстрый старт через Maven

```bash
# создать проект из архетипа (structure: src/test/scala/yourpackage)
mvn archetype:generate \
  -DgroupId=com.example -DartifactId=loadtest \
  -DarchetypeGroupId=io.gatling.archetypes \
  -DarchetypeArtifactId=gatling-maven-plugin-demo
cd loadtest
mvn gatling:test -Dgatling.simulationClass=BasicSimulation
```

### Сценарий 2: Тест с авторизацией (correlation)

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

`saveAs` — традиционный аналог JSON Extractor из JMeter.

### Сценарий 3: Интеграция с CI/CD (Jenkins/GitLab)

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

### Сценарий 4: Профиль сотен тысяч одновременных пользователей

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

Для распределённой генерации используется **Gatling Enterprise** (управляемые нагрузки из инициатора) либо кастомное развёртывание нескольких инстансов (мастер/агенты не входят в open-source версию в отличие от JMeter).

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Could not build Simulation` | Синтаксис DSL/версия Gatling | Проверка совместимости версий gatling-maven-plugin и gatling |
| Поток HTTP-ошибок (connection reset) | Клиент не справляется или сервер закрывает keep-alive | Проверить `http().extraInfoExtractor`, увеличить `maxConnectionsPerHost` |
| Чужеродные 4xx | Нет корреляций токена/данных | Починить `check`-и и SaveAs; use session variables |
| Assertions FAIL несмотря на «хорошие» RPS | Неверный порог или закрытые KPI | Перцентили в часа — итоговый вывод из отчёта |
| Memory: столько «users», сколько акторов | Высокий `constantUsersPerSec` без pause | Ввести `pause` (think time), он снизит количество одновременных активных сессий |
| Потеря выхода из отчёта в CI | Результаты в разбивке по временам не сохраняются | Использовать `gatling:lastSessionId` семантику плагина |

## Дополнительная информация

### См. также

- **[Методология тестирования производительности](./performance_testing_methodology.md)** — открытая/закрытая модель нагрузки, перцентили, NFR.
- **[Нагрузочное тестирование с помощью Apache JMeter](./jmeter_load_testing.md)** — сравнение «Gatling vs JMeter» по модели исполнения.
- **[Нагрузочное тестирование с помощью k6](./k6_load_testing.md)** — современная альтернатива с JS/TS.

### Внешние ресурсы

- [Gatling: What's new / release notes](https://docs.gatling.io/release-notes/) — актуальная версия и изменения (3.15.x).
- [Gatling documentation](https://docs.gatling.io/) — официальная документация (reference + guttenberg).