# Отладка и устранение неполадок в GitLab CI/CD

**Актуально для:** GitLab CI/CD 17.x–19.4, GitLab Runner 17.x–19.4

## Определения

**Отладка пайплайна (Pipeline Debugging)** — системный процесс выявления и устранения логических, синтаксических и инфраструктурных ошибок в конфигурации CI/CD.

**GitLab CLI (`glab`)** — официальный инструмент командной строки для взаимодействия с GitLab. Позволяет управлять пайплайнами, просматривать логи и выполнять глубокую инспекцию конфигурации без Web UI.

**Интерактивный веб-терминал (Interactive Web Terminal)** — функция GitLab, позволяющая подключиться к работающей среде выполнения задачи (контейнеру или виртуальной машине) через браузер для ручного запуска команд и отладки "на месте".

**`CI_DEBUG_TRACE`** — служебная переменная, включающая трассировку выполнения шелл-скриптов (аналог `set -x`). Runner выводит каждую команду и детали взаимодействия с API.

**`CI_DEBUG_SERVICES`** — переменная для отладки Docker-сервисов (`services`). Выводит логи инициализации вспомогательных контейнеров (баз данных, кэшей) в основной лог задачи.

**`gitlab-runner exec`** — команда для локального запуска задач GitLab CI без коммита в репозиторий. Позволяет воспроизвести окружение пайплайна на локальной машине для быстрой отладки.

**Классификация сбоев CI/CD** — выделение трёх основных категорий: (1) сбои конфигурации (ошибки YAML, неверные переменные), (2) сбои приложения (ошибки в коде, тестах, сборке), (3) сбои инфраструктуры (проблемы Runner, сети, ресурсов хоста).

## Предварительные требования

### Версии и поддерживаемые функции

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| GitLab Server | 17.x (рекомендуется 19.4+) | Self-hosted инстанс |
| GitLab Runner | 17.x (рекомендуется 19.4+) | ±1 мажорная версия от GitLab Server |
| `glab` CLI | 2.0+ | Для статического анализа YAML и работы с API |
| `gitlab-runner exec` | 17.x+ | Локальная отладка без коммита |
| Docker Engine | 20.10+ | Для DinD/DooD сценариев и `docker` executor |
| `CI_DEBUG_TRACE` | Все версии | Встроенная переменная GitLab Runner |
| `session_server` | GitLab Runner 16.0+ | Для интерактивного веб-терминала |

### Инфраструктурные требования

-   **GitLab Server**: Self-hosted (on-prem) инстанс GitLab 17.x–19.4 с доступным HTTPS API
-   **RBAC**: Доступ `Developer`+ для просмотра логов; `Maintainer`+ для изменения переменных и настроек Runner'ов
-   **Сеть**: Runner'ы должны иметь доступ к GitLab API (исходящие HTTPS); входящие соединения не требуются (Pull-модель)
-   **TLS**: GitLab Server должен работать по HTTPS с валидным сертификатом (не self-signed в production)
-   **NTP**: Синхронизация времени между GitLab Server и Runner'ами — критична для проверки JWT-подписи и временных меток логов
-   **Хранилище**: Достаточное место для артефактов, кэша и логов; рекомендуется отдельный диск для `/var/lib/gitlab-runner`
-   **Docker** (опционально): Для `docker` executor и DinD сценариев — Docker Engine 20.10+ с включенным `cgroup` driver

### Необходимые знания

-   YAML: синтаксис, вложенность, anchors/aliases
-   GitLab CI/CD: `rules`, `needs`, `extends`, `include`, `trigger`
-   Docker: образы, volumes, сети, DinD/DooD
-   Linux: bash scripting, `set -euo pipefail`, systemd, journalctl
-   GitLab RBAC: роли, области видимости, protected branches
-   REST API: аутентификация, пагинация, фильтрация

## Методология отладки

### Принцип изоляции проблемы

Перед началом отладки необходимо локализовать проблему по одному из трёх уровней:

1. **Уровень конфигурации** — ошибка в `.gitlab-ci.yml`: неверный синтаксис, некорректные `rules`, неправильные `extends`, конфликтующие переопределения переменных.
2. **Уровень выполнения** — ошибка в `script`: команда возвращает ненулевой код, ресурс недоступен, инструмент не установлен в образе.
3. **Уровень инфраструктуры** — проблемы Runner: недостаточно ресурсов, сетевые сбои, проблемы с Docker-демоном, ошибки хранилища.

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

### Принцип最小imalного привилегия при отладке

При отладке секретов и переменных:
- Никогда не логируйте значения секретов в открытом виде
- Используйте `echo "VAR is ${VAR:+set}"` для проверки наличия переменной без раскрытия значения
- Временные отладочные переменные добавляйте через GitLab UI (Settings > CI/CD > Variables), а не хардкодьте в YAML
- После отладки немедленно удаляйте временные переменные

## Инструментарий отладки

### GitLab CLI (glab)

Инструмент критичен для работы со сложными иерархиями YAML ( `include`, `extends`, `components`).

*   **Статический анализ и развертывание YAML**:
    ```bash
    # Показать итоговый YAML после всех include и extends
    glab ci lint --show-expanded
    
    # Валидация с имитацией типа события
    glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=merge_request_event
    ```
*   **Мониторинг выполнения**:
    ```bash
    # Интерактивный дашборд текущего пайплайна
    glab ci view
    
    # Трассировка последней задачи в терминале
    glab ci trace
    ```
*   **Работа с API для отладки**:
    ```bash
    # Получить список последних пайплайнов с их статусами
    glab api "projects/${CI_PROJECT_ID}/pipelines?per_page=10" | jq '.[].status'
    
    # Получить логи конкретной упавшей задачи
    glab api "projects/${CI_PROJECT_ID}/pipelines/${PIPELINE_ID}/jobs" | jq '.[] | select(.status=="failed") | .id'
    
    # Просмотр логов конкретной задачи
    glab api "projects/${CI_PROJECT_ID}/jobs/${JOB_ID}/trace"
    ```

### Интерактивный веб-терминал

Позволяет исследовать файловую систему и сетевое окружение прямо во время выполнения задачи.

1.  **Условие**: Runner должен быть настроен с включенным терминалом (`session_server` в `config.toml`).
2.  **Запуск**: В Web UI на странице задачи нажмите кнопку **Debug** (доступна, пока задача выполняется).
3.  **Использование**: Вы можете устанавливать инструменты (`apt update && apt install -y curl`), проверять доступность портов или содержимое переменных окружения.

> **Ограничение:** Терминал недоступен для задач, которые уже завершились. Для отладки таких задач добавьте `sleep 3600` в секцию `script`.

### Глубокая трассировка (Trace & Services)

Активация через переменные в `.gitlab-ci.yml` или при ручном запуске пайплайна.

```yaml
debug_job:
  variables:
    CI_DEBUG_TRACE: "true"
    CI_DEBUG_SERVICES: "true"
  services:
    - name: postgres:15-alpine
      alias: db
  script:
    - printenv | sort # Инспекция всех переменных (осторожно с секретами!)
    - curl -v http://db:5432 # Проверка сетевой связности с сервисом
```

### Локальная отладка через gitlab-runner exec

Позволяет запускать задачи локально, воспроизводя окружение GitLab CI без коммита в репозиторий.

```bash
# Установка Runner (если не установлен)
curl -L --output /usr/local/bin/gitlab-runner \
  https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-amd64
chmod +x /usr/local/bin/gitlab-runner

# Локальный запуск задачи из текущей ветки
gitlab-runner exec docker test_job

# Запуск с конкретным образом (переопределение image)
gitlab-runner exec docker --docker-image python:3.11 test_job

# Запуск с передачей переменных
gitlab-runner exec docker -v CI_DEBUG_TRACE=true test_job

# Запуск 특정ной задачи из файла конфигурации
gitlab-runner exec docker --file .gitlab-ci.yml test_job
```

**Ограничения `gitlab-runner exec`**:
- Не поддерживает `services` (Docker-сервисы недоступны)
- Не поддерживает `include` (внешние файлы конфигурации не загружаются)
- Секретные переменные (`Protected/Masked`) не передаются автоматически
- Сетевые условия могут отличаться от продакшн-среды
- Кэш и артефакты не сохраняются между запусками

**Альтернатива для сложных сценариев**: инструмент [Dagger](https://dagger.io) или [act](https://github.com/nektos/act) (для GitHub Actions) позволяют воспроизводить CI/CD локально с поддержкой сервисов и кэша.

## Диагностика на уровне Runner

Если задачи застревают в статусе `pending` или падают с системными ошибками, проблема локализована на уровне агента.

### Проверка состояния агента
```bash
# Проверка регистрации и доступности GitLab API
gitlab-runner verify

# Просмотр системных логов в реальном времени
journalctl -u gitlab-runner -f

# Запуск в режиме отладки (остановка службы и ручной запуск)
gitlab-runner --debug run

# Проверка статуса службы
gitlab-runner status

# Просмотр списка зарегистрированных Runner'ов
gitlab-runner list

# Диагностический скрипт для проверки всех компонентов
cat <<'EOF' > runner-diagnose.sh
#!/bin/bash
echo "=== GitLab Runner Diagnostics ==="
echo "--- Version ---"
gitlab-runner --version
echo ""
echo "--- Status ---"
gitlab-runner status
echo ""
echo "--- Registered Runners ---"
gitlab-runner list
echo ""
echo "--- Verify Runners ---"
gitlab-runner verify
echo ""
echo "--- Docker Status ---"
docker info --format '{{.ServerVersion}}' 2>/dev/null || echo "Docker not available"
echo ""
echo "--- Disk Space ---"
df -h / | tail -1
echo ""
echo "--- Memory ---"
free -h 2>/dev/null || vm_stat 2>/dev/null
echo ""
echo "--- Docker Containers ---"
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" 2>/dev/null
echo ""
echo "--- Recent Runner Logs ---"
journalctl -u gitlab-runner --no-pager -n 20 2>/dev/null || echo "No systemd logs"
EOF
chmod +x runner-diagnose.sh
./runner-diagnose.sh
```

### Проблемы с ресурсами
*   **Disk Space**: Ошибка `No space left on device`. Runner не может скачать образ или создать временные файлы. Очистите старые контейнеры и образы: `docker system prune -af`.
*   **OOM (Out of Memory)**: Задача падает с `Exit code 137`. Проверьте лимиты в `config.toml` (секция `[runners.docker] memory`) или системные лимиты хоста.
*   **Zombies**: При использовании Docker-исполнителя могут оставаться "зависшие" контейнеры. Проверьте через `docker ps`.
*   **Disk I/O**: Медленная запись артефактов или кэша. Проверьте `iostat -x 1 5` для выявления узких мест дисковой подсистемы.
*   **CPU throttling**: Задачи выполняются дольше ожидаемого при нормальной загрузке CPU. Проверьте `docker stats` для мониторинга потребления ресурсов контейнерами.

## Сетевая диагностика в CI

Среда CI часто имеет специфические ограничения (Proxy, Firewalls).

*   **DNS Resolution**: Проверьте, резолвятся ли внутренние и внешние имена.
    ```bash
    cat /etc/resolv.conf
    nslookup gitlab.example.com
    # Проверка времени резолвинга
    dig gitlab.example.com | grep "Query time"
    ```
*   **MTU Issues**: Если `git clone` или загрузка артефактов зависают на больших файлах, проверьте MTU сетевого интерфейса Docker. Подробнее см. **[Сетевые проблемы Docker](../../../Docker/Docker_troubleshooting/network_connectivity_issues.md)**.
*   **Service Alias**: Если сервис недоступен по алиасу (например, `db`), убедитесь, что:
    1.  Используется `docker` executor.
    2.  Переменная `FF_NETWORK_PER_BUILD` включена (для изоляции сетей).
*   **Proxy**: Если Runner работает за прокси, настройте переменные `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` в `config.toml` или в переменных проекта.
    ```toml
    # Пример настройки прокси в config.toml
    [runners.docker]
      dns = ["8.8.8.8", "8.8.4.4"]
    ```
*   **SSL/TLS**: Если самоподписанные сертификаты используются для registry или внутренних сервисов, добавьте CA-сертификат в образ:
    ```yaml
    before_script:
      - cp /etc/ssl/certs/my-ca.crt /usr/local/share/ca-certificates/
      - update-ca-certificates
    ```

## Отладка скриптов и окружения

### Shell Best Practices
Для повышения предсказуемости скриптов в GitLab CI используйте строгий режим:

```yaml
.script_template:
  before_script:
    - set -eo pipefail  # Остановка при любой ошибке в пайпе
    - export PS4='+ ${BASH_SOURCE}:${LINENO}: ${FUNCNAME[0]:+${FUNCNAME[0]}(): }'
    - set -x            # Локальный трейс команд
```

### Отладочные артефакты
Если задача генерирует логи, которые слишком велики для стандартного вывода GitLab (лимит ~4-10MB), сохраняйте их как артефакты.

```yaml
test_job:
  script:
    - ./run-tests.sh > full_test_log.txt 2>&1
  artifacts:
    when: always
    paths:
      - full_test_log.txt
    expire_in: 1 day
```

### Отладка артефактов и кэша

**Артефакты не загружаются**:
- Проверьте путь в `paths` — он должен быть относительным корня репозитория
- Убедитесь, что файлы существуют к моменту завершения задачи
- Проверьте размер: артефакты > 100MB могут вызвать проблемы с производительностью
- Используйте `exclude` для исключения ненужных файлов

```yaml
build_job:
  script:
    - ./build.sh
  artifacts:
    paths:
      - dist/
    exclude:
      - dist/**/*.map
      - dist/node_modules/
```

**Кэш не восстанавливается**:
- Проверьте ключ кэша: `key` должен быть детерминированным
- Убедитесь, что путь в `paths` существует после выполнения задачи
- Для монокэша используйте `key: ${CI_COMMIT_REF_SLUG}`

```yaml
cache_debug_job:
  variables:
    CI_DEBUG_TRACE: "true"
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - node_modules/
  script:
    - ls -la node_modules/ # Проверка восстановления кэша
    - npm ci
```

### Отладка переменных и секретов

**Порядок приоритетов переменных** (от низшего к высшему):
1. GitLab instance variables
2. Group variables
3. Project variables
4. Job-level variables
5. Pipeline trigger variables

**Проверка наличия переменных без раскрытия значений**:
```yaml
debug_variables:
  script:
    # Проверка наличия переменных (без вывода значений)
    - echo "DATABASE_URL is ${DATABASE_URL:+SET}${DATABASE_URL:-NOT SET}"
    - echo "API_KEY is ${API_KEY:+SET}${API_KEY:-NOT SET}"
    
    # Вывод первых 4 символов для валидации формата (без раскрытия)
    - echo "API_KEY starts with: ${API_KEY:0:4}..."
    
    # Проверка переменных, необходимых для выполнения
    - |
      for var in DATABASE_URL API_KEY DEPLOY_TOKEN; do
        if [ -z "${!var}" ]; then
          echo "ERROR: Required variable $var is not set"
          exit 1
        fi
      done
```

**Типичные ошибки с переменными**:
- Переменная определена как `masked`, но содержит значение, которое GitLab не может замаскировать (содержит спецсимволы)
- Переменная определена как `protected`, но используется в нев protected ветке
- Переменная переопределена в `rules:when` и не доступна в `script`

### Отладка производительности пайплайна

**Мониторинг времени выполнения задач**:
```yaml
performance_debug:
  script:
    - time ./build.sh 2>&1 | tee build_timing.log
    - time ./test.sh 2>&1 | tee test_timing.log
  artifacts:
    when: always
    paths:
      - build_timing.log
      - test_timing.log
```

**Выявление узких мест**:
- Используйте `needs` для параллельного выполнения независимых задач
- Проверьте кэширование зависимостей (восстановление кэша может быть медленнее `npm install`)
- Мониторьте размер артефактов: передача больших артефактов между задачами — частый источник задержек

## Устранение типичных неисправностей (Troubleshooting)

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Job failed: exit code 1** | Ошибка в логике скрипта или приложении. | Включите `CI_DEBUG_TRACE`, проверьте логи приложения. |
| **Job failed (system failure)** | Проблема инфраструктуры Runner (Docker dead, Disk full). | Проверьте `journalctl -u gitlab-runner` на хосте Runner. |
| **Missing runner token** | Неверный токен при регистрации (v16.0+). | Используйте `--token` (authentication token) вместо registration token. |
| **Connection refused (Docker)** | Runner не имеет прав на `/var/run/docker.sock`. | Добавьте пользователя `gitlab-runner` в группу `docker` или проверьте `privileged` mode. |
| **Entrypoint issues** | Конфликт `ENTRYPOINT` образа и команд GitLab CI. | Переопределите `entrypoint: [""]` в определении образа в YAML. |
| **Job timeout** | Превышен лимит времени выполнения. | Увеличьте `timeout` в настройках проекта или в `config.toml` Runner'а. |
| **No matching runner** | Теги задачи не совпадают с тегами доступных Runner'ов. | Проверьте `tags` в задаче и настройки Runner'ов в Settings > CI/CD > Runners. |
| **Stuck in pending** | Все подходящие Runner'ы заняты или недоступны. | Проверьте `concurrent` в `config.toml`, освободите ресурсы, добавьте Runner'ов. |
| **YAML syntax error** | Ошибка в синтаксисе `.gitlab-ci.yml`. | Выполните `glab ci lint` для валидации, проверьте отступы (2 пробела). |
| **Circular dependency** | Задачи с `needs` образуют цикл. | Проверьте граф зависимостей через `glab ci lint --show-expanded`. |
| **Artifact limit exceeded** | Размер артефактов превышает лимит (по умолчанию 100MB). | Используйте `exclude`, сжатие, или увеличьте лимит в настройках проекта. |
| **Cache not restoring** | Неверный ключ кэша или повреждённые данные. | Используйте `key: files`, проверьте `cache:policy: pull` для read-only кэша. |
| **Token expired/revoked** | Токен доступа к registry или API истёк. | Обновите CI/CD Variables, проверьте `CI_JOB_TOKEN` для built-in операций. |
| **Docker rate limit** | Превышен лимит запросов к Docker Hub. | Настройте mirror registry, используйте аутентифицированный доступ к Docker Hub. |
| **Submodule clone failed** | Проблемы с доступом к приватным подмодулям. | Настройте `GIT_SUBMODULE_STRATEGY` и передайте токен через `GIT_SUBMODULE_FORCE_HTTPS`. |

## Практические сценарии

### Сценарий 1: Отладка сложного наследования (extends/include)
Когда итоговое поведение задачи не совпадает с ожидаемым из-за множественных переопределений.
1.  Выполните `glab ci lint --show-expanded`.
2.  Найдите целевую задачу и проанализируйте секции `before_script` и `variables`.
3.  Помните: последний элемент в списке `extends` имеет наивысший приоритет.

### Сценарий 2: Диагностика "зависшего" пайплайна
Пайплайн не запускается или задачи висят в `pending`.
1.  Проверьте **Settings > CI/CD > Runners**: есть ли активные раннеры с нужными тегами.
2.  Проверьте `rules` и `only/except`: возможно, условия запуска не выполняются для текущей ветки или события.
3.  Используйте `glab ci status` для быстрой проверки статуса из консоли.

### Сценарий 3: Отладка Docker-in-Docker (DinD)
Когда команда `docker build` выдает `Cannot connect to the Docker daemon`.
1.  Убедитесь, что `services` включает `docker:dind`.
2.  Проверьте переменные `DOCKER_HOST` (обычно `tcp://docker:2375`) и `DOCKER_TLS_CERTDIR: ""`.
3.  Включите `CI_DEBUG_SERVICES: "true"` для просмотра логов запуска демона Docker внутри контейнера.

### Сценарий 4: Отладка правил (rules) и условий запуска
Задача не запускается хотя ожидается, или запускается неожиданно.
1.  Проанализируйте `rules` через `glab ci lint --show-expanded` с имитацией переменных:
    ```bash
    glab ci lint --dry-run \
      --variable CI_PIPELINE_SOURCE=merge_request_event \
      --variable CI_MERGE_REQUEST_TARGET_BRANCH_NAME=main \
      --variable CI_COMMIT_BRANCH=feature-xyz
    ```
2.  Проверьте приоритеты: `rules` перезаписывают `only/except`, а `when` в `rules` имеет приоритет над `when` на уровне задачи.
3.  Используйте отладочный вывод для проверки значения переменных:
    ```yaml
    debug_rules:
      rules:
        - if: $CI_COMMIT_BRANCH == "main"
          variables:
            DEBUG_MODE: "true"
      script:
        - echo "Debug mode: $DEBUG_MODE"
    ```

### Сценарий 5: Отладка DAG (Directed Acyclic Graph) и зависимостей
Задачи выполняются в неправильном порядке или с искажениями.
1.  Визуализируйте граф через API:
    ```bash
    glab api "projects/${CI_PROJECT_ID}/pipelines/${PIPELINE_ID}/dag" | jq '.[].name'
    ```
2.  Проверьте корректность `needs`: если задача A указывает `needs: [B]`, но B не существует или имеет опечатку, GitLab игнорирует зависимость.
3.  Для отладки каскадных зависимостей используйте `CI_DEBUG_TRACE`:
    ```yaml
    downstream_job:
      needs: [build_job]
      variables:
        CI_DEBUG_TRACE: "true"
      script:
        - echo "Dependencies resolved, starting execution"
    ```

### Сценарий 6: Отладка scheduled (cron) пайплайнов
Cron-пайплайн не запускается по расписанию или запускается с неверными переменными.
1.  Проверьте расписание в **Build > Schedules**: убедитесь, что cron-выражение корректно и 시간овая зона установлена правильно.
2.  Убедитесь, что ветка, на которую ссылается расписание, существует и не защищена (если cron-задача не помечена как protected).
3.  Проверьте переменные расписания: они переопределяют переменные проекта, но не защищённые переменные.
4.  Используйте `glab ci list --mine` для проверки последних запусков.

### Сценарий 7: Отладка parent-child (downstream) пайплайнов
Дочерний пайплайн не запускается или завершается с ошибкой.
1.  Проверьте статус parent-задачи: `trigger` задача должна быть `success`.
2.  Убедитесь, что `project` и `ref` в `trigger` указывают на правильный репозиторий и ветку.
3.  Для отладки передайте переменные в downstream:
    ```yaml
    trigger_downstream:
      trigger:
        project: group/downstream-project
        ref: main
        variables:
          DEBUG: "true"
          UPSTREAM_PIPELINE_ID: $CI_PIPELINE_ID
    ```
4.  Просмотрите логи downstream-пайплайна через Web UI или API.

### Сценарий 8: Отладка merge request пайплайнов
MR-пайплайн не запускается или неверно определяет целевую ветку.
1.  Проверьте, что пайплайн привязан к MR (статус MR должен быть `opened`).
2.  Убедитесь, что `rules` корректно фильтруют по `CI_PIPELINE_SOURCE=merge_request_event`.
3.  Проверьте `CI_MERGE_REQUEST_TARGET_BRANCH_NAME` — он указывает ветку назначения, а не источник.
4.  Используйте `glab mr view` для просмотра информации о MR.

## Edge cases и ограничения

### Масштаб репозитория
- Репозитории >1GB могут вызывать проблемы с `git clone`. Используйте `GIT_DEPTH: "1"` для shallow clone.
- Для монорепозиториев с `include` из разных проектов учитывайте лимит `include` (50 файлов на пайплайн).
- При большом количестве артефактов настройте `artifacts:expire_in` для автоматической очистки.

### Параллельные задачи
- При параллельном выполнении задач убедитесь, что они не конфликтуют по ресурсам (порты, файлы, Docker-образы).
- Используйте `resource_group` для взаимного исключения задач, работающих с общими ресурсами.
- Для длительных пайплайнов используйте `needs` для параллельного выполнения независимых задач.

### Секреты и маскирование
- GitLab автоматически маскирует переменные, помеченные как `masked`, в логах. Однако если секрет попадает в вывод команды (например, `echo $SECRET`), он будет замаскирован только если формат переменной уникален.
- Переменные с `masked: true` должны содержать минимум 8 символов и не могут содержать `\n`.
- Для OIDC-аутентификации используйте `id_tokens` вместо статических секретов. Это исключает риск утечки долгоживущих паролей через логи.

### Квоты и лимиты
- **Артефакты**: максимальный размер 100MB по умолчанию (настраивается в Settings > CI/CD, до 10GB в GitLab 17+).
- **Кэш**: максимальный размер 10GB на проект.
- **Логи**: отображаются в реальном времени, но обрезаются при превышении ~4-10MB. Для полных логов используйте артефакты.
- **API rate limit**: 60 запросов в минуту для аутентифицированных пользователей. При высоконагруженных инстансах используйте personal access token с расширенным лимитом.
- **Включение задач**: максимальное количество одновременно выполняемых задач ограничено `concurrent` в `config.toml` Runner'а.

### Версионная совместимость
- `rules` заменили `only/except` начиная с GitLab 13.9. Старые конфигурации с `only/except` продолжают работать, но `rules` рекомендуются для новых пайплайнов.
- `needs` для DAG доступны с GitLab 12.2, но полная поддержка `parallel:matrix` с `needs` появилась в 13.3.
- `resource_group` доступен с GitLab 13.12.
- `glrt-` Authentication Token заменил registration token начиная с GitLab 16.0. Для эфемерных Runner'ов используйте JIT Config (GitLab 17.0+).
- `docker-autoscaler` доступен с GitLab 17.0+. В более старых версиях используйте `docker-machine` (устарел) или статические Runner'ы.

### Специфические сценарии
- **Fork-репозитории**: Для Fork MR задачи запускаются только на Shared runner'ах. Project runner'ы не доступны.
- **Запуск пайплайна из пайплайна**: При использовании `CI_JOB_TOKEN` для Trigger API убедитесь, что целевой проект добавлен в Inbound Allowlist. Иначе вернётся 403 Forbidden.
- **Deadlock в Resource Group**: Если задача зависла и удерживает группу, последующие пайплайны будут ждать бесконечно. Ручная очистка в `CI/CD > Resource Groups` или настройка `timeout` на задаче.
- **Высокая частота задач**: При массовых задачах (bulk triggers) GitLab может дедуплицировать запросы. Настраивайте `check_interval` и `concurrent` с запасом.
- **Scheduled пайплайны**: Cron-выражения интерпретируются в UTC. Убедитесь, что временная зона установлена правильно в настройках расписания.

### Ограничения инфраструктуры
- **Сетевая задержка**: Runner должен отвечать на запросы GitLab API за <10 секунд. При высокой задержке увеличьте `check_interval` или используйте regional Runner'ы.
- **TLS-сертификаты**: GitLab не отправляет задачи на HTTP (кроме `localhost` в development-режиме). Убедитесь, что GitLab Server работает по HTTPS с валидным сертификатом.
- **DNS**: GitLab кэширует DNS на 5 минут. При смене IP GitLab Server старый IP может использоваться до истечения кэша.
- **Файрвол**: Если Runner и GitLab Server находятся в разных сегментах сети, откройте порт 443 в обе стороны.
- **Ресурсы хоста**: Убедитесь, что на хосте Runner'а достаточно RAM и CPU. При нехватке ресурсов Docker OOM-killer завершит контейнеры задач.

## Best Practices

### Проектирование CI/CD (DevOps/SRE)

-   **Один executor — одна ответственность**: Не смешивайте задачи разных типов на одном раннере. Отдельные runner'ы для builds, tests, deploy с уникальными тегами.
-   **Protected runners только для production**: Включайте `protected = true` только для runner'ов, обслуживающих `main`/`production` ветки. Это защищает секреты от кражи через Pull Request из форков.
-   **DooD вместо DinD**: По умолчанию используйте DooD (монтирование `/var/run/docker.sock`). DinD (`privileged = true`) — только для задач, требующих полной изоляции Docker-демонов.
-   **Эфемерные runner'ы по умолчанию**: Для тестов и сборок используйте эфемерные runner'ы (Fleeting). Постоянные раннеры — только для долгоживущих стендов с контролируемым доступом.
-   **JIT Config вместо registration tokens**: Используйте JIT (Just-In-Time) Config для автоматической регистрации эфемерных runner'ов. Это исключает хранение registration tokens.
-   **Максимальный `GIT_DEPTH`**: Используйте `GIT_DEPTH: "1"` для shallow clone, если полная история не требуется. Это ускоряет `git clone` и уменьшает использование диска.
-   **Очередь Merge Request**: Для проектов с высокой активностью MR используйте Merge Queue, чтобы предотвратить breakage main при интеграции нестабильных изменений.

### Безопасность (SRE)

-   **`allowed_images` и `allowed_services`**: Ограничьте список разрешённых образов в `config.toml`. Это предотвращает запуск вредоносного ПО через `docker`/`kubernetes` executor.
-   **OIDC вместо статических секретов**: Для доступа к Vault и внутренним сервисам используйте `id_tokens`. Это исключает риск утечки долгоживущих паролей через логи.
-   **`privileged = false` по умолчанию**: Включайте `privileged = true` только для DinD-задач. Для сборки образов используйте Kaniko или BuildKit без привилегий.
-   **Ротация `glrt-` токенов**: Периодически меняйте Authentication Token. Для эфемерных runner'ов используйте JIT Config с коротким TTL.
-   **Сетевая изоляция**: Runner'ы должны находиться в отдельном сегменте сети с доступом только к GitLab API и внутренним registry. Не открывайте доступ к интернету без необходимости.
-   **Аудит регистрации**: Включите audit logging в Admin Area → Settings → Audit Events. Мониторьте новые регистрации runner'ов.

### Производительность и надёжность (Sysadmin/SRE)

-   **`concurrent` и `limit`**: Настраивайте глобальный `concurrent` и per-runner `limit` с запасом 20-30% от пиковой нагрузки. Это предотвращает перегрузку хоста.
-   **`check_interval`**: Устанавливайте `check_interval = 1` для production-раннеров. Меньшие значения увеличивают нагрузку на GitLab API.
-   **Кэширование артефактов**: Настройте распределённый кэш (S3/MinIO) для `docker` executor'ов. Это уменьшает время сборки при переиспользовании зависимостей.
-   **Мониторинг метрик**: Включите `metrics_server = ":9252"` и настройте алерты на `gitlab_runner_queue_size > 0` и `runner_system_failure`.
-   **Резервное копирование config.toml**: Регулярно бэкапите `/etc/gitlab-runner/config.toml` и храните в защищённом хранилище.
-   **Очистка Docker ресурсов**: Настройте автоматическую очистку остановленных контейнеров, неиспользуемых образов и volumes (cron или scheduled pipeline).

### Управление инстансом (Sysadmin)

-   **Обновление Runner'ов**: Обновляйте GitLab Runner в течение 1-2 недель после выхода мажорной версии GitLab. Runner должен быть той же мажорной версии, что и GitLab Server (±1).
-   **Ротация секретов**: Периодически меняйте `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` для кэша и обновляйте их в `config.toml`.
-   **Мониторинг очереди доставки вебхуков**: GitLab помещает неудачные вебхуки в очередь. Мониторьте размер очереди через Admin API.
-   **Резервное копирование**: Регулярно бэкапите базу данных GitLab и хранилище артефактов. Тестируйте восстановление на изолированном стенде.

## Валидация

### Валидация конфигурации до коммита

Перед.push сложных изменений в `.gitlab-ci.yml` выполните валидацию:

```bash
# Статический анализ YAML через glab
glab ci lint --show-expanded

# Валидация с имитацией события Merge Request
glab ci lint --dry-run \
  --variable CI_PIPELINE_SOURCE=merge_request_event \
  --variable CI_MERGE_REQUEST_TARGET_BRANCH_NAME=main

# Проверка синтаксиса через GitLab API (без коммита)
curl -X POST "https://gitlab.example.com/api/v4/projects/${CI_PROJECT_ID}/lint" \
  -H "PRIVATE-TOKEN: ${GITLAB_TOKEN}" \
  -d "content=$(cat .gitlab-ci.yml)"
```

### Валидация после деплоя

```bash
# Проверка последнего пайплайна
glab ci view --latest

# Проверка статуса всех задач
glab api "projects/${CI_PROJECT_ID}/pipelines/${PIPELINE_ID}/jobs" | \
  jq '.[] | {name, status, stage}'

# Проверка метрик Runner'а
curl -s "http://runner1.example.com:9252/metrics" | \
  grep -E "gitlab_runner_jobs_running_total|gitlab_runner_errors_total"
```

### Ожидаемые результаты валидации

| Проверка | Ожидаемый результат |
| :--- | :--- |
| `glab ci lint --show-expanded` | Валидный YAML без ошибок |
| Pipeline Editor → CI Lint | `Valid` с отображением всех stages и jobs |
| `gitlab-runner verify` | `Verifying runner... is alive` |
| Runner metrics | `gitlab_runner_jobs_running_total` > 0 при активных задачах |
| Web Terminal | Доступен для запущенных задач (status: `running`) |

## Дополнительная информация

### См. также
-   **[Обзор Runner и Executor](./gitlab_ci_runners_executors.md)** — детальная диагностика агентов и типов исполнения.
-   **[Продвинутые рабочие процессы](./gitlab_ci_advanced_workflow.md)** — архитектура и оптимизация.
-   **[Сетевые проблемы Docker](../../../Docker/Docker_troubleshooting/network_connectivity_issues.md)** — глубокая диагностика сети (SSoT).
-   **[Диагностика DNS в контейнерах](../../../Linux/Diagnostics/Networking/dns/container_diagnostics.md)** — решение проблем с резолвом имен.
-   [Официальная документация GitLab: Troubleshooting CI/CD](https://docs.gitlab.com/ee/ci/troubleshooting.html)
