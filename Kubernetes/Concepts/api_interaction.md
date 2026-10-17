# Взаимодействие с API Kubernetes

**Актуально для:** Kubernetes 1.30–1.35 (Bare-Metal / On-Premise)

## Определения

*   **kube-apiserver** — центральный компонент плоскости управления (Control Plane), предоставляющий декларативный RESTful API через HTTPS (порт по умолчанию 6443) и являющийся единственной точкой доступа к базе данных состояний `etcd`.
*   **GVK (Group, Version, Kind)** — схема спецификации типа ресурса в манифестах (например, `Group: apps`, `Version: v1`, `Kind: Deployment`). Определяет структуру схемы данных.
*   **GVR (Group, Version, Resource)** — REST-путь к эндпоинту ресурса в HTTP API (например, `/apis/apps/v1/namespaces/default/deployments`). Используется клиентами для выполнения сетевых запросов.
*   **Subresource (Подресурс)** — специализированный дочерний HTTP-эндпоинт объекта (например, `/status`, `/scale`, `/exec`, `/log`, `/portforward`, `/ephemeralcontainers`), имеющий собственную схему данных, независимые права RBAC и выделенные обработчики.
*   **OCC (Optimistic Concurrency Control)** — механизм оптимистичной блокировки параллельных изменений на основе числового идентификатора ревизии `metadata.resourceVersion`. Предотвращает перезапись изменений при гонках обновлений (Race Conditions).
*   **SSA (Server-Side Apply)** — механизм применения декларативных конфигураций, при котором вычисление различий (diff), слияние и отслеживание владельцев полей (`field managers`) производятся на стороне `kube-apiserver` через метаданные `metadata.managedFields`.
*   **CSA (Client-Side Apply)** — традиционный метод применения конфигураций (`kubectl apply`), рассчитывающий 3-way merge diff на стороне клиента и сохраняющий полный снимок манифеста в аннотации `kubectl.kubernetes.io/last-applied-configuration`.
*   **Watch и Bookmarks** — потоковый HTTP-механизм доставки событий изменения ресурсов клиентам в реальном времени с поддержкой контрольных меток времени/версии (`Bookmark`) для надежного восстановления потока без повторного полного перечитывания списка.
*   **Informer / SharedInformer** — архитектурный паттерн и компонент библиотеки `client-go`, реализующий локальное in-memory кеширование ресурсов кластера и оповещение контроллеров через подписку на события Watch.
*   **APF (API Priority and Fairness)** — встроенный механизм приоритизации, буферизации в очередях и ограничения конкурентности входящих запросов в `kube-apiserver`, защищающий Control Plane от исчерпания ресурсов при пиковых нагрузках.

---

## Архитектура и принципы работы

### Конвейер обработки запроса (Request Processing Pipeline)

Каждый HTTP-запрос к `kube-apiserver` проходит детерминированную цепочку фильтров и обработчиков (Handler Chain) перед фиксацией изменений:

```
Запрос клиента (kubectl / CI-CD / Controller / curl)
        │
        ▼  [HTTPS :6443 / TLS Termination]
   kube-apiserver
        │
        ├── 1. Authentication (Аутентификация)
        │      ├── Проверка X.509 клиентских сертификатов
        │      ├── Bearer Tokens (ServiceAccount TokenRequest API)
        │      └── Webhook Token Authenticator / OIDC
        │
        ├── 2. Authorization (Авторизация)
        │      ├── Node Authorizer (запросы от kubelet)
        │      ├── RBAC (Role-Based Access Control)
        │      └── Webhook Authorizer
        │
        ├── 3. APF — API Priority and Fairness (Фильтрация и приоритизация)
        │      ├── FlowSchema: сопоставление запроса с потоком
        │      └── PriorityLevelConfiguration: помещение в очередь и лимиты concurrency
        │
        ├── 4. Mutating Admission (Мутирующий контроль допуска)
        │      ├── Встроенные плагины (NamespaceLifecycle, ServiceAccount, DefaultStorageClass)
        │      ├── MutatingAdmissionWebhook (внешние хуки мутации)
        │      └── MutatingAdmissionPolicy (нативные CEL-мутации K8s 1.32+)
        │
        ├── 5. Schema Validation & Object Parsing (Синтаксическая валидация)
        │      └── Проверка соответствия схеме OpenAPI, валидация полей и типов
        │
        ├── 6. Validating Admission (Валидирующий контроль допуска)
        │      ├── ValidatingAdmissionPolicy (нативный движок CEL)
        │      ├── ValidatingAdmissionWebhook (внешние хуки проверки)
        │      └── Встроенные плагины валидации
        │
        ├── 7. Object Storage & Commit (Запись в хранилище)
        │      ├── Преобразование во внутреннюю версию (Internal Version)
        │      ├── Проверка Optimistic Concurrency Control (resourceVersion)
        │      └── Сериализация в Protobuf/JSON и атомарная запись в etcd
        │
        └── 8. Event Notification (Оповещение подписчиков)
               └── Watch Stream / SharedInformer рассылают событие контроллерам
```

Подробный разбор специализированных механизмов фильтрации вынесен в профильные разделы:
*   Управление потоками и очередями запросов: **[API Priority and Fairness (APF)](./api_priority_and_fairness.md)**.
*   Валидация и мутация содержимого: **[Контроллеры допуска (Admission Controllers)](./admission_controllers.md)**.
*   Авторизация и роли: **[RBAC: Управление доступом](../Security/rbac/rbac_overview.md)**.

### Иерархия эндпоинтов и структура API

API Kubernetes организовано по иерархическому принципу:

```
/ (Корень API)
├── /api/v1                                (Core Group: Pods, Services, Namespaces, ConfigMaps)
├── /apis                                  (Named Groups Root)
│   ├── /apis/apps/v1                      (Deployments, StatefulSets, DaemonSets)
│   ├── /apis/batch/v1                     (Jobs, CronJobs)
│   ├── /apis/networking.k8s.io/v1         (NetworkPolicies, Ingresses)
│   └── /apis/{group}/{version}            (CRD и Aggregated APIs)
├── /livez, /readyz, /healthz              (Проверки жизнеспособности и готовности API-сервера)
├── /metrics                               (Prometheus-метрики производительности)
├── /openapi/v2, /openapi/v3               (Спецификации OpenAPI для валидации и автодополнения)
└── /version                               (Информация о версии бинарного файла kube-apiserver)
```

1.  **Core Group (Legacy):** Расположена по префиксу `/api/v1`. Содержит базовые исторические примитивы Kubernetes (`pods`, `services`, `nodes`, `namespaces`, `secrets`, `configmaps`). В манифестах поле `apiVersion` указывается как `v1`.
2.  **Named Groups:** Расположены по префиксу `/apis/{group}/{version}`. В манифестах поле `apiVersion` имеет вид `{group}/{version}` (например, `apps/v1`, `batch/v1`).
3.  **Discovery API и OpenAPI v3:** Клиенты (например, `kubectl`) выполняют динамическое обнаружение возможностей сервера через запросы `/api` и `/apis`, сохраняя схемы в локальный кеш (`~/.kube/cache/discovery`). Начиная с Kubernetes 1.27+ стандартом является **OpenAPI v3** (`/openapi/v3`), который отдает спецификации дифференциально по группам, устраняя передачу единого монолитного JSON-файла размером в десятки мегабайт.

### Подресурсы (Subresources)

Подресурсы позволяют выполнять операции над отдельными аспектами объекта без затрагивания основного тела спецификации (`spec`):

| Подресурс | HTTP-путь | Назначение и специфика |
| :--- | :--- | :--- |
| **`/status`** | `/apis/apps/v1/namespaces/{ns}/deployments/{name}/status` | Обновление текущего состояния контроллерами. Изолировано от изменения `spec`. Требует отдельного разрешения в RBAC (`deployments/status`). |
| **`/scale`** | `/apis/apps/v1/namespaces/{ns}/deployments/{name}/scale` | Легковесный объект масштабирования (`Scale`), содержащий только число реплик и селектор. Используется HPA и KEDA без блокировки всего ресурса. |
| **`/exec`** | `/api/v1/namespaces/{ns}/pods/{name}/exec` | Открытие интерактивного терминала внутри контейнера. Двунаправленный потоковый протокол. |
| **`/log`** | `/api/v1/namespaces/{ns}/pods/{name}/log` | Чтение stdout/stderr контейнера (текстовый поток или WebSocket). |
| **`/portforward`** | `/api/v1/namespaces/{ns}/pods/{name}/portforward` | Проброс сетевых портов от клиента к поду через Control Plane. |
| **`/ephemeralcontainers`**| `/api/v1/namespaces/{ns}/pods/{name}/ephemeralcontainers` | Добавление отладочных контейнеров в уже запущенный под (`kubectl debug`). |

> **Смена транспортного протокола (WebSockets):** Исторически интерактивные подресурсы (`/exec`, `/portforward`, `/attach`) использовали протокол SPDY/3.1. В Kubernetes 1.30+ нативным стандартом стал протокол **WebSockets** (RFC 6455). Это обеспечивает совместимость со стандартными корпоративными L7-прокси и балансировщиками (HAProxy, Nginx, Envoy) без сбоев длинных TCP-сессий.

### Механизмы обновления и модификации данных

Kubernetes предоставляет 4 способа изменения существующих объектов в API:

```
                             СПОСОБЫ МОДИФИКАЦИИ
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
  1. Полная замена              2. Патчи (Client)            3. Server-Side Apply
     (HTTP PUT)                    (HTTP PATCH)                 (HTTP PATCH SSA)
   Требует передачи            Логика слияния на              Логика слияния на
    resourceVersion             стороне клиента                стороне API-сервера
                                      │
                   ┌──────────────────┴──────────────────┐
                   ▼                                     ▼
          Strategic Merge Patch / JSON Merge      JSON Patch (RFC 6902)
```

1.  **Полная замена (HTTP PUT / Update):**
    Клиент отправляет полный объект. Сервер требует обязательного совпадения поля `metadata.resourceVersion`. Если объект был изменен другим процессом между чтением и записью, сервер отклоняет запрос со статусом `409 Conflict`.
2.  **JSON Patch (RFC 6902, `application/json-patch+json`):**
    Массив атомарных инструкций (`add`, `remove`, `replace`, `copy`, `move`, `test`). Позволяет точно изменить отдельный элемент списка или значение ключа.
3.  **JSON Merge Patch (RFC 7386, `application/merge-patch+json`):**
    Частичный JSON-документ. Ключи со значением `null` удаляются. Применяется для CRD, где нет метаданных о правилах объединения списков.
4.  **Strategic Merge Patch (`application/strategic-merge-patch+json`):**
    Специализированный формат Kubernetes для встроенных типов. Использует директивы в схеме Go-структур (`patchStrategy`, `patchMergeKey`). Позволяет объединять списки объектов по ключу (например, обновлять свойства одного контейнера в массиве `containers` по его полю `name`, не затирая остальные контейнеры).

### Server-Side Apply (SSA) и управление полями

**Server-Side Apply** переносит ответственность за слияние манифестов с клиента на `kube-apiserver`:

*   Каждое поле объекта связывается с владельцем (**Field Manager**).
*   История владения хранится в метаданных ресурса в блоке `metadata.managedFields`.
*   При попытке изменения поля другим менеджером через SSA сервер возвращает ошибку `409 Conflict` с описанием конфликтующих полей.

```json
"managedFields": [
  {
    "manager": "argocd-application-controller",
    "operation": "Apply",
    "apiVersion": "apps/v1",
    "time": "2026-10-17T20:00:00Z",
    "fieldsType": "FieldsV1",
    "fieldsV1": {
      "f:spec": {
        "f:template": {
          "f:spec": {
            "f:containers": {
              "k:{\"name\":\"web\"}": {
                ".": {},
                "f:image": {}
              }
            }
          }
        }
      }
    }
  }
]
```

**Разрешение конфликтов SSA в связке с внешними контроллерами:**
*   **Проблема:** Если инструмент GitOps (ArgoCD, Flux) или `kubectl apply --server-side` объявляет поле `spec.replicas: 3`, а в кластере работает HPA (Horizontal Pod Autoscaler), возникает конфликт владения: HPA пытается управлять полем через подресурс `/scale`, а GitOps перезаписывает его на каждом цикле синхронизации.
*   **Правильное решение:** Исключить поле `spec.replicas` из Git-манифеста после первоначального развертывания или настроить исключение менеджера полей в конфигурации GitOps-инструмента. Захват владения флагом `--force-conflicts` допустим только при осознанной передаче контроля новому инструменту.

### Механизм Watch и архитектура Informer

Вместо циклического опроса (Polling) клиенты подписываются на изменения через HTTP GET с параметром `?watch=true`:

1.  **Потоковый HTTP-ответ:** Соединение остается открытым (HTTP chunked transfer encoding). По мере изменения объектов сервер отправляет JSON-события:
    *   `ADDED` — объект создан или попал в выборку фильтра;
    *   `MODIFIED` — объект изменен;
    *   `DELETED` — объект удален;
    *   `BOOKMARK` — контрольная точка, содержащая только актуальный `resourceVersion` без передачи полезной нагрузки (снижает риск получения 410 Gone при неактивных ресурсах).
2.  **Ошибка 410 Gone:** Если клиент отключился, а его последний `resourceVersion` был удален из журнала compact-операций `etcd`, сервер возвращает `410 Gone (too old resource version)`. Клиент обязан перехватить эту ошибку, выполнить полный List всех объектов и перезапустить Watch.
3.  **Архитектура Informer (библиотека `client-go`):**

```
kube-apiserver (Watch Stream)
       │
       ▼
   Reflector  ──────→  DeltaFIFO  ──────→  Indexer (In-Memory Cache)
                                                  │
                                                  ▼
                                       ResourceEventHandler
                                    (OnAdd / OnUpdate / OnDelete)
```

Informer исключает прямое обращение контроллеров к API-серверу при чтении данных: контроллер читает состояние из локального Indexer, а запросы к API отправляет только при необходимости мутации.

---

## Практические сценарии и конфигурация

### Сценарий 1: Прямое взаимодействие с REST API через curl (On-Premise / Bare-Metal)

В автоматизациях и сценариях восстановления узлов часто требуется выполнить запрос к API без установленного бинарного файла `kubectl`.

```bash
# 1. Определение адреса API-сервера из локального kubeconfig
APISERVER=$(grep 'server:' ~/.kube/config | head -1 | awk '{print $2}')
echo "API Server: $APISERVER"
# → API Server: https://192.168.10.10:6443

# 2. Получение временного Bearer-токена через TokenRequest API
TOKEN=$(kubectl create token default --duration=1h)

# 3. Путь к CA-сертификату кластера (на master-ноде или извлеченный из kubeconfig)
CACERT="/etc/kubernetes/pki/ca.crt"

# 4. Выполнение аутентифицированного запроса списка подов
curl -s --cacert "$CACERT" \
  --header "Authorization: Bearer $TOKEN" \
  -X GET "$APISERVER/api/v1/namespaces/default/pods" | jq -r '.items[].metadata.name'
# → nginx-deployment-77d7f6c77-4xkz9
# → nginx-deployment-77d7f6c77-8qmn2
```

### Сценарий 2: Разрешение конфликтов владения полями в Server-Side Apply

При совместной работе CI/CD пайплайна и ручных правок инженера возникает ошибка конфликта:

```bash
# Попытка применить манифест другим менеджером
kubectl apply --server-side --field-manager=ci-pipeline -f deploy.yaml
# → error: Apply failed with 1 conflict: conflict with "manual-admin": .spec.replicas

# Шаг 1: Инспекция владельцев конкретного поля
kubectl get deploy nginx -o json | jq '.metadata.managedFields[] | {manager: .manager, fields: .fieldsV1."f:spec"}'
# → {
# →   "manager": "manual-admin",
# →   "fields": {
# →     "f:replicas": {}
# →   }
# → }

# Шаг 2: Принудительный захват владения полем (Force Ownership)
kubectl apply --server-side --field-manager=ci-pipeline --force-conflicts -f deploy.yaml
# → deployment.apps/nginx serverside-applied
```

### Сценарий 3: Выполнение частичных обновлений через различные типы Patch

Сравнение применения различных типов патчей к объекту Deployment:

```bash
# Вариант А: JSON Patch (RFC 6902) — замена образа в первом контейнере
kubectl patch deployment nginx --type='json' -p='[
  {"op": "replace", "path": "/spec/template/spec/containers/0/image", "value": "nginx:1.27.4"}
]'
# → deployment.apps/nginx patched

# Вариант Б: Strategic Merge Patch — добавление переменной окружения без удаления существующих
kubectl patch deployment nginx --type='strategic' -p='{
  "spec": {
    "template": {
      "spec": {
        "containers": [
          {
            "name": "nginx",
            "env": [
              {"name": "ENVIRONMENT", "value": "production"}
            ]
          }
        ]
      }
    }
  }
}'
# → deployment.apps/nginx patched

# Вариант В: Server-Side Apply через curl (HTTP PATCH с application/apply-patch+yaml)
curl -s --cacert /etc/kubernetes/pki/ca.crt \
  --header "Authorization: Bearer $TOKEN" \
  --header "Content-Type: application/apply-patch+yaml" \
  -X PATCH "$APISERVER/apis/apps/v1/namespaces/default/deployments/nginx?fieldManager=curl-admin&force=true" \
  --data '
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
spec:
  template:
    metadata:
      labels:
        managed-by: api-curl
' | jq '.metadata.labels'
# → {
# →   "app": "nginx",
# →   "managed-by": "api-curl"
# → }
```

### Сценарий 4: Безопасное применение изменений в CI/CD с анализом diff и dry-run

В скриптах непрерывного развертывания команда `kubectl diff` возвращает код завершения `1`, если обнаружены изменения. При включенном `set -e` это приводит к аварийной остановке пайплайна:

```bash
#!/usr/bin/env bash
set -uo pipefail

MANIFEST="deploy.yaml"

echo "=== Этап 1: Валидация манифеста на стороне API-сервера (dry-run=server) ==="
kubectl apply -f "$MANIFEST" --dry-run=server
# → deployment.apps/nginx-app validated (server dry run)

echo "=== Этап 2: Сравнение конфигураций (diff) ==="
DIFF_RC=0
kubectl diff -f "$MANIFEST" || DIFF_RC=$?

case "$DIFF_RC" in
  0)
    echo "Изменения отсутствуют. Пропуск этапа применения."
    exit 0
    ;;
  1)
    echo "Обнаружены изменения в манифесте. Применение..."
    ;;
  *)
    echo "Критическая ошибка выполнения kubectl diff (код: $DIFF_RC)" >&2
    exit "$DIFF_RC"
    ;;
esac

echo "=== Этап 3: Декларативное применение через Server-Side Apply ==="
kubectl apply --server-side --field-manager=gitlab-ci -f "$MANIFEST"

echo "=== Этап 4: Детерминированное ожидание готовности раскатки ==="
kubectl rollout status deployment/nginx-app --timeout=180s
# → deployment "nginx-app" successfully rolled out
```

### Сценарий 5: Постраничная выгрузка (Pagination) для предотвращения OOM API-сервера

При запросе десятков тысяч объектов стандартный вызов `kubectl get` или GET-запрос без параметров может вызвать всплеск потребления памяти и аварийное завершение `kube-apiserver`:

```bash
# Использование chunk-size на стороне CLI
kubectl get pods -A --chunk-size=500 -o custom-columns=NAME:.metadata.name,NS:.metadata.namespace

# Выполнение постраничного запроса через REST API с маркером continue
# Первый запрос (размер страницы 100)
PAGE1=$(curl -s --cacert "$CACERT" -H "Authorization: Bearer $TOKEN" \
  "$APISERVER/api/v1/pods?limit=100")

# Извлечение токена следующей страницы
CONTINUE_TOKEN=$(echo "$PAGE1" | jq -r '.metadata.continue')

# Второй запрос с передачей токена пагинации
if [ -n "$CONTINUE_TOKEN" ] && [ "$CONTINUE_TOKEN" != "null" ]; then
  PAGE2=$(curl -s --cacert "$CACERT" -H "Authorization: Bearer $TOKEN" \
    "$APISERVER/api/v1/pods?limit=100&continue=$CONTINUE_TOKEN")
fi
```

---

## Операции и команды

### Исследование ресурсов и схем API

```bash
# Получение списка всех поддерживаемых типов ресурсов, их коротких имен и API-групп
kubectl api-resources --sort-by=name
# → NAME         SHORTNAMES   APIVERSION   NAMESPACED   KIND
# → configmaps   cm           v1           true         ConfigMap
# → deployments  deploy       apps/v1      true         Deployment
# → pods         po           v1           true         Pod

# Просмотр всех активированных версий API-групп
kubectl api-versions | sort
# → admissionregistration.k8s.io/v1
# → apps/v1
# → batch/v1
# → flowcontrol.apiserver.k8s.io/v1
# → v1

# Инспекция документации по конкретному полю схемы
kubectl explain deployment.spec.strategy.rollingUpdate.maxSurge
# → FIELD: maxSurge <IntOrString>
# → DESCRIPTION: The maximum number of pods that can be scheduled above the desired number of pods.

# Рекурсивный вывод всех доступных полей подресурса status
kubectl explain pods.status --recursive
```

### Проверка работоспособности и системные эндпоинты

```bash
# Проверка общей доступности кластера
kubectl cluster-info
# → Kubernetes control plane is running at https://192.168.10.10:6443

# Получение точной версии бинарников клиента и сервера в формате JSON
kubectl version -o json | jq '{client: .clientVersion.gitVersion, server: .serverVersion.gitVersion}'
# → {
# →   "client": "v1.32.2",
# →   "server": "v1.32.2"
# → }

# Детализированная проверка состояния внутренних подсистем API-сервера
kubectl get --raw /readyz?verbose
# → [+]ping ok
# → [+]log ok
# → [+]etcd ok
# → [+]informer-sync ok
# → readyz check passed

# Проверка метрик загрузки и задержек API-сервера
kubectl get --raw /metrics | grep -E '^apiserver_request_total' | head -3
# → apiserver_request_total{code="200",component="apiserver",resource="pods",verb="LIST"} 1420
# → apiserver_request_total{code="200",component="apiserver",resource="deployments",verb="GET"} 890
# → apiserver_request_total{code="403",component="apiserver",resource="secrets",verb="GET"} 4
```

### Управление и инспекция прав доступа (RBAC)

```bash
# Проверка собственных прав на создание секретов в текущем namespace
kubectl auth can-i create secrets
# → yes

# Проверка прав конкретного сервисного аккаунта (impersonation)
kubectl auth can-i delete pods -n production --as=system:serviceaccount:production:deploy-bot
# → no

# Проверка возможности изменения подресурса масштабирования
kubectl auth can-i update deployments/scale -n default
# → yes
```

### Потоковое наблюдение и отслеживание состояний

```bash
# Наблюдение за изменениями подов в реальном времени
kubectl get pods -n default --watch

# Наблюдение за системными событиями с фильтрацией по конкретному объекту
kubectl get events --field-selector involvedObject.name=nginx-deployment,involvedObject.kind=Deployment -w

# Ожидание перехода ресурса в целевое состояние с таймаутом
kubectl wait --for=condition=Available deployment/nginx --timeout=60s
# → deployment.apps/nginx condition met

# Ожидание завершения фонового Job
kubectl wait --for=condition=complete job/db-backup --timeout=300s
# → job.batch/db-backup condition met

# Ожидание удаления пода
kubectl wait --for=delete pod/terminating-pod --timeout=30s
# → pod/terminating-pod condition met
```

---

## Диагностика и устранение неполадок

### Матрица HTTP-статусов и рецепты устранения

| HTTP-код | Статус | Первопричина | Диагностическая команда | Метод устранения |
| :--- | :--- | :--- | :--- | :--- |
| **400** | Bad Request | Синтаксическая ошибка в теле запроса или некорректный Query-параметр | `kubectl apply -f manifest.yaml --v=8` | Проверить форматирование JSON/YAML, проверить соответствие типов в схеме. |
| **401** | Unauthorized | Токен отсутствует, истек срок действия, либо невалиден сертификат x509 | `kubectl get pods --v=6` (проверка заголовка Authorization) | Обновить kubeconfig, перевыпустить клиентский сертификат или токен через `kubectl create token`. |
| **403** | Forbidden | Недостаточно прав в RBAC или блокировка Admission-контроллером | `kubectl auth can-i <verb> <res> --as=<user>` | Создать RoleBinding/ClusterRoleBinding или скорректировать правила ValidatingWebhook/VAP. |
| **404** | Not Found | Ресурс удален либо указан неверный URI (ошибка в имени группы/версии) | `kubectl api-resources --api-group=<group>` | Проверить правильность регистра и множественного числа в URL ресурса. |
| **409** | Conflict | 1. Гонка версий OCC (`resourceVersion`).<br>2. Конфликт менеджеров полей SSA. | `kubectl get <res> -o json \| jq '.metadata.managedFields'` | Для OCC: перечитать объект и повторить операцию.<br>Для SSA: использовать `--force-conflicts` или разграничить поля. |
| **410** | Gone | Запрошенный `resourceVersion` удален из etcd по причине compaction | Проверить логи контроллера на сообщение `too old resource version` | Выполнить полный List ресурсов без `resourceVersion` и перезапустить Watch. |
| **413** | Payload Too Large | Размер объекта превысил лимит etcd (по умолчанию 1.5 МБ) или лимит аннотации CSA (256 КБ) | `ls -lh manifest.yaml` | Перейти с Client-Side Apply на Server-Side Apply; уменьшить ConfigMap/Secret. |
| **422** | Unprocessable Entity | Семантическая ошибка схемы (например, неизменяемое поле или ошибка регулярного выражения) | `kubectl apply -f manifest.yaml --dry-run=server` | Исправить значения полей манифеста согласно сообщению валидатора API. |
| **429** | Too Many Requests | Сработал лимит APF (API Priority and Fairness) или исчерпан лимит конкурентности | `kubectl get --raw /metrics \| grep apiserver_flowcontrol_rejected_requests_total` | Настроить PriorityLevelConfiguration или оптимизировать частоту запросов клиента. |
| **500** | Internal Error | Сбой внутри бинарного процесса `kube-apiserver` | `journalctl -u kube-apiserver -n 100 --no-pager` | Проверить свободную оперативную память на master-ноде и системные логи ядра (OOM-killer). |
| **503** | Service Unavailable | `kube-apiserver` запущен, но потерял связь с кластером `etcd` | `kubectl get --raw /readyz?verbose` | Проверить доступность и кворум узлов etcd (`etcdctl endpoint health`). |
| **504** | Gateway Timeout | Таймаут ответа от Admission Webhook или длительное ожидание в очереди APF | `kubectl get validatingwebhookconfigurations -o yaml` | Проверить сетевую доступность подов вебхуков, проверить таймауты `timeoutSeconds` в хуках. |

### Диагностические сценарии

#### 1. Диагностика разрыва Watch-соединений (HTTP 410 Gone)

Симптом: Контроллеры или агенты мониторинга перестают получать события и выдают ошибку:
`rpc error: code = ResourceExhausted desc = The resourceVersion is too old`

```bash
# 1. Проверка журнала compaction в etcd через метрики API-сервера
kubectl get --raw /metrics | grep etcd_debugging_mvcc_compact_revision

# 2. Проверка задержек обработки запросов etcd
kubectl get --raw /metrics | grep -E 'etcd_request_duration_seconds_bucket.*LIST' | head -5

# Корректный алгоритм обработки 410 Gone в клиентском коде:
# - Перехват ошибки HTTP 410
# - Сброс локальной переменной resourceVersion в пустую строку ""
# - Вызов API List для обновления локального кеша
# - Возобновление вызова Watch с полученной актуальной версией
```

#### 2. Диагностика зависания запросов из-за таймаутов Admission Webhooks (HTTP 504)

Симптом: Вызов `kubectl apply` или создание подов зависает на 10–30 секунд и завершается ошибкой `504 Gateway Timeout`.

```bash
# 1. Поиск зарегистрированных вебхуков в кластере
kubectl get mutatingwebhookconfigurations,validatingwebhookconfigurations

# 2. Инспекция настроек таймаутов и политики сбоя конкретного вебхука
kubectl get validatingwebhookconfigurations ingress-nginx-admission -o json | \
  jq '.webhooks[] | {name: .name, failurePolicy: .failurePolicy, timeoutSeconds: .timeoutSeconds}'
# → {
# →   "name": "validate.nginx.ingress.kubernetes.io",
# →   "failurePolicy": "Fail",
# →   "timeoutSeconds": 10
# → }

# 3. Проверка доступности пода, обслуживающего вебхук
kubectl get endpoints -A | grep admission
```

---

## Лучшие практики

1.  **Watch вместо Polling:** Никогда не выполняйте опрос состояния в цикле (`while true; do kubectl get ...; sleep 1; done`). Используйте `kubectl get --watch` или Informer в коде. Постоянный polling создает лавинообразную нагрузку на `kube-apiserver` и диск `etcd`.
2.  **Обязательное использование пагинации (`--chunk-size` / `limit`):** В скриптах и автоматизациях, запрашивающих списки ресурсов в масштабе всего кластера (`kubectl get pods -A`), всегда указывайте параметр `--chunk-size=500`. Запрос десятков тысяч объектов за один раз может вызвать аллокацию сотен мегабайт в памяти API-сервера и привести к его перезапуску по OOM.
3.  **Исключение управляемых полей из GitOps-манифестов:** При совместном использовании HPA и GitOps (ArgoCD, Flux) не описывайте поле `spec.replicas` в манифесте Deployment в Git-репозитории. Это исключает бесконечную войну правок (Ownership flapping) и позволяет HPA монопольно владеть этим полем через подресурс `/scale`.
4.  **Стандартизация на Server-Side Apply:** Полностью переходите на `kubectl apply --server-side`. SSA решает проблему ограничения размера аннотации `last-applied-configuration` (256 КБ), которая часто ломает деплой крупных CRD и сложных манифестов.
5.  **Контроль кодов возврата `kubectl diff` в автоматизациях:** Учитывайте, что `kubectl diff` возвращает код `0` при отсутствии изменений, `1` при наличии изменений и `>1` при ошибках соединения или валидации. Используйте явную обработку статуса (`case $rc in ...`), чтобы не прерывать пайплайн при стандартном коде `1`.
6.  **Мониторинг задержек API (SLI/SLO):** Отслеживайте в Prometheus метрики:
    *   `apiserver_request_duration_seconds_bucket` — задержка обработки запросов по группам и глаголам (SLI доступности Control Plane);
    *   `apiserver_current_inflight_requests` — количество параллельно обрабатываемых запросов;
    *   `apiserver_flowcontrol_rejected_requests_total` — количество запросов, отклоненных APF из-за перегрузки.
7.  **Запрет императивного `kubectl edit` в Production:** Ручные изменения через `kubectl edit` не оставляют следа в Git, нарушают модель версионирования и создают неявные конфликты с field manager в Server-Side Apply.

---

## См. также

*   **[Архитектура Control Plane](./control_plane_architecture.md)** — роль и место API-сервера в структуре компонентов кластера.
*   **[API Priority and Fairness (APF)](./api_priority_and_fairness.md)** — глубокое погружение в механизм приоритизации и очередей запросов к API.
*   **[Контроллеры допуска (Admission Controllers)](./admission_controllers.md)** — перехват, мутация и валидация объектов перед записью.
*   **[Метаданные, метки и аннотации](./metadata_and_labels.md)** — детальная структура метаданных и `managedFields`.
*   **[Пользовательские ресурсы (CRD)](./kubernetes_crd.md)** — расширение API собственными схемами и типами данных.
*   **[Операторы Kubernetes](./kubernetes_operators.md)** — реализация паттерна Controller и использование Informer/Client-Go.
*   **[RBAC: Управление доступом](../Security/rbac/rbac_overview.md)** — модель разграничения прав доступа субъектов к эндпоинтам API.
*   **[Kubeconfig и подключение](../Operations/kubeconfig_and_connection.md)** — настройка клиентских контекстов и сертификатов.
*   **[Мониторинг kube-apiserver](../MonitoringLogging/kube_apiserver_monitoring.md)** — мониторинг SLI/SLO, метрик и производительности API.
*   **[Аудит событий Kubernetes](../Security/audit.md)** — регистрация и анализ журнала событий безопасности API-сервера.
