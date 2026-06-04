# Flux: Обзор и Ключевые Концепции

> **Надежность: 10** (Подтверждено SSoT и актуальными данными на февраль 2026)
> **Актуальные версии:** Flux v2.8.1, notification-controller v1.8.1, image-automation-controller v1.1.0.

**Flux** — это модульный и расширяемый набор инструментов для построения GitOps-конвейеров в Kubernetes. Проект является частью CNCF (Graduated с ноября 2022) и фокусируется на подходе "Unix-way", где каждый компонент решает свою задачу, а вместе они образуют гибкую систему.

## Определения

- **Flux**: Набор контроллеров, автоматизирующих синхронизацию состояния кластера с конфигурациями из Git-репозиториев и других источников.
- **GitOps Toolkit**: Набор специализированных контроллеров, из которых состоит Flux. Каждый контроллер отвечает за свой тип ресурсов (источники, Kustomize-манифесты, Helm-релизы и т.д.).
- **Reconciliation (Согласование)**: Процесс, при котором Flux сравнивает желаемое состояние в Git с фактическим состоянием в кластере и вносит изменения для их выравнивания.

## Базовые концепции

### Архитектура GitOps Toolkit

Flux состоит из нескольких независимых контроллеров, взаимодействующих через CRD (Custom Resource Definitions).

| Контроллер | Основные CRD | Назначение |
| :--- | :--- | :--- |
| `source-controller` | `GitRepository`, `HelmRepository`, `Bucket` | Получение манифестов из внешних источников. |
| `kustomize-controller`| `Kustomization` | Применение YAML-манифестов с использованием Kustomize. |
| `helm-controller` | `HelmRelease` | Управление жизненным циклом Helm-релизов. |
| `notification-controller`| `Provider`, `Alert`, `Receiver` | Отправка уведомлений о событиях (Slack, Teams, Webhooks). |
| `image-reflector-controller`| `ImageRepository`, `ImagePolicy` | Сканирование реестров образов и отслеживание тегов. |
| `image-automation-controller`| `ImageUpdateAutomation` | Автоматизация обновления тегов образов в Git. |

### Ключевые ресурсы (CRD)

Философия Flux — разделение ответственности. Процесс развертывания описывается несколькими типами ресурсов:

1. **Источник (`GitRepository`, `HelmRepository`)**: Описывает, *откуда* брать данные (URL, ветка, интервал проверки).
2. **Применение (`Kustomization`, `HelmRelease`)**: Описывает, *что*, *куда* и *как* разворачивать, ссылаясь на конкретный источник.

Эта модель позволяет использовать один `GitRepository` как источник для множества независимых `Kustomization`.

### Декларативное управление Helm

Flux позволяет управлять Helm-релизами полностью декларативно, без использования `helm` CLI.

- **`HelmRepository`**: Описывает репозиторий чартов.
- **`HelmRelease`**: Описывает конкретный релиз (чарт, версия, `values`). `helm-controller` обеспечивает установку, обновление и автоматический откат при неудаче.

### Безопасность и секреты

Flux нативно поддерживает работу с зашифрованными секретами через **Mozilla SOPS**. Это позволяет безопасно хранить секреты прямо в Git-репозитории.

- Поддерживаемые провайдеры: AWS KMS, Azure Key Vault, Google Cloud KMS, HashiCorp Vault, PGP, age.
- Секреты расшифровываются непосредственно `kustomize-controller` перед применением в кластер.

### Ключевые изменения в v2.8 (февраль 2026)

| Функция | Описание |
| :--- | :--- |
| **Поддержка Helm v4** | Server-side apply и kstatus-based health checking для HelmRelease. |
| **Оценка готовности** | Проверка готовности Helm-объектов через CEL-выражения. |
| **Inventory tracking** | Отслеживание инвентаря в `.status.inventory` для HelmRelease. |
| **Комментарии в PR** | Прямое комментирование Pull Request из Flux notifications. |
| **Поддержка Cosign v3** | Верификация OCI-артефактов и образов контейнеров. |
| **mTLS** | Поддержка mTLS для алертов и GitHub App transport. |
| **OpenTelemetry** | Трассировка для Kustomization и HelmRelease. |

> **Внимание:** API v1beta2 и v2beta2 удалены в v2.8.0. Требуется миграция через `flux migrate` перед обновлением.

## Практические сценарии

### Сценарий 1: Первоначальная установка (Bootstrap)

Настраивает кластер так, чтобы он управлял сам собой из Git-репозитория.

```bash
# Экспортируем токен доступа (например, GitHub PAT)
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

### Сценарий 2: Развертывание приложения через Kustomize

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
  path: ./kustomize/overlays/prod
  prune: true # Удалять ресурсы, отсутствующие в Git
  sourceRef:
    kind: GitRepository
    name: my-app-repo
  targetNamespace: my-app
```

### Сценарий 3: Развертывание Helm-чарта с SOPS

```yaml
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
      existingSecret: redis-pass
  # Ссылка на расшифровку секретов (если используются в манифестах)
  # decryption:
  #   provider: sops
  #   secretRef:
  #     name: sops-age-key
```

## Дополнительная информация

**Связанные документы:**

- [Сравнение с ArgoCD](./argo_vs_flux_manifests.md) — детальное сравнение архитектур и манифестов.
- [Уведомления в GitOps](./gitops_notifications.md) — настройка оповещений в Slack/Teams.
- [Управление секретами](./secrets_encryption.md) — подробнее о SOPS, Sealed Secrets и Vault.

**Официальные ресурсы:**

- [Документация Flux](https://fluxcd.io/)
- [GitHub проекта](https://github.com/fluxcd/flux2)
- [Список изменений (Changelog)](https://github.com/fluxcd/flux2/releases)
