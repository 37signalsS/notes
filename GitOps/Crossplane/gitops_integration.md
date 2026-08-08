# Crossplane: Интеграция с GitOps

## Определения

**GitOps для инфраструктуры** — это операционная модель, при которой Git-репозиторий является единственным источником правды (SSoT) для всей декларативной конфигурации инфраструктуры. Crossplane выступает в роли исполнительного механизма (Control Plane), предоставляя Kubernetes-native API для облачных ресурсов, а GitOps-инструменты (Argo CD, Flux) обеспечивают автоматическую доставку и синхронизацию этого состояния.

В 2026 году эта связка является стандартом для построения **Internal Developer Platforms (IDP)**, позволяя разработчикам запрашивать инфраструктуру через абстрактные Claims без прямого доступа к облачным консолям.

## Базовые концепции

### Архитектура и разделение ответственности

Эффективная интеграция строится на разделении репозиториев по ролям (Separation of Concerns):

1.  **Платформенный репозиторий (Platform Repo):**
    *   **Содержимое:** `CompositeResourceDefinitions` (XRD), `Compositions`, функции композиции, настройки провайдеров (`ProviderConfig`).
    *   **Владелец:** Команда платформы (SRE/Platform Engineers).
    *   **Задача:** Определение корпоративных стандартов и "золотых путей" (Golden Paths) инфраструктуры.
2.  **Репозиторий приложений (Application Repo):**
    *   **Содержимое:** `CompositeResourceClaims` (Claims) — запросы на конкретные ресурсы (БД, S3, очереди).
    *   **Владелец:** Команды разработки.
    *   **Задача:** Использование инфраструктуры как зависимости приложения.

### Схема взаимодействия

```text
┌─────────────────┐      ┌───────────────┐      ┌────────────────┐      ┌──────────────┐
│  Git (Claims)   │─────▶│   Argo CD     │─────▶│   Crossplane   │─────▶│   Облако     │
│  (App Repo)     │      │   (Sync)      │      │  (Reconcile)   │      │   (API)      │
└─────────────────┘      └───────────────┘      └────────────────┘      └──────────────┘
         │                       │                       │                      │
    1. Коммит Claim         2. Применение          3. Создание MR          4. Ресурс
       в Git                   в кластер              в облаке                готов
```

### Поддерживаемые инструменты

| Инструмент | Преимущества в связке с Crossplane | Рекомендация |
| :--- | :--- | :--- |
| **Argo CD** | Отличная визуализация иерархии (Claim -> XR -> MR). Нативная поддержка `ApplicationSet`. | Для централизованных Control Plane с UI. |
| **Flux** | Нативная поддержка OCI-репозиториев (Crossplane Packages), интеграция с SOPS. | Для распределенных систем и Edge-кластеров. |

## Управление секретами

В GitOps-процессе секреты (пароли БД, ключи доступа) не должны храниться в Git в открытом виде.

### External Secrets Operator (ESO) + HashiCorp Vault
*   **Workflow:** Crossplane создает базу данных -> записывает учетные данные в K8s Secret -> ESO синхронизирует этот секрет в Vault для долгосрочного хранения или другие приложения запрашивают его из Vault.
*   **Плюс:** Централизованное управление и безопасная ротация секретов.

### Mozilla SOPS
*   **Workflow:** Конфиденциальные манифесты (например, `ProviderConfig` с API-ключами) шифруются в Git. GitOps-контроллер расшифровывает их "на лету" перед применением.
*   **Плюс:** Простота, секреты хранятся рядом с кодом в зашифрованном виде.

## Практические сценарии

### Сценарий 1: Argo CD + Crossplane Claim (Рекомендуемый подход)

Вместо управления низкоуровневыми ресурсами, разработчики используют `Claim`.

1.  **Создание Claim в Git (App Repo):**

    ```yaml
    apiVersion: database.example.org/v1alpha1
    kind: PostgreSQLInstance
    metadata:
      name: inventory-db
      namespace: production
    spec:
      parameters:
        storageGB: 20
        version: "15"
      compositionSelector:
        matchLabels:
          provider: yandex-cloud
          tier: production
      writeConnectionSecretToRef:
        name: db-conn-secret
    ```

2.  **Настройка Argo CD Application:**

    ```yaml
    apiVersion: argoproj.io/v1alpha1
    kind: Application
    metadata:
      name: app-infrastructure
      namespace: argocd
    spec:
      project: default
      source:
        repoURL: https://github.com/org/app-infra-gitops.git
        targetRevision: main
        path: infrastructure/production
      destination:
        server: https://kubernetes.default.svc
        namespace: production
      syncPolicy:
        automated:
          prune: true
          selfHeal: true # Автоматическое исправление дрейфа в кластере
    ```

### Сценарий 2: Масштабирование через ApplicationSet

Для управления множеством окружений (dev, staging, prod) используйте генераторы.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: platform-stacks
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - env: dev
            cluster: in-cluster
          - env: prod
            cluster: prod-cluster-url
  template:
    metadata:
      name: '{{env}}-stack'
    spec:
      project: default
      source:
        repoURL: https://github.com/org/platform-manifests.git
        targetRevision: main
        path: 'stacks/{{env}}'
      destination:
        server: '{{cluster}}'
        namespace: crossplane-system
```

### Сценарий 3: Динамические окружения (Review Apps)

Связка ApplicationSet + Crossplane позволяет автоматически создавать полные стеки (приложение + БД) для каждой ветки разработчика. Подробное руководство: **[ArgoCD: Динамические окружения с Crossplane](../ArgoCD/dynamic_environments_crossplane.md)**.

## Передовые практики (2026)

### Валидация в CI (Pre-flight checks)
Перед синхронизацией манифестов в кластер необходимо проверить их корректность:
*   `crossplane render` — локальный рендеринг композиции для проверки итоговых Managed Resources.
*   `crossplane beta validate` — проверка манифестов на соответствие схемам CRD и политикам безопасности.

### Доставка через OCI-артефакты
Вместо хранения сырых YAML-файлов композиций в Git, рекомендуется упаковывать их в **Crossplane Configuration Packages** и публиковать в OCI-реестр.
*   Это обеспечивает версионирование инфраструктурных модулей аналогично Helm-чартам.
*   Flux или Argo CD отслеживают новые версии пакетов и обновляют ресурс `Configuration`.

### Настройка Health Checks в Argo CD
Для корректного отображения статуса Crossplane-ресурсов (Claims) в интерфейсе Argo CD необходимо добавить кастомные проверки здоровья в `resourceHealthChecks`:

```yaml
resource.customizations.health.database.example.org_PostgreSQLInstance: |
  hs = {}
  if obj.status ~= nil and obj.status.conditions ~= nil then
    for i, condition in ipairs(obj.status.conditions) do
      if condition.type == "Ready" and condition.status == "True" then
        hs.status = "Healthy"
        hs.message = condition.message
        return hs
      end
    end
  end
  hs.status = "Progressing"
  hs.message = "Waiting for resource to be ready"
  return hs
```

### Политики удаления (Deletion Policy)
В GitOps важно явно определять поведение при удалении манифеста из Git:
*   `DeletionPolicy: Delete` (по умолчанию) — физическое удаление ресурса в облаке.
*   `DeletionPolicy: Orphan` — удаление только объекта в Kubernetes. Рекомендуется для критических БД в Prod, чтобы избежать случайного удаления при ошибках в GitOps-пайплайне.

## Исправление дрейфа (Drift Detection)

Связка Crossplane + GitOps обеспечивает двухуровневую защиту от изменений вручную:

1.  **Уровень GitOps (Argo CD/Flux):** Если кто-то изменит манифест Crossplane в кластере через `kubectl edit`, GitOps-инструмент обнаружит расхождение с Git и вернет состояние манифеста к эталонному.
2.  **Уровень Crossplane:** Если кто-то изменит параметры ресурса напрямую в консоли облака, контроллер Crossplane обнаружит расхождение с манифестом и вернет параметры в облаке к описанным в YAML.

## Дополнительная информация

*   Обзор Crossplane: [Crossplane Overview](./overview.md)
*   Настройка провайдеров: [Yandex Cloud Setup](./provider_yandex_cloud_setup.md), [Kubernetes Setup](./provider_kubernetes_setup.md)
*   Инструменты GitOps: [Argo CD Overview](../ArgoCD/argocd_overview.md), [Flux Overview](../flux.md)

Внешние ресурсы:
* [Crossplane GitOps Workflows](https://docs.crossplane.io/latest/concepts/gitops/)
* [Argo CD Health Checks](https://argo-cd.readthedocs.io/en/stable/operator-manual/health-checks/)
