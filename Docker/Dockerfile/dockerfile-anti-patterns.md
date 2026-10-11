# Антипаттерны Dockerfile

**Актуально для:** Docker 27+ / BuildKit 0.13+ (Dockerfile 1.11). Каталог evergreen; версионные ограничения отмечены отдельно.

## Определения

**Антипаттерн Dockerfile** — распространённая, но ошибочная практика написания Dockerfile, которая выглядит допустимой, но приводит к увеличению размера образа, дырам в безопасности, нестабильным сборкам или проблемам в runtime. В отличие от синтаксических ошибок, антипаттерн успешно собирается, поэтому обнаруживается только в production или на code review.

**Blast Radius (радиус поражения)** — область воздействия антипаттерна. Антипаттерн в базовом образе (например, `FROM latest`) имеет больший blast radius, чем в одноразовом builder-стейдже, потому что затрагивает все downstream-образы и все среды.

**Technical Debt (технический долг)** — накопленная стоимость обходных путей. Антипаттерны Dockerfile — это форма технического долга: каждый «временный» `RUN apt-get install` без очистки или `COPY . .` без `.dockerignore` увеличивает время сборки и поверхность атаки.

**Shift-Left** — принцип раннего обнаружения. Антипаттерны дешевле всего обнаруживать на этапе lint (Hadolint, BuildKit Checks) — до сборки образа, а не после push в registry.

## Основные концепции

### Почему антипаттерны важны

Dockerfile — это единственный артефакт, описывающий, как строится production-образ. Ошибка в нём воспроизводится в каждой среде (dev, staging, prod) и в каждом релизе. Антипаттерны делятся на пять категорий по домену воздействия:

| Категория | Домен воздействия | Типичный симптом |
| :--- | :--- | :--- |
| **Размер** | Размер образа, время pull | Образ 2 ГБ вместо 200 МБ |
| **Безопасность** | Поверхность атаки, секреты | CVE, утечка токена в слое |
| **Сборка** | Скорость, воспроизводимость | Cache miss, недетерминированный билд |
| **Поддерживаемость** | Читаемость, drift | Непонятно, что внутри образа |
| **Runtime** | Сигналы, PID 1, graceful shutdown | Exit 137, zombie-процессы |

### Механизм: почему антипаттерн «работает»

Антипаттерн не ломает сборку — он собирается, но с скрытой стоимостью. Пример: `RUN apt-get update && apt-get install -y curl` без очистки собирается успешно, но слой содержит кеш apt (`/var/lib/apt/lists/*`), который никогда не используется в runtime и только увеличивает образ. Проблема проявляется при `docker push` (долго) и при сканировании (лишние CVE из кеша пакетов).

### Связь с другими антипаттернами в базе

Антипаттерны Dockerfile — частный случай более широких каталогов антипаттернов в базе знаний:

- **[Антипаттерны управления секретами](../../Vault/common_antipatterns.md)** — Secret Sprawl, Secret Zero, статические секреты (пересекаются с антипаттерном «секреты в слоях»).
- **[Антипаттерны Feature Toggles](../../CI-CD/Testing/feature_toggles/antipatterns.md)** — combinatorial explosion, флаги как замена авторизации.
- **[vCluster: антипаттерны](../../Kubernetes/ToolsUtilities/vcluster/vcluster_antipatterns.md)** — configuration drift, blast radius в виртуальных кластерах.
- **[Надёжность CI/CD: антипаттерны](../../CI-CD/Core_Concepts/reliability_patterns.md)** — антипаттерны пайплайнов, в которые встроен Dockerfile.

## Практические сценарии

Каталог антипаттернов по категориям. Для каждого: антипаттерн, почему плохо, исправление. Подробное объяснение механизма — в связанном файле.

### Размер образа

**1. `FROM latest` или незакреплённый базовый образ**

```dockerfile
# Антипаттерн
FROM node:latest
```

Почему плохо: сборка недетерминирована — сегодня и завтра `node:latest` указывают на разные образы, что ломает воспроизводимость и затрудняет rollback. Исправление — закрепить по тегу или по дайджесту:

```dockerfile
# Исправление: тег (читаемо) или дайджест (детерминировано)
FROM node:22-slim
# FROM node:22-slim@sha256:abc123...
```

Подробнее: [Выбор базового образа и метаданные](Instructions/base_image_and_metadata.md), [Воспроизводимые сборки](Instructions/build_time_commands.md).

**2. Отсутствие multi-stage сборки**

```dockerfile
# Антипаттерн: toolchain и исходники остаются в финальном образе
FROM golang:1.24
WORKDIR /app
COPY . .
RUN go build -o myapp .
CMD ["./myapp"]
```

Почему плохо: в production-образ попадают компилятор Go (~800 МБ), исходники и кеш сборки. Исправление — multi-stage: собрать в builder, скопировать только бинарник в runtime-образ. Подробнее: [Оптимизация сборки](Docker_best_practices/build_optimization.md).

**3. `COPY . .` без `.dockerignore`**

```dockerfile
# Антипаттерн
COPY . .
```

Почему плохо: в контекст сборки попадают `.git`, `node_modules`, логи, `.env` — это увеличивает контекст (медленная передача демону) и может утечить секреты в слой. Исправление — `.dockerignore` с явным исключением. Подробнее: [Контекст сборки и .dockerignore](dockerfile_build_context.md).

**4. Очистка пакетов в отдельном слое**

```dockerfile
# Антипаттерн: кеш apt остаётся в слое №1 навсегда
RUN apt-get update
RUN apt-get install -y curl
RUN rm -rf /var/lib/apt/lists/*
```

Почему плохо: каждый `RUN` — отдельный слой; кеш apt записан в слой №1 и не удаляется последующими слоями (слои иммутабельны). Исправление — объединить в один `RUN` через `&&`:

```dockerfile
# Исправление
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
```

Подробнее: [Оптимизация сборки](Docker_best_practices/build_optimization.md), [Alpine/musl](dockerfile_alpine_linux.md).

### Безопасность

**5. Запуск от root**

```dockerfile
# Антипаттерн: процесс в контейнере — root
FROM python:3.12-slim
COPY . .
CMD ["python", "app.py"]
```

Почему плохо: при побеге из контейнера злоумышленник получает root на хосте (если нет user namespace remap). Исправление — создать пользователя и переключиться через `USER`. Подробнее: [Безопасность образов](Docker_best_practices/security.md), [Исполнение контейнера](Docker_best_practices/container_execution.md).

**6. Секреты в слоях**

```dockerfile
# Антипаттерн: токен навсегда записан в слой
RUN echo "REGISTRY_TOKEN=abc123" > /etc/token
```

Почему плохо: секрет доступен через `docker history --no-trunc` и в любом слое образа, даже если удалён в последующем `RUN`. Исправление — BuildKit secrets: `RUN --mount=type=secret,id=token ...`. Подробнее: [BuildKit: монтирования и секреты](dockerfile_buildkit.md), [Безопасность](Docker_best_practices/security.md).

**7. `ADD` для удалённых URL**

```dockerfile
# Антипаттерн
ADD https://example.com/app.tar.gz /opt/
```

Почему плохо: `ADD` для URL не использует кеш, недетерминирован (содержимое URL меняется), и автоматически распаковывает архивы — поведение неочевидно. Исправление — `RUN curl` для URL, `COPY` для локальных файлов. Подробнее: [COPY и ADD](Instructions/copying_files.md).

**8. `sudo` внутри контейнера**

```dockerfile
# Антипаттерн
RUN apt-get install -y sudo
USER app
CMD ["sudo", "python", "app.py"]
```

Почему плохо: `sudo` в контейнере не нужен — для смены пользователя есть директива `USER`, а для привилегированных операций — capabilities. `sudo` только увеличивает поверхность атаки. Подробнее: [Безопасность](Docker_best_practices/security.md).

### Сборка

**9. Неиспользование BuildKit**

```bash
# Антипаттерн: legacy builder
DOCKER_BUILDKIT=0 docker build .
```

Почему плохо: legacy builder не поддерживает Heredoc, `--mount`, `COPY --link`, `check=error` и параллельные стадии — теряются производительность и безопасность (secrets). Исправление — BuildKit по умолчанию (Docker 23+) или `docker buildx build`. Подробнее: [BuildKit](dockerfile_buildkit.md), [Buildx](docker_buildx.md).

**10. Нарушение порядка кеширования**

```dockerfile
# Антипаттерн: часто меняющаяся инструкция раньше редко меняющейся
COPY . .
RUN apt-get update && apt-get install -y curl
```

Почему плохо: любое изменение исходников инвалидирует кеш установки пакетов — каждая сборка заново скачивает пакеты. Исправление — редко меняющиеся инструкции (`apt-get install`) раньше часто меняющихся (`COPY . .`). Подробнее: [Кеширование слоёв](Docker_best_practices/build_optimization.md).

**11. Отсутствие `ARG`/`ENV` — захардкоженные значения**

```dockerfile
# Антипаттерн
RUN curl -o /app https://internal.example.com/app-v1.2.3
```

Почему плохо: версия и URL захардкожены; обновление требует правки Dockerfile. Исправление — `ARG VERSION=1.2.3` для build-time и `ENV` для runtime-конфигурации. Подробнее: [Переменные окружения и ARG](Instructions/environment_variables.md).

### Поддерживаемость

**12. Отсутствие `LABEL` и метаданных**

```dockerfile
# Антипаттерн: образ без автора, версии, источника
FROM alpine:3.20
COPY . .
```

Почему плохо: невозможно определить владельца, версию и происхождение образа — критично для аудита и compliance. Исправление — OCI-лейблы (`org.opencontainers.image.*`). Подробнее: [Базовый образ и метаданные](Instructions/base_image_and_metadata.md).

**13. Монолитный Dockerfile для всех сервисов**

```dockerfile
# Антипаттерн: один Dockerfile собирает frontend, backend и worker
COPY frontend/ /frontend/
COPY backend/ /backend/
COPY worker/ /worker/
```

Почему плохо: любое изменение любого сервиса пересобирает весь образ; невозможно оптимизировать контекст под сервис. Исправление — отдельный Dockerfile на сервис (в монорепо — path-based контексты через Buildx/Bake). Подробнее: [Сборка в монорепозиториях](../../CI-CD/Build_Systems/monorepo_build_systems.md), [Bake](docker-bake.md).

### Runtime

**14. Shell-форма `CMD`/`ENTRYPOINT`**

```dockerfile
# Антипаттерн: CMD в shell-форме
CMD python app.py
```

Почему плохо: shell-форма запускает процесс через `/bin/sh -c`, поэтому PID 1 — shell, а не приложение; сигналы (`SIGTERM`) не доставляются приложению, graceful shutdown не работает, контейнер завершается по `SIGKILL` (Exit 137). Исправление — exec-форма: `CMD ["python", "app.py"]`. Подробнее: [Исполнение контейнера](Docker_best_practices/container_execution.md), [PID 1 и Tini](init_process_tini.md).

**15. Отсутствие init-процесса (PID 1)**

```dockerfile
# Антипаттерн: приложение как PID 1 без reap zombie
ENTRYPOINT ["./myapp"]
```

Почему плохо: если приложение не реализует reap zombie-процессов (ожидание потомков), zombie-процессы накапливаются. Исправление — `tini`/`dumb-init` как entrypoint или `docker run --init`. Подробнее: [Tini и init-процесс](init_process_tini.md).

**16. Отсутствие `HEALTHCHECK` и `STOPSIGNAL`**

```dockerfile
# Антипаттерн: нет ни HEALTHCHECK, ни STOPSIGNAL
FROM nginx:alpine
COPY . /usr/share/nginx/html
```

Почему плохо: оркестратор не знает, живо ли приложение (нет HEALTHCHECK), и при остановке посылает `SIGKILL` вместо `SIGTERM` (нет STOPSIGNAL для приложений с нестандартным сигналом). Подробнее: [Сигналы здоровья](Instructions/health_signals.md), [STOPSIGNAL](Docker_best_practices/container_execution.md).

**17. Хранение данных в writable layer**

```dockerfile
# Антипаттерн: данные пишутся в слой контейнера
RUN mkdir /data
# приложение пишет логи и БД в /data
```

Почему плохо: данные теряются при удалении контейнера, растут размер слоя, не шарятся между контейнерами. Исправление — `VOLUME` или bind-mount/volume в runtime. Подробнее: [Хранение данных](Instructions/data_storage.md).

## Разрешение проблем

### Как обнаружить антипаттерн

| Инструмент | Что находит | Команда |
| :--- | :--- | :--- |
| **Hadolint** | Статические правила (DL3000–DL4000) | `hadolint Dockerfile` |
| **BuildKit Checks** | Встроенные проверки (`check=error=true`) | `docker build --check .` |
| **Dive** | Слои, дублирование, размер | `dive myimage:latest` |
| **`docker history`** | Что попало в каждый слой | `docker history --no-trunc myimage:latest` |
| **Docker Scout / Trivy** | CVE, секреты, misconfiguration | `docker scout cves myimage:latest` |

Подробнее: [Инструменты оптимизации Dockerfile](dockerfile_optimization_tools.md), [Тестирование контейнеров и образов](../../CI-CD/Testing/container_testing.md).

### Типичные ошибки

| Симптом | Антипаттерн-причина | Решение |
| :--- | :--- | :--- |
| Образ > 1 ГБ для простого приложения | Нет multi-stage, `FROM latest` | Multi-stage, distroless/Alpine |
| `docker history` показывает секрет | Секрет в `RUN` | BuildKit `--mount=type=secret` |
| Контейнер не останавливается graceful | Shell-форма `CMD` | Exec-форма, `STOPSIGNAL` |
| Zombie-процессы растут | Нет init (PID 1) | `tini`/`dumb-init`/`--init` |
| Сборка медленная, кеш не попадает | Порядок инструкций, `COPY . .` | Кеширующий порядок, `.dockerignore` |

## Best Practices

Чек-лист перед коммитом Dockerfile:

- [ ] Базовый образ закреплён (тег или дайджест), не `latest`
- [ ] Multi-stage: в финальном образе только runtime-артефакты
- [ ] `.dockerignore` исключает `.git`, секреты, артефакты сборки
- [ ] Очистка пакетов (`rm -rf /var/lib/apt/lists/*`) в том же `RUN`
- [ ] `USER` nonroot; нет `sudo`
- [ ] Секреты — через BuildKit `--mount=type=secret`, не через `RUN`
- [ ] `CMD`/`ENTRYPOINT` в exec-форме
- [ ] Init-процесс (tini/dumb-init) для приложений с потомками
- [ ] `HEALTHCHECK` и `STOPSIGNAL` при необходимости
- [ ] OCI-лейблы (`org.opencontainers.image.*`)
- [ ] `ARG`/`ENV` вместо захардкоженных значений
- [ ] BuildKit включён (Docker 23+ по умолчанию)

## Дополнительная информация

- **[Оптимизация сборки](Docker_best_practices/build_optimization.md)** — кеширование, multi-stage, distroless (детали антипаттернов размера и сборки).
- **[Безопасность образов](Docker_best_practices/security.md)** — non-root, capabilities, supply chain (детали антипаттернов безопасности).
- **[Исполнение контейнера](Docker_best_practices/container_execution.md)** — PID 1, сигналы, graceful shutdown (детали runtime-антипаттернов).
- **[Инструменты оптимизации Dockerfile](dockerfile_optimization_tools.md)** — Hadolint, Dive, Trivy, Scout (автоматическое обнаружение).
- **[Тестирование контейнеров и образов](../../CI-CD/Testing/container_testing.md)** — lint → build → scan → functional test → quality gate.
- **[Антипаттерны управления секретами](../../Vault/common_antipatterns.md)** — смежный каталог для секретов.
