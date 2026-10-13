# Crossplane: Защита зависимостей (Usage)

**Актуально для:** Crossplane v1.18+ / v2.x (актуально v2.4); Kubernetes 1.28–1.32+; On-Premise / Bare-Metal

---

## Определения

**Usage (`protection.crossplane.io/v1beta1`)** — декларативный ресурс Kubernetes уровня пространства имён (`Namespace-scoped`), объявляющий формальную связь «ресурс используется другим объектом». Выполняет две ключевые функции:
1. **Защита от непреднамеренного удаления (Deletion Protection):** блокирует удаление критического компонента инфраструктуры до тех пор, пока существует хотя бы один ссылающийся на него потребитель.
2. **Упорядочивание графа удаления (Deletion Ordering):** предотвращает каскадное разрушение зависимостей в распределённой системе, гарантируя, что нижележащие сервисы (базы данных, сетевые фабрики, хранилища) не будут уничтожены раньше высокоуровневых потребителей (микросервисов, ингрессов, релизов).

**ClusterUsage (`protection.crossplane.io/v1beta1`)** — кластерный аналог ресурса `Usage` (`Cluster-scoped`), предназначенный для защиты неизолированных объектов уровня платформы: определений типов (`CompositeResourceDefinition`), управляющих пакетов (`Provider`, `Function`), глобальных конфигураций провайдеров (`ClusterProviderConfig`, `ProviderConfig`) и общих инфраструктурных сервисов.

**Защищаемый ресурс (`spec.of`)** — целевой объект (Target), на который накладывается запрет на физическое и логическое удаление. Поддерживает ссылки на любые стандартные ресурсы Kubernetes (`apps/v1`, `core/v1`), управляемые ресурсы Crossplane (`Managed Resources`), композитные ресурсы (`Composite Resources`, `XR`) и пользовательские CRD.

**Использующий ресурс (`spec.by`)** — ресурс-потребитель (Consumer), существование которого обуславливает необходимость сохранения защищаемого объекта. Пока ресурс `spec.by` присутствует в etcd и не завершил процесс удаления, защищаемый ресурс `spec.of` не может быть финализирован.

**Административная блокировка (Administrative Lock / Unconditional Protection)** — режим конфигурации манифеста `Usage` или `ClusterUsage`, при котором поле `spec.by` намеренно опущено. Целевой ресурс `spec.of` защищается безусловно до момента явного удаления самого манифеста `Usage` администратором платформы.

**Replay Deletion (`spec.replayDeletion: true`)** — механизм отложенного повторения операции удаления: если на защищаемый ресурс уже поступил запрос на удаление (выставлен `metadata.deletionTimestamp`), контроллер Crossplane после окончательного удаления использующего ресурса `spec.by` автоматически завершает процедуру снятия блокировок и инициирует удаление `spec.of` без повторного ручного вызова со стороны оператора или CI/CD.

**Usage Finalizer (`protection.crossplane.io/usage-protection`)** — системный финализатор Kubernetes, автоматически инжектируемый контроллером Crossplane в метаданные ресурса `spec.of` при регистрации действующей блокировки.

**Foreground Composite Deletion Policy (`spec.defaultCompositeDeletePolicy: Foreground`)** — директива спецификации `CompositeResourceDefinition` (XRD), предписывающая API-серверу блокировать удаление родительского композитного ресурса (`XR`), пока все дочерние ресурсы и их взаимные блокировки `Usage` не будут полностью удалены.

---

## Базовые концепции и архитектура

### Механизм работы контроллера Usage и финализаторы

В архитектуре Crossplane механизм защиты строится на базе стандартных примитивов Kubernetes API Server — финализаторов (`finalizers`) и механизма разрешения связей. Ядро Crossplane содержит специализированный `Usage Controller`, запуск которого регулируется параметром `--enable-usages` (активирован по умолчанию в ветках v1.17+ и v2.x).

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                 Kubernetes Control Plane                               │
│                                                                                        │
│   ┌─────────────────────┐               ┌──────────────────────────────────────────┐   │
│   │   spec.by Resource  │               │             spec.of Resource             │   │
│   │   (apps/v1 Deploy)  │               │   (postgresql.sql.crossplane.io/v1alpha1)│   │
│   └──────────┬──────────┘               └────────────────────┬─────────────────────┘   │
│              │                                               │                         │
│              │ Активен в etcd                                │ metadata.finalizers:    │
│              │                                               │ - protection.crossplane │
│              │                                               │   .io/usage-protection  │
│              ▼                                               ▼                         │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                       Crossplane Usage Controller                              │   │
│   │                                                                                │   │
│   │ 1. Отслеживает ресурс Usage (protection.crossplane.io/v1beta1)                 │   │
│   │ 2. Удерживает finalizer на spec.of, пока жив spec.by                          │   │
│   │ 3. При удалении spec.by -> снимает finalizer со spec.of                        │   │
│   │ 4. Если spec.replayDeletion: true -> форсирует удаление spec.of                │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### Порядок реконсиляции:

1. **Регистрация блокировки:** При создании ресурса `Usage` контроллер валидирует наличие ресурсов, указанных в `spec.of` и `spec.by`.
2. **Инжекция финализатора:** Контроллер выполняет PATCH-запрос к объекту `spec.of`, добавляя финализатор:
   ```yaml
   metadata:
     finalizers:
       - protection.crossplane.io/usage-protection
   ```
3. **Попытка удаления защищаемого ресурса:** Если пользователь или пайплайн пытается удалить `spec.of` (`kubectl delete ...`), API Server выставляет в метаданных ресурса метку времени `metadata.deletionTimestamp`. Ресурс переходит в статус `Terminating`.
4. **Блокировка Garbage Collection:** Garbage Collector Kubernetes не может удалить запись объекта из etcd, так как в списке финализаторов остаётся `protection.crossplane.io/usage-protection`.
5. **Очистка зависимости:** Пользователь удаляет ресурс `spec.by`. Как только `spec.by` полностью исчезает из API-сервера (завершает все собственные финализаторы), контроллер `Usage` фиксирует исчезновение потребителя.
6. **Снятие финализатора и финализация:** Контроллер удаляет `protection.crossplane.io/usage-protection` из объекта `spec.of`. Ресурс удаляется стандартными средствами платформы.

### Жизненный цикл блокировки и режим Replay Deletion

Флаг `spec.replayDeletion: true` решает критическую проблему асинхронного удаления в GitOps и контроллерах.

- **Поведение по умолчанию (`replayDeletion: false`):** Если ресурс `spec.of` получил `deletionTimestamp`, но был заблокирован `Usage`, после удаления `spec.by` финализатор `usage-protection` снимается. Однако, если за время ожидания процесс реконсиляции прервался, объект может остаться в подвисшем состоянии до следующего триггера контроллера.
- **Поведение при `replayDeletion: true`:** Контроллер `Usage` гарантирует, что как только `spec.by` удалён, запрос на удаление `spec.of` будет повторно отправлен в Kubernetes API Server. Это обеспечивает детерминированную сквозную очистку всей цепочки инфраструктуры при удалении родительского окружения.

### Сравнение механизмов защиты ресурсов в Kubernetes и Crossplane

В средах On-Premise и Bare-Metal для обеспечения сохранности данных и стабильности топологии применяются несколько уровней защиты:

| Параметр | Usage API (`protection.crossplane.io`) | `deletionPolicy: Orphan` | ValidatingAdmissionPolicy (CEL) | Ручные Finalizers |
|---|---|---|---|---|
| **Уровень работы** | Crossplane Core Controller | Движок провайдеров Crossplane | Kube-apiserver (In-Tree Admission) | Внешние скрипты / Operators |
| **Осведомленность о связях** | **Высокая:** динамически связывает разнородные ресурсы | **Низкая:** статическое правило для одного ресурса | **Средняя:** требует сложных проверок по etcd | **Низкая:** требует ручного управления |
| **Реакция на `kubectl delete`** | Переводит в `Terminating`, удерживает финализатор | Удаляет объект K8s, сохраняет физический ресурс | Отклоняет запрос на уровне HTTP (Reject) | Переводит в `Terminating` |
| **Упорядочивание удаления** | **Да:** освобождает ресурс строго после потребителя | Нет (просто оставляет сироту) | Нет (только бинарный запрет) | Требует внешнего оркестратора |
| **Поддержка внутри Compositions** | Полная (декларативная генерация) | Полная (в манифесте MR) | Ограниченная (только валидация) | Сложная интеграция |

### Взаимодействие с CompositeResourceDefinition и Composition

Критическая архитектурная особенность связки `Usage` и композитных ресурсов (`XR`):

- **По умолчанию в XRD:** параметр `spec.defaultCompositeDeletePolicy` имеет значение `Background`.
- **Проблема при `Background`:** При удалении родительского XR Kubernetes инициирует фоновое удаление всех дочерних ресурсов одновременно. Если в композиции объявлен `Usage`, где `spec.by` — это сам XR, а `spec.of` — дочерний ресурс (например, база данных), при политике `Background` объект XR удалится первым. Это снимет блокировку `Usage` до того, как завершатся зависимые процессы, что приведет к нарушению порядка депровижининга.
- **Решение платформенного уровня:** Для всех XRD, управляющих критическими компонентами, **обязательно** задавать политику каскадного удаления `Foreground`:
  ```yaml
  apiVersion: apiextensions.crossplane.io/v1
  kind: CompositeResourceDefinition
  metadata:
    name: xpostgresqlservices.platform.internal
  spec:
    group: platform.internal
    names:
      kind: XPostgreSQLService
      plural: xpostgresqlservices
    defaultCompositeDeletePolicy: Foreground
  ```
  В режиме `Foreground` родительский XR получает финализатор `foregroundDeletion` и физически не удаляется из etcd, пока живы его дочерние объекты и активны блокировки `Usage`.

---

## Практические сценарии

### 1. Защита On-Premise базы данных PostgreSQL от удаления активным приложением

**Контекст:** В инфраструктуре Bare-Metal развернута база данных через локальный оператор (`provider-sql` или внутренний DBaaS). Микросервис биллинга работает в поде Kubernetes (`Deployment`). Случайное выполнение `kubectl delete database billing-db` должно быть заблокировано до тех пор, пока приложение не будет остановлено или удалено.

```yaml
apiVersion: protection.crossplane.io/v1beta1
kind: Usage
metadata:
  name: billing-app-uses-postgres
  namespace: billing-system
spec:
  of:
    apiVersion: postgresql.sql.crossplane.io/v1alpha1
    kind: Database
    resourceRef:
      name: billing-production-db
  by:
    apiVersion: apps/v1
    kind: Deployment
    resourceRef:
      name: billing-api-server
  reason: "База данных биллинга находится под нагрузкой. Удаление запрещено, пока существует Deployment billing-api-server"
  replayDeletion: false
```

#### Проверка блокировки в терминале:

```bash
# Попытка удалить базу данных при работающем приложении
kubectl delete database billing-production-db -n billing-system
# → database.postgresql.sql.crossplane.io "billing-production-db" deleted
# (Команда возвращает управление, но ресурс переходит в статус блокировки)

kubectl get database billing-production-db -n billing-system
# → NAME                    READY   SYNCED   AGE   DELETIONTIMESTAMP
# → billing-production-db   True    True     45d   2026-10-13T16:15:30Z

kubectl get usage billing-app-uses-postgres -n billing-system
# → NAME                        IN-USE   REASON                                                 AGE
# → billing-app-uses-postgres   True     База данных биллинга находится под нагрузкой...        12m
```

### 2. Упорядочивание удаления инфраструктуры через replayDeletion

**Контекст:** Инженерная платформа развертывает виртуальный изолированный кластер (`vcluster`) для команды разработки, а поверх него через `provider-helm` устанавливает инфраструктурные агенты (Prometheus Node Exporter, Fluentbit). При удалении проекта виртуальный кластер не должен удалиться раньше, чем удалятся Helm-релизы. После удаления релизов кластер должен удалиться автоматически.

```yaml
apiVersion: protection.crossplane.io/v1beta1
kind: Usage
metadata:
  name: helm-release-uses-vcluster
  namespace: tenant-sandbox
spec:
  of:
    apiVersion: kubernetes.m.crossplane.io/v1alpha1
    kind: Object
    resourceRef:
      name: sandbox-vcluster-controlplane
  by:
    apiVersion: helm.m.crossplane.io/v1beta1
    kind: Release
    resourceRef:
      name: tenant-monitoring-stack
  reason: "Не удалять управляющий контур vcluster до завершения деинсталляции Helm-релиза мониторинга"
  replayDeletion: true
```

#### Механика отработки `replayDeletion: true`:
1. Оператор запускает депровижининг всего пространства имён `tenant-sandbox`.
2. Ресурс `sandbox-vcluster-controlplane` получает `deletionTimestamp`, но его финализатор удерживается контроллером `Usage`.
3. `provider-helm` выполняет штатный `helm uninstall` для `tenant-monitoring-stack`.
4. После исчезновения релиза `tenant-monitoring-stack` контроллер Crossplane фиксирует снятие зависимости `spec.by`, убирает финализатор `protection.crossplane.io/usage-protection` и автоматически финализирует удаление `sandbox-vcluster-controlplane` без повторного вмешательства инженера.

### 3. Защита системных компонентов платформы через ClusterUsage (Administrative Lock)

**Контекст:** Администратор платформы развернул системный пакет `provider-kubernetes` и глобальный профиль подключения к физическому кластеру Bare-Metal. Случайное удаление пакета провайдера нарушит реконсиляцию сотен ресурсов. Опускание блока `spec.by` превращает `ClusterUsage` в постоянный административный замок.

```yaml
apiVersion: protection.crossplane.io/v1beta1
kind: ClusterUsage
metadata:
  name: protect-core-provider-kubernetes
spec:
  of:
    apiVersion: pkg.crossplane.io/v1
    kind: Provider
    resourceRef:
      name: provider-kubernetes
  reason: "Критический системный провайдер. Для удаления требуется сначала снять данный ClusterUsage манифест"
```

#### Попытка несанкционированного удаления:

```bash
kubectl delete provider provider-kubernetes
# → provider.pkg.crossplane.io "provider-kubernetes" deletion scheduled, waiting for finalizers...

kubectl get provider provider-kubernetes -o jsonpath='{.metadata.finalizers}'
# → ["protection.crossplane.io/usage-protection"]
```

### 4. Декларативная защита ресурсов внутри Composition Functions

**Контекст:** В On-Premise платформе разработчик заказывает композитный сервис `ApplicationStack`. Внутри Composition создаются:
- Общий пул дискового пространства Ceph (`LocalPool`).
- StatefulSet базы данных.
- Deployment веб-сервиса.

Через конвейер функций композиции (`function-patch-and-transform`) платформа автоматически генерирует манифест `Usage`, привязывающий диск к базе данных, исключая случайную отстыковку хранилища.

```yaml
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: app-stack.platform.internal
spec:
  compositeTypeRef:
    apiVersion: platform.internal/v1alpha1
    kind: XApplicationStack
  mode: Pipeline
  pipeline:
    - step: generate-resources
      functionRef:
        name: function-patch-and-transform
      input:
        apiVersion: pt.fn.crossplane.io/v1beta1
        kind: Resources
        resources:
          - name: storage-protection
            base:
              apiVersion: protection.crossplane.io/v1beta1
              kind: Usage
              spec:
                of:
                  apiVersion: storage.k8s.io/v1
                  kind: PersistentVolumeClaim
                  resourceRef:
                    name: shared-data-pvc
                by:
                  apiVersion: apps/v1
                  kind: StatefulSet
                  resourceRef:
                    name: backend-statefulset
                reason: "Дисковый том PVC заблокирован от удаления, пока работает StatefulSet"
                replayDeletion: true
            patches:
              - type: FromCompositeFieldPath
                fromFieldPath: metadata.namespace
                toFieldPath: metadata.namespace
```

### 5. Динамическое связывание ресурсов через метки и контроллеры

**Контекст:** Имена ресурсов генерируются динамически с рандомными суффиксами (например, `db-backend-7f8d9b`). Использование статического `resourceRef.name` в манифестах невозможно. Используются селекторы `resourceSelector`.

```yaml
apiVersion: protection.crossplane.io/v1beta1
kind: Usage
metadata:
  name: dynamic-cache-protection
  namespace: analytics-prod
spec:
  of:
    apiVersion: kubernetes.m.crossplane.io/v1alpha1
    kind: Object
    resourceSelector:
      matchLabels:
        infrastructure.internal/role: in-memory-cache
        environment: production
  by:
    apiVersion: apps/v1
    kind: Deployment
    resourceSelector:
      matchLabels:
        app.kubernetes.io/component: data-processor
  reason: "Кэш Redis не может быть удален, пока запущены обработчики данных"
  replayDeletion: true
```

---

## Операции и команды

### Инспекция и фильтрация блокировок

```bash
# Получение списка всех namespaced-блокировок во всех пространствах имён
kubectl get usage -A
# → NAMESPACE       NAME                        OF-KIND    OF-NAME            BY-KIND      BY-NAME            REPLAY   AGE
# → billing-system  billing-app-uses-postgres   Database   billing-prod-db    Deployment   billing-api        false    2d
# → tenant-sandbox  helm-uses-vcluster          Object     sandbox-vcluster   Release      tenant-monitoring  true     4h

# Получение списка глобальных кластерных блокировок
kubectl get clusterusage
# → NAME                               OF-KIND    OF-NAME               BY-KIND   BY-NAME   REPLAY   AGE
# → protect-core-provider-kubernetes   Provider   provider-kubernetes   <none>    <none>    false    14d

# Просмотр детального статуса блокировки и причины
kubectl describe usage billing-app-uses-postgres -n billing-system
# → Name:         billing-app-uses-postgres
# → Namespace:    billing-system
# → Labels:       <none>
# → API Version:  protection.crossplane.io/v1beta1
# → Kind:         Usage
# → Spec:
# →   Of:
# →     Api Version:  postgresql.sql.crossplane.io/v1alpha1
# →     Kind:         Database
# →     Resource Ref:
# →       Name:       billing-production-db
# →   By:
# →     Api Version:  apps/v1
# →     Kind:         Deployment
# →     Resource Ref:
# →       Name:       billing-api-server
# →   Reason:         База данных биллинга находится под нагрузкой.
# →   Replay Deletion: false
# → Events:           <none>
```

### Проверка инжектированных финализаторов на управляемых ресурсах

```bash
# Проверка наличия системного финализатора на целевом ресурсе
kubectl get database billing-production-db -n billing-system -o jsonpath='{.metadata.finalizers}'
# → ["protection.crossplane.io/usage-protection"]

# Проверка ресурсов, зависших в состоянии Terminating из-за блокировки Usage
kubectl get database -A -o jsonpath='{range .items[?(@.metadata.deletionTimestamp != "")]}{.metadata.namespace}{"/"}{.metadata.name}{" | finalizers: "}{.metadata.finalizers}{"\n"}{end}'
# → billing-system/billing-production-db | finalizers: ["protection.crossplane.io/usage-protection"]
```

### Экстренная разблокировка (Break-Glass Runbook)

В случае аварийных ситуаций (удаление ресурса `spec.by` с обходом API, сбой etcd, повреждение контроллера Crossplane), когда ресурс навечно заблокирован в `Terminating`:

```bash
# Шаг 1: Удаление самого ресурса Usage (штатный метод)
kubectl delete usage billing-app-uses-postgres -n billing-system --timeout=10s
# → usage.protection.crossplane.io "billing-app-uses-postgres" deleted

# Шаг 2: Если контроллер не отвечает — аварийное снятие финализатора с защищаемого ресурса
kubectl patch database billing-production-db -n billing-system --type=json -p='[{"op": "remove", "path": "/metadata/finalizers"}]'
# → database.postgresql.sql.crossplane.io/billing-production-db patched
```

---

## Устранение неполадок

### 1. Ресурс зависает в статусе Terminating из-за финализатора usage-protection

- **Симптом:** Администратор или GitOps-оператор выполнил удаление ресурса (`kubectl delete`), команда зависла или завершилась, но объект остается в кластере со статусом `Terminating`.
- **Причина:** На объект ссылается ресурс `Usage`, и использующий компонент (`spec.by`) все еще функционирует.
- **Диагностика:**
  ```bash
  # 1. Проверяем наличие финализатора
  kubectl get database billing-production-db -n billing-system -o yaml | grep "protection.crossplane.io/usage-protection"
  # → - protection.crossplane.io/usage-protection

  # 2. Ищем, какой именно Usage блокирует данный ресурс
  kubectl get usage -n billing-system -o jsonpath='{range .items[?(@.spec.of.resourceRef.name=="billing-production-db")]}{.metadata.name}{" -> used by: "}{.spec.by.kind}{"/"}{.spec.by.resourceRef.name}{"\n"}{end}'
  # → billing-app-uses-postgres -> used by: Deployment/billing-api-server
  ```
- **Решение:**
  1. Корректный путь: сначала остановить или удалить сервис-потребитель:
     ```bash
     kubectl delete deployment billing-api-server -n billing-system
     # → deployment.apps "billing-api-server" deleted
     ```
  2. После завершения деинсталляции `Deployment` контроллер Crossplane автоматически удалит финализатор, и `Database` завершит удаление.

### 2. Взаимная блокировка (Deadlock) при циклическом графе зависимостей

- **Симптом:** Ни один из связанных ресурсов не может быть удален; оба ресурса зависают в статусе `Terminating`.
- **Причина:** Ошибка проектирования архитектуры: ресурс A блокирует ресурс B через `Usage-1`, а ресурс B блокирует ресурс A через `Usage-2`. При попытке совместного удаления возникает классический Deadlock.
- **Диагностика:**
  ```bash
  # Проверка взаимных ссылок в namespace
  kubectl get usage -n billing-system -o custom-columns=NAME:.metadata.name,OF:.spec.of.resourceRef.name,BY:.spec.by.resourceRef.name
  # → NAME      OF       BY
  # → lock-ab   res-b    res-a
  # → lock-ba   res-a    res-b
  ```
- **Решение:**
  1. Принудительно разорвать петлю взаимной блокировки, удалив один из манифестов `Usage`:
     ```bash
     kubectl delete usage lock-ba -n billing-system
     # → usage.protection.crossplane.io "lock-ba" deleted
     ```
  2. Дождаться штатного удаления первого ресурса, после чего второй ресурс разблокируется автоматически.

### 3. Ресурс spec.by удален, но блокировка не снимается контроллером

- **Симптом:** Ресурс `spec.by` уже физически отсутствует в etcd (`NotFound`), но целевой объект `spec.of` продолжает удерживать финализатор `usage-protection`.
- **Причина:**
  1. Контроллер Crossplane не запущен или аварийно завершил работу (CrashLoopBackOff).
  2. Флаг `--enable-usages=false` был передан в аргументы pod `crossplane`.
  3. Недостаточно прав RBAC у ServiceAccount контроллера для снятия финализаторов с целевого типа CRD.
- **Диагностика:**
  ```bash
  # 1. Проверка статуса подов ядра Crossplane
  kubectl get pods -n crossplane-system -l app=crossplane
  # → NAME                          READY   STATUS    RESTARTS   AGE
  # → crossplane-7f64bf7589-k2m9p   1/1     Running   0          5d

  # 2. Анализ логов контроллера на предмет ошибок реконсиляции Usage
  kubectl logs -n crossplane-system -l app=crossplane --tail=200 | grep -i "usage"
  # → 2026-10-13T16:22:10Z ERROR cannot remove finalizer {"controller": "usage", "error": "databases.postgresql.sql.crossplane.io is forbidden"}
  ```
- **Решение:**
  1. При ошибках прав доступа — выдать необходимые `ClusterRole` сервисному аккаунту Crossplane (`crossplane-system:crossplane`).
  2. При зависании контроллера перезапустить под:
     ```bash
     kubectl rollout restart deployment crossplane -n crossplane-system
     # → deployment.apps/crossplane restarted
     ```

### 4. Ошибка разрешения селектора (ResourceNotFound / AmbiguousMatch)

- **Симптом:** Манифест `Usage` создан, но финализатор не появляется на целевом ресурсе. В статусе `Usage` отсутствуют подтверждения привязки.
- **Причина:** Ошибка в метках `matchLabels` в блоке `resourceSelector` — под селектор не подходит ни один ресурс, либо селектор возвращает более одного кандидата без детерминированного выбора.
- **Диагностика:**
  ```bash
  # Проверка селектора вручную
  kubectl get database -n billing-system -l infrastructure.internal/role=in-memory-cache
  # → No resources found in billing-system namespace.
  ```
- **Решение:** Исправить метки в манифесте `Usage` либо перейти на детерминированную адресацию через `resourceRef.name`.

### 5. Дочерние ресурсы удаляются раньше времени при удалении XR

- **Симптом:** При удалении Composite Resource (`XR`) или Claim удаляется общая сеть или том данных, несмотря на наличие блокировок `Usage`.
- **Причина:** В определении `CompositeResourceDefinition` (XRD) установлена политика по умолчанию `defaultCompositeDeletePolicy: Background`.
- **Решение:** Внести исправление в манифест XRD, переключив политику на `Foreground`:
  ```bash
  kubectl patch xrd xapplicationstacks.platform.internal --type=merge -p '{"spec":{"defaultCompositeDeletePolicy":"Foreground"}}'
  # → compositeresourcedefinition.apiextensions.crossplane.io/xapplicationstacks.platform.internal patched
  ```

---

## Лучшие практики

### Архитектурные шаблоны SRE и сохранность данных

1. **Комбинация с `deletionPolicy: Orphan` для баз данных и хранилищ:**
   Для критических данных (Ceph RBD, Local PV, кластеры PostgreSQL, очереди Kafka) механизм `Usage` должен служить первым эшелоном обороны от человеческой ошибки. Вторым эшелоном всегда выступает директива `spec.deletionPolicy: Orphan` на уровне самого управляемого ресурса (Managed Resource). Даже если блокировка `Usage` будет принудительно снята администратором, физические данные на дисках останутся нетронутыми.
2. **Исключение циклических зависимостей в архитектуре:**
   Запрещено связывать ресурсы взаимными ссылками на одном уровне иерархии. Граф зависимостей `Usage` обязан быть строго направленным ациклическим графом (DAG):
   `Workload (App) ──► Database / Cache ──► Storage / Network Fabric`.
3. **Обязательное использование `Foreground` удаления для XRD:**
   Любой композитный ресурс, инкапсулирующий несколько взаимозависимых объектов, обязан определять `defaultCompositeDeletePolicy: Foreground`.

### Ролевая модель (RBAC) и предотвращение несанкционированного снятия защиты

В многопользовательских кластерах разработчики (тенанты) не должны иметь возможности самостоятельно удалить блокирующий `Usage` для обхода ограничений платформы:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: platform:tenant-developer-restricted
rules:
  # Разработчик может просматривать зависимости
  - apiGroups: ["protection.crossplane.io"]
    resources: ["usages"]
    verbs: ["get", "list", "watch"]
  # Удаление и создание Usage разрешено только платформенному контроллеру и SRE
  - apiGroups: ["protection.crossplane.io"]
    resources: ["clusterusages"]
    verbs: ["get", "list", "watch"]
```

### Интеграция с GitOps (Argo CD и Flux)

При декларативном управлении инфраструктурой через GitOps удаление приложений и инфраструктуры происходит через удаление файлов из Git-репозитория.

1. **Синхронизация волн удаления (Sync Waves / Hooks):**
   При каскадном удалении Argo CD удаляет ресурсы согласно `argocd.argoproj.io/sync-wave`. Назначайте потребителям (`spec.by`, например `Deployment`) более поздние волны при создании и ранние при удалении (через PreDelete hook), чтобы приложение удалялось до того, как GitOps попытается удалить базу данных.
2. **Предотвращение бесконечной деградации Argo CD Sync:**
   Если ресурс `spec.of` заблокирован `Usage`, попытка Argo CD удалить его переведет приложение в статус `SyncFailed` / `Prune Failed`. Для предотвращения зависания пайплайна используйте аннотацию:
   ```yaml
   metadata:
     annotations:
       argocd.argoproj.io/sync-options: Delete=false
   ```
   на критических базах данных, требуя явного снятия защиты перед депровижинингом.

### Мониторинг, метрики и алертинг

Для обеспечения прозрачности состояния блокировок экспортируйте метрики реконсиляции Crossplane в локальный Prometheus:

- **Метрика ошибок финализации:**
  `crossplane_reconcile_errors_total{controller="usage"} > 0`
- **Алертинг на зависшие блокировки:**
  Оповещение SRE-дежурного, если ресурс находится в состоянии `Terminating` с финализатором `usage-protection` более 30 минут:
  ```yaml
  - alert: CrossplaneResourceStuckInUsageProtection
    expr: |
      sum by (namespace, name) (
        kube_customresource_status_condition{condition="Ready", status="Unknown"}
        * on (namespace, name) group_left()
        (time() - kube_customresource_created > 1800)
      ) > 0
    for: 15m
    labels:
      severity: warning
    annotations:
      summary: "Ресурс {{ $labels.namespace }}/{{ $labels.name }} заблокирован финализатором usage-protection более 30 минут"
      description: "Проверьте зависшие зависимости и активные манифесты Usage в пространстве имён."
  ```

---

## Дополнительная информация

Внутренние связанные разделы базы знаний:
- [Обзор Crossplane](./overview.md) — базовые концепции плоскости управления, Managed Resources и провайдеров.
- [Мультитенантность и изоляция](./multi_tenancy.md) — разграничение прав доступа, soft/hard multitenancy и паттерн Owner Only Orphan.
- [Политики и Governance](./policy_governance.md) — многоуровневое управление и сравнение Usage API с ValidatingAdmissionPolicy / Kyverno.
- [Обновление и миграция](./upgrade_migration.md) — стратегии обновления управляющих компонентов, миграция XRD и сохранение данных.
- [Composition Functions](./composition_functions.md) — генерация манифестов инфраструктуры через конвейер функций.
- [Интеграция с GitOps](./gitops_integration.md) — шаблоны синхронизации, Argo CD Sync Waves и предотвращение дедлоков удаления.
- [Самообслуживание и каталоги сервисов](./self_service.md) — проектирование безопасных пользовательских Claim и жизненный цикл Day-2.

Внешняя документация:
- [Crossplane Usages Documentation](https://docs.crossplane.io/latest/managed-resources/usages/)
- [Kubernetes Finalizers Architecture](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/)
