# Argo CD — игнорирование различий и принудительная синхронизация

**Актуально для:** Argo CD v3.5.x / master. Версионные отличия: `managedFieldsManagers` — с v2.3 (PR #7869, декабрь 2021); server-side diff (`--server-side-diff`, `compare-options: ServerSideDiff=true`) — с v3.5.

## Предварительные требования

Перед настройкой `ignoreDifferences` необходимо убедиться в следующем:

1. **Версия Argo CD:** `ignoreDifferences` с `jsonPointers`/`jqPathExpressions` доступен во всех актуальных версиях; `managedFieldsManagers` — с v2.3; server-side diff — с v3.5.
2. **Доступ к кластеру:** у приложения Argo CD есть права на чтение ресурсов (`get`, `list`, `watch`) — без них diff не строится.
3. **Определён источник изменений:** нужно знать, какой контроллер или мутирующий вебхук меняет ресурс (HPA, cert-manager, сервисный меш, оператор) и как он записывается в `metadata.managedFields`.
4. **Понимание причины `OutOfSync`:** типичные причины (см. раздел «Базовые концепции») — лишние поля, удаляемые ресурсы, мутации вебхуков, нестабильный рендер Helm, переупорядочивание полей контроллером. Игнорирование применяется только когда причину нельзя исправить в Git.

## Определения

**Игнорирование различий (Ignore Differences)** — механизм Argo CD, исключающий конкретные поля или группы полей ресурсов из процесса сравнения (diffing). Предотвращает ложные срабатывания статуса `OutOfSync` для полей, которые изменяются внешними контроллерами или мутирующими вебхуками.

**Принудительная синхронизация (Force Sync)** — режим синхронизации, при котором Argo CD удаляет и пересоздаёт ресурс (sync option `Force=true`, аналог `kubectl delete` + `create`). Применяется, когда обычное обновление (apply/patch) некорректно применяется к ресурсу с неизменяемыми полями.

**managedFieldsManagers** — метод игнорирования по владельцу поля: Argo CD исключает из diff все поля, которыми в `metadata.managedFields` live-ресурса владеет указанный менеджер. Метод основан на механизме field management Kubernetes, который отслеживает, какой актор (controller, operator, пользователь) управляет каждым полем ресурса.

**Server-Side Diff** — режим вычисления diff (v3.5+), при котором желаемое состояние применяется к kube-apiserver в dry-run режиме, и diff считается по результату применения. Учитывает defaulting и работу мутирующих вебхуков API-сервера.

**RespectIgnoreDifferences** — sync option (default `false`), заставляющий Argo CD учитывать `ignoreDifferences` не только при вычислении diff, но и при применении состояния во время синхронизации.

## Базовые концепции

### Почему ресурс может быть OutOfSync

Официальная документация выделяет пять причин, которые невозможно исправить в Git и для которых предназначено игнорирование:

1. **Лишние/неизвестные поля** в манифесте: API-сервер отбрасывает их при чтении live-состояния, и diff показывает «отсутствующее» поле.
2. **Ресурсы, требующие удаления**, при отключённом pruning.
3. **Мутирующий вебхук** изменяет объект после его создания (инъекция sidecar, подпись `caBundle`).
4. **Нестабильный рендер Helm**: шаблонные функции вроде `randAlphaNum` генерируют разные данные при каждом `helm template`.
5. **Переупорядочивание полей контроллером**: HPA-контроллер переупорядочивает `spec.metrics` в определённом порядке (kubernetes issue #74099). Обход: упорядочить `spec.metrics` в Git так, как предпочитает контроллер.

### Методы идентификации полей

Argo CD предлагает три способа указания исключаемых полей (можно комбинировать в одном правиле):

1. **managedFieldsManagers** — опирается на *кто* изменил поле. Автоматически покрывает все поля указанного менеджера без перечисления путей. Ограничение: требует, чтобы мутирующий актор записывался в `managedFields` под ожидаемым именем менеджера.
2. **jqPathExpressions** — JQ-выражения, позволяют выбирать элементы списков по содержимому (например, контейнер с конкретным именем в массиве `containers`). Argo CD оборачивает выражение в `del(...)` и удаляет выбранные узлы.
3. **jsonPointers** — пути по RFC 6901 (например, `/spec/replicas`), применяются как JSON Patch `remove` (RFC 6902). Простой и предсказуемый метод для фиксированных полей.

| Сценарий | Рекомендуемый метод | Причина |
| :--- | :--- | :--- |
| Контроллер масштабабирования (HPA) | `managedFieldsManagers` | Документированный паттерн для `kube-controller-manager` |
| Сервисный меш (Istio, Linkerd) | `jqPathExpressions` | Sidecar добавляется динамически в массив контейнеров |
| Фиксированное поле (`replicas`, аннотация) | `jsonPointers` | Простой путь, не зависит от структуры |
| Политика мутации (Kyverno, OPA) | `managedFieldsManagers` или `jqPathExpressions` | Зависит от того, как контроллер записывает мутации |

**Группа и тип ресурса:** `group` — имя Kubernetes API-группы без версии (пустая строка или `""` для core-группы); `kind` — тип ресурса. Группа и тип сопоставляются как glob-выражения, поэтому поддерживаются шаблоны: `group: '*'`, `kind: '*'`. Правило можно сузить до конкретного ресурса полями `name` и `namespace`.

**Экранирование:** символ `/` в имени поля (например, в аннотации `node-role.kubernetes.io/worker`) кодируется как `~1`: `/metadata/labels/node-role.kubernetes.io~1worker`.

### Уровни конфигурации и их взаимодействие

- **Локальный (Application level):** правила в секции `spec.ignoreDifferences` манифеста `Application`. Применяются только к данному приложению.
- **Глобальный (System level):** ключи `resource.customizations.ignoreDifferences.<group>_<kind>` и `resource.customizations.ignoreDifferences.all` в ConfigMap `argocd-cm`. Применяются ко всем приложениям экземпляра Argo CD.

**Взаимодействие:** уровни **объединяются (union), а не переопределяют друг друга**. Системные правила добавляются к правилам приложения, и оба набора применяются при нормализации diff (реализация: `NewIgnoreNormalizer` в `util/argo/normalizers/diff_normalizer.go` добавляет системные правила в список приложения). Локальное правило не отключает и не заменяет глобальное — если оба уровня задают пути для одного Group/Kind, исключаются оба набора полей.

### Статус diff по умолчанию и `resource.compareoptions`

Поле `status` большинства ресурсов **не участвует в diff по умолчанию**: ключ `resource.compareoptions` в `argocd-cm` поддерживает параметр `ignoreResourceStatusField` со значениями `crd` (только CustomResourceDefinition), `all` (все ресурсы — **default**) и `none` (выключено). Если состояние `status` намеренно используется как часть желаемого конфига (не рекомендуется), поведение меняется через этот ключ; документация рекомендует `crd` вместо `none`, поскольку `status` CRD часто коммитится в Git.

Там же задаётся `ignoreAggregatedRoles: true` — игнорировать изменения `rules`, вызванные Aggregated ClusterRoles (RBAC-агрегация).

### Параметр RespectIgnoreDifferences

По умолчанию `ignoreDifferences` влияет **только на вычисление diff** (и, соответственно, на статус `Synced`/`OutOfSync`). На этапе синхронизации желаемое состояние применяется как есть: patch строится трёхсторонним слиянием live-состояния, желаемого состояния и аннотации `kubectl.kubernetes.io/last-applied-configuration`, что может вернуть игнорируемое поле к значению из Git.

Чтобы Argo CD **не перезаписывал** игнорируемые поля при автоматической или ручной синхронизации, устанавливается sync option `RespectIgnoreDifferences=true` (default `false`).

### Взаимодействие с Server-Side Apply (SSA)

При использовании SSA (sync option `ServerSideApply=true`) каждый контроллер, мутирующий ресурс, получает идентификатор менеджера в `metadata.managedFields`, что делает `managedFieldsManagers` предсказуемым.

Однако `managedFields` заполняются при **любой** записи через API-сервер (начиная с Kubernetes 1.16), а не только при SSA: при client-side apply менеджером выступает клиент (например, `kubectl-client-side-apply`), при обновлениях контроллером — имя его field manager. Поэтому `managedFieldsManagers` работает и без SSA — при условии, что мутирующий актор записывается в `managedFields` под известным именем. SSA лишь делает имена менеджеров стабильными и явными.

**Рекомендация:** для новых приложений `ServerSideApply=true` в `syncOptions` обеспечивает корректное разделение полей между контроллерами и предсказуемое поведение `managedFieldsManagers`.

## Практические сценарии

### Сценарий 1: Совместная работа с HPA

HPA-контроллер (компонент `kube-controller-manager`) управляет `spec.replicas` Deployment. Правило по менеджеру полей покрывает все поля, которыми владеет `kube-controller-manager`:

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    managedFieldsManagers:
    - kube-controller-manager
  syncPolicy:
    syncOptions:
    - RespectIgnoreDifferences=true
```

Это тот же паттерн, что в официальной документации и примере `argocd-cm.yaml` (`resource.customizations.ignoreDifferences.all: managedFieldsManagers: [kube-controller-manager]`).

**Проверка:** убедитесь, что поле `replicas` действительно принадлежит менеджеру `kube-controller-manager`:

```bash
kubectl get deployment <name> -o jsonpath='{range .metadata.managedFields[*]}{.manager}{"\n"}{end}' | sort -u
# → result: kube-controller-manager (среди менеджеров)
```

Если в кластере HPA обновляет scale через другой менеджер, правило не сработает — имя менеджера зависит от версии Kubernetes и способа обновления, его всегда нужно проверять по `managedFields`.

### Сценарий 2: Игнорирование мутаций сервисного меша (Istio/Linkerd)

Сервисные меши внедряют sidecar-контейнеры и аннотации, которых нет в Git. Поскольку sidecar добавляется динамически в массив контейнеров, используется `jqPathExpressions` для выбора элемента по имени:

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jqPathExpressions:
    - .spec.template.spec.containers[] | select(.name == "istio-proxy")
    - .spec.template.metadata.annotations["sidecar.istio.io/status"]
```

**Для Linkerd** аналогично:

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jqPathExpressions:
    - .spec.template.spec.containers[] | select(.name == "linkerd-proxy")
    - .spec.template.metadata.annotations["linkerd.io/proxy-version"]
```

### Сценарий 3: Игнорирование мутаций вебхуков (официальный пример)

Канонический случай из документации — поле `caBundle` в `MutatingWebhookConfiguration`, которое подписывает API-сервер/контроллер и которое невозможно зафиксировать в Git:

```yaml
data:
  resource.customizations.ignoreDifferences.admissionregistration.k8s.io_MutatingWebhookConfiguration: |
    jsonPointers:
    - /webhooks/0/clientConfig/caBundle
    jqPathExpressions:
    - .webhooks[0].clientConfig.caBundle
    managedFieldsManagers:
    - kube-controller-manager
```

Тот же приём применяется к любым аннотациям и меткам, которые добавляет мутирующий вебхук: правило задаётся в `argocd-cm` один раз для конкретного Group/Kind и распространяется на все приложения.

### Сценарий 4: cert-manager

cert-manager добавляет аннотации к выдаваемым Secret и обновляет TLS-секреты. Аннотации `cert-manager.io/certificate-name` и `cert-manager.io/issuer-name` в Secret — типичный источник шума diff:

```yaml
spec:
  ignoreDifferences:
  - group: ""
    kind: Secret
    jqPathExpressions:
    - .metadata.annotations["cert-manager.io/certificate-name"]
    - .metadata.annotations["cert-manager.io/issuer-name"]
```

Для ресурсов `cert-manager.io/Certificate`, где drift вносится самим cert-manager, сначала определите имя менеджера (`kubectl get certificate <name> -o jsonpath='{.metadata.managedFields[*].manager}'`) и, если оно стабильно, добавьте его в `managedFieldsManagers` — имена менеджеров cert-manager зависят от версии и не являются частью стабильного контракта.

### Сценарий 5: Настройка для Reloader (Stakater)

Reloader перезапускает поды при изменении ConfigMap/Secret и добавляет аннотацию `reloader.stakater.com/last-reloaded-from`, создающую шум в diff:

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jsonPointers:
    - /spec/template/metadata/annotations/reloader.stakater.com~1last-reloaded-from
```

> **Примечание:** `~1` — экранирование слеша `/` в имени аннотации по RFC 6901.

### Сценарий 6: Принудительное обновление неизменяемых полей

Если в Git изменилось поле, которое Kubernetes запрещает обновлять (например, `spec.selector` в `Service` или `spec.clusterIP`), обычная синхронизация завершится ошибкой.

**Решение через CLI:**

```bash
argocd app sync <app-name> --force
```

**Решение в манифесте (использовать с осторожностью):**

```yaml
spec:
  syncPolicy:
    syncOptions:
    - Force=true # Приведет к удалению и пересозданию ресурса
```

> **Внимание:** `Force=true` удаляет и пересоздаёт ресурс — возможен даунтайм для Stateless-приложений и потеря данных для StatefulSet. Применяйте только когда `Replace=true` недостаточно. **С SSA `Force` не работает:** при `ServerSideApply=true` `kubectl apply --server-side` не поддерживает `--force`, поэтому `Force=true` игнорируется, а ресурс применяется с `--force-conflicts`.

**Альтернатива — `Replace=true`:**

```yaml
spec:
  syncPolicy:
    syncOptions:
    - Replace=true # Использует kubectl replace вместо apply
```

`Replace=true` применяет `kubectl replace`, который перезаписывает весь ресурс целиком. Подходит для ресурсов с неизменяемыми полями, но не приводит к удалению.

### Сценарий 7: CRD с динамическим status

Поле `status` CRD **по умолчанию не участвует в diff** (`ignoreResourceStatusField: all` — default), поэтому отдельное игнорирование `/status` обычно избыточно. Оно требуется, только если в `argocd-cm` явно задано `ignoreResourceStatusField: none` или правило сужено до `crd`, а `status` конкретного CR всё ещё попадает в diff:

```yaml
spec:
  ignoreDifferences:
  - group: example.com
    kind: MyResource
    jsonPointers:
    - /status
```

> **Внимание:** если `status` коммитится в Git и должен учитываться, документация рекомендует `ignoreResourceStatusField: crd` (а не `none`) — так `status` обычных ресурсов остаётся игнорируемым, а CRD остаются отслеживаемыми.

### Сценарий 8: Именованные правила для конкретного ресурса

Правило можно сузить до одного ресурса по `name` и `namespace` — например, когда только один Deployment в приложении мутируется оператором:

```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    name: guestbook
    namespace: default
    jsonPointers:
    - /spec/replicas
```

## Технический справочник

### Структура правила ignoreDifferences

| Поле | Описание |
| :--- | :--- |
| `group` | API-группа без версии; core-группа — `""`; поддерживаются glob-шаблоны (`'*'`) |
| `kind` | Тип ресурса; поддерживаются glob-шаблоны |
| `name` | (опционально) сужает правило до ресурса с данным именем |
| `namespace` | (опционально) сужает правило до namespace |
| `jsonPointers` | Список путей RFC 6901; `/` в именах кодируется как `~1` |
| `jqPathExpressions` | Список JQ-выражений; Argo CD применяет `del(<expression>)` |
| `managedFieldsManagers` | Список имён менеджеров из `metadata.managedFields` |

### Ключи argocd-cm

| Ключ | Описание |
| :--- | :--- |
| `resource.customizations.ignoreDifferences.<group>_<kind>` | Правила для конкретного Group/Kind (например, `apps_Deployment`) |
| `resource.customizations.ignoreDifferences.all` | Правила для всех ресурсов всех приложений |
| `resource.compareoptions` | `ignoreResourceStatusField: crd\|all\|none` (default `all`), `ignoreAggregatedRoles: true` |
| `resource.customizations.ignoreResourceUpdates.<group>_<kind>` / `.all` | Смежный механизм: поля, изменения которых не должны запускать реконсиляцию приложения (jsonPointers/jqPathExpressions) |
| `resource.ignoreResourceUpdatesEnabled` | Включает/выключает правила ignoreResourceUpdates (default `true`) |

### Смежный механизм: ignoreResourceUpdates

`ignoreDifferences` влияет на diff и статус. `resource.customizations.ignoreResourceUpdates` решает другую задачу: изменения перечисленных полей live-ресурса не вызывают обновление кэша и реконсиляцию приложения (например, `resourceVersion` или аннотации HPA `autoscaling.alpha.kubernetes.io/*`). Включается параметром `resource.ignoreResourceUpdatesEnabled: "true"` (default) и настраивается тем же синтаксисом (`jsonPointers`, `jqPathExpressions`).

### knownTypeFields: CRD, переиспользующие типы Kubernetes

Некоторые CRD переиспользуют структуры из Kubernetes API (например, `argoproj.io/Rollout` включает `core/v1/PodSpec`). Кастомные маршаллеры могут сериализовать поля иначе и порождать ложный drift — классический пример `IntOrString`: `cpu: 100m` превращается в `cpu: 0.1`. Решение — указать, какие поля использует встроенные типы:

```yaml
data:
  resource.customizations.knownTypeFields.argoproj.io_Rollout: |
    - field: spec.template.spec
      type: core/v1/PodSpec
```

Полный список поддерживаемых типов — в `util/argo/normalizers/diffing_known_types.txt`, дополнительно `core/Quantity` и `meta/v1/Duration`.

### Таймаут JQ-выражений

Вычисление `jqPathExpressions` ограничено одной секундой по умолчанию. При ошибке «JQ patch execution timed out» на сложных выражениях таймаут расширяется ключом `ignore.normalizer.jq.timeout` в ConfigMap `argocd-cmd-params-cm`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cmd-params-cm
data:
  ignore.normalizer.jq.timeout: '5s'
```

### Server-Side Diff (v3.5+)

Server-side diff вычисляет diff, выполняя server-side apply желаемого состояния в dry-run режиме против kube-apiserver. Результат учитывает defaulting полей и мутации admission-вебхуков — diff строится по «финальному» состоянию, а не по исходному манифесту.

Включается тремя способами:

1. **CLI:** `argocd app diff <app-name> --server-side-diff` (флаг появился в v3.5; есть также `--server-side-diff-concurrency` и `--server-side-diff-max-batch-kb` для настройки параллелизма и размера батча).
2. **Аннотация приложения:** `argocd.argoproj.io/compare-options: ServerSideDiff=true`.
3. **Неявно:** для ресурсов с sync option `ServerSideApply=true` (в новых версиях).

**Особенности:**
- Требует поддержки dry-run на стороне repo-server; когда dry-run runner недоступен (например, `argocd app diff` без server-side generation), Argo CD автоматически откатывается к клиентскому трёхстороннему/двустороннему diff.
- При фактическом запуске server-side diff клиентская полная нормализация (включая `ignoreDifferences` и `knownTypeFields`) **пропускается** — нормализация выполняется после dry-run apply на стороне сервера.
- CLI-флаг `--server-side-generate` используется вместе с `--local`: отправляет локальные манифесты на сервер для генерации перед diff.

### Compare-options аннотация

Аннотация `argocd.argoproj.io/compare-options` принимает значения (через запятую):

- **`IgnoreExtraneous`** — исключает «лишний» ресурс из общего статуса синхронизации (например, ресурс, сгенерированный инструментом, Kustomize `configMapGenerator`). Влияет **только на sync status**: если health ресурса деградирован, приложение всё равно будет degraded.
- **`ServerSideDiff=true`** (v3.5+) — включает server-side diff для приложения (см. выше).

### Диагностические команды

```bash
# Diff приложения (в CI — с кодом возврата при наличии различий)
argocd app diff <app-name>
argocd app diff <app-name> --exit-code --diff-exit-code 20

# Server-side diff (v3.5+)
argocd app diff <app-name> --server-side-diff

# Менеджеры полей ресурса
kubectl get <resource> <name> -o jsonpath='{range .metadata.managedFields[*]}{.manager}{"\n"}{end}'

# Статус и синхронизация приложения
argocd app get <app-name>

# Логи контроллера
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller
```

## Диагностика и устранение неисправностей

### Типичные проблемы

| Проблема | Симптомы | Вероятная причина | Решение |
| :--- | :--- | :--- | :--- |
| **Бесконечный `OutOfSync`** | Приложение постоянно `OutOfSync` несмотря на `ignoreDifferences` | Неверный путь в `jsonPointers`/`jqPathExpressions` или неверное имя менеджера | `argocd app diff <name>` — покажет конкретные поля; сверьте имя менеджера с `managedFields` |
| **Игнорирование не влияет на синхронизацию** | Статус `Synced`, но поле возвращается к значению из Git | Не установлен `RespectIgnoreDifferences=true` | Добавьте `RespectIgnoreDifferences=true` в `syncOptions` |
| **Конфликт с HPA** | Argo CD пытается вернуть число реплик | Не настроено игнорирование для менеджера, владеющего `spec.replicas` | Найдите менеджера через `managedFields` и добавьте в `managedFieldsManagers` |
| **Ошибка при нормализации** | `JQ patch execution timed out` | Сложное JQ-выражение превышает таймаут 1с | `ignore.normalizer.jq.timeout` в `argocd-cmd-params-cm` |
| **Ложный drift в CRD** | `100m` ↔ `0.1`, различия в форматировании | CRD переиспользует встроенные типы K8s | `resource.customizations.knownTypeFields.<group>_<kind>` |
| **Лишние ресурсы удаляются** | Ресурсы, созданные вне Git, удаляются при синхронизации | Включён pruning | `Prune=false` в `syncOptions` |

### Пошаговая диагностика

1. **Проверьте diff:** `argocd app diff <name>` — покажет, какие именно поля различаются.
2. **Определите источник изменений:** `kubectl get <resource> <name> -o yaml | grep managedFields` — какой контроллер управляет каждым полем.
3. **Проверьте JQ-выражение локально:** `echo '<json>' | jq 'del(<expression>)'` — убедитесь, что выражение выбирает нужные узлы.
4. **Проверьте статус приложения:** `argocd app get <name>` — применилось ли правило.
5. **Просмотрите логи контроллера:** `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller` — ошибки нормализации и синхронизации.

## Валидация и проверка работоспособности

### Проверка применения правил

```bash
# 1. Примените манифест Application
kubectl apply -f application.yaml

# 2. Дождитесь обновления статуса (или принудительно обновите через --refresh)
argocd app get <name> --refresh

# 3. Проверьте, что статус стал Synced
argocd app get <name> | grep Status
# → result: Status: Synced
```

### Проверка игнорирования конкретного поля

```bash
# 1. Измените поле, которое должно игнорироваться
kubectl patch deployment <name> --type merge -p '{"spec":{"replicas":5}}'

# 2. Дождитесь следующей сверки (или принудительно)
argocd app get <name> --refresh

# 3. Проверьте, что статус остался Synced
argocd app get <name> | grep Status
# → result: Status: Synced

# 4. Убедитесь, что поле НЕ было возвращено в Git-значение (при RespectIgnoreDifferences=true)
kubectl get deployment <name> -o jsonpath='{.spec.replicas}'
# → result: 5 (не значение из Git)
```

### Проверка для `jqPathExpressions`

```bash
# 1. Проверьте выражение на live-ресурсе
kubectl get deployment <name> -o json | jq '.spec.template.spec.containers[] | select(.name == "istio-proxy")'
# → result: объект контейнера

# 2. Проверьте обёртку del(), которую применяет Argo CD
echo '{"containers":[{"name":"app"},{"name":"istio-proxy"}]}' | jq 'del(.containers[] | select(.name == "istio-proxy"))'
# → result: {"containers":[{"name":"app"}]}
```

## Лучшие практики

### Приоритет методов

1. **`managedFieldsManagers`** — когда мутирующий актор известен и стабильно записывается в `managedFields`: покрывает все поля менеджера и не требует обновления при изменении структуры ресурса.
2. **`jqPathExpressions`** — когда нужна фильтрация по значениям внутри списков (конкретный контейнер, элемент массива).
3. **`jsonPointers`** — для простых фиксированных полей (`/spec/replicas`, конкретная аннотация).

### Безопасность

- **Не игнорируйте поля безопасности:** не исключайте `securityContext`, `runAsNonRoot`, `readOnlyRootFilesystem` и подобные — это скрывает критические отклонения.
- **Минимальные правила:** вместо глобальных `kind: '*'` указывайте конкретные Group/Kind и, по возможности, сужайте `name`/`namespace`.
- **Ревью через PR:** изменения `ignoreDifferences` влияют на видимость drift в кластере и должны проходить code review.
- **Помните про границы механизма:** `ignoreDifferences` влияет только на diff и статус `OutOfSync`. Health-статус ресурса (Healthy/Degraded) определяется отдельно и игнорированием не изменяется.

### Масштабирование

- **Для ApplicationSet:** задавайте `ignoreDifferences` в шаблоне ApplicationSet, чтобы правила применялись ко всем порождённым приложениям.
- **Для единообразия:** общие правила (вебхуки, системные аннотации) выносите в `argocd-cm` — они объединяются с локальными правилами приложений.
- **Для кастомных CRD:** проверьте, записывает ли оператор свои поля в `managedFields`, и добавьте его менеджера; для CRD с переиспользованием встроенных типов настройте `knownTypeFields`.

### Мониторинг

- Настраивайте алерты на длительный статус `OutOfSync` — это может указывать на неправильно настроенное игнорирование.
- Регулярно проверяйте `managedFields` ресурсов: обновления контроллеров могут менять имена менеджеров.

## Ограничения и edge cases

1. **Правила безусловны:** Argo CD не поддерживает условное игнорирование (например, «игнорировать поле только если значение > 100»).
2. **Именем менеджера управляет контроллер:** `managedFieldsManagers` работает только для менеджеров, реально присутствующих в `managedFields`. Если контроллер не записывает поле (или использует другое имя), правило не применяется — имя нужно проверять в целевом кластере.
3. **Множественные менеджеры одного поля:** если поле принадлежит нескольким менеджерам, Argo CD игнорирует изменения от всех перечисленных в правиле менеджеров.
4. **Удаление записи managedFields:** если контроллер перестаёт владеть полем (например, при обновлении), ранее игнорируемые поля снова начинают отслеживаться.
5. **Ресурсы без managedFields:** объекты, созданные до обновления кластера до Kubernetes 1.16, могут не содержать `managedFields` — для них работают только `jsonPointers`/`jqPathExpressions`.
6. **Сужение по name/namespace:** правило без `name`/`namespace` применяется ко всем ресурсам данного Group/Kind в приложении; для кластерных ресурсов (ClusterRoleBinding и т.п.) namespace не указывается.
7. **Взаимодействие с SelfHeal:** при `selfHeal: true` дрейфующие поля возвращаются к Git-состоянию; чтобы SelfHeal не перезаписывал игнорируемые поля, используйте `RespectIgnoreDifferences=true`.
8. **Server-side diff и нормализация:** когда server-side diff фактически выполняется (v3.5+), клиентская нормализация с `ignoreDifferences` пропускается — diff считается после dry-run apply. Учитывайте это при отладке: результат `argocd app diff --server-side-diff` может отличаться от клиентского diff.

## Дополнительная информация

### См. также
- [Синхронизация Argo CD: Обзор](../synchronization.md)
- [Автоматическая синхронизация и Self-Heal](./scenarios/auto_sync.md)
- [Отслеживание ресурсов](../argocd_resource_tracking.md)
- [Диагностика и Troubleshooting](../argocd_troubleshooting_and_monitoring.md)
- [Интеграция Kyverno и Argo CD](../../../Kubernetes/Security/kyverno/argo-cd.md)
- [ignoreDifferences для Crossplane](../../../GitOps/Crossplane/gitops_integration.md)

### Ссылки
- [Argo CD Documentation: Diffing Customization](https://argo-cd.readthedocs.io/en/stable/user-guide/diffing/)
- [Argo CD Documentation: Compare Options](https://argo-cd.readthedocs.io/en/stable/user-guide/compare-options/)
- [Argo CD Documentation: Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
- [Kubernetes: Server-Side Apply and field management](https://kubernetes.io/docs/reference/using-api/server-side-apply/#field-management)
- [RFC 6901: JavaScript Object Notation (JSON) Pointer](https://datatracker.ietf.org/doc/html/rfc6901)
