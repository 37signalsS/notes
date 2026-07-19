# Dockerfile: Лучшие практики для Java

> **Надежность: 10** (Актуализировано согласно стандартам 2026 года, Java 21/25)

## Определения

- **JDK (Java Development Kit):** Комплект разработчика, необходимый для компиляции исходного кода в байт-код. Содержит компилятор `javac` и инструменты сборки.
- **JRE (Java Runtime Environment):** Минимальный набор компонентов для запуска Java-приложений. В современных версиях (Java 9+) рекомендуется создавать кастомные JRE через **JLink**.
- **Layered JAR:** Технология (внедренная в Spring Boot), позволяющая разделить JAR-файл на слои (зависимости, ресурсы, код) для эффективного кэширования в Docker.
- **CDS (Class Data Sharing):** Механизм ускорения запуска JVM за счет сохранения метаданных классов в архив при сборке и их быстрого отображения в память при старте.
- **Distroless:** Образы, содержащие только приложение и его рантайм-зависимости, без оболочки (shell), пакетного менеджера и других утилит.

## Базовые концепции

### Многоэтапная сборка (Multi-stage)

Для Java-приложений разделение этапа сборки и запуска является обязательным.
1. **Этап сборки:** Используется полный образ JDK (например, `eclipse-temurin:21-jdk`). Здесь происходит компиляция и выполнение тестов.
2. **Этап выполнения:** Используется легковесный JRE, Distroless или кастомный образ, созданный через JLink. Это сокращает размер образа с ~500 МБ до ~100-150 МБ и повышает безопасность.

### Выбор базового образа

| Тип образа | Преимущества | Недостатки |
| :--- | :--- | :--- |
| **Alpine (`-alpine`)** | Минимальный размер, безопасность. | Использует `musl` вместо `glibc`, что может вызвать проблемы с некоторыми нативными библиотеками. |
| **Ubuntu/Debian (`-slim`)** | Высокая совместимость, стандартная `glibc`. | Больший размер по сравнению с Alpine. |
| **Distroless** | Максимальная безопасность (нет shell). | Сложность отладки (требуются эфемерные контейнеры). |

### Оптимизация кэширования зависимостей

Java-зависимости (библиотеки в `~/.m2` или `~/.gradle`) меняются реже, чем код. Использование `--mount=type=cache` в BuildKit позволяет сохранять кэш между сборками, не раздувая при этом слои образа.

### Осведомленность о лимитах (Container Awareness)

Современные версии Java (8u191+, 11+) корректно распознают лимиты памяти и ЦП в контейнере. Настройка параметров памяти (`-XX:MaxRAMPercentage`) должна производиться согласно SSoT-файлу [Управление и тюнинг Java (JVM)](../../../Linux/Development/java_management.md).

## Практические сценарии

### Сценарий 1: Spring Boot 3 + Layered JAR (Оптимальный для Spring)

Разделение JAR на слои позволяет обновлять только слой с кодом (несколько КБ), не перекачивая сотни МБ зависимостей.

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Сборка и разделение на слои ---
FROM eclipse-temurin:21-jdk-alpine AS builder
WORKDIR /app
COPY . .
# Сборка и извлечение слоев через специальный режим Spring Boot
RUN --mount=type=cache,target=/root/.m2 \
    ./mvnw clean package -DskipTests && \
    java -Djarmode=layertools -jar target/*.jar extract

# --- Этап 2: Финальный образ ---
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
# Копируем слои по отдельности (от редко меняющихся к часто меняющимся)
COPY --from=builder /app/dependencies/ ./
COPY --from=builder /app/spring-boot-loader/ ./
COPY --from=builder /app/snapshot-dependencies/ ./
COPY --from=builder /app/application/ ./

# Запуск через Launcher для поддержки слоев
ENTRYPOINT ["java", "org.springframework.boot.loader.launch.JarLauncher"]
```

### Сценарий 2: Кастомная JRE через JLink (Минимальный размер)

Создание образа, содержащего только необходимые модули Java.

```dockerfile
# --- Этап 1: Сборка и JLink ---
FROM eclipse-temurin:21-jdk-alpine AS jre-builder
WORKDIR /app
COPY . .
RUN ./mvnw clean package -DskipTests

# Создание кастомного JRE
RUN $JAVA_HOME/bin/jlink \
    --add-modules java.base,java.logging,java.naming,java.desktop,java.management,java.security.jgss,java.instrument \
    --strip-debug \
    --no-man-pages \
    --no-header-files \
    --compress=2 \
    --output /javaruntime

# --- Этап 2: Финальный образ ---
FROM alpine:3.24
WORKDIR /app
ENV JAVA_HOME=/opt/java/jre
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Копируем кастомный JRE и JAR
COPY --from=jre-builder /javaruntime $JAVA_HOME
COPY --from=jre-builder /app/target/*.jar app.jar

RUN adduser -S appuser && chown appuser /app
USER appuser

ENTRYPOINT ["java", "-jar", "app.jar"]
```

### Сценарий 3: Ускорение старта через CDS (Class Data Sharing)

Полезно для Serverless и систем с частым масштабированием.

```dockerfile
# ... (после этапа сборки) ...
# Генерация CDS архива
RUN java -XX:ArchiveClassesAtExit=app.jsa -jar app.jar || true

# Запуск с использованием архива
ENTRYPOINT ["java", "-XX:SharedArchiveFile=app.jsa", "-jar", app.jar"]
```

### Сценарий 4: Безопасный Distroless образ

```dockerfile
FROM gcr.io/distroless/java21-debian12
WORKDIR /app
COPY --from=builder /app/target/*.jar app.jar
USER nonroot:nonroot
CMD ["app.jar"]
```

## Дополнительная информация

- [Управление и тюнинг Java (JVM)](../../../Linux/Development/java_management.md) — SSoT по настройке памяти и флагов.
- [Оптимизация сборки Docker-образов](./build_optimization.md) — общие принципы кэширования и multi-stage.
- [Безопасность в Dockerfile](./security.md) — работа с пользователями и сканирование образов.
- [Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md) — сборка под разные архитектуры процессоров.
