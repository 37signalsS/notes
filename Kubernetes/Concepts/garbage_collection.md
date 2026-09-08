# Garbage Collection и Owner References

## Определение

**Garbage Collection (GC)** — механизм Kubernetes, который автоматически удаляет объекты, оставшиеся без владельца (owner) после удаления родительского объекта. Механизм основан на поле `ownerReferences` в метаданных каждого объекта и обеспечивает каскадное управление жизненным циклом ресурсов.

Без Garbage Collection удаление Deployment привело бы к «осиротевшим» ReplicaSet и Pod, которые продолжали бы работать, но уже не управлялись бы никаким контроллером.

---

## Архитектура Owner References

### Структура поля ownerReferences

Каждый объект Kubernetes содержит в `metadata.ownerReferences` список ссылок на владельцев:

```yaml
metadata:
  ownerReferences:
  - apiVersion: apps/v1
    kind: ReplicaSet
    name: web-abc123
    uid: a1b2c3d4-e5f6-7890-abcd-ef1234567890
    controller: true          # единственный «основной» владелец
    blockOwnerDeletion: true  # блокирует удаление владельца до завершения удаления этого объекта
```

### Поля записи ownerReferences

| Поле | Описание |
|:---|:---|
| `apiVersion` | API-группа и версия владельца (`apps/v1`, `batch/v1`) |
| `kind` | Тип ресурса владельца (`ReplicaSet`, `Job`, `Deployment`) |
| `name` | Имя владельца в рамках Namespace |
| `uid` | Глобально уникальный идентификатор владельца (UUID) |
| `controller` | `true` у **единственного** контроллера, управляющего этим объектом. Остальные записи — `false`. Используется GC для определения «основного» владельца |
| `blockOwnerDeletion` | Если `true`, удаление владельца будет **заблокировано**, пока зависимый объект не будет физически удален из etcd |

### Кто создаёт ownerReferences

API-сервер автоматически заполняет `ownerReferences` при создании объектов через контроллеры:

- **ReplicaSet** → создаёт Pod'ы с `ownerReferences` на себя
- **Deployment** → создаёт ReplicaSet с `ownerReferences` на себя
- **Job** → создаёт Pod'ы с `ownerReferences` на себя
- **DaemonSet** → создаёт Pod'ы с `ownerReferences` на себя
- **StatefulSet** → создаёт Pod'ы и PVC с `ownerReferences` на себя

Для **кастомных контроллеров** (Operator, Custom Controller) ownerReferences создаются вручную или через логику контроллера.

---

## Каскадное удаление (Cascade Deletion)

Kubernetes Garbage Collector отслеживает граф зависимостей между объектами и удаляет их при удалении владельца.

### Три стратегии удаления

Политика удаления задаётся через параметр `propagationPolicy` в запросе `kubectl delete`:

#### 1. Background (по умолчанию)

```
Удаление Owner → API ставит deletionTimestamp → GC удаляет Owner →
→ GC обнаруживает orphaned dependent → GC удаляет dependent
```

- Owner удаляется **сразу** из etcd
- dependent-объекты удаляются GC **после** удаления владельца
- Подходящ для большинства сценариев

```bash
kubectl delete rs web-api                           # propagationPolicy=Background по умолчанию
kubectl delete rs web-api --cascade=background      # явное указание
```

#### 2. Foreground

```
Удаление Owner → API ставит deletionTimestamp → GC удаляет dependent →
→ dependent удалены → GC удаляет Owner
```

- Owner **не удаляется** из etcd, пока все dependent не будут удалены
- Owner переходит в состояние `Terminating` (видимое через `kubectl get`)
- Подходящ, когда нужно **дождаться** полного удаления зависимых объектов

```bash
kubectl delete rs web-api --cascade=foreground
```

#### 3. Orphan

```
Удаление Owner → API удаляет Owner → dependent остаются без владельца
```

- Owner удаляется **сразу**
- dependent-объекты **не удаляются** и становятся «осиротевшими»
- Подходящ для миграций, когда нужно сохранить Pod'ы

```bash
kubectl delete rs web-api --cascade=orphan
```

> **Важно:** Осиротевшие Pod'ы **не пересоздаются** контроллером при сбоях. Если узел с таким Pod'ом упадет, Pod будет потерян безвозвратно.

---

## Цепочка владения (Ownership Chain)

Kubernetes поддерживает **многоуровневые** цепочки владения:

```
Deployment → ReplicaSet → Pod
     ↓            ↓         ↓
  ReplicaSet   Pod'ы     Container
```

При удалении Deployment:
1. Deployment помечается на удаление
2. ReplicaSet получает `deletionTimestamp` (GC обрабатывает)
3. ReplicaSet помечается на удаление
4. Pod'ы получают `deletionTimestamp` (GC обрабатывает)
5. Все объекты удаляются из etcd

### Правила цепочки

- У одного объекта может быть **несколько** владельцев (но только один `controller: true`)
- `blockOwnerDeletion: true` создаёт последовательную блокировку: пока dependent не удалён, владелец не может быть удалён
- GC проверяет только **прямых** владельцев (не транзитивно)

---

## Controller vs Non-Controller Owner

Поле `controller` в `ownerReferences` разделяет два типа владельцев:

| Тип | Роль | Пример |
|:---|:---|:---|
| **Controller** (`controller: true`) | Управляет жизненным циклом объекта, отвечает за reconciliation | ReplicaSet управляет Pod |
| **Non-Controller** (`controller: false`) | Имеет ссылку на объект, но не управляет им | Service ссылается на Pod через ownerReference |

Только **один** владелец может иметь `controller: true`. Если контроллер пытается назначить `controller: true` объекту, у которого уже есть контроллер, API-сервер вернёт ошибку.

---

## Взаимодействие с Finalizers

Garbage Collection и Finalizers работают совместно:

```
kubectl delete pod web-0
    ↓
1. API ставит deletionTimestamp
2. Проверяются finalizers
3. Если finalizer есть → объект НЕ удаляется из etcd
4. Контроллер удаляет свой finalizer
5. Когда finalizers пуст → GC удаляет объект
```

Стандартные finalizers, связанные с GC:

| Finalizer | Назначение |
|:---|:---|
| `foregroundDeletion` | Устанавливается при `--cascade=foreground`. Удаляется GC после удаления всех dependent |
| `orphanDependents` | Устанавливается при `--cascade=orphan`. Удаляется GC после «осиротения» dependent |

---

## Практические сценарии

### Просмотр ownerReferences

```bash
# Кому принадлежит Pod
kubectl get pod <pod-name> -o jsonpath='{.metadata.ownerReferences}'
# → [{"apiVersion":"apps/v1","kind":"ReplicaSet","name":"web-abc123","uid":"...","controller":true}]

# Кому принадлежит ReplicaSet
kubectl get rs <rs-name> -o jsonpath='{.metadata.ownerReferences}'
# → [{"apiVersion":"apps/v1","kind":"Deployment","name":"web","uid":"...","controller":true}]

# Цепочка: Pod → RS → Deployment
kubectl get pod <pod-name> -o jsonpath='{range .metadata.ownerReferences[*]}Owner: {.kind}/{.name}{"\n"}{end}'
```

### Определение осиротевших Pod (без владельца)

```bash
# Pod'ы без ownerReferences
kubectl get pods --all-namespaces -o json | \
  jq -r '.items[] | select(.metadata.ownerReferences == null or .metadata.ownerReferences == []) | "\(.metadata.namespace)/\(.metadata.name)"'

# Или через jsonpath
kubectl get pods --all-namespaces -o jsonpath='{range .items[?(@.metadata.ownerReferences==null)]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'
```

### Каскадное удаление Deployment

```bash
# Background (по умолчанию) — быстрое удаление
kubectl delete deployment web

# Foreground — дождаться удаления всех Pod
kubectl delete deployment web --cascade=foreground

# Orphan — сохранить Pod'ы (для миграции)
kubectl delete deployment web --cascade=orphan
```

### Восстановление осиротевших Pod

```bash
# Найти осиротевшие Pod
kubectl get pods -l app=web -o json | \
  jq '.items[] | select(.metadata.ownerReferences == null or .metadata.ownerReferences == []) | .metadata.name'

# Создать новый ReplicaSet с теми же метками (если Pod ещё живы)
kubectl apply -f - <<EOF
apiVersion: apps/v1
kind: ReplicaSet
metadata:
  name: web-recovered
  labels:
    app: web
spec:
  replicas: 0
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
      - name: web
        image: nginx
EOF

# Поды с меткой app=web НЕ будут пересозданы (RS видит существующие Pod)
# Но новые Pod'ы при масштабировании будут созданы этим RS
```

### Создание ownerReferences вручную (для кастомных контроллеров)

```bash
# Добавить ownerReference к существующему Pod
kubectl patch pod <pod-name> --type='json' -p='[
  {"op": "add", "path": "/metadata/ownerReferences", "value": [
    {
      "apiVersion": "apps/v1",
      "kind": "ReplicaSet",
      "name": "my-rs",
      "uid": "<rs-uid>",
      "controller": true,
      "blockOwnerDeletion": true
    }
  ]}
]'
```

---

## Диагностика проблем с GC

### Зависшие удаления (Stuck Deletion)

| Симптом | Причина | Решение |
|:---|:---|:---|
| Объект в `Terminating` бесконечно | Finalizer не удаляется контроллером | `kubectl patch <resource> <name> -p '{"metadata":{"finalizers":null}}' --type=merge` |
| Owner удалён, dependent остаются | GC-контроллер не обработал удаление | Проверить логи `kube-controller-manager`, увеличить `--garbage-collector-sync-period` |
| `blockOwnerDeletion` блокирует удаление | Dependent ещё не удалён | Дождаться удаления dependent или удалить его вручную |
| OwnerReference указывает на несуществующий объект | UID владельца изменился (пересоздание) | Удалить осиротевший объект или исправить ownerReference |

### Проверка состояния GC

```bash
# События GC (в логах controller-manager)
kubectl logs -n kube-system kube-controller-manager-<master> | grep -i garbage

# Количество осиротевших объектов
kubectl get pods --all-namespaces -o json | \
  jq '[.items[] | select(.metadata.ownerReferences == null or .metadata.ownerReferences == [])] | length'

# Проверка specific owner
kubectl get rs -o json | jq '.items[] | select(.metadata.ownerReferences[0].name=="web") | .metadata.name'
```

---

## Дополнительная информация

*   **[Метаданные, метки и аннотации](metadata_and_labels.md)** — поля `ownerReferences`, `finalizers`, `deletionTimestamp`
*   **[ReplicaSet](../Base/replicaset.md)** — механизм владения и каскадное удаление
*   **[Deployment: Lifecycle Management](../Base/Deployment/lifecycle_management.md)** — управление через ownerReferences
*   **[ArgoCD: Deletion and Cleanup](../../GitOps/ArgoCD/argocd_deletion_and_cleanup.md)** — Propagation Policy в контексте GitOps
