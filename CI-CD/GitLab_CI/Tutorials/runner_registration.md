# Регистрация GitLab Runner

**Актуально для:** GitLab Runner 19.3.x / GitLab 19.3.x

## Определения

**GitLab Runner** — агент (приложение на Go), который опрашивает сервер GitLab на наличие заданий (jobs), выполняет их и возвращает результат (логи, артефакты). Runner работает по принципу исходящих соединений (Pull-модель) и не требует входящего доступа извне.

**Executor (Исполнитель)** — компонент Runner, определяющий изолированную среду выполнения задания (Docker, Shell, Kubernetes, VirtualBox). Подробнее см. **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)**.

**Runner Manager** — экземпляр службы `gitlab-runner`, запущенный на конкретном хосте. Один менеджер может управлять несколькими зарегистрированными раннерами через один файл конфигурации.

**Authentication Token (`glrt-`)** — уникальный секрет с префиксом `glrt-` (например, `glrt-t1_xxxx`). Начиная с GitLab 16.0, это основной способ регистрации. Токен привязан к конкретной конфигурации раннера, созданной в интерфейсе GitLab. Устаревшие Registration Token отключены по умолчанию в GitLab 17.0+ и будут удалены в GitLab 20.0.

**Runner Registration Token (deprecated)** — общий токен для проекта/группы/инстанса. Устарел в пользу `glrt-`. Приведет к ошибке `410 Gone`, если legacy-регистрация отключена администратором.

**Protected Runner** — раннер, который запускает задачи только из защищенных веток или тегов. Используется для секретных окружений (production).

**Paused Runner** — раннер, который не принимает новые задачи, но остается зарегистрированным. Используется дляplanned maintenance.

**Locked Runner** — раннер, привязанный к конкретному проекту. Недоступен для других проектов даже в той же группе.

**Limit** — максимальное количество задач, которое раннер может выполнять одновременно (`limit` в `config.toml`). По умолчанию `0` (без ограничения, до глобального `concurrent`).

## Основные концепции (GitLab 19.x)

### Жизненный цикл регистрации

1.  **Декларация:** Вы создаете запись о раннере в интерфейсе GitLab (Admin, Group или Project). Здесь вы заранее определяете теги, executor, protected-статус и описание.
2.  **Токенизация:** GitLab генерирует `glrt-` токен. Он отображается один раз и является единственным ключом для связки локального менеджера с серверной записью.
3.  **Связывание:** Вы запускаете `register` на целевой машине, передавая URL сервера и `glrt-` токен. Локальные настройки (executor, volumes) дополняют серверную конфигурацию.
4.  **Валидация:** После регистрации Runner начинает опрашивать GitLab API (`POST /api/v4/jobs/request`) и появляется в списке со статусом `online`.

### Версионная совместимость

| GitLab Runner | GitLab Server | Статус |
| :--- | :--- | :--- |
| 19.x | 19.x | Текущий стабильный. Полная поддержка Fleeting/Taskscaler. |
| 18.x | 18.x+ | Поддержка. Registration Token отключен по умолчанию. |
| 17.x | 17.x | Устаревший. Требуется `--token` с `glrt-`. |
| 16.x | 16.x | Legacy. Registration Token еще доступен, но deprecated. |

> **Важно:** Runner должен быть не более чем на одну мажорную версию старше GitLab Server. При несовместимости возможны ошибки в API-запросах и логировании.

### Архитектура Runner Manager vs Executor

**Runner Manager** — процесс-демон (`gitlab-runner`), который:
- Регистрируется на GitLab-сервере через API
- Опрашивает сервер на наличие задач (polling)
- Управляет жизненным циклом задач
- Управляет конфигурацией из `config.toml`

**Executor** — модуль внутри Manager, который определяет **как** будет выполнена задача:
- Создает изолированную среду (контейнер, ВМ, Pod)
- Запускает скрипты задачи
- Управляет ресурсами (CPU, память, диск)
- Уничтожает среду после выполнения

Один Manager может иметь несколько секций `[[runners]]` с разными executor'ами.

## Предварительные требования (Prerequisites)

### Аппаратные ресурсы

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| **RAM** | 4 ГБ | 8 ГБ+ для Docker/Kubernetes executor |
| **CPU** | 2 ядра | 4 ядра+ для параллельных задач |
| **Диск** | 20 ГБ SSD | 50 ГБ+ SSD для кэша и артефактов |

### Программное обеспечение

| Компонент | Минимум | Рекомендация | Проверка |
| :--- | :--- | :--- | :--- |
| **GitLab Runner** | 19.0 | 19.3.x | `gitlab-runner --version` |
| **Docker Engine** | 24.0 | 27.0 | `docker --version` |
| **GitLab Server** | 19.0 | 19.3.x | `curl https://gitlab.example.com/api/v4/version` |

### Установка gitlab-runner

#### Linux (Debian/Ubuntu)

```bash
# Добавление репозитория
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash

# Установка
sudo apt-get install gitlab-runner

# Проверка версии
gitlab-runner --version
# → Version:      19.3.1
```

#### Linux (RHEL/CentOS/Fedora/Rocky)

```bash
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.rpm.sh" | sudo bash
sudo dnf install gitlab-runner
# или sudo yum install gitlab-runner
```

#### Docker (как контейнер)

```bash
# Регистрация через временный контейнер
docker run --rm -it \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  gitlab/gitlab-runner:alpine-v19.3.1 register \
    --non-interactive \
    --url "https://gitlab.example.com/" \
    --token "glrt-YOUR_TOKEN" \
    --executor "docker" \
    --docker-image "alpine:latest"
```

### Проверка после установки

```bash
# Статус службы
sudo gitlab-runner status
# → gitlab-runner: Service is running

# Список зарегистрированных раннеров
sudo gitlab-runner list
# → Runner:  abc12345...  https://gitlab.example.com/ ...  executor=docker

# Проверка связи с сервером
sudo gitlab-runner verify
# → Verifying runner... is alive                        runner=abc12345

# Диагностика (детальный скрипт)
# См. раздел "Диагностический скрипт" в [Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)
```

## Практические сценарии

### Сценарий 1: Регистрация с Docker Executor (Рекомендуемый)

Этот сценарий предполагает запуск раннера в Docker-контейнере для изоляции процессов сборки.

#### 1. Создание в интерфейсе GitLab

1.  Перейдите в **Settings > CI/CD > Runners** (или **Admin Area > Runners** для общего раннера).
2.  Нажмите **New project runner**.
3.  Выберите платформу (`Linux`) и укажите **Tags** (например, `docker, nodejs`).
4.  Нажмите **Create runner** и скопируйте токен `glrt-...`.

#### 2. Выполнение регистрации (One-off container)

Используйте временный контейнер для генерации `config.toml`:

```bash
docker run --rm -it \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  gitlab/gitlab-runner:alpine-v19.3.1 \
  register \
    --non-interactive \
    --url "https://gitlab.example.com/" \
    --token "glrt-YOUR_TOKEN_HERE" \
    --executor "docker" \
    --docker-image "alpine:latest" \
    --docker-volumes "/var/run/docker.sock:/var/run/docker.sock" \
    --docker-network-mode "bridge"
```

#### 3. Запуск постоянного сервиса

```bash
docker run -d --name gitlab-runner --restart always \
  -v /srv/gitlab-runner/config:/etc/gitlab-runner \
  -v /var/run/docker.sock:/var/run/docker.sock \
  gitlab/gitlab-runner:alpine-v19.3.1
```

---

### Сценарий 2: Регистрация на Linux/macOS/Windows (Shell Executor)

Подходит для задач, требующих прямого доступа к ресурсам хоста (например, для сборки системных пакетов, доступа к локальному железу).

#### Linux/macOS

```bash
# Регистрация
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "glrt-YOUR_TOKEN_HERE" \
  --executor "shell"

# Проверка статуса
sudo gitlab-runner status
# → gitlab-runner: Service is running
```

#### Windows (PowerShell Core)

```powershell
# Регистрация (от имени Administrator)
gitlab-runner register `
  --non-interactive `
  --url "https://gitlab.example.com/" `
  --token "glrt-YOUR_TOKEN_HERE" `
  --executor "shell" `
  --shell "pwsh"

# Проверка статуса
gitlab-runner status
```

> **Примечание:** Для Windows используйте `pwsh` (PowerShell Core). Docker executor на Windows поддерживает только Windows-контейнеры через Docker Desktop. Многие Linux-образы для CI/CD несовместимы с Windows-контейнерами.

---

### Сценарий 3: Массовая регистрация через API (IaC)

Для автоматизации через Ansible, Terraform или скрипты используйте GitLab API. Требуется Personal Access Token (PAT) с правами `api`.

```bash
# 1. Создание записи раннера через API
RESPONSE=$(curl --request POST "https://gitlab.example.com/api/v4/user/runners" \
     --header "PRIVATE-TOKEN: ${GITLAB_PAT}" \
     --data "runner_type=project_type" \
     --data "project_id=42" \
     --data "tag_list=autoscale,high-cpu" \
     --data "description=API-Registered-Runner")

# 2. Извлечение токена
AUTH_TOKEN=$(echo $RESPONSE | jq -r .token)

# 3. Регистрация на узле
gitlab-runner register --non-interactive --url "https://gitlab.example.com/" --token "$AUTH_TOKEN" --executor "docker" --docker-image "ruby:3.2"
```

---

### Сценарий 4: Использование шаблонов конфигурации (--template-config)

Если вам нужно применить сложные настройки (например, лимиты памяти в Docker или настройки кэширования) при регистрации множества раннеров, используйте файл-шаблон.

**Файл `template.toml`:**
```toml
[[runners]]
  [runners.docker]
    memory = "4g"
    cpus = "2"
    privileged = false
  [runners.cache]
    Type = "s3"
    Path = "shared-cache"
    [runners.cache.s3]
      ServerAddress = "minio.internal:9000"
      BucketName = "my-gitlab-cache"
```

**Команда регистрации:**
```bash
gitlab-runner register \
  --token "glrt-..." \
  --url "https://gitlab.com/" \
  --template-config /path/to/template.toml \
  --executor "docker"
```

---

### Сценарий 5: Регистрация с Docker-in-Docker (DinD)

Для сборки Docker-образов внутри задач пайплайна.

#### 1. Конфигурация Runner

```bash
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "glrt-YOUR_TOKEN" \
  --executor "docker" \
  --docker-image "docker:27.0" \
  --docker-privileged \
  --docker-volumes "/var/run/docker.sock:/var/run/docker.sock" \
  --description "DinD Runner"
```

#### 2. config.toml (финальная конфигурация)

```toml
[[runners]]
  name = "dind-runner"
  url = "https://gitlab.example.com/"
  token = "glrt-..."
  executor = "docker"

  [runners.docker]
    image = "docker:27.0"
    privileged = true
    volumes = ["/var/run/docker.sock:/var/run/docker.sock"]
    allowed_images = ["docker:*", "alpine:*"]
    pull_policy = "if-not-present"
```

#### 3. Пример задачи .gitlab-ci.yml

```yaml
build_image:
  stage: build
  image: docker:27.0
  services:
    - docker:27.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
    DOCKER_TLS_CERTDIR: ""
  script:
    - docker build -t myapp:$CI_COMMIT_SHA .
    - docker push myapp:$CI_COMMIT_SHA
  tags:
    - dind-runner
```

> **Безопасность:** `privileged = true` дает Runner'у полный доступ к ядру хоста. Для production используйте **Kaniko** или **BuildKit без привилегий**. Подробнее см. **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)**.

---

### Сценарий 6: Регистрация Group Runner (Групповой раннер)

Доступен всем проектам внутри группы. Идеален для общих стандартов CI/CD.

#### 1. Создание в интерфейсе GitLab

1.  Перейдите в **Group > Settings > CI/CD > Runners**.
2.  Нажмите **New group runner**.
3.  Укажите теги и настройки (например `group-runner, docker`).
4.  Скопируйте `glrt-` токен.

#### 2. Регистрация на хосте

```bash
sudo gitlab-runner register \
  --non-interactive \
  --url "https://gitlab.example.com/" \
  --token "glrt-YOUR_GROUP_TOKEN" \
  --executor "docker" \
  --docker-image "alpine:latest" \
  --description "Group Runner for my-group"
```

#### 3. Проверка доступности

```bash
sudo gitlab-runner list
# → Runner:  xyz789...  https://gitlab.example.com/ ...  executor=docker
```

Все проекты группы `my-group` теперь могут использовать этот раннер (тег: `group-runner`).

---

### Сценарий 7: Регистрация с Kubernetes Executor

Для работы в кластере Kubernetes. Подробнее см. **[Установка GitLab Runner в Kubernetes](../../../Kubernetes/Installation/gitlab_runner_kubernetes_installation.md)**.

#### 1. Через Helm (рекомендуется)

```bash
helm repo add gitlab https://charts.gitlab.io
helm repo update

helm install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runners \
  --create-namespace \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerToken=glrt-YOUR_TOKEN \
  --set runners.executor=kubernetes \
  --set runners.image=ubuntu:24.04 \
  --set runners.namespace=gitlab-runners \
  --set runners.cpu_limit=1 \
  --set runners.memory_limit=2Gi
```

#### 2. config.toml (сгенерированный)

```toml
[[runners]]
  name = "k8s-runner"
  url = "https://gitlab.example.com/"
  token = "glrt-..."
  executor = "kubernetes"

  [runners.kubernetes]
    image = "ubuntu:24.04"
    namespace = "gitlab-runners"
    cpu_limit = "1"
    memory_limit = "2Gi"
    service_cpu_limit = "500m"
    service_memory_limit = "1Gi"
    helper_image = "registry.gitlab.com/gitlab-org/gitlab-runner/gitlab-runner-helper:x86_64-v19.x.x"
    poll_timeout = 600

  [runners.cache]
    Type = "s3"
    Shared = true
    [runners.cache.s3]
      ServerAddress = "minio.internal:9000"
      BucketName = "gitlab-runner-cache"
      BucketLocation = "us-east-1"
      Insecure = false
```

---

### Сценарий 8: Автоматизация через Ansible (IaC)

Для массового развёртывания раннеров в инфраструктуре.

```yaml
# roles/gitlab-runner/tasks/main.yml
---
- name: Установка gitlab-runner
  ansible.builtin.package:
    name: gitlab-runner
    state: present

- name: Регистрация раннера
  ansible.builtin.command: >
    gitlab-runner register
    --non-interactive
    --url "{{ gitlab_url }}"
    --token "{{ gitlab_runner_token }}"
    --executor "{{ runner_executor }}"
    --docker-image "{{ runner_docker_image }}"
    --description "{{ runner_description }}"
    --tag-list "{{ runner_tags }}"
  args:
    creates: /etc/gitlab-runner/config.toml
  no_log: true

- name: Настройка config.toml
  ansible.builtin.template:
    src: config.toml.j2
    dest: /etc/gitlab-runner/config.toml
    owner: gitlab-runner
    group: gitlab-runner
    mode: "0600"
  notify: restart gitlab-runner

- name: Включение автозапуска
  ansible.builtin.service:
    name: gitlab-runner
    enabled: true
    state: started
```

---

### Сценарий 9: Настройка кэширования (S3/MinIO)

Для распределённого кэша между несколькими раннерами. В качестве бэкенда можно использовать MinIO (self-hosted S3-совместимое хранилище) или любое другое S3-совместимое решение.

```toml
[[runners]]
  name = "cached-runner"
  url = "https://gitlab.example.com/"
  token = "glrt-..."
  executor = "docker"

  [runners.docker]
    image = "alpine:latest"

  [runners.cache]
    Type = "s3"
    Shared = true
    Path = "runner-cache"
   [runners.cache.s3]
      ServerAddress = "minio.internal:9000"
      BucketName = "gitlab-cache"
      BucketLocation = "us-east-1"
      Insecure = false
```

#### Проверка кэширования

```bash
# Очистка кэша через UI
# Settings > CI/CD > Runners > Clear runner caches

# Или через API
curl --request DELETE --header "PRIVATE-TOKEN: $PAT" \
  "https://gitlab.example.com/api/v4/runners/{id}/cache"
```

---

### Сценарий 10: Настройка Monitoring (Prometheus)

Для сбора метрик работы раннеров.

```toml
# /etc/gitlab-runner/config.toml
listen_address = ":9252"  # Порт для Prometheus

[[runners]]
  name = "monitored-runner"
  url = "https://gitlab.example.com/"
  token = "glrt-..."
  executor = "docker"
```

#### Пример scrape-конфигурации Prometheus

```yaml
scrape_configs:
  - job_name: "gitlab-runner"
    static_configs:
      - targets: ["runner-host:9252"]
    metrics_path: /metrics
```

#### Ключевые метрики

| Метрика | Описание |
| :--- | :--- |
| `gitlab_runner_concurrent` | Текущее количество запущенных задач |
| `gitlab_runner_errors_total` | Количество ошибок связи с GitLab |
| `gitlab_runner_jobs_total` | Общее количество задач по статусам |
| `gitlab_runner_version` | Версия Runner |

---

### Сценарий 11: Регистрация Windows Runner (Shell/PowerShell)

Для задач, требующих Windows-среды (`.NET Framework`, PowerShell-скрипты, Windows-specific тесты).

```powershell
# Регистрация на Windows хосте
gitlab-runner register `
  --non-interactive `
  --url "https://gitlab.example.com/" `
  --token "glrt-YOUR_TOKEN_HERE" `
  --executor "shell" `
  --shell "pwsh" `
  --tag-list "windows,pwsh" `
  --description "Windows Runner"
```

**Ограничения Windows Runner:**
- Нет `services` (sidecar-контейнеры)
- Нет `docker-autoscaler` (Fleeting не поддерживает Windows-инстансы)
- Docker Desktop требует Linux-контейнеров через WSL2 для совместимости с большинствами CI/CD-образов

## После регистрации: Структура config.toml

После успешной регистрации в файле `/etc/gitlab-runner/config.toml` появляется блок `[[runners]]`.

*   **`concurrent`**: Глобальный лимит одновременно выполняемых задач на этом менеджере.
*   **`check_interval`**: Частота опроса сервера GitLab (в секундах).
*   **`token`**: Здесь хранится ваш `glrt-` токен. Никогда не передавайте его третьим лицам.
*   **`executor`**: Выбранный тип среды выполнения.
*   **`limit`**: Максимальное количество задач для этого runner'а (0 = без ограничения).
*   **`protected`**: Запускать только из защищенных веток/тегов.
*   **`tag_list`**: Теги для маршрутизации задач.
*   **`pull_policy`**: Определяет, когда Runner скачивает Docker-образ. Значение `["if-not-present"]` предотвращает повторное скачивание неизменяемых образов при каждом запуске задачи.
*   **`pre_clone_script`**: Команды, выполняемые перед клонированием репозитория.
*   **`post_build_script`**: Команды, выполняемые после завершения задачи.

### Пример multi-runner конфигурации

```toml
concurrent = 20
check_interval = 3

[session_server]
  listen_address = "[::]:8093"

[[runners]]
  name = "docker-fast"
  executor = "docker"
  tags = ["fast", "docker"]
  limit = 10
  [runners.docker]
    image = "ubuntu:24.04"
    memory = "2g"
    cpus = "1"

[[runners]]
  name = "shell-system"
  executor = "shell"
  tags = ["system", "admin"]
  limit = 5
  protected = true
```

## Граничные случаи

| Сценарий | Описание | Рекомендация |
| :--- | :--- | :--- |
| **Большой инвентарь** | Регистрация 50+ раннеров через API | Используйте пагинацию GitLab API и идемпотентность (`creates` в Ansible) |
| **Дрейф конфигурации** | `config.toml` изменен вручную | Используйте Infrastructure as Code (Ansible/Terraform) для управления конфигом |
| **SSH-agent forwarding в DinD** | Задача внутри DinD не имеет доступа к SSH-агенту хоста | Монтируйте `SSH_AUTH_SOCK` или используйте `forward_agent` в `config.toml` |
| **Vault + ephemeral runners** | Секреты Vault привязаны к runner'у, который удаляется после задачи | Используйте OIDC (`id_tokens`) вместо статических токенов |
| **Windows + Docker** | Docker Desktop на Windows не поддерживает Linux-контейнеры в production | Используйте отдельный Linux-раннер или WSL2 backend |
| **Высокая нагрузка на API** | 100+ раннеров опрашивают GitLab одновременно | Увеличьте `check_interval` и используйте `limit` на каждом runner'е |
| **Обновление во время деплоя** | Runner обновляется, а задачи в выполнении | Используйте rolling update: остановите приём (`gitlab-runner stop`), дождитесь завершения, обновите, запустите |
| **Сетевые разрывы** | Runner теряет связь с GitLab на время выполнения задачи | Задачи завершатся с таймаутом. Настройте `request_concurrency` и `check_interval` |

## Валидация и проверка

После регистрации выполните следующие проверки:

```bash
# 1. Версия Runner
gitlab-runner --version
# → Version: 19.3.1

# 2. Статус службы
sudo gitlab-runner status
# → active (running)

# 3. Список зарегистрированных раннеров
sudo gitlab-runner list
# → Runner: abc12345... executor=docker tags=[docker, build]

# 4. Верификация связи
sudo gitlab-runner verify
# → Verifying runner... is alive

# 5. Проверка в UI
# Admin > CI/CD > Runners > Runner должен быть online

# 6. Тестовый запуск задачи
# Создайте .gitlab-ci.yml с тегом runner'а и запустите pipeline

# 7. Логи Runner'а
journalctl -u gitlab-runner -f
# → Listening for jobs
```

## Очистка

```bash
# Остановка службы
sudo gitlab-runner stop

# Удаление раннера из GitLab (через UI или API)
# Admin > CI/CD > Runners > Delete

# Удаление конфигурации
sudo rm -rf /etc/gitlab-runner

# Очистка Docker-образов и контейнеров (для Docker executor)
docker system prune -af

# Удаление кэша
# Settings > CI/CD > Runners > Clear runner caches

# Удаление Runner из Kubernetes (если использовался Helm)
helm uninstall gitlab-runner -n gitlab-runners
kubectl delete namespace gitlab-runners
```

## Решение проблем (Troubleshooting)

| Симптом / Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **410 Gone** | Попытка регистрации через устаревший Registration Token | Используйте `glrt-` токен, созданный в UI GitLab 16.0+. |
| **403 Forbidden** | PAT не имеет прав `api` или пользователь не владелец проекта | Проверьте Scope у токена и права доступа в GitLab. |
| **Runner is Offline в UI** | Служба `gitlab-runner` не запущена на хосте | Выполните `gitlab-runner run` или проверьте `systemctl status`. |
| **Certificate verify failed** | Самоподписанный сертификат GitLab | Добавьте `--tls-ca-file` или импортируйте CA в доверенные системные. |
| **glrt- token not found** | Токен был удален в UI GitLab | Создайте новый раннер в UI и выполните перерегистрацию. |
| **New runner token is invalid** | Использование `--registration-token` вместо `--token` (v16.0+) | Замените флаг на `--token` и передайте `glrt-` токен. |
| **Job failed (system failure)** | Проблема инфраструктуры Runner (Docker dead, Disk full) | Проверьте `journalctl -u gitlab-runner` на хосте Runner. |
| **Connection refused (Docker)** | Runner не имеет прав на `/var/run/docker.sock` | Добавьте пользователя `gitlab-runner` в группу `docker` или проверьте `privileged` mode. |
| **Entrypoint issues** | Конфликт `ENTRYPOINT` образа и команд GitLab CI | Переопределите `entrypoint: [""]` в определении образа в YAML. |
| **Job timeout** | Превышен лимит времени выполнения | Увеличьте `timeout` в настройках проекта или в `config.toml` Runner'а. |
| **OOM (Out of Memory)** | Задача падает с `Exit code 137` | Увеличьте `memory_limit` в `[runners.docker]` или `[runners.kubernetes]`. |
| **No space left on device** | Runner не может скачать образ или создать временные файлы | Очистите старые контейнеры: `docker system prune -af`. |
| **Failed to pull helper image** | Runner не может скачать вспомогательный образ | Проверьте доступ к `registry.gitlab.com` или настройте `helper_image`. |
| **Stuck in Pending** | Нет раннеров с соответствующими тегами или достигнут лимит `concurrent` | Проверьте `tags` в `.gitlab-ci.yml` и `concurrent`/`limit` в `config.toml`. |
| **Cache download failed** | Истек срок действия pre-signed URL или неверные credentials | Проверьте NTP-синхронизацию и доступ к кэш-бакету. |
| **Permission Denied (cache)** | Неверные права доступа к кэш-бакету | Проверьте `config.toml` Runner'а. Для S3-совместимого хранилища нужны права `s3:PutObject` и `s3:GetObject`. |
| **exec format error** | Несоответствие архитектуры образа (arm64) и хоста (amd64) | Используйте multi-arch образы или QEMU. |
| **Runner is locked and assigned to project** | Runner привязан к конкретному проекту | Переключите на Group/Instance scope или создайте новый runner. |
| **Windows: Git not found** | Git for Windows не установлен или не в PATH | Установите Git for Windows и добавьте в системный PATH. |

## Дополнительная информация

### Уровни раннеров

1.  **Shared (Общие):** Доступны всем проектам (настраиваются в Admin Area).
2.  **Group (Групповые):** Доступны всем проектам внутри конкретной группы.
3.  **Project (Проектные):** Привязаны к одному конкретному репозиторию.

### Безопасность

*   **Protected Runners:** Включайте эту опцию в UI для раннеров, имеющих доступ к продакшн-секретам. Такие раннеры будут запускать задачи только из защищенных веток/тегов.
*   **Runtime Isolation:** Для недоверенного кода всегда используйте Docker или Kubernetes Executor вместо Shell.
*   **Ротация токенов:** Регулярно обновляйте `glrt-` токены через UI GitLab (Settings > CI/CD > Runners > Edit > Rotate authentication token).
*   **Masked Variables:** Используйте Masked Variables для секретов — они заменяются на `[masked]` в логах Runner'а.
*   **OIDC (id_tokens):** Для аутентификации во внешних сервисах (Vault, внутренние системы) используйте временные JWT-токены вместо статических ключей.
*   **Allowed Images:** В `config.toml` ограничьте список разрешенных Docker-образов для предотвращения запуска вредоносного кода.
*   **Аудит:** Каждая регистрация и выполнение задачи логируется GitLab (Admin > Audit Events). Проверяйте логи регулярно.

### Смотрите также

*   **[Обзор GitLab Runner и Executor](../Advanced/gitlab_ci_runners_executors.md)** — архитектура, типы Executor'ов и оптимизация config.toml.
*   **[GitLab Runner в Docker Compose](./gitlab_runner_docker_compose.md)** — развертывание полного стека локально.
*   **[Отладка и устранение неполадок](../Advanced/debugging_and_troubleshooting.md)** — диагностика Runner'ов и пайплайнов.
