# Установка GitLab Runner в Kubernetes

Руководство по развертыванию, масштабированию и оптимизации GitLab Runner в кластере Kubernetes при помощи официального Helm-чарта.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **GitLab Runner** | Агент (приложение на Go), выполняющий задачи CI/CD пайплайнов. |
| **Kubernetes Executor** | Исполнитель, который для каждой задачи создает отдельный под (Pod) в кластере. |
| **Authentication Token** | Токен нового образца (префикс `glrt-`), заменяющий устаревшие `Registration Tokens`. Создается в UI GitLab 16.0+. |
| **Concurrent** | Глобальный параметр, определяющий максимальное количество одновременно запущенных задач на один инстанс раннера. |
| **Check Interval** | Интервал (в секундах), с которым раннер опрашивает GitLab на наличие новых задач. |
| **Distributed Cache** | Механизм хранения кэша заданий во внешнем объектном хранилище (S3, MinIO, GCS) для доступа из разных подов. |

---

## Основные концепции

### Преимущества Kubernetes Executor

Использование Kubernetes в качестве среды выполнения обеспечивает:
- **Автомасштабирование:** Ресурсы потребляются только во время выполнения задач.
- **Изоляция:** Каждая задача запускается в "чистом" контейнере, что исключает конфликты зависимостей.
- **Гибкость:** Возможность динамически назначать `requests/limits`, `nodeSelector` и `tolerations` для разных типов задач.

### Взаимодействие компонентов

1.  **Poll:** Раннер опрашивает GitLab по HTTPS (порт 443).
2.  **Schedule:** При получении задачи раннер через Kubernetes API создает под.
3.  **Execute:** Под выполняет шаги `script`, используя указанные образы.
4.  **Upload:** Результаты и кэш отправляются обратно в GitLab или во внешнее хранилище.

---

## Практические сценарии

### Стандартная установка через Helm

Рекомендуется использовать отдельный `namespace` для раннера и его рабочих подов.

```bash
# Добавление репозитория
helm repo add gitlab https://charts.gitlab.com/
helm repo update

# Установка с минимальными параметрами
helm upgrade --install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab-runner \
  --create-namespace \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerToken="glrt-YOUR_AUTHENTICATION_TOKEN" \
  --set rbac.create=true
```

### Настройка распределенного кэширования (S3/MinIO)

Без внешнего кэша данные между запусками на разных узлах будут теряться.

**Пример конфигурации в values.yaml:**

```yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "alpine:latest"
      [runners.cache]
        Type = "s3"
        Path = "gitlab-runner"
        Shared = true
        [runners.cache.s3]
          ServerAddress = "minio.example.com"
          BucketName = "runner-cache"
          BucketLocation = "us-east-1"
          Insecure = false
          AuthenticationType = "access-key"
```
*Примечание: Секреты (AccessKey/SecretKey) рекомендуется прокидывать через существующий Kubernetes Secret (`runners.cache.secretName`).*

### Оптимизация стоимости (Spot-инстанции)

Для экономии средств задачи CI/CD можно запускать на Spot-узлах (AWS) или Preemptible-узлах (GCP/Yandex).

**Настройка через values.yaml:**

```yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        [runners.kubernetes.node_selector]
          "node-role.kubernetes.io/ci-worker" = "true"
        [[runners.kubernetes.tolerations]]
          key = "spot-instance"
          operator = "Exists"
          effect = "NoSchedule"
```

### Безопасность и привилегии

По умолчанию раннер запускается с минимальными правами. Если требуется сборка Docker-образов, используйте **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md)** вместо привилегированного режима (DinD).

**Ограничение ресурсов для задач:**

```yaml
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        cpu_requests = "500m"
        memory_requests = "1Gi"
        cpu_limit = "2"
        memory_limit = "4Gi"
```

---

## Дополнительная информация

### См. также

- **[Обзор GitLab Runner и Executor](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_runners_executors.md)** — глубокая теория.
- **[Использование Docker-in-Docker](../../Docker/docker-in-docker.md)** — если Kaniko не подходит.
- **[Интеграция GitLab CI с Kubernetes](../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)** — настройка Агента и CI/CD.
- **[Регистрация Runner](../../CI-CD/GitLab_CI/Tutorials/runner_registration.md)** — подробнее о токенах и UI.
