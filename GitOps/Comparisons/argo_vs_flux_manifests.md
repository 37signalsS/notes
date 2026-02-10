# Сравнение структуры манифестов ArgoCD и Flux

## Концептуальные различия
*   Argo CD объединяет описание того, что и куда разворачивать, в одном ресурсе Application. Источник, путь/чарт и целевой кластер/namespace задаются прямо в манифесте Application, синхронизация управляется полями syncPolicy и опциями.
*   Flux разделяет ответственность: источники (Git/Helm/OCI/S3) описываются отдельными ресурсами Source API (GitRepository, HelmRepository, OCIRepository, Bucket), а применение — ресурсом Kustomization или HelmRelease. Таким образом, граф зависимости между «источником» и «применением» выражается явно через ссылки.

## Базовые ресурсы и поля
| Аспект | Argo CD | Flux |
| --- | --- | --- |
| Главный CR | Application | Kustomization, HelmRelease |
| Группа CRD | argoproj.io | fluxcd.io |
| Источник артефактов | spec.source (repoURL, path, chart, targetRevision) | Отдельный Source: GitRepository/HelmRepository/OCIRepository |
| Целевой кластер | spec.destination.server/namespace | По умолчанию локальный кластер; удалённый через spec.kubeConfig в Kustomization |
| Управление порядком | Sync waves (аннотации), hooks | dependsOn в Kustomization, healthChecks |
| Массовая генерация | ApplicationSet | Kustomize-композиции, генерация на стороне Git, HelmRelease c values |

## Минимальные примеры
Argo CD: единый Application, описывающий источник и назначение.
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-app
spec:
  project: default
  source:
    repoURL: https://github.com/org/platform-configs.git
    path: apps/billing/overlays/prod
    targetRevision: main
    kustomize:
      commonLabels:
        app: billing
  destination:
    server: https://kubernetes.default.svc
    namespace: billing
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
```
Flux: явное разделение источника и применения.
```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: platform-configs
  namespace: flux-system
spec:
  url: https://github.com/org/platform-configs.git
  ref:
    branch: main
  interval: 1m
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: billing-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./apps/billing/overlays/prod
  prune: true
  sourceRef:
    kind: GitRepository
    name: platform-configs
  targetNamespace: billing
  dependsOn:
    - name: platform-base
  patches:
    - patch: |
        - op: replace
          path: /spec/replicas
          value: 3
      target:
        kind: Deployment
        name: billing-api
```
Для Helm-чартов Flux использует HelmRepository + HelmRelease и может одновременно управлять зависимостями и значениями; в Argo CD Helm описывается через spec.source.chart и values/parameters внутри Application.

## Организация репозиториев
*   Argo CD:
*   Часто применяется паттерн app-of-apps: корневой Application указывает на директорию, где лежат дочерние Applications.
*   Распространённое разделение: один репозиторий с декларациями приложений, другой — с инфраструктурой/кластерами. Назначение кластера задаётся в каждом Application через destination.
*   Flux:
*   Рекомендуется структура clusters//*, где объявлены Kustomization и источники, привязанные к конкретному кластеру.
*   Каталоги infrastructure/* и apps/* переиспользуются несколькими кластерами; привязка осуществляется за счёт Kustomization в директории соответствующего кластера.

## Детали валидации и дрейфа
*   Argo CD использует сравнение с live-объектами и может игнорировать различия через ignoreDifferences; дополнительные опции поведения задаются в syncOptions.
*   Flux применяет server-side apply, осуществляет периодическую сверку по interval, поддерживает точечные модификации через patches и postBuild, а контроль зависимостей и готовности — через dependsOn и healthChecks.
