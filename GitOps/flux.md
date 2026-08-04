# Flux: Обзор и Ключевые Концепции

**Flux** — это модульный и расширяемый набор инструментов для построения GitOps-конвейеров в Kubernetes. Проект является частью CNCF (Graduated) и фокусируется на подходе "Unix-way", где каждый компонент решает свою задачу, а вместе они образуют гибкую систему.

## Определения

- **Flux**: Набор контроллеров, автоматизирующих синхронизацию состояния кластера с конфигурациями из Git-репозиториев и других источников.
- **GitOps Toolkit**: Набор специализированных контроллеров, из которых состоит Flux. Каждый контроллер отвечает за свой тип ресурсов (источники, Kustomize-манифесты, Helm-релизы и т.д.).
- **Reconciliation (Согласование)**: Процесс, при котором Flux сравнивает желаемое состояние в Git с фактическим состоянием в кластере и вносит изменения для их выравнивания. В основе лежит паттерн **Reconciliation Loop** (цикл сверки): контроллеры периодически сравнивают эталон (Git/Helm/OCI) и реальное состояние ресурсов в Kubernetes, при расхождениях принудительно приводя систему к заявленному виду. Это обеспечивает автоматизацию доставки, упрощает аудит и восстановление кластера (Drift Detection & Correction).

## Базовые концепции

### Архитектура GitOps Toolkit

Flux состоит из нескольких независимых контроллеров, взаимодействующих через CRD (Custom Resource Definitions). Для управления жизненным циклом самих контроллеров рекомендуется использовать **Flux Operator**.

| Контроллер | Основные CRD | Назначение |
| :--- | :--- | :--- |
| `source-controller` | `GitRepository`, `HelmRepository`, `OCIRepository`, `Bucket` | Отвечает за получение артефактов. Следит за репозиториями, чартами и OCI-реестрами, проверяет наличие новых коммитов/тегов и делает их доступными другим контроллерам. |
| `kustomize-controller`| `Kustomization` | Применяет манифесты, поддерживает Kustomize (иерархии, патчи). Отвечает за сборку финального манифеста перед отправкой в `kube-apiserver`. |
| `helm-controller` | `HelmRelease` | Управляет Helm-релизами, поддерживает автоматическое обновление зависимостей и интеграцию с OCI для чартов. |
| `notification-controller`| `Provider`, `Alert`, `Receiver` | Обрабатывает события кластера и отправляет уведомления (Slack, Teams, Loki, Webhooks). Информирует о статусе реконсиляции и ошибках. |
| `image-reflector-controller`| `ImageRepository`, `ImagePolicy` | Сканирование реестров образов и отслеживание тегов по заданным политикам (например, SemVer). |
| `image-automation-controller`| `ImageUpdateAutomation` | Автоматизация обновления тегов образов непосредственно в Git-репозитории. |

### Визуализация и GUI

Сам FluxCD не имеет встроенного графического интерфейса, следуя философии модульности, но интегрируется со сторонними решениями:
- **FreeLens**: Бесплатное расширение для Lens (и форка FreeLens), которое объединяет все ресурсы Flux (`GitRepository`, `Kustomization`, `HelmRelease`) в одной вкладке. Позволяет видеть историю операций, ошибки и ссылки на коммиты.
- **Weave GitOps**: Популярный GUI для визуализации и управления Flux-ресурсами.
- **GitOps Dashboard**: Другие UIs и интеграции, включая VS Code Extension.
- **Applied Revision**: В визуальных инструментах (как FreeLens) критически важно отслеживать столбец *Applied Revision* — он показывает хэш последнего примененного коммита, позволяя мгновенно проверить актуальность версии в кластере.

### Управление порядком деплоя (`dependsOn`)

Flux позволяет задавать строгую последовательность развертывания ресурсов (например, сначала CRD и оператор, затем кастомный ресурс).
- Реализуется через параметр `dependsOn` в объекте `Kustomization`.
- **Важно:** Зависимости не должны образовывать циклов.
- Рекомендуется использовать иерархию: базовый уровень (инфраструктура/операторы) → прикладной уровень.

### Ручное управление и отладка

Для временных работ в кластере или тестирования ad-hoc правок процесс автоматической синхронизации можно приостановить:
1. **Команды CLI:** `flux suspend ks <name>` (заморозка) и `flux resume ks <name>` (возобновление).
2. **Декларативно:** Поле `spec.suspend: true` в манифесте `Kustomization`.
3. **Принудительный запуск:** `flux reconcile kustomization <name>` — запускает цикл сверки немедленно, не дожидаясь интервала.
**Совет:** Не оставляйте `suspend` надолго, так как это нарушает принцип GitOps как единого источника истины.

### Ключевые ресурсы (CRD)

Философия Flux — разделение ответственности. Процесс развертывания описывается двумя типами ресурсов:

1. **Источник (`GitRepository`, `OCIRepository`)**: Описывает, *откуда* брать данные. С версии v2.9 через **ArtifactGenerator API** значительно оптимизирована работа с крупными монорепозиториями.
2. **Применение (`Kustomization`, `HelmRelease`)**: Описывает, *что*, *куда* и *как* разворачивать, ссылаясь на конкретный источник.

### Декларативное управление Helm

Flux позволяет управлять Helm-релизами полностью декларативно.
- **`HelmRepository`**: Описывает репозиторий чартов.
- **`HelmRelease`**: Описывает конкретный релиз (чарт, версия, `values`). `helm-controller` обеспечивает установку, обновление, проверку готовности через CEL-выражения и автоматический откат.

### Автоматизация обновления образов (Image Automation)

Flux включает встроенные механизмы для отслеживания новых версий образов в реестрах и автоматического обновления манифестов в Git.

- **`image-reflector-controller`**: Сканирует реестры образов и записывает метаданные тегов в ресурс `ImageRepository`. Использует `ImagePolicy` для выбора тега (например, SemVer-фильтры `~v1.2`).
- **`image-automation-controller`**: Выполняет коммит в Git-репозиторий при появлении тега, соответствующего политике.

**Пример настройки через маркеры в `HelmRelease`:**
Для того чтобы Flux понял, какой именно параметр в YAML нужно заменить, используются маркеры-комментарии:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
spec:
  values:
    image:
      tag: v1.0.0 # {"$imagepolicy": "flux-system:app-policy"}
```

*Примечание: Прямая правка `values.yaml` контроллером Flux может приводить к конфликтам слияния (merge conflicts) при параллельных ручных правках тех же файлов.*

### Безопасность и секреты

Flux нативно поддерживает работу с зашифрованными секретами, обеспечивая безопасность данных в Git-репозиториях:
- **Mozilla SOPS**: Основной инструмент. Секреты (YAML/JSON) шифруются с использованием KMS (AWS, GCP, Azure), HashiCorp Vault или локальных ключей (age, PGP). Расшифровка происходит "на лету" контроллером `kustomize-controller`.
- **Sealed Secrets**: Интеграция с Bitnami Sealed Secrets — секреты шифруются публичным ключом контроллера в кластере и могут быть расшифрованы только им.
- **External Secrets Operator (ESO)**: Flux может управлять манифестами `ExternalSecret`, которые синхронизируют данные из внешних хранилищ (Vault, AWS Secrets Manager) в нативные секреты Kubernetes.

**Принципы безопасности:**
- Не храните plain-text секреты в Git (даже в приватных репозиториях).
- Регулярно проводите ротацию ключей и аудит доступа к KMS.

### Управление удаленными ресурсами (`prune`)

Flux контролирует, что происходит с ресурсами в кластере после их удаления из Git через параметр `prune` в объекте `Kustomization`.
- **`prune: true`**: Автоматическая очистка (Garbage Collection). Ресурсы, удаленные из Git, удаляются из кластера. Git — единственный источник истины.
- **`prune: false`**: Ресурсы остаются в кластере даже после удаления их описания из Git.
- **Stateful-ресурсы**: Для объектов с данными (PersistentVolumeClaim, базы данных) рекомендуется устанавливать `prune: false` или выносить их в отдельную `Kustomization`, чтобы избежать случайной безвозвратной потери данных при удалении пространства имен или манифеста.

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

### Сценарий 3: Настройка зависимостей (dependsOn)

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: app-backend
  namespace: flux-system
spec:
  dependsOn:
    - name: infra-crds  # Backend начнет деплоиться только после успеха infra-crds
    - name: infra-operators
  interval: 5m
  path: ./apps/backend
  sourceRef:
    kind: GitRepository
    name: fleet-infra
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
  # Ссылка на расшифровку секретов
  # decryption:
  #   provider: sops
  #   secretRef:
  #     name: sops-age-key
```

### Сценарий 5: Ручное управление и отладка

```bash
# Приостановить синхронизацию для проведения ручных работ
flux suspend kustomization web-app

# После завершения работ возобновить процесс
flux resume kustomization web-app

# Принудительно запустить цикл сверки (не дожидаясь интервала)
flux reconcile kustomization web-app --with-source
# → ► annotating Kustomization web-app in flux-system namespace
# → ✔ reconciliation triggered
```

### Сценарий 6: Просмотр состояния и ревизий

```bash
flux get kustomizations
# → NAME    REVISION             SUSPENDED  READY   MESSAGE
# → web-app main@sha1:e1a2b3c4   False      True    Applied revision: main@sha1:e1a2b3c4
```

## Дополнительная информация

**Связанные документы:**
- [Сравнение с ArgoCD](./argo_vs_flux_manifests.md) — детальное сравнение архитектур.
- [Управление секретами](./secrets_encryption.md) — подробнее о SOPS и Sealed Secrets.
- [GitOps: Уведомления](./gitops_notifications.md) — детальная настройка алертинга в Slack/Teams.
- [Документация Flux](https://fluxcd.io/) — официальный справочник и руководства.

