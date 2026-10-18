# Garbage Collection и Owner References

**Актуально для:** Kubernetes 1.30–1.35+ (Bare-Metal / On-Premise)

---

## Определения

**Garbage Collection (GC, сборка мусора)** — комплекс механизмов Kubernetes, предназначенный для автоматической очистки неиспользуемых, осиротевших или завершённых ресурсов кластера и освобождения системных мощностей (etcd, дискового пространства и дескрипторов узлов). В Kubernetes функционирует двухуровневая модель GC:
1. **Control Plane GC** — контроллеры в составе `kube-controller-manager`, отслеживающие граф владения объектами API (`ownerReferences`), удаляющие зависимые ресурсы (каскадное удаление), очищающие завершённые поды (`PodGC`) и завершённые задачи (`TTL-after-finished`).
2. **Node-level GC (Kubelet)** — фоновые процессы агента `kubelet` на каждом рабочем узле, выполняющие сборку мусора неиспользуемых контейнерных образов (Image GC) и остановленных контейнеров/логов (Container GC).

**Owner References (ссылки на владельцев)** — метаданные в поле `metadata.ownerReferences` каждого ресурса, указывающие, какому вышестоящему объекту (владельцу) принадлежит данный зависимый объект (dependent). Служат основой для построения графа зависимостей (DAG).

**Cascading Deletion (каскадное удаление)** — процесс автоматического удаления зависимых объектов при удалении их владельца.

**Propagation Policy (политика распространения)** — стратегия каскадного удаления (`Foreground`, `Background`, `Orphan`), определяющая порядок и синхронность удаления владельца и его зависимых объектов.

**Finalizers (финализаторы)** — строковые маркеры в массиве `metadata.finalizers`, регистрируемые контроллерами. Наличие финализатора блокирует физическое удаление объекта из etcd, пока ответственный контроллер не выполнит необходимые процедуры очистки и не удалит свой маркер.

**Orphaned Objects (осиротевшие объекты)** — ресурсы, оставшиеся без владельца в результате отвязки (`propagationPolicy=Orphan`) либо удаления владельца без каскадного распространения.

**Pod Garbage Collector (Pod GC)** — контроллер в `kube-controller-manager`, который очищает старые завершённые поды (фазы `Succeeded` и `Failed`), поды, привязанные к удалённым узлам, и зависшие поды в статусе `Terminating`.

---

## Архитектура и принцип работы

### 1. Архитектура Control Plane GC (kube-controller-manager)

Сборщик мусора в составе `kube-controller-manager` оперирует на уровне объектов API-сервера и состоит из двух основных компонентов:

1. **GraphBuilder (построитель графа):**
   - Запускает информаторы (Informers/Monitors) для всех зарегистрированных в API типов ресурсов (включая CRD).
   - Отслеживает события добавления, изменения и удаления любых ресурсов через API Watch.
   - Поддерживает в оперативной памяти направленный ациклический граф зависимостей (DAG — Directed Acyclic Graph) всего кластера на основе UID объектов и их `ownerReferences`.
   - При обнаружении объекта с установленным полем `metadata.deletionTimestamp` помещает его в очередь обработки.

2. **GarbageCollector Controller (воркеры обработки):**
   - Извлекает объекты из очереди и запускает логику каскадного удаления: `AttemptToDeleteItem` или `AttemptToOrphanControls`.
   - Проверяет зависимости: если у объекта есть dependents, сборщик применяет заданную политику (`Foreground`, `Background` или `Orphan`).
   - Отправляет запросы на удаление зависимых объектов через стандартный Kubernetes REST API.

```
       API Server (Watch/Events)
                  │
                  ▼
         ┌──────────────────┐
         │   GraphBuilder   │  (Слушает все типы ресурсов,
         └────────┬─────────┘   строит DAG по UID и ownerReferences)
                  │
                  ▼
         ┌──────────────────┐
         │ GarbageCollector │  (Обрабатывает очереди AttemptToDelete
         └────────┬─────────┘   и AttemptToOrphan)
                  │
    ┌─────────────┼─────────────┐
    ▼             ▼             ▼
Foreground    Background     Orphan
(Finalizer)   (Асинхронно)  (Снятие ссылок)
```

### 2. Структура поля metadata.ownerReferences

Каждый объект Kubernetes может содержать массив ссылок на владельцев в `metadata.ownerReferences`:

```yaml
metadata:
  ownerReferences:
  - apiVersion: apps/v1
    kind: ReplicaSet
    name: web-app-7b8f6c9d
    uid: 4c3d2e1a-5b6c-7d8e-9f0a-1b2c3d4e5f6a
    controller: true          # Указывает на управляющий контроллер
    blockOwnerDeletion: true  # Блокирует удаление владельца до удаления этого объекта
```

#### Поля спецификации ownerReferences

| Поле | Тип | Назначение |
|:---|:---|:---|
| `apiVersion` | String | API-версия ресурса-владельца (например, `apps/v1`, `batch/v1`). |
| `kind` | String | Тип ресурса владельца (`Deployment`, `ReplicaSet`, `Job`). |
| `name` | String | Имя объекта-владельца в том же пространстве имён. |
| `uid` | String | Глобально уникальный UUID владельца (RFC 4122). Проверка по UID гарантирует, что при пересоздании объекта с тем же именем старые потомки не будут ошибочно связаны с новым владельцем. |
| `controller` | Boolean | Флаг `true` разрешён **только для одного** владельца в массиве. Он указывает, какой именно контроллер отвечает за reconciliation и жизненный цикл ресурса. Попытка назначить второй `controller: true` отклоняется API-сервером. |
| `blockOwnerDeletion` | Boolean | Если `true`, удаление владельца в режиме `Foreground` будет заблокировано финалайзером `foregroundDeletion` до тех пор, пока данный дочерний объект не будет полностью удален из etcd. |

### 3. Архитектурные правила связей и пространств имён

Kubernetes строго регламентирует правила связывания объектов через `ownerReferences`:

1. **Изоляция пространств имён (Namespace Boundary):**
   - Зависимый объект и его владелец **обязаны находиться в одном и том же пространстве имён**.
   - Кросс-неймспейс ссылки (`cross-namespace ownerReferences`) архитектурно **не поддерживаются**: Garbage Collector игнорирует такие связи, чтобы предотвратить эскалацию привилегий (нельзя из пространства имён `dev` захватить или удалить ресурс в `kube-system`).
2. **Кластерные и неймспейсные ресурсы (Cluster-scoped vs Namespaced):**
   - Кластерный ресурс (Cluster-scoped, например `ClusterRole`, `CustomResourceDefinition`) **может** быть владельцем ресурса в пространстве имён (Namespaced).
   - Ресурс в пространстве имён **не может** быть владельцем ресурса кластерного уровня (Cluster-scoped). При попытке связать их сборщик мусора отклоняет удаление кластерного ресурса через каскад.
3. **Прямая проверка связей:**
   - Garbage Collector проверяет только непосредственные ссылки первого уровня в графе. Транзитивное распространение вычисляется рекурсивно по узлам графа DAG.
4. **Отношения между StatefulSet и PersistentVolumeClaim (PVC):**
   - По умолчанию PVC, созданные через `volumeClaimTemplates` в StatefulSet, **не имеют** `ownerReferences` на StatefulSet. Это предотвращает случайную потерю постоянных данных при удалении или пересоздании контроллера.
   - Автоматическое удаление PVC регулируется отдельным механизмом — политикой `spec.persistentVolumeClaimRetentionPolicy` (`whenDeleted: Delete`, `whenScaled: Delete`), а не базовым каскадным GC.

### 4. Стратегии каскадного удаления (Propagation Policies)

Поведение сборщика мусора при удалении объекта задаётся параметром `propagationPolicy` в API или флагом `--cascade` в CLI `kubectl`:

```
1. Background (по умолчанию в REST API):
   DELETE Owner ──> API ставит deletionTimestamp ──> Owner удаляется немедленно ──>
                ──> Dependents обнаруживаются сборщиком ──> Dependents удаляются в фоне

2. Foreground:
   DELETE Owner ──> API добавляет finalizer 'foregroundDeletion' ──> Owner в Terminating ──>
                ──> Dependents удаляются сборщиком ──> Все Dependents удалены ──>
                ──> Сборщик снимает finalizer ──> Owner удаляется из etcd

3. Orphan:
   DELETE Owner ──> API добавляет finalizer 'orphanDependents' ──> Сборщик обнуляет ownerReferences у Dependents ──>
                ──> Сборщик снимает finalizer ──> Owner удаляется ──> Dependents продолжают жить
```

#### Сравнительный анализ стратегий

| Стратегия | Скорость ответа API | Состояние владельца | Безопасность ресурсов | Типичный сценарий использования |
|:---|:---|:---|:---|:---|
| **Background** | Мгновенно | Удаляется сразу из etcd | Высокая (потомки удаляются асинхронно) | Стандартное удаление Deployment, ReplicaSet, CronJob. |
| **Foreground** | Блокируется до очистки потомков | Переходит в статус `Terminating` | Максимальная (гарантия полного завершения зависимостей перед освобождением родителя) | Контролируемый вывод сервиса из эксплуатации, гарантированное закрытие сессий. |
| **Orphan** | Мгновенно | Удаляется сразу | Низкая (потомки остаются без контроллера) | Миграция подов под другой контроллер, замена контроллера без перезапуска подов. |

### 5. Взаимодействие со специальными сборщиками Control Plane

Помимо каскадного сборщика по `ownerReferences`, в Control Plane работают дополнительные сборщики мусора:

1. **Pod Garbage Collector (`PodGC`):**
   - Контроллер `podgc` в `kube-controller-manager` мониторит количество завершённых подов (`phase: Succeeded` или `Failed`).
   - Если число таких подов в кластере превышает лимит, заданный флагом `--terminated-pod-gc-threshold` (по умолчанию 12500), контроллер начинает удалять наиболее старые поды до возврата к пороговому значению.
   - Очищает "осиротевшие" поды (`orphaned pods`), назначенные на узлы, которые были удалены из кластера (`NodeNotFound`).
   - Очищает поды, зависшие в фазе `Terminating`, если сам узел прекратил существование.
2. **TTL-after-finished Controller:**
   - Контроллер в `kube-controller-manager`, обрабатывающий объекты `Job`.
   - Если в спецификации Job указано поле `spec.ttlSecondsAfterFinished`, контроллер отсчитывает указанное время с момента завершения (успешного или аварийного) и инициирует удаление Job вместе с его подами через каскадное удаление.
3. **Event Garbage Collection:**
   - Выполняется непосредственно `kube-apiserver`.
   - События (`Events`) имеют короткий жизненный цикл и автоматически вычищаются из etcd по истечении тайм-аута, заданного параметром `--event-ttl` (по умолчанию 1 час).

### 6. Архитектура Node-level GC (Kubelet)

На рабочих узлах сборка мусора выполняется локальным демоном `kubelet` независимо от Control Plane:

```
                  Kubelet Node GC
                         │
        ┌────────────────┴────────────────┐
        ▼                                 ▼
   Container GC                       Image GC
- Мертвые контейнеры              - Проверка FS (nodefs/imagefs)
- Устаревшие логи                 - HighThreshold (>80% -> запуск)
- Очистка sandboxes               - LowThreshold (<70% -> остановка)
- maximum-dead-containers         - imageMinimumGCAge
```

1. **Image Garbage Collection (сборка неиспользуемых образов):**
   - `kubelet` периодически опрашивает Container Runtime через CRI Image Service о занятом дисковом пространстве на файловой системе образов (`imagefs` или `nodefs`).
   - Управляется двумя пороговыми значениями:
     - `imageGCHighThresholdPercent` (по умолчанию 85%): при превышении данного процента занятого места запускается удаление образов.
     - `imageGCLowThresholdPercent` (по умолчанию 80%): удаление продолжается до тех пор, пока использование диска не снизится до этого порога.
   - Алгоритм удаляет образы в порядке **LRU (Least Recently Used)** — первыми удаляются образы, которые дольше всего не запускались.
   - Образы, используемые активными контейнерами, защищены от удаления.
   - Параметр `imageMinimumGCAge` (по умолчанию `2m`) задаёт минимальный возраст образа: образы младше этого возраста не удаляются, даже если превышен HighThreshold (защита от удаления свежескачанных слоёв во время rolling-update).
2. **Container Garbage Collection (сборка завершённых контейнеров):**
   - Очищает завершённые контейнеры, поды-песочницы (pod sandbox) и связанные с ними файлы логов `/var/log/pods/`.
   - Регулируется параметрами `KubeletConfiguration`:
     - `maximumDeadContainersPerContainer` (по умолчанию 1 или 2): сколько остановленных копий одного и того же контейнера сохранять для диагностики (`kubectl logs --previous`).
     - `maximumDeadContainers` (по умолчанию -1, без жесткого лимита, либо лимитируется пулом): максимальное общее количество завершённых контейнеров на узле.
     - `minimumGCAge` (по умолчанию 0s): минимальное время удержания мертвого контейнера перед возможностью его удаления сборщиком.

---

## Практические сценарии и конфигурация

### Сценарий 1: Инспекция и трассировка цепочки владения (DAG)

В повседневной эксплуатации SRE-инженеру необходимо проверять, какой контроллер управляет конкретным подом и блокирует ли дочерний объект удаление вышестоящего.

```bash
# 1. Проверка прямых владельцев пода
kubectl get pod web-app-7b8f6c9d-4x8zt -n production -o jsonpath='{range .metadata.ownerReferences[*]}Kind: {.kind} | Name: {.name} | Controller: {.controller} | BlockDeletion: {.blockOwnerDeletion}{"\n"}{end}'
# → Kind: ReplicaSet | Name: web-app-7b8f6c9d | Controller: true | BlockDeletion: true

# 2. Проверка владельца найденного ReplicaSet (цепочка к Deployment)
kubectl get rs web-app-7b8f6c9d -n production -o jsonpath='{range .metadata.ownerReferences[*]}Kind: {.kind} | Name: {.name} | Controller: {.controller}{"\n"}{end}'
# → Kind: Deployment | Name: web-app | Controller: true

# 3. Полная трассировка цепочки владения одной командой
POD="web-app-7b8f6c9d-4x8zt"; NS="production"
echo "=== Pod: $POD ==="
RS=$(kubectl get pod $POD -n $NS -o jsonpath='{.metadata.ownerReferences[?(@.controller==true)].name}')
echo "Managed by ReplicaSet: $RS"
DEPLOY=$(kubectl get rs $RS -n $NS -o jsonpath='{.metadata.ownerReferences[?(@.controller==true)].name}')
echo "Managed by Deployment: $DEPLOY"
# → === Pod: web-app-7b8f6c9d-4x8zt ===
# → Managed by ReplicaSet: web-app-7b8f6c9d
# → Managed by Deployment: web-app
```

### Сценарий 2: Поиск осиротевших ресурсов (без ownerReferences)

Осиротевшие поды ("голые поды", bare pods) опасны для инфраструктуры: при сбое узла или выполнении `kubectl drain` они не будут пересозданы планировщиком и могут быть потеряны.

```bash
# 1. Поиск всех подов в кластере без ownerReferences
kubectl get pods --all-namespaces -o json | \
  jq -r '.items[] | select(.metadata.ownerReferences == null or (.metadata.ownerReferences | length) == 0) | "\(.metadata.namespace)/\(.metadata.name)"'
# → default/debug-tools-test
# → monitoring/standalone-collector

# 2. Поиск подов без владельца на конкретном узле перед проведением drain
NODE="worker-node-01"
kubectl get pods --all-namespaces --field-selector spec.nodeName=$NODE -o json | \
  jq -r '.items[] | select(.metadata.ownerReferences == null or (.metadata.ownerReferences | length) == 0) | "\(.metadata.namespace)/\(.metadata.name)"'
# → default/manual-migration-pod
```

### Сценарий 3: Управление каскадным удалением через kubectl

В зависимости от задачи администратор может выбрать нужный тип каскада:

```bash
# Вариант А: Background каскад (по умолчанию)
# Быстрый возврат управления, удаление подов происходит асинхронно
kubectl delete deployment api-gateway -n production --cascade=background
# → deployment.apps "api-gateway" deleted

# Вариант Б: Foreground каскад
# Команда ожидает, пока все поды не завершат работу и не удалятся
kubectl delete deployment api-gateway -n production --cascade=foreground
# → deployment.apps "api-gateway" deleted

# Вариант В: Orphan каскад (сохранение подов для миграции или траблшутинга)
# Deployment удаляется, но связанные ReplicaSet и Pod продолжают работать
kubectl delete deployment api-gateway -n production --cascade=orphan
# → deployment.apps "api-gateway" deleted

# Проверяем, что поды остались работать:
kubectl get pods -n production -l app=api-gateway
# → NAME                           READY   STATUS    RESTARTS   AGE
# → api-gateway-5c9b6f874d-k9q2m   1/1     Running   0          42m
```

### Сценарий 4: Настройка параметров Control Plane GC (kube-controller-manager)

В production-кластерах с сотнями тысяч короткоживущих подов дефолтный лимит `--terminated-pod-gc-threshold=12500` приводит к разрастанию базы etcd и замедлению работы API. Рекомендуется снижать порог до 200–500.

Манифест `/etc/kubernetes/manifests/kube-controller-manager.yaml` на контрольных узлах:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: kube-controller-manager
  namespace: kube-system
spec:
  containers:
  - name: kube-controller-manager
    image: registry.k8s.io/kube-controller-manager:v1.31.2
    command:
    - kube-controller-manager
    - --bind-address=127.0.0.1
    - --leader-elect=true
    - --terminated-pod-gc-threshold=250   # Лимит завершенных подов перед запуском PodGC
    - --concurrent-gc-syncs=20          # Количество параллельных воркеров GarbageCollector
```

Проверка применения параметров:

```bash
kubectl get pod -n kube-system -l component=kube-controller-manager -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.containers[0].command}{"\n"}{end}' | grep -E "terminated-pod-gc-threshold|concurrent-gc-syncs"
# → kube-controller-manager-master-01: ["...","--terminated-pod-gc-threshold=250","--concurrent-gc-syncs=20"]
```

### Сценарий 5: Настройка Node GC в Kubelet (Image и Container GC)

Конфигурация параметров сборщика мусора узла в `/var/lib/kubelet/config.yaml`:

```yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration

# Image Garbage Collection
imageGCHighThresholdPercent: 80      # Начать удаление образов при достижении 80% диска
imageGCLowThresholdPercent: 70       # Очищать до тех пор, пока диск не освободится до 70%
imageMinimumGCAge: 5m                # Не удалять образы моложе 5 минут

# Container Garbage Collection
maximumDeadContainers: 100           # Максимум 100 завершенных контейнеров на узел
maximumDeadContainersPerContainer: 2 # Хранить не более 2 копий одного контейнера (для логов)
minimumGCAge: 1m                     # Минимальное время удержания мертвого контейнера
```

Применение настроек на рабочем узле без перезагрузки сервера:

```bash
systemctl daemon-reload
systemctl restart kubelet
systemctl status kubelet --no-pager
# → Active: active (running) since Sun 2026-10-18 11:45:00 UTC
```

### Сценарий 6: Автоматическая очистка завершённых Job (TTL-after-finished)

Для предотвращения захламления etcd объектами выполненных Job и их подов необходимо всегда указывать параметр `ttlSecondsAfterFinished`:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-schema-migration
  namespace: backend
spec:
  ttlSecondsAfterFinished: 300   # Удалить Job и связанные поды через 5 минут после завершения
  backoffLimit: 3
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: migrate
        image: internal-registry.local/backend/migrator:v2.4.1
        command: ["./run-migrations.sh"]
```

Проверка времени жизни и запланированного удаления:

```bash
kubectl get job db-schema-migration -n backend -o jsonpath='CompletionTime: {.status.completionTime} | StartTime: {.status.startTime}{"\n"}'
# → CompletionTime: 2026-10-18T11:50:00Z | StartTime: 2026-10-18T11:48:30Z
```

### Сценарий 7: Ручная установка ownerReferences для собственных операторов и автоматизаций

Если скрипт автоматизации или кастомный контроллер создаёт ConfigMap или Secret, привязанный к жизненному циклу сервиса, необходимо прописать `ownerReferences`:

```bash
# Получаем UID родительского Deployment
DEPLOY_UID=$(kubectl get deployment api-service -n production -o jsonpath='{.metadata.uid}')

# Создаем ConfigMap, привязанный к Deployment
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: api-service-dynamic-config
  namespace: production
  ownerReferences:
  - apiVersion: apps/v1
    kind: Deployment
    name: api-service
    uid: $DEPLOY_UID
    controller: false
    blockOwnerDeletion: true
data:
  features.json: '{"rate_limit": 500, "cache_enabled": true}'
EOF
# → configmap/api-service-dynamic-config created

# Проверка: при удалении Deployment api-service данный ConfigMap будет удален автоматически
```

---

## Операции и команды

Сводная таблица ключевых команд для работы со сборщиками мусора Kubernetes:

| Операция | Команда | Ожидаемый результат / вывод |
|:---|:---|:---|
| Удаление с фоновым каскадом (Background) | `kubectl delete deploy <name> --cascade=background` | `# → deployment.apps "<name>" deleted` (поды удаляются в фоне) |
| Удаление с синхронным каскадом (Foreground) | `kubectl delete deploy <name> --cascade=foreground` | `# → deployment.apps "<name>" deleted` (ожидание удаления подов) |
| Удаление без каскада (Orphan) | `kubectl delete deploy <name> --cascade=orphan` | `# → deployment.apps "<name>" deleted` (поды сохранены) |
| Поиск подов без владельцев во всех неймспейсах | `kubectl get pods -A -o json \| jq -r '.items[] \| select(.metadata.ownerReferences == null or (.metadata.ownerReferences \| length) == 0) \| "\(.metadata.namespace)/\(.metadata.name)"'` | `# → default/temp-pod` |
| Поиск подов с конкретным именем владельца | `kubectl get pods -n <ns> -o json \| jq -r '.items[] \| select(.metadata.ownerReferences[0].name=="<owner>") \| .metadata.name'` | `# → web-7d8b-xyz` |
| Проверка зависших финализаторов ресурса | `kubectl get <resource> <name> -n <ns> -o jsonpath='{.metadata.finalizers}'` | `# → ["kubernetes.io/foregroundDeletion"]` |
| Экстренная принудительная очистка финализаторов | `kubectl patch <resource> <name> -n <ns> -p '{"metadata":{"finalizers":null}}' --type=merge` | `# → <resource>.apps/<name> patched` |
| Просмотр логов GC контроллера | `kubectl logs -n kube-system kube-controller-manager-<node> \| grep -i "garbage"` | `# → I1018 11:20:01 garbagecollector.go:732] Processing "default/web"` |
| Просмотр событий очистки образов Kubelet | `journalctl -u kubelet -e \| grep -i "image garbage collection"` | `# → kubelet[1450]: Image garbage collection removed 12 images, reclaimed 4.1GB` |

---

## Диагностика и устранение неисправностей

### 1. Объект бесконечно зависает в статусе Terminating

**Симптом:** При выполнении `kubectl delete` объект (Pod, Namespace, CRD, Deployment) не удаляется и находится в статусе `Terminating` часы или дни.

**Причины:**
1. На объекте висит системный или пользовательский финализатор (`metadata.finalizers`), например `kubernetes.io/foregroundDeletion`, `kubernetes.io/pvc-protection` или финализатор кастомного оператора.
2. Контроллер, обязанный снять финализатор, аварийно остановлен, недоступен либо заблокирован admission-вебхуком.
3. В случае `foregroundDeletion` дочерний объект имеет `blockOwnerDeletion: true` и не может удалиться (например, под завис на стадии graceful shutdown из-за неотвечающего хранилища NFS/Ceph/iSCSI).

**Алгоритм диагностики и решения:**

```bash
# Шаг 1: Определить список финализаторов и причину блокировки
kubectl get deployment payment-service -n production -o yaml | grep -A 5 "finalizers:"
# →   finalizers:
# →   - kubernetes.io/foregroundDeletion
# →   - custom.operator.io/cleanup-hook

# Шаг 2: Проверить наличие зависших дочерних объектов с blockOwnerDeletion
DEPLOY_UID=$(kubectl get deployment payment-service -n production -o jsonpath='{.metadata.uid}')
kubectl get rs -n production -o json | \
  jq -r --arg uid "$DEPLOY_UID" '.items[] | select(.metadata.ownerReferences[]? | select(.uid==$uid and .blockOwnerDeletion==true)) | .metadata.name'
# → payment-service-589fc4779d

# Шаг 3: Если дочерний под завис в Terminating из-за CSI/Storage — решить проблему хранилища либо принудительно удалить под
kubectl delete pod payment-service-589fc4779d-q8w9r -n production --force --grace-period=0
# → Warning: Immediate deletion does not wait for confirmation...
# → pod "payment-service-589fc4779d-q8w9r" force deleted

# Шаг 4: Если контроллер удален безвозвратно и финализатор некому снять — экстренно патчим ресурс
kubectl patch deployment payment-service -n production -p '{"metadata":{"finalizers":[]}}' --type=merge
# → deployment.apps/payment-service patched
# → Объект немедленно удаляется из etcd
```

### 2. При удалении владельца зависимые объекты не удаляются (утечка ресурсов)

**Симптом:** Deployment удалён, однако ReplicaSet или поды продолжают работать в кластере.

**Причины:**
1. Удаление было выполнено с ключом `--cascade=orphan`.
2. Служебная учётная запись Garbage Collector (`system:controller:generic-garbage-collector`) не имеет RBAC-прав на чтение или удаление конкретных ресурсов (типично для некорректно настроенных CRD без предоставления прав контроллеру).
3. Разрыв связи по UID: владелец был пересоздан с тем же именем, но получил новый UID, вследствие чего дочерние объекты стали осиротевшими.

**Диагностика:**

```bash
# Шаг 1: Проверить логи kube-controller-manager на наличие ошибок прав GC
kubectl logs -n kube-system kube-controller-manager-master-01 | grep -E "garbagecollector.*Forbidden"
# → E1018 11:30:12 garbagecollector.go:420] failed to delete customresources.example.com/foo: User "system:controller:generic-garbage-collector" cannot delete resource "customresources" in API group "example.com"

# Шаг 2: Исправление прав RBAC для GC (добавление ClusterRoleBinding для generic-garbage-collector при необходимости)
kubectl create clusterrolebinding garbage-collector-crd-fix \
  --clusterrole=admin \
  --user=system:controller:generic-garbage-collector
# → clusterrolebinding.rbac.authorization.k8s.io/garbage-collector-crd-fix created
```

### 3. Перегрузка etcd при массовом каскадном удалении (GC Storm)

**Симптом:** При удалении крупного пространства имён или высокореплицированного сервиса (например, 2000 подов) резко возрастает задержка etcd (`etcd_disk_backend_commit_duration_seconds`), `kube-apiserver` начинает отвечать ошибками `504 Gateway Timeout` или `429 Too Many Requests`.

**Причина:** Garbage Collector генерирует тысячи одновременных запросов на удаление. Если `concurrent-gc-syncs` выставлен слишком высоко, API-сервер и etcd перегружаются операциями записи и compaction.

**Решение и профилактика:**
1. Снизить параметр `--concurrent-gc-syncs` в `kube-controller-manager` до стабильного уровня (10–20).
2. Настроить механизм **API Priority and Fairness (APF)** для изоляции запросов контроллеров от внешнего пользовательского трафика.
3. Масштабировать приложения ступенчато (scale down до 0 перед полным удалением Deployment/Namespace).

### 4. Kubelet DiskPressure: сбой Image GC на рабочем узле

**Симптом:** Узел переходит в статус `NotReady` или выставляет taint `node.kubernetes.io/disk-pressure:NoSchedule`. `kubelet` не удаляет старые образы.

**Причины:**
1. Все образы на узле помечены как используемые (например, десятки подов работают с разными образами без централизованного кэша).
2. Раздел диска заполнен не образами контейнеров, а системными логами (`/var/log/syslog`, `/var/log/messages`), логами подов (`/var/log/pods/`) либо дампом ядра. Image GC очищает **только** слои образов CRI (`/var/lib/containerd/` или `/var/lib/containers/storage`).
3. Ошибка связи kubelet со средой Container Runtime по сокету CRI.

**Диагностика и восстановление:**

```bash
# Шаг 1: Анализ использования дискового пространства на узле
df -hT /var/lib/kubelet /var/lib/containerd /var/log
# → Filesystem     Type  Size  Used Avail Use% Mounted on
# → /dev/nvme0n1p2 ext4  200G  182G   18G  91% /

# Шаг 2: Проверка логов сборщика мусора Kubelet
journalctl -u kubelet -n 100 --no-pager | grep -iE "imagegc|diskpressure"
# → kubelet[1230]: I1018 11:35:10 image_gc_manager.go:315] Disk usage on image filesystem is at 91%, which is over the high threshold (80%).
# → kubelet[1230]: E1018 11:35:12 image_gc_manager.go:330] Freeing 22891234 bytes failed: image is pinned or in use

# Шаг 3: Ручная очистка неиспользуемых образов через crictl
crictl rmi --prune
# → Deleted: sha256:7b8f9a0c1...
# → Deleted: sha256:4c2d1e0b9...

# Шаг 4: Проверка ротации логов подов
ls -lh /var/log/pods/*/*/*.log | sort -k5 -hr | head -n 5
# → Очистить или настроить containerLogMaxSize в KubeletConfiguration
```

---

## Лучшие практики (Best Practices)

1. **Тюнинг `--terminated-pod-gc-threshold` для Bare-Metal кластеров:**
   - Дефолтное значение 12500 рассчитано на сверхкрупные облачные кластеры с гигантским объемом памяти etcd. В Bare-metal/On-premise кластерах выставляйте значение в диапазоне **100–500**. Это предотвращает деградацию производительности etcd и ускоряет вывод списков `kubectl get pods`.
2. **Обязательное использование `ttlSecondsAfterFinished` в Job:**
   - Никогда не оставляйте `Job` и `CronJob` без явного тайм-аута очистки. Рекомендуемое значение для успешных задач: от `300` (5 минут) до `3600` (1 час). Этого достаточно для сбора логов системой мониторинга (Fluentbit/Vector/Loki) без риска забивания etcd.
3. **Безопасная настройка Kubelet Image GC:**
   - Всегда выдерживайте дельту (гистерезис) между `imageGCHighThresholdPercent` и `imageGCLowThresholdPercent` не менее **10–15%** (например, High=80%, Low=70%).
   - Слишком узкий диапазон (например, 85% и 84%) приводит к постоянному запуску сборщика, троттлингу ввода-вывода диска и повторному скачиванию базовых слоёв образов.
4. **Контроль `blockOwnerDeletion` в кастомных контроллерах:**
   - При разработке операторов или CRD включайте `blockOwnerDeletion: true` только тогда, когда дочерний объект должен выполнить обязательный grace-period (например, сбросить буфер на диск перед удалением родителя). Необоснованный `blockOwnerDeletion` приводит к зависанию ресурсов при сбоях оператора.
5. **Не допускайте смешивания жизненных циклов через ручные ссылки:**
   - Не привязывайте один независимый сервис в качестве владельца к другому равноправному сервису. Владелец должен строго доминировать по жизненному циклу (Controller Pattern).
6. **Мониторинг ключевых метрик Garbage Collector:**
   - `garbagecollector_controller_attempt_to_delete_latency_seconds` — задержка удаления объектов Control Plane GC.
   - `garbagecollector_controller_attempt_to_orphan_latency_seconds` — задержка перевода зависимостей в статус Orphan.
   - `kubelet_image_garbage_collected_total` — счетчик успешно удаленных образов на узле.
   - `kubelet_containers_gc_errors_total` — ошибки удаления мертвых контейнеров.

---

## Дополнительная информация

*   **[Метаданные, метки и аннотации](metadata_and_labels.md)** — структура полей `ownerReferences`, `finalizers` и `deletionTimestamp`.
*   **[Kubelet: Архитектура и компоненты](kubelet.md)** — детальное устройство демона узла, Resource Managers и Node GC.
*   **[Архитектура Control Plane](control_plane_architecture.md)** — устройство компонентов Control Plane и kube-controller-manager.
*   **[Job и CronJob](../Base/job.md)** — параметры `ttlSecondsAfterFinished` и управление пакетными заданиями.
*   **[ReplicaSet](../Base/replicaset.md)** — каскадное управление репликами и механизм Adoption/Release.
*   **[Deployment: Lifecycle Management](../Base/Deployment/lifecycle_management.md)** — управление жизненным циклом и стратегиями обновления.
*   **[Диагностика ошибок PodTerminating](../Troubleshooting/Common_Errors/PodTerminating/definitions.md)** — зависшие финализаторы и сборщик мусора подов.
*   **[Диагностика Image Pull и Image GC](../Troubleshooting/Common_Errors/PodImagePullErrors/definitions.md)** — пороговые параметры Image GC и DiskPressure.
