# Flux: Обзор и Ключевые Концепции

> **Актуальные версии (февраль 2026):** Flux v2.8.1, notification-controller v1.8.1, image-automation-controller v1.1.0.

**Flux** — это модульный и расширяемый набор инструментов для построения GitOps-конвейеров в Kubernetes. Проект является частью CNCF (Graduated с ноября 2022) и фокусируется на "Unix-way" подходе, где каждый компонент решает свою задачу, а вместе они образуют гибкую систему.

## Определения

- **Flux**: Набор контроллеров, которые автоматизируют синхронизацию состояния кластера с конфигурациями из Git-репозиториев и других источников.
- **GitOps Toolkit**: Набор специализированных контроллеров, из которых состоит Flux. Каждый контроллер отвечает за свой тип ресурсов (источники, Kustomize-манифесты, Helm-релизы и т.д.).

## Базовые концепции

### Архитектура GitOps Toolkit

Flux состоит из нескольких независимых контроллеров, которые взаимодействуют через CRD.

| Контроллер | Основные CRD | Назначение |
| :--- | :--- | :--- |
| `source-controller` | `GitRepository`, `HelmRepository`, `Bucket` | Отвечает за получение манифестов из источников. |
| `kustomize-controller`| `Kustomization` | Применяет YAML-манифесты, используя Kustomize. |
| `helm-controller` | `HelmRelease` | Управляет жизненным циклом Helm-релизов. |
| `notification-controller`| `Provider`, `Alert`, `Receiver` | Отправляет уведомления о событиях в Slack, Teams и др. |
| `image-reflector-controller`| `ImageRepository`, `ImagePolicy` | Сканирует реестры образов и отражает метаданные. |
| `image-automation-controller`| `ImageUpdateAutomation` | Автоматизирует обновление тегов образов в Git. |

### Ключевые ресурсы (CRD)

Философия Flux — разделение ответственности. Процесс развертывания описывается несколькими CRD:

1. **Источник (`GitRepository`, `HelmRepository`)**: Описывает, *откуда* брать манифесты или чарты.
2. **Применение (`Kustomization`, `HelmRelease`)**: Описывает, *что*, *куда* и *как* разворачивать, ссылаясь на источник.

Эта модель позволяет, например, использовать один `GitRepository` как источник для нескольких `Kustomization`'ов.

### Декларативное управление Helm

Flux позволяет управлять Helm-релизами полностью декларативно, без использования `helm` CLI.

- **`HelmRepository`**: Определяет репозиторий чартов.
- **`HelmRelease`**: Описывает конкретный релиз: какой чарт и с какими `values` установить. `helm-controller` берет на себя установку, обновление и откат.

### Ключевые изменения в v2.8 (февраль 2026)

| Функция | Описание |
| :--- | :--- |
| **Helm v4 support** | Server-side apply и kstatus-based health checking для HelmRelease |
| **Readiness evaluation** | Оценка готовности Helm-объектов через CEL-выражения |
| **Inventory tracking** | Отслеживание инвентаря в `.status.inventory` для HelmRelease |
| **PR Comments** | Прямое комментирование Pull Request из Flux notifications |
| **Cosign v3 support** | Верификация OCI-артефактов и образов контейнеров |
| **mTLS support** | mTLS для алертов и GitHub App transport |
| **OpenTelemetry tracing** | Трассировка для Kustomization и HelmRelease |

> **Важно:** API v1beta2 и v2beta2 удалены в v2.8.0. Требуется миграция через `flux migrate` перед обновлением.

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

**Связанные документы:** [Сравнение с ArgoCD](./argo_vs_flux_manifests.md), [GitOps Notifications](./gitops_notifications.md), [GitOps Security](./secrets_encryption.md).

**Официальные ресурсы:** [Документация](https://fluxcd.io/), [GitHub](https://github.com/fluxcd/flux2), [Changelog](https://github.com/fluxcd/flux2/releases).
