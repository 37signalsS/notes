# Flux: Обзор и Ключевые Концепции

**Flux** — это модульный и расширяемый набор инструментов для построения GitOps-конвейеров в Kubernetes. Проект является частью CNCF и фокусируется на "Unix-way" подходе, где каждый компонент решает свою задачу, а вместе они образуют гибкую систему.

## Определения

- **Flux**: Набор контроллеров, которые автоматизируют синхронизацию состояния кластера с конфигурациями из Git-репозиториев и других источников.
- **GitOps Toolkit**: Набор специализированных контроллеров, из которых состоит Flux. Каждый контроллер отвечает за свой тип ресурсов (источники, Kustomize-манифесты, Helm-релизы и т.д.).

## Основные концепции

### Архитектура GitOps Toolkit

Flux состоит из нескольких независимых контроллеров, которые взаимодействуют через CRD.

| Контроллер | Основные CRD | Назначение |
| --- | --- | --- |
| `source-controller` | `GitRepository`, `HelmRepository` | Отвечает за получение манифестов из источников. |
| `kustomize-controller`| `Kustomization` | Применяет YAML-манифесты, используя Kustomize. |
| `helm-controller` | `HelmRelease` | Управляет жизненным циклом Helm-релизов. |
| `notification-controller`| `Provider`, `Alert` | Отправляет уведомления о событиях в Slack, Teams и др. |
| `image-automation-controller`| `ImageUpdateAutomation` | Автоматизирует обновление тегов образов в Git. |

### Ключевые Ресурсы (CRD)

Философия Flux — разделение ответственности. Процесс развертывания описывается несколькими CRD:

1. **Источник (`GitRepository`, `HelmRepository`)**: Описывает, *откуда* брать манифесты или чарты.
2. **Применение (`Kustomization`, `HelmRelease`)**: Описывает, *что*, *куда* и *как* разворачивать, ссылаясь на источник.

Эта модель позволяет, например, использовать один `GitRepository` как источник для нескольких `Kustomization`'ов.

### Декларативное управление Helm

Flux позволяет управлять Helm-релизами полностью декларативно, без использования `helm` CLI.

- **`HelmRepository`**: Определяет репозиторий чартов.
- **`HelmRelease`**: Описывает конкретный релиз: какой чарт и с какими `values` установить. `helm-controller` берет на себя установку, обновление и откат.

## Практические сценарии

### Сценарий 1: Установка (Bootstrap)

Первоначальная установка Flux настраивает кластер так, чтобы он управлял сам собой из Git-репозитория.

```bash
# Устанавливаем Flux CLI
# Генерируем Personal Access Token (PAT) для GitHub
export GITHUB_TOKEN=<your-token>
export GITHUB_USER=<your-username>

# Запускаем bootstrap
flux bootstrap github \
  --owner=$GITHUB_USER \
  --repository=my-cluster-config \
  --branch=main \
  --path=./clusters/my-cluster \
  --personal
```

Эта команда установит компоненты Flux в кластер и создаст коммит в `my-cluster-config` с их конфигурацией.

### Сценарий 2: Развертывание Kustomize-приложения

```yaml
# 1. Источник манифестов
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: my-app-repo
  namespace: flux-system
spec:
  interval: 1m
  url: https://github.com/my-org/my-app
  ref:
    branch: main
---
# 2. Правила применения
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: my-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./kustomize/overlays/prod # Путь в репозитории
  prune: true # Удалять ресурсы, которых больше нет в Git
  sourceRef:
    kind: GitRepository
    name: my-app-repo
  targetNamespace: my-app # Куда разворачивать
```

### Сценарий 3: Развертывание Helm-чарта

```yaml
# 1. Источник (репозиторий Helm-чартов)
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: bitnami
  namespace: flux-system
spec:
  interval: 1h
  url: https://charts.bitnami.com/bitnami
---
# 2. Правила релиза
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: redis
  namespace: db
spec:
  interval: 10m
  chart:
    spec:
      chart: redis
      version: "18.x.x"
      sourceRef:
        kind: HelmRepository
        name: bitnami
  values:
    auth:
      enabled: false
```

## Дополнительная информация

- **[Сравнение с ArgoCD](../Comparisons/argo_vs_flux_manifests.md)**: Детальный разбор различий в философии и структуре манифестов.
- **Официальная документация**: [fluxcd.io](https://fluxcd.io/)
- **Flux CLI**: Мощный инструмент для отладки, ручной синхронизации (`flux reconcile`) и проверки состояния (`flux get kustomizations`).
