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

## Базовые концепции

### Эволюция рантайма в контейнерах (Java 21/25/26)

Начиная с версий Java 21 и 25 (LTS), платформа стала полностью адаптированной для облачных сред и контейнеризации.

*   **Compact Object Headers (Java 25+):** Снижает потребление Heap на **15–30%** за счет уменьшения размера заголовков объектов. Включается через `-XX:+UseCompactObjectHeaders`.
*   **Generational ZGC:** Обеспечивает паузы сборщика мусора **<1 мс** даже на очень больших объемах памяти, эффективно разделяя объекты по поколениям.
*   **Container Awareness:** Современные JVM (11+) нативно поддерживают лимиты CPU и RAM из cgroups v1/v2, корректно определяя количество доступных ядер и объем памяти.
*   **GOMEMLIMIT-like tuning:** Использование `-XX:MaxRAMPercentage=75.0` является стандартом для защиты от OOM Kill, оставляя 25% памяти на Metaspace, стеки потоков и нужды ОС.

### Выбор базового образа (Сравнение 2026)

| Тип образа | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Wolfi (Chainguard)** | **0 CVE**, нативный `glibc`, non-root. | Требует настройки путей SDK. | **Основной выбор для Prod**. |
| **Alpine (`-alpine`)** | Минимальный размер. | `musl` требует тестирования производительности. | Для простых утилит. |
| **Distroless** | Максимальная безопасность (нет shell). | Сложность диагностики внутри. | Для стабильных микросервисов. |
| **Ubuntu (`-noble`)** | Максимальная совместимость. | Большой размер, наличие CVE. | Для сложных legacy-систем. |

### Оптимизация управления памятью

*   **Heap Hard Limit:** Всегда ограничивайте кучу через `%` от памяти контейнера, а не абсолютные значения, для гибкости при масштабировании.
*   **Soft Max Heap Size:** Используйте `-XX:SoftMaxHeapSize`, чтобы GC активнее возвращал память операционной системе при низкой нагрузке.

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
RUN $JAVA_HOME/bin/jlink \
    --add-modules java.base,java.logging,java.naming,java.security.jgss,java.instrument \
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

Идеально для Serverless и систем с мгновенным масштабированием.

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

- **[Управление и тюнинг Java (JVM)](../../../Linux/Development/java_management.md)** — SSoT по параметрам памяти и GC.
- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — общие принципы кэширования.
- **[Безопасность в Dockerfile](./security.md)** — работа с non-root и SBOM.
- **[Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)** — поддержка ARM64/AMD64.
- **[Проблема зомби-процессов (PID 1)](./container_execution.md)** — теория обработки сигналов.
