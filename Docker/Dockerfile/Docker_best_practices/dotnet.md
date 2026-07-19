# Dockerfile: Лучшие практики для .NET

> **Надежность: 10** (Актуализировано согласно стандартам 2026 года, .NET 9/10)

## Определения

- **SDK (Software Development Kit):** Полный набор инструментов (компиляторы, библиотеки, CLI) для сборки приложения. Используется только на этапе сборки.
- **Runtime:** Минимальная среда для запуска байт-кода .NET. Различают `aspnet` (для веб-приложений) и `runtime` (для консольных задач).
- **Native AOT (Ahead-of-Time):** Режим компиляции приложения в нативный код под конкретную ОС и архитектуру. Исключает необходимость в JIT и сокращает потребление памяти и размер образа.
- **NuGet:** Официальный менеджер пакетов для .NET.
- **Chiseled Images:** Ультра-минималистичные образы (от Canonical), не содержащие shell и пакетных менеджеров, оптимизированные для безопасности .NET-приложений.

## Базовые концепции

### Многоэтапная сборка (Multi-stage)

Для .NET разделение SDK и Runtime является критическим.
1. **Этап сборки (Build):** Образ `mcr.microsoft.com/dotnet/sdk`.
2. **Этап выполнения (Runtime):** Образ `mcr.microsoft.com/dotnet/aspnet` или `mcr.microsoft.com/dotnet/runtime`.
Это позволяет уменьшить размер образа с ~800 МБ до ~200 МБ (или до ~30 МБ при использовании Native AOT).

### Кэширование NuGet и BuildKit

Использование `--mount=type=cache` позволяет сохранять кэш пакетов между сборками, даже если файл проекта `.csproj` изменился. Это существенно ускоряет `dotnet restore`.

### Кросс-компиляция и архитектуры

Современный подход требует сборки под разные архитектуры (AMD64, ARM64). Рекомендуется использовать встроенные переменные `TARGETARCH` для корректного выбора платформы при публикации.

### Безопасность и пользователь по умолчанию

Начиная с .NET 8, официальные образы включают непривилегированного пользователя `app` (UID 1654) и слушают порт `8080` вместо `80`. Использование этого пользователя обязательно для production.

## Практические сценарии

### Сценарий 1: Стандартное ASP.NET Core приложение (Оптимальное кэширование)

```dockerfile
# syntax=docker/dockerfile:1
# --- Этап 1: Сборка (builder) ---
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:9.0-alpine AS builder
ARG TARGETARCH
WORKDIR /src

# Копируем файлы проекта для кэширования зависимостей
COPY ["MyProject/MyProject.csproj", "MyProject/"]
# Используем кэш BuildKit для NuGet
RUN --mount=type=cache,id=nuget,target=/root/.nuget/packages \
    dotnet restore "MyProject/MyProject.csproj" -a $TARGETARCH

# Копируем остальной код и публикуем
COPY . .
RUN --mount=type=cache,id=nuget,target=/root/.nuget/packages \
    dotnet publish "MyProject/MyProject.csproj" \
    -c Release \
    -o /app/publish \
    -a $TARGETARCH \
    --no-restore

# --- Этап 2: Финальный образ ---
FROM mcr.microsoft.com/dotnet/aspnet:9.0-alpine
WORKDIR /app
COPY --from=builder /app/publish .

# Использование встроенного пользователя "app"
USER app
EXPOSE 8080
ENTRYPOINT ["dotnet", "MyProject.dll"]
```

### Сценарий 2: Использование Native AOT (Максимальная производительность)

Native AOT превращает .NET приложение в один бинарный файл, не требующий рантайма.

```dockerfile
# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/dotnet/sdk:9.0-alpine AS builder
# Для AOT требуются инструменты компиляции C++
RUN apk add --no-cache clang build-base zlib-dev
WORKDIR /src
COPY . .

# Публикация в нативный код
RUN dotnet publish "MyProject.csproj" \
    -c Release \
    -r linux-musl-x64 \
    -o /app/publish \
    /p:PublishAot=true \
    /p:StripSymbols=true

# --- Финальный этап (scratch или минимальный alpine) ---
FROM alpine:3.24
RUN apk add --no-cache libgcc
WORKDIR /app
COPY --from=builder /app/publish/MyProject .
USER 10001
ENTRYPOINT ["./MyProject"]
```

### Сценарий 3: Chiseled-образы для безопасности

```dockerfile
FROM mcr.microsoft.com/dotnet/sdk:9.0 AS builder
# ... (сборка проекта) ...

FROM mcr.microsoft.com/dotnet/nightly/runtime-deps:9.0-jammy-chiseled
WORKDIR /app
COPY --from=builder /app/publish .
USER app
ENTRYPOINT ["./MyProject"]
```

## Дополнительная информация

### Смотрите также

- [Оптимизация сборки Docker-образов](./build_optimization.md) — общие принципы кэширования.
- [Безопасность в Dockerfile](./security.md) — детали работы с пользователями.
- [Контейнерные переменные .NET](https://learn.microsoft.com/en-us/dotnet/core/tools/dotnet-environment-variables) — настройка логирования и производительности через ENV.
- [Docker Buildx: Мультиплатформенная сборка](../docker_buildx.md)
