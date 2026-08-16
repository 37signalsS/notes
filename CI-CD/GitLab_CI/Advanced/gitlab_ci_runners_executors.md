# Обзор GitLab Runner и Executor

## Определения

**[GitLab Runner](https://docs.gitlab.com/runner/)** — агент (приложение на Go), предназначенный для выполнения заданий (jobs) CI/CD пайплайнов. Он работает по Pull-модели: опрашивает сервер GitLab через API, получает описание задачи, исполняет её в изолированной среде и возвращает логи и артефакты.

**Executor (Исполнитель)** — изолированный модуль внутри Runner, который определяет технологию создания среды выполнения (контейнер, виртуальная машина или сессия в ОС).

**Authentication Token (`glrt-`)** — современный стандарт безопасности (введен в GitLab 16.0), заменяющий устаревшие регистрационные токены. Токен создается на стороне сервера и жестко привязывает Runner к области видимости (Project/Group/Instance), исключая возможность несанкционированного изменения конфигурации агентом.

**[Fleeting & Taskscaler](https://docs.gitlab.com/runner/executors/docker_autoscaler.md)** — архитектура автоскейлинга нового поколения (стандарт с GitLab 17.0+):
-   **Fleeting**: Библиотека управления эфемерной инфраструктурой. Через плагины взаимодействует с API облаков (AWS ASG, GCP MIG, Azure VMSS), обеспечивая создание и удаление узлов.
-   **Taskscaler**: Высокоуровневый планировщик, который распределяет задачи по инстансам Fleeting, учитывая их загрузку и жизненный цикл.
-   **Преимущество**: Полный уход от устаревшего `docker-machine` в пользу нативных облачных механизмов масштабирования.

## Жизненный цикл задачи (Job Lifecycle)

1.  **Request (Запрос)**: Runner отправляет запрос `POST /api/v4/jobs/request` с указанием своих тегов и возможностей.
2.  **Pickup (Прием)**: Если есть подходящее задание, GitLab передает Runner'у спецификацию (скрипты, переменные, зависимости).
3.  **Preparation (Подготовка)**: Executor создает среду (поднимает контейнер, ВМ или Pod в K8s).
4.  **Execution (Выполнение)**:
    -   `pre_clone_script` (если задан) — выполнение команд до клонирования Git.
    -   `git clone` и загрузка артефактов/кэша.
    -   `pre_build_script` — подготовка окружения.
    -   `script` — выполнение основной логики задачи.
    -   `post_build_script` — действия после основного скрипта.
5.  **Finalization (Завершение)**: Выгрузка артефактов и кэша, отправка финального лога и статуса (Success/Failed).
6.  **Cleanup (Очистка)**: Executor уничтожает временную среду.

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
| **`kubernetes`** | Высокая | Горизонтальное (Cluster) | Высоконагруженные системы, K8s-native пайплайны. |
| **`docker-autoscaler`** | Высокая | Облачное (Fleeting) | Современный автоскейлинг в AWS/GCP/Azure. Замена `docker+machine`. |
| **`instance`** | Полная (VM) | Облачное (Fleeting) | Максимальная изоляция (по ВМ на каждую задачу). |
| **`custom`** | Любая | Любое | Использование сторонних инструментов (например, Podman или LXC) через драйвер. |

## Безопасность и ограничения

1.  **Allowed Images & Services**: В `config.toml` можно (и нужно) ограничить список разрешенных образов для `docker` и `kubernetes` executors, чтобы предотвратить запуск вредоносного ПО.
    ```toml
    [runners.docker]
      allowed_images = ["my-registry.com/ci/*", "alpine:*"]
      allowed_services = ["postgres:15-alpine", "redis:7-alpine"]
    ```
2.  **Privileged Mode**: `privileged = true` требуется для DinD (Docker-in-Docker), но является критической уязвимостью. Рекомендуется использовать **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md)** для сборки образов без привилегий.
3.  **Protected Runners**: Флаг в настройках Runner'а, разрешающий выполнять задачи только из защищенных веток (`main`, `production`). Это защищает секреты от кражи через Pull Request из форков.
4.  **OIDC & id_tokens**: Runner поддерживает передачу временных JWT-токенов во внешние системы. Это позволяет безопасно аутентифицироваться в Vault или AWS без хранения статических ключей в переменных.

## Конфигурация и мониторинг

### Оптимизация config.toml

Файл конфигурации (`/etc/gitlab-runner/config.toml`) позволяет тонко настраивать производительность:

```toml
concurrent = 20           # Глобальный лимит задач на весь агент
check_interval = 3        # Интервал опроса GitLab API (сек)

[session_server]
  listen_address = "[::]:8093" # Для интерактивного терминала в браузере

[[runners]]
  name = "k8s-runner-prod"
  executor = "kubernetes"
  builds_dir = "/builds"
  cache_dir = "/cache"
  
  [runners.kubernetes]
    image = "ubuntu:24.04"
    namespace = "gitlab-runners"
    cpu_limit = "1"
    memory_limit = "2Gi"
    service_cpu_limit = "500m"
    service_memory_limit = "1Gi"
    helper_image = "registry.gitlab.com/gitlab-org/gitlab-runner/gitlab-runner-helper:x86_64-v17.x.x"

  [runners.cache]
    Type = "s3"
    Shared = true
    [runners.cache.s3]
      ServerAddress = "s3.amazonaws.com"
      BucketName = "my-ci-cache"
      BucketLocation = "us-east-1"
```

### Мониторинг раннера
Runner имеет встроенный экспортер метрик для Prometheus.
-   **Включение**: В `config.toml` добавьте `listen_address = ":9252"`.
-   **Метрики**:
    -   `gitlab_runner_concurrent`: Текущее количество запущенных задач.
    -   `gitlab_runner_errors_total`: Количество ошибок связи с GitLab.
    -   `gitlab_runner_jobs_total`: Общее количество выполненных задач по статусам.

## Устранение неполадок (Troubleshooting)

### Типичные ошибки
-   **`New runner token is invalid`**: Ошибка при использовании `glrt-` токена с командой `register`. С версии 16.0+ используйте `--token` вместо `--registration-token`.
-   **`Job failed: execution took longer than timeout`**: Превышен лимит времени выполнения. Проверьте настройки `timeout` в проекте или `runners.config.toml`.
-   **`Error response from daemon: oom killed`**: Превышение лимитов памяти в Docker/K8s. Увеличьте `memory_limit` в `config.toml`.
-   **`Failed to pull helper image`**: Runner не может скачать вспомогательный образ для работы с кэшем/артефактами. Проверьте доступ к `registry.gitlab.com` или настройте локальный `helper_image`.
-   **`Stuck in Pending`**: Нет раннеров с соответствующими тегами или достигнут лимит `concurrent`.

### Диагностика
1.  **Логи**: `journalctl -u gitlab-runner -f` или просмотр логов контейнера.
2.  **Debug mode**: Запуск раннера с флагом `--debug`.
3.  **Verify**: Команда `gitlab-runner verify` для проверки связи всех зарегистрированных раннеров с сервером.

## Дополнительная информация

### См. также
-   **[GitLab CI/CD для iOS и macOS](../../mobile-ci-cd/gitlab-ios-ci.md)** — специфические настройки для мобильной разработки.
-   **[Управление парком раннеров](../../runner-fleet-management.md)** — политики распределения ресурсов, квоты и административные аспекты.
-   **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)** — практическое пошаговое руководство.
-   **[Интеграция с Kubernetes](./gitlab_kubernetes_integration_guide.md)** — детальная настройка K8s Executor.
-   **[Docker-in-Docker](../../../Docker/docker-in-docker.md)** — сборка образов и вопросы безопасности.
-   **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — общая архитектура системы.
-   **[Кэширование в GitLab CI](./gitlab_ci_caching/caching_overview.md)** — настройка локального и распределенного кэша.
