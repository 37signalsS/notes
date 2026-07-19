# Установка GitLab Runner в Kubernetes

Руководство по развертыванию GitLab Runner в кластере Kubernetes при помощи официального Helm-чарта.

## Определения

| Термин | Описание |
|--------|----------|
| **GitLab Runner** | Приложение, которое работает с GitLab CI/CD для выполнения заданий в конвейере. |
| **Kubernetes Executor** | Тип исполнителя, позволяющий запускать каждое задание в отдельном поде Kubernetes. |
| **Authentication Token** | Токен (префикс `glrt-`), связывающий Runner с инстансом GitLab. Создается в UI GitLab (с версии 16.0). |
| **RBAC** | Метод регулирования доступа к ресурсам кластера, необходимый раннеру для создания подов. |

## Основные концепции

### Преимущества Kubernetes Executor

- **Динамическое масштабирование**: Поды создаются только на время задания.
- **Изоляция**: Каждое задание выполняется в чистом окружении.
- **Гибкость**: Настройка ресурсов (CPU/Memory) для каждой задачи.

### Предварительные требования

1. **GitLab URL**: Адрес вашего инстанса.
2. **Runner Token**: Получите токен аутентификации в GitLab (`Settings > CI/CD > Runners`). См. **[Регистрацию Runner](../Tutorials/runner_registration.md)**.
3. **Helm**: Версия 3.x.

## Практические сценарии

### Стандартная установка через Helm

GitLab Runner рекомендуется устанавливать в отдельное пространство имен.

```bash
# Добавление репозитория
helm repo add gitlab https://charts.gitlab.com/
helm repo update

# Установка (используйте runnerToken для GitLab 16.0+)
helm upgrade --install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab \
  --create-namespace \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerToken="glrt-YOUR_AUTHENTICATION_TOKEN" \
  --set rbac.create=true
```

### Настройка для Docker-in-Docker (DinD)

Для сборки образов внутри CI-задач требуется включить привилегированный режим. 
**Внимание:** Это снижает безопасность кластера. Рекомендуется использовать **[Kaniko](../../Docker/Dockerfile/dockerfile_kaniko.md)**.

```bash
helm upgrade --install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerToken="glrt-YOUR_TOKEN" \
  --set runners.privileged=true \
  --set rbac.create=true
```

### Конфигурация через values.yaml

Пример `custom-runner-values.yaml`:

```yaml
gitlabUrl: https://gitlab.example.com
runnerToken: "glrt-YOUR_TOKEN"
rbac:
  create: true
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "alpine:latest"
        privileged = false
        cpu_requests = "100m"
        memory_requests = "128Mi"
        service_account_overwrite_allowed = ".*"
```

Применение:
```bash
helm upgrade --install gitlab-runner gitlab/gitlab-runner -f custom-runner-values.yaml -n gitlab
```

## Дополнительная информация

### См. также

- **[Обзор GitLab Runner и Executor](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_runners_executors.md)**
- **[Использование Docker-in-Docker](../../Docker/docker-in-docker.md)**
- **[Интеграция GitLab CI с Kubernetes](../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)**
