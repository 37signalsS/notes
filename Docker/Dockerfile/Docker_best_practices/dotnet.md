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
- **runtime-deps:** Минимальный образ от Microsoft, содержащий только зависимости .NET (libicu, libssl, линковщик) без самого рантайма. Используется как база для Native AOT, где рантайм .NET не нужен — приложение компилируется в нативный код. Размер: ~25 МБ (Alpine) vs ~80 МБ (aspnet).
- **docker init:** Команда CLI Docker, автоматически генерирующая Dockerfile, docker-compose.yml и .dockerignore для проекта. Для .NET создаёт оптимизированный multi-stage Dockerfile с правильными базовыми образами и переменными окружения.
- **Health Probe (Liveness/Readiness/Startup):** Механизм Kubernetes для проверки состояния контейнера. Liveness — перезапускает контейнер при зависании. Readiness — убирает из балансировщика при недоступности. Startup — защищает от ложных срабатываний Liveness при длительном старте ( характерно для .NET с cold start).

## Базовые концепции

### Многоэтапная сборка (Multi-stage)

Разделение этапов сборки и выполнения является стандартом для .NET в контейнерах:
1.  **Этап сборки (Build):** Используется тяжелый образ `mcr.microsoft.com/dotnet/sdk`. Здесь происходит восстановление пакетов, сборка и публикация.
2.  **Этап выполнения (Runtime):** Используется легкий образ `mcr.microsoft.com/dotnet/aspnet` или `mcr.microsoft.com/dotnet/runtime`. Содержит только необходимые компоненты для работы.

### Выбор базового образа: runtime-deps vs aspnet vs runtime

Microsoft предоставляет три категории образов для финальной стадии. Правильный выбор определяет размер, функциональность и безопасность контейнера:

| Образ | Содержимое | Размер (Alpine) | Когда использовать |
| :--- | :--- | :--- | :--- |
| `runtime-deps` | Только зависимости (libicu, libssl, линковщик) | ~25 МБ | Native AOT (нет рантайма .NET) |
| `aspnet` | runtime-deps + ASP.NET Core + Kestrel | ~80 МБ | Веб-приложения (HTTP API, MVC, Razor) |
| `runtime` | runtime-deps + полный рантайм .NET | ~90 МБ | Консольные задачи, воркеры, инструменты CLI |

**Ключевые отличия:**
- `aspnet` включает `Microsoft.AspNetCore.App` — полный стек для веб-приложений (Kestrel, Routing, DI, Middleware). Если приложение использует `WebApplication.CreateBuilder()`, нужен именно `aspnet`.
- `runtime` не содержит ASP.NET Core — подходит для консольных приложений, фоновых сервисов (Worker Service), инструментов CI/CD.
- `runtime-deps` не содержит даже рантайм .NET — подходит только для Native AOT, где приложение компилируется в нативный код и не требует `dotnet`.

**Важно:** Начиная с .NET 8, образы `aspnet` и `runtime` доступны в вариантах `jammy-chiseled` (Ubuntu) и `alpine`. Chiseled-образы не содержат shell и пакетных менеджеров — максимальная безопасность, но невозможно отладить контейнер через `docker exec`.

### Управление ресурсами и GC

.NET отлично адаптирован под контейнеры, но требует настройки для экстремальных нагрузок:
*   **GC Heap Limit:** Начиная с .NET 8/9, рантайм автоматически подстраивается под лимиты памяти cgroups. Для предотвращения OOMKilled при резких скачках можно явно ограничить кучу через `DOTNET_GCHeapHardLimit` (значение в байтах или hex, например `0x38400000` = 900 МБ).
*   **Server GC vs Workstation GC:** В контейнерах с малым количеством ядер (<2) рекомендуется отключать Server GC (`DOTNET_gcServer=0`) для снижения потребления памяти. Server GC выделяет отдельный поток GC на каждое ядро — при 1 ядре это лишний оверхед.
*   **CPU Limits:** .NET использует количество ядер для определения параллелизма в ThreadPool и GC. При использовании дробных лимитов (например, 0.5 CPU) рантайм округлит значение до 1. Для корректного определения доступных ядер убедитесь, что контейнер запущен с `--cpus` (cgroups v2), а не с `--cpu-quota`.

### Переменные окружения .NET для контейнеров

Полный обзор переменных, влияющих на поведение .NET в Docker:

| Переменная | Описание | Рекомендуемое значение |
| :--- | :--- | :--- |
| `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` | Отключает ICU, уменьшает образ на ~20-50 МБ | `1` (если нет локализации) |
| `DOTNET_gcServer=0` | Workstation GC (меньше памяти при <2 ядер) | `0` для малых контейнеров |
| `DOTNET_GCHeapHardLimit` | Лимит кучи GC в байтах (hex: `0x38400000`) | 70-80% от лимита памяти |
| `DOTNET_GCHeapHardLimitPercent` | Лимит кучи GC в процентах от памяти хоста | `70` |
| `DOTNET_TC_ThreadPoolMinThreads` | Минимум потоков в ThreadPool | Значение по умолчанию |
| `DOTNET_TC_ThreadPoolMaxThreads` | Максимум потоков в ThreadPool | Значение по умолчанию |
| `DOTNET_SYSTEM_NET_HTTP_SOCKETSHTTPHANDLER_HTTP3SUPPORT` | Поддержка HTTP/3 | `1` (.NET 7+) |
| `DOTNET_RUNNING_IN_CONTAINER=true` | Указывает что приложение работает в контейнере | `true` |
| `ASPNETCORE_URLS` | Адреса для прослушивания Kestrel | `http://+:8080` |
| `DOTNET_CLI_TELEMETRY_OPTOUT=1` | Отключает телеметрию CLI | `1` |
| `DOTNET_EnableDiagnostics=0` | Отключает диагностику (diagnostics port) | `0` в production |

**Пример конфигурации для контейнера с 512 МБ памяти:**
```dockerfile
ENV DOTNET_RUNNING_IN_CONTAINER=true \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    DOTNET_gcServer=0 \
    DOTNET_GCHeapHardLimit=0x18000000 \
    ASPNETCORE_URLS=http://+:8080
```

### Кэширование слоёв: паттерн .csproj

Восстановление NuGet-пакетов — самая длительная операция в сборке .NET. Паттерн кэширования основан на том, что Docker пересобирает слой только при изменении его содержимого:

```dockerfile
# 1. Копируем ТОЛЬКО .csproj файлы (меняются редко)
COPY ["src/Api/Api.csproj", "src/Api/"]
COPY ["src/Core/Core.csproj", "src/Core/"]

# 2. Восстанавливаем пакеты (слой кэшируется, пока .csproj не изменятся)
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet restore

# 3. Копируем исходный код (меняется часто)
COPY . .

# 4. Сборка (пересобирается только этот слой)
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet publish -c Release -o /app/publish --no-restore
```

**Почему это работает:** Docker сравнивает checksum каждого слоя. Если `.csproj` не изменились — слой `dotnet restore` берётся из кэша, и пакеты не скачиваются заново. Это экономит 30–120 секунд на каждой сборке.

**BuildKit cache mount** (`--mount=type=cache`) дополнительно сохраняет пакеты на хосте между сборками, даже если базовый образ изменился. Это критично для CI/CD, где каждый запуск — новый агент.

### Глобализация и локализация

Для большинства микросервисов, работающих с JSON и техническими данными, инвариантный режим является предпочтительным:
```dockerfile
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
```
Это критично для Alpine-образов, так как они по умолчанию не включают `icu-libs`.

### Безопасность (Rootless, порты и isolation)

В современных образах .NET (8.0, 9.0 и далее) предустановлен пользователь `app` (UID 1654):
*   **Порты:** Приложение по умолчанию слушает порт `8080` вместо `80`. Это позволяет избежать привязки к привилегированным портам (<1024) без дополнительных настроек.
*   **Права:** Пользователь `app` не имеет прав на запись в системные директории и биндинг привилегированных портов.

**Рекомендуемые флаги запуска для .NET контейнеров:**
```bash
docker run -d \
  --read-only \                          # Read-only rootfs
  --tmpfs /tmp:rw,noexec,nosuid \       # Временные данные в tmpfs
  --cap-drop=ALL \                       # Удаление всех capabilities
  --cap-add=NET_BIND_SERVICE \           # Только если нужен порт < 1024
  --security-opt=no-new-privileges \     # Блокировка эскалации
  -e ASPNETCORE_URLS=http://+:8080 \
  -p 8080:8080 \
  my-dotnet-app:latest
```

**Зачем это нужно для .NET:**
- `--read-only` блокирует запись в `/tmp` и лог-файлы — containerized .NET приложения пишут во временные файлы, поэтому cần `--tmpfs /tmp`.
- `--cap-drop=ALL` + `--security-opt=no-new-privileges` предотвращают эскалацию привилегий, если в .NET рантайме обнаружена уязвимость.
- Пользователь `app` (UID 1654) уже непривилегирован — дополнительные меры isolation усиливают защиту.

Подробнее: [Безопасность в Dockerfile](./security.md).

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

# Проверка здоровья через ASP.NET Core Health endpoint
# В приложении должен быть endpoints.MapHealthChecks("/health")
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -sf http://localhost:8080/health || exit 1

# Запуск от не-root пользователя
USER app
EXPOSE 8080
ENTRYPOINT ["dotnet", "Gateway.Api.dll"]
```

### Сценарий 2: Native AOT и Chiseled-образы (Безопасность + Скорость)

Максимальная производительность и минимальный вектор атаки.

```dockerfile
# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:10.0@sha256:... AS builder
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
FROM mcr.microsoft.com/dotnet/nightly/runtime-deps:10.0-jammy-chiseled@sha256:...
WORKDIR /app
COPY --from=builder /app/publish/Fast.Service .
USER app
ENTRYPOINT ["./Fast.Service"]
```

**Валидация:**
```bash
# Проверка что образ не содержит shell (Chiseled)
docker run --rm my-app:latest /bin/sh -c "echo hacked" 2>&1
# → exec: "/bin/sh": executable file not found in $PATH

# Проверка размера
docker images my-app:latest
# → REPOSITORY   TAG       SIZE
# → my-app       latest    ~25 MB (runtime-deps) vs ~80 MB (aspnet)

# Проверка что приложение запущено от non-root
docker exec <container> id
# → uid=1654(app) gid=1654(app)
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

**Запуск с volume mount для горячей перезагрузки кода:**
```bash
docker run -d \
  -v $(pwd)/src:/app/src \
  -p 8080:8080 \
  -e DOTNET_WATCH_USE_POLLING_FILE_WATCHER=1 \
  my-app-dev:latest
```

Изменения в `src/` автоматически отслеживаются через polling (работает на macOS/Windows через Docker Desktop).

### Сценарий 4: Worker Service (фоновая задача)

Фоновый процесс без HTTP-сервера — используется `mcr.microsoft.com/dotnet/runtime` вместо `aspnet`.

```dockerfile
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS builder
ARG TARGETARCH
WORKDIR /src

COPY ["src/Worker/Worker.csproj", "src/Worker/"]
RUN --mount=type=cache,id=nuget,target=/root/.nuget/packages \
    dotnet restore "src/Worker/Worker.csproj" -a $TARGETARCH

COPY . .
RUN --mount=type=cache,id=nuget,target=/root/.nuget/packages \
    dotnet publish "src/Worker/Worker.csproj" \
    -c Release -o /app/publish -a $TARGETARCH --no-restore

# runtime (не aspnet) — нет ASP.NET Core, только .NET рантайм
FROM mcr.microsoft.com/dotnet/runtime:10.0-alpine
WORKDIR /app
ENV DOTNET_RUNNING_IN_CONTAINER=true \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    DOTNET_gcServer=0

COPY --from=builder /app/publish .

# Worker Service не слушает порты — используем random port для health endpoint
ENV ASPNETCORE_URLS=http://+:8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -sf http://localhost:8080/health || exit 1

USER app
ENTRYPOINT ["dotnet", "Worker.dll"]
```

**Важные отличия от ASP.NET Worker:**
- Если Worker использует `IHostedService` с HTTP-эндпоинтом (metrics/health), нужен `aspnet` образ.
- Если Worker — чистый `BackgroundService` без HTTP, достаточно `runtime` образа.
- `DOTNET_gcServer=0` рекомендуется для Worker, так как они обычно потребляют мало CPU.

### Сценарий 5: Тестовый этап в Dockerfile

Интеграция тестов в multi-stage сборку — тесты выполняются в контейнере, но финальный образ не содержит тестовый код.

```dockerfile
# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS builder
WORKDIR /src

# Копируем все .csproj для восстановления
COPY ["src/Api/Api.csproj", "src/Api/"]
COPY ["src/Core/Core.csproj", "src/Core/"]
COPY ["tests/Api.Tests/Api.Tests.csproj", "tests/Api.Tests/"]

RUN --mount=type=cache,id=nuget,target=/root/.nuget/packages \
    dotnet restore

COPY . .

# Этап тестирования (не попадает в финальный образ)
FROM builder AS tester
RUN --mount=type=cache,id=nuget,target=/root/.nuget/packages \
    dotnet test --no-restore --logger "trx;LogFilePath=/test-results/results.trx"

# Финальный образ — только приложение
FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine
WORKDIR /app
ENV DOTNET_RUNNING_IN_CONTAINER=true \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1
COPY --from=builder /src/src/Api/bin/Release/net10.0/publish/ .
USER app
EXPOSE 8080
ENTRYPOINT ["dotnet", "Api.dll"]
```

**Команда сборки с тестами:**
```bash
# Сборка с прохождением всех этапов (включая тесты)
docker build --target tester -t my-app:test .

# Если тесты провалились — финальный образ не будет создан
# Сборка только финального образа (пропуск тестов)
docker build -t my-app:latest .
```

### Сценарий 6: Windows-контейнер (NAS/многосервисное приложение)

Для приложений, требующих Windows-специфичных API (NTLM, Windows Auth, реестр). multi-stage сохраняется, но базовые образы — Windows-based.

```dockerfile
# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:10.0-nanoserver-ltsc2022 AS builder
WORKDIR /src
COPY . .
RUN dotnet publish "MyApp.csproj" -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0-nanoserver-ltsc2022
WORKDIR /app
COPY --from=builder /app/publish .
EXPOSE 8080
ENTRYPOINT ["dotnet", "MyApp.dll"]
```

**Важные ограничения Windows-контейнеров:**
- `--read-only` поддерживается начиная с Windows Server 2022.
- `--tmpfs` не поддерживается — используйте `--mount type=volume`.
- Пользователь по умолчанию — ContainerUser (не app).
- Chiseled-образы недоступны — только nanoserver или servercore.
- Размер образа значительно больше (~500 МБ vs ~80 МБ для Linux).

**Валидация:**
```bash
# Проверка что контейнер использует Windows isolation
docker inspect <container> --format '{{.HostConfig.Isolation}}'
# → windows

# Проверка что приложение слушает порт
docker exec <container> netstat -an | findstr 8080
# → TCP 0.0.0.0:8080 0.0.0.0:0 LISTENING
```

## Диагностика и мониторинг

### Sidecar для диагностики

В 2026 году стандартным подходом является использование sidecar-контейнера с `dotnet-monitor` для получения дампов и трейсов без изменения основного образа:
1.  **Сбор дампов:** `dotnet-monitor dump` — создает heap dump процесса для анализа утечек памяти.
2.  **Сбор трейсов:** `dotnet-monitor collect` — собирает CPU/EventType трейсы для анализа производительности.
3.  **Метрики:** `dotnet-monitor metrics` — экспорт метрик .NET через Prometheus endpoint.

Это позволяет держать основной образ максимально легким (Alpine/Chiseled), при этом имея полный инструментарий отладки рядом.

### Probe'ы для Kubernetes

.NET приложения имеют длительный cold start (особенно с JIT-компиляцией). Правильная настройка probe'ов критична для стабильности в Kubernetes:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: dotnet-app
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: app
          image: my-dotnet-app:latest
          ports:
            - containerPort: 8080
          # StartupProbe: защищает от ложных срабатываний Liveness при долгом старте
          # .NET cold start может занимать 10-30 секунд
          startupProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 5
            failureThreshold: 12  # 5 + 5*12 = 60 секунд на старт
          # LivenessProbe: перезапускает контейнер при зависании
          livenessProbe:
            httpGet:
              path: /health/live
              port: 8080
            periodSeconds: 15
            failureThreshold: 3
          # ReadinessProbe: убирает из балансировщика при недоступности
          readinessProbe:
            httpGet:
              path: /health/ready
              port: 8080
            periodSeconds: 10
            failureThreshold: 3
          resources:
            limits:
              memory: "256Mi"
              cpu: "500m"
            requests:
              memory: "128Mi"
              cpu: "250m"
```

**Ключевые моменты для .NET:**
- `startupProbe` с `failureThreshold: 12` дает 60 секунд на старт — критично для приложений с large object heap или множеством зависимостей.
- `livenessProbe` не должен зависеть от внешних сервисов (БД, Redis) — иначе контейнер будет перезапускаться при недоступности БД.
- `readinessProbe` может проверять зависимость от БД — это корректно убирает контейнер из балансировщика.

### Наблюдаемость (Observability)

Интеграция OpenTelemetry является обязательной:
*   Используйте переменные окружения `OTEL_EXPORTER_OTLP_ENDPOINT` для настройки экспорта метрик и трейсов из контейнера.
*   .NET 10+ нативно поддерживает многие протоколы OTLP без дополнительных NuGet пакетов для базовых метрик.
*   Метрики .NET доступны через `dotnet-counters` — инструмент для мониторинга GC, ThreadPool, исключений в реальном времени.

## Типичные ошибки и их решение

### Ошибка 1: OOMKilled при резком скачке памяти

**Причина:** .NET GC автоматически расширяет кучу при росте нагрузки, но не успевает освободить память до лимита cgroups.

```bash
# Диагностика: проверить лимиты контейнера
kubectl describe pod <pod> | grep -A5 "Limits\|Last State"
# → Limits: memory: 256Mi
# → Last State: Terminated (reason: OOMKilled)

# Решение 1: установить явный лимит кучи (70% от памяти)
ENV DOTNET_GCHeapHardLimit=0x7000000  # 112 МБ

# Решение 2: увеличить лимит памяти
resources:
  limits:
    memory: "512Mi"
```

### Ошибка 2: HealthCheck не работает (HealthCheckClient.dll не найден)

**Причина:** Ссылка на несуществующий `HealthCheckClient.dll` — этот файл не входит в стандартные образы .NET.

```bash
# Симптом:
docker inspect <container> --format '{{.State.Health.Status}}'
# → starting (никогда не перейдет в healthy)

# Решение: использовать curl или HTTP endpoint
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -sf http://localhost:8080/health || exit 1

# Или без curl (требует HTTP endpoint в приложении):
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD dotnet dev-certs https --trust 2>/dev/null; \
  wget -q --spider http://localhost:8080/health || exit 1
```

### Ошибка 3: Hot Reload не видит изменения кода

**Причина:** Docker Desktop на macOS/Windows не мониторит файловые изменения через overlay filesystem.

```bash
# Симпptom: dotnet watch не реагирует на изменения в src/

# Решение: volume mount с polling
docker run -d \
  -v $(pwd)/src:/app/src \
  -e DOTNET_WATCH_USE_POLLING_FILE_WATCHER=1 \
  -e DOTNET_SUPPRESS_STATUS_MESSAGES=true \
  -p 8080:8080 \
  my-app-dev:latest

# Дополнительно: увеличить интервал опроса
ENV DOTNET_WATCH_POLLING_INTERVAL=2000  # 2 секунды
```

### Ошибка 4: NuGet пакеты не кэшируются (каждая сборка скачивает заново)

**Причина:** Нет `--mount=type=cache` для `/root/.nuget/packages`.

```bash
# Симптом: dotnet restore занимает 60+ секунд на каждой сборке

# Решение: добавить cache mount
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet restore

# Проверка что кэш работает:
docker buildx du --filter type=cache
# → 전체 캐시 크기 중 nuget 캐시 포함
```

### Ошибка 5: Контейнер запущен от root (не от app)

**Причина:** Нет инструкции `USER` в Dockerfile или образ не содержит пользователя `app`.

```bash
# Диагностика:
docker exec <container> id
# → uid=0(root) gid=0(root)

# Решение: добавить в конец Dockerfile
USER app

# Проверка что пользователь существует:
docker run --rm my-app:latest id
# → uid=1654(app) gid=1654(app)
```

### Ошибка 6: Server GC потребляет слишком много памяти

**Причина:** Server GC выделяет отдельный поток на каждое ядро — при 4+ ядрах это может быть 200+ МБ только на GC.

```bash
# Диагностика: проверить потребление GC
docker exec <container> dotnet-counters monitor \
  --process-id 1 \
  --counters System.Runtime

# Решение: отключить Server GC для малых контейнеров
ENV DOTNET_gcServer=0

# Или установить лимит потоков GC
ENV DOTNET_GCHeapHardLimitPercent=50
```

### Ошибка 7: Native AOT не компилируется (clang не найден)

**Причина:** В образе SDK отсутствуют зависимости для нативной компиляции.

```bash
# Симптом:
# error : The compiler 'clang' was not found on the PATH

# Решение: установить зависимости в builder stage
FROM mcr.microsoft.com/dotnet/sdk:10.0 AS builder
RUN apt-get update && apt-get install -y clang zlib1g-dev

# Для Alpine:
RUN apk add clang zlib-dev
```

### Ошибка 8: Chiseled образ не запускается (shell not found)

**Причина:** Chiseled-образы не содержат shell — невозможно войти через `docker exec`.

```bash
# Симптом:
docker exec -it <container> /bin/sh
# → exec: "/bin/sh": executable file not found in $PATH

# Решение: использовать debug-версию для отладки
FROM mcr.microsoft.com/dotnet/nightly/runtime-deps:10.0-jammy-chiseled:debug

# Или собрать отдельный образ для отладки
FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine
```

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Multi-stage** | SDK для сборки, aspnet/runtime для запуска | Уменьшает размер образа на 70-80% |
| **Layer caching** | Копировать .csproj до исходного кода | Ускоряет повторную сборку в 5-10 раз |
| **Cache mount** | `--mount=type=cache,target=/root/.nuget/packages` | Пакеты не скачиваются заново в CI/CD |
| **Non-root** | `USER app` в конце Dockerfile | Предотвращение Container Escape |
| **Read-only** | `--read-only` + tmpfs | Блокировка записи в системные директории |
| **Pinning** | `FROM image@sha256:...` | Гарантия воспроизводимости |
| **Globalization** | `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` | Уменьшает образ на 20-50 МБ |
| **GC tuning** | `DOTNET_gcServer=0` для <2 ядер | Снижение потребления памяти |
| **Health endpoint** | `/health` endpoint в приложении | Проверка состояния контейнера |
| **StartupProbe** | `failureThreshold: 12` (60 сек) | Защита от ложных срабатываний |
| **AOT vs R2R** | Native AOT для максимальной скорости, R2R для совместимости | Выбор зависит от требований |
| **Chiseled** | Для production, Alpine для dev | Максимальная безопасность |

### Порядок инструкций в безопасном Dockerfile

```dockerfile
# 1. Версия синтаксиса
# syntax=docker/dockerfile:1

# 2. Базовый образ SDK с pinning
FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine@sha256:... AS builder

# 3. Переменные сборки
ARG TARGETARCH
ENV DOTNET_CLI_TELEMETRY_OPTOUT=1

# 4. Копирование .csproj (layer caching)
COPY ["src/Api/Api.csproj", "src/Api/"]

# 5. Восстановление пакетов с cache mount
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet restore -a $TARGETARCH

# 6. Копирование исходного кода
COPY . .

# 7. Сборка и публикация
RUN --mount=type=cache,target=/root/.nuget/packages \
    dotnet publish -c Release -o /app/publish -a $TARGETARCH --no-restore

# 8. Финальный образ (минимальный)
FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine

# 9. Переменные рантайма
ENV DOTNET_RUNNING_IN_CONTAINER=true \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 \
    ASPNETCORE_URLS=http://+:8080

# 10. Копирование артефактов
WORKDIR /app
COPY --from=builder /app/publish .

# 11. Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -sf http://localhost:8080/health || exit 1

# 12. Non-root пользователь
USER app

# 13. Порты и точка входа
EXPOSE 8080
ENTRYPOINT ["dotnet", "Api.dll"]
```

### Чек-лист перед деплоем

**Dockerfile:**
- [ ] Инструкция `USER app` в конце (не root)
- [ ] Multi-stage: финальная стадия не содержит SDK
- [ ] Базовый образ зафиксирован по SHA256 дайджесту
- [ ] .csproj копируются до исходного кода (layer caching)
- [ ] `--mount=type=cache` для NuGet packages
- [ ] `DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1` установлен
- [ ] HEALTHCHECK настроен и работает
- [ ] Нет секретов в ENV или ARG

**Запуск контейнера:**
- [ ] `--read-only` с tmpfs для временных данных
- [ ] `--cap-drop=ALL` + только необходимые capabilities
- [ ] `--security-opt=no-new-privileges`
- [ ] Привязка портов к localhost (если не нужен внешний доступ)
- [ ] Лимиты памяти установлены (resources.limits.memory)

**Kubernetes:**
- [ ] StartupProbe с достаточным failureThreshold (60+ сек)
- [ ] LivenessProbe не зависит от внешних сервисов
- [ ] ReadinessProbe проверяет зависимость от БД
- [ ] Лимиты памяти и CPU установлены
- [ ] DOTNET_GCHeapHardLimit настроен (70% от лимита)

## Дополнительная информация

### Смотрите также

- **[Оптимизация сборки Docker-образов](./build_optimization.md)** — кэширование, слои и Multi-stage.
- **[Безопасность в Dockerfile](./security.md)** — аудит, сканирование CVE и работа с пользователями.
- **[Проблема зомби-процессов (PID 1)](./container_execution.md)** — важно для приложений, запускающих дочерние процессы.
