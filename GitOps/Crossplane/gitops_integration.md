# Crossplane: Интеграция с GitOps

## Определения

**GitOps для инфраструктуры** — подход, при котором Git-репозиторий становится единым источником правды как для приложений, так и для инфраструктуры. Crossplane предоставляет декларативный API для управления облачными ресурсами, а GitOps-инструменты автоматизируют доставку и синхронизацию.

## Базовые концепции

### Архитектура интеграции

Crossplane идеально вписывается в методологию GitOps. В этой парадигме Git-репозиторий становится единым источником правды как для приложений, так и для инфраструктуры. **Argo CD** выступает в роли оператора, который отслеживает изменения в Git, обнаруживает новые или измененные манифесты ресурсов Crossplane и применяет их в кластере. Затем Crossplane берет на себя задачу по приведению реальной облачной инфраструктуры в соответствие с этими манифестами.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│     Git     │────▶│   ArgoCD    │────▶│ Crossplane  │────▶│   Cloud     │
│  Repository │     │  (Sync)     │     │ (Reconcile) │     │   API       │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
      │                   │                   │                   │
      │ 1. Коммит         │                   │                   │
      │    манифеста      │                   │                   │
      └──────────────────▶│                   │                   │
                          │ 2. Detect change  │                   │
                          │    & Apply        │                   │
                          └──────────────────▶│                   │
                                              │ 3. Create/Update  │
                                              │    Cloud Resource │
                                              └──────────────────▶│
                                                                  │
                          ◀───────────────────────────────────────┘
                          5. Status Update      4. Status Response
```

### Поддерживаемые GitOps-инструменты

| Инструмент | Поддержка | Особенности |
| :--- | :--- | :--- |
| **ArgoCD** | Полная | Нативная синхронизация CRD, Application, ApplicationSet |
| **Flux** | Полная | Kustomize Controller, Helm Controller для Crossplane манифестов |

Обзор Crossplane и его возможностей см. в [Crossplane: Обзор](./overview.md).

## Практические сценарии

### Сценарий 1: ArgoCD + Crossplane для управления инфраструктурой

1. **Создание манифеста Crossplane в Git:**

   ```yaml
   apiVersion: yandexcloud.crossplane.io/v1alpha1
   kind: ObjectStorageBucket
   metadata:
     name: my-artifacts
   spec:
     forProvider:
       name: my-artifacts-bucket
       location:
         region: ru-central1
     providerConfigRef:
       name: yandexcloud-provider
   ```

2. **ArgoCD Application для синхронизации:**

   ```yaml
   apiVersion: argoproj.io/v1alpha1
   kind: Application
   metadata:
     name: crossplane-infra
     namespace: argocd
   spec:
     project: default
     source:
       repoURL: https://github.com/org/infra-gitops.git
       targetRevision: main
       path: crossplane/resources
     destination:
       server: https://kubernetes.default.svc
       namespace: default
     syncPolicy:
       automated:
         prune: true
         selfHeal: true
       syncOptions:
         - CreateNamespace=true
   ```

3. **Мониторинг статуса:**

   ```bash
   # Статус синхронизации ArgoCD
   argocd app get crossplane-infra
   
   # Статус ресурса Crossplane
   kubectl get rdsinstance my-postgres-db -o yaml
   ```

### Сценарий 2: Мультикластерная синхронизация с ArgoCD

ArgoCD может управлять несколькими кластерами с Crossplane:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: crossplane-multi-cluster
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - cluster: dev
            url: https://dev-cluster.example.com
          - cluster: prod
            url: https://prod-cluster.example.com
  template:
    metadata:
      name: crossplane-infra-{{cluster}}
    spec:
      project: default
      source:
        repoURL: https://github.com/org/infra-gitops.git
        targetRevision: main
        path: crossplane/resources/{{cluster}}
      destination:
        server: {{url}}
        namespace: default
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

## Дополнительная информация

Обзор ArgoCD и его возможностей см. в [ArgoCD Overview](../ArgoCD/argocd_overview.md), политики синхронизации — в [Synchronization](../ArgoCD/synchronization.md), использование Helm — в [Helm Integration](../ArgoCD/helm_integration.md). Альтернативный GitOps-инструмент описан в [Flux](../flux.md).

Внешние ресурсы:

- Официальная документация Crossplane: [GitOps Workflows](https://docs.crossplane.io/latest/concepts/gitops/)
