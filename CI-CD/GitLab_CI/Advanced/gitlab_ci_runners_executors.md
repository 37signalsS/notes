# GitLab CI: Исполнители (Runners) и их типы (Executors)

## Определения

- **[GitLab Runner](https://docs.gitlab.com/runner/)**: Отдельное приложение, которое выполняет задания (jobs) из пайплайнов GitLab CI/CD. Runner опрашивает сервер GitLab, забирает задачи и выполняет их в указанной среде.
- **[Executor](https://docs.gitlab.com/runner/executors/)**: Модуль внутри Runner'а, который определяет, *как* и *где* будут выполняться скрипты (например, в Docker-контейнере, на хосте через shell или в Kubernetes Pod).
- **Теги (`tags`)**: Метки, которые присваиваются Runner'ам (`docker`, `linux`, `gpu`) и используются в `.gitlab-ci.yml` для выбора исполнителя для конкретной задачи.

## Основные концепции

#### 1. Типы Runner'ов (по области видимости)

| Тип | Область видимости | Контроль | Безопасность |
| :--- | :--- | :--- | :--- |
| **Shared** (общий) | Вся инстанция GitLab | Ограниченный | Ниже |
| **Group** (групповой) | Все проекты в группе | Частичный | Средняя |
| **Specific** (проектный) | Конкретный проект | Полный | Выше |

- **Specific Runner** является предпочтительным для задач с особыми требованиями (секреты, доступ в приватную сеть).
- **Protected Runner** выполняет задания только из защищенных веток, что критично для задач развертывания.

#### 2. Типы Executor'ов (по среде выполнения)

| Executor | Изоляция | Скорость | Управление зависимостями | Основной сценарий |
| :--- | :--- | :--- | :--- | :--- |
| **`shell`** | Низкая | Очень высокая | Ручная установка на хост | Простые задачи, доступ к железу. |
| **`docker`** | Высокая | Высокая | Автоматическая (`image:`) | **Самый популярный.** Чистая среда на каждую задачу. |
| **`kubernetes`**| Очень высокая| Высокая | Автоматическая (`image:`) | Оркестрация в Kubernetes, автомасштабирование. |

#### 3. Файл конфигурации `config.toml`

Основной файл конфигурации GitLab Runner, где определяются глобальные параметры и настройки для каждого зарегистрированного runner.

```toml
# Глобальный лимит одновременно выполняемых задач
concurrent = 4

[[runners]]
  name = "project-docker-runner"
  url = "https://gitlab.example.com/"
  token = "REDACTED"
  executor = "docker"
  [runners.docker]
    image = "alpine:latest"
    privileged = false
  [runners.cache]
    Type = "s3"
    [runners.cache.s3]
      ServerAddress = "s3.example.com"
      BucketName = "gitlab-cache"
```

## Практические сценарии

#### Сценарий 1: Выбор Runner'а по тегам

Задача `test:db` будет выполнена только на Runner'е с тегами `docker` и `postgres`.

```yaml
test:db:
  stage: test
  tags:
    - docker
    - postgres
  script:
    - psql -h postgres -U user -d db -c "SELECT 1;"
```

#### Сценарий 2: Использование Kubernetes Executor

Для динамического масштабирования и изоляции используется Kubernetes Executor, который создает отдельный Pod для каждой задачи. Настраивается через Helm-чарт GitLab Runner.

```yaml
# values.yaml для Helm-чарта
gitlabUrl: https://gitlab.example.com
runnerRegistrationToken: "REDACTED"
runners:
  tags: "k8s,linux"
  # ... другие настройки
```

## Дополнительная информация

#### Рекомендации и лучшие практики

- **Изолируйте рабочие нагрузки:** Используйте `tags` для разделения Runner'ов для разных сред (`dev`, `prod`).
- **Предпочитайте Specific Runner'ы:** Для production-задач всегда используйте `Specific Runner`'ы и отключайте `Shared Runner`'ы.
- **Безопасность Docker:** Избегайте `privileged` режима и монтирования Docker-сокета. Для сборки образов используйте **[Kaniko](../../../Docker/Dockerfile/dockerfile_kaniko.md)**.
- **Наблюдаемость:** Включите `metrics_server` в `config.toml` для сбора метрик в формате Prometheus.

## Связанные документы

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — для понимания базовых концепций.
- **[Общий глоссарий элементов CI/CD](../../Core_Concepts/pipeline_elements.md)** — для понимания универсальных терминов.
- **Практическое руководство:** **[Регистрация GitLab Runner](../Tutorials/runner_registration.md)**.
- **Интеграция с Kubernetes:** **[Интеграция GitLab CI с Kubernetes](./gitlab_kubernetes_integration_guide.md)**.
