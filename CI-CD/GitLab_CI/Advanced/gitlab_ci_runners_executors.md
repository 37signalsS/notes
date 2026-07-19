# Обзор GitLab Runner и Executor

## Определения

**[GitLab Runner](https://docs.gitlab.com/runner/)** — это агент (приложение на языке Go), который опрашивает сервер GitLab на наличие заданий (jobs), выполняет их и возвращает результат (логи, артефакты) обратно. Runner работает по принципу исходящих соединений — ему не нужен входящий доступ из интернета.

**[Executor](https://docs.gitlab.com/runner/executors/)** — модуль внутри Runner, определяющий среду выполнения скриптов (контейнер Docker, под Kubernetes, shell-сессия на хосте и др.).

**Токен аутентификации (Authentication Token)** — современный способ (с GitLab 16.0+) связи Runner'а с инстансом. В отличие от старых регистрационных токенов, аутентификационный токен создается в интерфейсе GitLab и сразу определяет область видимости и теги Runner'а.

## Основные концепции

### Типы Runner по области видимости

| Тип | Где настраивается | Кто может использовать | Основное применение |
| :--- | :--- | :--- | :--- |
| **Shared** | Admin Area | Все проекты инстанса | Общие задачи сборки, небольшие проекты |
| **Group** | Group Settings | Все проекты и подгруппы в группе | Командные ресурсы, специфические зависимости |
| **Project** | Project Settings | Только данный проект | Критичные задачи, доступ к закрытой инфраструктуре |

### Сравнение Executor'ов

| Executor | Изоляция | Сложность | Масштабирование | Рекомендуемое применение |
| :--- | :--- | :--- | :--- | :--- |
| **`shell`** | Отсутствует | Очень низкая | Нет | Локальные задачи, быстрые скрипты на хосте |
| **`docker`** | Высокая | Низкая | Ограничено хостом | Стандарт для большинства CI задач |
| **`kubernetes`** | Высокая | Высокая | Динамическое | Высокая нагрузка, K8s-инфраструктура |
| **`docker-autoscaler`** | Высокая | Средняя | Динамическое (Cloud) | Замена `docker+machine` для облаков (AWS, GCP) |
| **`instance`** | Полная (VM) | Средняя | Динамическое | Максимальная изоляция (Google Cloud/EC2) |

#### Shell Executor
Задания выполняются от имени пользователя `gitlab-runner`. 
- **Риски:** Задачи имеют доступ к файловой системе хоста и могут влиять на другие задания. 
- **Когда использовать:** Только для простых задач или если требуется прямой доступ к аппаратному обеспечению (GPU без Docker-поддержки).

#### Docker Executor
Самый популярный тип. Каждое задание запускается в новом контейнере. 
- **Конфигурация:** Образ указывается в `.gitlab-ci.yml` (`image: name`). 
- **Docker-in-Docker (DinD):** Для сборки образов внутри Docker Executor требуется `privileged = true` в `config.toml` или использование **[Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)**.

#### Kubernetes Executor
Создает отдельный Pod для каждого задания. Поддерживает динамическое выделение ресурсов. 
- **Преимущества:** Нативный для K8s, легко масштабируется, высокая надежность.
- **Интеграция:** См. подробнее в **[Интеграции с Kubernetes](./gitlab_kubernetes_integration_guide.md)**.

### Архитектура и безопасность

1. **Коммуникация:** Runner опрашивает GitLab через API (HTTPS). Если Runner за корпоративным Firewall, достаточно разрешить исходящий трафик на порт 443 к GitLab.
2. **Защищенные Runner'ы (Protected):** Могут выполнять задания только из защищенных веток и тегов. Предотвращают кражу секретов продуктивных сред через сторонние ветки.
3. **Изоляция:** Для высокой безопасности рекомендуется использовать `docker` или `instance` executors. `shell` executor считается небезопасным для публичных проектов.

### Конфигурация `config.toml`

Файл настроек обычно находится в `/etc/gitlab-runner/config.toml`.

```toml
concurrent = 4               # Общий лимит задач для всех Runner'ов на хосте
check_interval = 0           # Частота опроса GitLab (0 = по умолчанию 3 сек)
log_level = "info"

[session_server]             # Позволяет использовать интерактивный терминал в UI GitLab
  session_timeout = 1800

[[runners]]
  name = "docker-prod-01"
  url = "https://gitlab.example.com/"
  id = 123
  token = "glrt-XXXXXXXXXXXX" # Authentication Token (начинается с glrt-)
  token_obtained_at = 2024-01-01T00:00:00Z
  token_expires_at = 0001-01-01T00:00:00Z
  executor = "docker"
  [runners.docker]
    image = "alpine:latest"
    privileged = false        # Рекомендуется false (безопасность)
    volumes = ["/cache", "/var/run/docker.sock:/var/run/docker.sock"] # Для доступа к Docker хоста
    pull_policy = ["always"]
  [runners.cache]
    Type = "s3"
    [runners.cache.s3]
      ServerAddress = "s3.amazonaws.com"
      BucketName = "gitlab-cache"
```

## Практические сценарии

### Сценарий 1: Ускорение сборки через теги (Tags)

Назначение задачи на Runner с мощным CPU или GPU.

```yaml
build:gpu_optimized:
  stage: build
  tags:
    - gpu
    - cuda-12
  script:
    - nvcc --version
```

### Сценарий 2: Использование переменных для выбора Executor

Хотя Executor жестко задан в `config.toml`, вы можете переопределять образ динамически.

```yaml
test:multi_version:
  stage: test
  image: $TEST_IMAGE
  parallel:
    matrix:
      - TEST_IMAGE: ["python:3.10", "python:3.11", "python:3.12"]
  script:
    - python --version
```

## Дополнительная информация

### Новая модель регистрации (GitLab 16+)
Старая модель с регистрационными токенами считается устаревшей. Теперь процесс выглядит так:
1. Создание записи Runner в интерфейсе GitLab (Admin -> Runners или Project -> CI/CD -> Runners).
2. Получение `glrt-` токена.
3. Запуск команды `gitlab-runner register --token glrt-XXXXX` без указания регистрационного токена.

### Смотрите также

- **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)** — актуальная инструкция по установке и регистрации.
- **[Интеграция с Kubernetes](./gitlab_kubernetes_integration_guide.md)** — глубокая настройка K8s Executor.
- **[Docker-in-Docker](../../../Docker/docker-in-docker.md)** — подробности сборки образов в CI.
- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — общая архитектура.
