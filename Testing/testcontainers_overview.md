# Testcontainers

## 1. Определения

**Testcontainers** — это библиотека с открытым исходным кодом, которая предоставляет временные ("эфемерные"), легковесные экземпляры зависимостей (баз данных, брокеров сообщений, браузеров), запускаемые в Docker-контейнерах. Библиотека управляет полным жизненным циклом контейнеров, обеспечивая их автоматический запуск перед тестами и удаление после завершения.

Основная цель — создание чистой, изолированной и детерминированной среды для интеграционного и сквозного (E2E) тестирования.

## 2. Основные концепции

### Механизм работы и очистки (Ryuk)

Одной из ключевых особенностей Testcontainers является наличие **Ryuk (Resource Reaper)**. Это вспомогательный "контейнер-сторож", который запускается первым.
* **Задача:** Ryuk следит за сессией тестирования и гарантирует, что все созданные контейнеры, сети и тома будут удалены, даже если процесс тестирования завершился аварийно (например, при падении JVM или остановке CI-раннера). Ryuk является отдельным Go-приложением (`testcontainers/moby-ryuk`) и использует Docker-подключение без привилегированного режима.
* **Безопасность (2025+):** Начиная с версии 0.13.0 (сентябрь 2025) образ Ryuk базируется на `scratch`, что минимизирует риски безопасности в корпоративных контурах. Актуальная версия образа на начало 2026 года — 0.14.0, она используется в Testcontainers Java начиная с релиза февраля 2026 года.
* **Конфигурация:** Образ можно переопределить через `ryuk.container.image`, а в средах, где запрещён запуск привилегированных контейнеров, — включить `ryuk.container.privileged=true`. Если очистка уже реализована самой средой (например, CI), Ryuk можно отключить переменной окружения `TESTCONTAINERS_RYUK_DISABLED=true` или свойством `ryuk.disabled`.
* **Rootless Docker / Podman:** В rootless-окружениях и Podman Ryuk может работать некорректно; для таких рантаймов применяется отключение Ryuk либо использование Podman с поддержкой привилегированного режима.

### Стратегии ожидания (Wait Strategies)

Testcontainers не просто запускает контейнер, но и дожидается его готовности к приему трафика:
* **Wait.forListeningPort():** Ожидание открытия TCP-порта.
* **Wait.forHttp(path):** Ожидание успешного HTTP-ответа (код 200).
* **Wait.forLogMessage(regex):** Ожидание появления определенной строки в логах (например, "Database is ready").
* **Wait.forHealthcheck():** Использование встроенной команды `HEALTHCHECK` из Dockerfile. Рекомендуется для образов, в которых она определена; в новых версиях SDK (например, `testcontainers-node` v12+) она стала стратегией по умолчанию при наличии `HEALTHCHECK`, с переходом на `Wait.forListeningPorts()` в противном случае.

### Сетевое взаимодействие (Networking)

Библиотека позволяет создавать изолированные виртуальные сети между контейнерами:
* **Network.newNetwork():** Создание сети для группы контейнеров (например, приложение + БД + Kafka).
* **Network Aliases:** Возможность обращения к контейнерам по именам внутри сети Docker, что имитирует конфигурацию production-среды.
* **Динамические порты:** Testcontainers автоматически пробрасывает (map) внутренние порты контейнеров на случайные свободные порты хост-машины, исключая конфликты при параллельном запуске тестов.

### Ограничение ресурсов и cgroups

Для тестов, запускаемых на общих CI-раннерах, Testcontainers позволяет явно задавать лимиты CPU, памяти и ulimit через метод `.withCreateContainerCmdModifier()`:
* **CPU/Memory:** Ограничение потребления предотвращает влияние "прожорливого" теста на другие джобы на том же агенте.
* **Ulimit:** Увеличение `nofile` или `nproc` необходимо для тестов с большим количеством соединений или процессов.
* **cgroups v1/v2:** При работе в rootless-окружениях или Podman убедитесь, что cgroup-driver совместим с Testcontainers.

Пример ограничения памяти для PostgreSQL-контейнера:
```java
GenericContainer<?> postgres = new PostgreSQLContainer<>("postgres:16")
    .withCreateContainerCmdModifier(cmd -> {
        cmd.withMemory(512 * 1024 * 1024L)       // 512 MB
           .withMemoryReservation(256 * 1024 * 1024L); // 256 MB
    });
```

### Управление секретами

Testcontainers поддерживает передачу секретов в контейнер тремя способами:
* **Переменные окружения:** `.withEnv("DB_PASSWORD", "secret")` — удобно для CI, но секрет виден в `docker inspect`.
* **Файлы (Bind Mount):** `.withFileSystemBind("/host/secret.txt", "/run/secret/db_password", BindMode.READ_ONLY)` — безопаснее, файл не попадает в образ.
* **Docker Secrets:** В Docker Swarm или Compose v3+ можно использовать `.withCreateContainerCmdModifier(cmd -> cmd.withSecretSource(...))`, однако это требует поддержки Swarm в рантайме.

Рекомендация для CI: используйте файловый bind mount с временным файлом, создаваемым в `/tmp` и удаляемым после теста.

### Параллелизм и изоляция тестов

* **Изоляция по умолчанию:** Каждый тестовый класс/метод получает свой экземпляр контейнера с уникальным именем и динамическими портами.
* **Параллельный запуск:** При использовании JUnit 5 с `@Execution(ExecutionMode.CONCURRENT)` Testcontainers безопасно управляет несколькими контейнерами одновременно.
* **Sharding:** Для ускорения пайплайнов тесты можно делить на шарды (shards) по типу сервиса (например, все тесты PostgreSQL в одной джобе, Kafka — в другой).
* **Ограничение:** Параллелизм ограничен ресурсами CI-раннера; при превышении лимитов процессов или памяти Ryuk может не успеть очищать контейнеры.

### Безопасность контейнеров

* **Non-root пользователи:** Рекомендуется указывать пользователя через `.withCreateContainerCmdModifier(cmd -> cmd.withUser("1001:1001"))`, если образ поддерживает non-root.
* **Read-only root filesystem:** `.withReadOnlyRootFilesystem()` снижает поверхность атаки при компрометации контейнера.
* **Capabilities:** Отключение неиспользуемых Linux capabilities через `.withCapabilityDrop("ALL")` повышает безопасность.
* **Image Tag Pinning:** Всегда используйте фиксированные теги образов (например, `postgres:16.3`), а не `:latest`, чтобы обеспечить детерминизм и избежать supply-chain атак.

## 3. Практические сценарии

### Интеграционное тестирование с реальными зависимостями

Вместо использования эмуляторов или In-memory решений (которые могут вести себя иначе, чем реальная БД), Testcontainers поднимает идентичную production-версию сервиса.

**Пример (псевдокод):**

```python
# Инициализация контейнеров
postgres = PostgreSQLContainer("postgres:16")
redis = RedisContainer("redis:7-alpine")

def setup_module():
    # Запуск и получение динамических параметров
    postgres.start()
    redis.start()
    
    # Настройка приложения на лету
    app.config.db_url = postgres.get_connection_url()
    app.config.redis_host = redis.get_host()
    app.config.redis_port = redis.get_mapped_port(6379)

def teardown_module():
    # Ручная остановка (необязательно, Ryuk подчистит сам)
    postgres.stop()
    redis.stop()
```

**Пример (Java / JUnit 5):** В Java используется встроенная интеграция с JUnit Jupiter через аннотации `@Testcontainers` и `@Container`:

```java
@Testcontainers
class OrderRepositoryTest {

    @Container
    static PostgreSQLContainer<?> postgres =
        new PostgreSQLContainer<>("postgres:16")
            .withDatabaseName("orders")
            .withUsername("test")
            .withPassword("test");

    @BeforeAll
    static void initConnection() {
        orderRepository = new OrderRepository(postgres.getJdbcUrl(),
                                              postgres.getUsername(),
                                              postgres.getPassword());
    }

    @Test
    void shouldPersistOrder() {
        // тест использует реальный контейнер PostgreSQL
    }
}
```

`@Container` — инструкция жизненным циклом контейнера управляет Testcontainers; `@Testcontainers` — включает расширение JUnit Jupiter (автозапуск контейнеров до тестов и автоматическую очистку после).

### Ускорение разработки через Reusable Mode

Режим **Reusable Mode** (переиспользование) позволяет не перезапускать контейнеры при каждом локальном запуске теста, если их конфигурация не изменилась.
1. В коде включается флаг `.withReuse(true)`.
2. В файле `~/.testcontainers.properties` на машине разработчика добавляется `testcontainers.reuse.enable=true`.
3. **Результат:** Время обратной связи сокращается с десятков секунд до миллисекунд, так как тесты подключаются к уже запущенному контейнеру.

**Ограничения:**
* Режим является **экспериментальным** и ориентирован на локальную разработку, а не на CI: в пайплайнах он противоречит принципу эфемерных окружений.
* Контейнер переиспользуется только при полном совпадении параметров запуска (образ, конфигурация, имя); любые изменения приводят к пересозданию.
* Testcontainers Desktop включает `testcontainers.reuse.enable=true` по умолчанию для локальных прогонов.

### Инициализация данных и миграции

Вместо ручного создания схемы БД в каждом тесте, используйте стандартные механизмы инициализации:
* **initScript:** `.withInitScript("schema.sql")` автоматически выполняет SQL-файл после запуска контейнера.
* **Миграции:** Если проект использует Flyway или Liquibase, запустите миграции в `@BeforeAll` через JDBC-соединение Testcontainers.
* **Тестовые данные:** Генерация фикстур через библиотеки (например, `java-faker` или `faker.js`) после инициализации БД.

Пример (Java):
```java
@Container
static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:16")
    .withDatabaseName("testdb")
    .withUsername("test")
    .withPassword("test")
    .withInitScript("init/schema.sql");
```

### Прокидывание секретов из CI

В CI-пайплайне секреты (пароли, токены) обычно поступают как переменные окружения. Для безопасной передачи в контейнер:
1. Запишите секрет во временный файл на агенте: `echo "$DB_PASSWORD" > /tmp/db_secret`.
2. Прокиньте файл в контейнер через `withFileSystemBind`.
3. Укажите приложению путь к файлу через переменную окружения.

Пример (Python/pytest):
```python
from testcontainers.postgres import PostgresContainer
import os, tempfile

postgres = PostgresContainer("postgres:16")
postgres.start()

secret_file = tempfile.NamedTemporaryFile(delete=False, mode="w")
secret_file.write(os.environ["DB_PASSWORD"])
secret_file.close()

postgres.with_command(f"bash -c 'cat /run/secret/db_password | psql -U test'")
postgres.with_file_system_bind(secret_file.name, "/run/secret/db_password", "ro")
```

### Предварительная загрузка образов (Pre-pull)

Для ускорения запуска тестов в CI заранее подготавливайте образы на раннере:
```bash
# В скрипте инициализации джобы (before_script)
docker pull postgres:16
docker pull redis:7-alpine
docker pull testcontainers/ryuk:0.14.0
```
Это сокращает время ожидания на этапе `docker run` внутри тестов и исключает проблемы с rate-limiting Docker Hub.

### Инспекция и отладка запущенных контейнеров

При падении теста иногда необходимо исследовать состояние контейнера:
```bash
# Список запущенных контейнеров Testcontainers (фильтр по имени)
docker ps --filter "name=testcontainers"

# Просмотр логов конкретного контейнера
docker logs testcontainers-postgres-1

# Подключение к контейнеру для ручной диагностики
docker exec -it testcontainers-postgres-1 psql -U test -d testdb

# Просмотр метрик и событий
docker inspect testcontainers-postgres-1
```
После отладки не забудьте выполнить `docker rm -f testcontainers-postgres-1`, если Ryuk по какой-то причине не удалил контейнер автоматически.

## 4. Роль в DevOps и CI/CD

### Упрощение инфраструктуры CI

* **Docker как единственная зависимость:** Для работы пайплайна на агенте (Runner) требуется только Docker. Нет необходимости описывать сложные блоки `services` в YAML-файлах CI.
* **Изоляция пайплайнов:** Благодаря динамическим портам, несколько сборок одного проекта могут одновременно запускаться на одном агенте без конфликтов.
* **Ресурсы CI-раннера:** Убедитесь, что у раннера достаточно CPU и памяти для параллельных контейнеров; лимиты задаются через `docker run --cpus` и `--memory` или через cgroup-настройки раннера.

### Паритет сред (Dev/Prod Parity)

* Testcontainers гарантируют, что разработчик локально тестирует код на тех же версиях ОС и библиотек, которые будут в production.
* **Shift-Left:** Обнаружение ошибок конфигурации или несовместимости версий происходит на этапе написания кода, а не после деплоя в тестовую среду.

### Особенности запуска в CI

При запуске внутри контейнеризированных пайплайнов (например, в GitLab CI или GitHub Actions) требуется настройка вложенности Docker. Подробный разбор подходов DinD (Docker-in-Docker) и DooD (Socket Mounting), их рисков и оптимизации см. в файле: **[Docker-in-Docker: Запуск в контейнере](../Docker/docker-in-docker.md)**.

#### Практика: права на Docker socket в CI

При использовании DooD (монтирование `/var/run/docker.sock`) на CI-раннере:
1. Убедитесь, что пользователь, от имени которого запускаются тесты, входит в группу `docker`: `usermod -aG docker $USER`.
2. Проверьте права на сокет: `ls -la /var/run/docker.sock` — должен быть `srw-rw---- 1 root docker ...`.
3. Для повышения безопасности используйте Rootless Docker на раннере, если environment это позволяет.

#### Параллелизм и sharding в CI

Для сокращения времени пайплайна разбейте интеграционные тесты по нескольким джобам:
* **По типу сервиса:** Отдельная джоба для тестов PostgreSQL, отдельная — для Kafka.
* **По шардам (sharding):** Используйте параметры окружения для выбора подмножества тестов внутри джобы.
* **Ограничение:** Не превышайте количество параллельных контейнеров, допустимое для раннера; используйте `docker system df` для мониторинга места и количества образов.

### Testcontainers Desktop

Экосистема вокруг библиотек включает бесплатные инструменты для локальной разработки:

* **Testcontainers Desktop** — бесплатное GUI-приложение для локальной разработки. Позволяет запускать тесты без локального Docker-демона (встроенный runtime на macOS), переключать рантаймы (Docker Desktop, Podman, Rancher), фиксировать порты сервисов, «замораживать» контейнеры для отладки.
* **Testcontainers Desktop** по умолчанию включает `testcontainers.reuse.enable=true` для локальных прогонов.

## 5. Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Контейнер не запускается в CI | Нет доступа к Docker socket / DinD не настроен | Настроить DooD или DinD; проверить права пользователя |
| Ryuk не удаляет контейнеры | Ryuk отключен или не может подключиться к Docker | Проверить `TESTCONTAINERS_RYUK_DISABLED`, образ `testcontainers/ryuk` |
| `Connection refused` на порт | Порт неожиданно занят другим процессом | Использовать `docker ps` для поиска конфликтов; убедиться, что `docker rm` удалил старые контейнеры |
| Таймаут ожидания готовности | Медленный образ или неверная wait strategy | Увеличить таймаут через `.waitingFor(Wait.forHttp(...).withStartupTimeout(Duration.ofSeconds(120)))` |
| `Permission denied` на Docker socket | Пользователь не в группе `docker` | `usermod -aG docker $USER` и перелогин |
| Нехватка памяти (OOM) | Контейнер выходит за лимиты на раннере | Задать `.withCreateContainerCmdModifier` с `--memory` |
| Контейнеры остаются после падения тестов | Ryuk упал или не запустился | Включить Ryuk явно или настроить cleanup в CI |
| Проблемы с DNS в сети Testcontainers | Кастомный DNS не настроен | Использовать `Network.newNetwork()` с явным указанием DNS-сервера |

## 6. Дополнительная информация

### Модульная экосистема (2025–2026)

Библиотека предоставляет готовые модули-обертки, упрощающие настройку специфичных инструментов. Список модулей постоянно растёт, официальный каталог — [testcontainers.com/modules](https://testcontainers.com/modules/):
* **Базы данных:** PostgreSQL, MySQL, MariaDB, Oracle, MSSQL, ClickHouse, TiDB, YugabyteDB, Neon, PlanetScale.
* **Брокеры и очереди:** Kafka (включая Apache Kafka нативно, без ZooKeeper), Redpanda, RabbitMQ, Pulsar, NATS.
* **NoSQL и Кэш:** Redis, Valkey, MongoDB (Atlas Local), Cassandra, Elasticsearch, OpenSearch.
* **Браузеры (E2E):** Selenium (Chrome и Firefox) через `BrowserWebDriverContainer`.
* **Тестирование контейнеров:** GenericContainer для произвольных образов, DockerComposeContainer для запуска нескольких сервисов из `docker-compose.yml`.

### Поддерживаемые языки

* **Java/JVM:** Версия 2.0+ (стандарт индустрии). В ветке 2.x удалена поддержка JUnit 4 (только JUnit Jupiter), классы контейнеров переехали в пакет `org.testcontainers.*`, все артефакты имеют префикс `testcontainers-` (например, `org.testcontainers:testcontainers-mysql`).
* **Node.js:** `testcontainers-node` v12+ (требует Node.js >= 22.22).
* **Go:** `testcontainers-go`.
* **Python:** `testcontainers-python`.
* **.NET:** `testcontainers-dotnet`.
* **Rust:** `testcontainers-rs`.

### Сравнение с альтернативами

| Инструмент | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Testcontainers** | Реальные сервисы в Docker | Программное управление, динамические порты, глубокая интеграция |
| **Docker Compose** | Оркестрация через YAML | Статичные окружения, простые стеки без сложной логики в коде |
| **In-memory БД** | Эмуляция (H2, SQLite) | Быстрые unit-тесты, когда поведение 100% идентично реальной БД |
| **Docker Compose CI/CD** | Управление через YAML в пайплайне | Альтернатива Testcontainers, когда требуется минимальный код; см. **[Docker Compose CI/CD Testing](../Docker/Docker_compose/docker_compose_ci_cd_testing.md)** |

---

### Связанные документы

* **[Виды тестов: Unit, Integration, E2E](./testing_types_unit_integration_e2e.md)** — основы стратегии тестирования.
* **[Интеграция тестов в CI/CD](./testing_cicd_integration.md)** — использование эфемерных окружений.
* **[Docker Compose CI/CD Testing](../Docker/Docker_compose/docker_compose_ci_cd_testing.md)** — альтернативный подход к управлению контейнерами.
