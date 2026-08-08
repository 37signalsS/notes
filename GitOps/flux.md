# Flux — обзор и ключевые концепции

**Flux** — это модульный и расширяемый набор инструментов для построения GitOps-конвейеров в Kubernetes. Проект является частью CNCF (Graduated) и фокусируется на подходе "Unix-way", где каждый компонент решает свою задачу, а вместе они образуют гибкую систему.

## Определения

- **Flux**: Набор контроллеров, автоматизирующих синхронизацию состояния кластера с конфигурациями из Git-репозиториев и других источников.
- **GitOps Toolkit**: Набор специализированных контроллеров, из которых состоит Flux. Каждый контроллер отвечает за свой тип ресурсов (источники, Kustomize-манифесты, Helm-релизы и т.д.).
- **Reconciliation (Согласование)**: Процесс, при котором Flux сравнивает желаемое состояние в Git с фактическим состоянием в кластере и вносит изменения для их выравнивания. В основе лежит паттерн **Reconciliation Loop** (цикл сверки): контроллеры периодически сравнивают эталон (Git/Helm/OCI) и реальное состояние ресурсов в Kubernetes, при расхождениях принудительно приводя систему к заявленному виду. Это обеспечивает автоматизацию доставки, упрощает аудит и восстановление кластера (Drift Detection & Correction).

## Базовые концепции

### Архитектура набора инструментов GitOps (GitOps Toolkit)

Flux состоит из нескольких независимых контроллеров, взаимодействующих через CRD (Custom Resource Definitions).

| Контроллер | Основные CRD | Назначение |
| :--- | :--- | :--- |
| `source-controller` | `GitRepository`, `HelmRepository`, `OCIRepository`, `Bucket` | Отвечает за получение артефактов. Следит за репозиториями, чартами и OCI-реестрами, проверяет наличие новых коммитов/тегов и делает их доступными другим контроллерам. |
| `kustomize-controller`| `Kustomization` | Применяет манифесты, поддерживает Kustomize (иерархии, патчи). Отвечает за сборку финального манифеста перед отправкой в `kube-apiserver`. |
| `helm-controller` | `HelmRelease` | Управляет Helm-релизами, поддерживает автоматическое обновление зависимостей и интеграцию с OCI для чартов. |
| `notification-controller`| `Provider`, `Alert`, `Receiver` | Обрабатывает события кластера и отправляет уведомления (Slack, Teams, Loki, Webhooks). Информирует о статусе реконсиляции и ошибках. |
| `image-reflector-controller`| `ImageRepository`, `ImagePolicy` | Сканирование реестров образов и отслеживание тегов по заданным политикам (например, SemVer). |
| `image-automation-controller`| `ImageUpdateAutomation` | Автоматизация обновления тегов образов непосредственно в Git-репозитории. |

### Управление жизненным циклом через Flux Operator

Для управления самим Flux (установка, обновление, конфигурация компонентов) рекомендуется использовать **Flux Operator**. Он позволяет:
- Декларативно описывать желаемую версию Flux и состав включенных контроллеров.
- Управлять несколькими инстансами Flux в одном кластере (sharding).
- Автоматизировать миграции и обновление CRD.

### Визуализация и графический интерфейс (GUI)

Сам FluxCD не имеет встроенного графического интерфейса, следуя философии модульности, но интегрируется со сторонними решениями:
- **FreeLens**: Бесплатное расширение для Lens (и форка FreeLens), которое объединяет все ресурсы Flux (`GitRepository`, `Kustomization`, `HelmRelease`) в одной вкладке. Позволяет видеть историю операций, ошибки и ссылки на коммиты.
- **Weave GitOps**: Популярный GUI для визуализации и управления Flux-ресурсами.
- **GitOps Dashboard**: Другие UI и интеграции, включая расширение для VS Code.
- **Applied Revision**: В визуальных инструментах критически важно отслеживать столбец *Applied Revision* — он показывает хэш последнего примененного коммита, позволяя мгновенно проверить актуальность версии в кластере.

### Управление порядком развертывания (dependsOn)

Flux позволяет задавать строгую последовательность развертывания ресурсов (например, сначала CRD и оператор, затем кастомный ресурс).
- Реализуется через параметр `dependsOn` в объекте `Kustomization`.
- **Важно:** Зависимости не должны образовывать циклов.
- Рекомендуется использовать иерархию: базовый уровень (инфраструктура/операторы) → прикладной уровень.

### Мультитенентность и изоляция (Multi-tenancy)

Flux v2 спроектирован с учетом безопасности в многопользовательских средах:
- **Service Account Impersonation**: Каждая `Kustomization` или `HelmRelease` может выполняться от имени конкретного `ServiceAccount`. Это ограничивает права Flux на манипуляции только теми ресурсами, к которым есть доступ у данного аккаунта.
- **Namespace isolation**: Контроллеры могут быть настроены на прослушивание только определенных пространств имен.
- **Tenant Self-Service**: Позволяет командам управлять своими релизами в выделенных неймспейсах без доступа к системным настройкам Flux.

### Ручное управление и отладка

Для временных работ в кластере или тестирования ad-hoc правок процесс автоматической синхронизации можно приостановить:
1. **Команды CLI:** `flux suspend ks <name>` (заморозка) и `flux resume ks <name>` (возобновление).
2. **Декларативно:** Поле `spec.suspend: true` в манифесте `Kustomization`.
3. **Принудительный запуск:** `flux reconcile kustomization <name>` — запускает цикл сверки немедленно, не дожидаясь интервала.
**Совет:** Не оставляйте `suspend` надолго, так как это нарушает принцип GitOps как единого источника истины.

### Ключевые ресурсы (CRD)

Процесс развертывания описывается двумя типами ресурсов:

1. **Источник (`GitRepository`, `OCIRepository`)**: Описывает, *откуда* брать данные.
2. **Применение (`Kustomization`, `HelmRelease`)**: Описывает, *что*, *куда* и *как* разворачивать, ссылаясь на конкретный источник.

### Использование OCI-репозиториев

Современный подход во Flux — использование OCI-совместимых реестров (Docker Hub, GHCR, Harbor) в качестве источников не только для образов, но и для Helm-чартов и обычных YAML-манифестов.
- **Преимущества**: Высокая скорость загрузки, поддержка тегов и версионирования, единое хранилище для всех артефактов.
- **Ресурс**: `OCIRepository`.

### Декларативное управление Helm

Flux позволяет управлять Helm-релизами полностью декларативно.
- **`HelmRepository`**: Описывает репозиторий чартов.
- **`HelmRelease`**: Описывает конкретный релиз. `helm-controller` обеспечивает установку, обновление и автоматический откат при сбоях.

### Автоматизация обновления образов (Image Automation)

Flux включает механизмы для отслеживания новых версий образов в реестрах и автоматического обновления манифестов в Git.

- **`image-reflector-controller`**: Сканирует реестры образов и записывает метаданные тегов в ресурс `ImageRepository`. Использует `ImagePolicy` для выбора тега (например, SemVer `~v1.2`).
- **`image-automation-controller`**: Выполняет коммит в Git-репозиторий при появлении тега, соответствующего политике.

**Пример настройки через маркеры в `HelmRelease`:**
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
spec:
  values:
    image:
      tag: v1.0.0 # {"$imagepolicy": "flux-system:app-policy"}
```

### Безопасность и управление секретами

Flux нативно поддерживает работу с зашифрованными секретами:
- **Mozilla SOPS**: Основной инструмент. Секреты шифруются через KMS или age/PGP. Расшифровка происходит "на лету" контроллером `kustomize-controller`.
- **Sealed Secrets**: Интеграция с Bitnami Sealed Secrets — шифрование публичным ключом кластера.
- **External Secrets Operator (ESO)**: Синхронизация данных из внешних хранилищ (Vault, AWS Secrets Manager) в нативные секреты Kubernetes.

### Управление удаленными ресурсами (prune)

Параметр `prune` в объекте `Kustomization` определяет судьбу ресурсов, удаленных из Git.
- **`prune: true`**: Ресурсы, удаленные из Git, удаляются из кластера. Git — единственный источник конфигурации.
- **`prune: false`**: Ресурсы остаются в кластере даже после удаления их описания из Git.
- **Stateful-ресурсы**: Для PVC и баз данных рекомендуется `prune: false`, чтобы избежать потери данных.

### Верификация источников (Source Verification)

Для обеспечения безопасности в production-средах Flux поддерживает проверку подлинности источников:
- **SSH Verification**: Использование `known_hosts` для проверки личности Git-сервера.
- **GPG/Cosign Signing**: Проверка подписей коммитов или OCI-артефактов. Если подпись неверна, Flux откажется применять манифесты. Настраивается через поле `spec.verify` в `GitRepository` или `OCIRepository`.

### Масштабирование и производительность

При управлении сотнями `Kustomization` или `HelmRelease` могут потребоваться оптимизации:
- **Resource Limits**: Настройка лимитов CPU/Memory для контроллеров (особенно `kustomize-controller`).
- **Sharding**: Использование **Flux Operator** для распределения ресурсов между несколькими инстансами Flux.
- **Interval Tuning**: Увеличение `spec.interval` для некритичных приложений, чтобы снизить нагрузку на API-сервер.

### Ключевые изменения в версии v2.9 (июль 2026)

| Функция | Описание |
| :--- | :--- |
| **Система плагинов CLI** | Новая архитектура для расширения возможностей `flux` CLI сторонними инструментами. |
| **ArtifactGenerator API** | Оптимизация работы с монорепозиториями, снижение нагрузки на сеть. |
| **Улучшения SSA** | Расширенный контроль над игнорированием полей (`ignore rules`) при синхронизации. |
| **AI-driven GitOps** | Интеграция AI-агентов для диагностики и авто-исправления конфигураций. |
| **GCP Sovereign Cloud** | Нативная поддержка Artifact Registry в суверенных облаках Google. |

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
# -> connecting to github.com
# -> cloning branch "main" from repo "my-org/fleet-infra"
# -> components are up to date
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
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  healthChecks:
    - kind: Deployment
      name: web-app
      namespace: apps
```

### Сценарий 3: Настройка мультитенентности (Service Account Impersonation)

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: team-a-app
  namespace: flux-system
spec:
  interval: 10m
  # Выполнение от имени ограниченного аккаунта
  serviceAccountName: team-a-reconciler
  path: ./tenants/team-a
  prune: true
  sourceRef:
    kind: GitRepository
    name: team-a-repo
```

### Сценарий 4: Использование OCI-репозитория для манифестов

```yaml
apiVersion: source.toolkit.fluxcd.io/v1beta2
kind: OCIRepository
metadata:
  name: podinfo
  namespace: flux-system
spec:
  interval: 5m
  url: oci://ghcr.io/stefanprodan/manifests/podinfo
  ref:
    tag: 6.3.5
```

### Сценарий 5: Ручное управление и отладка

```bash
# Приостановить синхронизацию
flux suspend kustomization web-app

# Возобновить процесс
flux resume kustomization web-app

# Принудительно запустить цикл сверки
flux reconcile kustomization web-app --with-source
# -> annotating Kustomization web-app in flux-system namespace
# -> reconciliation triggered
```

### Сценарий 6: Просмотр состояния и ревизий

```bash
flux get kustomizations
# -> NAME    REVISION             SUSPENDED  READY   MESSAGE
# -> web-app main@sha1:e1a2b3c4   False      True    Applied revision: main@sha1:e1a2b3c4
```

### Сценарий 7: Диагностика и устранение неполадок

Flux предоставляет мощный CLI для глубокой инспекции состояния:

```bash
# Проверка готовности компонентов Flux
flux check

# Просмотр логов конкретного контроллера
flux logs --level=error --tail=100

# Трассировка процесса реконсиляции для ресурса
flux trace kustomization web-app
# -> Object: Kustomization/flux-system/web-app
# -> Status: Ready
# -> Source: GitRepository/flux-system/fleet-infra
```

## Дополнительная информация

**Связанные документы:**
- [Сравнение с ArgoCD](./argo_vs_flux_manifests.md) — детальное сравнение архитектур и манифестов.
- [Управление секретами](./secrets_encryption.md) — шифрование через SOPS и Sealed Secrets.
- [GitOps: Уведомления](./gitops_notifications.md) — настройка оповещений и алертинга.

