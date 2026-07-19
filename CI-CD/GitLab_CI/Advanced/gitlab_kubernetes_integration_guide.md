# Интеграция GitLab CI/CD с Kubernetes

## Определения

**GitLab Agent for Kubernetes (KAS)** — основной инструмент для безопасной интеграции GitLab с кластером Kubernetes. Состоит из серверной части (**GitLab KAS**) и агента (**agentk**), устанавливаемого внутри кластера.

**CI/CD Tunnel** — механизм, позволяющий CI/CD-задачам GitLab взаимодействовать с API кластера Kubernetes через защищенное соединение Агента, без необходимости экспонировать API-сервер в интернет.

**GitOps (Pull-модель)** — метод развертывания, при котором Агент GitLab самостоятельно отслеживает изменения в репозитории с манифестами и синхронизирует состояние кластера с Git.

**Устаревшие методы**: Интеграция на основе сертификатов (Certificate-based integration) и использование долгоживущих токенов `KUBECONFIG` в переменных. **Не рекомендуется к использованию.**

## Основные концепции

### Стратегии интеграции (GitLab 17+)

| Метод | Тип | Механизм | Преимущества |
| :--- | :--- | :--- | :--- |
| **CI/CD Tunnel** | Push-модель | GitLab Runner → KAS → Agent → K8s API | Гибкость пайплайнов, отсутствие секретов в CI. |
| **GitOps** | Pull-модель | Agent → Git Repo → K8s API | Высокая безопасность, автоматический дрейф-контроль. |
| **OIDC (ID Tokens)** | Push-модель | GitLab Runner → Cloud provider → K8s API | Бесшовная интеграция с AWS EKS, GCP GKE через роли. |

### Безопасный доступ через CI/CD Tunnel

При использовании Агента CI/CD задачи получают доступ к кластеру через автоматически настраиваемый контекст. Вам не нужно хранить `KUBECONFIG` в переменных проекта.
1. Пайплайн запускается на любом Runner'е.
2. GitLab предоставляет временный токен доступа.
3. Задача подключается к кластеру через `kas-address`.

### Аутентификация через OIDC (ID Tokens)

С версии **GitLab 17.0** вместо устаревших `CI_JOB_JWT_TOKEN` используются **`id_tokens`**. Это позволяет кластеру (или облачному провайдеру) валидировать идентичность пайплайна и выдавать временные права доступа.

```yaml
# Пример декларации ID токена
deploy:
  id_tokens:
    GITLAB_OIDC_TOKEN:
      aud: https://gitlab.example.com
```

## Практические сценарии

### Сценарий 1: Настройка GitLab Agent и CI/CD Tunnel

1. **Регистрация Агента**:
   - Перейдите в **Operate > Kubernetes clusters**.
   - Нажмите **Connect a cluster** и выберите **Create a new agent**.
   - Скопируйте команду установки Helm.

2. **Установка в кластер**:
   ```bash
   helm upgrade --install gitlab-agent gitlab/gitlab-agent \
     --namespace gitlab-agent \
     --create-namespace \
     --set config.token=<YOUR_AGENT_TOKEN> \
     --set config.kasAddress=wss://kas.gitlab.example.com
   ```

3. **Использование в пайплайне**:
   ```yaml
   deploy:
     image: line/kubectl:latest
     script:
       # Выбор контекста агента (формат: путь/к/проекту:имя-агента)
       - kubectl config use-context path/to/project:my-agent
       - kubectl get pods
   ```

### Сценарий 2: Настройка GitOps (Pull-модель)

Для синхронизации манифестов без прямого участия пайплайна:
1. Создайте файл конфигурации агента в репозитории: `.gitlab/agents/my-agent/config.yaml`.
2. Опишите проекты для синхронизации:
   ```yaml
   gitops:
     manifest_projects:
       - id: path/to/manifest-repo
         paths:
           - glob: 'manifests/*.yaml'
   ```
3. Агент автоматически применит изменения при пуше в указанный репозиторий.

### Сценарий 3: Развертывание через Helm с OIDC

Если кластер поддерживает OIDC-аутентификацию (например, через Vault или Cloud IAM):

```yaml
deploy_helm:
  id_tokens:
    K8S_TOKEN:
      aud: k8s-cluster-audience
  variables:
    KUBE_CONTEXT: path/to/project:my-agent
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - helm upgrade --install my-release ./charts
```

## Дополнительная информация

### Безопасность и RBAC

- **Принцип наименьших привилегий**: Назначайте Агенту и его `ServiceAccount` только те права, которые необходимы для работы (избегайте `cluster-admin`).
- **Имперсонация**: Используйте механизм `access_as` в конфигурации агента, чтобы ограничить права доступа CI/CD задач до уровня конкретных пользователей или групп.
- **Секреты**: Для управления секретами в Kubernetes рекомендуется использовать **[Sealed Secrets](../../../Kubernetes/Security/sealed_secrets_overview.md)** или интеграцию с **[Vault](../Tutorials/vault_kubernetes_integration.md)**.

### Устранение неполадок

- **Ошибка подключения к KAS**: Проверьте сетевую доступность `kasAddress` изнутри кластера (особенно если используется самоподписанный сертификат).
- **Контекст не найден**: Убедитесь, что имя проекта и имя агента указаны верно, и что проект, в котором запущен пайплайн, имеет доступ к агенту (настраивается в `config.yaml`).
- **RBAC Forbidden**: Проверьте `RoleBinding` для `ServiceAccount`, под которым работает агент в целевом namespace.

### См. также

- **[Обзор GitLab Runner и Executor](./gitlab_ci_runners_executors.md)** — выбор среды выполнения (Kubernetes Executor).
- **[GitOps: Обзор методологии](../../../GitOps/GitOps_overview.md)** — принципы Pull-модели.
- **[Установка GitLab Runner в Kubernetes](../../../Kubernetes/Installation/gitlab_runner_kubernetes_installation.md)** — деплой исполнителя.
