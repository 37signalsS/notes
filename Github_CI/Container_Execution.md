# GitHub Actions: Контейнеры в задачах (Job Containers и Services)

**Актуально для:** GitHub Actions, октябрь 2026 (job containers и service containers; ключ `container:` работает только на Linux-раннерах)

Запуск задачи внутри собственного Docker-образа и подключение инфраструктурных сервисов (БД, брокеры, кеши) — стандартные продакшен-паттерны. Тематический блок охватывает ключ `container` на уровне задачи, приватные реестры, тома и service containers.

## Определения

- **Job Container**: Docker-контейнер, в котором выполняются все шаги задачи (`container:` на уровне job). Раннер запускает контейнер и прокидывает внутрь workspace и переменные окружения.
- **Service Container**: Инфраструктурный контейнер-компаньон (sidecar), поднимаемый рядом с задачей (`services:`): PostgreSQL, Redis, Kafka и т.п. Живёт столько же, сколько задача.
- **Registry Credentials**: Учётные данные для pull приватного образа (`credentials.username/password`) — задаются секретами, никогда не хардкодятся.
- **Health Check**: Механика готовности сервис-контейнера: раннер ждёт статуса `healthy` (флаги `--health-cmd/--health-interval` в `options`) перед стартом шагов.
- **Named Volume**: Именованный том Docker; единственный вид томов, поддерживаемый в GitHub-hosted средах для `volumes:`.

## Основные концепции

### Ключ `container` на уровне задачи

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    container:
      image: node:24-bookworm
      credentials:
        username: ${{ secrets.REG_USER }}
        password: ${{ secrets.REG_TOKEN }}
      env:
        NODE_ENV: test
      volumes:
        - my-cache:/home/node/.npm     # именованный том
      options: --cpus 2 --memory 4g
      ports:
        - 8080:80
```

- Контейнерные операции разрешены **только на Linux**-раннерах — ограничение зашито в код раннера: на `windows-*`/`macos-*` задача с `container:`/`services:` падает с ошибкой `Container operations are only supported on Linux runners`. На self-hosted Windows есть лишь экспериментальная поддержка за отдельным флагом — не для продакшена. Матрицы с контейнерами строят только вокруг Linux.
- Раннер монтирует workspace в `/__w/<repo>/<repo>`, переопределяет `ENTRYPOINT` образа своим процессом и задаёт рабочую директорию `__w`.
- Docker CLI/Docker daemon **внутри** job container недоступны (socket не пробрасывается): собирать или запускать образы из такого шага нельзя — сборка делается обычными шагами без `container`, либо выносится на self-hosted с явным монтированием socket (осознанное решение по безопасности).
- `options:` принимает любые флаги `docker create` (ресурсы, healthchecks); `volumes:` — только анонимные (`/path`) и именные (`name:/path`) тома; bind-mount хоста невозможен, поскольку путь хоста hosted-раннера не контролируется пользователем.
- Образ пинуйте по digest или конкретной минорной версии — `latest` делает сборку невоспроизводимой (правило пиннинга — в [Готовых действиях](./Marketplace_Actions.md)).
- Архитектура образа должна совпадать с архитектурой раннера: на `arm64`-раннерах (`ubuntu-*-arm`) нужен arm64-образ (или multi-arch). Автоматической эмуляции нет — при несовпадении pull падает с `no matching manifest for linux/<arch> in the manifest list entries`. Для собственных CI-образов собирайте multi-arch (`docker buildx build --platform linux/amd64,linux/arm64`).
- Отдельная категория hosted-раннеров — `ubuntu-slim`: задача исполняется напрямую в unprivileged-контейнере (без `container:`), Docker-in-Docker и монтирование файловых систем недоступны. Для контейнерных сборок не предназначен; характеристики и ограничения разобраны в [Среды выполнения и ограничения](./Environment_Limitations.md).
- Внутри job container `$GITHUB_WORKSPACE` содержит корректный путь (`/__w/...`), тогда как контекст `${{ github.workspace }}` из-за открытого бага раннера ([actions/runner#2058](https://github.com/actions/runner/issues/2058)) может вернуть путь хоста, отсутствующий в контейнере. В шагах контейнерных задач опирайтесь на переменную окружения, а не на контекст.

### Service containers и ожидание готовности

```yaml
    services:
      postgres:
        image: postgres:18
        env:
          POSTGRES_PASSWORD: test
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 10
```

- Без health-check раннер считает сервис готовым сразу после старта процесса — приложение упадёт на первом соединении («connection refused»), хотя контейнер жив. Health-check обязателен для любых реальных БД.
- Адресация сервиса зависит от того, где исполняется задача:
  - Задача **в job container**: сервис доступен по hostname = имени сервиса (`postgres:5432`) — раннер объединяет контейнеры одной сетью;
  - Задача **на раннере напрямую**: сервис доступен на `localhost:<mapped-port>` из блока `ports`.
- Сервисы поддерживают те же `credentials`, `env`, `volumes`, `options`; образом может быть выражение с матрицей (`image: ${{ matrix.db }}`).

### Сравнение подходов исполнения

| Критерий | Шаги на раннере | Job container | Self-hosted + свой образ |
| :--- | :--- | :--- | :--- |
| Окружение | Предустановленный софт образа | Полный контроль версий | Полный контроль + своё железо |
| Доступ к Docker | Да (docker.sock) | Нет | Настраивается вручную |
| Windows/macOS | Да | Только Linux | По мощности парка |
| Воспроизводимость | Зависит от образа раннера | Высокая (пин образа) | Максимальная |

Выбор: если проект уже имеет devcontainer/Dockerfile окружения — job container даёт CI-среду, идентичную локальной разработке.

### Self-hosted: подмена контейнерного рантайма (container hooks)

Self-hosted Linux-раннер умеет делегировать создание job/service контейнеров внешнему скрипту — это позволяет заменить Docker на Podman, containerd/CRI-O или Kubernetes-под без изменения воркфлоу. Механизм (public preview, root на раннере не обязателен) управляется переменными раннера, которые задаются в `.env` каталога раннера или в окружении ОС:

```bash
ACTIONS_RUNNER_CONTAINER_HOOKS=/opt/runner-hooks/index.js   # обработчик контейнерных задач (абсолютный путь)
ACTIONS_RUNNER_REQUIRE_JOB_CONTAINER=true                   # каждая задача обязана исполняться в контейнере
```

- Скрипту передаются четыре события — `prepare_job`, `cleanup_job`, `run_container_step`, `run_script_step`; эталонные реализации для Docker и Kubernetes — в [actions/runner-container-hooks](https://github.com/actions/runner-container-hooks).
- `prepare_job` получает описание job container и сервисов (`image`, `createOptions` из `options:`, `userMountVolumes`, `credentials`, системные монтирования `_work → /__w`, `_tool → /__w/_tool`), обязан поднять контейнеры, дождаться healthcheck'ов и вернуть раннеру состояние сети и флаг `isAlpine` — без этого запуск шагов не начнётся.
- Вызов скрипта синхронный и блокирует задачу; таймаута у раннера нет — закладывайте его в сам скрипт.
- `ACTIONS_RUNNER_REQUIRE_JOB_CONTAINER=true` делает `container:` обязательным: задача без job container завершится ошибкой.

---

## Практические сценарии

### Сценарий 1: Задача в приватном образе организации

**Предварительные требования**: PAT или App-токен с правом `read:packages` лежит в секрете `GHCR_TOKEN`.

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
    container:
      image: ghcr.io/acme/ci-base:1.9@sha256:e3b0c44...   # digest-пин
      credentials:
        username: ${{ github.actor }}
        password: ${{ secrets.GHCR_TOKEN }}
    steps:
      - uses: actions/checkout@v7          # git есть в базовом образе либо ставится ниже
      - run: make ci                        # → все инструменты уже в образе, setup-шагов нет
```

- Каждый параметр: `username: github.actor` + токен — каноническая аутентификация GHCR из воркфлоу; digest исключает дрейф базового образа между релизами.
- **Валидация**: первая строка лога задачи показывает `Pull down action image 'ghcr.io/acme/ci-base:1.9...'`; внутри шага `cat /etc/os-release && which make` подтверждает содержимое.
- Экономический эффект: тяжёлые установки (toolchains) переносятся из каждого прогона в сборку базового образа — сокращение времени до результата (TTR) без кешей.

### Сценарий 2: Интеграционные тесты с PostgreSQL и Redis

```yaml
jobs:
  integration:
    runs-on: ubuntu-latest
    services:
      db:
        image: postgres:18
        env:
          POSTGRES_PASSWORD: ci
          POSTGRES_DB: app_test
        options: >-
          --health-cmd "pg_isready"
          --health-interval 5s
          --health-retries 10
      cache:
        image: redis:8-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
    steps:
      - uses: actions/checkout@v7
      - name: Run tests
        env:
          DATABASE_URL: postgres://postgres:ci@db:5432/app_test   # hostname = имя сервиса
          REDIS_URL: redis://cache:6379/0
        run: npm run test:integration
```

- Задача исполняется на раннере без `container:`, поэтому альтернативная адресация — `localhost:${{ job.services.db.ports[5432] }}`; вариант через имя сервиса проще и не требует маппинга портов вовсе.
- **Валидация**: в логе раздел «Starting application container services» завершается статусом `healthy` для обоих сервисов; тесты подключаются без retry-логики.
- Диагностика падения: `job.services.<name>.id` позволяет вытащить логи сервиса (`docker logs` недоступен, но логи попадают в архив прогона при включённой опции отладки — см. [Инструменты отладки](./Debugging_Tooling.md)).

### Сценарий 3: Матрица версий базы данных

```yaml
jobs:
  compat:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        pg: ['16', '17', '18']
    services:
      db:
        image: postgres:${{ matrix.pg }}
        env: { POSTGRES_PASSWORD: ci }
        options: >-
          --health-cmd "pg_isready" --health-retries 10
    steps:
      - uses: actions/checkout@v7
      - run: ./migrate-and-test.sh
        env:
          DATABASE_URL: postgres://postgres:ci@db:5432/postgres
```

- Выражения в `services.image` разрешаются при планировании задачи — комбинация с матрицей легальна и является штатным способом проверки совместимости миграций (механика матриц — в [Матричных сборках](./Matrix_Builds.md)).
- **Валидация**: три задачи с именами `compat (16/17/18)`; отчёт миграций различает версии сервера.

### Сценарий 4: Диагностика OOM в контейнерной задаче

```bash
# признак: шаг убит без стектрейса, код выхода 137 (128 + SIGKILL)
dmesg | grep -i "killed process" || journalctl -k | grep -i oom
# → Out of memory: Killed process 1234 (node)
```

- Причина: лимит памяти контейнера (`options: --memory`) исчерпан; по умолчанию контейнер получает весь объём раннера, но ручной лимит часто ставят «на всякий случай» слишком низко.
- Решение: поднять `--memory`, ограничить параллелизм тестового раннера (`--max-workers`), вынести тяжёлые шаги из контейнера.
- **Валидация**: повторный прогон проходит с тем же набором тестов; потребление памяти видно в логах инструмента (`--max-old-space-size` для Node).

## Устранение неполадок

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `connection refused` при первом запросе к сервису | Нет health-check: раннер не ждёт готовности БД | Добавить `--health-cmd` с реальной проверкой готовности |
| Exit code 137, шаг молча умер | OOM-killer убил процесс (лимит памяти) | Поднять `options: --memory`, снизить параллелизм приложения |
| `docker: command not found` внутри job container | Socket демона не монтируется в контейнерную задачу | Собирать образы отдельными задачами без `container:` |
| Bind mount ошибка при старте | Указан host-path том в `volumes:` | Использовать именованные/анонимные тома |
| `unauthorized: authentication required` при pull | Не заданы `credentials` для приватного реестра | Добавить блок credentials с секретами |
| `Container operations are only supported on Linux runners` | Задача с `container:`/`services:` назначена на Windows/macOS | Контейнерные ключи работают только на Linux-раннерах |
| Permission denied при записи в workspace | В образе задан непривилегированный `USER` без прав на смонтированный workspace | `options: --user 0` в job container либо подготовить образ под нужный UID |
| `no matching manifest for linux/<arch>` при pull | Образ не собран под архитектуру раннера (например, `arm64`) | Использовать multi-arch образ или раннер соответствующей архитектуры |
| `${{ github.workspace }}` ведёт в несуществующий путь в контейнере | Открытый баг раннера (#2058): контекст отдаёт путь хоста | Опираться на `$GITHUB_WORKSPACE`, а не на контекст |
| Сервис не резолвится по имени | Задача вне контейнера, обращение по alias | Либо добавить `container:`, либо ходить на `localhost:mapped-port` |

## Лучшие практики

1. Всегда пиньте образы (версия минимум, digest максимум) — воспроизводимость важнее свежести.
2. Health-check обязателен для stateful-сервисов; интервал короткий (3–5 c), ретраев достаточно для холодного старта.
3. Минимальные образы (alpine/distroless/slim) для сервисов — быстрее pull, меньше поверхность атаки.
4. Секреты для приватных реестров — только через `credentials`, значения никогда не попадают в YAML.
5. Не запускайте доверенный код в одном контейнере с docker.sock — изоляция job container от демона это фича, а не недоработка.
6. Матрица версий зависимостей (БД, Redis) дешевле и честнее, чем «последний тег на проде угадается сам».

## Дополнительная информация

- **[Running jobs in a container](https://docs.github.com/en/actions/how-tos/write-workflows/choose-where-workflows-run/run-jobs-in-a-container)** — официальный справочник по job containers и service containers.
- **[Customizing the containers used by jobs](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/customizing-the-containers-used-by-jobs)** — self-hosted container hooks (Podman, Kubernetes, CRI).
- **[События, Задачи и Шаги](./Events_Jobs_Steps.md)** — базовый сценарий sidecar-сервисов.
- **[Матричные сборки](./Matrix_Builds.md)** — комбинирование контейнеров и стратегий.
- **[Среды выполнения и ограничения](./Environment_Limitations.md)** — ресурсы раннеров под контейнерные нагрузки.
- **[Сетевая безопасность](./network-security.md)** — egress-контроль трафика контейнеров.
- **[Docker: оптимизация сборки](../Docker/Dockerfile/Docker_best_practices/build_optimization.md)** — слои и сборка базовых CI-образов.
