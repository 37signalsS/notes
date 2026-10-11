# Pipeline Execution Model: внутренности GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

* **Pipeline Creation** — процесс создания пайплайна после события (push, MR, schedule, API trigger).
* **Expanded Config (Expanded YAML)** — итоговый YAML после обработки всех `include`, `extends`, `!reference` и `spec:inputs`.
* **Pipeline Compilation** — этап сборки итогового конфига из всех источников.
* **Pipeline Validation** — проверка синтаксиса, типов, секретов и доступности образов/артефактов.
* **Pipeline Queue** — очередь пайплайнов, ожидающих обработки Sidekiq-воркерами.
* **Job Assignment** — процесс назначения задачи Runner'у по тегам и executor type.
* **Runner Polling** — опрос Runner'ом GitLab API на предмет новых задач (pull-модель).
* **Build Trace (Job Trace)** — лог выполнения задачи, собираемый в реальном времени через `ci_build_trace`.
* **CI_JOB_TOKEN** — краткоживущий токен для аутентификации задач CI/CD внутри job.
* **Sidekiq Worker** — фоновый процесс, обрабатывающий очереди задач GitLab.
* **Pipeline Scheduler** — компонент, планирующий выполнение пайплайнов.
* **Merge Queue** — очередь коммитов для слития в защищённые ветки.
* **Resource Group** — серверный мьютекс, сериализующий доступ задачи к внешнему ресурсу.
* **DAG (Directed Acyclic Graph)** — модель выполнения пайплайна через `needs`, где задачи запускаются по готовности зависимостей, а не строго по стадиям.
* **interruptible** — флаг задачи, указывающий, что она может быть безопасно отменена механизмом `auto_cancel`.

## Основные концепции

### Архитектура выполнения пайплайнов

GitLab CI/CD состоит из нескольких ключевых компонентов, участвующих в выполнении пайплайна:

1. **GitLab Server (Puma/Unicorn)** — веб-интерфейс и API. Принимает события, создаёт пайплайны, отдаёт логи и артефакты.
2. **PostgreSQL** — хранение метаданных пайплайнов, задач, переменных, статусов.
3. **Redis/Valkey** — брокер сообщений для очередей Sidekiq и кэширование.
4. **Sidekiq** — асинхронный обработчик очередей. Отдельные процессы обрабатывают `pipeline_processing`, `create_downstream_pipeline`, `web_hooks`, `mailers` и другие очереди.
5. **Gitaly** — сервис для работы с Git-репозиториями (клонирование, чтение файлов).
6. **Object Storage** — хранение артефактов, логов, бэкground-задач (локальный диск или S3-совместимое хранилище).
7. **Runner** — исполнитель задач. Подключается через pull-модель: опрашивает GitLab API и получает задания.

### Полный жизненный цикл пайплайна

```
[Git Push / MR / Schedule / API / Pipeline Trigger]
    ↓
[Pipeline Creation] — создание записи в PostgreSQL
    ↓
[YAML Compilation] — обработка include, extends, !reference, spec:inputs
    ↓
[Pipeline Validation] — проверка синтаксиса, секретов, правил, образов
    ↓
[Pipeline Queue] — постановка в очередь Sidekiq (pipeline_processing)
    ↓
[Sidekiq Processing] — обработка воркером Sidekiq
    ↓
[Job Scheduling] — выбор Runner'а по тегам/executor/availability
    ↓
[Runner Polling] — Runner опрашивает API (/jobs)
    ↓
[Job Assignment] — назначение задачи Runner'у
    ↓
[Execution] — запуск скриптов в изолированной среде (контейнер/pod/VM/host)
    ↓
[Artifact Upload] — загрузка артефактов и отчётов в Object Storage
    ↓
[Pipeline Finish] — обновление статуса, уведомления, webhooks
```

### Этап компиляции YAML

GitLab собирает итоговый конфигурационный файл в несколько шагов:

1. **Загрузка корневого `.gitlab-ci.yml`**
2. **Обработка `include`** — рекурсивное включение внешних файлов (лимит 150 includes на пайплайн в GitLab 17.3+)
3. **Обработка `extends`** — наследование и объединение блоков
4. **Разрешение `!reference`** — замена ссылок на реальные блоки YAML
5. **Интерполяция `spec:inputs`** — подстановка типизированных параметров (GitLab 17.11+)
6. **Валидация** — проверка синтаксиса, типов, секретов

> **Важно:** На этапе компиляции переменные CI/CD (`$CI_*`, project/group variables) ещё не существуют. Работают только `spec:inputs`.

### Очереди Sidekiq для CI/CD

GitLab использует именованные очереди Sidekiq, сгруппированные по feature category:

| Очередь | Назначение | Приоритет |
|:---|:---|:---|
| `pipeline_processing` | Создание и обработка пайплайнов | Высокий |
| `create_downstream_pipeline` | Создание downstream-пайплайнов | Средний |
| `web_hooks` | Отправка webhook'ов | Средний |
| `mailers` | Email-уведомления | Низкий |
| `default` | Прочие фоновые задачи | Низкий |

### Модель выполнения задачи

```
Job → Runner Assignment → Executor Isolation → Script Execution → Artifact Collection → Upload
```

1. **Runner Assignment**: GitLab выбирает Runner по тегам (`tags`), executor type и доступности. Если Runner не найден, задача остаётся в состоянии `pending`.
2. **Executor Isolation**: Задача выполняется в изолированной среде (контейнер, pod, VM, host).
3. **Script Execution**: Выполняются `before_script` → `script` → `after_script`.
4. **Artifact Collection**: Сбор артефактов и отчётов.
5. **Upload**: Загрузка результатов на GitLab Server.

### Build Trace и логирование

GitLab собирает логи задач в реальном времени через `ci_build_trace`:

- **Live Trace**: Логи доступны в UI во время выполнения задачи.
- **Trace Sink**: Агрегация логов от Runner'а к GitLab Server.
- **Log Storage**: Логи хранятся в PostgreSQL (ссылки) и в artifact storage (полные логи).

### Механизм DAG и stages

GitLab CI/CD поддерживает две модели выполнения:

1. **Stage-based (последовательная)**: задачи выполняются группами (стадии). Внутри стадии — параллельно, между стадиями — последовательно.
2. **DAG (Directed Acyclic Graph)**: через `needs` задачи запускаются сразу после готовности зависимостей, игнорируя границы стадий.

> **Примечание:** DAG требует GitLab 12.2+. Для матричных задач адресация `needs` 1:1 доступна с 16.3+, выражения `$[[ matrix.VAR ]]` в `needs` — с 18.6+.

### Merge Queue

Merge Queue (GitLab 17.0+) — очередь коммитов для защищённых веток. При включённом Merge Queue пайплайны создаются не для каждого коммита отдельно, а для комбинированного набора изменений, что снижает нагрузку на CI/CD при активном мерже.

## Предварительные требования

### Версии и поддерживаемые функции

| Компонент | Минимальная версия | Примечание |
|:---|:---|:---|
| GitLab CE/EE | 17.0+ | Для `spec:inputs` и advanced DAG требуется 17.11+ |
| GitLab Runner | 17.0+ | Рекомендуется версия, совпадающая с основной версией GitLab |
| Docker | 20.10+ | Для исполнителя Docker и сервисных контейнеров |
| `spec:inputs` с `regex` | 17.10+ | Валидация входных параметров регулярными выражениями |
| `spec:inputs` с `options` | 18.0+ | Выпадающие списки в UI «Run Pipeline» |
| `parallel:matrix` + `needs` | 16.3+ | Матричная адресация зависимостей 1:1 |
| `newest_ready_first` | 18.6+ | Приоритизация готовых задач в resource_group |

### Инфраструктурные требования

- **GitLab Instance**: Self-managed (CE/EE). Для пайплайнов с `resource_group` и `auto_cancel` требуется активная связь между Runner'ами и GitLab Server через HTTPS.
- **Runner'ы**: Как минимум один Runner с исполнителем `docker` или `docker+machine`. Для production-сред рекомендуется выделенный Runner с привязкой к группе.
- **Сеть**: Runner должен иметь доступ к внутренним сервисам (реестрам образов, базам данных, artifact-хранилищу). При использовании `services` требуется разрешение межконтейнерного DNS (`alias`).
- **Хранилище артефактов**: Рекомендуется настроить внешнее хранилище (S3-совместимое, Azure Blob, или локальный NFS) для артефактов, чтобы избежать исчерпания диска на GitLab Server.
- **Права доступа**: Учётная запись, запускающая Runner, должна иметь права на монтирование Docker-сокета (если используется `docker` executor) или на создание виртуальных машин (если используется `docker+machine`).

### Необходимые знания

- Синтаксис YAML 1.2 и структура `.gitlab-ci.yml`
- Базовые концепции CI/CD: стадии (`stages`), задачи (`jobs`), артефакты, кэш
- Принципы контейнеризации (Docker-образы, слои, entrypoint, working directory)
- Основы сетевого взаимодействия в Docker (bridge-сеть, DNS-алиасы, публикация портов)
- Работа с предопределёнными переменными GitLab (`CI_COMMIT_SHA`, `CI_PIPELINE_ID`, `CI_REGISTRY`)

## Практические сценарии

### Сценарий 1: Просмотр Expanded Config

```bash
# 1. Через Web UI
# Pipeline → Actions → View merged YAML

# 2. Через glab CLI
glab ci config compile
# → Полный YAML после обработки всех include, extends, !reference, inputs

# 3. Через API
curl --header "PRIVATE-TOKEN: <token>" \
  --header "Content-Type: application/json" \
  --data '{"content": "'"$(cat .gitlab-ci.yml | sed 's/"/\\"/g')"'"}' \
  "https://gitlab.example.com/api/v4/projects/:id/ci/lint?include_merged_yaml=true"
```

### Сценарий 2: Мониторинг Pipeline Queue

```bash
# 1. Проверка размера очереди Sidekiq
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/admin/sidekiq/queues" | \
  jq '.[] | select(.name == "pipeline_processing")'

# 2. Prometheus метрики
curl -s http://localhost:9090/api/v1/query?query=gitlab_ci_current_queue_size
curl -s http://localhost:9090/api/v1/query?query=gitlab_ci_queue_iteration_duration_seconds

# 3. Алерт при большой очереди
# prometheus/alert.rules
- alert: GitLabPipelineQueueHigh
  expr: gitlab_ci_current_queue_size > 50
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "GitLab pipeline queue is high"
```

### Сценарий 3: Устранение задержек при создании пайплайна

```bash
# Диагностика долгого создания пайплайна

# 1. Проверка времени создания
curl -s http://localhost:9090/api/v1/query?query=gitlab_ci_pipeline_creation_duration_seconds

# 2. Проверка размера YAML
wc -c .gitlab-ci.yml
# → Если > 1 MB: упростите includes, используйте CI/CD Components

# 3. Проверка сложности rules
# Слишком много changes patterns замедляют компиляцию
# Лимит: 1000 patterns на pipeline

# 4. Проверка количества includes
# Лимит: 150 includes на pipeline (GitLab 17.3+)

# Решения:
# - Упростите workflow:rules
# - Используйте CI/CD Components вместо множества includes
# - Уменьшите количество stages/jobs в одном YAML
```

### Сценарий 4: Мониторинг выполнения задач

```bash
# 1. Получение логов задачи через API
curl --header "JOB-TOKEN: $CI_JOB_TOKEN" \
  "https://gitlab.example.com/api/v4/projects/:id/jobs/:job_id/trace"

# 2. Проверка статуса задачи
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/jobs/:job_id"

# 3. Prometheus метрики Runner'а
curl -s http://runner:9252/metrics | grep gitlab_runner_
# gitlab_runner_jobs_running_total
# gitlab_runner_concurrent
# gitlab_runner_request_concurrency

# 4. Алерт на долгие задачи
- alert: GitLabJobRunningTooLong
  expr: time() - gitlab_runner_jobs_start_timestamp_seconds > 3600
  for: 10m
  labels:
    severity: warning
```

### Сценарий 5: Внутренности job token и security

```bash
# CI_JOB_TOKEN scope (GitLab 18.0+)

# 1. Проверка allowlist
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/application/settings" | \
  jq '.ci_job_token_scope_enabled'

# 2. Настройка scope в gitlab.rb
gitlab_rails['ci_job_token_scope_enabled'] = true
gitlab_rails['ci_job_token_scope_allowlist'] = ['read_registry', 'write_registry']

# 3. Использование в пайплайне
deploy:
  script:
    - curl --header "JOB-TOKEN: $CI_JOB_TOKEN" \
      "https://gitlab.example.com/api/v4/projects/:id/registry/repositories"
```

### Сценарий 6: Конфигурация Runner под execution model

```bash
# 1. Регистрация Runner'а с тегами для DAG-пайплайна
gitlab-runner register \
  --url https://gitlab.example.com/ \
  --token $RUNNER_TOKEN \
  --executor docker \
  --docker-image docker:24-dind \
  --tag-list "docker,dind,amd64" \
  --run-untagged=false \
  --locked=true \
  --access-level not_protected

# 2. Настройка concurrent и request_concurrency в config.toml
# /etc/gitlab-runner/config.toml
[[runners]]
  name = "docker-runner"
  url = "https://gitlab.example.com/"
  token = "TOKEN"
  executor = "docker"
  [runners.docker]
    image = "docker:24-dind"
    privileged = true
  [runners.custom_config]
    concurrent = 10
    request_concurrency = 2
    output_limit = 10485760  # 10 MB

# 3. Проверка метрик Runner'а
curl -s http://localhost:9252/metrics | grep gitlab_runner_concurrent
curl -s http://localhost:9252/metrics | grep gitlab_runner_jobs_running_total
```

### Сценарий 7: Восстановление зависшего pipeline

```bash
# Папплайн завис в состоянии "pending" без выполнения задач

# 1. Проверка очереди Sidekiq
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/admin/sidekiq/queues" | \
  jq '.[] | select(.name == "pipeline_processing")'

# 2. Проверка, есть ли доступные Runner'ы
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/runners" | jq '.[] | {id, status, tags}'

# 3. Проверка, совпадают ли теги задачи и Runner'а
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/jobs" | \
  jq '.[] | {name, tags: .tag_list, runner: .runner.name}'

# 4. Перезапуск через API (если пайплайн не создан корректно)
curl --request POST \
  --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/pipeline"

# 5. Ручной retry задачи
curl --request POST \
  --header "JOB-TOKEN: $CI_JOB_TOKEN" \
  "https://gitlab.example.com/api/v4/projects/:id/jobs/:job_id/retry"
```

## Операции и команды

### GitLab CI/CD CLI

| Команда | Описание |
|:---|:---|
| `glab ci config compile` | Показать expanded config текущего репозитория |
| `glab ci lint` | Локальная валидация `.gitlab-ci.yml` |
| `glab ci lint --dry-run` | Dry-run валидация с раскрытием includes и inputs |
| `glab ci trace <job-id>` | Потоковое чтение логов задачи |
| `glab pipeline view` | Список пайплайнов проекта |
| `glab pipeline run` | Запуск пайплайна через API |

### GitLab API (высокоуровневые endpoints)

| Endpoint | Метод | Описание |
|:---|:---|:---|
| `/projects/:id/ci/lint` | POST | Валидация YAML, expanded config |
| `/projects/:id/pipeline` | POST | Создание пайплайна |
| `/projects/:id/pipelines/:pipeline_id/jobs` | GET | Список задач пайплайна |
| `/projects/:id/jobs/:job_id/trace` | GET | Получение логов задачи |
| `/projects/:id/jobs/:job_id/retry` | POST | Перезапуск задачи |
| `/projects/:id/jobs/:job_id/cancel` | POST | Отмена задачи |
| `/projects/:id/pipelines/:pipeline_id/cancel` | POST | Отмена пайплайна |
| `/admin/sidekiq/queues` | GET | Размеры очередей Sidekiq (admin) |

### GitLab Runner

| Команда | Описание |
|:---|:---|
| `gitlab-runner verify` | Проверка связи Runner'а с GitLab |
| `gitlab-runner list` | Список зарегистрированных Runner'ов |
| `gitlab-runner run` | Запуск Runner'а в foreground (для отладки) |
| `gitlab-runner exec docker <job> [--docker-image <image>]` | Локальный запуск задачи без коммита |
| `gitlab-runner exec shell <job>` | Локальный запуск задачи в shell |
| `gitlab-ctl tail sidekiq` | Просмотр логов Sidekiq (Omnibus) |

### Docker (для docker executor)

```bash
# Проверка доступности Docker-демона
docker info

# Очистка неиспользуемых образов и контейнеров
docker system prune -f --filter "until=24h"

# Просмотр ресурсов Runner'а
docker stats --no-stream
```

## Устранение неполадок

### Типичные проблемы и решения

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Pending: задача не получает Runner** | Нет Runner'ов с нужными тегами | Проверьте `tags` в задаче и Runner'е; добавьте Runner или исправьте теги |
| **Pending: все Runner'ы offline** | Runner не.polling или TLS-ошибка | Проверьте `gitlab-runner verify`; проверьте сертификаты и сеть |
| **Stuck in "pending" после cancel** | Sidekiq Dead Set или stuck job | Проверьте `/admin/sidekiq/queues`; при необходимости перезапустите Sidekiq |
| **Создание пайплайна > 30s** | Слишком большой YAML или сложные `rules` | Упростите includes, используйте CI/CD Components, разбейте пайплайн |
| **`CI_JOB_TOKEN` не работает** | Отсутствует Inbound Allowlist (18.0+) | Добавьте проект в allowlist или используйте Project Access Token |
| **Ошибка "Job token not found"** | Токен отозван или срок истёк | Токен живёт только в рамках job; используйте `CI_JOB_TOKEN` только внутри `script` |
| **YAML compilation: "undefined variable"** | Переменная используется до объявления | Переменные объявляются после компиляции YAML; используйте `rules:variables` или `script` |
| **Artifact not found downstream** | Задача-потребитель не указана в `needs` | Добавьте `needs: ["build"]` или распределите по stages |
| **`needs:job not found`** | Имя задачи в `needs` не совпадает | Проверьте `CI_JOB_NAME` с суффиксами матрицы |
| **Digest mismatch при promote** | Registry переписал манифест | Используйте immutable tags; верифицируйте digest до и после push |

### Диагностический алгоритм

```
Пайплайн упал
  │
  ├── Есть ли ошибки в CI Lint? → Исправить конфигурацию
  │
  ├── Задача в статусе pending? → Проверить Runners и tags
  │
  ├── Задача падает мгновенно? → Проверить image, entrypoint, variables
  │
  ├── Задача падает в script? → Включить CI_DEBUG_TRACE, проверить логи
  │
  └── Задача зависает? → Проверить timeout, сетевую доступность, ресурсы
```

### Полезные команды диагностики

```bash
# Включение debug-режима в задаче
# В UI: Pipeline → Run pipeline → Edit variables → CI_DEBUG_TRACE=true

# Проверка доступности Runner'ов через API
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/runners" | jq '.[] | {id, status, tags}'

# Просмотр логов Sidekiq (Omnibus)
gitlab-ctl tail sidekiq

# Проверка очередей Sidekiq
gitlab-rails runner "Sidekiq::Queue.all.map { |q| {name: q.name, size: q.size} }"
```

## Рекомендации

### Проектирование execution model

1. **Предпочитайте DAG стадиям**: используйте `needs` для явного указания зависимостей вместо цепочек stages. Это сокращает время выполнения и упрощает рефакторинг.
2. **Используйте `resource_group`** для операций, которые не могут выполняться параллельно (деплой в один environment, миграции БД).
3. **Устанавливайте `timeout` явно** для каждой задачи. Защита от зависаний важнее, чем отсутствие таймаута.
4. **Маркируйте задачи как `interruptible: true`** для не критических операций (lint, тесты). Это позволяет `auto_cancel` эффективно освобождать ресурсы.
5. **Избегайте circular dependencies**: DAG должен быть направленным ациклическим графом. GitLab отклоняет пайплайны с циклами в `needs`.
6. **Используйте `workflow:rules`** для фильтрации пайплайнов на уровне события (push vs MR vs schedule), а не для управления логикой внутри пайплайна.
7. **Ограничивайте размер YAML**: если `.gitlab-ci.yml` превышает 1 MB, разбейте его на компоненты CI/CD Catalog.
8. **Назначайте Runner'ы в группы**, а не в отдельные проекты, для централизованного управления capacity и tags.
9. **Включайте `expire_in` для артефактов** (например, `1h` или `1 week`) для автоматической очистки.
10. **Используйте `dependencies: []` или `needs: []`** для задач, которым не нужны артефакты предыдущих шагов — это экономит время и место.

### Наблюдаемость

1. **Включите метрики очереди** (`gitlab_ci_builds_queuing_metrics` feature flag) для мониторинга задержек.
2. **Настройте алерты** на размер очереди `pipeline_processing > 50` и время создания пайплайна `> 30s`.
3. **Мониторьте `gitlab_runner_jobs_running_total`** относительно `concurrent`-лимита Runner'ов.
4. **Используйте `CI_DEBUG_TRACE`** только при необходимости: логи становятся громоздкими и могут содержать чувствительные данные.

### Безопасность

1. **Никогда не передавайте `CI_JOB_TOKEN`** по SSH в downstream-пайплайны или на удалённые хосты. Используйте Project Access Token с ограниченным scope.
2. **Используйте OIDC Workload Identity** вместо статических секретов для доступа к облачным сервисам (где применимо).
3. **Включайте `protected: true`** для Runner'ов, обрабатывающих защищённые ветки.
4. **Ограничивайте `resource_group`** доступом только к необходимым проектам через Fine-grained Permissions.

## Граничные случаи

### Ограничения execution model

1. **Лимит includes**: 150 includes на пайплайн (GitLab 17.3+). При превышении — ошибка компиляции.
2. **Лимит patterns в `changes:`**: 1000 patterns на пайплайн. Слишком сложные `rules:changes:` замедляют компиляцию.
3. **Лимит задач в пайплайне**: Нет жёсткого лимита, но пайплайны с > 200 задачми замедляют UI и API.
4. **DAG deadlock**: циклические зависимости в `needs` приводят к отклонению пайплайна.
5. **`parallel: N` и `parallel:matrix` взаимоисключающие**: нельзя использовать числовой `parallel` и `matrix` одновременно.
6. **Dotenv + `parallel:matrix`**: Dotenv-переменные не работают между инстансами матрицы. Используйте артефакты или API.

### Особенности поведения

1. **Air-gapped окружения**: Runner'ы не могут обращаться к внешним registry. Используйте локальный registry mirror или pre-cached образы.
2. **Registry failover**: при недоступности Container Registry задача падает на `docker push`. Настройте retry и registry mirror.
3. **Concurrent promotions**: `resource_group` сериализует доступ, но не предотвращает состояние гонки на уровне registry. Используйте immutability tags.
4. **Approval TTL**: approval rules не имеют встроенного TTL. Для автоматического отката используйте `workflow:auto_cancel`.
5. **Runner resources**: Runner с `concurrent=1` обрабатывает одну задачу за раз. Для параллелизма увеличьте `concurrent` в `config.toml`.
6. **Multi-project artifacts**: `needs:project` требует явного разрешения через project access tokens или `CI_JOB_TOKEN` allowlist.
7. **Helm chart drift**: версия Helm в Runner-образе должна совпадать с версией, использованной при упаковке chart.

### Cleanup и откат

```bash
# Отмена stuck approval
curl --request POST \
  --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/approvals/:approval_id/unapprove"

# Отмена пайплайна
curl --request POST \
  --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/projects/:id/pipelines/:pipeline_id/cancel"

# Очистка неиспользуемых Docker-образов на Runner'е
docker system prune -f --filter "until=24h"

# Очистка старых артефактов через API (скрипт)
# Требует административного токена и Python-скрипта для пагинации
```

## Дополнительная информация

### См. также

* **[Мониторинг и метрики](./monitoring_and_metrics.md)** — метрики пайплайнов и Runner'ов
* **[Sidekiq: глубинное погружение](./gitlab_sidekiq_deep_dive.md)** — архитектура очередей
* **[CI/CD API Rate Limits](./ci_cd_api_rate_limits.md)** — лимиты API
* **[Валидация пайплайнов](./pipeline_validation_and_versioning.md)** — локальное тестирование и dry-run
* **[DAG с использованием needs](./workflow_rules/dag_with_needs.md)** — управление графом зависимостей
* **[Матричные сборки и сериализация](./workflow_rules/matrix_builds_and_serialization.md)** — `parallel:matrix`, `resource_group`
* **[Правила запуска задач](./workflow_rules/job_rules.md)** — `rules`, `only/except`, `when`
* **[CI_JOB_TOKEN: attack surface и аудит](./ci_job_token_security.md)** — безопасность токенов
* **[Отладка и устранение неполадок](./debugging_and_troubleshooting.md)** — методология диагностики

### Ключевые метрики для мониторинга

Подробный справочник метрик — в **[Мониторинг и метрики GitLab CI/CD](./monitoring_and_metrics.md)**.

| Метрика | Описание | Алерт |
|:---|:---|:---|
| `gitlab_ci_pipeline_creation_duration_seconds` | Время создания пайплайна | > 30s |
| `gitlab_ci_current_queue_size` | Размер очереди пайплайнов | > 50 |
| `gitlab_ci_queue_iteration_duration_seconds` | Время поиска задачи в очереди | > 5s |
| `pipelines_finished_total` | Количество завершённых пайплайнов | Success Rate < 95% |
| `gitlab_runner_jobs_running_total` | Текущие выполняющиеся задачи | > concurrent limit |
