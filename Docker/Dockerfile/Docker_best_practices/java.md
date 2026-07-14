# Dockerfile: Лучшие практики для Java

## Определения

* **JDK (Java Development Kit):** Комплект разработчика Java, включающий JRE, компилятор (`javac`) и инструменты сборки.
* **OOM (Out Of Memory) Killed:** Событие принудительной остановки контейнера операционной системой из-за превышения лимита выделенной памяти.
* **Внутренние зависимости:** Библиотеки (`.jar`), которые упаковываются внутрь контейнера.
* **Внешние зависимости:** Окружение (JRE, системные конфиги), которые Docker изолирует от хостовой системы.
*(Определения JVM, JRE, Heap и cgroups вынесены в [Управление и тюнинг Java (JVM)](../../../Linux/Development/java_management.md))*

## Основные концепции

### Синхронизация версий

Версия Java в базовых образах (`FROM`) должна строго соответствовать или быть выше версии, указанной в манифесте проекта. Определить её можно следующим образом:

*   **Maven (`pom.xml`)**: Ищите свойство `<java.version>` или параметры `source`/`target` в `maven-compiler-plugin`.
*   **Gradle (`build.gradle`)**: Ищите `sourceCompatibility`, `targetCompatibility` или блок `java { toolchain { languageVersion = ... } }`.

Это гарантирует, что среда выполнения (JRE) сможет исполнить байт-код, созданный на этапе сборки (JDK).

### Многоэтапная сборка

Для Java-приложений критически важно использовать [многоэтапную сборку](./build_optimization.md). Паттерн заключается в использовании JDK для компиляции на первом этапе и JRE для запуска на втором. Это позволяет уменьшить размер финального образа на 40–50%.

### Мультиплатформенная сборка (Buildx)

Частая проблема Java-разработки — несовместимость архитектур (например, сборка на Mac ARM64 для запуска на сервере AMD64). Современный подход требует использования `buildx`:

```bash
# Создание и активация билдера
docker buildx create --name mybuilder --use

# Сборка сразу под две архитектуры
docker buildx build --platform linux/amd64,linux/arm64 -t myapp:1.0 --push .
```
Подробнее см. **[BuildKit и Buildx](../dockerfile_buildkit.md)**.

### Использование .dockerignore

Для Java-проектов важно исключать мусор сборки и настройки IDE из контекста Docker, чтобы уменьшить размер и ускорить `COPY`:

```text
# .dockerignore
## Второй этап

```
FROM eclipse-temurin:21-jre-alpine
```

Используется только JRE.

Это значительно уменьшает размер итогового образа.
```
*(Мы исключаем всё содержимое `build/` или `target/`, кроме итогового JAR-файла, который нужен для инструкции `COPY` в простом Dockerfile).*

*(Детальная информация о настройке памяти JVM, осведомленности о лимитах контейнера и флагах описана в [Управление и тюнинг Java (JVM)](../../../Linux/Development/java_management.md))*


## Практические сценарии

### Сценарий 1: Многоэтапная сборка с использованием кэша BuildKit

Современный и наиболее практичный подход при использовании BuildKit. Вместо разделения на `dependency:go-offline` и `package`, мы используем один запуск Maven с монтированием кэша. Это упрощает Dockerfile и уменьшает количество слоев.

```dockerfile
# --- Этап 1: Сборка с Maven (builder) ---
FROM maven:3.9.11-eclipse-temurin-21 AS builder
WORKDIR /app

# Копируем манифест и исходный код
COPY pom.xml .
COPY src ./src

# Сборка приложения с использованием кэша Maven (~/.m2)
# clean: удаляет старые артефакты
# -DskipTests: ускоряет сборку (если тесты проходят на отдельном этапе CI)
RUN --mount=type=cache,target=/root/.m2 \
    mvn clean package -DskipTests
# → Проект собран, зависимости в кэше, слоев меньше

# --- Этап 2: Финальный образ (production) ---
FROM eclipse-temurin:21-jre-alpine
WORKDIR /app

# Копируем только собранный JAR-файл
COPY --from=builder /app/target/*.jar app.jar

# Создаем непривилегированного пользователя (синтаксис Alpine/BusyBox)
RUN adduser -S appuser
USER appuser

EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
```

**Почему это эффективно:**
*   **`clean package`**: Гарантирует сборку «с нуля» без остатков предыдущих попыток внутри контейнера.
*   **`--mount=type=cache`**: Если вы используете BuildKit, зависимости будут подтягиваться из локального кэша хоста/билдера, даже если слои Docker были сброшены из-за изменений в `pom.xml`.
*   **`-DskipTests`**: Существенно экономит время сборки образа. Тесты рекомендуется запускать на более ранних стадиях CI.

**Примечание про `dependency:go-offline`:**
Раздельный запуск (`COPY pom.xml` -> `RUN mvn dependency:go-offline`) всё ещё имеет смысл в средах **без BuildKit** или при медленном сетевом соединении, так как позволяет Docker закешировать слой со всеми внешними библиотеками. В современных пайплайнах с кэшированием монтируемых директорий этот подход становится избыточным.

### Сценарий 2: Spring Boot приложение с Maven Wrapper

Пример использования Maven Wrapper (`mvnw`), который автоматически загружает нужную версию Maven, исключая зависимость от предустановленных инструментов в базовом образе.

```dockerfile
# --- Этап 1: Сборка (builder) ---
FROM eclipse-temurin:21-jdk AS builder
WORKDIR /app

# Копируем Maven Wrapper и pom.xml для кеширования зависимостей
COPY .mvn/ .mvn
COPY mvnw pom.xml ./

# Скачиваем зависимости (без сборки) — слой кешируется
RUN ./mvnw dependency:go-offline
# → Зависимости загружены через wrapper

# Копируем исходный код и собираем JAR (Java Archive)
COPY src ./src
RUN ./mvnw clean package -DskipTests
# → Собран app.jar без выполнения тестов

# --- Этап 2: Финальный образ (production) ---
FROM eclipse-temurin:21-jre
WORKDIR /app

# Копируем JAR из builder
COPY --from=builder /app/target/*.jar app.jar

EXPOSE 8080

# Запуск с указанием максимальной доли RAM для кучи
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75.0", "-jar", "app.jar"]
```

## Дополнительная информация

* [Оптимизация сборки Docker-образов](./build_optimization.md) — многоэтапная сборка, jlink и минимизация размера
* [Безопасность в Dockerfile](./security.md) — непривилегированные пользователи и distroless-образы
* [Управление и тюнинг Java (JVM)](../../../Linux/Development/java_management.md) — SSoT: детальная настройка лимитов, cgroups и флагов производительности
