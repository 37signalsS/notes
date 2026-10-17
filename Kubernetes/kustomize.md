# Kustomize: основы и лучшие практики для множественных окружений

**Актуально для:** Kustomize v5.4.x / Flux CD v2.3.x / Kubernetes 1.28–1.31

## Определения

- **Kustomize** — нативный инструмент декларативной кастомизации манифестов Kubernetes без использования шаблонизации, настраивающий объекты через иерархические слои (overlays), компоненты (components) и патчи (patches).
- **kustomization.yaml** — основной конфигурационный файл (`apiVersion: kustomize.config.k8s.io/v1beta1`, `kind: Kustomization`), декларирующий включаемые ресурсы, генераторы, модификаторы метаданных и патчи для конкретного слоя.
- **Base (Базовый слой)** — каталог с манифестами, содержащий эталонные конфигурации, одинаковые для всех сред развертывания.
- **Overlay (Слой наложения)** — каталог с файлом `kustomization.yaml`, который ссылается на `base` (или другие оверлеи) и накладывает специфичные для окружения изменения (патчи, селекторы, переменные).
- **Custom (Слой опциональных компонентов)** — каталог модульных сервисов или аддонов (например, базы данных, очереди, стеки мониторинга), подключаемых к окружениям по принципу конструктора.
- **Component (Компонент Kustomize)** — переиспользуемый модуль (`apiVersion: kustomize.config.k8s.io/v1alpha1`, `kind: Component`), инкапсулирующий ресурсы и патчи для горизонтального подмешивания функциональности (например, включение TLS, аутентификации или debug-режима) без создания промежуточных оверлеев.
- **Patch (Патч)** — файл или встроенная инструкция, описывающая изменения (дельты), применяемые к целевым объектам.
- **Strategic Merge Patch** — метод слияния YAML-манифестов на основе схемы Kubernetes OpenAPI, позволяющий обновлять и добавлять поля без перезаписи неизмененных атрибутов.
- **JSON 6902 Patch** — стандарт точечной модификации структуры (RFC 6902), использующий операции `add`, `remove`, `replace` по точным путям JSON Pointer; критически важен для модификации нетипизированных полей (`values` в CRD).
- **HelmRelease** — пользовательский ресурс (CRD `helm.toolkit.fluxcd.io/v2`) оператора Flux CD Helm Controller, обеспечивающий декларативное управление жизненным циклом Helm-релизов в рамках GitOps.

## Архитектура и принципы работы

### DRY-архитектура управления конфигурациями

Главный вызов при эксплуатации нескольких Kubernetes-кластеров и сред (Dev, Staging, SRE/Prod) — устранение дублирования конфигураций (принцип DRY — Don't Repeat Yourself). Изменение глобального параметра (например, версии Helm-чарта, глобального тайм-аута или базового probe) должно выполняться ровно в одном месте.

```text
                               ┌───────────────────────────┐
                               │   Уровень 1: base/        │
                               │   (общие HelmRelease,     │
                               │    версии, baseline probe)│
                               └─────────────┬─────────────┘
                                             │
                               ┌─────────────┴─────────────┐
                               │   Уровень 2: custom/      │
                               │   (опциональные сервисы:  │
                               │    db, elk, queue, infra) │
                               └─────────────┬─────────────┘
                                             │
                 ┌───────────────────────────┼───────────────────────────┐
                 │                           │                           │
                 v                           v                           v
  ┌─────────────────────────────┐ ┌─────────────────────────────┐ ┌─────────────────────────────┐
  │ Уровень 3: projects/dev/    │ │ Уровень 3: projects/test/   │ │ Уровень 3: projects/sre/    │
  │ • StorageClass: local-path  │ │ • StorageClass: nfs-client  │ │ • StorageClass: ceph-rbd    │
  │ • Min replicas (1)          │ │ • Middle replicas (2)       │ │ • HA replicas (3), limits   │
  │ • dev-kubeconfig            │ │ • test-kubeconfig           │ │ • prod-kubeconfig           │
  └─────────────────────────────┘ └─────────────────────────────┘ └─────────────────────────────┘
```

Иерархия разделения ответственности:

1. **Уровень 1: `base/`**
   - Содержит манифесты `HelmRelease` и общие объекты со значениями, идентичными для всех окружений.
   - Здесь фиксируются: версия Helm-чарта, источник `HelmRepository`, базовые интервалы сверки, общие флаги (`grafana.enabled: false` для spoke-кластеров), базовые метрики и probes.
   - Обновление версии в `base/` мгновенно каскадируется на все среды.

2. **Уровень 2: `custom/` (или `components/`)**
   - Содержит опциональные компоненты, сгруппированные по категориям (например, `db/`, `elk/`, `monitoring/`, `queue/`, `web/`).
   - Каждый каталог содержит собственный `kustomization.yaml`, подключающий ресурсы внутри категории (например, `custom/db/kustomization.yaml` агрегирует `redis/`, `postgresql/`).
   - Позволяет подключать или отключать функциональные блоки для конкретных кластеров без копирования манифестов.

3. **Уровень 3: `projects/{env}/hub/` (или `environments/{env}/`)**
   - Оверлей конкретного окружения (`dev`, `test`, `sre`), выполняющий:
     - Подключение базовых ресурсов из `base/` и выбранных компонентов из `custom/` через директиву `resources:`.
     - Наложение точечных патчей (`patches:`), содержащих исключительно дельты параметров окружения: класс хранилища (`storageClass`), лимиты памяти/CPU, количество реплик, профили сетевой изоляции.
     - Установку пространства имен на уровне всего оверлея (`namespace: dev`), автоматически транслируемую во все дочерние ресурсы без хардкода в каждом отдельном файле.
     - Инъекцию контекстных секретов (например, `kubeConfig` для взаимодействия Hub-кластера со Spoke-кластерами).

### Механизм патчинга в Kustomize v5+

В современном Kustomize устаревшие поля `bases:`, `patchesStrategicMerge:` и `patchesJson6902:` объединены в универсальный блок `patches:`.

| Метод | Механизм применения | Когда применять |
| :--- | :--- | :--- |
| **Strategic Merge** | Слияние по именованным ключам схемы K8s OpenAPI | Изменение стандартных полей K8s (`replicas`, `resources`, `env`, `nodeSelector`). |
| **JSON 6902 Patch** | Адресация по RFC 6902 путям (`add`, `remove`, `replace`) | Модификация `values` внутри CRD `HelmRelease`, удаление секций, массовая инъекция блоков через селектор. |
| **$patch директивы** | Директивы `$patch: delete` и `$patch: replace` в Strategic Merge | Полная замена списков или удаление контейнеров/томов в стандартных подах. |

> [!IMPORTANT]
> Манифесты CRD (включая `HelmRelease` от Flux CD) содержат секцию `spec.values`, которая с точки зрения OpenAPI K8s является нетипизированным объектом (`type: object`, `x-kubernetes-preserve-unknown-fields: true`). Для `spec.values` Strategic Merge Patch не может вычислить ключи слияния списков! Поэтому для удаления или точечной модификации списков внутри `values` необходимо применять **JSON 6902 patch**.

## Практические сценарии и конфигурация

### Базовая структура каталогов репозитория

```text
fluxcd/
├── base/
│   └── monitoring/
│       └── kube-prom-stack/
│           ├── helmrelease.yaml        # Базовый релиз со стабильными values
│           └── kustomization.yaml      # Регистрация ресурса base
├── custom/
│   ├── db/
│   │   ├── redis/
│   │   │   └── helmrelease.yaml
│   │   └── kustomization.yaml          # Экспорт сервисов баз данных
│   ├── elk/
│   │   ├── elasticsearch/
│   │   │   └── helmrelease.yaml
│   │   └── kustomization.yaml
│   └── monitoring/
│       └── kustomization.yaml
└── projects/
    ├── dev/
    │   └── kustomization/
    │       └── hub/
    │           ├── kustomization.yaml  # Точка входа для dev-окружения
    │           └── patches/
    │               ├── elasticsearch.yaml
    │               ├── kube-prom-stack.yaml
    │               └── redis.yaml
    ├── test/
    │   └── kustomization/
    │       └── hub/
    │           ├── kustomization.yaml
    │           └── patches/
    │               └── elasticsearch.yaml
    └── sre/
        └── kustomization/
            └── hub/
                ├── kustomization.yaml
                └── patches/
                    ├── elasticsearch.yaml
                    └── kube-prom-stack.yaml
```

### Базовый манифест HelmRelease (base/)

Файл `fluxcd/base/monitoring/kube-prom-stack/helmrelease.yaml`:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: kube-prom-stack
spec:
  interval: 30m
  timeout: 15m
  chart:
    spec:
      chart: kube-prometheus-stack
      version: "70.3.0"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
  install:
    remediation:
      retries: 3
  upgrade:
    remediation:
      retries: 3
  values:
    grafana:
      enabled: false       # Grafana централизована на Hub-кластере
    defaultRules:
      create: true
    kubeScheduler:
      enabled: false
    kubeProxy:
      enabled: false
    prometheus:
      prometheusSpec:
        retention: 7d
        storageSpec:
          volumeClaimTemplate:
            spec:
              resources:
                requests:
                  storage: 50Gi
```

Файл `fluxcd/base/monitoring/kube-prom-stack/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - helmrelease.yaml
```

### Патч для Dev-окружения (On-Prem, local-path storage)

Файл `fluxcd/projects/dev/kustomization/hub/patches/elasticsearch.yaml`:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: elasticsearch
  namespace: dev
spec:
  values:
    replicas: 1
    master:
      persistence:
        storageClass: local-path
        size: 20Gi
      resources:
        requests:
          cpu: 500m
          memory: 2Gi
        limits:
          cpu: 1000m
          memory: 2Gi
    esConfig:
      elasticsearch.yml: |
        xpack.security.enabled: true
    esJavaOpts: "-Xmx1g -Xms1g"
```

### Патч для SRE/Production-окружения (On-Prem, Ceph RBD / Высокая доступность)

Файл `fluxcd/projects/sre/kustomization/hub/patches/elasticsearch.yaml`:

```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: elasticsearch
  namespace: sre
spec:
  values:
    replicas: 3
    master:
      persistence:
        storageClass: ceph-rbd
        size: 200Gi
      resources:
        requests:
          cpu: 2000m
          memory: 8Gi
        limits:
          cpu: 4000m
          memory: 8Gi
    esConfig:
      elasticsearch.yml: |
        xpack.security.enabled: true
    esJavaOpts: "-Xmx4g -Xms4g"
```

### Итоговый Hub kustomization.yaml (Dev-окружение)

Файл `fluxcd/projects/dev/kustomization/hub/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: dev

resources:
  - ../../../../base/monitoring/kube-prom-stack
  - ../../../../custom/db
  - ../../../../custom/elk
  - spoke-sync.yaml

patches:
  # Стратегические патчи для отдельных сервисов
  - path: patches/elasticsearch.yaml
    target:
      group: helm.toolkit.fluxcd.io
      version: v2
      kind: HelmRelease
      name: elasticsearch
  - path: patches/kube-prom-stack.yaml
    target:
      group: helm.toolkit.fluxcd.io
      version: v2
      kind: HelmRelease
      name: kube-prom-stack

  # Массовая инъекция через JSON 6902 Patch: добавление kubeConfig во ВСЕ HelmRelease
  - target:
      group: helm.toolkit.fluxcd.io
      version: v2
      kind: HelmRelease
    patch: |-
      - op: add
        path: /spec/kubeConfig
        value:
          secretRef:
            name: dev-cluster-kubeconfig

# Безопасное добавление меток без мутации matchLabels селекторов
labels:
  - pairs:
      env: dev
      managed-by: flux-kustomize
    includeSelectors: false
```

### Сценарий использования Kustomize Components

Когда необходимо добавить опциональный функционал (например, `node-exporter` host-root доступ или корпоративный TLS Sidecar), используются компоненты Kustomize.

Пример компонента `fluxcd/custom/components/tls-sidecar/kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component
patches:
  - target:
      kind: Deployment
      labelSelector: "app.kubernetes.io/part-of=web"
    patch: |-
      apiVersion: apps/v1
      kind: Deployment
      metadata:
        name: not-used
      spec:
        template:
          spec:
            containers:
              - name: tls-proxy
                image: envoyproxy/envoy:v1.30.0
                volumeMounts:
                  - name: certs
                    mountPath: /etc/ssl/certs
                    readOnly: true
            volumes:
              - name: certs
                secret:
                  secretName: onprem-corp-cert
```

Подключение компонента в оверлее:

```yaml
components:
  - ../../../../custom/components/tls-sidecar
```

## Операции и команды

### Локальная проверка и валидация манифестов

Сборка оверлея и проверка результирующего манифеста:

```bash
kubectl kustomize fluxcd/projects/dev/kustomization/hub/
# → apiVersion: helm.toolkit.fluxcd.io/v2
# → kind: HelmRelease
# → metadata:
# →   name: kube-prom-stack
# →   namespace: dev
# → ...
```

Проверка применения JSON-патча (наличие добавленного `kubeConfig` во всех релизах):

```bash
kubectl kustomize fluxcd/projects/dev/kustomization/hub/ | grep -A 4 "kubeConfig:"
# →     kubeConfig:
# →       secretRef:
# →         name: dev-cluster-kubeconfig
# → --
# →     kubeConfig:
# →       secretRef:
# →         name: dev-cluster-kubeconfig
```

Выборочный просмотр `spec.values` конкретного сервиса с помощью `yq`:

```bash
kubectl kustomize fluxcd/projects/dev/kustomization/hub/ | \
  yq '. | select(.metadata.name == "elasticsearch") | .spec.values.master.persistence'
# → storageClass: local-path
# → size: 20Gi
```

Сравнение сгенерированных манифестов между двумя окружениями:

```bash
diff -u \
  <(kubectl kustomize fluxcd/projects/dev/kustomization/hub/) \
  <(kubectl kustomize fluxcd/projects/sre/kustomization/hub/) | head -n 25
# → --- /dev/fd/63
# → +++ /dev/fd/62
# → @@ -8,7 +8,7 @@
# → -  namespace: dev
# → +  namespace: sre
# → @@ -45,7 +45,7 @@
# → -        storageClass: local-path
# → +        storageClass: ceph-rbd
```

### Сборка через автономный бинарный файл kustomize

Если оверлеи ссылаются на каталоги выше корня запуска, используется флаг снятия ограничений загрузки:

```bash
kustomize build fluxcd/projects/dev/kustomization/hub/ --load-restrictor LoadRestrictionsNone > /dev/null
# → (код возврата 0 при успешной компиляции)
```

### Dry-Run валидация в кластере Kubernetes

```bash
kubectl apply -k fluxcd/projects/dev/kustomization/hub/ --dry-run=client
# → helmrelease.helm.toolkit.fluxcd.io/kube-prom-stack configured (dry run)
# → helmrelease.helm.toolkit.fluxcd.io/elasticsearch configured (dry run)
# → helmrelease.helm.toolkit.fluxcd.io/redis configured (dry run)
```

### Валидация в GitLab CI / Автоматизация

Пример этапа валидации в конвейере CI/CD (`.gitlab-ci.yml`):

```yaml
kustomize-validate:
  stage: validate
  image: bitnami/kubectl:1.31.1
  before_script:
    - kubectl version --client=true
  script:
    - set -euo pipefail
    - |
      for env in dev test sre; do
        echo "=== [CHECK] Валидация оверлея: ${env} ==="
        kubectl kustomize "fluxcd/projects/${env}/kustomization/hub/" > /tmp/manifest.yaml
        if [ ! -s /tmp/manifest.yaml ]; then
          echo "ERROR: Пустой манифест для ${env}" >&2
          exit 1
        fi
        echo "OK: Оверлей ${env} успешно собран ($(wc -l < /tmp/manifest.yaml) строк)"
      done
```

## Устранение неполадок

### 1. Ошибка load-restrictor при локальной сборке

- **Симптом:**
  ```text
  Error: accumulating resources: accumulation err='merging resources from ...':
  security; file is not in or below current working directory
  ```
- **Причина:** Kustomize по умолчанию блокирует выход за пределы корневой папки сборки (`LoadRestrictionsRootOnly`) при использовании относительных путей `../../..`.
- **Диагностика:** Проверьте относительный путь в `resources:` манифеста `kustomization.yaml`.
- **Решение:**
  - При вызове бинарного `kustomize` передайте флаг:
    ```bash
    kustomize build <overlay-dir> --load-restrictor LoadRestrictionsNone
    ```
  - В настройках Argo CD repo-server укажите параметр:
    `kustomize.buildOptions: "--load-restrictor LoadRestrictionsNone"` в ConfigMap `argocd-cm`.
  - Убедитесь, что пути ссылаются на каталоги с `kustomization.yaml`, а не на одиночные манифесты за пределами корня.

### 2. Strategic Merge Patch не удаляет параметры из HelmRelease

- **Симптом:** При попытке занулить ключ (например, убрать `resources.limits` или отключить блок) через Strategic Merge старые значения из `base/` остаются в манифесте.
- **Причина:** Поля `spec.values` внутри CRD `HelmRelease` не имеют типизированной схемы слияния K8s OpenAPI. Стратегическое слияние выполняет глубокий merge словарей, но не может удалить существующие ключи.
- **Диагностика:**
  ```bash
  kubectl kustomize <overlay> | yq '.spec.values'
  ```
- **Решение:** Использовать JSON 6902 Patch с операцией `remove`:
  ```yaml
  patches:
    - target:
        group: helm.toolkit.fluxcd.io
        version: v2
        kind: HelmRelease
        name: elasticsearch
      patch: |-
        - op: remove
          path: /spec/values/master/resources/limits
  ```

### 3. Ошибка мутации matchLabels селекторов (Immutable Field)

- **Симптом:** При деплое в кластер возникает ошибка:
  ```text
  The Deployment "app" is invalid: spec.selector: Invalid value: field is immutable
  ```
- **Причина:** Использование директивы `commonLabels:` в `kustomization.yaml` приводит к тому, что Kustomize принудительно изменяет поле `spec.selector.matchLabels` в Deployment/StatefulSet. В Kubernetes изменение селектора подов для существующих контроллеров запрещено.
- **Диагностика:** Проверьте `diff` манифеста Deployment на наличие измененных `matchLabels`.
- **Решение:** В Kustomize v5+ используйте директиву `labels` с отключением мутации селекторов:
  ```yaml
  labels:
    - pairs:
        environment: dev
      includeSelectors: false
  ```

### 4. Непримененный патч из-за несовпадения Namespace или API-группы

- **Симптом:** Сборка завершается успешно, но изменения из файла патча не появляются в целевом манифесте.
- **Причина:** Если в `target` патча указан `namespace: dev`, но базовый ресурс в `base/` определен без `namespace` (или наоборот), Kustomize не считает их идентичными объектами до фазы присвоения общего namespace.
- **Диагностика:** Проверьте точные метаданные в базовом файле:
  ```bash
  grep -E "(kind|name|namespace):" fluxcd/base/monitoring/kube-prom-stack/helmrelease.yaml
  ```
- **Решение:** В блоке `target` патча опускайте поле `namespace`, если селекция однозначно выполняется по имени (`name`) и типу (`kind`), либо синхронизируйте его декларацию.

## Лучшие практики

1. **Абсолютная чистота `base/`:**
   - В `base/` помещаются только 100% общие параметры. Если параметр варьируется хотя бы в одном окружении (например, реплики или StorageClass), он должен выноситься в патч оверлея или компонент.
2. **Дельты вместо дублирования:**
   - Патч должен содержать только изменяемые поля. Никогда не копируйте весь `values.yaml` чарта в патч оверлея — это обесценивает DRY и приводит к рассинхронизации версий.
3. **Разделение типов патчей:**
   - Используйте Strategic Merge для лаконичной модификации стандартных манифестов Kubernetes.
   - Используйте JSON 6902 Patch для работы со `spec.values` внутри CRD `HelmRelease`, `PrometheusRule` и других кастомных ресурсов.
4. **Безопасная работа с метаданными:**
   - Откажитесь от устаревшей директивы `commonLabels:` в пользу `labels` с `includeSelectors: false`, чтобы избежать падений подов из-за иммутабельности селекторов.
5. **Изоляция секретов в GitOps:**
   - Конфиденциальные параметры (пароли БД, токен доступа к spoke-кластерам) не должны храниться в открытом виде в патчах. Используйте интеграцию с SealedSecrets, SOPS или External Secrets Operator.
6. **Обязательная валидация в CI:**
   - Каждый коммит, затрагивающий директории `base/`, `custom/` или `projects/`, должен проходить automated `kubectl kustomize` проверку всех оверлеев в конвейере GitLab CI перед слиянием.
7. **Алгоритм добавления нового окружения:**
   1. Создать каталог `projects/<new-env>/kustomization/hub/` копированием эталонного оверлея.
   2. Обновить значение `namespace: <new-env>` в файле `kustomization.yaml`.
   3. Скорректировать имя секрета доступа к целевому кластеру в JSON-патче `kubeConfig`.
   4. Настроить патчи хранилищ под доступные локальные классы (например, `local-path` для стендов разработчиков, `ceph-rbd` для отказоустойчивых кластеров).
   5. Добавить манифест SealedSecret для `kubeconfig` целевого кластера.
   6. Выполнить локальную сборку `kubectl kustomize` и закоммитить изменения.

## Дополнительная информация

### Внутренние ссылки базы знаний
- [Kustomize — Обзор и основные концепции](./ToolsUtilities/kustomize/kustomize_overview.md)
- [Kustomize — Наложения и патчи (Overlays and Patches)](./ToolsUtilities/kustomize/kustomize_overlays_and_patches.md)
- [Kustomize — Multi-cluster и multi-tenancy паттерны](./ToolsUtilities/kustomize/kustomize_multi_cluster.md)
- [Kustomize — Структура проекта и синтаксис](./ToolsUtilities/kustomize/kustomize_structure_and_syntax.md)
- [Kustomize — Отладка и диагностика](./ToolsUtilities/kustomize/kustomize_debugging.md)
- [GitOps с использованием Flux CD](../GitOps/flux.md)
- [Интеграция Kustomize в Argo CD](../GitOps/ArgoCD/kustomize_integration.md)
- [Local-path-provisioner в Kubernetes](../Kubernetes/Storage/local-path-provisioner.md)

### Официальные источники
- [Официальная документация Kustomize (SIG CLI)](https://kubernetes-sigs.github.io/kustomize/)
- [Спецификация Flux CD HelmRelease](https://fluxcd.io/flux/components/helm/helmrelease/)
- [RFC 6902: JavaScript Object Notation (JSON) Patch](https://datatracker.ietf.org/doc/html/rfc6902)