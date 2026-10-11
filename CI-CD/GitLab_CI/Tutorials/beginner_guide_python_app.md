# Настройка CI/CD для простого Python-приложения

**Актуально для:** GitLab 19.x

## Определения

**uv** — сверхбыстрый менеджер пакетов и установщик Python, написанный на Rust. К 2026 году является индустриальным стандартом для CI/CD благодаря экстремальной скорости установки и встроенной поддержке виртуальных окружений.

**GitLab Container Registry** — встроенный в GitLab реестр Docker-образов. Позволяет хранить образы приложений в контексте проекта, обеспечивая тесную интеграцию с пайплайнами.

**CI_JOB_TOKEN** — кратковременный токен безопасности, автоматически создаваемый для каждой задачи. Используется для авторизации в Registry и API без необходимости ручного управления секретами.

**Multi-stage Build (Многостадийная сборка)** — метод оптимизации Docker-образов, позволяющий разделить этап сборки зависимостей (с компиляторами и инструментами) от этапа выполнения, что минимизирует размер и поверхность атаки финального образа.

**Docker Executor** — тип GitLab Runner, который запускает задачи в изолированных Docker-контейнерах. Это обеспечивает чистоту окружения и безопасность хост-системы.

**default-блок** — рекомендуемый в GitLab 18.x/19.x способ задания общих настроек (образ, теги, кэш) для всех задач без использования устаревших глобальных ключевых слов `before_script`, `image`, `cache` на верхнем уровне.

**workflow:rules** — глобальные правила, управляющие запуском всего пайплайна. Позволяют отсеивать дублирующие запуски (например, при одновременном открытии MR и пуше в ветку) и экономят ресурсы раннеров.

## Основные концепции

### Зачем Python-приложению CI/CD?

Автоматизация жизненного цикла Python-приложения решает три ключевые проблемы:
1.  **Конфликты зависимостей:** Гарантирует, что код работает в той же версии интерпретатора и библиотек, что и у разработчика.
2.  **Регрессии:** Автоматический запуск тестов при каждом коммите предотвращает попадание багов в основную ветку.
3.  **Безопасность доставки:** Контейнеризация упаковывает приложение вместе со всеми зависимостями в неизменяемый артефакт, готовый к деплою.

### Архитектура пайплайна

Пайплайн состоит из трёх изолированных стадий, каждая из которых выполняет проверку или действие перед переходом к следующей:

```
[Коммит] → [validate] → [build] → [deploy] → [Production]
               ↓           ↓          ↓
            linting     build      SSH deploy
            unit-tests  push
```

1.  **Validate (Проверка качества):** Быстрые статические проверки (`ruff`) и модульные тесты (`pytest`). При ошибке пайплайн завершается до затратных операций сборки.
2.  **Build (Сборка образа):** Multi-stage Docker-сборка с кэшированием зависимостей через `uv`. Образ помещается в GitLab Container Registry с уникальным тегом SHA коммита.
3.  **Deploy (Деплой):** Доставка образа на целевой хост по SSH. Деплой в `production` защищен правилом `when: manual`, что требует явного подтверждения Maintainer'ом.

Каждая стадия изолирована: Runner запускает свежий Docker-контейнер, что исключает «загрязнение» окружения между задачами.

### Принцип «Ворот качества» (Quality Gates)

Пайплайн не просто доставляет код, он проверяет его на соответствие стандартам:
*   **Static Analysis (SAST):** Проверка синтаксиса и стиля (PEP 8) через `ruff` или `flake8`.
*   **Unit Testing:** Проверка логики функций через `pytest`.
*   **Container Audit:** Проверка образа на наличие уязвимостей в системных библиотеках.

## Практические сценарии

### Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая версия | Установка |
| :--- | :--- | :--- | :--- |
| **Docker** | 24.0 | 27.0 | `sudo apt install docker.io` (Ubuntu) |
| **GitLab Runner** | 16.0 | 17.0+ | См. [Регистрация Runner](./runner_registration.md) |
| **uv** | 0.4.0 | 0.8.x | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Python** | 3.11 | 3.13 | Входит в Docker-образ |

**Проверка окружения:**
```bash
docker --version
# → Docker version 27.0.3, build 7d4fcc8

gitlab-runner --version
# → Version:      17.8.0

# Установка uv (для локальной разработки)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
# → uv 0.8.13
```

**Предварительные требования (checklist):**
1.  **Репозиторий:** Приватный проект в GitLab.
2.  **Runner:** Установленный GitLab Runner с тегом `docker-runner` и включённым Docker-in-Docker.
3.  **Доступ:** Права `Maintainer` в проекте для настройки переменных и CI/CD.
4.  **Container Registry:** Включен в настройках проекта (Deploy -> Container Registry).
5.  **Переменные:** `SSH_PRIVATE_KEY` и `SSH_KNOWN_HOSTS` добавлены в CI/CD -> Variables (для деплоя по SSH).

### Шаг 1: Подготовка кода приложения и зависимостей

Создайте минимальное Flask-приложение. Для управления зависимостями используем современный формат `pyproject.toml`.

**`app.py`:**
```python
from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    return jsonify({"status": "ok", "message": "Hello from GitLab CI/CD 2026!"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
```

**`pyproject.toml` (конфигурация uv/pip):**
```toml
[project]
name = "python-beginner-app"
version = "0.1.0"
dependencies = [
    "flask>=3.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "ruff>=0.4.0",
]
```

### Шаг 2: Создание безопасного Dockerfile (Multi-stage + uv)

Используем `uv` для мгновенной сборки и `python:3.13-slim` для минимизации размера.

**`.dockerignore` (обязательно перед Dockerfile):**
```
.git
.gitignore
__pycache__
*.pyc
.pytest_cache
.ruff_cache
*.egg-info
dist
build
.env
.venv
venv
htmlcov
.coverage
.coverage.*
report.xml
*.log
```

**`Dockerfile`:**
```dockerfile
# syntax=docker/dockerfile:1

# Stage 1: Сборка зависимостей (Builder)
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.8.13 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml ./
# Установка зависимостей в отдельную директорию без кэша в финальном слое
RUN uv pip install --system --no-cache-dir .

# Stage 2: Финальный образ (Runtime)
FROM python:3.13-slim

WORKDIR /app
# Создание непривилегированного пользователя
RUN useradd -m -u 10001 appuser

# Копируем установленные пакеты из builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY app.py .

RUN chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
EXPOSE 5000

# Проверка здоровья контейнера (Docker HEALTHCHECK)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/')" || exit 1

# Использование exec-формы для корректной обработки сигналов (SIGTERM)
ENTRYPOINT ["python", "app.py"]
```

**Проверка сборки локально:**
```bash
docker build -t python-app .
docker run -d --name python-app -p 5000:5000 python-app
curl http://localhost:5000/
# → {"status":"ok","message":"Hello from GitLab CI/CD 2026!"}

# Проверка HEALTHCHECK
docker inspect --format='{{json .State.Health}}' python-app | python3 -m json.tool
# → "Status": "healthy"
```

### Шаг 3: Настройка пайплайна `.gitlab-ci.yml`

Пайплайн разделен на проверку качества, сборку образа и деплой. Используем кэширование `uv` для ускорения задач. Конфигурация следует рекомендациям GitLab 19.x: `default:`-блок для общих настроек, `workflow:rules` для фильтрации запусков, `timeout-minutes` для защиты от зависаний.

```yaml
# Глобальные правила запуска пайплайна (GitLab 19.x)
workflow:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS'
      when: never
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

stages:
  - validate
  - build
  - deploy

variables:
  DOCKER_HOST: tcp://docker:2375
  DOCKER_TLS_CERTDIR: ""
  IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

# Настройки по умолчанию (GitLab 19.x)
default:
  tags:
    - docker-runner

# Шаблон для задач, требующих Docker
.docker-env:
  image: docker:27.0
  services:
    - docker:27.0-dind
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY

# Статическая проверка кода (Линтинг)
linting:
  stage: validate
  image: ghcr.io/astral-sh/uv:python3.13-slim
  interruptible: true
  timeout-minutes: 10
  retry: 2
  script:
    - uv pip install --system ruff
    - ruff check .
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "**/*.py"
        - "pyproject.toml"
        - ".gitlab-ci.yml"
  tags:
    - docker-runner

# Запуск тестов
unit-tests:
  stage: validate
  image: ghcr.io/astral-sh/uv:python3.13-slim
  interruptible: true
  timeout-minutes: 15
  retry: 2
  script:
    - uv pip install --system .[dev]
    - pytest --junitxml=report.xml
  artifacts:
    when: always
    expire_in: 1 week
    reports:
      junit: report.xml
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
         - "**/*.py"
         - "pyproject.toml"
         - ".gitlab-ci.yml"

# Сборка и отправка образа в Registry
build-image:
  stage: build
  extends: .docker-env
  timeout-minutes: 20
  retry: 2
  script:
    - docker build -t $IMAGE_TAG .
    - docker push $IMAGE_TAG
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

# Пример деплоя на удаленный сервер
deploy-prod:
  stage: deploy
  extends: .docker-env
  timeout-minutes: 30
  resource_group: production-deploy
  script:
    - ssh $DEPLOY_USER@$DEPLOY_HOST "docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY && 
        docker pull $IMAGE_TAG && 
        docker stop my-app || true && 
        docker rm my-app || true && 
        docker run -d --name my-app -p 5000:5000 $IMAGE_TAG"
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

## Валидация и проверка

Для подтверждения успешной настройки выполните следующие действия:
1.  **CI Lint:** В интерфейсе GitLab перейдите в **CI/CD > Editor** и нажмите **Validate**. Убедитесь, что синтаксис корректен и все `extends`/`include` раскрыты.
2.  **Проверка статуса пайплайна:** В интерфейсе GitLab (Build -> Pipelines) все стадии должны быть отмечены зеленым цветом.
3.  **Просмотр артефактов:** Убедитесь, что в задаче `unit-tests` появился вкладка **Tests** с результатами `pytest`.
4.  **Проверка Registry:** Перейдите в **Deploy -> Container Registry**. Там должен появиться новый образ с тегом (коротким SHA коммита).
5.  **Проверка Runner'ов:** Выполните на хосте с Runner'ом:
    ```bash
    gitlab-runner list
    # → Должен отображаться registered runner с тегом docker-runner

    gitlab-runner verify
    # → Все раннеры должны быть доступны
    ```
6.  **Локальный запуск:** Скачайте собранный образ локально и запустите его:
    ```bash
    docker run -it --rm -p 5000:5000 <registry_url>/<project_path>:<tag>
    ```

## Архитектура Runner для Sysadmin

Для администратора инфраструктуры важно понимать конфигурацию Runner на уровне хоста. GitLab Runner хранит настройки в `/etc/gitlab-runner/config.toml`.

**Пример `config.toml` для Docker Executor:**
```toml
concurrent = 4
check_interval = 3

[[runners]]
  name = "docker-runner"
  url = "https://gitlab.example.com/"
  token = "glrt-..."
  executor = "docker"
  limit = 2

  [runners.docker]
    image = "docker:27.0"
    privileged = true
    volumes = ["/var/run/docker.sock:/var/run/docker.sock"]
    allowed_images = ["docker:*", "alpine:*", "python:*"]
    pull_policy = "if-not-present"
    shm_size = 0
```

**Параметры для Sysadmin:**
*   **`concurrent`** — глобальный лимит параллельных задач на менеджере. Устанавливайте исходя из доступных CPU/RAM.
*   **`limit`** — лимит задач для конкретного раннера. `0` = без ограничения (до `concurrent`).
*   **`privileged = true`** — требуется для DinD. Даёт контейнеру доступ к ядру хоста. Для production сред рассмотрите **Kaniko** или **BuildKit без привилегий**.
*   **`shm_size`** — размер shared memory. Для Python-приложений с NumPy/SciPy установите `shm_size = "1gb"` для предотвращения segmentation fault.
*   **`pull_policy`** — `if-not-present` ускоряет запуск задач за счёт использования локального кэша образов.

## Технические нюансы и Безопасность

### Почему `uv` вместо `pip`?
В CI/CD время — это деньги. `uv` устанавливает зависимости до 10-100 раз быстрее за счет реализации на Rust и эффективного управления кэшем. В данном руководстве мы используем `--system` для установки напрямую в системный Python контейнера, так как контейнер сам по себе обеспечивает изоляцию.

### Безопасность Non-root пользователя
Запуск приложения от `root` внутри контейнера — критическая уязвимость. Если злоумышленник взломает приложение, он получит права суперпользователя в контексте контейнера. Использование `USER appuser` минимизирует риски.

### Использование `CI_JOB_TOKEN`
Этот токен имеет права только на текущий проект и живет только время работы задачи. Это гораздо безопаснее, чем использование личных Access Tokens или статических паролей. В GitLab 19.x можно дополнительно ограничить токены через **Fine-grained Permissions**.

### Защита `timeout-minutes` и `resource_group`
*   **`timeout-minutes`** — предотвращает зависание пайплайна при блокировках сети или дедлоках. Для деплоя production рекомендуется `30` минут.
*   **`resource_group`** — гарантирует, что в production-среде запускается только один деплой одновременно. При попытке второго параллельного запуска задача ставится в очередь (`pending`).

## Устранение неполадок (Troubleshooting)

### Пайплайн

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Permission denied (Docker)** | Runner не имеет прав на Docker Socket | Убедитесь, что Runner настроен с привилегированным режимом для DinD (`privileged = true` в `config.toml`) или используйте Kaniko. |
| **ModuleNotFoundError** | Зависимость не установлена в Dockerfile | Проверьте, добавлен ли пакет в `pyproject.toml` и выполнен ли `uv pip install`. |
| **SSH connection timed out** | Закрыт порт 22 на целевом сервере | Проверьте настройки Firewall (iptables/nftables) на сервере деплоя. |
| **GitLab Registry 403 Forbidden** | Недостаточно прав у токена | Убедитесь, что в настройках проекта включен Container Registry и токен `CI_JOB_TOKEN` имеет права `write_repository`. |
| **HEALTHCHECK: starting** | Контейнер еще не готов | Начальная задержка `start-period=10s` — подождите. Если продолжает оставаться на `unhealthy`, проверьте логи: `docker logs python-app`. |
| **No space left on device** | Заполнен диск на Runner | Очистите старые образы: `docker system prune -a` или добавьте volume для кэша. |
| **pip install fails in CI** | Нет доступа к PyPI через прокси | Добавьте прокси в переменные: `PIP_INDEX_URL`, `HTTPS_PROXY`. |
| **uv: command not found** | Бинарник uv не скопирован в runtime | Проверьте строку `COPY --from=builder /usr/local/bin /usr/local/bin` в Dockerfile. |
| **SIGTERM received, exiting** | Приложение не обрабатывает сигналы | Используйте exec-форму ENTRYPOINT (`["python", "app.py"]` вместо `CMD python app.py`). |
| **Connection refused (5000)** | Flask не слушает 0.0.0.0 | Убедитесь, что `app.run(host='0.0.0.0')` — по умолчанию Flask слушает только localhost. |
| **GitLab CI: job: not found** | Неправильный тег Runner'а | Проверьте `tags:` в `.gitlab-ci.yml` совпадают с тегом registered Runner'а. |
| **Docker-in-Docker: Cannot connect** | `DOCKER_HOST` не задан или порт закрыт | Проверьте переменную `DOCKER_HOST: tcp://docker:2375` и что сервис `docker:dind` доступен. |
| **Runner: OOMKilled** | Недостаточно RAM на хосте | Увеличьте `limit` в `config.toml` или добавьте swap. Проверьте: `docker inspect <runner_container>`. |
| **cannot allocate memory (DinD)** | `shm_size` слишком мал | Установите `shm_size = "1gb"` в `config.toml` или `--shm-size=1g` в `docker run`. |

### Инфраструктура (Sysadmin)

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Gitaly timeout 502** | Медленный HDD/SSD на хосте GitLab | Для production обязательны SSD/NVMe и драйвер `overlay2`. Проверьте: `gitlab-ctl status gitaly`. |
| **PostgreSQL 17 required** | Устаревшая версия БД при обновлении | GitLab 19.0+ требует PostgreSQL 17. при обновлении с 18.x миграция схемы может занять часы на больших инстансах (>50 GB). Тестируйте обновление в staging. |
| **Sidekiq queue backlog** | Большое количество одновременных задач | Мониторьте длину очереди через `/admin/sidekiq/queues` и настраивайте `concurrency` в `gitlab.rb` под количество RAM. |
| **Docker-in-Docker и SELinux** | SELinux блокирует контейнеры dind | На RHEL/CentOS/Fedora добавьте опции `:z` или `:Z` для томов, или отключите SELinux для тестирования. |
| **Docker-in-Docker и AppArmor** | Профиль AppArmor конфликтует с DinD | На Ubuntu/Debian проверьте профиль: `aa-status`. Добавьте исключение для `docker` бинарника. |
| **Runner не берет задачи** | Runner не авторизован или теги не совпадают | Проверьте статус: `gitlab-runner list`. Убедитесь, что теги задачи совпадают с тегами Runner'а. |
| **Container перезапускается** | CrashLoopBackOff из-за ошибки в конфиге | Проверьте логи: `docker logs gitlab --tail 100`. Частая причина — невалидный `GITLAB_OMNIBUS_CONFIG`. |

### Граничные случаи

*   **Gitaly в Docker:** GitLab 19.x интенсивно использует Gitaly (сервис управления git-репозиториями). При запуске GitLab в Docker на хосте с медленным HDD возникают таймауты Gitaly и ошибки 502. Для production сред обязательны SSD/NVMe и драйвер `overlay2`.
*   **Минимальная версия PostgreSQL:** GitLab 19.0+ требует PostgreSQL 17. При обновлении с GitLab 18.x миграция схемы может занять часы на больших инстансах (>50 GB). Тестируйте обновление в staging перед production.
*   **Память и `shm_size`:** Для Python-приложений с NumPy/SciPy стандартный `shm_size: 64mb` в Docker недостаточен — возникают ошибки сегментации. Установите `shm_size: '1gb'` в Docker Compose или передайте `--shm-size=1g` в `docker run`.
*   **Sidekiq queue backlog:** При деплое большого количества задач одновременно Sidekiq может отставать. Мониторьте длину очереди через `/admin/sidekiq/queues` и настраивайте `concurrency` в `gitlab.rb` под количество RAM.
*   **Docker-in-Docker и SELinux:** На хостах с включенным SELinux (RHEL, CentOS, Fedora) DinD требует дополнительных опций `:z` или `:Z` для томов. Без этого контейнеры dind не смогут запустить дочерние контейнеры.
*   **Зависимости с нативными расширениями (C-extensions):** Пакеты вроде `psycopg2`, `cryptography` или `numpy` требуют компиляторов C (`gcc`, `musl-dev`). Multi-stage build должен включать соответствующие системные пакеты в builder-образ, иначе `uv pip install` упадет с ошибкой линковки.
*   **Сеть и IPv6:** Если хост имеет только IPv6-адрес, убедитесь, что Docker daemon слушает на `tcp://[::1]:2375` или доступном интерфейсе, а не только на `unix:///var/run/docker.sock`, иначе Runner не сможет подключиться к DinD.
*   **Очередь Runner при высокой нагрузке:** При более чем 100 коммитах в день настройте `interruptible: true` для задач валидации в MR. Это отменяет устаревшие запуски при новом пуше, экономя ресурсы.
*   **Runner OOMKiller:** Если Runner периодически завершается с `OOMKilled`, проверьте лимиты памяти в `config.toml` и добавьте swap на хосте. Для DinD рекомендуется минимум 4 GB RAM.

## Дополнительная информация

### Документация переменных окружения

Переменные, используемые в пайплайне, должны быть добавлены через **CI/CD -> Variables**:

| Переменная | Описание | Где добавить | Защищена? |
| :--- | :--- | :--- | :--- |
| `SSH_PRIVATE_KEY` | Приватный SSH-ключ для деплоя | CI/CD -> Variables | Yes (masked + protected) |
| `SSH_KNOWN_HOSTS` | SSH fingerprint целевого сервера | CI/CD -> Variables | No |
| `DEPLOY_USER` | Пользователь на сервере деплоя | CI/CD -> Variables | No |
| `DEPLOY_HOST` | IP/hostname сервера деплоя | CI/CD -> Variables | No |

**Генерация SSH_KNOWN_HOSTS:**
```bash
ssh-keyscan -H <deploy_host>
# → Вывод скопируйте в переменную SSH_KNOWN_HOSTS
```

**Генерация SSH ключа:**
```bash
ssh-keygen -t ed25519 -C "gitlab-ci-deploy" -f deploy_key -N ""
# → deploy_key (приватный) → в переменную SSH_PRIVATE_KEY
# → deploy_key.pub (публичный) → добавьте в ~/.ssh/authorized_keys на целевом сервере
```

### Лучшие практики (Best Practices)

**Безопасность:**
*   Всегда используйте `USER appuser` в Dockerfile — никогда не запускайте приложение от root.
*   Используйте `CI_JOB_TOKEN` вместо личных Access Tokens — токен автоматически истекает после задачи.
*   Маскируйте секреты в CI/CD Variables (флаги `masked` + `protected`).
*   Используйте `--no-cache-dir` для pip/uv в CI — ускоряет сборку и исключает утечку кэша.
*   Для DinD используйте `privileged = true` только на изолированных раннерах. Для production — переходите на Kaniko.
*   Ограничьте `allowed_images` в `config.toml` — разрешайте только доверенные образы.

**Производительность:**
*   Используйте Multi-stage Build — образ уменьшается на 40-60%.
*   Кэшируйте Docker-слои: в CI кэшируйте `uv` cache через `variables: UV_CACHE_DIR`.
*   Не копируйте `.git` и другие артефакты через `.dockerignore`.
*   Используйте `default:`-блок в `.gitlab-ci.yml` для DRY и соответствия GitLab 19.x.
*   Добавьте `timeout-minutes` к задачам CI/CD для защиты от бесконечных пайплайнов.
*   Используйте `artifacts:expire_in` для автоматической очистки артефактов.
*   Добавьте `interruptible: true` для задач валидации в MR — экономьте ресурсы при активной разработке.
*   Используйте `retry: 2` для network-dependent задач (pip install, docker push).
*   Используйте `rules:changes` для запуска задач только при изменении релевантных файлов.

**Надёжность:**
*   Пинайте версии инструментов: `uv:0.8.13` вместо `uv:latest`.
*   Используйте `HEALTHCHECK` в Dockerfile для оркестраторов (Docker Compose).
*   Используйте `workflow:rules` для предотвращения дублирования пайплайнов.
*   Добавьте `resource_group` для критических деплоев в production.
*   Тестируйте Docker-образ локально перед коммитом: `docker build -t app:test . && docker run --rm app:test`.

**Логирование:**
*   `PYTHONUNBUFFERED=1` — обязательная переменная для корректного вывода логов в stdout/stderr.
*   В продакшене используйте JSON-formatted логи для парсинга (ELK, Loki).

### Очистка артефактов (Cleanup)

**Удаление образа из Container Registry:**
```bash
# Удаление конкретного тега через API
curl --request DELETE "https://gitlab.example.com/api/v4/projects/<project_id>/registry/repositories/<repo_id>/tags/<tag>" \
  --header "PRIVATE-TOKEN: <your_token>"

# Удаление всех тегов через скрипт
for tag in $(curl -s "https://gitlab.example.com/api/v4/projects/<project_id>/registry/repositories/<repo_id>/tags" | python3 -c "import sys,json; [print(t['name']) for t in json.load(sys.stdin)]"); do
  curl --request DELETE "https://gitlab.example.com/api/v4/projects/<project_id>/registry/repositories/<repo_id>/tags/$tag" \
    --header "PRIVATE-TOKEN: <your_token>"
done
```

**Очистка Registry через GitLab UI (рекомендуется):**
1.  Перейдите в **Deploy > Container Registry**.
2.  Нажмите на репозиторий и выберите **Delete tag** для устаревших тегов.
3.  Включите **Cleanup policy** в **Settings > Packages and Registries > Container Registry**:
    *   Укажите `expire_in: 30d` для автоматического удаления тегов старше 30 дней.
    *   Исключите теги `latest` и `release-*` из очистки.

**Автоматическая очистка Registry (через CI):**
```yaml
cleanup-registry:
  stage: .post
  image: alpine:latest
  script:
    - apk add --no-cache curl jq
    - curl -s "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/registry/repositories" \
        --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" | jq -r '.[].id' | while read repo_id; do
        curl -s "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/registry/repositories/$repo_id/tags" \
          --header "PRIVATE-TOKEN: $CI_JOB_TOKEN" | \
          jq -r '.[] | select(.name | test("^(latest|release-)$") | not) | .name' | \
          head -n -5 | xargs -I {} curl -s --request DELETE \
          "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/registry/repositories/$repo_id/tags/{}" \
          --header "PRIVATE-TOKEN: $CI_JOB_TOKEN"
      done
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
  tags:
    - docker-runner
```

**Очистка артефактов CI:**
```bash
# Ручная очистка через API
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/jobs/$JOB_ID/artifacts"

# Настройте политику в Settings > CI/CD > Artifacts > Artifacts expiration
```

**Очистка кэша Runner:**
```bash
# На хосте Runner'а
gitlab-runner cache-clear --all-runners

# Локальная очистка uv-кэша
uv cache clean
rm -rf .venv
```

**Откат деплоя (Rollback):**
```bash
# На целевом сервере — остановка текущего контейнера и запуск предыдущего образа
ssh $DEPLOY_USER@$DEPLOY_HOST << 'EOF'
docker stop my-app && docker rm my-app
# Используем тег предыдущего коммита или release-тег
docker pull $CI_REGISTRY_IMAGE:previous_tag
docker run -d --name my-app -p 5000:5000 $CI_REGISTRY_IMAGE:previous_tag
EOF
```

### Мониторинг и логирование

**Базовый мониторинг приложения:**

```python
# Добавьте в app.py для экспорта метрик для Prometheus
from prometheus_client import Counter, Gauge, generate_latest
from flask import Response

REQUEST_COUNT = Counter('flask_requests_total', 'Total requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Gauge('flask_request_latency_seconds', 'Request latency', ['endpoint'])

@app.route('/metrics')
def metrics():
    return Response(generate_latest(), mimetype='text/plain')
```

**Логирование в structured формате:**

```python
import logging
import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName
        })

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)
```

**Проверка логов в Docker:**
```bash
# Просмотр логов контейнера
docker logs -f python-app
# → {"timestamp":"2026-08-25 10:30:00","level":"INFO","message":"Running on http://0.0.0.0:5000"}

# Проверка HEALTHCHECK статуса
docker inspect --format='{{json .State.Health}}' python-app
```

**Мониторинг инфраструктуры GitLab (Self-hosted):**
```bash
# Статус всех компонентов GitLab
gitlab-ctl status

# Проверка конкретных сервисов
gitlab-ctl status postgresql
gitlab-ctl status redis
gitlab-ctl status gitaly
gitlab-ctl status sidekiq

# Просмотр логов Gitaly
gitlab-ctl tail gitaly

# Проверка очереди Sidekiq
curl -s http://gitlab.example.com/-/sidekiq/queues | jq
```

### Смотрите также

*   **[Комплексный Pipeline для Python](./python_project_pipeline_guide.md)** — продвинутые сценарии с SAST, Helm и расширенным тестированием.
*   **[Dockerfile: Лучшие практики для Python](../../../Docker/Dockerfile/Docker_best_practices/python.md)** — глубокая оптимизация слоев и кэширования.
*   **[Регистрация GitLab Runner](./runner_registration.md)** — подробности настройки Docker Executor.
