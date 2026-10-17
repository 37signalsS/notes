# ReplicaSet

**Актуально для:** Kubernetes 1.30–1.35+ (Bare-Metal / On-Premise)

## Определения

**ReplicaSet** — это базовый контроллер рабочей нагрузки в Kubernetes (API-группа `apps/v1`), поддерживающий стабильный пул идентичных экземпляров подов (**Pod**) в кластере. Его ключевая задача — непрерывное приведение фактического количества работающих подов с заданными метками к желаемому числу (`spec.replicas`).

В отличие от контроллеров верхнего уровня ([Deployment](./Deployment/index.md)), `ReplicaSet` не управляет жизненным циклом обновлений (rolling updates, канареечные выкатки, сохранение истории ревизий), а решает исключительно задачу количественной репликации и поддержания доступности.

### Ключевые термины и концепции

*   **Одиночный под (Ad-hoc Pod) как точка отказа:** Запуск подов без контроллера — грубая ошибка архитектуры. При аппаратном сбое узла, перезапуске демона `kubelet` или плановом обслуживании (`kubectl drain`) ad-hoc поды безвозвратно уничтожаются. Контроллер ReplicaSet гарантирует воссоздание экземпляров на доступных узлах.
*   **Историческая преемственность:** `ReplicaSet` заменил устаревший объект первого поколения **ReplicationController** (API `v1`). Главное техническое отличие — поддержка **Set-based селекторов** (операторы `In`, `NotIn`, `Exists`, `DoesNotExist`), тогда как `ReplicationController` поддерживал только простое равенство (**Equality-based**).
*   **Цикл согласования (Reconciliation Loop):** Непрерывный процесс в управляющем контуре `kube-controller-manager`, сравнивающий желаемое состояние (`spec`) с фактическим (`status`) и устраняющий расхождения через вызовы Kubernetes API.
*   **Селектор меток (Label Selector):** Критерий фильтрации, по которому ReplicaSet находит «свои» поды. Спецификация `spec.selector` является **неизменяемой (immutable)** после создания объекта.
*   **Хеш шаблона пода (`pod-template-hash`):** Служебная метка, вычисляемая контроллером Deployment на основе 32-битного алгоритма FNV-1a от `spec.template` и внедряемая в ReplicaSet и дочерние поды. Гарантирует уникальность пространства имен меток между разными ревизиями одного приложения.
*   **Стоимость удаления пода (`pod-deletion-cost`):** Механизм приоритезации удаления реплик при уменьшении масштаба (downscaling) через аннотацию `controller.kubernetes.io/pod-deletion-cost`.
*   **Усыновление и освобождение (Adoption & Orphaning):** Механизм, при котором контроллер связывает себя с бесхозными подами, подходящими под его селектор (усыновление), либо отпускает поды, если их метки были изменены (освобождение).

---

## Основные концепции и архитектура

### Архитектура контроллера в kube-controller-manager

Управление ReplicaSet осуществляется демоном `replicaset-controller` в составе бинарного файла `kube-controller-manager`:

```
+---------------------------------------------------------------------------------+
|                            kube-controller-manager                              |
|                                                                                 |
|  +-----------------------+     Watch Events     +----------------------------+  |
|  |  Informer Cache (RS)  | <------------------ |       kube-apiserver       |  |
|  +-----------------------+                      +----------------------------+  |
|             |                                                  ^                |
|             v                                                  |                |
|  +-----------------------+                              Create/Delete Pods      |
|  |       Workqueue       |                                     |                |
|  +-----------------------+                                     |                |
|             |                                                  |                |
|             v                                                  |                |
|  +-----------------------+     Reconcile        +----------------------------+  |
|  |   Worker Goroutines   | -------------------> |    Reconciliation Loop     |  |
|  +-----------------------+                      +----------------------------+  |
+---------------------------------------------------------------------------------+
```

1.  **Informer & Lister:** Контроллер подписывается на поток событий (Watch API) изменений ReplicaSet и Pod, сохраняя локальный кэш состояния для минимизации нагрузки на etcd.
2.  **Workqueue (Очередь задач):** При обнаружении дельты ключ ресурса (`namespace/name`) помещается в очередь с механизмом экспоненциальной задержки при ошибках (rate-limiting).
3.  **SyncHandler (Согласование):** Воркер извлекает ключ, опрашивает локальный кэш и сопоставляет список существующих подов с селектором ReplicaSet.
4.  **Атомарные мутации через API:** Если подов меньше целевого числа — отправляются запросы `POST /api/v1/namespaces/{ns}/pods`. Если больше — запросы `DELETE`.

### Алгоритм пакетного создания (Slow-Start Batching)

Для защиты `kube-apiserver` и базы данных `etcd` от взрывной нагрузки (thundering herd problem) при масштабном развертывании (например, увеличение с 0 до 500 реплик) контроллер использует экспоненциальный алгоритм **Slow-Start**:

*   В первой итерации цикла контроллер создает **1 под**.
*   При успешном создании лимит удваивается: **2, 4, 8, 16, 32, 64, 128, 256...**
*   Если на каком-либо шаге создание пода завершается ошибкой (исчерпание квоты, отклонение admission-вебхуком), пакетная обработка немедленно прерывается. Контроллер переходит в режим ожидания следующей итерации очереди, предотвращая перегрузку API бесплодными запросами.

### Алгоритм выбора жертв при масштабировании вниз (Downscaling Priority)

Когда администратор или HPA уменьшает `spec.replicas`, контроллер выбирает поды для удаления не случайным образом, а по строгому детерминированному алгоритму (реализация функции `controller.ActivePods.Less`):

```
                                  [Кандидаты на удаление]
                                             |
                                             v
                         1. Поды в процессе завершения (Terminating)?
                                 /                       \
                              [Да]                       [Нет]
                                |                          |
                       (Удаляются первыми)                 v
                                            2. Поды без назначенного узла (Pending)?
                                                    /                 \
                                                 [Да]                 [Нет]
                                                   |                    |
                                           (Удаляются первыми)          v
                                                         3. Меньшая аннотация pod-deletion-cost?
                                                                 /                 \
                                                              [Да]                 [Нет]
                                                                |                    |
                                                        (Удаляются первыми)          v
                                                                     4. Больше реплик на одном узле?
                                                                             /                 \
                                                                          [Да]                 [Нет]
                                                                            |                    |
                                                                    (Удаляются первыми)          v
                                                                                 5. Неготовые (Not Ready)?
                                                                                         /                 \
                                                                                      [Да]                 [Нет]
                                                                                        |                    |
                                                                                (Удаляются первыми)          v
                                                                                             6. Меньшее время готовности?
                                                                                                     /                 \
                                                                                                  [Да]                 [Нет]
                                                                                                    |                    |
                                                                                            (Удаляются первыми)          v
                                                                                                         7. Более молодые поды
                                                                                                         (CreationTimestamp)
```

1.  **Поды в процессе завершения:** Поды с установленным `metadata.deletionTimestamp` удаляются в первую очередь.
2.  **Неназначенные поды (Pending):** Поды, которые `kube-scheduler` еще не назначил на конкретный узел (`pod.spec.nodeName == ""`).
3.  **Аннотация `controller.kubernetes.io/pod-deletion-cost`:** Под с наименьшим числовым значением удаляется раньше (диапазон значений: от `-2147483648` до `2147483647`).
4.  **Колокация на узлах (Topology Balance):** Контроллер группирует поды по узлам и выбирает кандидатов с узлов, где запущено наибольшее количество реплик данного ReplicaSet. Это сохраняет отказоустойчивость и балансировку по зонам/серверам.
5.  **Готовность (Readiness State):**
    *   Поды в статусе `Pending` удаляются раньше `Running`.
    *   Поды, у которых условие `Ready: False` (не прошедшие readinessProbe), удаляются раньше готовых (`Ready: True`).
6.  **Стаж готовности:** Если оба пода готовы, удаляется тот, который находится в состоянии готовности меньшее время (`podReadyTime`).
7.  **Время создания (CreationTimestamp):** При абсолютном равенстве предыдущих критериев удаляется наиболее молодой под (с самым поздним временем создания).

### Механизм владения (OwnerReferences, Adoption и Orphaning)

Связь между ReplicaSet и Pod осуществляется через системное поле `metadata.ownerReferences`:

```yaml
metadata:
  ownerReferences:
  - apiVersion: apps/v1
    kind: ReplicaSet
    name: web-backend-7b64f4c9c
    uid: a812b1d3-3759-4b14-8743-1e24bc557a11
    controller: true
    blockOwnerDeletion: true
```

*   **Флаг `controller: true`:** Указывает, что данный ReplicaSet является непосредственным управляющим владельцем. У пода может быть несколько `ownerReferences` (например, финалайзеры), но управляющий контроллер с `controller: true` всегда только один.
*   **Adoption (Усыновление):** Если в кластере создается под, метки которого совпадают с селектором ReplicaSet, и у пода нет управляющего контроллера (`controllerRef == nil`), ReplicaSet атомарно регистрирует свое владение через `PATCH`-запрос к API.
*   **Release (Освобождение):** Если метки пода изменяются администратором так, что перестают удовлетворять `spec.selector`, контроллер удаляет ссылку на себя из `ownerReferences`. Поскольку счетчик реплик уменьшается, контроллер создает новый под взамен ушедшего.
*   **Каскадное удаление (Garbage Collection):**
    *   **Foreground:** ReplicaSet переходит в статус удаления, ожидает завершения всех зависимых подов, после чего удаляется сам.
    *   **Background (по умолчанию в kubectl):** Сам ReplicaSet удаляется немедленно, а сборщик мусора API-сервера удаляет дочерние поды в фоне.
    *   **Orphan (`--cascade=orphan`):** ReplicaSet удаляется, но поле `ownerReferences` у подов очищается. Поды продолжают работать как изолированные ad-hoc экземпляры.

### Статусные поля и условия (Conditions)

Объект ReplicaSet возвращает детальную информацию о своем состоянии в блоке `status`:

*   `status.replicas`: Общее количество обнаруженных в кластере подов с подходящим селектором.
*   `status.fullyLabeledReplicas`: Число подов, шаблон которых полностью удовлетворяет селектору.
*   `status.readyReplicas`: Число подов, успешно прошедших проверку `readinessProbe`.
*   `status.availableReplicas`: Число подов, остававшихся в состоянии `Ready` не менее `spec.minReadySeconds`.
*   `status.observedGeneration`: Числовое поколение метаданных объекта, зафиксированное контроллером. Если `metadata.generation > status.observedGeneration`, контроллер еще не успел обработать последние изменения спецификации.
*   `status.conditions`: Массив системных условий. Ключевое условие для ReplicaSet — **`ReplicaFailure`**:
    *   Выставляется в `status: "True"`, если контроллер не может создать под (причины: `FailedCreate`, исчерпание `ResourceQuota`, отказ Admission Webhook, недействительный ServiceAccount).

---

## Практические сценарии и конфигурация

### Эталонный production-манифест ReplicaSet (Bare-Metal / On-Premise)

Манифест промышленного уровня с жестким ограничением привилегий, пробами доступности, политикой распределения по физическим серверам и бюджетом деградации.

```yaml
apiVersion: apps/v1
kind: ReplicaSet
metadata:
  name: api-gateway-v1
  namespace: production
  labels:
    app.kubernetes.io/name: api-gateway
    app.kubernetes.io/instance: api-gateway-prod
    app.kubernetes.io/version: "1.28.2"
    app.kubernetes.io/component: backend
    app.kubernetes.io/part-of: core-infrastructure
    app.kubernetes.io/managed-by: manual
spec:
  replicas: 4
  minReadySeconds: 15
  selector:
    matchLabels:
      app.kubernetes.io/name: api-gateway
      app.kubernetes.io/instance: api-gateway-prod
  template:
    metadata:
      labels:
        app.kubernetes.io/name: api-gateway
        app.kubernetes.io/instance: api-gateway-prod
        app.kubernetes.io/version: "1.28.2"
    spec:
      terminationGracePeriodSeconds: 60
      # Защита от запуска привилегированных контейнеров
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      # Равномерное распределение по физическим узлам (Anti-Affinity / Topology Spread)
      topologySpreadConstraints:
      - maxSkew: 1
        topologyKey: kubernetes.io/hostname
        whenUnsatisfiable: DoNotSchedule
        labelSelector:
          matchLabels:
            app.kubernetes.io/name: api-gateway
            app.kubernetes.io/instance: api-gateway-prod
      containers:
      - name: gateway
        image: internal-registry.corp.local/core/api-gateway:v1.28.2
        imagePullPolicy: IfNotPresent
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        ports:
        - name: http
          containerPort: 8080
          protocol: TCP
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 1000m
            memory: 1024Mi
        # Быстрый отказ при инициализации
        startupProbe:
          httpGet:
            path: /healthz/startup
            port: http
          failureThreshold: 30
          periodSeconds: 2
        # Контроль жизнеспособности процесса
        livenessProbe:
          httpGet:
            path: /healthz/liveness
            port: http
          initialDelaySeconds: 0
          periodSeconds: 10
          timeoutSeconds: 2
          failureThreshold: 3
        # Контроль включения в балансировку трафика
        readinessProbe:
          httpGet:
            path: /healthz/readiness
            port: http
          initialDelaySeconds: 0
          periodSeconds: 5
          timeoutSeconds: 2
          successThreshold: 1
          failureThreshold: 2
        lifecycle:
          preStop:
            exec:
              command: ["/bin/sh", "-c", "sleep 15"]
        volumeMounts:
        - name: tmp-dir
          mountPath: /tmp
      volumes:
      - name: tmp-dir
        emptyDir:
          sizeLimit: 128Mi
```

### Изоляция дефектного пода для глубокого анализа (Quarantine / Forensics)

В SRE-практике часто возникает ситуация: один под из пула начинает течь по памяти, отдавать HTTP 500 или потреблять 100% CPU. Стандартный `kubectl delete pod` уничтожит процесс и сотрет доказательства (coredump, временные файлы, открытые сокеты).

**Решение через освобождение (Release):** Смена метки пода выводит его из-под селектора ReplicaSet. Контроллер считает, что реплика потеряна, и мгновенно создает чистый под взамен. Старый под переходит в изолированное состояние и продолжает работать для снятия дампов.

```bash
# 1. Находим проблемный под в пуле
kubectl get pods -n production -l app.kubernetes.io/name=api-gateway -o wide
# → NAME                 READY   STATUS    RESTARTS   AGE   IP             NODE
# → api-gateway-v1-4k2x1   1/1     Running   0          42m   10.244.3.89    worker-node-03
# → api-gateway-v1-9z8m4   1/1     Running   3          40m   10.244.1.112   worker-node-01

# 2. Изолируем под, перезаписав ключевую метку приложения
kubectl label pod api-gateway-v1-9z8m4 -n production app.kubernetes.io/name=quarantine --overwrite
# → pod/api-gateway-v1-9z8m4 labeled

# 3. Проверяем реакцию ReplicaSet: создан новый под взамен изолированного
kubectl get pods -n production -l app.kubernetes.io/name=api-gateway
# → NAME                 READY   STATUS    RESTARTS   AGE
# → api-gateway-v1-4k2x1   1/1     Running   0          43m
# → api-gateway-v1-new01   1/1     Running   0          5s

# 4. Проверяем изолированный под: он жив, но трафик через Service на него больше не идет
kubectl get pod api-gateway-v1-9z8m4 -n production --show-labels
# → NAME                 READY   STATUS    RESTARTS   AGE   LABELS
# → api-gateway-v1-9z8m4   1/1     Running   3          41m   app.kubernetes.io/name=quarantine,...

# 5. Проводим системную криминалистику на узле worker-node-01 через сокет CRI (containerd)
# crictl ps | grep api-gateway
# crictl exec -it <container-id> sh
# gdb /proc/<pid>/exe <pid>
```

### Тонкое управление масштабированием вниз через pod-deletion-cost

Если воркеры обрабатывают длинные задачи (например, пересчет отчетов или рендеринг), при автоматическом масштабировании HPA не должен удалять под, выполняющий вычисления прямо сейчас.

Приложение может динамически выставлять через Kubernetes API или Downward API аннотацию стоимости удаления:

```bash
# Воркер начал длительную транзакцию: поднимаем стоимость (защита от удаления)
kubectl annotate pod worker-batch-v1-m98pl -n batch \
  controller.kubernetes.io/pod-deletion-cost="100000" --overwrite
# → pod/worker-batch-v1-m98pl annotated

# Воркер завершил задачу и простаивает: снижаем стоимость до минимума
kubectl annotate pod worker-batch-v1-m98pl -n batch \
  controller.kubernetes.io/pod-deletion-cost="-1000" --overwrite
# → pod/worker-batch-v1-m98pl annotated

# При выполнении масштабирования вниз контроллер гарантированно удалит под со значением -1000
kubectl scale rs worker-batch-v1 -n batch --replicas=3
```

### Ручное бесшовное обновление (Blue-Green / Canary) на сырых ReplicaSet

Контроллер ReplicaSet не выполняет rolling update. Изменение поля `spec.template` затронет только **новые** поды, создаваемые после удаления старых. Чтобы обновить сервис без простоев на уровне чистых ReplicaSet:

```bash
# Шаг 1: Разворачиваем второй ReplicaSet (Green) с версией v2 и нулевым числом реплик
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: ReplicaSet
metadata:
  name: web-api-v2
  namespace: default
  labels:
    app: web-api
    version: v2
spec:
  replicas: 0
  selector:
    matchLabels:
      app: web-api
      version: v2
  template:
    metadata:
      labels:
        app: web-api
        version: v2
    spec:
      containers:
      - name: nginx
        image: nginx:1.27.4-alpine
        ports:
        - containerPort: 80
EOF
# → replicaset.apps/web-api-v2 created

# Шаг 2: Прогреваем и проверяем 1 канареечную реплику v2
kubectl scale rs web-api-v2 --replicas=1
# → replicaset.apps/web-api-v2 scaled

# Шаг 3: Сервис с селектором 'app: web-api' автоматически направляет часть трафика на v2
# После успешного smoke-тестирования переключаем емкость:
kubectl scale rs web-api-v2 --replicas=3
kubectl scale rs web-api-v1 --replicas=0
# → replicaset.apps/web-api-v2 scaled
# → replicaset.apps/web-api-v1 scaled

# Шаг 4: Удаляем старый ReplicaSet после подтверждения стабильности
kubectl delete rs web-api-v1
# → replicaset.apps "web-api-v1" deleted
```

> [!WARNING]
> Команда `kubectl rollout restart rs/<name>` **не поддерживается** в Kubernetes:
> ```bash
> kubectl rollout restart rs api-gateway-v1
> # → error: cannot restart replicasets.apps "api-gateway-v1": resource not supported
> ```
> Перезапуск группы подов возможен только через поэтапное удаление подов `kubectl delete pod` либо через контроллер верхнего уровня [Deployment](./Deployment/index.md).

---

## Операции и команды

### Оперативное управление и диагностика

```bash
# Проверка текущего статуса реплик
kubectl get rs -n production api-gateway-v1
# → NAME             DESIRED   CURRENT   READY   AGE
# → api-gateway-v1   4         4         4       2d4h

# Детальная инспекция событий и условий контроллера
kubectl describe rs -n production api-gateway-v1
# → Conditions:
# →   Type             Status  Reason
# →   ReplicaFailure   False   NoFailure
# → Events:
# →   Type    Reason            Age   From                   Message
# →   ----    ------            ----  ----                   -------
# →   Normal  SuccessfulCreate  5m    replicaset-controller  Created pod: api-gateway-v1-x4b91

# Атомарное масштабирование с защитой от гонок (Race Condition Guard)
# Масштабирование применится только если текущее число реплик равно строго 4
kubectl scale rs api-gateway-v1 -n production --replicas=8 --current-replicas=4
# → replicaset.apps/api-gateway-v1 scaled

# Попытка масштабирования при несовпадении текущего числа реплик завершится отказом
kubectl scale rs api-gateway-v1 -n production --replicas=8 --current-replicas=3
# → error: Expected requesters to be 3, but got 4

# Масштабирование «в ноль» для временного останова нагрузки
kubectl scale rs api-gateway-v1 -n production --replicas=0
# → replicaset.apps/api-gateway-v1 scaled

# Просмотр всех подов, принадлежащих конкретному ReplicaSet
kubectl get pods -n production -l app.kubernetes.io/name=api-gateway,app.kubernetes.io/instance=api-gateway-prod
# → NAME                 READY   STATUS    RESTARTS   AGE
# → api-gateway-v1-4k2x1   1/1     Running   0          45m
# → api-gateway-v1-new01   1/1     Running   0          2m

# Просмотр системных условий статуса в формате JSON
kubectl get rs api-gateway-v1 -n production -o jsonpath='{.status.conditions}' | jq .
# → [
# →   {
# →     "type": "ReplicaFailure",
# →     "status": "False",
# →     "lastTransitionTime": "2026-10-15T12:00:00Z"
# →   }
# → ]
```

### Аудит и системный поиск аномалий ReplicaSet по всему кластеру

```bash
# 1. Поиск всех ReplicaSet в кластере, у которых число готовых подов меньше желаемого
kubectl get rs -A -o json | jq -r '
  .items[] | 
  select(.status.replicas > 0 and (.status.readyReplicas // 0) < .spec.replicas) | 
  "\(.metadata.namespace)/\(.metadata.name) -> Desired: \(.spec.replicas), Ready: \(.status.readyReplicas // 0)"
'
# → production/billing-worker-v1 -> Desired: 5, Ready: 3
# → default/legacy-redis -> Desired: 2, Ready: 0

# 2. Поиск осиротевших ReplicaSet, не управляемых Deployment (прямой запуск)
kubectl get rs -A -o json | jq -r '
  .items[] | 
  select((.metadata.ownerReferences // []) | map(select(.kind == "Deployment")) | length == 0) | 
  "\(.metadata.namespace)/\(.metadata.name)"
'
# → custom-system/raw-operator-rs
# → monitoring/standalone-collector

# 3. Выгрузка событий сбоев создания подов (FailedCreate) за последнее время
kubectl get events -A --field-selector reason=FailedCreate --sort-by='.lastTimestamp'
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Матрица типовых отказов

| Симптом | Корневая причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `spec.replicas` задано, но поды не создаются вообще (`CURRENT = 0`) | Исчерпана квота `ResourceQuota`, сбой `LimitRange` или запрет Admission Webhook | `kubectl describe rs <name>` → раздел `Events` и condition `ReplicaFailure` | Расширить квоту `kubectl edit resourcequota`, проверить доступность mutating/validating вебхуков |
| Поды зависают в статусе `Pending` | Нехватка CPU/RAM на узлах, несовпадение `nodeSelector`, `taints` без `tolerations` | `kubectl describe pod <pod-name>` → раздел `Events` (`0/16 nodes available`) | Добавить вычислительные мощности в кластер, оптимизировать `resources.requests`, скорректировать affinity |
| `READY = 0`, но контейнеры работают (`CURRENT = DESIRED`) | Падает `readinessProbe` либо не истек интервал прогрева `minReadySeconds` | `kubectl describe pod <name>` → `Readiness probe failed: HTTP 500` | Исправить код проверки готовности, проверить сетевую связность с локальной БД/кэшем |
| Ошибка `The ReplicaSet ... is invalid: spec.selector: Invalid value` | Попытка изменить селектор существующего ReplicaSet | `kubectl apply -f rs.yaml` возвращает ошибку валидации поля | Поле `spec.selector` неизменяемо (immutable). Создать новый RS с новым именем или использовать Deployment |
| HPA постоянно сбрасывает значение `replicas` | Конфликт владельца: администратор выполняет `kubectl scale` при активном HPA | В событиях HPA и RS видны постоянные скачки числа реплик | Масштабировать только через объект HPA (`spec.minReplicas`/`spec.maxReplicas`), либо удалить HPA |
| Один ReplicaSet захватил поды другого приложения | Пересечение селекторов меток (Label Selector Collision) | `kubectl get pods --show-labels` выявляет одинаковые метки у разных сервисов | Добавить разделяющие метки (например, `app.kubernetes.io/instance` или хеш `pod-template-hash`) |
| Задержка создания реплик >30 секунд | Перегрузка очередей воркеров `kube-controller-manager` | Метрика Prometheus `workqueue_depth{name="replicaset"}` растет | Увеличить ресурсы процессора мастер-узла, проверить задержки записи в etcd (`etcd_disk_wal_fsync_duration_seconds`) |

### Пошаговый сценарий: разбор сбоя ReplicaFailure при исчерпании квоты

Если в пространстве имен настроена `ResourceQuota`, при достижении лимита контроллер ReplicaSet не сможет отправить запрос на создание пода в API:

```bash
# Шаг 1: Проверяем статус контроллера
kubectl get rs -n dev-team payment-processor
# → NAME                DESIRED   CURRENT   READY   AGE
# → payment-processor   5         2         2       10m

# Шаг 2: Извлекаем системное условие сбоя
kubectl get rs -n dev-team payment-processor -o jsonpath='{.status.conditions[?(@.type=="ReplicaFailure")]}' | jq .
# → {
# →   "type": "ReplicaFailure",
# →   "status": "True",
# →   "lastTransitionTime": "2026-10-17T18:12:00Z",
# →   "reason": "FailedCreate",
# →   "message": "pods \"payment-processor-8b4d1\" is forbidden: exceeded quota: compute-quota, requested: pods=1, used: pods=10, limited: pods=10"
# → }

# Шаг 3: Проверяем фактическое использование квоты в пространстве имен
kubectl describe resourcequota compute-quota -n dev-team
# → Name:            compute-quota
# → Resource         Used  Hard
# → --------         ----  ----
# → pods             10    10

# Шаг 4: Устраняем дефицит путем корректировки квоты администратором
kubectl patch resourcequota compute-quota -n dev-team --type='merge' -p '{"spec":{"hard":{"pods":"20"}}}'
# → resourcequota/compute-quota patched

# Шаг 5: Контроллер автоматически подхватывает событие и завершает репликацию
kubectl get rs -n dev-team payment-processor
# → NAME                DESIRED   CURRENT   READY   AGE
# → payment-processor   5         5         5       12m
```

---

## Рекомендации и Best Practices

1.  **Используйте Deployment вместо ReplicaSet для прикладных задач:** Прямое использование манифестов ReplicaSet оправдано только при создании кастомных операторов, фреймворков оркестрации или специализированных пайплайнов. Во всех остальных сценариях слой [Deployment](./Deployment/index.md) предоставляет автоматические откаты, rolling updates и контроль версий.
2.  **Всегда задавайте `readinessProbe` и `minReadySeconds`:** Без проб готовности поле `status.readyReplicas` всегда приравнивается к работающим контейнерам, и трафик балансировщика пойдет на непрогретые приложения. Параметр `minReadySeconds: 15-30` защитит от каскадного падения кластера, если сервис аварийно завершается через 5 секунд после запуска.
3.  **Используйте флаг `--current-replicas` в скриптах автоматизации:** При вызове `kubectl scale` из bash-скриптов или CI/CD всегда указывайте ожидаемое исходное число реплик. Это защитит от случайной перезаписи состояния, если в этот момент сработал внешний автоскейлер.
4.  **Соблюдайте стандарты разметки Kubernetes (Recommended Labels):** Всегда применяйте префиксы `app.kubernetes.io/name`, `app.kubernetes.io/instance`, `app.kubernetes.io/component`. Избегайте примитивных меток вроде `app: web`, провоцирующих конфликты захвата подов чужими контроллерами.
5.  **Защищайте пул реплик с помощью PodDisruptionBudget (PDB):** При плановом выводе узлов на обслуживание (`kubectl drain`) PDB гарантирует, что контроллер выселения не удалит больше реплик, чем допустимо для SLA:
    ```yaml
    apiVersion: policy/v1
    kind: PodDisruptionBudget
    metadata:
      name: api-gateway-pdb
      namespace: production
    spec:
      minAvailable: 75%
      selector:
        matchLabels:
          app.kubernetes.io/name: api-gateway
    ```
6.  **Контролируйте распределение по узлам:** Используйте `topologySpreadConstraints` с ключом `kubernetes.io/hostname` и правилом `whenUnsatisfiable: DoNotSchedule`, чтобы предотвратить запуск всех 4 реплик на одном физическом сервере.

---

## Мониторинг и алертинг (SRE / Observability)

### Метрики экспортера kube-state-metrics

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `kube_replicaset_spec_replicas` | Gauge | Желаемое количество реплик согласно манифесту (`spec.replicas`). |
| `kube_replicaset_status_replicas` | Gauge | Фактическое количество обнаруженных контроллером подов. |
| `kube_replicaset_status_ready_replicas` | Gauge | Количество реплик, успешно прошедших проверку готовности (`readinessProbe`). |
| `kube_replicaset_status_observed_generation` | Gauge | Поколение объекта, синхронизированное контроллером. |
| `kube_replicaset_metadata_generation` | Gauge | Текущее поколение метаданных объекта. |
| `kube_replicaset_owner` | Gauge | Информация о родительском объекте (Deployment). Позволяет фильтровать бесхозные RS. |

### Внутренние метрики kube-controller-manager

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `workqueue_depth{name="replicaset"}` | Gauge | Текущая глубина очереди синхронизации ReplicaSet. Рост говорит о насыщении контроллера. |
| `workqueue_queue_duration_seconds_bucket{name="replicaset"}` | Histogram | Время ожидания ключа в очереди до начала обработки воркером. |
| `workqueue_work_duration_seconds_bucket{name="replicaset"}` | Histogram | Время непосредственного выполнения одного цикла согласования ReplicaSet. |

### Промышленные правила алертинга (Prometheus Alerting Rules)

```yaml
groups:
- name: kubernetes-replicaset-alerts
  rules:
  # Деградация пула реплик: число готовых подов меньше желаемого более 10 минут
  - alert: KubeReplicaSetUnavailableReplicas
    expr: |
      (
        kube_replicaset_spec_replicas{job="kube-state-metrics"} > 0
      ) 
      and 
      (
        kube_replicaset_status_ready_replicas{job="kube-state-metrics"} 
        < 
        kube_replicaset_spec_replicas{job="kube-state-metrics"}
      )
    for: 10m
    labels:
      severity: warning
      tier: platform
    annotations:
      summary: "Деградация пула реплик в ReplicaSet {{ $labels.namespace }}/{{ $labels.replicaset }}"
      description: "ReplicaSet {{ $labels.replicaset }} в пространстве имен {{ $labels.namespace }} не может обеспечить требуемое число готовых подов (доступно: {{ $value }}, требуется: {{ query \"kube_replicaset_spec_replicas{namespace='\" $labels.namespace \"',replicaset='\" $labels.replicaset \"'}\" }}). Проверьте события: kubectl describe rs -n {{ $labels.namespace }} {{ $labels.replicaset }}."
      runbook_url: "https://wiki.corp.local/sre/runbooks/k8s-rs-degraded"

  # Контроллер не успевает обрабатывать изменения конфигурации (дрифт поколения)
  - alert: KubeReplicaSetGenerationMismatch
    expr: |
      kube_replicaset_metadata_generation{job="kube-state-metrics"} 
      != 
      kube_replicaset_status_observed_generation{job="kube-state-metrics"}
    for: 15m
    labels:
      severity: critical
      tier: control-plane
    annotations:
      summary: "Рассинхронизация поколения ReplicaSet {{ $labels.namespace }}/{{ $labels.replicaset }}"
      description: "Контроллер kube-controller-manager не применил изменения спецификации для {{ $labels.replicaset }} более чем за 15 минут. Возможна перегрузка control-plane или зависание очереди workqueue."

  # Аномальный рост очереди воркеров ReplicaSet на управляющем узле
  - alert: KubeControllerManagerReplicaSetQueueStall
    expr: |
      workqueue_depth{job="kube-controller-manager", name="replicaset"} > 50
    for: 5m
    labels:
      severity: warning
      tier: control-plane
    annotations:
      summary: "Очередь задач replicaset-controller перегружена"
      description: "Глубина очереди workqueue для ReplicaSet превышает 50 элементов в течение 5 минут на инстансе {{ $labels.instance }}. Проверьте загрузку CPU мастера и задержки etcd."
```

---

## Дополнительная информация

### Сравнительный анализ контроллеров рабочей нагрузки

| Критерий | ReplicaSet | Deployment | StatefulSet | DaemonSet |
| :--- | :--- | :--- | :--- | :--- |
| **Основное назначение** | Поддержание стабильного числа одинаковых реплик | Декларативное обновление и версионирование сервисов | Идентичность сетевых имен и сохранение дискового состояния | Запуск строго по одному экземпляру на каждом узле |
| **Стратегия обновлений** | Только ручная (пересоздание подов) | Автоматический RollingUpdate или Recreate | Порядковый RollingUpdate (`Partition`) | Поузельный RollingUpdate (`maxUnavailable`) |
| **Хранилище (Volumes)** | Общие тома (NFS/Ceph/emptyDir) | Общие тома (NFS/Ceph/emptyDir) | Индивидуальные диски через `volumeClaimTemplates` | Локальные пути хоста (`hostPath`) или emptyDir |
| **Сетевая идентификация** | Случайные имена (`rs-name-xyz`) | Случайные имена через RS | Детерминированные имена (`app-0, app-1`) | Имена на основе хеша узла |
| **История ревизий** | Отсутствует | Хранится в подчиненных ReplicaSet | Хранится в `ControllerRevision` | Хранится в `ControllerRevision` |

### См. также

*   **[Deployment: архитектура и управление жизненным циклом](./Deployment/index.md)** — контроллер оркестрации над ReplicaSet.
*   **[Deployment: диагностика и устранение неисправностей](./Deployment/troubleshooting.md)** — углубленный траблшутинг выкаток и статусов `ReplicaFailure`.
*   **[Пробы в Kubernetes (Probes)](./probes.md)** — тонкая настройка `readinessProbe`, `livenessProbe` и `startupProbe`.
*   **[DaemonSet](./daemonset.md)** — организация топологических системных демонов на узлах кластера.
*   **[Garbage Collection и Owner References](../Concepts/garbage_collection.md)** — механизмы каскадного удаления и очистки ресурсов.
*   **[Метаданные, метки и аннотации](../Concepts/metadata_and_labels.md)** — правила проектирования селекторов и меток.
*   **[Horizontal Pod Autoscaler (HPA)](../Autoscaling/HPA/index.md)** — динамическое масштабирование пула реплик по метрикам.
*   **[Архитектура мониторинга и логирования Kubernetes](../MonitoringLogging/kubernetes-monitoring-logging-architecture.md)** — организация сбора метрик `kube-state-metrics` и журналов.
