# Интеграция GitLab CI/CD с Kubernetes

## Определения

**GitLab Agent for Kubernetes (KAS)** — основной и единственный рекомендуемый метод интеграции GitLab с кластерами Kubernetes (начиная с версий 17.x/18.x). Система состоит из серверного компонента (**GitLab KAS**) и агента (**agentk**), работающего внутри кластера по Pull-модели.

**CI/CD Tunnel** — защищенный GRPC-туннель, позволяющий CI/CD-задачам GitLab взаимодействовать с API кластера Kubernetes напрямую. Исключает необходимость хранения `KUBECONFIG` в переменных и экспонирования API кластера в интернет.

**Workload Identity Federation (OIDC/WIF)** — модель безопасности **Zero Trust**, при которой GitLab Runner получает временный JWT-токен (`id_tokens`) для федеративной аутентификации в облаках (AWS EKS, GKE, Azure AKS) без использования статических секретов.

**GitLab Workspaces** — функционал (v16.x–19.x) для предоставления разработчикам облачных сред разработки (Cloud IDE) внутри кластера Kubernetes, управляемых через Агент.

## Основные концепции

### Стратегии интеграции (GitLab 18.x/19.x)

| Метод | Тип | Технология | Основной сценарий |
| :--- | :--- | :--- | :--- |
| **CI/CD Tunnel** | Push-модель | KAS + `kubectl`/`helm` | Динамический деплой, администрирование, Review Apps. |
| **GitOps (Native)** | Pull-модель | KAS + Git Sync | Простая синхронизация манифестов из репозитория. |
| **GitOps (Flux)** | Pull-модель | Flux v2 + GitLab UI | Enterprise-стандарт с визуализацией состояния в GitLab. |
| **OIDC (WIF)** | Push-модель | `id_tokens` + IAM | Максимальная безопасность в публичных облаках. |

### Контексты доступа и иерархия

Связь пайплайна с кластером устанавливается через переменную `KUBE_CONTEXT`.
**Формат:** `путь/к/проекту-конфигурации:имя-агента`
**Пример:** `ops/k8s-infra:production-agent`

Если агент находится в отдельном «инфраструктурном» проекте, необходимо разрешить доступ в его `config.yaml`:
```yaml
# .gitlab/agents/production-agent/config.yaml
ci_access:
  projects:
    - id: web-apps/frontend
  groups:
    - id: backend-services
```

## Практические сценарии

### Сценарий 1: Деплой через CI/CD Tunnel с имперсонацией (RBAC)

Использование механизма `access_as` для ограничения прав пайплайна до уровня пользователя.

```yaml
# В пайплайне приложения (.gitlab-ci.yml)
deploy_app:
  stage: deploy
  image: 
    name: line/kubectl-kustomize:latest
  variables:
    KUBE_CONTEXT: "ops/infra:my-agent"
  script:
    - kubectl config use-context $KUBE_CONTEXT
    - kubectl apply -f manifests/ --namespace $CI_PROJECT_NAME
```

**Настройка агента (config.yaml):**
```yaml
ci_access:
  projects:
    - id: my-app/repo
      access_as:
        user: {} # Пайплайн получит права пользователя, запустившего его
```

### Сценарий 2: Аутентификация в облаке AWS через OIDC

Исключение использования статических `AWS_ACCESS_KEY_ID`.

```yaml
deploy:aws:
  image: amazon/aws-cli:latest
  id_tokens:
    GITLAB_OIDC_TOKEN:
      aud: https://gitlab.com
  variables:
    ROLE_ARN: "arn:aws:iam::123456789012:role/GitLabDeployer"
  script:
    - >
      export $(printf "AWS_ACCESS_KEY_ID=%s AWS_SECRET_ACCESS_KEY=%s AWS_SESSION_TOKEN=%s"
      $(aws sts assume-role-with-web-identity
      --role-arn ${ROLE_ARN}
      --role-session-name "GitLabCI-${CI_PIPELINE_ID}"
      --web-identity-token ${GITLAB_OIDC_TOKEN}
      --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]'
      --output text))
    - aws eks update-kubeconfig --name prod-cluster
    - helm upgrade --install my-app ./chart
```

### Сценарий 3: Интеграция с Flux v2 (Enterprise GitOps)

GitLab v18.x обеспечивает нативную поддержку Flux с отображением ресурсов в UI.

1.  **Bootstrap Flux** в кластере (рекомендуется через GitLab Runner):
    ```bash
    flux bootstrap gitlab \
      --owner=my-group \
      --repository=infra-gitops \
      --branch=main \
      --path=clusters/prod-cluster \
      --personal
    ```
2.  **Визуализация**: В интерфейсе GitLab перейдите в **Operate > Kubernetes clusters**. Выберите ваш агент для просмотра состояния синхронизации (Kustomizations, HelmReleases).

### Сценарий 4: Настройка сред разработки (GitLab Workspaces)

1.  **Условие**: Наличие Ingress-контроллера с поддержкой Wildcard (например, `*.workspaces.example.com`).
2.  **Конфигурация агента**:
    ```yaml
    remote_development:
      enabled: true
      dns_zone: workspaces.example.com
    ```
3.  **Использование**: Разработчик может запустить Workspace непосредственно из Web IDE или раздела **Operate > Workspaces**.

## Безопасность и RBAC

1.  **Принцип наименьших привилегий**: Никогда не назначайте ServiceAccount агента роль `cluster-admin`. Используйте RoleBindings для ограничения доступа конкретными неймспейсами.
2.  **Защита туннеля**: Ограничивайте сетевой доступ `agentk` к KAS через Network Policies.
3.  **Имперсонация**: Механизм `access_as: { agent: {} }` (по умолчанию) использует права агента, в то время как `user: {}` или `service_account: { name: ... }` обеспечивают более гранулярный контроль.

## Устранение неполадок (Troubleshooting)

### Типичные ошибки
-   **`Context not found`**: 
    -   Пайплайн запущен в проекте, который не добавлен в `ci_access` агента.
    -   Имя проекта или агента в `KUBE_CONTEXT` указано неверно (чувствительно к регистру).
-   **`GRPC: connection error`**: Проблема сетевой связности между `agentk` и GitLab KAS. Проверьте настройки прокси и доступность порта 443/wss.
-   **`RBAC: forbidden`**: Права ServiceAccount агента в кластере недостаточны для выполнения `kubectl` команд. Проверьте логи агента: `kubectl logs -n gitlab-agent -l app=gitlab-agent`.

### Команды диагностики
-   `kubectl config get-contexts` — внутри CI задачи для проверки активных туннелей.
-   `glab cluster agent list` — проверка статуса агентов через GitLab CLI.

## Дополнительная информация

### См. также
-   **[Обзор GitLab Runner и Executor](./gitlab_ci_runners_executors.md)** — выбор между Kubernetes и Docker executors.
-   **[GitOps: Обзор методологии](../../../GitOps/GitOps_overview.md)** — принципы Pull-модели.
-   **[Интеграция GitLab CI и Vault](../Tutorials/vault_kubernetes_integration.md)** — использование OIDC для получения секретов.
-   **[Установка GitLab Runner в Kubernetes](../../../Kubernetes/Installation/gitlab_runner_kubernetes_installation.md)** — детальное руководство по Helm-чарту.
-   **[Sealed Secrets](../../../Kubernetes/Security/sealed_secrets_overview.md)** — управление секретами в GitOps.
