# Обзор GitLab Runner и Executor

**Актуально для:** GitLab CI/CD 17.x–19.4, GitLab Runner 17.x–19.4

## Определения

**[GitLab Runner](https://docs.gitlab.com/runner/)** — агент (приложение на Go), предназначенный для выполнения заданий (jobs) CI/CD пайплайнов. Он работает по Pull-модели: опрашивает сервер GitLab через API, получает описание задачи, исполняет её в изолированной среде и возвращает логи и артефакты.

**Executor (Исполнитель)** — изолированный модуль внутри Runner, который определяет технологию создания среды выполнения (контейнер, виртуальная машина или сессия в ОС).

**Authentication Token (`glrt-`)** — современный стандарт безопасности (введен в GitLab 16.0), заменяющий устаревшие регистрационные токены. Токен создается на стороне сервера и жестко привязывает Runner к области видимости (Project/Group/Instance), исключая возможность несанкционированного изменения конфигурации агентом.

**[Fleeting & Taskscaler](https://docs.gitlab.com/runner/executors/docker_autoscaler.md)** — архитектура автоскейлинга нового поколения (стандарт с GitLab 17.0+):
-   **Fleeting**: Библиотека управления эфемерной инфраструктурой. Через плагины взаимодействует с API оркестраторов (libvirt/KVM, Proxmox, VMware vSphere), обеспечивая создание и удаление узлов по требованию.
-   **Taskscaler**: Высокоуровневый планировщик, который распределяет задачи по инстансам Fleeting, учитывая их загрузку и жизненный цикл.
-   **Преимущество**: Полный уход от устаревшего `docker-machine` в пользу нативных API виртуализации для масштабирования раннеров.

## Предварительные требования

### Версии и поддерживаемые функции

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| GitLab Runner | 17.x (рекомендуется 19.4+) | ±1 мажорная версия от GitLab Server |
| `shell` executor | Все версии | Стандарт для macOS/iOS, Windows (pwsh/cmd) |
| `docker` executor | Все версии | Требует Docker Engine 20.10+ |
| `instance` executor | GitLab 16.0+ | Полная изоляция по ВМ на задачу |
| `docker-autoscaler` | GitLab 17.0+ | Fleeting + плагин виртуализации (libvirt/VMware/Proxmox) |
| `glrt-` токен | GitLab 16.0+ | Заменяет устаревшие registration tokens |
| `metrics_server` | GitLab Runner 16.0+ | Включение через `listen_address` или `metrics_server` в config.toml |

### Инфраструктурные требования

-   **GitLab Server**: Self-hosted (on-prem) инстанс GitLab 17.x–19.4 с доступным API
-   **RBAC**: Роль `Maintainer`/`Owner` для регистрации Runner'ов; `Developer` для запуска задач
-   **Сеть**: Runner'ы должны иметь доступ к GitLab API (исходящие HTTPS); входящие соединения не требуются (Pull-модель)
-   **TLS**: GitLab Server должен работать по HTTPS с валидным сертификатом (не self-signed в production)
-   **NTP**: Синхронизация времени между GitLab Server и Runner'ами — критична для проверки JWT-подписи
-   **Хранилище**: Достаточное место для артефактов, кэша и логов; рекомендуется отдельный диск для `/var/lib/gitlab-runner`
-   **Виртуализация** (для Fleeting): KVM/libvirt, VMware vSphere или Proxmox на гипервизорах

### Необходимые знания

-   YAML: синтаксис, вложенность
-   Docker: образы, volumes, сети, DinD/DooD
-   Linux systemd: управление сервисами, логирование (journalctl)
-   GitLab RBAC: роли, области видимости, protected branches
-   REST API: аутентификация, пагинация
-   HMAC-SHA256: принципы подписи вебхуков (если используется)

## Жизненный цикл задачи (Job Lifecycle)

1.  **Request (Запрос)**: Runner отправляет запрос `POST /api/v4/jobs/request` с указанием своих тегов и возможностей.
2.  **Pickup (Прием)**: Если есть подходящее задание, GitLab передает Runner'у спецификацию (скрипты, переменные, зависимости).
3.  **Preparation (Подготовка)**: Executor создает среду (поднимает контейнер или виртуальную машину).
4.  **Execution (Выполнение)**:
    -   `pre_clone_script` (если задан) — выполнение команд до клонирования Git.
    -   `git clone` и загрузка артефактов/кэша.
    -   `pre_build_script` — подготовка окружения.
    -   `script` — выполнение основной логики задачи.
    -   `post_build_script` — действия после основного скрипта.
5.  **Finalization (Завершение)**: Выгрузка артефактов и кэша, отправка финального лога и статуса (Success/Failed).
6.  **Cleanup (Очистка)**: Executor уничтожает временную среду.

### Особенности Windows Runner

Windows-раннеры имеют ряд специфических ограничений и требований:

| Параметр | Windows | Linux/macOS |
|:---|:---|:---|
| **Shell executor** | `pwsh` (PowerShell Core) или `cmd` | `bash` |
| **Docker executor** | Docker Desktop (Windows containers) или Linux-контейнеры через WSL2 | Docker Engine |
| **Клонирование Git** | Требуется Git for Windows в PATH | Нативный git |
| **Переменные среды** | Case-insensitive, `%VAR%` или `$env:VAR` | Case-sensitive, `$VAR` |
| **Разделители путей** | `\` (обратный слэш) | `/` (прямой слэш) |
| **Скрипты** | `.ps1` (PowerShell) или `.bat` (cmd) | `.sh` (bash) |

**Конфигурация Windows Runner (config.toml):**
```toml
[[runners]]
  name = "windows-runner"
  executor = "shell"
  shell = "pwsh"  # PowerShell Core (рекомендуется)
  tags = ["windows", "pwsh"]
  [runners.docker]
    # Если используется Docker Desktop
    image = "mcr.microsoft.com/windows/servercore:ltsc2022"
```

**Ограничения Windows Runner:**
-   **Нет `services`**: Windows Docker не поддерживает Docker Compose-style services (нет PostgreSQL/Redis sidecar)
-   **Нет `docker-autoscaler`**: Fleeting не поддерживает Windows-инстансы для автоскейлинга
-   **Ограниченная совместимость**: Многие CI/CD-образы (Ubuntu-based) не работают в Windows-контейнерах
-   **Память**: Windows-контейнеры потребляют больше памяти, чем Linux-аналоги
-   **Рекомендация**: Используйте Windows runner только для задач, требующих Windows-среды (.NET Framework, Windows-specific тесты)

## Типы Runner и Executor

### Область видимости (Scope)

| Тип | Настройка | Область применения | Безопасность |
| :--- | :--- | :--- | :--- |
| **Shared** | Admin Area | Доступен всему инстансу. Идеален для общих утилит и маленьких проектов. | Низкая (требует строгой изоляции джоб). |
| **Group** | Group Settings | Доступен всем подгруппам и проектам группы. Подходит для корпоративных стандартов. | Средняя. |
| **Project** | Project Settings | Привязан к конкретному репозиторию. Для критичных задач и специфического железа. | Высокая. |

### Сравнение Executor'ов

| Executor | Изоляция | Масштабирование | Использование |
| :--- | :--- | :--- | :--- |
| **`shell`** | Отсутствует | Нет | Локальные системные задачи, доступ к GPU/HW напрямую. **Стандарт для macOS/iOS сборок.** |
| **`docker`** | Высокая | Вертикальное (на хосте) | Стандарт индустрии. Использование образов из Docker Hub/Harbor. |
| **`kubernetes`** | Высокая | Горизонтальное (Cluster) | **Не рекомендуется** для новых on-prem развёртываний. Требует полного стека Kubernetes, что добавляет сложность. Для on-prem используйте `docker` или `instance` executor'ы. |
| **`docker-autoscaler`** | Высокая | Динамическое (Fleeting) | Современный автоскейлинг через API оркестраторов (libvirt, VMware, Proxmox). Замена `docker+machine`. |
| **`instance`** | Полная (VM) | Динамическое (Fleeting) | Максимальная изоляция (по ВМ на каждую задачу). Подходит для high-trust сред. |
| **`custom`** | Любая | Любое | Использование сторонних инструментов (например, Podman или LXC) через драйвер. |

### Kubernetes Executor: Архитектура Pod'а задания

При использовании `kubernetes` executor'а GitLab Runner создаёт для каждой задачи отдельный Pod в Kubernetes-кластере. Pod состоит из трёх основных контейнеров:

| Контейнер | Роль | Описание |
| :--- | :--- | :--- |
| **`helper`** | Вспомогательный | Загружает артефакты, кэш, клонирует репозиторий, подготавливает окружение. Образ: `registry.gitlab.com/gitlab-org/gitlab-runner/gitlab-runner-helper:<runner-version>`. |
| **`build`** | Основной | Выполняет пользовательские скрипты из `.gitlab-ci.yml` (секция `script`). Образ задаётся в `image` или `default.image`. |
| **`service-*`** | Сервисные (sidecar) | Запускаются для каждого элемента в блоке `services` (БД, кэш, очереди). Каждый сервис — отдельный контейнер в том же Pod, доступен по `localhost` или имени сервиса. |

**Важные нюансы:**
- Все контейнеры разделяют сетевой namespace (один IP, `localhost`), volumes (`emptyDir` для кэша/артефактов) и PVC.
- `helper` всегда запускается первым и завершается последним (выгружает артефакты/кэш).
- Для сборки Docker-образов внутри Kubernetes executor **не используйте DinD** (`privileged: true`). Рекомендуется **Kaniko** (сборка без Docker-демона) или **BuildKit** с `docker-out-of-docker` (DooD) через монтирование сокета на узле, где запущен Runner Manager.

**Пример конфигурации Kubernetes executor в `config.toml`:**
```toml
[[runners]]
  name = "k8s-runner"
  executor = "kubernetes"
  [runners.kubernetes]
    namespace = "gitlab-runners"
    image = "ubuntu:24.04"
    cpu_limit = "2000m"
    memory_limit = "4Gi"
    service_cpu_limit = "500m"
    service_memory_limit = "1Gi"
    helper_cpu_limit = "500m"
    helper_memory_limit = "256Mi"
    # Для Kaniko:
    [runners.kubernetes.volumes.empty_dir]
      name = "kaniko-cache"
      mount_path = "/cache"
```

### Runner Tags: конфигурация и логика сопоставления

**Tags** — ключевые слова, присваиваемые раннерам для маршрутизации задач. Пайплайн запускается на том раннере, чьи теги совпадают с тегами, указанными в задаче.

**Синтаксис тегов в config.toml:**
```toml
[[runners]]
  name = "build-runner"
  executor = "docker"
  tags = ["build", "linux", "docker"]

[[runners]]
  name = "deploy-runner"
  executor = "shell"
  tags = ["deploy", "production"]
```

**Синтаксис тегов в .gitlab-ci.yml:**
```yaml
# Задача запустится только на раннере с тегом "build"
build:app:
  tags: [build]
  script: ./build.sh

# Задача запустится только на раннере с тегами "deploy" И "production"
deploy:prod:
  tags: [deploy, production]
  script: ./deploy.sh
```

**Логика сопоставления (tag matching):**
-   **AND-логика**: Если у задачи несколько тегов — раннер должен иметь **все** указанные теги
-   **OR-логика**: Если у раннера несколько тегов — задача с **любым** из этих тегов может на нём выполниться
-   **Пустые теги**: Задача без `tags` запустится на **любом** доступном раннере (включая shared)
-   **Приоритет**: Если несколько раннеров подходят — GitLab выбирает тот, который дольше не выполнял задач (FIFO-очередь)

**Runners without tags (tagless runners):**
```toml
[[runners]]
  name = "default-runner"
  executor = "docker"
  # tags не указан — этот раннер примет задачи без тегов
```

**Рекомендации:**
-   Используйте осмысленные имена тегов: `build`, `test`, `deploy`, `gpu`, `macos`
-   Не используйте теги для управления доступом — для этого есть `protected` и `paused`
-   Для кросс-платформенного тестирования комбинируйте `tags` с `parallel:matrix` (см. **[Матричные сборки](./workflow_rules/matrix_builds_and_serialization.md)**)

## Безопасность и ограничения

1.  **Allowed Images & Services**: В `config.toml` можно (и нужно) ограничить список разрешенных образов для `docker` и `kubernetes` executors, чтобы предотвратить запуск вредоносного ПО.
    ```toml
    [runners.docker]
      allowed_images = ["my-registry.com/ci/*", "alpine:*"]
      allowed_services = ["postgres:15-alpine", "redis:7-alpine"]
    ```
2.      **Privileged Mode**: `privileged = true` требуется для DinD (Docker-in-Docker), но является критической уязвимостью. Рекомендуется использовать **[Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)** для сборки образов без привилегий.
3.  **Protected Runners**: Флаг в настройках Runner'а, разрешающий выполнять задачи только из защищенных веток (`main`, `production`). Это защищает секреты от кражи через Pull Request из форков.
4.  **OIDC & id_tokens**: Runner поддерживает передачу временных JWT-токенов во внешние системы. Это позволяет безопасно аутентифицироваться в Vault, Kubernetes API или локальном Object Storage без хранения статических ключей в переменных. Подробности — см. **[API и Webhooks: Механизм id_tokens](./api_and_webhooks_automation.md#механизм-id_tokens-oidc)**.

## Архитектура Runner: Manager vs Executor

**Runner Manager** — это процесс-демон (`gitlab-runner`), который:
-   Регистрируется на GitLab-сервере через API
-   Опрашивает сервер на наличие задач (polling)
-   Управляет жизненным циклом задач (приём, выполнение, отчёт)
-   Управляет конфигурацией из `config.toml`

**Executor** — это модуль внутри Manager, который определяет **как** будет выполнена задача:
-   Создаёт изолированную среду (контейнер, ВМ, Pod)
-   Запускает скрипты задачи
-   Управляет ресурсами (CPU, память, диск)
-   Уничтожает среду после выполнения

**Множественные executors в одном Manager:**
Один Runner Manager может иметь несколько секций `[[runners]]` с разными executor'ами. Это позволяет запускать задачи в разных средах с одного сервера.

Для пошаговой регистрации и настройки см. SSoT: **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)**.

```toml
# Пример: один сервер с двумя runner'ами
concurrent = 10

# Runner 1: Docker для быстрых задач
[[runners]]
  name = "docker-fast"
  executor = "docker"
  tags = ["fast", "docker"]
  [runners.docker]
    image = "alpine:latest"
    memory = "2g"

# Runner 2: Shell для системных задач
[[runners]]
  name = "shell-system"
  executor = "shell"
  tags = ["system", "admin"]
```

### Multi-runner config.toml

В реальных deployment'ах один `config.toml` содержит несколько `[[runners]]` для различных целей. Базовый пример:

```toml
concurrent = 50           # Глобальный лимит: 50 задач одновременно
check_interval = 3

# Runner 1: Docker для быстрых задач
[[runners]]
  name = "build-linux"
  executor = "docker"
  tags = ["build", "linux"]
  limit = 20
  [runners.docker]
    image = "ubuntu:24.04"
    memory = "4g"
    cpus = "2"

# Runner 2: Shell для системных задач
[[runners]]
  name = "deploy-production"
  executor = "shell"
  tags = ["deploy", "production"]
  limit = 3
  protected = true
```

Для production-оптимизированных конфигураций (метрики, session_server, кэш S3, политики очистки) см. SSoT: **[Управление парком Runner'ов (Fleet Management)](./runner_fleet_management.md)**.

**Ключевые параметры `limit`:**
-   `limit = 0` (по умолчанию): Runner принимает задачи до достижения глобального `concurrent`
-   `limit = N`: Runner принимает максимум N задач одновременно
-   Рекомендуется задавать `limit` для каждого runner'а для предсказуемого поведения

### Очередь задач (FIFO Queue) и назначение задач

GitLab использует модель **Pull-based** (pull model) для назначения задач:

1.  Runner Manager отправляет `POST /api/v4/jobs/request` с указанием своих тегов,特色产业 и доступных ресурсов
2.  GitLab ищет подходящую задачу в очереди (FIFO: First In, First Out)
3.  Подходящая задача определяется по:
    -   **Tags**: Все теги задачи должны совпадать с тегами runner'а
    -   **Scope**: Задача должна принадлежать проекту/группе, к которой привязан runner
    -   **Status**: Задача должна быть в статусе `pending`
    -   **Protected**: Если runner `protected = true` — только из защищённых веток/MR
4.  Если подходящих задач нет — runner ждёт (`check_interval` секунд) и повторяет запрос

**Почему задачи «застряли в Pending»:**
-   Нет runner'ов с соответствующими тегами (проверьте `CI/CD > Runners`)
-   Достигнут лимит `concurrent` или `limit` на всех подходящих runner'ах
-   Runner `paused` или `locked` (привязан к другому проекту)
-   Protected runner, а задача из незащищённой ветки

### Runner: версионирование и обновление

**Рекомендации по обновлению:**
-   **Мажорные версии** (16.x → 17.x): Обновляйте после выхода patch-версии (17.1.1+), тестируя в staging-среде
-   **Минорные версии** (17.0 → 17.1): Обновляйте через 2-4 недели после выхода, отслеживая Known Issues
-   **Патчи** (17.1.0 → 17.1.1): Обновляйте немедленно (исправления безопасности)

**Rolling update стратегия:**
```bash
# 1. Остановить приём новых задач
gitlab-runner stop

# 2. Дождаться завершения текущих задач
gitlab-runner status  # → "Runtime platform" information

# 3. Обновить бинарник
# Debian/Ubuntu:
sudo apt-get update && sudo apt-get install gitlab-runner
# RHEL/CentOS:
sudo yum update gitlab-runner

# 4. Проверить конфигурацию
gitlab-runner verify

# 5. Запустить
gitlab-runner start
```

**Версионная совместимость:**
-   Runner должен быть той же мажорной версии, что и GitLab Server (±1 мажорная версия)
-   `helper_image` должен соответствовать версии runner'а (автоматически подбирается, но можно зафиксировать)
-   При несовместимости可能出现 ошибки в API-запросах и логах

### Оптимизация config.toml

Базовые параметры производительности:

```toml
concurrent = 20           # Глобальный лимит задач на весь агент
check_interval = 3        # Интервал опроса GitLab API (сек)
```

Для production-оптимизированных конфигураций (session_server, metrics_server, политики очистки, кэш S3) см. SSoT: **[Управление парком Runner'ов (Fleet Management)](./runner_fleet_management.md)**.

### Лимиты ресурсов Docker Executor

В отличие от Kubernetes executor, где ресурсы задаются через `cpu_limit`/`memory_limit`, Docker executor использует нативные Docker-параметры:

```toml
[[runners]]
  name = "docker-runner"
  executor = "docker"
  [runners.docker]
    image = "ubuntu:24.04"
    # Лимиты контейнера задачи
    memory = "4g"              # Максимум памяти (по умолчанию: без ограничений)
    memory_swap = "4g"         # Лимит swap (memory + swap; по умолчанию: memory + 2G)
    memory_reservation = "2g"  # Мягкий лимит памяти (для планировщика Docker)
    cpus = "2.0"               # Количество CPU (по умолчанию: все доступные)
    cpu_shares = 1024          # Относительный вес CPU (по умолчанию: 1024)
    shm_size = "256m"          # Размер /dev/shm (критично для Chrome, Firefox)
    
    # Лимиты вспомогательных контейнеров (services)
    allowed_services = ["postgres:15-alpine", "redis:7-alpine"]
```

**Важные нюансы:**
-   `memory` + `memory_swap`: если `memory_swap = memory` — swap отключается (рекомендуется для предсказуемого поведения)
-   `shm_size`: по умолчанию Docker выделяет 64MB. Для тестирования веб-приложений (Playwright, Selenium) увеличивайте до 256MB+
-   `cpus`: принимает дробные значения (`0.5`, `1.5`, `2.0`). Полезно для ограничения потребления на shared раннерах

### Docker-out-of-Docker (DooD) vs Docker-in-Docker (DinD)

Два основных подхода для сборки Docker-образов внутри CI/CD. Выбор зависит от требований безопасности и производительности.

| Параметр | Docker-in-Docker (DinD) | Docker-out-of-Docker (DooD) |
|:---|:---|:---|
| **Как работает** | Запуск Docker-демона внутри контейнера задачи (`--privileged`) | Монтирование Docker-сокета хоста в контейнер задачи |
| **Изоляция** | Полная изоляция (свой Docker-демон) | Частичная (доступ к Docker API хоста) |
| **Безопасность** | Низкая (`--privileged` даёт полный доступ к ядру) | Средняя (доступ к API Docker хоста) |
| **Производительность** | Медленнее (вложенная виртуализация) | Быстрее (использует Docker хоста) |
| **Кэш образов** | Изолированный (не разделяется между задачами) | Общий (разделяется с хостом) |
| **Рекомендация** | Для задач, требующих полной изоляции | Для большинства CI/CD-задач |

**Конфигурация DinD:**
```yaml
# .gitlab-ci.yml
build:
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_HOST: tcp://docker:2375
    DOCKER_TLS_CERTDIR: ""  # Отключение TLS для простоты
  script:
    - docker build -t my-app .
    - docker push my-registry.com/my-app
```

**Конфигурация DooD:**
```toml
# config.toml
[[runners]]
  [runners.docker]
    volumes = ["/var/run/docker.sock:/var/run/docker.sock"]
```
```yaml
# .gitlab-ci.yml
build:
  image: docker:24.0
  script:
    - docker build -t my-app .
    - docker push my-registry.com/my-app
```

**Рекомендация**: Для большинства on-premise сред используйте **DooD** (проще, быстрее, безопаснее). DinD — только когда критична полная изоляция Docker-демонов. Альтернатива для сборки образов без privileged — **[Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)** (сборка без Docker-демона).

### Мониторинг раннера

Runner имеет встроенный экспортер метрик для Prometheus. Базовые метрики:

-   `gitlab_runner_concurrent`: Текущее количество запущенных задач.
-   `gitlab_runner_errors_total`: Количество ошибок связи с GitLab.
-   `gitlab_runner_jobs_total`: Общее количество выполненных задач по статусам.

Для полного руководства по мониторингу (включение `metrics_server`, алерты, Grafana дашборды) см. SSoT: **[Мониторинг и метрики GitLab CI/CD](./monitoring_and_metrics.md)**.

## Устранение неполадок (Troubleshooting)

### Типичные ошибки
-   **`New runner token is invalid`**: Ошибка при использовании `glrt-` токена с командой `register`. С версии 16.0+ используйте `--token` вместо `--registration-token`.
-   **`Job failed: execution took longer than timeout`**: Превышен лимит времени выполнения. Проверьте настройки `timeout` в проекте или `runners.config.toml`.
-   **`Error response from daemon: oom killed`**: Превышение лимитов памяти в Docker/K8s. Увеличьте `memory_limit` в `config.toml`.
-   **`Failed to pull helper image`**: Runner не может скачать вспомогательный образ для работы с кэшем/артефактами. Проверьте доступ к `registry.gitlab.com` или настройте локальный `helper_image`.
-   **`Stuck in Pending`**: Нет раннеров с соответствующими тегами или достигнут лимит `concurrent`.
-   **`ERROR: Job failed: stuck or exceeded timeout`**: Задача зависла на одной из стадий. Проверьте логи задачи и убедитесь, что нет бесконечного цикла в скрипте.
-   **`exec format error`**: Несоответствие архитектуры образа (arm64) и хоста (amd64). Используйте multi-arch образы или QEMU.
-   **`cannot allocate memory`**: На хосте закончилась RAM. Уменьшите `concurrent` или увеличьте физическую память.
-   **`error during connect: Post http://%2F.%2Fpipe%2Fdocker_engine`**: Docker Desktop не запущен (Windows) или Docker-демон недоступен (Linux). Проверьте `systemctl status docker`.
-   **` Runner is locked and assigned to project`**: Runner привязан к конкретному проекту. Переключите на Group/Instance scope или создайте новый runner.

### Диагностика
1.  **Логи**: `journalctl -u gitlab-runner -f` или просмотр логов контейнера.
2.  **Debug mode**: Запуск раннера с флагом `--debug`.
3.  **Verify**: Команда `gitlab-runner verify` для проверки связи всех зарегистрированных раннеров с сервером.
4.  **List runners**: `gitlab-runner list` — показывает все зарегистрированные runners и их статус.
5.  **Ресурсы**: `docker stats` — мониторинг потребления ресурсов Docker-контейнеров в реальном времени.
6.  **Сеть**: `curl -s https://gitlab.internal/api/v4/version` — проверка доступности GitLab API с хоста раннера.

### Диагностический скрипт

```bash
#!/bin/bash
# /opt/scripts/runner-diagnose.sh — полная диагностика раннера

echo "=== GitLab Runner Diagnostics ==="
echo "1. Runner version:"
gitlab-runner --version

echo -e "\n2. Runner status:"
sudo systemctl status gitlab-runner --no-pager | head -5

echo -e "\n3. Registered runners:"
gitlab-runner list 2>&1 | grep -E "name|url|executor|tags"

echo -e "\n4. Runner verify:"
sudo gitlab-runner verify 2>&1

echo -e "\n5. Docker status:"
docker info --format '{{.ServerVersion}}' 2>/dev/null || echo "Docker not available"

echo -e "\n6. System resources:"
free -h | head -2
df -h / | tail -1
nproc

echo -e "\n7. Network connectivity to GitLab:"
curl -s -o /dev/null -w "%{http_code}" https://gitlab.internal/api/v4/version
# → 200 = OK
```

## Best Practices

### Проектирование Runner-инфраструктуры (DevOps/SRE)

-   **Один executor — одна ответственность**: Не смешивайте задачи разных типов на одном раннере. Отдельные runner'ы для builds, tests, deploy с уникальными тегами.
-   **Protected runners только для production**: Включайте `protected = true` только для runner'ов, обслуживающих `main`/`production` ветки. Это защищает секреты от кражи через Pull Request из форков.
-   **Least Privilege для executor'ов**: Используйте `shell` executor только для задач, требующих доступ к GPU/HW. Для большинства CI/CD задач используйте `docker` с минимальными привилегиями.
-   **DooD вместо DinD**: По умолчанию используйте DooD (монтирование `/var/run/docker.sock`). DinD (`privileged = true`) — только для задач, требующих полной изоляции Docker-демонов.
-   **Эфемерные runner'ы по умолчанию**: Для тестов и сборок используйте эфемерные runner'ы (Fleeting). Постоянные раннеры — только для долгоживущих стендов с контролируемым доступом.
-   **JIT Config вместо registration tokens**: Используйте JIT (Just-In-Time) Config для автоматической регистрации эфемерных runner'ов. Это исключает хранение registration tokens.

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
-   **Очередь Merge Request**: Для проектов с высокой активностью MR используйте Merge Queue, чтобы предотвратить breakage main при интеграции нестабильных изменений.
-   **Резервное копирование config.toml**: Регулярно бэкапите `/etc/gitlab-runner/config.toml` и храните в защищённом хранилище.

### Управление инстансом (Sysadmin)

-   **Обновление Runner'ов**: Обновляйте GitLab Runner в течение 1-2 недель после выхода мажорной версии GitLab. Runner должен быть той же мажорной версии, что и GitLab Server (±1).
-   **Ротация секретов**: Периодически меняйте `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` для кэша и обновляйте их в `config.toml`.
-   **Мониторинг очереди доставки вебхуков**: GitLab помещает неудачные вебхуки в очередь. Мониторьте размер очереди через Admin API.
-   **Очистка Docker ресурсов**: Настройте автоматическую очистку остановленных контейнеров, неиспользуемых образов и volumes (cron или scheduled pipeline).
-   **Резервное копирование**: Регулярно бэкапите базу данных GitLab и хранилище артефактов. Тестируйте восстановление на изолированном стенде.

## Граничные условия и ограничения (Edge Cases)

### Версионная совместимость

-   **`glrt-` токены**: Доступны с GitLab 16.0+. В более старых версиях используйте `registration-token` (устарели).
-   **`docker-autoscaler`**: Доступен с GitLab 17.0+. В более старых версиях используйте `docker-machine` (устарел) или статические runner'ы.
-   **`spec:inputs` в корневом файле**: Доступен только с GitLab 17.11+. В более старых версиях используйте `variables` с `options`.
-   **JIT Config**: Доступен с GitLab 17.0+. В более старых версиях используйте JIT Runner Registration Token.
-   **Runner Manager и GitLab Server**: Runner должен быть той же мажорной версии, что и GitLab Server (±1 мажорная версия). При несовместимости могут появиться ошибки в API-запросах.

### Ограничения механизмов

-   **`concurrent` лимит**: Глобальный лимит задач на один Runner Manager. При превышении задачи остаются в очереди. Для масштабирования используйте несколько Runner Manager'ов.
-   **`limit` на runner**: Если `limit = 0` (по умолчанию), runner принимает задачи до глобального `concurrent`. Если `limit = N` — максимум N задач.
-   **Docker DinD и `privileged`**: `privileged = true` даёт полный доступ к ядру хоста. Это критическая уязвимость. Используйте Kaniko или DooD вместо DinD.
-   **`shm_size`**: По умолчанию Docker выделяет 64MB. Для тестирования веб-приложений (Playwright, Selenium) увеличивайте до 256MB+.
-   **`memory_swap`**: Если `memory_swap = memory` — swap отключается. Это рекомендуется для предсказуемого поведения.

### Специфические сценарии

-   **Runner без исходящего интернета**: Если Runner находится в изолированной сети, убедитесь, что он может доставить запросы к GitLab API и внутреннему registry.
-   **Высокая частота задач**: При массовых задачах (bulk triggers) GitLab может дедуплицировать запросы. Настраивайте `check_interval` и `concurrent` с запасом.
-   **Fork-репозитории**: Для Fork MR задачи запускаются только на Shared runner'ах. Project runner'ы не доступны.
-   **Запуск пайплайна из пайплайна**: При использовании `CI_JOB_TOKEN` для Trigger API убедитесь, что целевой проект добавлен в Inbound Allowlist. Иначе вернётся 403 Forbidden.
-   **Deadlock в Resource Group**: Если задача зависла и удерживает группу, последующие пайплайны будут ждать бесконечно. Ручная очистка в `CI/CD > Resource Groups` или настройка `timeout` на задаче.

### Ограничения инфраструктуры

-   **Сетевая задержка**: Runner должен отвечать на запросы GitLab API за <10 секунд. При высокой задержке увеличьте `check_interval` или используйте regional Runner'ы.
-   **TLS-сертификаты**: GitLab не отправляет задачи на HTTP (кроме `localhost` в development-режиме). Убедитесь, что GitLab Server работает по HTTPS с валидным сертификатом.
-   **DNS**: GitLab кэширует DNS на 5 минут. При смене IP GitLab Server старый IP может использоваться до истечения кэша.
-   **Файрвол**: Если Runner и GitLab Server находятся в разных сегментах сети, откройте порт 443 в обе стороны.
-   **Ресурсы хоста**: Убедитесь, что на хосте Runner'а достаточно RAM и CPU. При нехватке ресурсов Docker OOM-killer завершит контейнеры задач.

## Дополнительная информация

### См. также
-   **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)** — практическое пошаговое руководство по установке и регистрации.
-   **[Docker-in-Docker vs Docker-out-of-Docker](../../../Docker/docker-in-docker.md)** — безопасность сборки образов, сравнение подходов.
-   **[Кэширование в GitLab CI](./gitlab_ci_caching/caching_overview.md)** — настройка локального и распределенного кэша.
-   **[Resource Group и контроль пайплайнов](./resource_group_and_pipeline_control.md)** — мьютекс, concurrency, retry, timeout.
-   **[CI_JOB_TOKEN безопасность](./ci_job_token_security.md)** — allowlist, scope, attack vectors.
-   **[OIDC и Workload Identity в GitLab CI](./gitlab_ci_oidc_workload_identity.md)** — аутентификация без секретов.
-   **[Управление парком Runner'ов (Fleet Management)](./runner_fleet_management.md)** — автоскейлинг, мониторинг, оптимизация.
