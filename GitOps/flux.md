# Flux: Обзор и Ключевые Концепции

**Flux** — это модульный и расширяемый набор инструментов для построения GitOps-конвейеров в Kubernetes. Проект является частью CNCF (Graduated) и фокусируется на подходе "Unix-way", где каждый компонент решает свою задачу, а вместе они образуют гибкую систему.

## Определения

- **Flux**: Набор контроллеров, автоматизирующих синхронизацию состояния кластера с конфигурациями из Git-репозиториев и других источников.
- **GitOps Toolkit**: Набор специализированных контроллеров, из которых состоит Flux. Каждый контроллер отвечает за свой тип ресурсов (источники, Kustomize-манифесты, Helm-релизы и т.д.).
- **Reconciliation (Согласование)**: Процесс, при котором Flux сравнивает желаемое состояние в Git с фактическим состоянием в кластере и вносит изменения для их выравнивания.

## Базовые концепции

### Архитектура GitOps Toolkit

Flux состоит из нескольких независимых контроллеров, взаимодействующих через CRD (Custom Resource Definitions). Для управления жизненным циклом самих контроллеров рекомендуется использовать **Flux Operator**.

| Контроллер | Основные CRD | Назначение |
| :--- | :--- | :--- |
| `source-controller` | `GitRepository`, `HelmRepository`, `OCIRepository` | Получение манифестов из внешних источников и OCI-реестров. |
| `kustomize-controller`| `Kustomization` | Применение YAML-манифестов с использованием Kustomize и SSA. |
| `helm-controller` | `HelmRelease` | Управление Helm-релизами (полная поддержка Helm v4). |
| `notification-controller`| `Provider`, `Alert`, `Receiver` | Отправка уведомлений о событиях (Slack, Teams, Webhooks). |
| `image-reflector-controller`| `ImageRepository`, `ImagePolicy` | Сканирование реестров образов и отслеживание тегов. |
| `image-automation-controller`| `ImageUpdateAutomation` | Автоматизация обновления тегов образов в Git. |

### Ключевые ресурсы (CRD)

Философия Flux — разделение ответственности. Процесс развертывания описывается двумя типами ресурсов:

1. **Источник (`GitRepository`, `OCIRepository`)**: Описывает, *откуда* брать данные. С версии v2.9 через **ArtifactGenerator API** значительно оптимизирована работа с крупными монорепозиториями.
2. **Применение (`Kustomization`, `HelmRelease`)**: Описывает, *что*, *куда* и *как* разворачивать, ссылаясь на конкретный источник.

### Декларативное управление Helm

Flux позволяет управлять Helm-релизами полностью декларативно.
- **`HelmRepository`**: Описывает репозиторий чартов.
- **`HelmRelease`**: Описывает конкретный релиз (чарт, версия, `values`). `helm-controller` обеспечивает установку, обновление, проверку готовности через CEL-выражения и автоматический откат.

### Безопасность и секреты

Flux нативно поддерживает работу с зашифрованными секретами через **Mozilla SOPS**. Это позволяет безопасно хранить секреты прямо в Git-репозитории.
- Поддерживаемые провайдеры: AWS KMS, Azure Key Vault, Google Cloud KMS (включая Sovereign Cloud), HashiCorp Vault, PGP, age.
- Секреты расшифровываются непосредственно `kustomize-controller` перед применением в кластер.

### Ключевые изменения в v2.9 (июль 2026)

| Функция | Описание |
| :--- | :--- |
| **Система плагинов CLI** | Новая архитектура для расширения возможностей `flux` CLI сторонними инструментами. |
| **ArtifactGenerator API** | Оптимизация работы с монорепозиториями, снижение нагрузки на сеть. |
| **Улучшения SSA** | Расширенный контроль над игнорированием полей (`ignore rules`) при синхронизации. |
| **AI-driven GitOps** | Анонс интеграции AI-агентов для диагностики и авто-исправления конфигураций. |
| **GCP Sovereign Cloud** | Нативная поддержка Artifact Registry в суверенных облаках Google. |
| **Kubernetes 1.36+** | Полная совместимость с актуальными версиями Kubernetes. |

## Практические сценарии

### Сценарий 1: Первоначальная установка (Bootstrap)

Настраивает кластер так, чтобы он управлял сам собой из Git-репозитория.

```bash
# Экспортируем токен доступа
export GITHUB_TOKEN=<your-token>

# Запускаем bootstrap
flux bootstrap github \
  --owner=my-org \
  --repository=fleet-infra \
  --branch=main \
  --path=./clusters/prod \
  --personal
# → ► connecting to github.com
# → ► cloning branch "main" from repo "my-org/fleet-infra"
# → ✔ components are up to date
```

### Сценарий 2: Развертывание приложения через Kustomize

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: web-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./apps/prod
  prune: true # Удалять ресурсы, отсутствующие в Git
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  healthChecks:
    - kind: Deployment
      name: web-app
      namespace: apps
```

### Сценарий 3: Просмотр состояния синхронизации

```bash
flux get kustomizations
# → NAME    REVISION             SUSPENDED  READY   MESSAGE
# → web-app main@sha1:e1a2b3c4   False      True    Applied revision: main@sha1:e1a2b3c4
```

### Сценарий 4: Развертывание Helm-чарта с SOPS

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
- [Сравнение с ArgoCD](./argo_vs_flux_manifests.md) — детальное сравнение архитектур.
- [Управление секретами](./secrets_encryption.md) — подробнее о SOPS и Sealed Secrets.
- [Документация Flux](https://fluxcd.io/) — официальный справочник и руководства.
