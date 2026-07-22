# Crossplane: Интеграция с GitOps

## Определения

**GitOps для инфраструктуры** — это операционная модель, при которой Git-репозиторий является единственным источником правды (SSoT) для всей декларативной конфигурации инфраструктуры. Crossplane выступает в роли "движка" управления облаком, предоставляя Kubernetes-native API, а GitOps-инструменты (Argo CD, Flux) обеспечивают автоматическую доставку и синхронизацию этого состояния.

В 2026 году эта связка является основой для построения **Internal Developer Platforms (IDP)**, позволяя разработчикам запрашивать инфраструктуру через стандартные Kubernetes-манифесты без прямого доступа к облачным консолям.

## Базовые концепции

### Архитектура и разделение ответственности

Эффективная интеграция Crossplane и GitOps строится на разделении репозиториев по ролям:

1.  **Платформенный репозиторий (Platform Repo):**
    *   **Контент:** `CompositeResourceDefinitions` (XRD), `Compositions`, функции композиции.
    *   **Владелец:** Команда платформы (SRE/DevOps).
    *   **Задача:** Определение "золотых стандартов" инфраструктуры (например, "стандартный PostgreSQL").
2.  **Репозиторий инфраструктуры/приложений (App/Infra Repo):**
    *   **Контент:** `Claims` (XRC) — запросы на создание конкретных ресурсов.
    *   **Владелец:** Команды разработки.
    *   **Задача:** Потребление инфраструктуры через высокоуровневые абстракции.

### Схема взаимодействия

```
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
| **Argo CD** | Превосходная визуализация иерархии ресурсов (Claim -> XR -> MR). Нативная поддержка `ApplicationSet`. | Для централизованных Control Plane с UI. |
| **Flux** | Модульность, нативная поддержка OCI-артефактов, интеграция с SOPS "из коробки". | Для распределенных систем и Edge-кластеров. |

## Управление секретами

В GitOps-процессе секреты (пароли БД, ключи доступа) требуют особого подхода. В 2026 году используются следующие паттерны:

### 1. External Secrets Operator (ESO) + HashiCorp Vault
*   **Workflow:** Crossplane создает базу данных -> записывает учетные данные в K8s Secret -> ESO синхронизирует этот секрет в Vault для долгосрочного хранения или другие приложения запрашивают его из Vault.
*   **Плюс:** Централизованное управление и ротация секретов.

### 2. Mozilla SOPS
*   **Workflow:** Секреты (например, манифест `ProviderConfig`) шифруются в Git с помощью SOPS.
*   **Плюс:** Секреты хранятся рядом с кодом, но в безопасности. Flux расшифровывает их автоматически перед применением.

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

## Исправление дрейфа (Drift Detection)

Связка Crossplane + GitOps обеспечивает двухуровневую защиту от изменений вручную:

1.  **Уровень GitOps (Argo CD/Flux):** Если кто-то изменит манифест Crossplane в кластере через `kubectl edit`, GitOps-инструмент обнаружит расхождение с Git и вернет состояние манифеста к эталонному.
2.  **Уровень Crossplane:** Если кто-то изменит параметры ресурса напрямую в консоли Yandex Cloud, контроллер Crossplane обнаружит расхождение с манифестом и вернет параметры в облаке к описанным в YAML.

## Дополнительная информация

*   Обзор Crossplane: [Crossplane Overview](./overview.md)
*   Настройка провайдера Yandex: [Yandex Cloud Setup](./provider_yandex_cloud_setup.md)
*   Инструменты GitOps: [Argo CD Overview](../ArgoCD/argocd_overview.md), [Flux Overview](../flux.md)

Внешние ресурсы:
* [Crossplane GitOps Workflows](https://docs.crossplane.io/latest/concepts/gitops/)
* [Argo CD Best Practices](https://argo-cd.readthedocs.io/en/stable/operator-manual/best-practices/)
