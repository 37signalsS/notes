# Взаимодействие с API Kubernetes

## Определение

Взаимодействие с **API-сервером Kubernetes** является основой управления кластером. `kube-apiserver` предоставляет RESTful интерфейс, через который пользователи (через CLI или UI) и внутренние контроллеры могут создавать, изменять, просматривать и удалять ресурсы.

**Ключевая роль:** API-сервер — это "входная дверь" и единственный компонент кластера, имеющий право на чтение и запись в базу данных `etcd`. Все взаимодействия строятся на принципах декларативности (мы описываем желаемое состояние, а кластер его достигает).

### Архитектура запроса к API

Каждый запрос к API-серверу проходит полный цикл обработки:

```
kubectl apply -f deploy.yaml
        │
        ▼
   API Server (HTTPS :6443)
        │
        ├── 1. Аутентификация (кто ты?) ──→ X.509 / Token / OIDC / Webhook
        │
        ├── 2. Авторизация (что тебе можно?) ──→ RBAC / ABAC / Webhook
        │
        ├── 3. Admission Control (соответствует ли?) ──→ Mutating → Validating
        │
        ├── 4. Объект валиден ──→ handlers.Parse() → Registry → Storage
        │
        └── 5. Запись в etcd ──→ Watch/Informer → контроллеры реагируют
```

**Точка отказа:** Если любой этап (2, 3) отклоняет запрос, объект не сохраняется. API-сервер возвращает HTTP-статус (401, 403, 409, 422 и др.).

---

## Структура API и Группы ресурсов

API Kubernetes организовано иерархически для обеспечения масштабируемости и возможности независимого развития различных функций без нарушения обратной совместимости.

### 1. Группы API (API Groups)
Ресурсы логически сгруппированы в API Groups.
*   **Core Group (Legacy):** Находится по пути `/api/v1`. Включает базовые ресурсы: `Pods`, `Services`, `Nodes`, `Namespaces`, `ConfigMaps`, `Secrets`. В манифестах поле `apiVersion` указывается просто как `v1`.
*   **Named Groups:** Находятся по пути `/apis/$GROUP_NAME/$VERSION` (например, `/apis/apps/v1`). Включают более сложные ресурсы: `Deployments` (в `apps`), `Jobs` (в `batch`), `NetworkPolicies` (в `networking.k8s.io`).

### 2. Версии API и Политика устаревания (Deprecation Policy)
Версионность позволяет Kubernetes тестировать новые функции и гарантировать стабильность старых.
*   **Alpha (`v1alpha1`):** Экспериментальные функции. Отключены по умолчанию. Могут быть удалены в любом релизе.
*   **Beta (`v1beta1`):** Код протестирован, включен по умолчанию. Схема может измениться. Обязательны для перехода в Stable.
*   **Stable (`v1`):** Полная поддержка и долгосрочная обратная совместимость (минимум 12 месяцев или 3 релиза).

> **Политика устаревания (Deprecation):** Когда ресурс переходит из Beta в Stable, старая Beta-версия объявляется устаревшей (deprecated) и полностью удаляется через несколько релизов. Пользователи обязаны мигрировать свои манифесты (используя `kubectl convert` или плагины Helm).

### 3. Объявление ресурсов (Resource Declaration)
Каждый объект Kubernetes описывается через стандартную структуру:
*   **`apiVersion`**: API-группа и версия (напр., `apps/v1`).
*   **`kind`**: Тип объекта (напр., `Deployment`).
*   **`metadata`**: Уникальные идентификаторы (`name`, `namespace`), а также `labels` и `annotations`.
*   **`spec`**: Желаемое состояние (описывается пользователем).
*   **`status`**: Фактическое состояние (заполняется только контроллерами Kubernetes).

---

## Продвинутые механизмы API

### 1. Watch (Наблюдение)
Вместо постоянного опроса (Polling) API-сервера, клиенты (например, `kubelet` или контроллеры) используют механизм **Watch**.
*   **Суть:** Клиент открывает постоянное HTTP-соединение с API-сервером и получает поток событий (Added, Modified, Deleted) для интересующих его ресурсов в реальном времени.
*   Это радикально снижает нагрузку на сеть и `etcd`.
*   Пример через CLI: `kubectl get pods --watch`.

**Watch и Bookmark:**
*   **Regular Watch:** Клиент отправляет `GET /api/v1/pods?watch=true`. API-сервер возвращает JSON-список текущих объектов, а затем — бесконечный поток событий.
*   **Bookmark Watch:** Клиент может запросить `?resourceVersion=X&watch=true` для получения событий начиная с определенной версии. Это позволяет переподключаться без потери данных.
*   **Error 410 Gone:** Если запрошенная `resourceVersion` слишком старая, API-сервер возвращает 410. Клиент должен выполнить полный List и начать Watch заново.

**Informer (оптимизация Watch):**
Прямой Watch на каждый ресурс неэффективен для контроллеров с десятками тысяч объектов. **Informer** — это кеширующий клиент, который:
1.  Выполняет полный List при старте.
2.  Открывает Watch и обновляет локальный кеш (in-memory store).
3.  Генерирует события (AddFunc, UpdateFunc, DeleteFunc) для контроллера.
4.  Автоматически переподключается при разрыве соединения.

Библиотека `client-go` предоставляет `SharedInformerFactory` — фабрику, которая переиспользует одно соединение Watch для разных типов ресурсов.

### 2. Server-Side Apply (SSA)
Традиционный метод `kubectl apply` вычисляет разницу (diff) между манифестом, текущим состоянием и скрытой аннотацией на стороне клиента.
**Server-Side Apply** переносит логику слияния на сторону API-сервера.
*   **Преимущества:** Позволяет нескольким контроллерам управлять разными полями одного объекта (Field Management) без конфликтов. Устраняет проблему превышения лимита размера аннотации `last-applied-configuration`.
*   **Пример:** `kubectl apply --server-side -f config.yaml`.
*   *Стандарт де-факто для GitOps-инструментов (ArgoCD, Flux) начиная с 2024 года.*

**Field Management (Управление полями):**
Каждое поле объекта имеет владельца (field manager). При изменении поля конфликтует тот менеджер, который пытается изменить поле, принадлежащее другому.

```bash
# Клиент "my-app" управляет полем spec.replicas
kubectl apply --server-side -f deploy.yaml --field-manager=my-app

# Принудительное перехват ownership (force)
kubectl apply --server-side -f deploy.yaml --field-manager=my-app --force-conflicts

# Просмотр владельцев полей
kubectl get deploy nginx -o json | jq '.metadata.managedFields'
```

**Конфликт и разрешение:**
*   **Без force:** Если `kubectl` и `Helm` пытаются управлять одним полем → ошибка 409 Conflict.
*   **С force:** Последний apply перехватывает ownership поля. Используйте `--force-conflicts` только когда точно знаете, что делаете.
*   **Auto-detection:** `kubectl` автоматически определяет field manager. По умолчанию это `kubectl-client-side-apply` или `kubectl-client-side-force`.

**Практический пример: HPA + Deployment без SSA:**
```
HPA управляет spec.replicas
kubectl apply --server-side -f deploy.yaml    # перехватывает spec.replicas
→ Conflict: HPA ownership lost → HPA перестает масштабировать
```
**Решение:** `kubectl apply --server-side -f deploy.yaml --field-manager=kubectl --force-conflicts`

---

## Основные способы взаимодействия

### 1. Инструмент командной строки (kubectl)
Основной инструмент администратора.
*   **Аутентификация:** Использует файл `kubeconfig` (обычно в `~/.kube/config`). Поддерживает переключение между кластерами (контекстами).
*   **Примеры:**
    ```bash
    kubectl get pods -A                 # Список подов во всех namespaces
    kubectl explain deployment.spec     # Документация по полям API
    kubectl api-resources               # Список всех доступных типов ресурсов (вкл. CRD)
    ```

**Полезные команды для работы с API:**

```bash
# Просмотр всех доступных API-ресурсов с группами и сокращениями
kubectl api-resources
# → NAME          SHORTNAMES   APIVERSION   NAMESPACED   KIND
# → pods          po           v1           true         Pod
# → deployments   deploy       apps/v1      true         Deployment

# Просмотр всех API-групп
kubectl api-versions
# → apps/v1
# → batch/v1
# → networking.k8s.io/v1

# Документация по конкретному полю (с вложенностью)
kubectl explain pod.spec.containers.resources.limits

# Проверка доступности конкретного ресурса
kubectl api-resources --api-group=apps

# Dry-run: проверка манифеста без применения (на стороне клиента)
kubectl apply -f deploy.yaml --dry-run=client -o yaml

# Dry-run: проверка манифеста через API-сервер (с валидацией)
kubectl apply -f deploy.yaml --dry-run=server

# Сравнение текущего состояния с манифестом
kubectl diff -f deploy.yaml

# Просмотр Events в реальном времени (по namespace)
kubectl get events -n default --watch

# Просмотр Events для конкретного объекта
kubectl get events --field-selector involvedObject.name=nginx,involvedObject.kind=Deployment

# Ожидание готовности ресурса (вместо sleep в скриптах)
kubectl wait --for=condition=Available deployment/nginx --timeout=300s
kubectl wait --for=condition=Ready pod -l app=nginx --timeout=120s
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded job/migrate --timeout=600s
kubectl wait --for=delete pod/test --timeout=60s

# Переключение контекста и namespace
kubectl config get-contexts                     # список всех контекстов
kubectl config use-context prod-cluster        # переключение контекста
kubectl config set-context --current --namespace=production  # смена namespace

# Просмотр Raw API (для отладки)
kubectl get --raw /api/v1/namespaces
kubectl get --raw /apis/apps/v1/namespaces/default/deployments

# Получение JSON-патча конкретного поля
kubectl get deploy nginx -o jsonpath='{.status.conditions[*].message}'

# Массовое обновление labels
kubectl label pods -l env=debug env- debug --overwrite

# Удаление всех ресурсов по label
kubectl delete pods -l env=test --grace-period=0 --force
```

### 2. Клиентские библиотеки (Client Libraries)
Официальные библиотеки (Go, Python, Java, C#) используются для разработки операторов и CI/CD скриптов.

**Пример на Python (`kubernetes-client`):**
```python
from kubernetes import client, config

# Загрузка конфигурации из ~/.kube/config или In-Cluster ServiceAccount
config.load_kube_config()

v1 = client.CoreV1Api()
# Получение списка подов
ret = v1.list_pod_for_all_namespaces(watch=False)
for pod in ret.items:
    print(f"{pod.metadata.namespace} / {pod.metadata.name}")
```

### 3. Прямые HTTP-запросы (REST)
Удобно для отладки или интеграции из систем, где нет клиентских библиотек. Для доступа требуется получить `Bearer Token` сервисного аккаунта.

**Пример прямого запроса:**
```bash
APISERVER=$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')
TOKEN=$(kubectl create token default)

curl -X GET $APISERVER/api/v1/namespaces/default/pods \
  --header "Authorization: Bearer $TOKEN" \
  --insecure
```

---

## Дополнительная информация

### Частые ошибки API и их диагностика

| HTTP-статус | Причина | Решение |
| :--- | :--- | :--- |
| **401 Unauthorized** | Невалидный/просроченный токен, неверный сертификат | Проверить `kubectl config view`, обновить токен/сертификат |
| **403 Forbidden** | Нет прав RBAC | `kubectl auth can-i <verb> <resource>` — проверить правила RBAC |
| **404 Not Found** | Ресурс не существует или неверное API-группа/версия | `kubectl api-resources` — проверить правильность имени |
| **409 Conflict** | Конфликт versions (optimistic locking) или SSA ownership | `kubectl get <resource> -o yaml` — проверить `resourceVersion` |
| **422 Unprocessable** | Ошибка валидации (неверная структура манифеста) | `kubectl apply --dry-run=server -f <file>` — проверить валидацию |
| **429 Too Many Requests** | Превышен rate limit API-сервера | Уменьшить частоту запросов, использовать Watch вместо Polling |
| **503 Service Unavailable** | API-сервер недоступен | Проверить `kubectl get nodes`, `kubectl -n kube-system get pods` |

```bash
# Быстрая диагностика: проверка доступа к API
kubectl cluster-info
# → Kubernetes control plane is running at https://k8s.example.com:6443

# Проверка версии API-сервера
kubectl version --short

# Проверка состояния API-сервера (liveness/readiness)
kubectl get --raw /livez?verbose
kubectl get --raw /readyz?verbose

# Проверка доступа к конкретному API-эндпоинту
kubectl get --raw /api/v1/namespaces/default/pods | jq '.items[].metadata.name' | head -5

# Диагностика RBAC
kubectl auth can-i list pods --as=system:serviceaccount:default:my-sa
kubectl auth can-i create deployments --as=admin --namespace=production

# Просмотр последних ошибок API-сервера
kubectl logs -n kube-system -l component=kube-apiserver --tail=50 | grep -i error
```

### Ограничения и известные особенности

*   **Лимит аннотации `last-applied-configuration`:** Клиентский `kubectl apply` хранит снимок манифеста в аннотации. При размере >256KB аннотация обрезается, и последующие apply ломаются. **Решение:** перейти на Server-Side Apply.
*   **Rate Limiting (APF):** API-сервер имеет встроенный механизм **API Priority and Fairness** (APF), который ограничивает количество запросов по приоритетам. При превышении лимита запросы получают HTTP 429 или长时间 блокируются. Мониторьте метрики `apiserver_request_total` и `apiserver_dropped_requests_total`.
*   **Pagination:** При запросе больших списков (>500-1000 объектов) используйте параметры `limit` и `continue` для постраничной загрузки. Без пагинации один запрос может вернуть мегабайты данных и вызвать таймаут.
*   **Watch reconnection:** При разрыве Watch-соединения клиент автоматически переподключается с последнего `resourceVersion`. Если `resourceVersion` слишком старый (>5 минут), API-сервер возвращает 410 Gone, и клиент должен выполнить полный List. Это нормальное поведение, но требует обработки в коде.
*   **Одноразовые токены:** `kubectl create token` создаёт временный токен (по умолчанию 1 час). В скриптах используйте ServiceAccount token с фиксированным TTL через TokenRequest API или long-lived Secret-based токены (deprecated в будущем).

### Best Practices

*   **Используйте Watch вместо Polling:** Вместо `kubectl get pods` в цикле (polling), используйте `kubectl get pods --watch` или клиентские библиотеки с Informer. Это снижает нагрузку на API-сервер в десятки раз.
*   **Пагинация для больших списков:** При запросе сотен/тысяч объектов используйте `kubectl get pods -A --chunk-size=100` или параметры `limit`/`continue` в API-запросах. Без пагинации один запрос может вернуть мегабайты данных и вызвать таймаут.
*   **Dry-run перед apply:** Всегда проверяйте манифесты перед применением: `kubectl apply -f <file> --dry-run=server`. Это проверяет валидацию схемы, RBAC-политики и Admission-контроллеры без фактического создания объекта.
*   **Используйте `kubectl diff`:** Перед `kubectl apply` выполняйте `kubectl diff -f <file>`, чтобы увидеть, что именно изменится. Это предотвращает нежелательные изменения. В CI/CD учитывайте коды завершения: `0` — различий нет, `1` — изменения обнаружены, `>1` — ошибка выполнения. При использовании `set -e` используйте явную обработку кода возврата, чтобы пайплайн не останавливался на штатном результате `1`.

    ```bash
    rc=0
    kubectl diff -f deployment.yaml || rc=$?

    case $rc in
      0) echo "Изменений нет" ;;
      1) echo "Обнаружены изменения" ;;
      *) echo "Ошибка kubectl diff"; exit "$rc" ;;
    esac
    ```

    `kubectl diff` не гарантирует успешного обновления приложения — фактическое состояние проверяется отдельно после применения изменений.
*   **Server-Side Apply для GitOps:** При работе с GitOps-инструментами (ArgoCD, Flux) всегда используйте `--server-side --force-conflicts`. Это предотвращает конфликты ownership между kubectl, Helm и ArgoCD.
*   **Избегайте `kubectl edit` в Production:** Императивные изменения через `kubectl edit` не версионируются и не воспроизводимы. Используйте декларативные манифесты + `kubectl apply`.
*   **Кешируйте результаты `kubectl api-resources`:** Эта команда может выполняться долго при большом количестве CRD. В скриптах кешируйте результат.
*   **Используйте `--output` форматы в скриптах:** Вместо парсинга текстового вывода используйте `-o json`, `-o yaml` или `-o jsonpath='{.field}'` для машинного чтения.
*   **Мониторинг API-сервера:** Отслеживайте метрики `apiserver_request_duration_seconds_bucket`, `apiserver_current_inflight_requests`, `etcd_request_duration_seconds_bucket` через Prometheus для раннего обнаружения проблем.

**См. также:**
*   **[Архитектура Control Plane](./control_plane_architecture.md)** — роль API-сервера в кластере.
*   **[Kubeconfig и подключение](../Operations/kubeconfig_and_connection.md)** — настройка клиентского доступа.
*   **[RBAC: Управление доступом](../Security/rbac/rbac_overview.md)** — авторизация запросов к API.
*   **[CRD: Пользовательские ресурсы](./kubernetes_crd.md)** — расширение API собственными типами.
