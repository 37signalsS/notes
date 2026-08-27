# Crossplane: Composition Functions и EnvironmentConfig

## Определения

**Composition Function** (функция композиции) — это отдельный OCI-пакет (`kind: Function`), который выполняет часть логики композиции. Вместо декларативных `patchSets`/`resources` (Patch & Transform) Composition в режиме `mode: Pipeline` вызывает упорядоченный список функций; вывод каждой функции передаётся следующей, итоговый вывод говорит Crossplane, какие ресурсы создать/обновить/удалить.

**functionConfig (input)** — произвольный встроенный в Composition YAML объект (`spec.pipeline[].input`), передаваемый функции как конфигурация. Поддерживается не всеми функциями.

**EnvironmentConfig** — кластер-скопированный, типизированный ресурс (как ConfigMap), хранящий значения окружения (регион, аккаунт, сетевые настройки, квоты), которые композиция подставляет в генерируемые ресурсы. Загружается в конвейер через `function-environment-configs`.

## Базовые концепции

### Как работает Pipeline
Crossplane наблюдает XR (composite resource) и отправляет его функциям как **observed state**. Каждая функция возвращает **desired state** (какие composed-ресурсы нужны). Функции не создают ресурсы сами — они лишь инструктируют контроллер. Преимущество перед P&T: логика на любом языке (Go, Python, Starlark, KCL, Go-темплейты), условия, циклы, валидация.

### Типы функций (примечательные)
- `function-patch-and-transform` — замена классическому P&T в конвейере.
- `function-environment-configs` — подгружает `EnvironmentConfig` в контекст.
- `function-go-templating` / `function-kcl` / `function-starlark` — генерация ресурсов шаблонами.
- `function-auto-ready` — автоматически выставляет `Ready` XR по готовности composed-ресурсов.
- кастомные функции (Go/Python SDK) — любая бизнес-логика.

### EnvironmentConfig: выбор по имени или селектору
Функция `function-environment-configs` выбирает `EnvironmentConfig` через `type: Reference` (по `ref.name`) или `type: Selector` (по labels, включая значение из поля XR — `FromCompositeFieldPath`). При нескольких конфигах они сливаются в порядке списка.

## Практические сценарии

### 1. Установка функции
```yaml
apiVersion: pkg.crossplane.io/v1
kind: Function
metadata:
  name: function-patch-and-transform
spec:
  package: xpkg.crossplane.io/crossplane-contrib/function-patch-and-transform:v0.8.2
```
> Версии функций проверяйте в реестре (`xpkg.upbound.io` / `xpkg.crossplane.io`) перед установкой.

### 2. Composition в режиме Pipeline (P&T внутри функции)
```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: xbuckets
spec:
  compositeTypeRef:
    apiVersion: example.crossplane.io/v1
    kind: XBucket
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: storage-bucket
            base:
              apiVersion: s3.aws.m.upbound.io/v1beta1
              kind: Bucket
              spec:
                forProvider:
                  region: us-east-2
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.bucketRegion
                toFieldPath: spec.forProvider.region
```

### 3. EnvironmentConfig + подстановка значений окружения
```yaml
# Значения окружения (cluster-scoped)
apiVersion: apiextensions.crossplane.io/v1
kind: EnvironmentConfig
metadata:
  name: production
data:
  region: ru-central1
  networkId: env-prod-net
  quotaCpu: "50"
---
# Composition выбирает EnvironmentConfig и подставляет поля
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: xtenant-apps
spec:
  compositeTypeRef:
    apiVersion: platform.example.com/v1alpha1
    kind: XTenantApp
  mode: Pipeline
  pipeline:
    - step: environment-configs
      functionRef:
        name: function-environment-configs
      input:
        apiVersion: environmentconfigs.fn.crossplane.io/v1beta1
        kind: Input
        spec:
          environmentConfigs:
            - type: Reference
              ref:
                name: production
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: namespace
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              spec:
                forProvider:
                  manifest:
                    apiVersion: v1
                    kind: Namespace
                    metadata:
                      name: app
            patches:
              - type: FromEnvironmentFieldPath   # значение из EnvironmentConfig
                fromFieldPath: region
                toFieldPath: spec.forProvider.manifest.metadata.labels[region]
```

### 4. Локальный рендер без кластера (сдвиг влево)
Команда `crossplane composition render` (в Crossplane ≥1.17 — GA; для старых — `crossplane beta render`) запускает функции локально через Docker и печатает итоговые ресурсы:

```bash
# xr.yaml — композитный ресурс, composition.yaml — Composition, functions.yaml — Function(ы)
crossplane composition render xr.yaml composition.yaml functions.yaml

# подставить реальное состояние (observed) и проверить status XR
crossplane composition render xr.yaml composition.yaml functions.yaml \
  --observed-resources observed --include-full-xr

# проверить, что EnvironmentConfig корректно выбран (контекст пайплайна)
crossplane composition render xr.yaml composition.yaml functions.yaml \
  --extra-resources extra-resources --include-context

# валидация сгенерированных ресурсов по схемам провайдеров
crossplane composition render xr.yaml composition.yaml functions.yaml \
  | crossplane beta validate schemas -
```
> `render` требует Docker. Для разработки своей функции используйте `render.crossplane.io/runtime: Development` в `functions.yaml`, чтобы запускать её локально (`go run` / `python`).

## Дополнительная информация

- [Compositions (Pipeline Mode)](https://docs.crossplane.io/latest/composition/compositions/)
- [Composition Functions](https://docs.crossplane.io/latest/composition/composition-functions/)
- [Environment Configs](https://docs.crossplane.io/latest/composition/environment-configs/)
- [Написание функции на Python](https://docs.crossplane.io/latest/guides/write-a-composition-function-in-python/)
- [CLI: render / validate](https://docs.crossplane.io/latest/cli/command-reference/)

Смежные темы:
- [Мультитенантность и OOO](./multi_tenancy.md) — `EnvironmentConfig` по тенанту.
- [Тестирование платформы](./testing_crossplane.md) — `render`/`validate` в CI.
- [Обзор Crossplane](./overview.md) — XRD/Composition на концептуальном уровне.
