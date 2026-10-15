# Crossplane: Патчи, трансформы и PatchSets (function-patch-and-transform)

**Актуально для:** Crossplane v1.17+ / v2.x (актуально v2.4); function-patch-and-transform v0.8.x; On-Premise / Bare-Metal

## Определения

**Patch (патч)** — декларативная операция копирования значения из одного поля исходного ресурса (XR, Managed Resource или EnvironmentConfig) в поле целевого ресурса внутри входа `function-patch-and-transform` (`pt.fn.crossplane.io/v1beta1`, `kind: Resources`). Патч описывается парой `fromFieldPath` / `toFieldPath` в нотации JSONPath-подобных путей Kubernetes (`spec.parameters.size`, `metadata.labels[env]`, `spec.hard[limits.cpu]`).

**Transform (трансформ)** — необязательная цепочка преобразований, применяемых к значению перед записью в целевое поле. Трансформы выполняются последовательно в порядке объявления; на выходе одного трансформа подаётся вход следующего.

**PatchSet** — именованный переиспользуемый набор патчей, объявляемый в блоке `patchSets` входа функции и подключаемый к конкретному ресурсу через патч `type: PatchSet`. Позволяет избежать дублирования одинаковых патчей между ресурсами композиции.

**FieldPath (полевой путь)** — строковое выражение, указывающее на конкретное поле YAML-манифеста. Поддерживается индексация массивов (`[0]`) и обращение к ключам map с точками в имени через квадратные скобки (`[corp.internal/env]`).

**Environment FieldPath** — вариация пути, читающего значение из контекста `EnvironmentConfig` (подключается функцией `function-environment-configs`) вместо полей самого XR.

## Базовые концепции и архитектура

### Место патчей в конвейере композиции

В Crossplane v2.x статический механизм Patch & Transform (`spec.resources` в `Composition`) удалён. Его полная замена — `function-patch-and-transform`, чей вход визуально совпадает с прежним синтаксисом, но размещён под `spec.pipeline[].input`:

```text
Composition (mode: Pipeline)
└─ step: patch-and-transform
   └─ functionRef: function-patch-and-transform
      └─ input (kind: Resources)
         ├─ patchSets[]      ← переиспользуемые группы патчей
         └─ resources[]      ← шаблоны MR + patches + transforms + connectionDetails
```

Функция исполняется как gRPC-под в `crossplane-system`; вход получает Observed State (XR и дочерние MR) и возвращает Desired State — пополненный список ресурсов с применёнными патчами.

### Типы патчей

| Тип | Источник → Цель | Типичный сценарий (On-Prem / SRE) |
|---|---|---|
| `FromCompositeFieldPath` | Поле XR → поле MR | Перенос `spec.parameters.region` в `spec.forProvider.region` |
| `ToCompositeFieldPath` | Поле MR → поле XR (status) | Проброс созданного Endpoint из MR в `status.endpoint` XR для потребления следующим шагом |
| `CombineFromComposite` | Несколько полей XR → одно поле MR (конкатенация/форматирование) | Сборка DNS-имени: `"<namespace>-<name>.corp.internal"` |
| `FromEnvironmentFieldPath` | Поле EnvironmentConfig → поле MR | Подстановка CIDR, квот StorageClass из профиля дата-центра |
| `ToEnvironmentFieldPath` | Поле MR → in-memory Environment (context) | Передача вычисленного значения в контекст для следующих функций конвейера |
| `PatchSet` | Подключение именованного набора | Массовое применение общих меток/лейблов ко всем ресурсам |

> **Ограничение:** патчи не поддерживают прямой перенос между двумя composed-ресурсами. Для передачи значения от одного MR к другому используется промежуточный `ToCompositeFieldPath` (запись в `status` XR), а следующий ресурс читает это значение через `FromCompositeFieldPath`.

### Типы трансформов

| Тип | Назначение | Пример использования |
|---|---|---|
| `string` | Форматирование: `fmt` (Go fmt), `trim`, `trimPrefix`, `trimSuffix`, `replace`, `regexp`, `join`, `convert` | `"db-%s" % name` → `db-billing` |
| `math` | Арифметика: `multiply`, `clamp`, `format` | Перевод GiB → MiB (`multiply: 1024`) |
| `map` | Детерминированное словарное преобразование значения | `"small" → "2Gi"`, `"prod" → "dc1-prod"` |
| `convert` | Смена типа: `string`, `int`, `int64`, `bool`, `float64` | Числовой порт из строки параметра |

Трансформы конвейируются: значение проходит последовательно через весь массив `transforms` в порядке объявления. Патч с неразрешимым `fromFieldPath` по умолчанию пропускается без ошибки; для обязательных полей используется `policy.fromFieldPath: Required`.

### PatchSets: правила и ограничения

- PatchSet **не может содержать** вложенные PatchSets.
- `transforms` и `policy`, объявленные внутри PatchSet, Crossplane **игнорирует** — применяются только сами патчи.
- PatchSet подключается к ресурсу патчем `type: PatchSet` с полем `patchSetName`.
- Имя PatchSet уникально в пределах одного входа функции.

## Практические сценарии и конфигурация

### Сценарий 1: Полный каталог патчей и трансформов (On-Premise PostgreSQL)

Композиция платформенной команды: из XR с параметрами `name`, `namespace`, `storageGiB`, `tier` генерируется `Object` (Secret connection) и `Database` (provider-sql), с обогащением через EnvironmentConfig.

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: postgres-onprem
spec:
  compositeTypeRef:
    apiVersion: platform.internal/v1alpha1
    kind: XPostgreSQLInstance
  mode: Pipeline
  pipeline:
    - step: load-env
      functionRef:
        name: function-environment-configs
      input:
        apiVersion: environmentconfigs.fn.crossplane.io/v1beta1
        kind: Input
        spec:
          environmentConfigs:
            - type: Reference
              ref:
                name: dc1-production

    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        patchSets:
          # Именованный набор общих меток — применяется ко всем ресурсам
          - name: common-labels
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: metadata.labels[team]
                toFieldPath: metadata.labels[corp.internal/team]
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.tier
                toFieldPath: metadata.labels[corp.internal/tier]
        resources:
          - name: db-secret
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              spec:
                forProvider:
                  manifest:
                    apiVersion: v1
                    kind: Secret
                    metadata:
                      name: db-credentials
                    stringData:
                      # Заполняется патчами ниже
                      POSTGRES_DB: ""
            patches:
              - type: PatchSet
                patchSetName: common-labels
              # CombineFromComposite: сборка имени базы из двух полей XR
              - type: CombineFromComposite
                combine:
                  variables:
                    - fromFieldPath: metadata.labels[team]
                    - fromFieldPath: spec.parameters.name
                  strategy: string
                  string:
                    fmt: "%s_%s"
                toFieldPath: spec.forProvider.manifest.stringData.POSTGRES_DB
              # map-трансформ: словарное преобразование tier → размер
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.tier
                toFieldPath: spec.forProvider.manifest.stringData.PGDATA_SIZE
                transforms:
                  - type: map
                    map:
                      small:  "2Gi"
                      medium: "8Gi"
                      large:  "32Gi"

          - name: database
            base:
              apiVersion: postgresql.sql.crossplane.io/v1alpha1
              kind: Database
              spec:
                forProvider:
                  encoding: UTF8
            patches:
              - type: PatchSet
                patchSetName: common-labels
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.name
                toFieldPath: metadata.annotations[crossplane.io/external-name]
              # math-трансформ: GiB → MiB (пример приведения типа + умножения)
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.storageGiB
                toFieldPath: spec.forProvider.storageMB
                transforms:
                  - type: convert
                    convert: int64
                  - type: math
                    math:
                      multiply: 1024
              # FromEnvironmentFieldPath: значение из EnvironmentConfig дата-центра
              - type: FromEnvironmentFieldPath
                fromFieldPath: defaultLocale
                toFieldPath: spec.forProvider.locale
              # ToCompositeFieldPath: проброс имени БД обратно в XR (status)
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.name
                toFieldPath: status.databaseName

    - step: auto-ready
      functionRef:
        name: function-auto-ready
```

### Сценарий 2: string-трансформы (fmt, trim, replace) для DNS-имён

```yaml
patches:
  # fmt: подстановка подстановочных значений Go fmt
  - type: FromCompositeFieldPath
    fromFieldPath: metadata.name
    toFieldPath: spec.forProvider.manifest.metadata.annotations[external-dns/hostname]
    transforms:
      - type: string
        string:
          type: Format
          fmt: "%s.db.corp.internal"
  # replace: замена запрещённых символов в имени
  - type: FromCompositeFieldPath
    fromFieldPath: metadata.name
    toFieldPath: spec.forProvider.manifest.metadata.name
    transforms:
      - type: string
        string:
          type: Convert
          convert: ToLower
      - type: string
        string:
          type: Replace
          regexp: "[^a-z0-9-]"
          replace: "-"
```

### Сценарий 3: Обязательные поля через policy и ToCompositeFieldPath между шагами

```yaml
patches:
  # Обязательный параметр: если путь не найден — ошибка композиции, а не тихий пропуск
  - type: FromCompositeFieldPath
    fromFieldPath: spec.parameters.backupWindow
    toFieldPath: spec.forProvider.backupWindow
    policy:
      fromFieldPath: Required

  # Проброс Endpoint из MR в status XR — читается следующим ресурсом
  - type: ToCompositeFieldPath
    fromFieldPath: status.atProvider.endpoint
    toFieldPath: status.connectionHost
```

Следующий ресурс в той же композиции читает `status.connectionHost`:

```yaml
- type: FromCompositeFieldPath
  fromFieldPath: status.connectionHost
  toFieldPath: spec.forProvider.manifest.stringData.DB_HOST
```

## Операции и команды

| Задача | Команда |
|---|---|
| Локальный рендер с проверкой патчей | `crossplane render xr.yaml composition.yaml functions.yaml` |
| Рендер с контекстом EnvironmentConfig | `crossplane render ... --extra-resources=env.yaml --include-context` |
| Валидация сгенерированных MR | `crossplane render ... \| crossplane beta validate schemas/ -` |
| Проверка установленной функции | `kubectl get function function-patch-and-transform` |
| Логи патчинга | `kubectl logs -n crossplane-system -l pkg.crossplane.io/pkg=function-patch-and-transform --tail=100` |

Пример ожидаемого вывода рендера (фрагмент):

```text
---
apiVersion: postgresql.sql.crossplane.io/v1alpha1
kind: Database
metadata:
  name: billing_prod
  annotations:
    crossplane.io/external-name: "billing_prod"
  labels:
    corp.internal/team: billing
    corp.internal/tier: medium
spec:
  forProvider:
    storageMB: 8192
    locale: ru_RU.UTF-8
    encoding: UTF8
```

## Устранение неполадок (Troubleshooting)

| Симптом | Первопричина | Диагностика | Решение |
|---|---|---|---|
| Поле MR остаётся с дефолтом из `base` | `fromFieldPath` указывает на несуществующее поле XR (опечатка или параметр не объявлен в XRD) | `crossplane render ... --include-context` — пустой путь в выводе | Исправить путь; для обязательных полей добавить `policy.fromFieldPath: Required` |
| Ошибка `cannot match` при использовании PatchSet | PatchSet не объявлен в `patchSets` или опечатка в `patchSetName` | Логи функции: `cannot find patchset` | Проверить имена; помнить: PatchSet не может быть вложен в другой PatchSet |
| `transforms` внутри PatchSet не выполняются | Ограничение функции: transforms и policy в PatchSet игнорируются | Вывод `crossplane render` без преобразования | Вынести трансформы в патчи на уровне ресурса |
| Значение не передаётся между двумя MR | Прямые патчи между composed-ресурсами не поддерживаются | Нет смены значения у второго MR | Использовать `ToCompositeFieldPath` → промежуточное поле `status` XR → `FromCompositeFieldPath` |
| `multiple candidates` при обращении к map-ключу с точками | Ключ содержит точку и парсится как вложенный путь | Ошибка валидации пути | Использовать квадратные скобки: `metadata.labels[corp.internal/env]` |

## Лучшие практики (Best Practices)

1. **PatchSet только для действительно общих патчей** (метки ownership, стандартные аннотации). Специфичные для ресурса патчи держите в блоке `resources[].patches` — иначе рефакторинг одного PatchSet затрагивает все ресурсы разом.
2. **Обязательные параметры — через `policy.fromFieldPath: Required`.** Тихий пропуск отсутствующего поля маскирует ошибки схемы XRD до попадания в прод.
3. **Передача между MR — через `status` XR,** а не через костыли с общими Secrets. Так сохраняется декларативность и трассируемость (`crossplane beta trace`).
4. **Проверяйте каждое изменение патчей через `crossplane render` в CI** (см. [Тестирование платформы](./testing_crossplane.md)): регрессии патчей выявляются до применения в кластер.
5. **Не смешивайте патчи с мутациями вебхуков** (см. [Политики и Governance](./policy_governance.md)): мутация XR/MR admission-вебхуком конфликтует с патчингом функции и усложняет отладку.
6. **Для динамических списков и условий** (`if`, `range`, цепочки зависимостей) переходите на `function-go-templating` или `function-kcl` — `function-patch-and-transform` намеренно не поддерживает циклы и условия (см. [Composition Functions](./composition_functions.md)).

## Дополнительная информация

### Внутренние ссылки

* [Composition Functions и EnvironmentConfig](./composition_functions.md) — gRPC-конвейер, подключение `function-environment-configs`, контекст окружений.
* [Тестирование платформы](./testing_crossplane.md) — оффлайн-рендер и golden-тесты патчей.
* [Политики и Governance](./policy_governance.md) — валидация патчей и запрет мутирующих вебхуков для XR/MR.
* [Паттерны композиций и connectionDetails](./connection_details.md) — агрегация секретов подключения, проброс между ресурсами.

### Внешние ресурсы

* [Function Patch and Transform (документация Crossplane v2.4)](https://docs.crossplane.io/latest/guides/function-patch-and-transform/) — справочник типов патчей, трансформов и PatchSets.
* [crossplane-contrib/function-patch-and-transform](https://github.com/crossplane-contrib/function-patch-and-transform) — исходный код функции, схема входа `pt.fn.crossplane.io/v1beta1`.
