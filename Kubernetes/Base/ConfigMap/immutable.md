# Неизменяемые (Immutable) ConfigMap

**Актуально для:** Kubernetes 1.28–1.32+

## Определения

**Immutable ConfigMap** (неизменяемый ConfigMap) — это объект API Kubernetes (`kind: ConfigMap`, группа `core/v1`), в спецификации которого установлен флаг `immutable: true`. После создания такого объекта его данные (`data` и `binaryData`) становятся аппаратно защищенными от изменений на уровне `kube-apiserver`. Функция является **GA (General Availability)** начиная с версии Kubernetes v1.21.

**Name Hashing (хеширование имен)** — паттерн именования конфигурационных объектов, при котором к базовому имени ресурса добавляется детерминированный суффикс на основе хеш-суммы его содержимого (например, `app-config-8f92bdgh72`). Любое изменение содержимого конфигурации порождает объект с новым уникальным именем, что инициирует нативный Rolling Update рабочих нагрузок.

**Watch Reduction (сокращение подписок Watch)** — архитектурная оптимизация Control Plane и Kubelet, заключающаяся в отказе от поддержки постоянных HTTP/2 Watch-соединений для статических объектов. Kubelet запрашивает неизменяемый ресурс однократным вызовом `GET` и не регистрирует подписчика в `kube-apiserver` и `etcd`.

**Configuration Drift (дрейф конфигурации)** — неконтролируемое расхождение между декларативным состоянием конфигурации в Git-репозитории и фактическим состоянием в кластере, возникающее вследствие ручных или императивных модификаций (`kubectl edit`, `kubectl patch`).

**Atomic Rollout (атомарное развертывание)** — процесс обновления рабочей нагрузки, при котором поды гарантированно запускаются либо полностью со старой, либо полностью с новой версией конфигурации, исключая промежуточные состояния полупримененных параметров и рассинхронизацию между репликами.

---

## Архитектура и принцип работы

### Механизм Watch Reduction и разгрузка Control Plane

В стандартном режиме работы с изменяемыми (mutable) ConfigMap агент `kubelet` на каждом рабочем узле обязан отслеживать изменения всех конфигураций, смонтированных в запущенные на этом узле поды.

```
Mutable ConfigMap:
  Kubelet ────( Long-lived HTTP/2 Watch )────► kube-apiserver ────► etcd
  (Постоянное соединение на каждый объект, сериализация событий, удержание памяти)

Immutable ConfigMap:
  Kubelet ────( Однократный HTTP GET )───────► kube-apiserver ────► etcd
  (Данные помещаются в in-memory кеш узла; Watch-канал не создается)
```

**Проблематика масштабирования при Mutable ConfigMap:**
1. **Экспоненциальный рост соединений:** В кластере из 1000 узлов, где 200 сервисов используют собственные ConfigMap, количество активных долгоживущих соединений Watch со стороны Kubelet к `kube-apiserver` может превышать десятки тысяч.
2. **Нагрузка на etcd и память apiserver:** Для каждого открытого Watch-потока `kube-apiserver` и `etcd` выделяют буферы памяти для отслеживания ревизий (`resourceVersion`) и сериализации событий доставки.
3. **Thundering Herd при сетевых сбоях:** При перезапуске `kube-apiserver` или кратковременных сетевых разрывах тысячи Kubelet одновременно начинают повторный `LIST/WATCH`, вызывая резкие скачки потребления CPU и задержек API.

**Поведение Kubelet при `immutable: true`:**
- Компонент `ConfigMapManager` внутри `kubelet` при инициализации пода выполняет разовый HTTP-запрос `GET` к API-серверу.
- Обнаружив маркер `immutable: true`, Kubelet сохраняет объект в локальном кеше узла и **не регистрирует Watch-подписку**.
- При перезапуске контейнеров внутри пода Kubelet берет данные из кеша памяти, не обращаясь повторно к API-серверу, пока существует объект Pod.
- Экономия сетевого трафика и ресурсов Control Plane в крупных инсталляциях достигает десятков гигабайт памяти etcd и существенно снижает фоновую утилизацию CPU на мастер-нодах.

### Границы неизменяемости и анатомия объекта

В схеме API Kubernetes флаг `immutable` располагается на верхнем уровне спецификации ресурса `ConfigMap` (на одном уровне с `metadata` и `data`).

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config-v1
  namespace: default
  labels:
    app.kubernetes.io/name: payment-service
immutable: true
data:
  app.properties: "mode=production"
```

**Правила модификации полей:**
1. **Данные (`data`, `binaryData`):** Полностью защищены от любых изменений. Любой запрос `UPDATE` или `PATCH`, изменяющий, добавляющий или удаляющий ключи в этих полях, немедленно отклоняется API-сервером с кодом ошибки `400 Bad Request`.
2. **Флаг `immutable` (One-way switch):**
   - Допускается перевод изменяемого ConfigMap в неизменяемый: `immutable: false` (или отсутствие поля) → `immutable: true`.
   - **Запрещен обратный перевод:** Попытка изменить `immutable: true` на `false` или удалить это поле блокируется валидатором API-сервера (`field is immutable`). Неизменяемость является необратимой.
3. **Метаданные (`metadata`):** Остаются **полностью изменяемыми**. Разрешено добавлять, изменять и удалять:
   - Метки (`labels`);
   - Аннотации (`annotations`);
   - Финализаторы (`finalizers`).
   Это позволяет сервисным операторам, системам резервного копирования и инвентаризации маркировать объекты без нарушения их неизменяемости.
4. **Удаление объекта:** Флаг `immutable: true` **не защищает** объект от удаления (`DELETE`). Если субъект в кластере обладает правами RBAC на удаление ConfigMap, объект будет удален.

### Сравнение с методами доставки конфигураций в Pod

Влияние неизменяемости напрямую зависит от способа передачи данных в контейнер:

| Способ монтирования | Поведение Mutable ConfigMap | Поведение Immutable ConfigMap | Инженерный вывод (SRE/Sysadmin) |
| :--- | :--- | :--- | :--- |
| **Volume (без `subPath`)** | Kubelet обновляет файлы через symlink (`..data`) с задержкой 60–90 с. | Файлы на диске узла остаются зафиксированными до пересоздания пода. | Исключает рассинхронизацию файлов на лету между репликами сервиса. |
| **Volume с `subPath`** | **Не обновляется автоматически** из-за ограничений Linux bind-mount в контейнере. | **Не обновляется**. Поведение полностью предсказуемо и детерминировано. | Для `subPath` mutable режим создает только оверхед от Watch, не давая преимуществ hot-reload. |
| **Переменные (`env`, `envFrom`)** | **Не обновляются** в памяти запущенного процесса без перезапуска контейнера. | **Не обновляются**. | Использование mutable ConfigMap для переменных окружения архитектурно нецелесообразно. |

### Взаимосвязь с GitOps, Name Hashing и Rollout

В парадигме GitOps и декларативного управления инфраструктурой in-place мутация конфигураций признана антипаттерном по следующим причинам:
- **Отсутствие транзакционности:** При in-place изменении ConfigMap разные реплики одного Deployment считывают обновленный файл в разное время (дрейф по времени может составлять до нескольких минут).
- **Невозможность безопасного отката:** При сбое в новом конфигурационном файле команда `kubectl rollout undo deployment/...` не откатит содержимое ConfigMap, так как Deployment ссылается на то же неизменное имя объекта.

**Решение — паттерн Name Hashing:**
1. Инструменты сборки (Kustomize, Helm) вычисляют SHA256-хеш содержимого конфигурации и добавляют его к имени ресурса: `app-config-8f92bdgh72`.
2. В манифесте `Deployment` в поле `spec.template.spec.volumes[*].configMap.name` подставляется это хешированное имя.
3. При изменении хотя бы одного байта в конфиге генерируется **новый** ConfigMap с **новым** именем и флагом `immutable: true`.
4. Изменение имени тома в спецификации `Deployment` автоматически инициирует стандартный контролируемый **Rolling Update**.
5. Если новая версия конфигурации вызывает ошибки, `kubectl rollout undo` возвращает спецификацию пода к предыдущему `ReplicaSet`, который по-прежнему ссылается на старый, неудаленный и гарантированно сохранный неизменяемый ConfigMap.

---

## Практические сценарии

### Сценарий 1: Декларативное создание неизменяемого ConfigMap

Базовый манифест промышленного образца с метаданными и неизменяемыми данными:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: payment-service-config-v1
  namespace: production
  labels:
    app.kubernetes.io/name: payment-service
    app.kubernetes.io/instance: payment-service-prod
    app.kubernetes.io/version: "1.4.2"
    app.kubernetes.io/managed-by: manual
immutable: true
data:
  application.yaml: |
    server:
      port: 8080
      shutdown: graceful
    database:
      pool-size: 20
      timeout-ms: 5000
    logging:
      level: INFO
```

Применение манифеста в кластере:

```bash
kubectl apply -f payment-service-config-v1.yaml
# → configmap/payment-service-config-v1 created
```

Проверка фиксации флага:

```bash
kubectl get configmap payment-service-config-v1 -n production -o jsonpath='{.immutable}'
# → true
```

### Сценарий 2: Создание через CLI без синтаксических ошибок

Стандартная генерация через `kubectl create configmap --dry-run=client` **не добавляет** поле `immutable` в манифест по умолчанию. Для корректного создания манифеста одной строкой используйте `kubectl patch --local` либо инструмент `yq`:

```bash
# Генерация с внедрением флага immutable через локальный patch
kubectl create configmap nginx-proxy-config \
  --namespace=production \
  --from-literal=WORKER_PROCESSES=auto \
  --from-literal=CLIENT_MAX_BODY_SIZE=10m \
  --dry-run=client -o yaml | \
  kubectl patch --local -f - -p '{"immutable":true}' -o yaml | \
  kubectl apply -f -
# → configmap/nginx-proxy-config created
```

Альтернативный способ через `yq`:

```bash
kubectl create configmap nginx-proxy-config \
  --namespace=production \
  --from-file=nginx.conf=./nginx.conf \
  --dry-run=client -o yaml | \
  yq '.immutable = true' | \
  kubectl apply -f -
```

### Сценарий 3: Автоматизация через Kustomize (Name Hashing)

Kustomize полностью автоматизирует процесс установки флага `immutable` и связывания с подами через генераторы `configMapGenerator`.

Структура каталога:
```
├── configs
│   └── application.properties
├── deployment.yaml
└── kustomization.yaml
```

Файл `kustomization.yaml`:

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: production

generatorOptions:
  immutable: true # Устанавливает immutable: true для всех сгенерированных ConfigMap и Secret

configMapGenerator:
- name: core-api-config
  files:
  - configs/application.properties
```

Манифест `deployment.yaml` ссылается на базовое имя:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: core-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: core-api
  template:
    metadata:
      labels:
        app: core-api
    spec:
      containers:
      - name: api
        image: internal-registry.example.local/core/api:v1.2.0
        volumeMounts:
        - name: cfg
          mountPath: /etc/app
          readOnly: true
      volumes:
      - name: cfg
        configMap:
          name: core-api-config # Kustomize автоматически заменит на core-api-config-<hash>
```

Результат выполнения команды `kubectl kustomize .`:

```yaml
apiVersion: v1
data:
  application.properties: |
    db.pool=10
immutable: true
kind: ConfigMap
metadata:
  name: core-api-config-7k8g479t6m
  namespace: production
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: core-api
  namespace: production
spec:
  template:
    spec:
      volumes:
      - configMap:
          name: core-api-config-7k8g479t6m
        name: cfg
```

### Сценарий 4: Реализация в Helm

В Helm-чартах для предотвращения проблем с рассинхронизацией применяется управление флагом через `values.yaml` и суффиксирование имен.

Файл `values.yaml`:

```yaml
config:
  immutable: true
  version: "v2"
  properties:
    logLevel: "WARN"
    maxConnections: "500"
```

Файл `templates/configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ include "mychart.fullname" . }}-config-{{ .Values.config.version }}
  labels:
    {{- include "mychart.labels" . | nindent 4 }}
immutable: {{ .Values.config.immutable | default false }}
data:
  app.conf: |
    LOG_LEVEL={{ .Values.config.properties.logLevel }}
    MAX_CONN={{ .Values.config.properties.maxConnections }}
```

Файл `templates/deployment.yaml`:

```yaml
spec:
  template:
    metadata:
      annotations:
        # Контрольная сумма для гарантированного перезапуска при смене значений
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      volumes:
      - name: config-volume
        configMap:
          name: {{ include "mychart.fullname" . }}-config-{{ .Values.config.version }}
```

### Сценарий 5: Безопасная миграция существующего ConfigMap в Production

Если в действующем кластере эксплуатируется изменяемый ConfigMap, перевод в неизменяемый статус выполняется одним из двух способов.

#### Способ А: In-place фиксация (без смены имени)

Применяется, если текущее имя объекта жестко зафиксировано в нескольких сервисах и смена имени нежелательна:

```bash
# 1. Экспорт резервной копии объекта
kubectl get configmap order-service-config -n production -o yaml > order-service-config.backup.yaml

# 2. Атомарное включение неизменяемости через patch
kubectl patch configmap order-service-config -n production \
  --type=merge \
  -p '{"immutable": true}'
# → configmap/order-service-config patched

# 3. Верификация флага
kubectl get configmap order-service-config -n production -o jsonpath='{.immutable}'
# → true
```

#### Способ Б: Blue-Green миграция со сменой имени (Рекомендуемый SRE-стандарт)

1. Создается новый объект с суффиксом ревизии:
```bash
kubectl create configmap order-service-config-v2 -n production \
  --from-file=config.properties \
  --dry-run=client -o yaml | \
  kubectl patch --local -f - -p '{"immutable":true}' -o yaml | \
  kubectl apply -f -
```

2. Обновляется целевой Deployment:
```bash
kubectl set volume deployment/order-service -n production \
  --add --name=config-volume \
  --mount-path=/etc/config \
  --configmap-name=order-service-config-v2
```

3. Контролируется статус завершения Rolling Update:
```bash
kubectl rollout status deployment/order-service -n production --timeout=120s
# → deployment "order-service" successfully rolled out
```

4. Старый объект `order-service-config` удаляется только после подтверждения стабильности подов.

### Сценарий 6: Валидация и аудит статуса в кластере

#### Проверка реакции API-сервера на попытку редактирования

Попытка изменить данные неизменяемого объекта:

```bash
kubectl patch configmap payment-service-config-v1 -n production \
  --type=merge \
  -p '{"data":{"application.yaml":"server:\n  port: 9090"}}'
# → Error from server (Invalid): ConfigMap "payment-service-config-v1" is invalid:
#   [data: Forbidden: field is immutable when `immutable` is set,
#    binaryData: Forbidden: field is immutable when `immutable` is set]
```

Попытка снять флаг неизменяемости:

```bash
kubectl patch configmap payment-service-config-v1 -n production \
  --type=merge \
  -p '{"immutable": false}'
# → Error from server (Invalid): ConfigMap "payment-service-config-v1" is invalid:
#   immutable: Forbidden: field is immutable when `immutable` is set
```

#### Инспекция и массовый аудит через `kubectl` и `jq`

Поиск всех изменяемых ConfigMap в кластере (потенциальные кандидаты на оптимизацию):

```bash
kubectl get configmaps -A -o json | jq -r '
  .items[] | 
  select(.metadata.namespace | test("^(kube-system|kube-public|kube-node-lease)$") | not) |
  select(.immutable != true) | 
  "[\(.metadata.namespace)] \(.metadata.name)"
'
```

Подсчет доли неизменяемых ConfigMap в production:

```bash
kubectl get configmaps -n production -o json | jq '
  {
    total: (.items | length),
    immutable: ([.items[] | select(.immutable == true)] | length),
    mutable: ([.items[] | select(.immutable != true)] | length)
  }
'
# → {
#     "total": 42,
#     "immutable": 38,
#     "mutable": 4
#   }
```

### Сценарий 7: Политики допуска (Admission Control)

В Kubernetes разграничение прав через RBAC не способно анализировать содержимое payload запроса (нельзя через `Role` запретить или разрешить установку значения `immutable: true`). Для принудительного контроля используются механизмы Admission Control.

#### Вариант А: Нативный ValidatingAdmissionPolicy (Kubernetes 1.30+ GA)

Не требует внешних вебхуков и контроллеров, выполняется внутри процесса `kube-apiserver` с помощью языка CEL (Common Expression Language):

```yaml
# 1. Определение политики
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: "require-immutable-configmaps"
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
    - apiGroups:   [""]
      apiVersions: ["v1"]
      operations:  ["CREATE"]
      resources:   ["configmaps"]
  validations:
    - expression: "has(object.immutable) && object.immutable == true"
      message: "Все ConfigMap в production обязаны создаваться с флагом 'immutable: true'."
---
# 2. Привязка политики к production-неймспейсам
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: "require-immutable-configmaps-binding"
spec:
  policyName: "require-immutable-configmaps"
  validationActions: [Deny]
  matchResources:
    namespaceSelector:
      matchExpressions:
      - key: environment
        operator: In
        values: ["production"]
```

#### Вариант Б: Политика Kyverno (ClusterPolicy)

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: enforce-immutable-configmaps
  annotations:
    policies.kyverno.io/title: Enforce Immutable ConfigMaps in Production
    policies.kyverno.io/category: Best Practices
spec:
  validationFailureAction: Enforce
  background: false
  rules:
  - name: check-immutable-flag
    match:
      any:
      - resources:
          kinds:
          - ConfigMap
          namespaces:
          - production
    validate:
      message: "В неймспейсе production запрещено создавать ConfigMap без 'immutable: true'."
      pattern:
        immutable: true
```

---

## Диагностика и устранение неполадок

### Ошибка 1: `cannot modify fields other than 'metadata' for immutable configmap`

**Симптомы:**
CI/CD пайплайн или администратор при вызове `kubectl apply` получает отказ:
```
Error from server (Invalid): ConfigMap "ingress-gateway-config" is invalid:
[data: Forbidden: field is immutable when `immutable` is set]
```

**Причина:**
В репозитории изменены значения в секции `data`, но имя ConfigMap в манифесте осталось прежним. API-сервер блокирует in-place мутацию данных объекта.

**Алгоритм устранения:**
1. Если используется Kustomize: убедитесь, что имя ресурса формируется через `configMapGenerator`, а не описано статическим манифестом в `resources: [...]`.
2. Если используется чистый YAML: измените имя ресурса (например, с `ingress-gateway-config-v1` на `ingress-gateway-config-v2`) и обновите ссылку в `Deployment`.
3. Примените манифесты повторно:
   ```bash
   kubectl apply -f ingress-gateway-config-v2.yaml
   kubectl apply -f deployment.yaml
   ```

### Ошибка 2: Ошибка снятия флага `immutable: Forbidden`

**Симптомы:**
При попытке отключить неизменяемость командой:
```bash
kubectl patch configmap app-cfg -p '{"immutable": null}'
```
Возвращается ошибка:
```
Error from server (Invalid): ConfigMap "app-cfg" is invalid: immutable: Forbidden: field is immutable when `immutable` is set
```

**Причина:**
В кодовой базе Kubernetes валидатор API запрещает переход `true → false` или `true → nil`. Флаг неизменяемости однонаправлен.

**Решение:**
Единственный способ изменить свойства — удаление и пересоздание ресурса:
```bash
# 1. Сохранение конфигурации во временный файл
kubectl get configmap app-cfg -o yaml > /tmp/app-cfg.yaml

# 2. Удаление существующего неизменяемого объекта
kubectl delete configmap app-cfg

# 3. Редактирование /tmp/app-cfg.yaml (удаление строки immutable: true)

# 4. Повторное создание
kubectl apply -f /tmp/app-cfg.yaml
```
> [!WARNING]
> Удаление ConfigMap в работающем кластере создает окно риска: если в этот момент упадет под или сработает эвикция, новый под не сможет запуститься до момента создания нового конфига.

### Ошибка 3: Зависание Pod в статусе `CreateContainerConfigError` или `FailedMount`

**Симптомы:**
После обновления Deployment поды не переходят в статус `Running`.
Вывод `kubectl get pods`:
```
NAME                       READY   STATUS                       RESTARTS   AGE
billing-api-7b94ff8-xk2m   0/1     CreateContainerConfigError   0          45s
```
Либо при монтировании тома в событиях пода (`kubectl describe pod`):
```
Warning  FailedMount  12s (x4 over 48s)  kubelet  MountVolume.SetUp failed for volume "config" : configmap "billing-config-v3" not found
```

**Причина:**
В манифесте рабочей нагрузки указано новое имя ConfigMap, но сам объект ConfigMap еще не был создан в целевом пространстве имен (ошибка очередности применения в CI/CD).

**Диагностика:**
```bash
# Проверка наличия целевого ресурса
kubectl get configmap billing-config-v3 -n production
# → Error from server (NotFound): configmaps "billing-config-v3" not found

# Инспекция точных событий пода
kubectl describe pod billing-api-7b94ff8-xk2m -n production | grep -A 5 Events:
```

**Решение:**
1. Настройте пайплайн доставки (GitOps sync waves или зависимости шагов), чтобы манифесты ConfigMap применялись строго **до** манифестов контроллеров (Deployment, StatefulSet, DaemonSet).
2. Создайте недостающий ресурс в кластере:
   ```bash
   kubectl apply -f billing-config-v3.yaml
   ```
   Kubelet автоматически повторит попытку монтирования без необходимости ручного перезапуска пода.

### Ошибка 4: Переполнение etcd устаревшими версионированными ConfigMap

**Симптомы:**
В etcd накапливаются тысячи объектов с именами вида `app-config-<hash>`, увеличивая объем базы данных `etcd.db` и время дефрагментации.

**Причина:**
По умолчанию объекты ConfigMap **не имеют** `ownerReferences`, связывающих их с конкретным `Deployment` или `ReplicaSet`. Стандартный сборщик мусора Kubernetes (Garbage Collector) не удаляет старые ConfigMap после успешного Rolling Update.

**Диагностика:**
```bash
# Оценка количества версий одного конфига
kubectl get configmaps -n production -o name | grep "app-config-" | wc -l
# → 247
```

**Решение:**
Внедрите автоматическую очистку через GitOps-инструменты либо регулярный CronJob (детально описано в разделе "Лучшие практики").

---

## Лучшие практики (Best Practices)

### 1. Стандарт «Immutable-by-Default» для статических конфигураций

- Для всех конфигураций, не требующих частого изменения на лету, флаг `immutable: true` должен быть обязательным стандартом для сред Staging и Production.
- Исключение составляют только специализированные сценарии Dynamic Reloading (например, динамическое переключение Feature Flags через inotify/SIGHUP без перезапуска процессов).

### 2. Стратегия именования: Content Hashing vs Semantic Versioning

| Подход | Формат имени | Преимущества | Недостатки | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Content Hashing** | `app-cfg-8f92bdgh72` | Полная автоматизация через Kustomize; гарантированный перезапуск при любых правках. | Имя не несет человекочитаемого смысла. | **Основной стандарт для CI/CD и GitOps** |
| **Semantic Versioning** | `app-cfg-v1.4.0` | Явная связь с релизным тегом приложения; простота ручного аудита. | Требует ручного контроля версий в манифестах. | Допустимо для крупных монолитных систем с редкими релизами |

### 3. Автоматизация очистки (Garbage Collection и Retention)

Поскольку Kubernetes не очищает несвязанные ConfigMap автоматически, необходимо настроить процесс ротации:

#### А. Автоматическая очистка средствами GitOps (Argo CD)

- **В Argo CD:** активируйте механизм автоматического удаления неиспользуемых ресурсов в `Application`:
  ```yaml
  spec:
    syncPolicy:
      automated:
        prune: true     # Автоматически удаляет старые ConfigMap, исчезнувшие из Git
        selfHeal: true
  ```
```

#### Б. Эксплуатационный CronJob для очистки орфанных ConfigMap

Для сред без жесткого GitOps pruning используйте безопасный скрипт очистки, который проверяет отсутствие ссылок на ConfigMap со стороны активных подов перед удалением:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: prune-unused-configmaps
  namespace: maintenance
spec:
  schedule: "0 3 * * 0" # Каждое воскресенье в 03:00
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: configmap-cleaner-sa
          restartPolicy: OnFailure
          containers:
          - name: cleaner
            image: bitnami/kubectl:1.32.0
            command:
            - /bin/bash
            - -c
            - |
              set -euo pipefail
              TARGET_NS="production"
              
              # Получаем список ConfigMap, реально используемых активными подами
              USED_CMS=$(kubectl get pods -n "$TARGET_NS" -o json | jq -r '
                [
                  .items[].spec | 
                  (
                    (.volumes[]?.configMap.name // empty),
                    (.volumes[]?.projected.sources[]?.configMap.name // empty),
                    (.containers[]?.env[]?.valueFrom.configMapKeyRef.name // empty),
                    (.containers[]?.envFrom[]?.configMapRef.name // empty)
                  )
                ] | unique | .[]
              ')
              
              # Находим версионированные ConfigMap старше 14 дней, не входящие в список используемых
              kubectl get configmaps -n "$TARGET_NS" -o json | jq -r --argjson used "$(echo "$USED_CMS" | jq -R . | jq -s .)" '
                .items[] |
                select(.immutable == true) |
                select(.metadata.name | test("-[a-f0-9]{7,10}$")) |
                select(.metadata.creationTimestamp < (now - 14*86400 | todate)) |
                select(.metadata.name as $name | ($used | index($name) | not)) |
                .metadata.name
              ' | while read -r CM_TO_DELETE; do
                if [ -n "$CM_TO_DELETE" ]; then
                  echo "Удаление устаревшего ConfigMap: $CM_TO_DELETE"
                  kubectl delete configmap "$CM_TO_DELETE" -n "$TARGET_NS"
                fi
              done
```

> [!NOTE]
> Сервисный аккаунт `configmap-cleaner-sa` должен иметь Role в целевом пространстве имен с правами:
> `get`, `list` для `pods` и `configmaps`, а также `delete` для `configmaps`.

### 4. Мониторинг, алертинг и аудит безопасности

#### Prometheus-метрики и корректный алертинг

Отслеживание соотношения объектов в кластере выполняется через стандартный `kube-state-metrics`:
- Метрика `kube_configmap_info{namespace="...", configmap="...", immutable="true|false"}` сообщает о текущем статусе.
- **Предостережение:** выражение `changes(kube_configmap_info[...])` **не работает** для отслеживания модификации данных, поскольку `kube_configmap_info` — это статичная информационная метрика со значением `1`.

Для обнаружения попыток несанкционированного изменения неизменяемых конфигураций используется счетчик отказов `kube-apiserver`:

```yaml
# PrometheusRule: оповещение об отклоненных попытках изменения ConfigMap
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: configmap-rejection-alerts
  namespace: monitoring
spec:
  groups:
  - name: configmap.rules
    rules:
    - alert: ConfigMapModificationRejected
      expr: |
        sum by (namespace) (
          rate(apiserver_request_total{resource="configmaps",verb=~"update|patch",code="400"}[5m])
        ) > 0
      for: 2m
      labels:
        severity: warning
      annotations:
        summary: "Отклонены попытки модификации ConfigMap в {{ $labels.namespace }}"
        description: "API-сервер отклоняет попытки обновления ConfigMap с кодом 400 Bad Request. Возможна попытка in-place модификации объекта с immutable: true."
```

#### Настройка политик аудита (kube-apiserver Audit Policy)

Чтобы фиксировать субъектов (ServiceAccount или пользователей), пытающихся отредактировать неизменяемые ресурсы, добавьте правило в файл конфигурации аудита мастера `/etc/kubernetes/audit-policy.yaml`:

```yaml
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
# Фиксация попыток изменения и удаления ConfigMap на уровне метаданных запроса
- level: Metadata
  verbs: ["update", "patch", "delete"]
  resources:
  - group: ""
    resources: ["configmaps"]
  namespaces: ["production"]
```

---

## Дополнительная информация

### Сравнительный анализ: Mutable vs Immutable ConfigMap

| Критерий оценки | Изменяемый (Mutable) ConfigMap | Неизменяемый (Immutable) ConfigMap |
| :--- | :--- | :--- |
| **Флаг в спецификации** | `immutable: false` (или отсутствует) | `immutable: true` |
| **Нагрузка на API-сервер** | Высокая (постоянный открытый Watch-канал Kubelet) | Минимальная (разовый вызов GET, отсутствие Watch) |
| **Расход памяти etcd** | Высокий при большом количестве нод/подов | Минимальный |
| **Обновление в томах пода** | Фоновое, с задержкой sync (60–90 секунд) | Отсутствует; требует пересоздания подов |
| **Поведение при `subPath`** | Не обновляется автоматически (ограничение ядра) | Не обновляется; предсказуемое поведение |
| **Поведение при `env` / `envFrom`** | Не обновляется в памяти процесса | Не обновляется; предсказуемое поведение |
| **Синхронность реплик** | Риск рассинхрона (разные поды видят разные данные) | 100% консистентность всех реплик |
| **Механизм отката (Rollback)** | Ручное восстановление содержимого в etcd | Мгновенный перевызов старого имени через ReplicaSet |
| **Основная область применения** | Локальная разработка, динамические debug-флаги | Промышленные production-окружения, GitOps |

### Применение для объектов Secret

Аналогичный флаг `immutable: true` поддерживается объектами API `kind: Secret` (группа `core/v1`). Все архитектурные правила, поведение Kubelet, оптимизация Watch Reduction и ограничения модификации работают идентично. Подробнее о защите учетных данных см. в [Безопасность Secret](../secrets/security.md).

### Ссылки на связанные материалы

- [Создание ConfigMap](./creation.md) — декларативный подход, генераторы и параметры спецификации.
- [Рекомендации и лучшие практики ConfigMap](./best_practices.md) — соглашения по именованию, структура и эксплуатационные паттерны.
- [Использование ConfigMap в поде](./pod_usage.md) — детальный анализ монтирования томов, передачи переменных окружения и ограничений Kubelet.
- [Обновление и Rollout](./update_and_rollout.md) — стратегии актуализации конфигураций, триггеры перезапуска и Hash-аннотации.
- [Работа с большими конфигурациями](./large_configs.md) — преодоление системного лимита etcd в 1 MiB.
- [Готовые шаблоны ConfigMap](./practical_templates.md) — примеры конфигураций Nginx, HAProxy, PostgreSQL, Redis.
