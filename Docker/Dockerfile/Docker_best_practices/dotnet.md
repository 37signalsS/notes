# Dockerfile: Лучшие практики для .NET

## Определения

- **SDK (Software Development Kit):** Полный набор инструментов (компиляторы, библиотеки, CLI) для сборки приложения. Используется только на этапе сборки.
- **Runtime:** Минимальная среда для запуска байт-кода .NET. Различают `aspnet` (для веб-приложений) и `runtime` (для консольных задач).
- **Native AOT (Ahead-of-Time):** Режим компиляции приложения в нативный машинный код. Исключает необходимость в JIT и наличии рантайма в финальном образе, существенно снижает потребление памяти и время холодного старта.
- **ReadyToRun (R2R):** Формат публикации, содержащий как промежуточный код (IL), так и предварительно скомпилированный нативный код. Ускоряет запуск без ограничений Native AOT.
- **NuGet:** Официальный менеджер пакетов для .NET.
- **Chiseled Images:** Ультра-минималистичные образы (от Microsoft и Canonical), не содержащие shell, пакетных менеджеров и лишних библиотек. Идеальны для безопасности и минимального размера.
- **Globalization Invariant Mode:** Режим работы .NET, при котором приложение не использует специфичные для культур данные (ICU). Позволяет уменьшить размер образа на ~20–50 МБ и использовать Alpine-образы без дополнительных зависимостей.
- **Tiered Compilation:** Механизм .NET, позволяющий рантайму быстро запустить код (Quick JIT), а затем перекомпилировать горячие методы с максимальной оптимизацией.

## Базовые концепции

### Многоэтапная сборка (Multi-stage)

Разделение этапов сборки и выполнения является стандартом для .NET в контейнерах:
1.  **Этап сборки (Build):** Используется тяжелый образ `mcr.microsoft.com/dotnet/sdk`. Здесь происходит восстановление пакетов, сборка и публикация.
2.  **Этап выполнения (Runtime):** Используется легкий образ `mcr.microsoft.com/dotnet/aspnet` или `mcr.microsoft.com/dotnet/runtime`. Содержит только необходимые компоненты для работы.

### Управление ресурсами и GC

.NET отлично адаптирован под контейнеры, но требует настройки для экстремальных нагрузок:
*   **GC Heap Limit:** Начиная с .NET 8/9, рантайм автоматически подстраивается под лимиты памяти cgroups. Для предотвращения OOMKilled при резких скачках можно явно ограничить кучу через `DOTNET_GCHeapHardLimit`.
*   **Server GC vs Workstation GC:** В контейнерах с малым количеством ядер (<2) рекомендуется отключать Server GC (`DOTNET_gcServer=0`) для снижения потребления памяти.
*   **CPU Limits:** .NET использует количество ядер для определения параллелизма в ThreadPool и GC. При использовании дробных лимитов (например, 0.5 CPU) рантайм округлит значение до 1.

### Глобализация и локализация

Для большинства микросервисов, работающих с JSON и техническими данными, инвариантный режим является предпочтительным:
```dockerfile
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
```
Это критично для Alpine-образов, так как они по умолчанию не включают `icu-libs`.

### Безопасность (Rootless и порты)

В современных образах .NET (8.0, 9.0 и далее) предустановлен пользователь `app` (UID 1654).
*   **Порты:** Приложение по умолчанию слушает порт `8080` вместо `80`.
*   **Права:** Пользователь `app` не имеет прав на запись в системные директории и биндинг привилегированных портов (<1024).

## Практические сценарии

### Сценарий 1: Оптимизированный ASP.NET Core для Production (2026)

Использование .NET 10 (прогноз), монтирования кэша и кросс-компиляции.

```dockerfile
# syntax=docker/dockerfile:1
# check=error=true

# --- Этап 1: Сборка (builder) ---
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS builder
ARG TARGETARCH
WORKDIR /src

# Отключаем телеметрию для ускорения
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1

# Копируем .csproj файлы для кэширования слоев восстановления NuGet
COPY ["src/Gateway.Api/Gateway.Api.csproj", "src/Gateway.Api/"]
COPY ["src/Common.Library/Common.Library.csproj", "src/Common.Library/"]

# Используем монтирование кэша BuildKit для NuGet
RUN --mount=type=cache,id=nuget,target=/root/.nuget/packages \
    dotnet restore "src/Gateway.Api/Gateway.Api.csproj" -a $TARGETARCH

# Копируем остальной код
COPY . .

# Сборка и публикация в режиме ReadyToRun для ускорения старта
RUN --mount=type=cache,id=nuget,target=/root/.nuget/packages \
    dotnet publish "src/Gateway.Api/Gateway.Api.csproj" \
    -c Release \
    -o /app/publish \
    -a $TARGETARCH \
    --no-restore \
    -p:PublishReadyToRun=true

# --- Этап 2: Финальный образ (runtime) ---
FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine
WORKDIR /app

# Настройки рантайма для контейнера
ENV ASPNETCORE_URLS=http://+:8080 \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    DOTNET_RUNNING_IN_CONTAINER=true

# Копируем артефакты
COPY --from=builder /app/publish .

# Проверка здоровья без установки тяжелого curl (используем возможности .NET 9+)
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD dotnet /app/HealthCheckClient.dll || exit 1

# Запуск от не-root пользователя
USER app
EXPOSE 8080
ENTRYPOINT ["dotnet", "Gateway.Api.dll"]
```

### Сценарий 2: Native AOT и Chiseled-образы (Безопасность + Скорость)

Максимальная производительность и минимальный вектор атаки.

```dockerfile
# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS builder
# Установка зависимостей для Native AOT
RUN apt-get update && apt-get install -y clang zlib1g-dev

WORKDIR /src
COPY . .
# Публикация в нативный код
RUN dotnet publish "Fast.Service.csproj" \
    -c Release \
    -r linux-x64 \
    -o /app/publish \
    /p:PublishAot=true

# Финальный Chiseled-образ (Ubuntu-based, без shell)
FROM mcr.microsoft.com/dotnet/nightly/runtime-deps:10.0-jammy-chiseled
WORKDIR /app
COPY --from=builder /app/publish/Fast.Service .
USER app
ENTRYPOINT ["./Fast.Service"]
```

### Сценарий 3: Среда разработки с Hot Reload

Использование `dotnet watch` для мгновенного применения изменений кода.

```dockerfile
# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS dev
WORKDIR /app
COPY . .
# Включаем Hot Reload для Docker
ENV DOTNET_WATCH_USE_POLLING_FILE_WATCHER=1
ENTRYPOINT ["dotnet", "watch", "run", "--urls", "http://0.0.0.0:8080"]
```

## Диагностика и мониторинг

### Sidecar для диагностики

В 2026 году стандартным подходом является использование sidecar-контейнера с `dotnet-monitor` для получения дампов и трейсов без изменения основного образа:
1.  **Сбор дампов:** `dotnet-monitor dump`
2.  **Сбор трейсов:** `dotnet-monitor collect`
Это позволяет держать основной образ максимально легким (Alpine/Chiseled), при этом имея полный инструментарий отладки рядом.

### Наблюдаемость (Observability)

Интеграция OpenTelemetry является обязательной:
*   Используйте переменные окружения `OTEL_EXPORTER_OTLP_ENDPOINT` для настройки экспорта метрик и трейсов из контейнера.
*   .NET 10+ нативно поддерживает многие протоколы OTLP без дополнительных NuGet пакетов для базовых метрик.

## Дополнительная информация

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — кэширование, слои и Multi-stage.
- **[Безопасность в Dockerfile](./security.md)** — аудит, сканирование CVE и работа с пользователями.
- **[Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)** — сборка под ARM64 и AMD64.
- **[Проблема зомби-процессов (PID 1)](./container_execution.md)** — важно для приложений, запускающих дочерние процессы.
- **[Официальная документация по переменным .NET](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-environment-variables)**
