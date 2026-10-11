**Актуально для:** Java 21+

# Dockerfile: Лучшие практики для Java

## Определения

- **JDK (Java Development Kit):** Полный комплект разработчика (компилятор `javac`, инструменты сборки, библиотеки). Используется исключительно на этапе сборки в multi-stage Dockerfile.
- **JRE (Java Runtime Environment):** Минимальная среда выполнения. В 2026 году рекомендуется использовать модульные сборки через **JLink** или специализированные JRE-образы (например, Wolfi/Chainguard).
- **Wolfi / Chainguard:** Современные "un-distro" образы, ориентированные на максимальную безопасность (0 CVE) и использующие `glibc`. Являются отраслевым стандартом для безопасных Java-приложений.
- **Layered JAR:** Технология (впервые представленная в Spring Boot), позволяющая разделить JAR-файл на логические слои (зависимости, ресурсы, код) для максимально эффективного кэширования слоев Docker.
- **CDS (Class Data Sharing):** Механизм ускорения старта JVM путем создания архива `.jsa` с предварительно загруженными метаданными классов.
- **GraalVM Native Image:** Технология компиляции Java-кода в автономный нативный бинарный файл, не требующий JVM для запуска. Обеспечивает мгновенный старт и минимальное потребление памяти.
- **Project Leyden:** Инициатива по улучшению времени запуска и прогрева Java-приложений за счет статического анализа и оптимизации на этапе сборки.
- **CRaC (Coordinated Restore at Checkpoint):** Технология для создания дампа памяти работающего Java-приложения и его мгновенного восстановления, что позволяет достигать времени старта <100 мс.
- **SBOM (Software Bill of Materials):** Декларативный список всех компонентов и зависимостей, входящих в состав образа, необходимый для аудита безопасности.
- **BuildKit:** Современный движок сборки Docker, поддерживающий параллельное выполнение этапов, монтирование кэша и Heredocs.
- **Multi-stage Build (Многоэтапная сборка):** Техника использования нескольких инструкций `FROM` в одном файле. Позволяет разделить среду сборки (с JDK и Maven/Gradle) и среду выполнения (только JRE и JAR), исключая инструменты из итогового образа.
- **JAR (Java Archive):** Файл-архив, содержащий скомпилированные классы, ресурсы и метаданные. В Spring Boot используется "fat JAR" (упаковка всех зависимостей в один файл).
- **WAR (Web Application Archive):** Формат развертывания веб-приложений, предназначенный для deployment в серверы приложений (Tomcat, Jetty).
- **Jakarta EE:** Спецификация корпоративных Java-приложений (наследник Java EE). Определяет контракты для сервлетов, CDI, JPA и других компонентов.
- **Maven / Gradle:** Два основных инструмента сборки для Java-проектов. Maven 3.9+ использует `pom.xml`, Gradle 8+ — Groovy/Kotlin DSL. Оба поддерживают кэширование зависимостей в Docker через BuildKit mounts.
- **Spring Boot:** Фреймворк для создания автономных микросервисов. В контексте Docker поддерживает Layered JAR и provides production-ready features (Actuator, metrics, health checks).
- **Quarkus / Micronaut:** Альтернативные фреймворки, оптимизированные для контейнеров и GraalVM Native Image. Обеспечивают время старта <100 мс и потребление памяти <100 МБ.
- **Testcontainers:** Библиотека для поднятия полноценных контейнеров (БД, брокеры сообщений) во время интеграционных тестов. В Java-экосистеме работает через Docker API и требует доступа к `/var/run/docker.sock`.
- **JMX (Java Management Extensions):** Механизм мониторинга и управления JVM в runtime. Позволяет получать метрики (память, потоки, GC) и изменять параметры без перезапуска.
- **JFR (Java Flight Recorder):** Встроенный в JVM низкоуровневый профайлер, записывающий события (GC, методы, блокировки) в файл `.jfr` для последующего анализа в JDK Mission Control.
- **jcmd / jstack / jmap / jinfo:** Утилиты JDK для диагностики живого процесса (`jcmd`), получения дампов потока (`jstack`), анализа кучи (`jmap`) и изменения параметров JVM (`jinfo`) без перезапуска.
- **-XX:MaxRAMPercentage:** Флаг JVM, задающий процент от лимита памяти контейнера, который JVM может использовать для Heap. Стандарт для контейнеризированных приложений — `75.0`.
- **-XX:+ExitOnOutOfMemoryError:** Флаг, заставляющий JVM завершиться (с non-zero exit code) при OutOfMemoryError вместо попытки продолжить работу в неопределенном состоянии.
- **-Xlog:gc:** Флаг включения детального логирования Garbage Collector в файл. Критичен для диагностики проблем с памятью в production.
- **Cache Mount (Монтирование кэша):** Механизм BuildKit (`--mount=type=cache`), сохраняющий данные пакетных менеджеров (`~/.m2`, `~/.gradle`) между сборками без их попадания в итоговый образ.
- **Bind Mount (Монтирование контекста):** Механизм BuildKit (`--mount=type=bind`), предоставляющий доступ к файлам (`pom.xml`, `go.mod`) из контекста сборки без их физического копирования в слой образа.
- **Reproducible Build (Воспроизводимая сборка):** Свойство сборки давать идентичный JAR/образ при одинаковых исходных данных. Достигается через `SOURCE_DATE_EPOCH`, pinning базовых образов по дайджесту и фиксацию зависимостей.
- **SOURCE_DATE_EPOCH:** Переменная окружения (Unix timestamp), фиксирующая метку времени для всех файлов в образе. Используется для получения идентичных дайджестов при повторных сборках.
- **.dockerignore:** Файл в корне контекста сборки, задающий исключения. Ускоряет сборку, исключая `.git`, `target/`, `build/`, `*.jar`, `*.war` из передачи сборщику.
- **checksec:** Утилита для проверки hardening-флагов в ELF-бинарниках. Для Java приложений релевантна при использовании GraalVM Native Image.
- **trivy:** Мультиформатный сканер уязвимостей от Aqua Security. Анализирует файловую систему контейнера, JAR-файлы и SBOM.
- **syft:** Утилита от Anchore для генерации SBOM в форматах SPDX и CycloneDX. Поддерживает анализ Maven/Gradle зависимостей.
- **dive:** Интерактивный инструмент для анализа слоев Docker-образов. Позволяет обнаруживать "мусор" (кэши Maven, исходный код), попавший в итоговый образ.
- **Tomcat / Jetty / Undertow:** Серверы приложений для deployment Java веб-приложений. В контейнерах часто используются как embedded (встроенные) серверы в Spring Boot или Quarkus.
- **Virtual Threads (Java 21+):** Легковесные потоки (Project Loom), работающие поверх ограниченного пула системных потоков. В контейнерах позволяют масштабировать приложения до миллионов конкурентных запросов без увеличения потребления памяти.
- **Metaspace:** Область памяти JVM для хранения метаданных классов (заменила PermGen в Java 8). Рекомендуется ограничивать через `-XX:MaxMetaspaceSize` для предотвращения утечек.
- **Direct Memory:** Память, выделяемая вне кучи (Heap) через NIO (например, в Netty, Kafka). Лимитируется через `-XX:MaxDirectMemorySize`.

## Базовые концепции

### Эволюция рантайма в контейнерах (Java 21+)

Начиная с версий Java 21 (LTS) и 25 (LTS), платформа получила существенные улучшения для контейнеризации и управления памятью.

*   **Compact Object Headers (Java 25+):** Снижает потребление Heap на **15–30%** за счет уменьшения размера заголовков объектов. Включается через `-XX:+UseCompactObjectHeaders`.
*   **Generational ZGC:** Обеспечивает паузы сборщика мусора **<1 мс** даже на очень больших объемах памяти, эффективно разделяя объекты по поколениям.
*   **Container Awareness:** Современные JVM (11+) нативно поддерживают лимиты CPU и RAM из cgroups v1/v2, корректно определяя количество доступных ядер и объем памяти.
*   **GOMEMLIMIT-like tuning:** Использование `-XX:MaxRAMPercentage=75.0` является стандартом для защиты от OOM Kill, оставляя 25% памяти на Metaspace, стеки потоков и нужды ОС.

### Выбор базового образа (Сравнение 2026)

| Тип образа | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Wolfi (Chainguard)** | **0 CVE**, нативный `glibc`, non-root. | Требует настройки путей SDK. | **Основной выбор для Prod**. |
| **Axiom Linux Base** | **Hardened-образ**, оптимизированный под Java, 0 CVE. | Менее распространен в open-source. | Для высокозащищенных контуров. |
| **Alpine (`-alpine`)** | Минимальный размер. | `musl` требует тестирования производительности. | Для простых утилит. |
| **Distroless** | Максимальная безопасность (нет shell). | Сложность диагностики внутри. | Для стабильных микросервисов. |
| **Ubuntu (`-noble`)** | Максимальная совместимость. | Большой размер, наличие CVE. | Для сложных legacy-систем. |

### Оптимизация управления памятью

*   **Heap Hard Limit:** Всегда ограничивайте кучу через `%` от памяти контейнера, а не абсолютные значения, для гибкости при масштабировании.
*   **Soft Max Heap Size:** Используйте `-XX:SoftMaxHeapSize`, чтобы GC активнее возвращал память операционной системе при низкой нагрузке.

### Multi-stage сборка для Java (Best Practices)

Multi-stage сборка является обязательной для Java-приложений, так как JDK весит 300–600 МБ, а финальному рантайму нужен только JRE (~50–150 МБ) или нативный бинарник.

*   **Правильный порядок слоев:**
    1.  Копирование только манифеста зависимостей (`pom.xml`, `build.gradle`) → кэш mount → загрузка зависимостей.
    2.  Копирование исходного кода → сборка.
    3.  Копирование только артефакта (`target/*.jar`) в финальный этап.
*   **Кэш Maven/Gradle:** Никогда не копируйте `COPY . .` перед установкой зависимостей — это инвалидирует кэш при любом изменении кода.
*   **Разделение тестов и сборки:** Запускайте тесты в отдельном промежуточном этапе (`tester`), чтобы не включать тестовые зависимости в финальный образ.

### Управление зависимостями и кэширование

Для радикального ускорения сборок используйте комбинацию **BuildKit Cache Mounts + Bind Mounts**:

```dockerfile
# --- Stage: Dependency warm-up ---
FROM eclipse-temurin:25-jdk AS deps
WORKDIR /app
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 \
    --mount=type=bind,source=pom.xml,target=pom.xml \
    mvn dependency:go-offline -B

# --- Stage: Build ---
FROM eclipse-temurin:25-jdk AS builder
WORKDIR /app
COPY --from=deps /root/.m2 /root/.m2
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 \
    mvn package -DskipTests
```

*   **Maven Local Repository:** По умолчанию находится в `~/.m2/repository`. При монтировании через `type=cache` кэш сохраняется между сборками, но не попадает в итоговый образ.
*   **Gradle:** Аналогично Maven, использует `~/.gradle/caches`. В Dockerfile применяется `--mount=type=cache,target=/home/gradle/.gradle`.
*   **Gradle Daemon:** В CI/CD рекомендуется отключать демон (`org.gradle.daemon=false`) для предсказуемости, но в локальных сборках он ускоряет инкрементальные изменения.

### Воспроизводимость сборок (Reproducible Builds)

Для получения идентичных дайджестов JAR-файлов и образов при повторных сборках:

1.  **SOURCE_DATE_EPOCH:** Переменная окружения, фиксирующая временную метку. BuildKit поддерживает её нативно:
    ```dockerfile
    ARG SOURCE_DATE_EPOCH=1724200000
    ENV SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH}
    ```
2.  **Pinning по дайджесту:** Базовые образы фиксируются по SHA256:
    ```dockerfile
    FROM cgr.dev/chainguard/jdk:25@sha256:abc123...
    ```
3.  **Фиксация зависимостей:** Maven использует `mvn dependency:go-offline` с зафиксированными версиями в `pom.xml`. Gradle — `gradle dependencies --write-locks`.
4.  **Удаление путей:** Используйте `-fdebug-prefix-map` (для нативных бинарников) или убедитесь, что `pom.xml` не содержит абсолютных путей.

### .dockerignore для Java

Исключение лишних файлов из контекста сборки радикально ускоряет передачу данных в BuildKit:

```dockerignore
# Системные директории
.git
.idea
.vscode

# Сборка Maven/Gradle
target/
build/
out/

# Зависимости (не нужны в контексте при использовании кэширования зависимостей)
vendor/
node_modules/

# Конфигурации и документация
*.md
LICENSE
.dockerignore
Dockerfile*
docker-compose*
Makefile
Taskfile*
Jenkinsfile*
.gitlab-ci.yml
```

### Мультиплатформенная сборка и кросс-компиляция

Для сборки под AMD64 и ARM64 используйте `docker buildx build` с флагом `--platform`. Java-приложения не требуют нативной кросс-компиляции (в отличие от Go/C++), так как байт-код JVM платформо-независим. Однако GraalVM Native Image требует кросс-компиляции:

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --builder=remote-builder \
  -t myapp:1.0.0 .
```

*   **QEMU/binfmt_misc:** Для GraalVM Native Image под ARM64 требуется эмулятор QEMU, если сборка происходит на AMD64. Установите `binfmt_misc` на хосте сборщика.
*   **Spring Boot JAR:** Не требует кросс-компиляции — работает на любой архитектуре, поддерживаемой JVM.

### Оптимизация сборки (PGO и кэширование)

1.  **PGO (Profile-Guided Optimization):** В 2026 году использование PGO считается стандартом для высоконагруженных систем.
    *   *Процесс:* Соберите образ → запустите под нагрузкой → снимите профиль (через JFR или async-profiler) → пересоберите с профилем.
    *   *GraalVM Native Image:* Поддерживает PGO через флаг `--pgo=profile.iprof`.
2.  **Кэширование BuildKit:** Монтирование `~/.m2` и `~/.gradle` через `type=cache` ускоряет повторные сборки в разы.
3.  **Layered JAR:** В Spring Boot разделение на слои (`dependencies`, `spring-boot-loader`, `snapshot-dependencies`, `application`) позволяет Docker кэшировать неизменяемые слои.

### Подводные камни минимальных образов (scratch / distroless / Wolfi)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **HTTPS/TLS ошибки** | Нет доверенных CA | Копировать `/etc/ssl/certs/ca-certificates.crt` из builder |
| **Неверное время** | Нет базы `tzdata` | Копировать `/usr/share/zoneinfo` или устанавливать `TZ=UTC` |
| **Permission Denied** | Запуск от root | Создать UID 10001 в builder и скопировать `/etc/passwd` |
| **ClassNotFoundException** | JLink отсек нужный модуль | Проверить `jdeps --print-module-deps` и добавить модуль |
| **DNS Resolving** | Проблемы с resolver в minimal image | Настройка `-Djava.net.preferIPv4Stack=true` или использование Wolfi |
| **OOM Kill (Exit 137)** | Отсутствие `-XX:MaxRAMPercentage` | Установить `-XX:MaxRAMPercentage=75.0` |
| **CPU Throttling** | Потоки GC превышают лимит CPU | Использовать `-XX:PreferContainerQuotaForCPUCount=true` |
| **Locale errors** | Нет `glibc` locale | Копировать `/usr/share/locale` или использовать Wolfi |

## Практические сценарии

### Сценарий 1: Spring Boot 3.5+ с Layered JAR (Золотой стандарт)

Разделение JAR на слои гарантирует, что при изменении одной строки кода Docker пересоберет только верхний слой весом в несколько КБ.

```dockerfile
# syntax=docker/dockerfile:1
# --- Stage 1: Build & Extract ---
FROM cgr.dev/chainguard/jdk:latest AS builder
WORKDIR /app
COPY . .
# Кэширование Maven зависимостей через BuildKit
RUN --mount=type=cache,target=/root/.m2 \
    ./mvnw clean package -DskipTests && \
    java -Djarmode=layertools -jar target/*.jar extract

# --- Stage 2: Hardened Runtime ---
FROM cgr.dev/chainguard/jre:latest
WORKDIR /app
# Копируем слои: от самых стабильных к часто меняющимся
COPY --from=builder /app/dependencies/ ./
COPY --from=builder /app/spring-boot-loader/ ./
COPY --from=builder /app/snapshot-dependencies/ ./
COPY --from=builder /app/application/ ./

# Тюнинг для Java 25/26: Компактные заголовки и ZGC
ENTRYPOINT ["java", \
    "-XX:+UseZGC", \
    "-XX:+UseCompactObjectHeaders", \
    "-XX:MaxRAMPercentage=75.0", \
    "-XX:+ExitOnOutOfMemoryError", \
    "org.springframework.boot.loader.launch.JarLauncher"]
```

### Сценарий 2: Кастомная модульная JRE через JLink

Создание минимального рантайма, содержащего только необходимые модули JDK.

```dockerfile
# syntax=docker/dockerfile:1
FROM eclipse-temurin:25-jdk-alpine AS jre-builder
WORKDIR /app
COPY . .
RUN ./mvnw clean package -DskipTests

# Создание кастомной JRE (удаляем неиспользуемые модули)
# jdeps используется для автоматического определения необходимых модулей приложения
RUN JAVA_MODULES=$(jdeps --ignore-missing-deps --print-module-deps --recursive --multi-release 25 target/*.jar) && \
    $JAVA_HOME/bin/jlink \
    --add-modules $JAVA_MODULES,java.instrument \
    --strip-debug \
    --no-man-pages \
    --no-header-files \
    --compress=2 \
    --output /javaruntime

FROM alpine:3.24
WORKDIR /app
ENV JAVA_HOME=/opt/java/jre
ENV PATH="${JAVA_HOME}/bin:${PATH}"
COPY --from=jre-builder /javaruntime $JAVA_HOME
COPY --from=jre-builder /app/target/*.jar app.jar

# Безопасность: запуск от не-root пользователя
RUN adduser -S appuser && chown -R appuser /app
USER appuser
ENTRYPOINT ["java", "-jar", "app.jar"]
```

### Сценарий 3: GraalVM Native Image (Максимальная плотность)

Идеально для систем с мгновенным масштабированием и ограниченными ресурсами.

```dockerfile
# syntax=docker/dockerfile:1
FROM ghcr.io/graalvm/native-image-community:21 AS builder
WORKDIR /build
COPY . .
RUN ./mvnw -Pnative native:compile -DskipTests

FROM cgr.dev/chainguard/static:latest
COPY --from=builder /build/target/app-binary /app
USER 65532
# Нативный бинарник стартует за 20-50 мс
ENTRYPOINT ["/app"]
```

### Сценарий 4: WAR в Tomcat / Jetty (legacy)

Для приложений, которые нельзя перевести на Spring Boot с embedded-сервером — классический WAR-деплой на сервер приложений.

```dockerfile
# syntax=docker/dockerfile:1

# --- Этап сборки ---
FROM eclipse-temurin:21-jdk AS builder
WORKDIR /build
COPY pom.xml .
RUN --mount=type=cache,target=/root/.m2 \
    mvn dependency:go-offline -B
COPY src ./src
RUN --mount=type=cache,target=/root/.m2 \
    mvn package -DskipTests -B

# --- Финальный этап: Tomcat ---
FROM tomcat:10.1-jdk17-temurin
# Удаляем дефолтные приложения (ROOT, examples, manager) — уменьшает attack surface
RUN rm -rf /usr/local/tomcat/webapps/*
COPY --from=builder /build/target/*.war /usr/local/tomcat/webapps/ROOT.war

# Tomcat стартует как PID 1 и корректно обрабатывает SIGTERM (graceful shutdown)
EXPOSE 8080
CMD ["catalina.sh", "run"]
```

**Jetty (альтернатива):**

```dockerfile
FROM jetty:11-jdk17-temurin
COPY --from=builder /build/target/*.war /var/lib/jetty/webapps/ROOT.war
EXPOSE 8080
```

**Валидация:**
```bash
docker build -t my-war-app:latest .
docker run -d -p 8080:8080 --name war-app my-war-app:latest
curl -s http://localhost:8080/health
# → OK

# Graceful shutdown
docker stop --timeout 30 war-app
docker inspect war-app --format='{{.State.ExitCode}}'
# → 0
```

**Рекомендация:** для новых проектов используйте Spring Boot с embedded Tomcat (Сценарий 1) — WAR на внешний сервер приложений оправдан только для legacy-приложений и Jakarta EE-проектов. WildFly/JBoss контейнеризируются аналогично (`jboss/wildfly`), но требуют настройки management-порта и пользователей.

## Отладка и мониторинг

### Инспекция Container Awareness

JVM должна видеть лимиты контейнера, а не хоста:
```bash
docker exec <id> java -XshowSettings:system -version
```

### Наблюдаемость (Observability)

*   **JFR (Java Flight Recorder):** Включайте в контейнерах для низкоуровневой диагностики без оверхеда: `-XX:StartFlightRecording=disk=true,dumponexit=true`.
*   **Prometheus:** Используйте `jmx_exporter` как Java-агент для сбора метрик в формате Prometheus.

### Обработка сигналов и завершение

Всегда используйте `ENTRYPOINT` в форме массива `["java", "-jar", ...]`, чтобы JVM была PID 1 (или дочерним процессом Tini) и корректно принимала сигнал `SIGTERM` для выполнения Graceful Shutdown.

## Дополнительная информация

### Смотрите также

- **[Безопасность Java-образов: Hardening](../../Docker_security/java-image-security.md)** — глубокий анализ угроз и методов защиты.
- **[Управление и тюнинг Java (JVM)](../../../Linux/Development/java_management.md)** — SSoT по параметрам памяти и GC.
- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие принципы кэширования.
- **[Безопасность в Dockerfile](./security.md)** — работа с non-root и SBOM.
- **[Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)** — поддержка ARM64/AMD64.
- **[Проблема зомби-процессов (PID 1)](./container_execution.md)** — теория обработки сигналов.
