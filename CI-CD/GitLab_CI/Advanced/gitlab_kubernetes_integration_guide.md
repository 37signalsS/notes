# Интеграция GitLab CI/CD с Kubernetes

## Определения

**GitLab Agent for Kubernetes (KAS)** — основной инструмент для безопасной интеграции GitLab с кластером Kubernetes. Состоит из серверной части (**GitLab KAS**) и агента (**agentk**), устанавливаемого внутри кластера.

**CI/CD Tunnel** — механизм, позволяющий CI/CD-задачам GitLab взаимодействовать с API кластера Kubernetes через защищенное соединение Агента, без необходимости экспонирования API-сервера в интернет.

**Workload Identity Federation (OIDC)** — современный стандарт аутентификации, позволяющий GitLab Runner получать временные учетные данные облачных провайдеров (AWS, GCP, Azure) на основе JWT-токенов (`id_tokens`).

**GitLab Workspaces** — функционал (GitLab 16.0+), позволяющий запускать полноценные среды разработки (Cloud IDE) внутри кластера Kubernetes через Агент.

## Основные концепции

### Стратегии интеграции (GitLab 17+)

| Метод | Тип | Механизм | Преимущества |
| :--- | :--- | :--- | :--- |
| **CI/CD Tunnel** | Push-модель | Runner → KAS → Agent → K8s API | Гибкость пайплайнов, использование Helm/Kubectl напрямую. |
| **GitOps (Native)** | Pull-модель | Agent → Git Repo → K8s API | Простота настройки, встроенный в GitLab дрейф-контроль. |
| **GitOps (External)** | Pull-модель | Git Repo ← **Flux/ArgoCD** | Профессиональный стандарт для сложных инфраструктур. |
| **OIDC (ID Tokens)** | Push-модель | Runner → Cloud IAM → K8s API | Безопасность без долгоживущих секретов (AWS EKS, GKE). |

### Иерархия доступа и контексты

Доступ к кластеру в пайплайне осуществляется через переменную `KUBE_CONTEXT`. Формат контекста:
`путь/к/проекту-конфигурации:имя-агента`

**Пример:** `infra/k8s-connection:prod-agent`

Если агент настроен в другом проекте, необходимо явно разрешить доступ в файле `config.yaml` агента:
```yaml
# .gitlab/agents/my-agent/config.yaml
ci_access:
  projects:
    - id: path/to/app-project
  groups:
    - id: path/to/app-group
```

## Практические сценарии

### Сценарий 1: Настройка аутентификации в AWS EKS через OIDC

Использование `id_tokens` для получения временных прав в AWS без хранения `AWS_ACCESS_KEY_ID`.

```yaml
deploy_eks:
  image: amazon/aws-cli:latest
  id_tokens:
    GITLAB_OIDC_TOKEN:
      aud: https://gitlab.example.com
  variables:
    ROLE_ARN: "arn:aws:iam::123456789012:role/GitLabDeployRole"
  script:
    - >
      export $(printf "AWS_ACCESS_KEY_ID=%s AWS_SECRET_ACCESS_KEY=%s AWS_SESSION_TOKEN=%s"
      $(aws sts assume-role-with-web-identity
      --role-arn ${ROLE_ARN}
      --role-session-name "GitLabCI-${CI_PIPELINE_ID}"
      --web-identity-token ${GITLAB_OIDC_TOKEN}
      --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]'
      --output text))
    - aws eks update-kubeconfig --name my-cluster
    - kubectl get pods
```

### Сценарий 2: Интеграция с Flux (GitLab 17.x)

GitLab официально поддерживает интеграцию с **Flux** для реализации Enterprise-уровня GitOps.

1.  **Генерация токена**: Создайте Project Access Token с правами `write_repository`.
2.  **Flux Bootstrap**:
    ```bash
    flux bootstrap gitlab \
      --owner=my-group \
      --repository=my-repo \
      --branch=main \
      --path=clusters/my-cluster
    ```
3.  **Визуализация**: Состояние ресурсов Flux отображается непосредственно в интерфейсе GitLab в разделе **Operate > Kubernetes clusters**.

### Сценарий 3: Настройка GitLab Workspaces

Для предоставления разработчикам изолированных сред в K8s:
1. Включите Workspaces в настройках группы.
2. Настройте Ingress-контроллер с поддержкой wildcard-доменов.
3. Добавьте в `config.yaml` агента блок `remote_development`.

## Дополнительная информация

### Безопасность и RBAC

- **Access As**: Используйте директиву `access_as: { agent: {} }` для выполнения задач от имени ServiceAccount агента или `access_as: { user: {} }` для ограничения прав до уровня запустившего пайплайн пользователя.
- **Network Policies**: Обязательно ограничивайте сетевой доступ `agentk` внутри кластера, так как он имеет доступ к API-серверу.

### Устранение неполадок

1. **KAS Connectivity**:
   ```bash
   # Проверка логов агента на наличие ошибок авторизации
   kubectl logs -n gitlab-agent -l app=gitlab-agent
   ```
2. **Context Not Found**:
   - Проверьте, что проект с конфигурацией агента публичный или проект с пайплайном добавлен в `ci_access`.
   - Выполните `kubectl config get-contexts` внутри CI-задачи для проверки доступных туннелей.

### См. также

- **[Обзор GitLab Runner и Executor](./gitlab_ci_runners_executors.md)** — выбор среды выполнения.
- **[GitOps: Обзор методологии](../../../GitOps/GitOps_overview.md)** — принципы Pull-модели.
- **[Интеграция GitLab CI и Vault](../Tutorials/vault_kubernetes_integration.md)** — управление секретами.
- **[Установка GitLab Runner в Kubernetes](../../../Kubernetes/Installation/gitlab_runner_kubernetes_installation.md)** — деплой исполнителя.

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
