# Crossplane: Connection Details — проброс секретов подключения

**Актуально для:** Crossplane v1.17+ / v2.x (актуально v2.4); On-Premise / Bare-Metal

## Определения

**Connection Details (секреты подключения)** — набор чувствительных данных (учётные данные, endpoint, порт), которые Managed Resource (MR) извлекает из внешней системы после создания ресурса и публикует в виде Kubernetes `Secret`. Провайдер сам определяет, какие атрибуты являются секретными (пароли, токены), и записывает их в `Secret`, настроенный через `spec.writeConnectionSecretToRef`.

**writeConnectionSecretToRef** — поле `spec` Managed Resource, указывающее имя и (для legacy cluster-scoped MR) namespace секрета, куда провайдер пишет реквизиты. В Crossplane v2 namespace--scoped MR всегда пишет секрет в собственный namespace.

**connectionDetails (в Composition)** — блок в шаблоне ресурса композиции, перечисляющий ключи из секрета MR, которые должны быть включены в агрегированный секрет XR. Поддерживает типы `FromConnectionSecretKey` (копирование ключа) и `FromValue` (передача фиксированного значения).

**Агрегированный секрет XR (v2-паттерн)** — рекомендованный в Crossplane v2 механизм: в композицию добавляется явный ресурс `Secret`, который собирает все connection details дочерних MR в один объект, доступный потребителю XR. Автоматическая генерация секрета XR (как в v1) в v2 для XRs удалена.

**Claim connection secret (v1-паттерн)** — в архитектуре с Claims пользователь указывает `writeConnectionSecretToRef` в манифесте Claim; Crossplane создаёт секрет в namespace Claim с указанным именем.

## Базовые концепции и архитектура

### Цепочка проброса (v1-стиль: Claim → XR → MR)

```text
Claim (writeConnectionSecretToRef.name: billing-db-secret)
  │
  ▼
XR (получает агрегированный секрет в namespace Claim)
  │  ← writeConnectionSecretsToNamespace в Composition
  │  ← connectionDetails[] в каждом ресурсе Composition
  ▼
MR (каждый пишет свой локальный Secret через writeConnectionSecretToRef)
  │
  ▼
Внешняя система (PostgreSQL, MinAPI, и т.д.) — провайдер читает реквизиты после Create
```

### Цепочка проброса (v2-рекомендация: XR ← агрегирующий Secret)

В Crossplane v2 автоматическое создание connection details для XR отключено. Рекомендованный паттерн:

```text
MR-A (Secret A: username/password)
MR-B (Secret B: host/port)
        │ connectionDetails: FromConnectionSecretKey
        ▼
Ресурс Secret в Composition (агрегат: скопирует ключи A + B)
        │
        ▼
XR читает/публикует этот Secret как свой connection secret
```

### Различия v1 и v2

| Аспект | Crossplane v1 | Crossplane v2 |
|---|---|---|
| Автосоздание секрета XR | Поддерживается (`writeConnectionSecretsToNamespace`) | Удалено для XR; MR не затронуты |
| Scope XR | Cluster-scoped (только с Claims) | Namespaced по умолчанию; `spec.crossplane` вместо верхнеуровневых полей |
| Секрет MR | `writeConnectionSecretToRef` (namespace + name) | `writeConnectionSecretToRef` (namespace совпадает с MR) |
| Рекомендация | Claims + `writeConnectionSecretsToNamespace` | Явный `Secret` в Composition |

## Практические сценарии и конфигурация

### Сценарий 1: Полная цепочка v1-style (Claim → XR → MR → PostgreSQL)

XRD объявляет поле имени секрета:

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xpostgresqlinstances.platform.internal
spec:
  group: platform.internal
  names:
    kind: XPostgreSQLInstance
    plural: xpostgresqlinstances
  claimNames:
    kind: PostgreSQLInstance
    plural: postgresqlinstances
  connectionSecretKeys:
    - username
    - password
    - endpoint
    - port
  versions:
    - name: v1alpha1
      served: true
      referenceable: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                writeConnectionSecretToRef:
                  type: object
                  properties:
                    name:
                      type: string
                  required:
                    - name
```

Composition с `writeConnectionSecretsToNamespace` и `connectionDetails`:

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: postgres-patroni
spec:
  compositeTypeRef:
    apiVersion: platform.internal/v1alpha1
    kind: XPostgreSQLInstance
  writeConnectionSecretsToNamespace: crossplane-system   # namespace для агрегата XR
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: postgres-database
            base:
              apiVersion: postgresql.sql.crossplane.io/v1alpha1
              kind: Database
              spec:
                forProvider:
                  encoding: UTF8
                writeConnectionSecretToRef:
                  name: db-conn      # локальный Secret MR
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.parameters.name
                toFieldPath: metadata.annotations[crossplane.io/external-name]
              # Проброс имени секрета из Claim/XR в MR
              - type: FromCompositeFieldPath
                fromFieldPath: spec.writeConnectionSecretToRef.name
                toFieldPath: spec.writeConnectionSecretToRef.name
            connectionDetails:
              - name: username
                type: FromConnectionSecretKey
                fromConnectionSecretKey: username
              - name: password
                type: FromConnectionSecretKey
                fromConnectionSecretKey: password
              - name: endpoint
                type: FromConnectionSecretKey
                fromConnectionSecretKey: endpoint
              - name: port
                type: FromConnectionSecretKey
                fromConnectionSecretKey: port

    - step: auto-ready
      functionRef:
        name: function-auto-ready
```

Claim пользователя:

```yaml
apiVersion: platform.internal/v1alpha1
kind: PostgreSQLInstance
metadata:
  name: billing-db
  namespace: team-billing
spec:
  parameters:
    name: billing_prod
  writeConnectionSecretToRef:
    name: billing-db-secret   # секрет появится в namespace team-billing
```

Проверка цепочки:

```bash
# 1. Секреты MR (namespace crossplane-system)
kubectl get secret -n crossplane-system db-conn
# → NAME      TYPE     DATA   AGE
# → db-conn   Opaque   4      3m

# 2. Агрегат XR (namespace crossplane-system)
kubectl get secret -n crossplane-system -l crossplane.io/composite=xpostgresqlinstances.platform.internal/billing-db
# → billing-db-agg   Opaque   4   2m

# 3. Секрет Claim (namespace team-billing)
kubectl get secret -n team-billing billing-db-secret
# → billing-db-secret   Opaque   4   2m

# 4. Содержимое
kubectl get secret -n team-billing billing-db-secret -o jsonpath='{.data}' | jq 'keys'
# → ["endpoint", "password", "port", "username"]
```

### Сценарий 2: v2-паттерн — явный агрегирующий Secret в Composition

Для Crossplane v2 (namespaced XR без Claims) добавьте ресурс `Secret`, который копирует ключи из MR:

```yaml
resources:
  - name: postgres-creds-mr
    base:
      apiVersion: postgresql.sql.crossplane.io/v1alpha1
      kind: Database
      spec:
        forProvider:
          encoding: UTF8
        writeConnectionSecretToRef:
          name: pg-local-conn
    patches:
      - type: FromCompositeFieldPath
        fromFieldPath: metadata.name
        toFieldPath: spec.writeConnectionSecretToRef.name
    connectionDetails:
      - name: username
        type: FromConnectionSecretKey
        fromConnectionSecretKey: username
      - name: password
        type: FromConnectionSecretKey
        fromConnectionSecretKey: password

  # Агрегирующий Secret: имя берётся из поля XR (или фиксируется)
  - name: aggregated-secret
    base:
      apiVersion: v1
      kind: Secret
      metadata:
        name: db-connection   # может быть переименован патчем
      type: Opaque
      stringData: {}
    patches:
      - type: FromCompositeFieldPath
        fromFieldPath: spec.parameters.secretName
        toFieldPath: metadata.name
        policy:
          fromFieldPath: Optional
    connectionDetails:
      - name: username
        type: FromConnectionSecretKey
        fromConnectionSecretKey: username
      - name: password
        type: FromConnectionSecretKey
        fromConnectionSecretKey: password
```

### Сценарий 3: FromValue — передача фиксированного значения в секрет

```yaml
connectionDetails:
  - name: connection_type
    type: FromValue
    value: "postgres-patroni-ha"
  - name: ssl_mode
    type: FromValue
    value: "require"
```

## Операции и команды

| Задача | Команда |
|---|---|
| Список секретов MR в namespace Crossplane | `kubectl get secret -n crossplane-system` |
| Фильтр по метке композитного ресурса | `kubectl get secret -n crossplane-system -l crossplane.io/composite=<xr-name>` |
| Просмотр ключей агрегата | `kubectl get secret -n <ns> <name> -o jsonpath='{.data}' \| jq 'keys'` |
| Диагностика отказа записи | `kubectl describe composite <xr> \| grep -A5 CannotPublish` |
| Проверка RBAC провайдера на секреты | `kubectl get clusterrole -l rbac.crossplane.io/managed-by=provider-<name> -o yaml \| grep -A3 secrets` |

Пример диагностики зависшего Claim:

```bash
kubectl describe postgresqlinstance billing-db -n team-billing
# → Events:
# →   Warning  CannotPublishConnectionDetails  composite/xbilling-db
# →     cannot write connection secret to namespace team-billing: secrets is forbidden
```

## Устранение неполадок (Troubleshooting)

| Симптом | Первопричина | Диагностика | Решение |
|---|---|---|---|
| `CannotPublishConnectionDetails` / `forbidden` | Crossplane SA не имеет права `create`/`update` секретов в namespace тенанта | Логи ядра: `cannot write connection secret` | Добавить RBAC (в v2 RBAC Manager делает это автоматически при корректной настройке); проверить `writeConnectionSecretToRef.namespace` |
| Секрет MR создан, но Claim пуст | В Composition не указаны `connectionDetails` или `writeConnectionSecretsToNamespace` | `kubectl get secret -n crossplane-system` — нет агрегата | Добавить блок `connectionDetails` к ресурсу и указать `writeConnectionSecretsToNamespace` (v1) или агрегирующий `Secret` (v2) |
| Ключи отсутствуют в агрегате | Провайдер не публикует ожидаемый ключ (несовпадение имени) | Сравнить `kubectl get secret <mr-secret> -o jsonpath='{.data}' \| jq 'keys'` с `connectionDetails[].fromConnectionSecretKey` | Исправить имена ключей; обратиться к документации провайдера за списком публикуемых ключей |
| Секрет перезаписан чужим ресурсом | Два MR указывают одно `writeConnectionSecretToRef.name` | `kubectl get secret <name> -o yaml` + `managedFields` | Гарантировать уникальность имени секрета (патчеризовать из `metadata.name` XR) |
| Удаление Claim не удаляет секрет | `deletionPolicy: Orphan` на MR или отсутствие владельца | `kubectl get secret <name> -o yaml \| grep ownerReferences` | Для временных сред переключить `deletionPolicy: Delete`; для прод — оставить Orphan и чистить отдельно |
| v2: XR без connection secret | Автогенерация удалена в v2 | Нет Secret с меткой композита | Добавить явный агрегирующий ресурс `Secret` в Composition (Сценарий 2) |

## Лучшие практики (Best Practices)

1. **Не храните чувствительные данные в `EnvironmentConfig` или параметрах XR** — только в Secrets, с ограниченным RBAC.
2. **Патчеризуйте имя секрета из `metadata.name` XR** (`"%s-conn" % xr.name`) — исключает коллизии при совместном использовании композиции.
3. **Для мультитенантности** включите ValidatingAdmissionPolicy, запрещающий запись в чужой namespace (см. [Мультитенантность](./multi_tenancy.md)).
4. **Секреты провайдеров (ProviderConfig credentials) и connection details — разные слои.** Первые доставляются ESO/Vault в `crossplane-system`; вторые создаёт сам Crossplane. Не смешивайте потоки.
5. **Ротация паролей во внешней системе** не обновит уже созданный Secret: провайдер перечитывает реквизиты только при reconcile изменения MR. После ротации выполните `kubectl annotate <mr> crossplane.io/forced-reconcile="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite` (или пересоздайте MR).
6. **В v2 переходите на явный агрегирующий `Secret`** вместо v1-механизма — он работает с namespaced XR и не требует `writeConnectionSecretsToNamespace`.

## Дополнительная информация

### Внутренние ссылки

* [Обзор Crossplane](./overview.md) — базовая модель XR/MR и lifecycle.
* [Мультитенантность и изоляция](./multi_tenancy.md) — защита от cross-namespace hijacking секретов.
* [Патчи, трансформы и PatchSets](./patch_transform.md) — патчеризация имени секрета из полей XR.
* [Self-Service и IDP](./self_service.md) — получение секретов прикладными командами.
* [Интеграция с GitOps](./gitops_integration.md) — ESO + PushSecret для возврата секретов во Vault.

### Внешние ресурсы

* [Connection Details Composition (Crossplane v2.4)](https://docs.crossplane.io/latest/guides/connection-details-composition/) — рекомендованный v2-паттерн с агрегирующим Secret.
* [Connection Details (Crossplane v1.20)](https://docs.crossplane.io/v1.20/concepts/connection-details/) — v1-механизм с Claims и `writeConnectionSecretsToNamespace`.
