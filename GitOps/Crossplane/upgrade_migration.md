# Crossplane: Обновление, миграция и откат

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

---

## Определения

**Control Plane Crossplane (ядро Crossplane)** — кластерный оператор Kubernetes (`crossplane`), состоящий из контроллеров управления жизненным циклом пакетов (`pkg.crossplane.io`), композиций (`apiextensions.crossplane.io`) и механизмов валидации. Отвечает за координацию провайдеров, выполнение конвейеров функций и поддержание желаемого состояния инфраструктуры.

**Package Revision (ревизия пакета)** — неизменяемый (`immutable`) дочерний ресурс пакета (`ProviderRevision`, `FunctionRevision`, `ConfigurationRevision` в API-группе `pkg.crossplane.io`), создаваемый пакетным менеджером Crossplane при изменении ссылки на OCI-образ (`spec.package`). Ревизия инкапсулирует распакованные CRD, вебхуки и контроллер конкретной версии пакета.

**Revision Activation Policy (`spec.revisionActivationPolicy`)** — стратегия переключения ревизий пакета:
- `Automatic` — новая ревизия автоматически активируется сразу после успешной загрузки и прохождения проверок работоспособности (`HEALTHY=True`), а старая деактивируется;
- `Manual` — новая ревизия создается в неактивном состоянии (`Active=False`), переключение на нее требует явного подтверждения оператором или платформенным скриптом.

**Revision History Limit (`spec.revisionHistoryLimit`)** — число неактивных предыдущих ревизий пакета (`ProviderRevision` или `FunctionRevision`), сохраняемых в etcd кластера после обновления. Служит для возможности быстрого отката и автоматической очистки (Garbage Collection) устаревших манифестов.

**CompositionRevision (ревизия композиции)** — неизменяемый снимок спецификации шаблона композиции (`kind: CompositionRevision`, API-группа `apiextensions.crossplane.io`), автоматически создаваемый Crossplane при любом изменении исходного ресурса `Composition`. Каждая ревизия фиксирует состояние конвейера функций и логику сборки управляемых ресурсов.

**Composition Revision Policy (`spec.compositionRevisionPolicy`)** — правило выбора ревизии композиции составным ресурсом (`XR`) или пользовательской заявкой (`Claim`):
- `Automatic` — XR непрерывно следует за самой свежей активной ревизией `Composition`;
- `Manual` — XR жестко зафиксирован на конкретной ревизии (`spec.compositionRevisionRef.name`), защищая инфраструктуру от непреднамеренных изменений логики шаблона.

**CRD Migration & Conversion Webhook** — процесс обновления схем CustomResourceDefinition в Kubernetes API при переходе между мажорными версиями Crossplane или провайдеров. Включает механизм конвертации версий API (например, `v1alpha1` → `v1beta1` → `v1`) через конверсионные вебхуки без потери метаданных ресурсов.

**Reconciliation Loop vs Git Rollback (семантика отката)** — фундаментальное различие между отменой коммита в системе контроля версий (`git revert`) и физическим состоянием управляемой инфраструктуры. GitOps-оператор синхронизирует декларативное состояние в etcd, после чего Crossplane запускает цикл согласования (Reconcile Loop). Если удаленный из Git ресурс имел политику по умолчанию `deletionPolicy: Delete`, Crossplane отправит команду на удаление физического объекта во внешней системе.

**Orphan Deletion Policy (`deletionPolicy: Orphan`)** — директива жизненного цикла ресурса Crossplane, предписывающая при удалении объекта из Kubernetes удалить только его Kubernetes-представление и финализаторы, оставив целевой физический ресурс (базу данных, том СХД, сеть, конфигурацию) нетронутым во внешней инфраструктуре.

**Crossplane Paused (`crossplane.io/paused`)** — системная аннотация (`"true"`), полностью замораживающая цикл реконсиляции для конкретного ресурса или пакета. Критически важна при аварийных переключениях, обновлении схем данных и миграциях между кластерами.

---

## Архитектура и базовые концепции

### 1. Архитектура жизненного цикла обновления ядра Crossplane

В корпоративной On-Premise инфраструктуре управляющий контур Crossplane развертывается в выделенном кластере Kubernetes посредством Helm-чарта `crossplane`. Оператор разделен на два ключевых процесса:
1. **Crossplane Core Controller:** обслуживает XRD, Compositions, Claims, Composite Resources (XR) и жизненный цикл пакетов.
2. **Crossplane RBAC Manager:** динамически генерирует кластерные роли и привязки для устанавливаемых провайдеров и ревизий.

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                       HELM UPGRADE PIPELINE CORE                            │
│                                                                             │
│ 1. Pre-Upgrade Backup (etcd / Velero)                                       │
│    └─► Фиксация состояния CRD, XR, Claim, ProviderRevision                  │
│                                                                             │
│ 2. CRD Server-Side Apply (Manual / Pre-Hook)                                │
│    └─► Обновление apiextensions.crossplane.io & pkg.crossplane.io           │
│                                                                             │
│ 3. RollingUpdate Deployment crossplane                                      │
│    ├─► Остановка старого Pod crossplane (Reconciliation замирает)           │
│    ├─► Старт нового Pod v2.4 (Запуск вебхуков валидации и конверсии)       │
│    └─► Возобновление циклов сверки (Data-plane инфраструктура НЕ прерывается)│
└─────────────────────────────────────────────────────────────────────────────┘
```

#### Поведение инфраструктуры во время обновления Core
При обновлении или временной недоступности пода оператора Crossplane:
- **Разделение Control Plane и Data Plane:** управляемая инфраструктура (локальные СУБД PostgreSQL, кластеры Kubernetes, распределенные тома Ceph, конфигурации сетевых коммутаторов, секреты HashiCorp Vault) продолжает функционировать штатно. Потеря связи с control plane не влияет на сетевой трафик и клиентские соединения.
- **Очередь событий (Reconciliation pause):** новые события модификации манифестов накапливаются в очередях `workqueue`. После старта нового пода контроллер производит холодный аудит всех ресурсов.
- **Особенность Helm:** встроенный механизм Helm не обновляет CRD, находящиеся в директории `crds/`, при выполнении стандартной команды `helm upgrade`. Поэтому регламент обновления ядра обязательно включает предварительное применение манифестов CRD через `kubectl apply --server-side`.

---

### 2. Архитектура пакетного менеджера: ревизии и изоляция

Пакеты Crossplane (`Provider`, `Function`, `Configuration`) распространяются в виде OCI-артефактов (`xpkg`). Пакетный менеджер Crossplane исключает деструктивные обновления «на месте» (in-place modification), используя модель неизменяемых ревизий:

```text
       spec.package: registry.local/provider-kubernetes:v1.3.0
                            │
                            ▼
               ┌─────────────────────────┐
               │    Provider (Parent)    │
               │  spec.revisionHistory: 2│
               │  activationPolicy: Auto │
               └────────────┬────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│ ProviderRevision-v1.2.0 │     │ ProviderRevision-v1.3.0 │
│   Active: False         │     │   Active: True          │
│   Healthy: True         │     │   Healthy: True         │
│   (Контроллер остановлен│     │   (Контроллер запущен,  │
│    CRD сохраняются)     │     │    управляет MR)        │
└─────────────────────────┘     └─────────────────────────┘
```

#### Фазы жизненного цикла ProviderRevision
1. **Pull & Unpack:** контроллер пакетов загружает OCI-образ из корпоративного registry, валидирует xpkg-манифест, подпись Cosign (если включена) и извлекает CRD контроллера.
2. **CRD Establishment:** ревизия регистрирует или обновляет CRD. Если другая активная ревизия того же пакета уже владеет этими CRD, происходит процедура передачи владения (ownership handoff).
3. **Deployment Reconciler:** при переходе ревизии в статус `Active=True` создается под контроллера провайдера с параметрами из `DeploymentRuntimeConfig`. Старая ревизия деактивируется (`Active=False`), а ее под контроллера грациозно удаляется.
4. **Garbage Collection:** если число неактивных ревизий превышает `spec.revisionHistoryLimit`, самая старая ревизия удаляется. Для защиты etcd от разрастания метаданных в production-контурах лимит фиксируется на значении `1` или `2`.

---

### 3. Версионирование и канареечный rollout композиций (CompositionRevisions)

В архитектуре Crossplane шаблон `Composition` является генератором графа управляемых ресурсов. В реальной эксплуатации внесение изменений в Composition без версионирования несет критический риск массовой деградации инфраструктуры платформы.

```text
 1. Изменение манифеста Composition (GitOps push)
                │
                ▼
 2. Контроллер Crossplane фиксирует diff
    └─► Генерация новой иммутабельной CompositionRevision (hash: a1b2c)
                │
                ├─────────────────────────────────────────┐
                ▼                                         ▼
 3. Claims с Automatic Policy             4. Canary Claim с Manual Policy
    (spec.compositionRevisionPolicy: Auto)   (spec.compositionRevisionRef: ...-a1b2c)
    └─► Мгновенный пересчет графа MR         └─► Изолированная проверка новой версии
```

#### Связка XRD, CompositionRevision и XR
- **CompositeResourceDefinition (XRD):** определяет глобальную политику по умолчанию для всех дочерних ресурсов через поле `spec.defaultCompositionRevisionPolicy` (`Automatic` или `Manual`).
- **Composite Resource (XR) и Claim:** содержат поля:
  - `spec.compositionRef.name` — базовое имя композиции;
  - `spec.compositionRevisionRef.name` — явное имя конкретной ревизии;
  - `spec.compositionRevisionPolicy` — стратегия обновления (`Automatic` или `Manual`).
- **Механизм отката:** если обновленная версия композиции порождает некорректные спецификации ресурсов или ошибки валидации, администратор выполняет мгновенное переключение `compositionRevisionRef` на предыдущую стабильную ревизию без необходимости повторного применения Git-коммитов и ожидания конвейеров CI/CD.

---

### 4. Ключевые архитектурные изменения Crossplane v2.x (Миграция с v1.x)

При переходе с мажорной ветки Crossplane v1.x на v2.x удален ряд устаревших механизмов ядра. Архитектурный регламент требует адаптации манифестов до обновления версии контроллера.

| Архитектурный аспект | Crossplane v1.x (Legacy) | Crossplane v2.x (Текущий стандарт) | Стратегия миграции |
| :--- | :--- | :--- | :--- |
| **Движок композиций** | Статический Patch & Transform (`spec.resources`) | Исключительно Composition Functions (`mode: Pipeline`) | Перевод композиций на вызов `function-patch-and-transform` и специализированные функции |
| **Секреты подключения XR** | Встроенный `spec.writeConnectionSecretToRef` в XRD/XR | Удален из XRD. Секреты генерируются функциями конвейера | Использование нативных секретов через `provider-kubernetes` или функции генерации Secret |
| **External Secret Store (ESS)** | Встроенный механизм ESS в провайдерах | Удален из ядра большинства провайдеров | Прямая интеграция с HashiCorp Vault или оператором External Secrets Operator (ESO) |
| **Размерность провайдеров** | Крупные монолитные пакеты провайдеров | Модульные семейства (Provider Families) и микро-провайдеры | Замена монолитных пакетов на целевые сервисные провайдеры (минимизация CRD в etcd) |
| **Пространства имен XR** | Строго Cluster-scoped XR | Поддержка Namespaced Composite Resources (`Namespaced XR`) | Опциональное использование пространств имен для изоляции тенантов |

---

### 5. Семантика отката и предотвращение потери данных

Откат в Crossplane принципиально отличается от отката stateless-микросервисов в Kubernetes:
1. **Revert не удаляет автоматически изменения во внешнем мире:** если в новой версии композиции был добавлен управляемый ресурс (например, база данных PostgreSQL `Database`), а затем выполнен `git revert`, контроллер Crossplane обнаружит, что ресурс больше не описан в графе композиции.
2. **Риск каскадного уничтожения (Cascading Deletion):** если у управляемого ресурса было установлено дефолтное значение `spec.deletionPolicy: Delete`, контроллер провайдера отправит команду `DROP DATABASE` на целевой сервер СУБД.
3. **Механизмы защиты SRE:**
   - **`deletionPolicy: Orphan`:** обязательна для всех критичных stateful-компонентов. При откате ресурс удаляется из Kubernetes, но физические данные сохраняются на сервере.
   - **Management Policies (`spec.managementPolicies`):** ограничение прав контроллера набором `[Observe, Create, Update]`, исключая `Delete` во время проведения регламентных работ.
   - **Защита зависимостей (`Usage` API):** создание блокировок `protection.crossplane.io/v1beta1`, запрещающих удаление ресурсов нижнего уровня (сеть, кластер), пока активны связанные сервисы.

---

## Практические сценарии и регламенты

### Сценарий 1: Регламент планового обновления Helm-чарта ядра Crossplane (v1.18 → v2.4)

Обновление ядра Crossplane в On-Premise кластере выполняется без остановки обслуживаемых сервисов, но требует строгого соблюдения очередности применения CRD.

#### Шаг 1. Создание резервной копии etcd и метаданных Crossplane
Перед выполнением любых манипуляций создается резервная копия состояния кластера и ресурсов Crossplane с помощью Velero (детальный регламент см. в [Резервное копирование и Disaster Recovery control plane](./backup_dr.md)):

```bash
velero backup create crossplane-pre-upgrade-$(date +%Y%m%d-%H%M) \
  --include-namespaces crossplane-system \
  --include-resources customresourcedefinitions,compositecustomresourcedefinitions,compositions,providers,functions \
  --wait
# → Backup crossplane-pre-upgrade-20261013-1900 completed with status: Completed.
```

#### Шаг 2. Обновление CustomResourceDefinitions ядра
Так как Helm не обновляет CRD автоматически при вызове `helm upgrade`, применяем актуальные CRD ядра через Server-Side Apply:

```bash
kubectl apply --server-side --force-conflicts -k https://github.com/crossplane/crossplane//cluster?ref=v2.4.0
# → customresourcedefinition.apiextensions.k8s.io/compositeresourcedefinitions.apiextensions.crossplane.io serverside-applied
# → customresourcedefinition.apiextensions.k8s.io/compositions.apiextensions.crossplane.io serverside-applied
# → customresourcedefinition.apiextensions.k8s.io/providers.pkg.crossplane.io serverside-applied
# → customresourcedefinition.apiextensions.k8s.io/functions.pkg.crossplane.io serverside-applied
```

#### Шаг 3. Обновление релиза Helm
Обновляем релиз Crossplane с контролем таймаута и сохранением конфигурационных параметров:

```bash
helm upgrade crossplane crossplane-stable/crossplane \
  --namespace crossplane-system \
  --version 2.4.0 \
  --set args='{"--enable-composition-functions","--enable-composition-webhook-schema-validation"}' \
  --set resourcesCrossplane.requests.cpu="500m" \
  --set resourcesCrossplane.requests.memory="1Gi" \
  --set resourcesCrossplane.limits.cpu="2" \
  --set resourcesCrossplane.limits.memory="2Gi" \
  --wait --timeout 10m
# → Release "crossplane" has been upgraded. Happy Helming!
```

#### Шаг 4. Верификация состояния контроллеров и вебхуков
Проверяем статус завершения развертывания и корректность регистрации подов:

```bash
kubectl rollout status deployment/crossplane -n crossplane-system
# → deployment "crossplane" successfully rolled out

kubectl get pods -n crossplane-system -l app=crossplane
# → NAME                          READY   STATUS    RESTARTS   AGE
# → crossplane-7f68c4d578-8kx9w   1/1     Running   0          92s
# → crossplane-rbac-manager-699   1/1     Running   0          92s
```

---

### Сценарий 2: Безопасное обновление Provider через Manual Activation

В production-средах автоматическая смена активной версии провайдера (`revisionActivationPolicy: Automatic`) создает риск деградации control plane в случае несовместимости OCI-образа или сетевых сбоев. Рекомендуется использовать режим `Manual`.

#### Шаг 1. Декларация манифеста Provider с ручной активацией
Создаем или обновляем манифест провайдера (на примере `provider-kubernetes`), фиксируя политику ручной активации и глубину хранения истории:

```yaml
# provider-kubernetes-manual.yaml
apiVersion: pkg.crossplane.io/v1
kind: Provider
metadata:
  name: provider-kubernetes
spec:
  package: registry.local/crossplane-contrib/provider-kubernetes:v1.3.0
  revisionActivationPolicy: Manual
  revisionHistoryLimit: 2
  packagePullPolicy: IfNotPresent
```

Применяем конфигурацию:
```bash
kubectl apply -f provider-kubernetes-manual.yaml
# → provider.pkg.crossplane.io/provider-kubernetes configured
```

#### Шаг 2. Анализ созданной ревизии пакета
Пакетный менеджер Crossplane загружает образ и создает ресурс `ProviderRevision`. Проверяем список ревизий:

```bash
kubectl get providerrevisions -l pkg.crossplane.io/provider=provider-kubernetes
# → NAME                                 HEALTHY   REVISION   ACTIVE   PACKAGE
# → provider-kubernetes-1a2b3c4d5e       True      1          True     registry.local/crossplane-contrib/provider-kubernetes:v1.2.0
# → provider-kubernetes-9f8e7d6c5b       True      2          False    registry.local/crossplane-contrib/provider-kubernetes:v1.3.0
```

Новая ревизия (`rev 2`) находится в статусе `HEALTHY=True`, но `ACTIVE=False`. Ее контроллер не перехватил цикл сверки, а текущие ресурсы продолжают обслуживаться проверенной ревизией `rev 1`.

#### Шаг 3. Активация новой ревизии и верификация
Для переключения управления переводим ревизию в активное состояние:

```bash
kubectl patch providerrevision provider-kubernetes-9f8e7d6c5b \
  --type=merge \
  -p '{"spec":{"desiredState":"Active"}}'
# → providerrevision.pkg.crossplane.io/provider-kubernetes-9f8e7d6c5b patched

kubectl get providerrevisions -l pkg.crossplane.io/provider=provider-kubernetes
# → NAME                                 HEALTHY   REVISION   ACTIVE   PACKAGE
# → provider-kubernetes-1a2b3c4d5e       True      1          False    registry.local/crossplane-contrib/provider-kubernetes:v1.2.0
# → provider-kubernetes-9f8e7d6c5b       True      2          True     registry.local/crossplane-contrib/provider-kubernetes:v1.3.0
```

#### Шаг 4. Экстренный откат (Rollback) при выявлении регрессии
Если контроллер новой версии демонстрирует ошибки реконсиляции, сбои по памяти (OOM) или конфликты CRD, выполняем мгновенный откат активацией предыдущей ревизии:

```bash
kubectl patch providerrevision provider-kubernetes-1a2b3c4d5e \
  --type=merge \
  -p '{"spec":{"desiredState":"Active"}}'
# → providerrevision.pkg.crossplane.io/provider-kubernetes-1a2b3c4d5e patched
```

---

### Сценарий 3: Канареечный rollout и откат CompositionRevision

При обновлении шаблонов композиций канареечная схема (Canary Rollout) позволяет протестировать новую логику на тестовом или пилотном составном ресурсе перед массовым применением изменений ко всем потребителям платформы.

#### Шаг 1. Определение XRD с поддержкой версионирования
В ресурсе `CompositeResourceDefinition` задаем политику ревизий:

```yaml
# xrd-database.yaml
apiVersion: apiextensions.crossplane.io/v1
kind: CompositeResourceDefinition
metadata:
  name: xpostgresinstances.platform.internal
spec:
  group: platform.internal
  names:
    kind: XPostgresInstance
    plural: xpostgresinstances
  claimNames:
    kind: PostgresInstance
    plural: postgresinstances
  defaultCompositionRevisionPolicy: Automatic
  enforcedCompositionRevisionPolicy: Manual
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
              required:
                - storageGB
              properties:
                storageGB:
                  type: integer
```

#### Шаг 2. Развертывание обновленной Composition
Применяем обновленный манифест Composition. Crossplane автоматически регистрирует новую `CompositionRevision`:

```bash
kubectl apply -f composition-postgres-v2.yaml
# → composition.apiextensions.crossplane.io/postgres-standalone configured

kubectl get compositionrevisions -l crossplane.io/composition=postgres-standalone
# → NAME                           REVISION   HEALTHY   COMPOSITION
# → postgres-standalone-a1b2c3d    1          True      postgres-standalone
# → postgres-standalone-e4f5g6h    2          True      postgres-standalone
```

#### Шаг 3. Фиксация тестового Claim на новой ревизии (Canary)
Создаем или модифицируем пилотный Claim, явно указывая ссылку на ревизию `rev 2`:

```yaml
# claim-canary.yaml
apiVersion: platform.internal/v1alpha1
kind: PostgresInstance
metadata:
  name: pg-billing-canary
  namespace: team-billing
spec:
  storageGB: 50
  compositionRevisionRef:
    name: postgres-standalone-e4f5g6h
```

Применяем манифест:
```bash
kubectl apply -f claim-canary.yaml
# → postgresinstance.platform.internal/pg-billing-canary created

kubectl get postgresinstance pg-billing-canary -n team-billing
# → NAME                SYNCED   READY   COMPOSITIONREVISION           AGE
# → pg-billing-canary   True     True    postgres-standalone-e4f5g6h   45s
```

#### Шаг 4. Откат канареечного ресурса в случае ошибки
Если тесты выявили проблему (например, некорректно сформированный ConfigMap параметров СУБД), возвращаем Claim на проверенную стабильную ревизию:

```bash
kubectl patch postgresinstance pg-billing-canary -n team-billing \
  --type=merge \
  -p '{"spec":{"compositionRevisionRef":{"name":"postgres-standalone-a1b2c3d"}}}'
# → postgresinstance.platform.internal/pg-billing-canary patched
```

Контроллер Crossplane пересчитает diff графа и приведет дочерние объекты к спецификации ревизии `rev 1` без удаления базы данных.

---

### Сценарий 4: Миграция Composition с Patch & Transform (v1.x) на Functions Pipeline (v2.x)

Crossplane v2.x полностью исключает устаревший синтаксис `spec.resources`. Миграция шаблонов выполняется переходом в режим `mode: Pipeline` с использованием функций `function-patch-and-transform` и `function-auto-ready`.

#### Исходная legacy-композиция (Crossplane v1.x):
```yaml
# legacy-composition.yaml (v1.x)
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: namespace-quota-v1
spec:
  compositeTypeRef:
    apiVersion: platform.internal/v1alpha1
    kind: XTenantNamespace
  resources:
    - name: target-namespace
      base:
        apiVersion: kubernetes.crossplane.io/v1alpha1
        kind: Object
        spec:
          forProvider:
            manifest:
              apiVersion: v1
              kind: Namespace
      patches:
        - type: FromCompositeFieldPath
          fromFieldPath: spec.tenantName
          toFieldPath: spec.forProvider.manifest.metadata.name
```

#### Целевая композиция стандарта Crossplane v2.x:
```yaml
# modern-composition.yaml (v2.x)
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: namespace-quota-v2
spec:
  compositeTypeRef:
    apiVersion: platform.internal/v1alpha1
    kind: XTenantNamespace
  mode: Pipeline
  pipeline:
    - step: patch-and-transform
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: target-namespace
            base:
              apiVersion: kubernetes.crossplane.io/v1alpha1
              kind: Object
              spec:
                forProvider:
                  manifest:
                    apiVersion: v1
                    kind: Namespace
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: spec.tenantName
                toFieldPath: spec.forProvider.manifest.metadata.name
    - step: automatically-detect-readiness
      functionRef:
        name: function-auto-ready
```

#### Оффлайн-валидация отсутствия расхождений (Zero-Diff Validation)
Перед деплоем в кластер валидируем сгенерированный граф через утилиту `crossplane render` (подробнее см. в [Тестирование платформы](./testing_crossplane.md)):

```bash
crossplane render tests/xr-sample.yaml modern-composition.yaml tests/functions-bundle.yaml > rendered-output.yaml
# → Проверяем, что сгенерированные манифесты идентичны продакшен-состоянию:
diff -u tests/golden-baseline.yaml rendered-output.yaml
# → Вывод пуст: различий в манифестах нет
```

Благодаря совпадению имен ресурсов (`target-namespace`) и их параметров, применение композиции не вызывает пересоздания существующих ресурсов Kubernetes.

---

## Диагностика и устранение неисправностей

### Сводная матрица типовых неисправностей при обновлении и отrollback

| Симптом | Первопричина | Диагностическая команда | Способ устранения |
| :--- | :--- | :--- | :--- |
| **`ProviderRevision: HEALTHY=False`** | Ошибка скачивания OCI-образа из локального реестра, невалидный сертификат x509 или отсутствие секрета pull | `kubectl describe providerrevision <name>` | Проверить сетевую доступность OCI registry, обновить сертификаты в кластере или добавить `packagePullSecrets` в манифест `Provider`. |
| **`CRDConflict / Cannot establish control`** | Две разные ревизии или два независимых провайдера претендуют на владение одной и той же CRD | `kubectl get providerrevision -o jsonpath='{.items[*].status.conditions[?(@.type=="Healthy")].message}'` | Удалить конфликтующий legacy-пакет, проверить `spec.revisionHistoryLimit` и принудительно очистить устаревшие ревизии. |
| **`CrossplaneConstraintsNotSatisfied`** | Версия ядра Crossplane не удовлетворяет ограничениям, объявленным в пакете (`crossplane.constraints`) | `kubectl describe providerrevision <name> \| grep -A 5 Constraints` | Обновить ядро Crossplane до требуемой версии либо временно установить флаг `spec.ignoreCrossplaneConstraints: true`. |
| **Удаление внешней инфраструктуры при Git Rollback** | При откате коммита удален ресурс, для которого была задана стандартная `deletionPolicy: Delete` | `kubectl get events -n crossplane-system --field-selector reason=Delete` | Настроить `deletionPolicy: Orphan` для всех критичных Managed Resources в шаблонах Composition до отката. |
| **Зависание ProviderRevision в статусе `Terminating`** | Блокировка системным финализатором `lock.pkg.crossplane.io` из-за неудаленных зависимых CRD | `kubectl get providerrevision <name> -o yaml \| grep -A 5 finalizers` | Проверить отсутствие активных управляемых ресурсов этого типа; при подтверждении удалить финализатор через `kubectl patch`. |
| **Деградация etcd и Kube-apiserver OOM** | Накопление сотен неактивных ревизий пакетов и композиций без Garbage Collection | `kubectl get crd \| grep -E 'crossplane\.io\|pkg\.' \| wc -l` | Установить `revisionHistoryLimit: 1` в ресурсах `Provider` и выполнить регламентную очистку мертвых ревизий. |

---

### Подробный разбор типовых инцидентов

#### Инцидент 1: Зависание ревизии провайдера в статусе HEALTHY=False из-за Airgap Registry
**Диагностика:**
```bash
kubectl describe providerrevision provider-kubernetes-9f8e7d6c5b
```
```text
# → Conditions:
# →   Type     Status   Reason                 Message
# →   Healthy  False    UnhealthyPackage       cannot unpack package: cannot fetch package image: Get "https://registry.corp.internal/v2/": x509: certificate signed by unknown authority
```
**Решение:**
1. Экспортировать корневой сертификат корпоративного CA в ConfigMap кластера.
2. Подключить сертификат к поду оператора Crossplane через `DeploymentRuntimeConfig`:
```yaml
apiVersion: pkg.crossplane.io/v1beta1
kind: DeploymentRuntimeConfig
metadata:
  name: custom-ca-runtime
spec:
  deploymentTemplate:
    spec:
      template:
        spec:
          volumes:
            - name: ca-bundle
              configMap:
                name: corporate-root-ca
          containers:
            - name: package-runtime
              volumeMounts:
                - name: ca-bundle
                  mountPath: /etc/ssl/certs/ca-certificates.crt
                  subPath: ca-certificates.crt
```
3. Привязать рантайм к провайдеру:
```bash
kubectl patch provider provider-kubernetes --type=merge -p '{"spec":{"runtimeConfigRef":{"name":"custom-ca-runtime"}}}'
# → provider.pkg.crossplane.io/provider-kubernetes patched
```

---

#### Инцидент 2: Конфликт схем CRD при переходе между мажорными версиями пакетов
**Диагностика:**
```bash
kubectl get providerrevisions
# → NAME                           HEALTHY   REVISION   ACTIVE   PACKAGE
# → provider-helm-3d4e5f           False     2          False    registry.local/provider-helm:v1.0.0
```
```bash
kubectl describe providerrevision provider-helm-3d4e5f
# → Message: cannot establish control of CRD "releases.helm.crossplane.io": CRD already controlled by another revision
```
**Решение:**
1. Убедиться, что старая ревизия деактивирована:
```bash
kubectl get providerrevision -l pkg.crossplane.io/provider=provider-helm
```
2. Если старая ревизия зависла в процессе передачи управления, проверить наличие висячих ресурсов:
```bash
kubectl patch providerrevision provider-helm-1a2b3c --type=merge -p '{"spec":{"desiredState":"Inactive"}}'
# → providerrevision.pkg.crossplane.io/provider-helm-1a2b3c patched
```
3. После освобождения блокировки повторно запросить согласование новой ревизии:
```bash
kubectl patch providerrevision provider-helm-3d4e5f --type=merge -p '{"spec":{"desiredState":"Active"}}'
# → providerrevision.pkg.crossplane.io/provider-helm-3d4e5f patched
```

---

## Лучшие практики

### 1. Операционный SRE-чеклист обновления (Pre-flight, Execution, Post-flight)

#### Этап 1. До обновления (Pre-flight)
- [ ] Проверен журнал изменений (Changelog) и список Breaking Changes релиза ядра Crossplane и обновляемых пакетов.
- [ ] Сформирован полный снимок etcd кластера и бэкап ресурсов Crossplane через Velero (`backup_dr.md`).
- [ ] Проверено, что все критичные Managed Resources имеют `spec.deletionPolicy: Orphan`.
- [ ] Проверено состояние кластера: отсутствуют зависшие поды, контроллеры Crossplane работают без постоянных рестартов (`Restarts=0`).
- [ ] В CI/CD конвейере выполнен оффлайн-прогон обновленных композиций через `crossplane render` со сравнением с эталонными манифестами (Zero-Diff).

#### Этап 2. Выполнение (Execution)
- [ ] Установлен режим ручной активации (`revisionActivationPolicy: Manual`) для критичных провайдеров.
- [ ] Применены актуальные CRD ядра через `kubectl apply --server-side`.
- [ ] Произведен `helm upgrade` ядра с флагами `--wait --timeout 10m`.
- [ ] В случае канареечного релиза композиций: новая ревизия протестирована на пилотном Claim перед глобальным переводом ресурсов.

#### Этап 3. После обновления (Post-flight)
- [ ] Проверен статус контроллеров: `kubectl get pods -n crossplane-system`.
- [ ] Проверен статус ревизий провайдеров: все активные ревизии имеют статус `HEALTHY=True, ACTIVE=True`.
- [ ] Выборочно проверен цикл согласования Managed Resources: отсутствие непрерывного дрейфа и ошибок `Synced=False`.
- [ ] Удалены временные тестовые Claims и ревизии.

---

### 2. Контроль ресурсов и гигиена etcd

Каждая установленная CustomResourceDefinition и каждая `ProviderRevision` создают существенную нагрузку на память `kube-apiserver` и увеличивают размер базы данных `etcd`.
- **Ограничение истории:** в манифестах `Provider`, `Function` и `Configuration` всегда задавать:
  ```yaml
  spec:
    revisionHistoryLimit: 1
  ```
- **Мониторинг объема etcd:** настроить оповещение Prometheus на рост размера etcd при выполнении частых обновлений пакетов.
- **Отказ от неиспользуемых провайдеров:** не развертывать универсальные бандлы, устанавливать только необходимые целевые провайдеры (принцип наименьших привилегий и минимального потребления памяти).

---

### 3. Автоматизированная валидация в CI/CD (Zero-Regress Policy)

Любое изменение в шаблонах композиций должно проходить обязательный этап валидации в репозитории платформы перед слиянием в основную ветку:
```bash
# Пример шага валидации в CI/CD
crossplane render apis/xr-test.yaml compositions/composition.yaml functions/functions.yaml > /tmp/rendered.yaml
crossplane validate /tmp/rendered.yaml
```
Это гарантирует, что сгенерированные манифесты строго соответствуют OpenAPI-схемам целевых версий провайдеров, исключая ситуации, когда новая `CompositionRevision` не может быть применена в кластере из-за синтаксических ошибок в патчах.

---

## Дополнительная информация

### Связанные разделы базы знаний

* [Обзор Crossplane](./overview.md) — фундаментальная архитектура, жизненный цикл и сравнительный анализ.
* [Резервное копирование и Disaster Recovery control plane](./backup_dr.md) — защита etcd, резервное копирование Velero и восстановление при авариях.
* [Защита зависимостей (Usage)](./usage_protection.md) — предотвращение каскадного и случайного удаления инфраструктуры через `protection.crossplane.io/v1beta1`.
* [Тестирование платформы](./testing_crossplane.md) — методология локального рендеринга композиций через `crossplane render` и golden-тесты.
* [Composition Functions и EnvironmentConfig](./composition_functions.md) — разработка и эксплуатация конвейеров функций `mode: Pipeline`.
* [Управление ресурсами Kubernetes (provider-kubernetes)](./provider_kubernetes_setup.md) — Server-Side Apply, работа с ClusterProviderConfig и манифестами `Object`.
* [Безопасность пакетов](./package_security.md) — проверка подписей OCI-образов через Cosign и развертывание в изолированных Airgap-контурах.
* [Observability](./observability.md) — мониторинг метрик контроллеров Crossplane, дашборды Grafana и алерты SRE.
* [Интеграция с GitOps](./gitops_integration.md) — синхронизация пакетов через Argo CD и Flux, управление фазами развертывания.

### Внешняя документация и ресурсы

* Официальное руководство по пакетам и ревизиям: [Crossplane Packages Documentation](https://docs.crossplane.io/latest/concepts/packages/)
* Руководство по установке и обновлению ядра: [Install & Upgrade Crossplane](https://docs.crossplane.io/latest/software/install/)
* Руководство по переходу на Crossplane v2: [Crossplane v2 Migration Guide](https://docs.crossplane.io/latest/guides/v2-migration/)
* Репозиторий ядра Crossplane: [GitHub crossplane/crossplane](https://github.com/crossplane/crossplane)
