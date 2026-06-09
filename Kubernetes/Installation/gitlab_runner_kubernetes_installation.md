# Установка GitLab Runner в Kubernetes

Руководство по развертыванию GitLab Runner в кластере Kubernetes при помощи официального Helm-чарта.

---

## Определения

| Термин | Описание |
|--------|----------|
| **GitLab Runner** | Приложение с открытым исходным кодом, которое работает с GitLab CI/CD для выполнения заданий в конвейере (pipeline). |
| **Kubernetes Executor** | Тип исполнителя (executor), который позволяет GitLab Runner запускать каждое задание в отдельном поде Kubernetes. |
| **Registration Token** | Уникальный ключ, используемый для регистрации нового раннера в инстансе GitLab. |
| **RBAC (Role-Based Access Control)** | Метод регулирования доступа к ресурсам кластера Kubernetes, необходимый раннеру для создания подов с заданиями. |

---

## Основные концепции

### Преимущества Kubernetes Executor

Использование GitLab Runner внутри Kubernetes предоставляет следующие возможности:

- **Динамическое масштабирование**: Поды создаются только на время выполнения задания и удаляются сразу после его завершения.
- **Изоляция**: Каждое задание выполняется в чистом окружении, что исключает влияние задач друг на друга.
- **Гибкость**: Для каждой задачи можно указать свои образы (Docker images) и требования к ресурсам.

### Предварительные требования

Для успешной установки необходимо подготовить:

1. **GitLab URL**: Адрес вашего инстанса GitLab (например, `https://gitlab.example.com`).
2. **Registration Token**: Находится в GitLab в разделе `Settings > CI/CD > Runners`.
3. **Helm**: Установленный пакетный менеджер версии 3.x.

---

## Практические сценарии

### Стандартная установка через Helm

GitLab Runner рекомендуется устанавливать в отдельное пространство имен.

```bash
# Добавление официального репозитория
helm repo add gitlab https://charts.gitlab.com/
helm repo update

# Установка раннера
helm upgrade --install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab \
  --create-namespace \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerRegistrationToken="YOUR_REGISTRATION_TOKEN" \
  --set rbac.create=true
```

### Настройка для Docker-in-Docker (DinD)

Для сборки Docker-образов внутри CI-задач требуется включить привилегированный режим.

**Внимание:** Привилегированный режим снижает безопасность кластера.

```bash
helm upgrade --install gitlab-runner gitlab/gitlab-runner \
  --namespace gitlab \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerRegistrationToken="YOUR_REGISTRATION_TOKEN" \
  --set runners.privileged=true \
  --set rbac.create=true
```

### Конфигурация через values.yaml

Для сложной настройки рекомендуется использовать файл `values.yaml`:

```yaml
# custom-runner-values.yaml
gitlabUrl: https://gitlab.example.com
runnerRegistrationToken: "YOUR_REGISTRATION_TOKEN"
rbac:
  create: true
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "ubuntu:22.04"
        privileged = true
        cpu_requests = "100m"
        memory_requests = "128Mi"
        service_account_overwrite_allowed = ".*"
```

Применение конфигурации:

```bash
helm upgrade --install gitlab-runner gitlab/gitlab-runner -f custom-runner-values.yaml -n gitlab
```

---

## Дополнительная информация

### См. также

- [Обзор GitLab Runners и Executor'ов](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_runners_executors.md)
- [Использование Docker-in-Docker (DinD)](../../Docker/docker-in-docker.md)
- [Интеграция GitLab CI с Kubernetes](../../CI-CD/GitLab_CI/Advanced/gitlab_kubernetes_integration_guide.md)
