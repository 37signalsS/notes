# Отладка и устранение неполадок в GitLab CI/CD

## Определения

**Отладка пайплайна (Pipeline Debugging)** — системный процесс выявления и устранения логических, синтаксических и инфраструктурных ошибок в конфигурации CI/CD.

**GitLab CLI (`glab`)** — официальный инструмент командной строки для взаимодействия с GitLab. Позволяет управлять пайплайнами, просматривать логи и выполнять глубокую инспекцию конфигурации без Web UI.

**Интерактивный веб-терминал (Interactive Web Terminal)** — функция GitLab, позволяющая подключиться к работающей среде выполнения задачи (контейнеру или виртуальной машине) через браузер для ручного запуска команд и отладки "на месте".

**`CI_DEBUG_TRACE`** — служебная переменная, включающая трассировку выполнения шелл-скриптов (аналог `set -x`). Runner выводит каждую команду и детали взаимодействия с API.

**`CI_DEBUG_SERVICES`** — переменная для отладки Docker-сервисов (`services`). Выводит логи инициализации вспомогательных контейнеров (баз данных, кэшей) в основной лог задачи.

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
```

### Проблемы с ресурсами
*   **Disk Space**: Ошибка `No space left on device`. Runner не может скачать образ или создать временные файлы. Очистите старые контейнеры и образы: `docker system prune -af`.
*   **OOM (Out of Memory)**: Задача падает с `Exit code 137`. Проверьте лимиты в `config.toml` (секция `[runners.docker] memory`) или системные лимиты хоста.
*   **Zombies**: При использовании Docker-исполнителя могут оставаться "зависшие" контейнеры. Проверьте через `docker ps`.

## Сетевая диагностика в CI

Среда CI часто имеет специфические ограничения (Proxy, Firewalls).

*   **DNS Resolution**: Проверьте, резолвятся ли внутренние и внешние имена.
    ```bash
    cat /etc/resolv.conf
    nslookup gitlab.example.com
    ```
*   **MTU Issues**: Если `git clone` или загрузка артефактов зависают на больших файлах, проверьте MTU сетевого интерфейса Docker. Подробнее см. **[Сетевые проблемы Docker](../../../Docker/Docker_troubleshooting/network_connectivity_issues.md)**.
*   **Service Alias**: Если сервис недоступен по алиасу (например, `db`), убедитесь, что:
    1.  Используется `docker` executor.
    2.  Переменная `FF_NETWORK_PER_BUILD` включена (для изоляции сетей).

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

## Устранение типичных неисправностей (Troubleshooting)

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Job failed: exit code 1** | Ошибка в логике скрипта или приложении. | Включите `CI_DEBUG_TRACE`, проверьте логи приложения. |
| **Job failed (system failure)** | Проблема инфраструктуры Runner (Docker dead, Disk full). | Проверьте `journalctl -u gitlab-runner` на хосте Runner. |
| **Missing runner token** | Неверный токен при регистрации (v16.0+). | Используйте `--token` (authentication token) вместо registration token. |
| **Connection refused (Docker)** | Runner не имеет прав на `/var/run/docker.sock`. | Добавьте пользователя `gitlab-runner` в группу `docker` или проверьте `privileged` mode. |
| **Entrypoint issues** | Конфликт `ENTRYPOINT` образа и команд GitLab CI. | Переопределите `entrypoint: [""]` в определении образа в YAML. |
| **Job timeout** | Превышен лимит времени выполнения. | Увеличьте `timeout` в настройках проекта или в `config.toml` Runner'а. |

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

## Дополнительная информация

### См. также
-   **[Обзор Runner и Executor](./gitlab_ci_runners_executors.md)** — детальная диагностика агентов и типов исполнения.
-   **[Продвинутые рабочие процессы](./gitlab_ci_advanced_workflow.md)** — архитектура и оптимизация.
-   **[Сетевые проблемы Docker](../../../Docker/Docker_troubleshooting/network_connectivity_issues.md)** — глубокая диагностика сети (SSoT).
-   **[Диагностика DNS в контейнерах](../../../Linux/Diagnostics/Networking/dns/container_diagnostics.md)** — решение проблем с резолвом имен.
-   [Официальная документация GitLab: Troubleshooting CI/CD](https://docs.gitlab.com/ee/ci/troubleshooting.html)
