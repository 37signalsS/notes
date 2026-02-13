# ArgoCD vs. Flux: Сравнение Подходов и Манифестов

ArgoCD и Flux — два ведущих GitOps-инструмента в экосистеме CNCF, но они реализуют свои задачи с разной философией. Это сравнение фокусируется на ключевых архитектурных различиях и том, как они отражаются в структуре манифестов.

## Определения

- **ArgoCD**: Централизованный GitOps-инструмент с упором на "все-в-одном", мощный Web UI и мультикластерное управление из коробки. Его основной ресурс — `Application`, который описывает, *что*, *откуда* и *куда* разворачивать.
- **Flux**: Набор ("toolkit") декомпозированных, независимых контроллеров, которые работают вместе. Философия Flux ближе к "Unix-way" — каждый инструмент делает одну вещь хорошо. Ответственность разделена между разными CRD (например, `GitRepository` + `Kustomization`).

## Основные концепции: Ключевые различия

### 1. Модель конфигурации

- **ArgoCD**: Использует единый, монолитный CRD `Application`. В нем смешаны все аспекты: ссылка на Git-репозиторий (`source`), целевой кластер (`destination`) и политика синхронизации (`syncPolicy`). Это делает конфигурацию простой для старта, но менее гибкой.
- **Flux**: Разделяет обязанности. `Source`-контроллер отвечает за получение артефактов из источников (`GitRepository`, `HelmRepository`). `Kustomize`- и `Helm`-контроллеры отвечают за применение (`Kustomization`, `HelmRelease`). Это более многословно, но позволяет переиспользовать один источник для нескольких развертываний.

### 2. Пользовательский интерфейс (UI)

- **ArgoCD**: Поставляется с мощным и интуитивно понятным Web UI, который является одной из его главных особенностей. UI позволяет визуализировать состояние приложений, просматривать `diff`, откатываться и управлять синхронизацией.
- **Flux**: Не имеет официального встроенного UI. Основной способ взаимодействия — CLI (`flux`) и просмотр CRD в кластере (`kubectl`). Существуют сторонние UI, например Weave GitOps.

### 3. Архитектура

- **ArgoCD**: Более централизованная модель. Один инстанс ArgoCD может управлять множеством кластеров.
- **Flux**: Децентрализованный набор контроллеров. Обычно один набор контроллеров Flux управляет одним кластером.

## Практические сценарии: Примеры Манифестов

Рассмотрим, как развернуть одно и то же Kustomize-приложение с помощью обоих инструментов.

### ArgoCD: Единый манифест `Application`

ArgoCD описывает все в одном ресурсе.

```yaml
# apps/argocd/my-app.yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
  namespace: argocd
spec:
  # ЧТО: источник в Git
  source:
    repoURL: https://github.com/my-org/my-app-config.git
    path: overlays/production
    targetRevision: main
  # КУДА: целевой кластер и namespace
  destination:
    server: https://kubernetes.default.svc
    namespace: my-app
  # КАК: политика синхронизации
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```

### Flux: Разделение на `Source` и `Kustomization`

Flux требует как минимум два ресурса: один для описания источника, другой — для описания процесса применения.

```yaml
# 1. Описываем источник (ЧТО)
# sources/git-repo.yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: my-app-config-repo
  namespace: flux-system
spec:
  interval: 1m
  url: https://github.com/my-org/my-app-config.git
  ref:
    branch: main
---
# 2. Описываем применение (КУДА и КАК)
# apps/flux/my-app.yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: my-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./overlays/production # Путь внутри источника
  prune: true
  # Ссылка на источник
  sourceRef:
    kind: GitRepository
    name: my-app-config-repo
  # Целевой namespace
  targetNamespace: my-app
```

## Дополнительная информация

- **[Обзор ArgoCD](../ArgoCD/argocd_overview.md)**: Подробное введение в архитектуру и возможности ArgoCD.
- **[Обзор Flux](../Flux/overview.md)**: Введение в философию и компоненты GitOps Toolkit от Flux.
- **Официальная документация ArgoCD**: [argoproj.github.io/cd/](https://argoproj.github.io/cd/)
- **Официальная документация Flux**: [fluxcd.io](https://fluxcd.io/)
