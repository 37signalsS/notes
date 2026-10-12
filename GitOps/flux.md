# Flux — обзор и ключевые концепции

**Flux** — это модульный и расширяемый набор инструментов для построения GitOps-конвейеров в Kubernetes. Проект является частью CNCF (Graduated) и фокусируется на подходе "Unix-way", где каждый компонент решает свою задачу, а вместе они образуют гибкую систему.

Актуальная линейка версий — **Flux v2.9.x** (GA-релиз v2.9.0 — 30 июня 2026, последний патч — v2.9.4, август 2026). Поддерживаются Kubernetes 1.34–1.36 и OpenShift 4.21; ветка v2.6 достигла статуса end-of-life и больше не получает исправлений. Flux следует релизному циклу Kubernetes (три минорных релиза в год) и поддерживает N-2 минорных версий Kubernetes.

## Определения

- **Flux**: Набор контроллеров, автоматизирующих синхронизацию состояния кластера с конфигурациями из Git-репозиториев и других источников.
- **GitOps Toolkit**: Набор специализированных контроллеров, из которых состоит Flux. Каждый контроллер отвечает за свой тип ресурсов (источники, Kustomize-манифесты, Helm-релизы и т.д.).
- **Reconciliation (Согласование)**: Процесс, при котором Flux сравнивает желаемое состояние в Git с фактическим состоянием в кластере и вносит изменения для их выравнивания. В основе лежит паттерн **Reconciliation Loop** (цикл сверки): контроллеры периодически сравнивают эталон (Git/Helm/OCI) и реальное состояние ресурсов в Kubernetes, при расхождениях принудительно приводя систему к заявленному виду. Это обеспечивает автоматизацию доставки, упрощает аудит и восстановление кластера (Drift Detection & Correction).
- **Bootstrap**: Процесс первоначальной установки Flux в кластер, при котором компоненты Flux устанавливаются из манифестов, закоммиченных в целевой Git-репозиторий. После bootstrap кластер начинает «управлять сам собой»: любые изменения конфигурации Flux вносятся через Git, а не императивными командами.
- **Artifact (Артефакт)**: Итоговый результат работы `source-controller` — tar-архив с манифестами/чартом, который распространяется между контроллерами внутри кластера. Каждый артефакт имеет ревизию (revision), связанную с коммитом, тегом или digest-хэшем источника.

## Предварительные требования

Для установки и работы с Flux v2.9 необходимы:

| Компонент | Требование |
| :--- | :--- |
| Kubernetes | Версия 1.34, 1.35 или 1.36 (для Flux v2.9); для OpenShift — 4.21 |
| flux CLI | Версия, соответствующая устанавливаемому Flux (например, v2.9.4) |
| kubectl | Совместимая с версией кластера |
| Git-провайдер | GitHub, GitLab, Bitbucket, AWS CodeCommit или любой Git по HTTPS/SSH |
| Права доступа | Персональный токен (GitHub PAT) со scope `repo` либо эквивалентные права на создание deploy key и webhook |

Установка CLI (Linux/macOS):

```bash
# Через Homebrew (macOS/Linux)
brew install fluxcd/tap/flux

# Или скриптом (Linux/macOS)
curl -s https://fluxcd.io/install.sh | sudo bash

# Проверка версии
flux --version
# -> flux version 2.9.4
```

Перед установкой в кластер можно проверить готовность окружения:

```bash
flux check --pre
# ► checking prerequisites
# ✔ Kubernetes 1.35.3 >=1.34.0-0
# ✔ prerequisites checks passed
```

## Базовые концепции

### Архитектура набора инструментов GitOps (GitOps Toolkit)

Flux состоит из нескольких независимых контроллеров, взаимодействующих через CRD (Custom Resource Definitions).

| Контроллер | Основные CRD | Назначение |
| :--- | :--- | :--- |
| `source-controller` | `GitRepository`, `HelmRepository`, `OCIRepository`, `Bucket` | Отвечает за получение артефактов. Следит за репозиториями, чартами и OCI-реестрами, проверяет наличие новых коммитов/тегов и делает их доступными другим контроллерам. |
| `source-watcher` | `ArtifactGenerator` | Компонент, появившийся в экосистеме Flux для работы с монорепозиториями: генерирует составные артефакты из нескольких источников, снижая нагрузку на сеть и количество пересборок. Начиная с Flux v2.9 включается в базовый набор манифестов установки. |
| `kustomize-controller`| `Kustomization` | Применяет манифесты, поддерживает Kustomize (иерархии, патчи). Отвечает за сборку финального манифеста перед отправкой в `kube-apiserver`. |
| `helm-controller` | `HelmRelease` | Управляет Helm-релизами, поддерживает автоматическое обновление зависимостей и интеграцию с OCI для чартов. |
| `notification-controller`| `Provider`, `Alert`, `Receiver` | Обрабатывает события кластера и отправляет уведомления (Slack, Teams, Loki, Webhooks). Информирует о статусе реконсиляции и ошибках. Также принимает входящие webhook-события через `Receiver` (например, триггер реконсиляции из CI). |
| `image-reflector-controller`| `ImageRepository`, `ImagePolicy` | Сканирование реестров образов и отслеживание тегов по заданным политикам (например, SemVer). |
| `image-automation-controller`| `ImageUpdateAutomation` | Автоматизация обновления тегов образов непосредственно в Git-репозитории. |

Особенности архитектуры:

- Все контроллеры по умолчанию разворачиваются в namespace `flux-system`, каждый — под собственным `ServiceAccount` с минимально необходимыми RBAC-правами.
- Каждый контроллер экспортирует метрики в формате Prometheus на порту `8080` (endpoint `/metrics`) — это стандартная точка интеграции с мониторингом.
- Контроллеры публикуют события Kubernetes непосредственно на управляемых объектах (например, `ReconciliationSucceeded`, `Progressing`, `ValidationFailed` на `Kustomization`), что упрощает диагностику через `kubectl describe` и `flux events`.
- Контроллеры не общаются друг с другом напрямую: связь идет через Kubernetes API — один контроллер читает статус артефакта другого. Это делает архитектуру слабосвязанной и позволяет заменять компоненты независимо.

### Модель реконсиляции и жизненный цикл объекта

Понимание жизненного цикла `Kustomization`/`HelmRelease` необходимо для отладки:

1. **Триггер**: истечение `spec.interval`, входящий webhook (`Receiver`), аннотация `reconcile.fluxcd.io/requestedAt` (устанавливается командой `flux reconcile`) или изменение зависимого объекта (`dependsOn`).
2. **Получение источника**: контроллер сверяет ревизию артефакта источника (`status.artifact.revision`) с последней доступной ревизией upstream.
3. **Сборка**: для `Kustomization` выполняется server-side kustomize build (с учетом `postBuild.substitute`); для `HelmRelease` — рендеринг чарта с values и post-renderers.
4. **Применение**: манифесты применяются через Server-Side Apply с полем `fieldManager` вида `flux-client-side-apply`/`kustomize-controller`; опционально выполняются `healthChecks`.
5. **Фиксация результата**: статус объекта обновляется — условия `Ready` (`True`/`False`), поля `status.lastAppliedRevision`, `status.lastAttemptRevision`; при успехе публикуется событие `ReconciliationSucceeded`.

Ключевые параметры поведения:

- `spec.interval` — период цикла сверки (обязательное поле).
- `spec.timeout` — максимальное время одной итерации (по умолчанию меньше `interval`).
- `spec.retry` — число повторных попыток после неудачи; задержка растет экспоненциально (backoff), что защищает API-сервер от шторма запросов при устойчивых ошибках.
- `spec.suspend` — приостановка реконсиляции без удаления объекта.

Такой дизайн означает, что Flux самовосстанавливающийся: даже если ручные изменения в кластере переживают одну итерацию, следующая снова приведет состояние к эталону из Git (если не настроены правила игнорирования полей — см. раздел про контроль дрейфа).

### Управление жизненным циклом через Flux Operator

Для управления самим Flux (установка, обновление, конфигурация компонентов) рекомендуется использовать **Flux Operator**. Он позволяет:
- Декларативно описывать желаемую версию Flux и состав включенных контроллеров (через API `FluxInstance`).
- Управлять несколькими инстансами Flux в одном кластере (sharding), распределяя нагрузку реконсиляции.
- Автоматизировать миграции и обновление CRD.
- Описывать поставку приложений через API `ResourceSet` и `ResourceSetInputProvider` — шаблонизацию наборов объектов Flux без внешних инструментов.
- Работать с веб-интерфейсом (Flux Operator UI) для визуализации состояния.

Operator особенно удобен в сценариях, где нужно единообразно управлять Flux в десятках кластеров: конфигурация `FluxInstance` сама хранится в Git и доставляется GitOps-подходом.

### Визуализация и графический интерфейс (GUI)

Сам FluxCD не имеет встроенного графического интерфейса, следуя философии модульности, но интегрируется со сторонними решениями:
- **FreeLens**: Бесплатное расширение для Lens (и форка FreeLens), которое объединяет все ресурсы Flux (`GitRepository`, `Kustomization`, `HelmRelease`) в одной вкладке. Позволяет видеть историю операций, ошибки и ссылки на коммиты.
- **Weave GitOps**: Популярный GUI для визуализации и управления Flux-ресурсами. Обратите внимание: после закрытия компании Weaveworks (2024) open-source версия проекта развивается ограниченно — перед внедрением проверяйте актуальность поддержки.
- **Flux Operator UI**: Веб-дашборд в составе Flux Operator, отображающий дерево ресурсов Flux, их статусы и связи.
- **GitOps Dashboard**: Другие UI и интеграции, включая расширение для VS Code.
- **Applied Revision**: В визуальных инструментах критически важно отслеживать столбец *Applied Revision* — он показывает хэш последнего примененного коммита, позволяя мгновенно проверить актуальность версии в кластере.

### Управление порядком развертывания (dependsOn)

Flux позволяет задавать строгую последовательность развертывания ресурсов (например, сначала CRD и оператор, затем кастомный ресурс).
- Реализуется через параметр `dependsOn` в объекте `Kustomization`.
- **Важно:** Зависимости не должны образовывать циклов.
- Рекомендуется использовать иерархию: базовый уровень (инфраструктура/операторы) → прикладной уровень.
- Зависимость считается выполненной только когда родительская `Kustomization` перешла в состояние `Ready=True` (все `healthChecks` пройдены). Это позволяет строить надежные цепочки: CRDs → оператор → кастомные ресурсы приложения.

Пример двухуровневой зависимости:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-cert-manager-crds
  namespace: flux-system
spec:
  interval: 1h
  path: ./infrastructure/cert-manager/crds
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infra-cert-manager
  namespace: flux-system
spec:
  interval: 10m
  dependsOn:
    - name: infra-cert-manager-crds # начнется только после Ready первого объекта
  path: ./infrastructure/cert-manager/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
```

Циклические зависимости обнаруживаются контроллером и фиксируются в статусе объекта как ошибка — объекты из цикла не будут реконcилированы вовсе, поэтому граф зависимостей стоит проектировать заранее как DAG (направленный ациклический граф).

### Мультитенентность и изоляция (Multi-tenancy)

Flux v2 спроектирован с учетом безопасности в многопользовательских средах:
- **Service Account Impersonation**: Каждая `Kustomization` или `HelmRelease` может выполняться от имени конкретного `ServiceAccount`. Это ограничивает права Flux на манипуляции только теми ресурсами, к которым есть доступ у данного аккаунта.
- **Namespace isolation**: Контроллеры могут быть настроены на прослушивание только определенных пространств имен.
- **Tenant Self-Service**: Позволяет командам управлять своими релизами в выделенных неймспейсах без доступа к системным настройкам Flux.

При включении строгого режима multi-tenancy lockdown (флаги контроллеров `--default-service-account` и запрет привилегированных аккаунтов) указание `spec.serviceAccountName` становится обязательным: если тенант его не задал, реконсиляция выполняется от дефолтного ограниченного аккаунта его namespace, а не от административного аккаунта Flux. Это предотвращает эскалацию привилегий через манифесты в Git.

### Ручное управление и отладка

Для временных работ в кластере или тестирования ad-hoc правок процесс автоматической синхронизации можно приостановить:
1. **Команды CLI:** `flux suspend ks <name>` (заморозка) и `flux resume ks <name>` (возобновление).
2. **Декларативно:** Поле `spec.suspend: true` в манифесте `Kustomization`.
3. **Принудительный запуск:** `flux reconcile kustomization <name>` — запускает цикл сверки немедленно, не дожидаясь интервала.
**Совет:** Не оставляйте `suspend` надолго, так как это нарушает принцип GitOps как единого источника истины.

Важно понимать семантику suspend: приостановленный объект перестает не только применять изменения, но и корректировать дрейф — ручные правки в кластере сохранятся до возобновления. Поэтому список suspended-объектов стоит периодически аудировать (`flux get all --status-selector ready=False`, `flux get kustomizations | grep True`).

### Ключевые ресурсы (CRD)

Процесс развертывания описывается двумя типами ресурсов:

1. **Источник (`GitRepository`, `OCIRepository`)**: Описывает, *откуда* брать данные.
2. **Применение (`Kustomization`, `HelmRelease`)**: Описывает, *что*, *куда* и *как* разворачивать, ссылаясь на конкретный источник.

Актуальные версии API (на момент Flux v2.9):

| Ресурс | apiVersion | Статус |
| :--- | :--- | :--- |
| `GitRepository`, `HelmRepository`, `Bucket` | `source.toolkit.fluxcd.io/v1` | GA |
| `OCIRepository` | `source.toolkit.fluxcd.io/v1beta2` | Beta |
| `Kustomization` | `kustomize.toolkit.fluxcd.io/v1` | GA |
| `HelmRelease` | `helm.toolkit.fluxcd.io/v2` | GA (мигрируйте с v2beta1/v2beta2) |
| `ImageRepository`, `ImagePolicy`, `ImageUpdateAutomation` | `image.toolkit.fluxcd.io/v1` | GA |
| `Provider`, `Alert`, `Receiver` | `notification.toolkit.fluxcd.io/v1beta3` | Beta |

В Flux v2.9 из состава CRD удалены end-of-life версии API (устаревшие beta-версии). Перед обновлением выполните миграцию существующих манифестов командой `flux migrate` — она автоматически перепишет `apiVersion` в манифестах Git-репозитория и переведет объекты в кластере на стабильные версии (см. Сценарий 10).

### Использование OCI-репозиториев

Современный подход во Flux — использование OCI-совместимых реестров (Docker Hub, GHCR, Harbor) в качестве источников не только для образов, но и для Helm-чартов и обычных YAML-манифестов.
- **Преимущества**: Высокая скорость загрузки, поддержка тегов и версионирования, единое хранилище для всех артефактов.
- **Дополнительно**: Immutable-теги и digest-пиннинг дают детерминированность доставки; доступ к приватным реестрам настраивается через `secretRef` с docker-конфигом.
- **Ресурс**: `OCIRepository`.

Публикация манифестов в OCI-реестр выполняется локально или из CI:

```bash
# Собрать kustomization и запушить как OCI-артефакт
flux push artifact oci://ghcr.io/my-org/manifests/app:$(git rev-parse --short HEAD) \
  --path=./apps/prod \
  --source="$(git config --get remote.origin.url)" \
  --revision="$(git branch --show-current)@sha1:$(git rev-parse HEAD)"

# Проставить плавающий тег latest для Flux
flux tag artifact oci://ghcr.io/my-org/manifests/app:$(git rev-parse --short HEAD) --tag=latest
```

### Источники типа Bucket (S3-совместимые хранилища)

Помимо Git и OCI, source-controller умеет забирать артефакты из объектных хранилищ (`Bucket`): AWS S3, Azure Blob, GCS и любые S3-совместимые (MinIO):

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: Bucket
metadata:
  name: platform-configs
  namespace: flux-system
spec:
  interval: 10m
  provider: generic            # aws | azure | gcp | generic (S3-совместимые)
  bucket: configs
  endpoint: http://minio.minio-system.svc.cluster.local:9000
  insecure: true               # только для внутренних endpoint'ов!
  secretRef:
    name: minio-credentials    # access/secret key
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: platform-stack
  namespace: flux-system
spec:
  interval: 10m
  sourceRef:
    kind: Bucket               # Kustomization работает с Bucket как с Git
    name: platform-configs
  path: ./stacks/base
```

Когда выбирать Bucket вместо GitRepository/OCIRepository:

| Случай | Почему Bucket |
| :--- | :--- |
| Air-gapped контуры без внутреннего Git-зеркала | Артефакты распространяются через существующее объектное хранилище |
| Конфигурации, порождаемые автоматикой (CI выкладывает tar.gz) | Не нужен рабочий Git-репозиторий для машинных артефактов |
| Крупные бинарные ассеты рядом с манифестами | Git плохо хранит большие файлы |

Во всех остальных случаях предпочтительнее `OCIRepository`: стандартизированные подписи (Cosign), digest-неизменяемость и единый транспорт с образами. Bucket — инструмент нишевых сценариев, а не замена Git.

### Декларативное управление Helm

Flux позволяет управлять Helm-релизами полностью декларативно.
- **`HelmRepository`**: Описывает репозиторий чартов.
- **`HelmRelease`**: Описывает конкретный релиз. `helm-controller` обеспечивает установку, обновление и автоматический откат при сбоях.
- **Детекция дрейфа**: helm-controller сравнивает фактическое состояние релиза с рассчитанным желаемым и корректирует расхождения (например, после ручного `helm set` или `kubectl edit`) — в пределах своей итерации реконсиляции.
- **Post-rendering**: Встроенная поддержка Kustomize-постобработки значений и манифестов чарта (`spec.postRender.kustomize`), включая стратегии обработки chart hooks (см. раздел о v2.9).

Минимальный каркас `HelmRelease` с политиками восстановления:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: podinfo
  namespace: default
spec:
  interval: 10m
  chartRef:
    kind: OCIRepository
    name: podinfo
  install:
    remediation:
      retries: 3          # повторить неудавшуюся установку до 3 раз
  upgrade:
    remediation:
      retries: 3
      strategy: rollback  # при неудаче upgrade — откат к предыдущей ревизии
  values:
    replicaCount: 2
```

### Автоматизация обновления образов (Image Automation)

Flux включает механизмы для отслеживания новых версий образов в реестрах и автоматического обновления манифестов в Git.

- **`image-reflector-controller`**: Сканирует реестры образов и записывает метаданные тегов в ресурс `ImageRepository`. Использует `ImagePolicy` для выбора тега (например, SemVer `~v1.2`).
- **`image-automation-controller`**: Выполняет коммит в Git-репозиторий при появлении тега, соответствующего политике.

Полный набор ресурсов автоматизации:

```yaml
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageRepository
metadata:
  name: web-app
  namespace: flux-system
spec:
  interval: 5m
  image: ghcr.io/my-org/web-app
---
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImagePolicy
metadata:
  name: web-app
  namespace: flux-system
spec:
  imageRepositoryRef:
    name: web-app
  filterTags:
    pattern: '^v(?P<semver>[0-9]+\.[0-9]+\.[0-9]+)-.*$'
    extract: '$semver'
  policy:
    semver:
      range: '>=1.0.0'
---
apiVersion: image.toolkit.fluxcd.io/v1
kind: ImageUpdateAutomation
metadata:
  name: fleet-infra-autamation
  namespace: flux-system
spec:
  interval: 30m
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  git:
    checkout:
      ref:
        branch: main
    commit:
      author:
        name: fluxbot
        email: flux@example.com
      messageTemplate: 'chore: update image {{.Updated.Image}}'
    push:
      branch: main
  update:
    path: ./apps/prod
    strategy: setters
```

Обновляемое значение помечается маркером в любом манифесте (HelmRelease, Deployment и др.) — контроллер заменит значение тега, найденное политикой:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: web-app
spec:
  values:
    image:
      repository: ghcr.io/my-org/web-app
      tag: v1.0.0 # {"$imagepolicy": "flux-system:web-app"}
```

Комментарий-маркер `{"$imagepolicy": "<ns>:<policy>"}` — контракт между манифестом и `ImagePolicy`: image-automation-controller перепишет значение строки выше комментария на последний тег, выбранный политикой. Историю применения видно в коммитах Git-репозитория — это дает полный аудит изменений версий образов.

### Безопасность и управление секретами

Flux нативно поддерживает работу с зашифрованными секретами:
- **Mozilla SOPS**: Основной инструмент. Секреты шифруются через KMS или age/PGP. Расшифровка происходит "на лету" контроллером `kustomize-controller`.
- **Sealed Secrets**: Интеграция с Bitnami Sealed Secrets — шифрование публичным ключом кластера.
- **External Secrets Operator (ESO)**: Синхронизация данных из внешних хранилищ (Vault, AWS Secrets Manager) в нативные секреты Kubernetes.

Подключение расшифровки SOPS к `Kustomization`:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: web-app
  namespace: flux-system
spec:
  interval: 10m
  path: ./apps/prod
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  decryption:
    provider: sops
    secretRef:
      name: sops-age # Secret с приватным ключом age в flux-system
```

Новое в v2.9 в части секретов:
- Поддержка постквантового шифра **Age** для SOPS — защита секретов шифрованием, устойчивым к квантовым атакам, без изменения рабочего процесса GitOps.
- Аутентификация kustomize-controller в **OpenBao и HashiCorp Vault через Kubernetes Workload Identity** — токен ServiceAccount контроллера обменивается на учетные данные Vault, что исключает хранение долгоживущих токенов в кластере.

Подробное руководство по шифрованию: [Управление секретами](./secrets_encryption.md).

### Контроль дрейфа и игнорирование полей

Server-Side Apply позволяет Flux точно знать, какими полями он владеет, однако часть полей законно управляется другими контроллерами (HPA меняет `spec.replicas`, cert-manager — `spec.tls`). Без настройки такие поля будут постоянно «мерцать» туда-сюда, генерируя шум в событиях и логах.

Механизмы контроля:

1. **Строковое поле `spec.ignore`** (исторический механизм) — JSON Patch-пути, которые kustomize-controller исключает из сверки:

   ```yaml
   spec:
     ignore: |
       /spec/replicas
   ```

2. **Структурированные правила игнорирования полей SSA** (Flux v2.9+) — тонкий контроль над тем, какие managed fields игнорировать при apply и детекции дрейфа, с возможностью привязки правила к конкретному field manager (например, оставить `spec.replicas` под владением HPA):

   ```yaml
   # Flux v2.9+
   spec:
     ignore:
       - fieldManager: HPA
         paths:
           - /spec/replicas
   ```

Правильно настроенные ignore-правила — обязательная часть production-конфигурации: они убирают ложные события дрейфа и предотвращают борьбу контроллеров за одни и те же поля.

### Верификация источников (Source Verification)

Для обеспечения безопасности в production-средах Flux поддерживает проверку подлинности источников:
- **SSH Verification**: Использование `known_hosts` для проверки личности Git-сервера.
- **GPG/Cosign Signing**: Проверка подписей коммитов или OCI-артефактов. Если подпись неверна, Flux откажется применять манифесты. Настраивается через поле `spec.verify` в `GitRepository` или `OCIRepository`.
- **SSH-подписи (v2.9+)**: Наряду с GPG source-controller умеет верифицировать подписи коммитов, сделанные SSH-ключами (`GitRepository.spec.verify`), а image-automation-controller может подписывать свои коммиты SSH-ключом (`ImageUpdateAutomation.spec.git.commit.signingKey`); подписывать коммиты умеет и `flux bootstrap`.

Пример включения проверки подписи коммитов:

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: fleet-infra
  namespace: flux-system
spec:
  interval: 1m
  url: ssh://git@github.com/my-org/fleet-infra
  ref:
    branch: main
  verify:
    mode: HEAD # проверять подпись последнего коммита ветки
    secretRef:
      name: gpg-public-keys # Secret с публичными ключами (GPG или SSH)
```

Если подпись отсутствует или невалидна, объект `GitRepository` перейдет в состояние `Ready=False` с диагностикой в статусе, а применение манифестов будет остановлено — fail-closed поведение безопасно по умолчанию.

### Масштабирование и производительность

При управлении сотнями `Kustomization` или `HelmRelease` могут потребоваться оптимизации:
- **Resource Limits**: Настройка лимитов CPU/Memory для контроллеров (особенно `kustomize-controller`).
- **Sharding**: Использование **Flux Operator** для распределения ресурсов между несколькими инстансами Flux.
- **Interval Tuning**: Увеличение `spec.interval` для некритичных приложений, чтобы снизить нагрузку на API-сервер.
- **Concurrency**: Флаги контроллеров (`--concurrent`) регулируют число параллельных реконсиляций одного контроллера; значения по умолчанию консервативны и подходят для большинства случаев, но при тысячах объектов их стоит поднять вместе с лимитами памяти.
- **Мониторинг**: Метрики контроллеров (порт 8080, `/metrics`) содержат длительность реконсиляций, размеры очередей workqueue и ошибки — по ним строятся алерты на деградацию конвейера доставки (например, `gotk_reconcile_condition`).

### Ключевые изменения в версии v2.9 (июнь 2026)

GA-релиз v2.9.0 опубликован 30 июня 2026; текущий патч — v2.9.4.

| Функция | Описание |
| :--- | :--- |
| **Система плагинов CLI (RFC-0013)** | Новая архитектура для расширения возможностей `flux` CLI сторонними инструментами; плагины (Mirror, Schema) версируются и поставляются независимо от CLI, устанавливаются через `flux plugin install` с поддержкой digest-пиннинга. |
| **ArtifactGenerator API** | Работа `source-watcher` с монорепозиториями: генерация артефактов из нескольких источников, снижение нагрузки на сеть. |
| **Улучшения SSA** | Расширенный контроль над игнорированием полей (`Kustomization.spec.ignore` / DriftIgnoreRules) при синхронизации — см. раздел «Контроль дрейфа». |
| **Расшифровка SOPS постквантовым шифром Age** | Защита секретов квантовоустойчивым шифрованием в рамках привычного SOPS-процесса. |
| **Workload Identity для OpenBao/Vault** | Keyless-аутентификация kustomize-controller в хранилищах секретов через токен ServiceAccount. |
| **Helm post-render стратегии** | Новые стратегии post-rendering в `HelmRelease`, управляющие участием chart hooks; поддержка подписания/верификации Git-коммитов SSH-ключами. |
| **OIDC-secured Receivers** | Webhook `Receiver` могут проверять OIDC ID-token вызывающего вместо общего секрета — бесшовная интеграция с платформами, поддерживающими OIDC. Новая команда `flux trigger receiver` для запуска webhook из CLI/CI. |
| **AWS CodeCommit** | Аутентификация через Workload Identity и поддержка `flux bootstrap git` для CodeCommit. |
| **Guidance для AI-агентов** | Официальное руководство по использованию Flux с AI coding assistants (документация и best practices для агентных сценариев). |
| **GCP Sovereign Cloud** | Нативная поддержка Artifact Registry в суверенных облаках Google. |

Критические изменения (breaking changes) v2.9 — проверьте перед обновлением:

1. **Стратегия Helm post-render по умолчанию изменена с `nohooks` на `combined`**: теперь chart hooks участвуют в post-rendering (ближе к нативному поведению Helm). Если ваши чарты полагались на старое поведение — явно укажите стратегию `nohooks` в `HelmRelease` до обновления.
2. **Удалены end-of-life версии API из CRD**: ресурсы на устаревших beta-версиях перестают применяться. Выполните миграцию командой `flux migrate` (см. Сценарий 10).
3. **CVE-2026-40109**: GCP-Receiver'ы (`type: gcr`) теперь требуют поля `email` и `audience` в ссылаемом Secret — проверьте существующие Receivers.
4. **Flux v2.6 EOL**: прямые обновления рекомендуется выполнять согласно процедуре Upgrade Procedure for Flux v2.7+.

## Практические сценарии

### Сценарий 1: Первоначальная установка (Bootstrap)

Настраивает кластер так, чтобы он управлял сам собой из Git-репозитория.

Что делает команда bootstrap:
1. Создает deploy key в Git-репозитории (для read/write доступа Flux к репозиторию) и регистрирует webhook для мгновенного триггера реконсиляции.
2. Коммитит в репозиторий манифесты компонентов Flux (по пути `--path`).
3. Устанавливает в кластер namespace `flux-system`, CRD и деплойменты всех контроллеров.
4. Создает корневой объект `Kustomization` с именем `flux-system`, который далее синхронизирует всю конфигурацию из этого пути репозитория.

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

Расшифровка параметров:

| Параметр | Значение |
| :--- | :--- |
| `--owner` | Владелец репозитория (организация или пользователь) |
| `--repository` | Имя репозитория с инфраструктурой (fleet-infra — рекомендация документации Flux) |
| `--branch` | Ветка, из которой будет идти синхронизация |
| `--path` | Путь внутри репозитория с манифестами данного кластера; разные кластеры = разные пути в одном репозитории |
| `--personal` | Создать личный (private) репозиторий, а не в организации |

Проверка успешности установки:

```bash
# Компоненты установлены и здоровы
flux check
# ► checking components
# ✔ source-controller is healthy
# ✔ kustomize-controller is healthy
# ✔ helm-controller is healthy
# ✔ notification-controller is healthy
# ✔ all components are healthy

# Корневая kustomization синхронизирована
flux get kustomizations --namespace flux-system
# -> NAME         REVISION              SUSPENDED  READY  MESSAGE
# -> flux-system  main@sha1:<hash>      False      True   Applied revision: main@sha1:<hash>
```

Для приватных репозиториев дополнительно создайте Secret с учетными данными (`flux create secret git`) или используйте SSH deploy key, который bootstrap создает автоматически.

### Сценарий 2: Развертывание приложения через Kustomize

Полный минимальный набор: источник + применение. Сначала описываем источник:

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: fleet-infra
  namespace: flux-system
spec:
  interval: 1m            # как часто проверять upstream на новые коммиты
  url: https://github.com/my-org/fleet-infra
  ref:
    branch: main
```

Затем — правило применения:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: web-app
  namespace: flux-system
spec:
  interval: 5m
  path: ./apps/prod       # путь относительно корня артефакта источника
  prune: true             # удалять ресурсы, исчезнувшие из Git
  sourceRef:
    kind: GitRepository
    name: fleet-infra
  healthChecks:
    - kind: Deployment
      name: web-app
      namespace: apps
```

Назначение полей:
- `interval` — период реконсиляции; `healthChecks` блокируют переход в `Ready=True`, пока Deployment не станет доступным, что важно для цепочек `dependsOn`;
- `prune: true` — Git полностью определяет состав ресурсов (см. раздел prune ниже);
- `healthChecks` — гейт готовности: зависимые kustomizations стартуют только после прохождения проверок.

Применение и валидация:

```bash
kubectl apply -f gitrepository.yaml -f kustomization.yaml

# Статус источника: артефакт собран из последнего коммита
flux get sources git
# -> NAME         REVISION             SUSPENDED READY MESSAGE
# -> fleet-infra  main@sha1:e1a2b3c4   False     True  Stored artifact for revision 'main@sha1:e1a2b3c4'

# Статус применения
flux get kustomizations
# -> NAME    REVISION             SUSPENDED  READY   MESSAGE
# -> web-app main@sha1:e1a2b3c4   False      True    Applied revision: main@sha1:e1a2b3c4
```

Ожидаемый результат: Deployment `web-app` в namespace `apps` создан и проходит `healthChecks`; событие `ReconciliationSucceeded` на объекте `Kustomization/web-app`.

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

Подготовка ограниченного аккаунта тенанта:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: team-a-reconciler
  namespace: team-a
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: team-a-reconciler
  namespace: team-a
subjects:
  - kind: ServiceAccount
    name: team-a-reconciler
    namespace: team-a
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: admin # права только в пределах namespace team-a
```

Без RoleBinding (или при недостаточных правах) реконсиляция завершится ошибками Forbidden в статусе `Kustomization` — это и есть ожидаемая работа изоляции.

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

Использование источника в `Kustomization` — достаточно поменять `sourceRef`:

```yaml
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: podinfo
  namespace: flux-system
spec:
  interval: 10m
  path: ./
  prune: true
  sourceRef:
    kind: OCIRepository
    name: podinfo
```

Приватный реестр подключается через `spec.secretRef` с dockerconfigjson-Secret; для верификации подписей артефактов используется `spec.verify` (Cosign). Проверка статуса: `flux get sources oci` — сообщение должно подтвердить получение артефакта по digest.

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

Флаг `--with-source` заставляет сначала переконсолидировать источник (GitRepository), затем применение — удобно сразу после push в Git.

### Сценарий 6: Просмотр состояния и ревизий

```bash
flux get kustomizations
# -> NAME    REVISION             SUSPENDED  READY   MESSAGE
# -> web-app main@sha1:e1a2b3c4   False      True    Applied revision: main@sha1:e1a2b3c4
```

Полная сводка по всем объектам Flux (источники, применения, Helm-релизы, уведомления):

```bash
flux get all --status-selector ready=False
# -> покажет только проблемные объекты со статусами и сообщениями об ошибках
```

Столбец REVISION содержит ссылку на конкретную ревизию источника (коммит/тег/digest) — сверив ее с Git, вы всегда знаете, какая версия конфигурации реально применена в кластере.

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

Дополнительные инструменты диагностики:

```bash
# События конкретного объекта (причины неудачных итераций)
kubectl describe kustomization web-app -n flux-system
# Events: Warning  ReconciliationFailed  ...  rpc error: ... Health check failed

# Логи конкретного контроллера напрямую
kubectl logs -n flux-system deploy/kustomize-controller --tail=100

# Dry-run сборки локально (без кластера): увидеть итоговые манифесты
flux build kustomization web-app --path ./apps/prod > rendered.yaml
```

Типовые ошибки и их решение:

| Симптом (сообщение в статусе/логах) | Причина | Решение |
| :--- | :--- | :--- |
| `authentication failed` у source-controller | Невалидный токен/deploy key, истек срок доступа | Пересоздать Secret с кредами: `flux create secret git`; проверить deploy key в настройках репозитория |
| `OOMKilled` у kustomize-controller | Очень большие манифесты/много объектов | Увеличить memory limits деплоймента контроллера; разбить монолитную kustomization |
| `Health check failed after timeout` | Приложение не проходит readiness; неправильные имена/namespace в `healthChecks` | `kubectl get pods -n apps`; сверить имена в `healthChecks` с реальными ресурсами |
| `Helm upgrade failed: ... has no deployed releases` | Рассинхронизация state Helm (ручные операции helm) | Проверить `helm history <release>`; при необходимости `flux reconcile helmrelease <name> --reset` |
| `dependency cycle detected` | Цикл в графе `dependsOn` | Построить граф (`flux get kustomizations`), убрать циклическую связь |
| Объект `Ready=False` без явной ошибки, реконcиляция не идет | `spec.suspend: true` | `flux get kustomizations` (столбец SUSPENDED), снять suspend: `flux resume` |
| Ручные правки постоянно затираются контроллером | Поле управляется и Git, и другим контроллером (HPA и т.п.) | Добавить поле в `spec.ignore` (см. раздел «Контроль дрейфа») |
| `validation failed` при apply | Манифест не проходит admission webhook / схему | Изучить событие `ValidationFailed`; проверить версию CRD в манифестах |

Общий порядок расследования: `flux get all --status-selector ready=False` → `flux trace <объект>` → события объекта (`kubectl describe`) → логи соответствующего контроллера (`flux logs --controller=<name>`).

### Сценарий 8: Развертывание Helm-релиза

Классическая пара для чарта из HTTP-репозитория:

```yaml
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: podinfo-charts
  namespace: flux-system
spec:
  interval: 10m
  url: https://stefanprodan.github.io/podinfo
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: podinfo
  namespace: default
spec:
  interval: 10m
  timeout: 5m
  chart:
    spec:
      chart: podinfo
      version: ">=6.0.0 <7.0.0" # SemVer-диапазон: автообновление внутри мажора
      sourceRef:
        kind: HelmRepository
        name: podinfo-charts
  install:
    remediation:
      retries: 3
  upgrade:
    remediation:
      retries: 3
      strategy: rollback
  values:
    replicaCount: 2
    resources:
      requests:
        cpu: 100m
        memory: 128Mi
```

Логика работы: helm-controller резолвит максимальную подходящую версию чарта, рендерит шаблоны, применяет манифесты и следит за дрейфом; при неудаче upgrade выполняется откат к предыдущей рабочей ревизии (`strategy: rollback`). Обновление версии чарта происходит автоматически при выходе новой, попадающей в диапазон `version` — пиннинг конкретной версии осуществляется явным указанием `version: 6.7.0`.

Проверка:

```bash
flux get helmreleases --all-namespaces
# -> NAME     REVISION SUSPENDED READY MESSAGE
# -> podinfo  6.7.0    False     True  Upgrade succeeded
```

Внимание (Flux v2.9+): стратегия post-render по умолчанию — `combined` (chart hooks участвуют в постобработке). Для чартов, зависящих от прежнего поведения, задайте стратегию явно.

### Сценарий 9: Шифрование секретов через SOPS

Шаги настройки end-to-end:

```bash
# 1. Сгенерировать ключ age
age-keygen -o age.key.txt
# Public key: age1abc...

# 2. Сохранить приватный ключ как Secret в flux-system
kubectl create secret generic sops-age \
  --namespace flux-system \
  --from-file=age.agekey=age.key.txt
```

```yaml
# 3. Конфигурация .sops.yaml в репозитории — какие файлы чем шифровать
creation_rules:
  - path_regex: .*\.enc\.yaml$
    encrypted_regex: ^(data|stringData)$ # шифровать только значения
    age: age1abc... # публичный ключ из шага 1
```

Шифрование файла с секретом и коммит в Git:

```bash
sops --encrypt --in-place apps/prod/db-password.enc.yaml
git add apps/prod/db-password.enc.yaml && git commit -m "add encrypted secret"
```

Подключение расшифровки — поле `decryption` в `Kustomization` (пример в разделе «Безопасность» выше). Проверка результата:

```bash
# После реконсиляции в кластере появится расшифрованный Secret
kubectl get secret db-password -n apps -o jsonpath='{.data.password}' | base64 -d
# -> <исходное значение секрета>
```

Приватный ключ существует только в кластере; в Git лежит исключительно шифротекст — утечка репозитория не раскрывает секреты. Ротация ключа: создать новый Secret, перекодировать файлы `sops --rotate-roles`.

### Сценарий 10: Обновление Flux и миграция устаревших API

Порядок обновления до новой минорной версии (пример: до v2.9.4):

```bash
# 1. Проверить текущую версию
flux --version

# 2. Обновить компоненты в кластере (для bootstrap-установок)
flux bootstrap github \
  --owner=my-org \
  --repository=fleet-infra \
  --branch=main \
  --path=./clusters/prod \
  --version=v2.9.4
# -> компоненты и CRD будут обновлены, новые манифесты закоммичены в репозиторий

# 3. Мигрировать манифесты с устаревшими apiVersion (v2.9 удалил EOL API)
flux migrate
# -> переписывает apiVersion в YAML-файлах репозитория и переводит
#    объекты кластера на стабильные версии API

# 4. Проверить здоровье после обновления
flux check && flux get kustomizations --namespace flux-system
```

Рекомендации:
- Перед обновлением прочитайте release notes целевой версии — начиная с v2.7 действует специальная процедура миграции (Upgrade Procedure for Flux v2.7+), отдельные шаги требуются при пропуске версий.
- Обновляйте сначала dev/staging-кластер; убедитесь, что `flux check` и все `Ready=True`.
- Если Flux управляется Flux Operator, версия задается в спецификации `FluxInstance` — обновление сводится к изменению поля в Git.

### Сценарий 11: Восстановление кластера после аварии (Disaster Recovery)

Фундаментальное преимущество GitOps: желаемое состояние кластера хранится вне кластера. Восстановление сводится к bootstrap нового кластера и реконсиляции из того же репозитория. Что Git **не** восстанавливает: данные PVC/БД (отдельная стратегия бэкапов), DNS и балансировщики, а также секреты, живущие только в кластере.

Что должно быть сохранено ЗАРАНЕЕ (вне Git):

| Артефакт | Где хранить резервную копию |
| :--- | :--- |
| Приватный ключ age для SOPS (`sops-age`) | KMS/Vault/менеджер секретов |
| Deploy key fleet-репозитория | Там же (или перевыпустить при bootstrap) |
| Мастер-ключ Sealed Secrets | Обязательно: без него зашифрованные Secret'ы не расшифровать никогда |
| Учетные данные ESO/Vault | Конфигурация внешнего хранилища |

Порядок восстановления:

```bash
# 1. Развернуть новый кластер средствами IaC и проверить доступ
kubectl get nodes
# → STATUS Ready по всем узлам

# 2. Восстановить pre-bootstrap секреты (до первой реконсиляции!)
kubectl create secret generic sops-age -n flux-system \
  --from-file=age.agekey=/secure-backup/keys.txt
# → secret/sops-age created

# 3. Повторить bootstrap с теми же параметрами — он идемпотентен:
#    на пустом кластере установит компоненты, на частично живом — приведет их к нужной версии
flux bootstrap github \
  --owner=my-org \
  --repository=fleet-infra \
  --branch=main \
  --path=./clusters/prod \
  --components-extra=image-reflector-controller,image-automation-controller
# ► component source-controller deployed
# ► kustomization flux-system reconciled

# 4. Наблюдать за волной восстановления: сначала sources, затем kustomizations/helmreleases
flux get all --status-selector ready=False
# → пустой вывод = все объекты Ready

# 5. Проверить здоровье приложений и восстановить данные stateful-сервисов из бэкапов
kubectl get pods -A | grep -v Running | grep -v Completed
```

Если Flux сам поврежден (контроллеры в CrashLoop, CRD удалены частично) — мягкий сброс без удаления рабочих нагрузок:

```bash
# Удалить ТОЛЬКО контроллеры и объекты flux-system; приложения остаются в кластере
flux uninstall --namespace=flux-system --keep-namespace
# затем повторный bootstrap (шаг 3)
```

После крупной аварии учтите особенности: инвентарь prune пуст — `prune: true` не будет удалять «осиротевшие» ресурсы, которых нет в инвентаре (безопасно, но возможен мусор — проверьте вручную); историю ревизий HelmRelease можно восстановить командой `flux reconcile helmrelease <name>`, чтобы вернуть возможность отката.

Проверка готовности к аварии — регулярная тренировка: полный rebuild тестового кластера из fleet-репозитория раз в квартал; тег коммита, из которого кластер был успешно восстановлен, фиксирует проверенную точку.

### Очистка окружения

Полное удаление Flux из кластера:

```bash
# Удалить контроллеры, объекты flux-system и (опционально) CRD
flux uninstall --namespace=flux-system --crds
# ► uninstalling flux
# ► deleting GitRepository flux-system
# ► deleting Kustomization flux-system
# ✔ uninstall finished
```

Важно понимать границы очистки:
- Приложения, развернутые через Flux, **остаются в кластере** — `uninstall` не удаляет рабочие нагрузки (это осознанный дизайн: доставка и жизненный цикл приложений независимы от инструмента).
- Deploy key и webhook останутся в настройках Git-репозитория — удалите их вручную.
- Зашифрованные Secret'ы ключей (например, `sops-age`) удаляются вместе с namespace; при необходимости переустановки их придется создать заново.

## Вопросы для собеседования

### Из каких контроллеров состоит Flux и за что каждый отвечает?
**source-controller** — забор артефактов (GitRepository/OCIRepository/Bucket/HelmRepository); **kustomize-controller** — применение Kustomization (включая расшифровку SOPS и impersonation SA); **helm-controller** — HelmRelease с установкой, апгрейдом и откатом; **notification-controller** — события наружу (Provider/Alert) и webhook'и внутрь (Receiver); опционально image-reflector/image-automation-controller — автоматизация версий образов.

### Чем модель Flux отличается от Argo CD при потере связи с Git?
Каждый кластер тянет конфигурацию сам (pull-per-cluster): при недоступности Git кластер продолжает работать на последней успешной ревизии, реконсиляция дрейфа продолжается локально. Восстановление произойдет автоматически после возвращения Git — вмешательства не требуется.

### Что делает `flux suspend` и почему это опасно надолго?
Приостанавливает реконсиляцию объекта: не применяются новые коммиты И не корректируется дрейф — ручные правки в кластере сохранятся. Накопленные suspended-объекты — скрытый отказ GitOps: аудитировать через `flux get all --status-selector ready=False`.

### Как во Flux устроена мультитенантность?
Impersonation: каждая Kustomization/HelmRelease выполняется от имени назначенного ServiceAccount (`spec.serviceAccountName`) с минимальным RBAC; контроллер откажет, если SA вне namespace владельца. Дополняется ограничением `spec.decryption` и запретом cross-namespace ссылок.

### Зачем нужен OCIRepository, если есть Git?
Единый транспорт для всех артефактов: digest-неизменяемость (откат гарантированно к тому же содержимому), подписи Cosign, скорость без клонирования репозитория, зеркалирование для air-gapped. Git остается местом совместной работы людей; OCI — каналом доставки («gitless GitOps»).

## Дополнительная информация

**Связанные документы:**
- [Сравнение с ArgoCD](./argo_vs_flux_manifests.md) — детальное сравнение архитектур и манифестов.
- [Организация Flux CD monorepo: кейс](./Concepts/flux_monorepo_organization.md) — миграция с v1 на v2, структура `clusters/` + `components/`, конвенции именования.
- [Управление секретами](./secrets_encryption.md) — шифрование через SOPS и Sealed Secrets.
- [GitOps: Уведомления](./gitops_notifications.md) — настройка оповещений и алертинга (Provider/Alert/Receiver во Flux).

**Внешние ресурсы:**
- [Официальная документация Flux](https://fluxcd.io/flux/) — guides, справочник API и CLI.
- [Announcing Flux 2.9 GA](https://fluxcd.io/blog/2026/06/flux-v2.9.0/) — подробности релиза v2.9.
- [Релизы fluxcd/flux2](https://github.com/fluxcd/flux2/releases) — changelog всех версий и патчей.
