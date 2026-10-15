# Kustomize: основы и лучшие практики для множественных окружений

## Определения
- Kustomize — инструмент для настройки Kubernetes объектов через слои overlays и патчи.
- HelmRelease — пользовательский ресурс определния (CRD) от Flux CD, позволяющий управлять Helm чартами как Kubernetes объектами.
- Overlay — директория, содержащая kustomization.yaml, которая определяет, какие базовые ресурсы включены и какие патци применены.
- Base — директория с манифестами, общими для всех сред развертывания.
- Custom — директория с опциональными компонентами, используемыми не во всех средах.
- Patch — файл с изменениями (делтами), применяемыми к ресурсам из base/ или custom/.
- Strategic merge patch — формат патча, который объединяет указанные поля с базовым ресурсом, оставляя остальные поля без изменений.
- JSON patch — формат патча, использующий операции add, remove, replace по JSON-pointer путям для модификации ресурсов.
- kustomization.yaml — конфигурационный файл Kustomize, указывающий ресурсы, патци, преобразования и другие параметры.

## Основные концепции и архитектура
Трехуровневая структура Kustomize для достижения DRY принципа в управлении Helm values across multiple environments:

1. **Уровень 1: base/**
   - Содержит HelmRelease объекты с значениями, идентичными для всех окружений.
   - Пример: версия чарта, ресурсные запросы/лимиты, настройки probe, параметры serviceMonitor, конфигурация TLS, feature flags.
   - Изменение значения в base/ (например, версия чарта) автоматически применяется ко всем окружениям.

2. **Уровень 2: custom/**
   - Содержит опциональные компоненты, структурированные по поддиректориям (например, apps/, db/, elk/, monitoring/, queue/, web/).
   - Каждая поддиректория имеет собственный kustomization.yaml, перечисляющий включенные компоненты (например, custom/db/kustomization.yaml список redis/, mongodb/, etc.).
   - Позволяет включать/исключать целые наборы компонентов для разных окружений без дублирования конфигурации.

3. **Уровень 3: projects/{env}/hub/**
   - Overlay для конкретного окружения {env}, который:
     * Ссылается на директории base/ и выбранные custom/ компоненты через resources в kustomization.yaml.
     * Применяет дельта-патчи (patches/), содержащие только отличия между окружениями (например, StorageClass, количество реплик, ресурсные лимиты, учетные данные, имена хостов).
     * Устанавливает namespace на уровне overlay (поле namespace в kustomization.yaml), что размещает все HelmRelease в namespace окружения без необходимости указывать namespace в каждом HelmRelease файле.
   - Пример: projects/dev/kustomization/hub/ для окружения dev, projects/sre/kustomization/hub/ для sre и т.д.

Ключевой принцип: патци содержат только дельты и никогда не дублируют значения из base/. Это обеспечивает, что обновление общей конфигурации (например, версии чарта) требует изменения только одного файла в base/.

## Практическая установка и настройка
Пример структуры репозитория:
```
fluxcd/
├── base/
│   └── monitoring/
│       └── kube-prom-stack/
│           └── helmrelease.yaml   # Общие значения для kube-prometheus-stack
├── custom/
│   ├── db/
│   │   └── kustomization.yaml     # Список компонентов баз данных
│   ├── elk/
│   │   └── kustomization.yaml
│   ├── monitoring/
│   │   └── kustomization.yaml
│   ├── queue/
│   │   └── kustomization.yaml
│   └── web/
│       └── kustomization.yaml
└── projects/
    ├── dev/
    │   └── kustomization/
    │       └── hub/
    │           ├── kustomization.yaml   # Hub overlay для dev
    │           └── patches/
    │               ├── elasticsearch.yaml
    │               ├── kube-prom-stack.yaml
    │               └── redis.yaml
    ├── test/
    │   └── ... (аналогично dev)
    ├── sre/
    │   └── kustomization/
    │       └── hub/
    │           ├── kustomization.yaml
    │           └── patches/
    │               ├── elasticsearch.yaml  # С другим StorageClass и ресурсами
    │               └── ...
    ├── loadgds/
    │   └── ...
    └── demo/
        └── ...
```

Пример базового HelmRelease в base/monitoring/kube-prom-stack/helmrelease.yaml:
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
      version: "85.2.0"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
        namespace: flux-system
  values:
    grafana:
      enabled: false      # Grafana размещается только на инфраструктурном хабе, не на spoke
    defaultRules:
      create: false
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
                  storage: 20Gi
```

Пример патца для Elasticsearch в окружении dev (on-prem, local-path storage):
```yaml
# projects/dev/kustomization/hub/patches/elasticsearch.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: elasticsearch
  namespace: dev
spec:
  values:
    master:
      persistence:
        storageClass: local-path
    esConfig:
      elasticsearch.yml: |
        xpack.security.enabled: true
    esJavaOpts: "-Xmx2g -Xms2g"
```

Пример патца для Elasticsearch в окружении sre (Yandex Cloud, сетевой SSD):
```yaml
# projects/sre/kustomization/hub/patches/elasticsearch.yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: elasticsearch
  namespace: sre
spec:
  values:
    master:
      persistence:
        storageClass: yc-network-ssd
      resources:
        requests:
          memory: 8Gi
          cpu: 2
    esJavaOpts: "-Xmx6g -Xms6g"
    replicas: 3
```

Пример hub kustomization.yaml для окружения dev:
```yaml
# projects/dev/kustomization/hub/kustomization.yaml
namespace: dev
resources:
  - ../../../../base/
  - ../../../../custom/db/
  - ../../../../custom/elk/
  - ../../../../custom/monitoring/
  - spoke.yaml        # Flux Kustomization для spoke-слоя
  - monitoring.yaml   # Flux Kustomization для monitoring-слоя

patches:
  - path: patches/elasticsearch.yaml
  - path: patches/kube-prom-stack.yaml
  - path: patches/redis.yaml
  # Добавление kubeConfig во ВСЕ HelmRelease через JSON patch
  - target:
      kind: HelmRelease
    patch: |-
      - op: add
        path: /spec/kubeConfig
        value:
          secretRef:
            name: dev-kubeconfig
```

Примечание: Поле `namespace: dev` в верхней части устанавливает namespace для всех ресурсов в этом оверлее, если у них нет собственного namespace. Это позволяет всем HelmRelease оказываться в namespace `dev` на hub без повторения `namespace: dev` в каждом файле.

## Операции и команды
Локальная валидация конфигурации перед коммитом:
- Проверка полного hub оверлея:
  ```bash
  kubectl kustomize fluxcd/projects/dev/kustomization/hub/
  ```
- Проверка наличия добавленного kubeConfig во всех HelmRelease:
  ```bash
  kubectl kustomize fluxcd/projects/dev/kustomization/hub/ | grep -A 5 "kubeConfig"
  ```
- Проверка values конкретного чарта после применения патци:
  ```bash
  kubectl kustomize fluxcd/projects/dev/kustomization/hub/ | \
    yq '. | select(.metadata.name == "elasticsearch") | .spec.values'
  ```
- Сравнение конфигураций двух окружений для выявления различий:
  ```bash
  diff \
    <(kubectl kustomize fluxcd/projects/dev/kustomization/hub/) \
    <(kubectl kustomize fluxcd/projects/test/kustomization/hub/)
  ```

Пример шага в GitLab CI для автоматической валидации:
```yaml
kustomize-validate:
  stage: validate
  image: bitnami/kubectl:latest
  script:
    - for env in dev test sre loadgds demo; do
        echo "Validating $env...";
        kubectl kustomize fluxcd/projects/${env}/kustomization/hub/ > /dev/null;
      done
```
Выполняется за ~5 секунд и обнаруживает ~90% ошибок в патци до слияния.

## Устранение неполадок
- **Ошибка: ссылка на отдельный файл вместо директории**
  - Симптом: команда `kubectl kustomize` падает с ошибкой load-restrictor при локальной валидации.
  - Причина: в resources указан путь к отдельному файлy (например, `../../../../custom/db/redis/helmrelease.yaml`) вместо директории с kustomization.yaml.
  - Решение: всегда ссылаться на директории, содержащие kustomization.yaml (например, `../../../../custom/db/`).

- **Проблема со strategic merge patch при удалении ключей**
  - Симптом: ключ не удаляется из результирующего ресурса при использовании strategic merge патца.
  - Причина: strategic merge не удаляет ключи без явной директивы `$patch: delete`.
  - Решение: для удаления ключей использовать JSON patch с операцией `op: remove`.

- **Конфликт при применении множественных патци**
  - Симптом: непредсказуемый результат при модификации одного и того же пути разными патци.
  - Причина: порядок применения патци может влиять на результат при конфликтующих изменениях.
  - Решение: обеспечить, чтобы патци модифицировали разные пути, или тщательно протестировать порядок их применения.

## Лучшие практики
- Хранить в директории base/ исключительно те значения и конфигурации, которые являются одинаковыми для всех окружений без исключений.
- Никогда не дублировать значения из base/ в патцих — патци должны содержать только дельты (изменения, специфичные для окружения).
- Использовать strategic merge патци для изменения существующих значений и JSON patch для структурных операций (добавление, удаление, замена полей, которые могут отсутствовать в base/).
- Всегда указывать поле `namespace` в metadata патца, чтобы Kustomize мог точно определить, к какому HelmRelease с данным именем применять патца (особенно важно, когда существует несколько HelmRelease с одинаковым именем в разных namespaces).
- Выполнять локальную валидацию через `kubectl kustomize` для каждого оверлея перед каждым коммитом, затрагивающим патци или kustomization.yaml.
- При добавлении нового окружения:
  1. Скопировать директорию существующего окружения (например, projects/dev/).
  2. Обновить поле `namespace` в kustomization.yaml hub оверлея.
  3. Обновить имя секрета в патце kubeConfig (например, с dev-kubeconfig на newenv-kubeconfig).
  4. Адаптировать значения в патцих под конкретное окружение (StorageClass, имена хостов, ресурсные лимиты, реплики).
  5. Добавить SealedSecret для нового kubeconfig секрета.
  6. Закоммитить изменения и дождаться синхронизации с Flux.
  Весь процесс занимает 20-30 минут и гарантирует, что новое окружение получает идентичные версии чартов и base values как существующие окружения, без ручной установки Helm или копирования values-файлов.

## Дополнительная информация
- Официальная документация Kustomize: https://kubernetes-sigs.github.io/kustomize/
- Документация HelmRelease в Flux CD: https://fluxcd.io/flux/components/helm/helmrelease/
- Примеры и best practices в репозитории Kustomize: https://github.com/kubernetes-sigs/kustomize/tree/master/examples
- Руководство по управлением множественными средами с Kustomize: https://kubetools.io/patterns/kustomize-multiple-environments