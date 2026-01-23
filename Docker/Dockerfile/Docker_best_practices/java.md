# Dockerfile: Лучшие практики для Java

1.  **Осведомленность о cgroups (Cgroup Awareness):**
    *   **Проблема:** Старые версии Java (до 8u131, например, Java 7) **не поддерживают [cgroups](../../Docker_components/docker_components.md#cgroups-управление-ресурсами)**.
    *   **Решение:** Если вы используете старую версию, **обязаны** вручную задавать размер кучи через флаги `-Xmx` и `-Xms`.
2.  **Multi-stage сборка:**
    *   **Этап 1 (builder):** Используется "тяжелый" образ с JDK и сборочным инструментом (Maven/Gradle).
    *   **Этап 2 (final):** Используется минималистичный образ только со средой выполнения (JRE), куда копируется собранный артефакт (JAR-файл).
    ```dockerfile
    # Этап 1: Сборка с Maven
    FROM maven:3.9.11-eclipse-temurin-25 AS builder
    WORKDIR /app
    COPY pom.xml .
    RUN --mount=type=cache,target=/root/.m2 mvn dependency:go-offline
    COPY src ./src
    RUN mvn package
    # Этап 2: Финальный образ с OpenJDK
    FROM eclipse-temurin:21-jre-alpine
    WORKDIR /app
    COPY --from=builder /app/target/*.jar app.jar
    EXPOSE 8080
    CMD ["java", "-jar", "app.jar"]
    ```
3.  **Управление памятью:**
    *   **Ограничивайте размер кучи (heap):** Явно задавайте максимальный размер кучи (`-Xmx<size>` или `-XX:MaxRAMPercentage`).
    *   **Дайте контейнеру больше памяти:** Выделяйте контейнеру примерно на 25% больше памяти, чем установлено в `-Xmx`, для нужд JVM.
4.  **Кэширование зависимостей:**
    *   Используйте `--mount=type=cache` для кэширования директорий `.m2` или `.gradle` для ускорения повторных сборок.
