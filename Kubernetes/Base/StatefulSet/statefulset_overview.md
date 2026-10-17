# StatefulSet: Обзор

**Актуально для:** Kubernetes 1.30–1.37+ (Bare-Metal / On-Premise)

## Определения

*   **StatefulSet** — специализированный контроллер рабочей нагрузки Kubernetes (входящий в группу API `apps/v1`), предназначенный для управления приложениями с отслеживанием состояния (stateful). Гарантирует уникальность, строгую очередность развертывания/масштабирования и сохранение стабильной идентичности (сетевого имени и привязанного хранилища) для каждого экземпляра.
*   **Headless Service** — сервис Kubernetes с явно установленным полем `spec.clusterIP: None`. Не выполняет балансировку нагрузки через виртуальный ClusterIP, а возвращает через CoreDNS прямые `A`/`AAAA`-записи IP-адресов целевых подов, формируя индивидуальные FQDN для каждой реплики.
*   **VolumeClaimTemplates** — декларативный шаблон внутри спецификации StatefulSet, по которому контроллер автоматически генерирует уникальный объект `PersistentVolumeClaim` (PVC) для каждого порядкового индекса пода.
*   **ControllerRevision** — версионированный объект Kubernetes (`apps/v1`), сохраняющий снимок конфигурации шаблона (`spec.template`) StatefulSet для отслеживания истории изменений и детерминированного отката (`rollout undo`).
*   **Sticky Storage (Липкое хранилище)** — архитектурный принцип StatefulSet, согласно которому сгенерированный PVC навсегда связывается с конкретным порядковым индексом пода (например, `data-db-0`). При перезапуске или перепланировании под с индексом 0 повторно монтирует строго свой исходный том.
*   **Ordinal Index (Порядковый индекс)** — целочисленный идентификатор от `0` до `N-1` (или начиная со `spec.ordinals.start`), присваиваемый каждой реплике. Определяет сетевой FQDN, имя привязанного PVC и строгую очередность при создании, обновлении и удалении.
*   **Split-brain (Расщепление мозга)** — критическая аварийная ситуация в кластерных системах с состоянием, при которой потеря сетевой связности приводит к разделению кластера на изолированные сегменты, каждый из которых считает себя лидером и одновременно пишет в общее хранилище, вызывая повреждение данных.
*   **Non-Graceful Node Shutdown** — встроенный механизм Kubernetes (GA с v1.28), позволяющий безопасно сигнализировать о гарантированном выключении физического узла через наложение taint `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute`, что инициирует принудительное отмонтирование томов (VolumeDetach) и безопасный перенос подов StatefulSet.

Сравнение с stateless-подходом см. в разделе **[Stateful vs Stateless](../../../Concepts/stateful_vs_stateless.md)**, а детальное сопоставление контроллеров — в **[StatefulSet vs Deployment](./statefulset_vs_deployment.md)**.

## Архитектура и основные концепции

### Архитектурная триада

Функционирование StatefulSet в инфраструктуре опирается на взаимодействие трех ключевых компонентов:

```
+-----------------------------------------------------------------------------------+
|                         kube-controller-manager                                   |
|                        [StatefulSet Controller]                                   |
+-----------------------------------------------------------------------------------+
             |                                                  |
             | Управляет подами 0..N-1                          | Создает PVC по шаблону
             v                                                  v
+-----------------------------+                    +--------------------------------+
|        Поды (Pods)          |                    | PersistentVolumeClaims (PVC)   |
|  - web-0 (10.244.1.15)      |                    |  - data-web-0  <---> [ PV-0 ]  |
|  - web-1 (10.244.2.22)      |                    |  - data-web-1  <---> [ PV-1 ]  |
|  - web-2 (10.244.3.40)      |                    |  - data-web-2  <---> [ PV-2 ]  |
+-----------------------------+                    +--------------------------------+
             ^                                                  ^
             | Резолвятся через                                 | Монтируются в
+-----------------------------------+                           | соответствующие поды
|      Headless Service             |                           |
|    (spec.clusterIP: None)         |---------------------------+
|                                   |
| web-0.web-svc.default.svc...      |
| web-1.web-svc.default.svc...      |
+-----------------------------------+
```

1.  **StatefulSet Controller:** цикл согласования внутри `kube-controller-manager`. Обеспечивает строгий порядок запуска реплик, отслеживает готовность через Readiness Probe, генерирует PVC и управляет объектами `ControllerRevision`.
2.  **Headless Service:** создает DNS-периметр для прямого сетевого взаимодействия узлов кластера между собой без NAT и проксирования kube-proxy. Подробнее: **[Headless Service](../../Networking/Service/service_type_headless.md)**.
3.  **Хранилище (VolumeClaimTemplates + PV/CSI):** изолирует дисковое пространство для каждой реплики. Подробнее: [PV и PVC](../../Storage/pv_and_pvc.md) и [StorageClass (классы хранения)](../../Storage/storageclass.md).

### Сетевая идентификация и DNS

Каждый под в составе StatefulSet получает предсказуемое имя формата `<имя-StatefulSet>-<индекс>` (например, `db-0`, `db-1`, `db-2`). При наличии связанного Headless Service каждый экземпляр регистрируется в CoreDNS кластера с персональным полным доменным именем (FQDN):

```
$(pod-name).$(service-name).$(namespace).svc.cluster.local
```

**Пример:** для StatefulSet `pg`, использующего Headless Service `pg-nodes` в пространстве имен `databases`, под с индексом 0 получает стабильный адрес:
`pg-0.pg-nodes.databases.svc.cluster.local`.

Системные метки, автоматически добавляемые контроллером к каждому поду:
*   `statefulset.kubernetes.io/pod-name` — стабильное имя пода (`web-0`). Позволяет адресовать трафик стандартного ClusterIP Service или политик NetworkPolicy на конкретный экземпляр (например, направить запись строго на реплику-лидер).
*   `apps.kubernetes.io/pod-index` — числовой индекс пода (`0`, `1`, `2`). Стабильно (GA) с Kubernetes v1.32. Используется для селекторов сервисов, маршрутизации телеметрии и фильтрации в мониторинге.

> [!IMPORTANT]
> **Проблема начального бутстрапа (Bootstrap Quorum):**
> По умолчанию CoreDNS не создает DNS-записи для подов, пока те не пройдут проверку готовности (`Readiness Probe`). В распределенных системах (etcd, Cassandra, ZooKeeper, Patroni) ноды должны обнаружить друг друга по DNS еще до того, как база запустится и станет готовой. Для решения этой проблемы в манифесте Headless Service обязательно указывается:
> ```yaml
> spec:
>   clusterIP: None
>   publishNotReadyAddresses: true
> ```
> Подробнее: [Headless Service — publishNotReadyAddresses](../../Networking/Service/service_type_headless.md).

### Стабильное хранилище через VolumeClaimTemplates

В отличие от Deployment, где все реплики монтируют одни и те же тома, StatefulSet создает **персональный PVC для каждого индекса**:

*   **Шаблон именования:** `<имя-шаблона>-<имя-пода>` (например, `data-web-0`).
*   **Иммутабельность:** секция `volumeClaimTemplates` валидируется API-сервером и запрещена к изменению после создания объекта. Изменение размера тома требует расширения через редактирование самих PVC.
*   **Sticky Binding:** если под `web-0` удален или перенесен на другой рабочий узел из-за сбоя оборудования, вновь созданный под с именем `web-0` смонтирует строго PVC `data-web-0`. Данные не мигрируют между индексами.
*   **Политика удержания (Retention Policy, GA v1.32):** управляется полем `spec.persistentVolumeClaimRetentionPolicy`. Позволяет определить, должны ли удаляться диски при уменьшении числа реплик (`whenScaled`) или при полном удалении StatefulSet (`whenDeleted`). Допустимые значения: `Retain` (по умолчанию) и `Delete`.

### Порядок жизненного цикла (`podManagementPolicy`)

Параметр `spec.podManagementPolicy` определяет правила параллелизма:

1.  **`OrderedReady` (по умолчанию):**
    *   **Запуск:** поды создаются строго по возрастанию: `0` → `1` → `2`. Под `i` не начинает создаваться, пока под `i-1` не перейдет в состояние `Running` и `Ready`.
    *   **Останов и масштабирование вниз:** поды удаляются строго в обратном порядке: `N-1` → `N-2` → `0`. Под `i-1` не завершается, пока под `i` полностью не остановится.
2.  **`Parallel`:**
    *   Контроллер инициирует создание или удаление всех реплик одновременно без ожидания готовности соседей.
    *   Применяется для систем, где реплики полностью автономны или протокол кластеризации сам управляет синхронизацией (например, кэширующие пулы memcached или независимые воркеры с локальными дисками).

### Стратегии обновления

Управляются полем `spec.updateStrategy.type`:

| Стратегия | Доступность | Поведение | Риски и сценарии SRE |
| :--- | :--- | :--- | :--- |
| **`RollingUpdate`** | По умолчанию | Обновляет поды один за другим в обратном порядке от `N-1` к `0`. Контроллер удаляет под, дожидается создания новой ревизии и ее перехода в `Ready`, затем переходит к следующему. | Стандарт для production. При падении обновленного пода обновление блокируется. |
| **`OnDelete`** | Стабильно | Контроллер не трогает работающие поды при изменении `spec.template`. Замена на новую ревизию происходит только в момент ручного удаления пода администратором. | Идеально для тяжелых СУБД (PostgreSQL/MySQL), где обновление версии бинарников требует ручного переключения репликации (failover/switchover). |
| **`Recreate`** | Alpha v1.37 (`StatefulSetRecreateStrategy`) | Полностью останавливает и удаляет **все** поды контроллера, дожидается их полного завершения и только после этого создает все поды на новой версии. | Сопровождается полным даунтаймом. Применяется, когда протокол данных не допускает сосуществования старой и новой версий схемы в кластере. |

**Тонкая настройка RollingUpdate:**
*   `rollingUpdate.partition`: целочисленный барьер. Обновляются только поды с индексом `>= partition`. Поды с индексом `< partition` остаются на старой версии, даже если они были перезапущены. Инструмент для Canary-релизов.
*   `rollingUpdate.maxUnavailable`: число или процент (Beta v1.35, включено по умолчанию в v1.37). Задает максимальное количество подов, которые могут быть недоступны во время обновления. По умолчанию `1`. **Не может быть равен `0`**. Позволяет ускорить обновление крупных инсталляций, но нарушает строгую очередность готовности.

### Ключевые поля спецификации (`.spec`)

| Поле | Тип | Обязательное | Назначение и эксплуатационные нюансы |
| :--- | :--- | :--- | :--- |
| `serviceName` | `string` | Да | Имя Headless Service. Должно быть создано до запуска подов, иначе не сформируются DNS FQDN. |
| `replicas` | `integer` | Нет (default: 1) | Число реплик. Если используется HPA, не должно задаваться жестко в манифесте GitOps. |
| `selector` | `LabelSelector` | Да | Селектор соответствия меток подов. **Иммутабелен** после создания объекта. |
| `template` | `PodTemplateSpec` | Да | Шаблон конфигурации пода (контейнеры, volumes, probes, securityContext). |
| `volumeClaimTemplates` | `[]PVC` | Нет | Шаблон создания хранилища. **Иммутабелен**. Редактирование схемы запрещено API. |
| `podManagementPolicy` | `string` | Нет (default: `OrderedReady`) | Порядок запуска/останова: `OrderedReady` или `Parallel`. |
| `updateStrategy` | `Object` | Нет | Конфигурация обновления: `type: RollingUpdate`, `partition`, `maxUnavailable`. |
| `revisionHistoryLimit` | `integer` | Нет (default: 10) | Количество хранимых объектов `ControllerRevision` для отката. Значение `0` выключает откат. |
| `minReadySeconds` | `integer` | Нет (default: 0) | Задержка в секундах, которую под обязан оставаться `Ready` перед тем, как контроллер продолжит rollout. |
| `persistentVolumeClaimRetentionPolicy` | `Object` | Нет (GA v1.32) | Политики очистки PVC: поля `whenDeleted` и `whenScaled` со значениями `Retain` или `Delete`. |
| `ordinals.start` | `integer` | Нет (GA v1.31) | Начальный номер индекса (по умолчанию `0`). Позволяет сегментировать кластер (например, 3..5). |

Детальный архитектурный анализ каждого механизма приведен в документе **[Ключевые концепции](./statefulset_core_concepts.md)**.

### Производственный манифест для On-Premise кластера

Ниже представлен production-ready манифест для Bare-Metal окружения: Headless Service + StatefulSet на 3 реплики с локальным или блочным хранилищем (StorageClass `local-storage` или Ceph RBD с режимом `WaitForFirstConsumer`), жесткими лимитами ресурсов, проверками готовности/живучести и контекстом безопасности.

```yaml
apiVersion: v1
kind: Service
metadata:
  name: storage-node-headless
  namespace: default
  labels:
    app.kubernetes.io/name: storage-node
spec:
  clusterIP: None
  publishNotReadyAddresses: true # Критично для начального бутстрапа кворума
  selector:
    app.kubernetes.io/name: storage-node
  ports:
  - port: 8080
    name: http-traffic
    targetPort: 8080
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: storage-node
  namespace: default
  labels:
    app.kubernetes.io/name: storage-node
spec:
  serviceName: "storage-node-headless"
  replicas: 3
  podManagementPolicy: OrderedReady
  revisionHistoryLimit: 10
  minReadySeconds: 10
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain
    whenScaled: Retain
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0
      maxUnavailable: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: storage-node
  template:
    metadata:
      labels:
        app.kubernetes.io/name: storage-node
    spec:
      terminationGracePeriodSeconds: 60 # Время на сброс буферов БД на диск перед SIGKILL
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        fsGroupChangePolicy: "OnRootMismatch"
      containers:
      - name: server
        image: nginx:1.27-alpine
        imagePullPolicy: IfNotPresent
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: false
          capabilities:
            drop:
            - ALL
        ports:
        - containerPort: 8080
          name: http-traffic
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "1000m"
            memory: "1Gi"
        startupProbe:
          httpGet:
            path: /healthz
            port: 8080
          failureThreshold: 30
          periodSeconds: 5
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 2
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 15
          periodSeconds: 10
          timeoutSeconds: 2
        volumeMounts:
        - name: data-volume
          mountPath: /var/lib/storage
  volumeClaimTemplates:
  - metadata:
      name: data-volume
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: "local-storage" # On-prem класс с WaitForFirstConsumer
      resources:
        requests:
          storage: 20Gi
```

## Практические сценарии и конфигурация

### Предварительные требования для On-Premise инфраструктуры

Перед развертыванием StatefulSet системный администратор и SRE обязаны обеспечить:

1.  **Рабочий кластер Kubernetes (v1.30–v1.37+)** с функционирующим DNS-плагином (CoreDNS).
2.  **StorageClass с динамическим провижинингом** на базе блочного CSI (Ceph RBD, TopoLVM, Linstor, Longhorn или Local Volume Provisioner). Режим привязки `volumeBindingMode: WaitForFirstConsumer` обязателен, чтобы PV создавался на том узле, куда планировщик поместил под с учетом доступных ресурсов. Подробнее: [StorageClass](../../Storage/storageclass.md).
3.  **RBAC-полномочия:** доступ к API-группам `apps/statefulsets`, `apps/controllerrevisions`, `v1/pods`, `v1/persistentvolumeclaims` и права на просмотр `events`.

### Матрица применимости рабочей нагрузки

| Тип нагрузки | Рекомендуемый контроллер | Причина выбора |
| :--- | :--- | :--- |
| **Stateless API / Web-сервисы** | `Deployment` | Взаимозаменяемые поды, быстрый запуск, автоматический surge при rollout. См. [StatefulSet vs Deployment](./statefulset_vs_deployment.md). |
| **СУБД с кворумом (Patroni, Galera, etcd)** | `StatefulSet` / специализированный `Operator` | Требуются стабильные сетевые имена для рафтинга/кворума и привязка персональных дисков с журналами WAL. |
| **Брокеры очередей (Kafka, RabbitMQ)** | `StatefulSet` / `Operator` (Strimzi) | Идентификаторы брокеров (broker-id) жестко привязаны к порядковым номерам разделов и логов на диске. |
| **Демоны мониторинга на узлах** | `DaemonSet` | Строгая привязка ровно одного экземпляра к каждому физическому серверу. |

### Базовые команды управления

```bash
# Применение манифеста
kubectl apply -f statefulset.yaml
# → service/storage-node-headless created
# → statefulset.apps/storage-node created

# Просмотр статуса контроллера
kubectl get statefulset storage-node -o wide
# → NAME           READY   AGE   CONTAINERS   IMAGES
# → storage-node   3/3     45s   server       nginx:1.27-alpine

# Наблюдение за созданием подов с номерами и привязанных PVC
kubectl get pods -l app.kubernetes.io/name=storage-node -L apps.kubernetes.io/pod-index
# → NAME             READY   STATUS    RESTARTS   AGE   POD-INDEX
# → storage-node-0   1/1     Running   0          50s   0
# → storage-node-1   1/1     Running   0          35s   1
# → storage-node-2   1/1     Running   0          20s   2

kubectl get pvc -l app.kubernetes.io/name=storage-node
# → NAME                        STATUS   VOLUME       CAPACITY   ACCESS MODES   STORAGECLASS    AGE
# → data-volume-storage-node-0  Bound    local-pv-01  20Gi       RWO            local-storage   52s
# → data-volume-storage-node-1  Bound    local-pv-02  20Gi       RWO            local-storage   37s
# → data-volume-storage-node-2  Bound    local-pv-03  20Gi       RWO            local-storage   22s
```

### Канареечный релиз через `partition`

Механизм `spec.updateStrategy.rollingUpdate.partition` позволяет зафиксировать границу обновления по порядковому номеру:

```bash
# Шаг 1: Установка partition на индекс 2 (обновится ТОЛЬКО под storage-node-2)
kubectl patch statefulset storage-node -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":2}}}}'
# → statefulset.apps/storage-node patched

# Шаг 2: Обновление версии образа приложения
kubectl set image statefulset/storage-node server=nginx:1.27.4-alpine
# → statefulset.apps/storage-node image updated

# Шаг 3: Проверка статуса (только storage-node-2 пересоздается на новой версии)
kubectl rollout status statefulset/storage-node
# → Waiting for partitioned rollout to finish: 1 out of 3 new pods have been updated...

# Проверка версий образов по репликам
kubectl get pods -l app.kubernetes.io/name=storage-node -o custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[0].image
# → NAME             IMAGE
# → storage-node-0   nginx:1.27-alpine
# → storage-node-1   nginx:1.27-alpine
# → storage-node-2   nginx:1.27.4-alpine

# Шаг 4: Снятие барьера (раскатка на поды 1 и 0)
kubectl patch statefulset storage-node -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
# → statefulset.apps/storage-node patched

kubectl rollout status statefulset/storage-node
# → statefulset rolling update complete 3 pods at revision storage-node-6f97d5b8c...
```

### Масштабирование и защита от конфликтов с HPA

```bash
# Масштабирование до 5 реплик (создаются по очереди 3, затем 4)
kubectl scale statefulset storage-node --replicas=5
# → statefulset.apps/storage-node scaled

# Проверка соответствия готовых и запрошенных реплик
kubectl get statefulset storage-node -o jsonpath='{.status.readyReplicas}/{"/"}{.spec.replicas}{"\n"}'
# → 5/5
```

> [!WARNING]
> Если в кластере используется `HorizontalPodAutoscaler` (HPA), поле `replicas` в манифесте репозитория GitOps (ArgoCD/Flux) должно быть исключено либо настроено игнорирование различий (`ignoreDifferences` по пути `/spec/replicas`). Иначе каждый GitOps-синк будет сбрасывать количество реплик к статическому числу в git.

### Управление ревизиями и откат (Rollback)

История конфигураций сохраняется в объектах `ControllerRevision`:

```bash
# Просмотр истории релизов
kubectl rollout history statefulset/storage-node
# → statefulset.apps/storage-node
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         kubectl set image statefulset/storage-node server=nginx:1.27.4-alpine

# Просмотр физических объектов ревизий
kubectl get controllerrevisions -l app.kubernetes.io/name=storage-node
# → NAME                      CONTROLLER                     REVISION   AGE
# → storage-node-5847dbbf78   statefulset.apps/storage-node   1          15m
# → storage-node-6f97d5b8c    statefulset.apps/storage-node   2          5m

# Откат на предыдущую стабильную ревизию
kubectl rollout undo statefulset/storage-node --to-revision=1
# → statefulset.apps/storage-node rolled back

kubectl rollout status statefulset/storage-node --timeout=120s
# → statefulset rolling update complete 3 pods at revision storage-node-5847dbbf78...
```

### Плановое обслуживание узла (Drain) на Bare-Metal

При плановом выводе сервера на обслуживание (замена RAM/диска, обновление ядра хоста) системный администратор переводит узел в режим обслуживания:

```bash
# 1. Запрет планирования новых подов и выселение существующих
kubectl drain srv-worker-02 --ignore-daemonsets --delete-emptydir-data --timeout=10m
# → node/srv-worker-02 cordoned
# → evicting pod default/storage-node-1
# → pod/storage-node-1 evicted
# → node/srv-worker-02 drained
```

**Эксплуатационная динамика SRE:**
1.  API Eviction проверяет **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)**. Если для StatefulSet из 3 реплик задан `minAvailable: 2`, а одна нода уже лежит, `drain` будет заблокирован, предотвращая потерю кворума.
2.  Выселенный под `storage-node-1` удаляется на старом узле. CSI-драйвер и операционная система размонтируют том и освобождают блокировку (detach).
3.  Планировщик размещает `storage-node-1` на другом узле `srv-worker-03`.
4.  Том `data-volume-storage-node-1` монтируется на новый узел.
5.  После завершения работ узел возвращается в строй:
    ```bash
    kubectl uncordon srv-worker-02
    # → node/srv-worker-02 uncordoned
    ```

Подробнее: **[Обслуживание узлов (Cordon/Drain)](../../Operations/node_maintenance.md)**.

### Аварийный отказ физического узла (SRE Drill)

В случае внезапного отключения питания или падения ядра физического узла Kubernetes **НЕ переносит поды StatefulSet автоматически** на другие серверы.

**Почему это происходит:** Узел переходит в статус `NotReady`. Kubelet не отвечает мастер-нодам. Control Plane не знает, действительно ли сервер выключен, или произошла сетевая изоляция (network partition). Если бы контроллер запустил копию `storage-node-0` на другом сервере, а изолированный сервер продолжал работать, возникло бы состояние **Split-brain**: два процесса с одинаковой личностью одновременно писали бы в свои тома или в общее SAN-хранилище, безвозвратно разрушая базу данных.

**Стандартный регламент действий инженера SRE:**

```bash
# 1. Диагностика состояния узлов и подов
kubectl get nodes
# → NAME            STATUS     ROLES    AGE   VERSION
# → srv-worker-01   NotReady   worker   45d   v1.32.1

kubectl get pods -l app.kubernetes.io/name=storage-node -o wide
# → NAME             READY   STATUS        NODE
# → storage-node-0   1/1     Terminating   srv-worker-01
# → storage-node-1   1/1     Running       srv-worker-02
# → storage-node-2   1/1     Running       srv-worker-03

# 2. Аппаратное подтверждение (Fencing / IPMI / BMC):
# Убедитесь через iLO / iDRAC / PDU, что сервер srv-worker-01 физически выключен!

# 3. Наложение официального taint Non-Graceful Node Shutdown (GA с K8s v1.28):
kubectl taint nodes srv-worker-01 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
# → node/srv-worker-01 tainted

# Результат: контроллер Kubernetes принудительно удаляет зависший под в статусе Terminating,
# CSI-контроллер принудительно очищает VolumeAttachment, и storage-node-0 поднимается на srv-worker-03.

# 4. После восстановления/замены оборудования и ПЕРЕД включением сервера — обязательно снимите taint:
kubectl taint nodes srv-worker-01 node.kubernetes.io/out-of-service:NoExecute-
# → node/srv-worker-01 untainted
```

> [!CAUTION]
> **Опасность `kubectl delete pod --force --grace-period=0`:**
> Выполнение принудительного удаления пода без предварительного наложения `out-of-service` taint или без аппаратного подтверждения отключения питания (STONITH) категорически запрещено на блочных сетевых хранилищах (iSCSI, FC, Ceph RBD). Это приводит к ошибке `Multi-Attach error for volume` и повреждению файловой системы тома.

### Безопасное удаление и зачистка ресурсов

```bash
# 1. Штатное удаление контроллера (поды удаляются, PVC по умолчанию СОХРАНЯЮТСЯ)
kubectl delete statefulset storage-node
# → statefulset.apps "storage-node" deleted

# 2. Каскадное удаление контроллера с СОХРАНЕНИЕМ работающих подов (Orphan mode):
kubectl delete statefulset storage-node --cascade=orphan
# → statefulset.apps "storage-node" deleted
# Поды storage-node-0, storage-node-1 продолжают работать без контроллера.

# 3. Ручное удаление отдельных PVC после переноса или архивации данных:
kubectl delete pvc data-volume-storage-node-0 data-volume-storage-node-1 data-volume-storage-node-2
# → persistentvolumeclaim "data-volume-storage-node-0" deleted
# → persistentvolumeclaim "data-volume-storage-node-1" deleted
# → persistentvolumeclaim "data-volume-storage-node-2" deleted
```

### Резервное копирование и Disaster Recovery (DR)

Для On-Premise инфраструктуры резервное копирование StatefulSet разделяется на два уровня:

1.  **Уровень метаданных (Декларативное состояние):** Манифесты StatefulSet, Headless Service, ConfigMap и Secret хранятся в репозитории Git (GitOps). Состояние кластера etcd регулярно бэкапится утилитой `etcdctl snapshot save`. Подробнее: **[Резервное копирование и аварийное восстановление в Kubernetes](../../Operations/backup-strategies.md)**.
2.  **Уровень данных (Хранилище PVC):**
    *   **CSI VolumeSnapshots:** создание консистентных снимков дисков через Kubernetes API (`VolumeSnapshot` / `VolumeSnapshotClass`).
    *   **Утилиты резервного копирования:** Velero с плагинами CSI для On-Premise S3/NFS хранилищ. Обязательно использование `pre-backup` и `post-backup` хуков (например, выполнение `fsync` и перевод БД в режим `pg_start_backup`).
    *   **Логические дампы:** выделенные CronJob с выгрузкой дампов (`pg_dump`, `mariadb-dump`) на внешние S3/NFS хранилища.

## Диагностика и устранение неполадок

### Матрица диагностических сценариев SRE

| Симптом | Первопричина | Порядок проверки и решение |
| :--- | :--- | :--- |
| **Под застрял в `Pending`** | 1. PVC не привязался (нет свободных PV, не совпал StorageClass).<br>2. `WaitForFirstConsumer`: том ждет планирования пода, но планировщик не может найти ноду по `podAntiAffinity` или нехватке CPU/RAM. | 1. `kubectl describe pod <имя>` → смотрим секцию Events.<br>2. `kubectl get pvc -l app=...` → если PVC в `Pending`, делаем `kubectl describe pvc <имя>`.<br>3. Проверить доступность дискового пула на хостах и ресурсы нод: [Проблемы с PVC](../../Troubleshooting/Common_Errors/CreateContainerConfigError/pvc_issues.md). |
| **Под в `ContainerCreating` / `FailedAttachVolume`** | Блокировка тома старым узлом (Multi-Attach). Старый под не завершился, а том уже пытается подключиться к новому серверу. | 1. Проверить статус объектов `VolumeAttachment`: `kubectl get volumeattachments`.<br>2. На упавшем узле принудительно применить taint `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute`. |
| **`CrashLoopBackOff` с `Permission Denied`** | Пользователь контейнера (`runAsUser: 10001`) не имеет прав на запись в смонтированный том (владелец тома `root:root`). | Задать в `spec.template.spec.securityContext` параметр `fsGroup: 10001` и `fsGroupChangePolicy: "OnRootMismatch"`. Kubelet автоматически выставит владельца на корень смонтированного диска. |
| **Зависший `RollingUpdate`** | Обновленный под `web-2` падает или не проходит Readiness Probe. Контроллер ждет его готовности и не идет обновлять `web-1` и `web-0`. | 1. Снять логи сбойного пода: `kubectl logs web-2`.<br>2. Откатить манифест: `kubectl rollout undo statefulset/web`.<br>3. **Критический нюанс (баг [#67250](https://github.com/kubernetes/kubernetes/issues/67250)):** если сбойный под находится в CrashLoop, после отката контроллер не всегда перезапускает его автоматически — выполните ручной `kubectl delete pod web-2`. |
| **Под застрял в `Terminating`** | Узел потерял связь с Control Plane; unmount тома заблокирован зависшим вводом-выводом (I/O hang на уровне ядра/NFS/CSI). | Ни в коем случае не удалять force сразу! Выполнить протокол `out-of-service` taint после подтверждения остановки ОС на сервере. |
| **Нет DNS-записи у пода** | 1. Headless Service не создан или его `metadata.name` не совпадает с `spec.serviceName` в StatefulSet.<br>2. Поды не стартовали, а `publishNotReadyAddresses: true` не выставлен. | Проверить соответствие `spec.serviceName` и наличие Headless Service: `kubectl get svc <serviceName>`. Проверить DNS-записи через утилиту `dig` из временного отладочного пода: `kubectl run debug --rm -it --image=alpine -- nslookup <pod>.<svc>`. |
| **Ошибка при `kubectl apply`:** `field is immutable` | Попытка изменить иммутабельные поля: `spec.volumeClaimTemplates` или `spec.selector`. | Kubernetes API запрещает изменение этих полей на лету. Изменение размера диска выполняется через редактирование существующих PVC; изменение селектора требует пересоздания объекта с миграцией данных. |

### Полезные команды глубокой диагностики

```bash
# Просмотр событий жизненного цикла пода и блокировок хранилища
kubectl get events --field-selector involvedObject.name=storage-node-0 --sort-by='.lastTimestamp'

# Проверка существующих связок томов и нод на уровне CSI
kubectl get volumeattachments -o wide

# Проверка внутреннего разрешения DNS из кластера
kubectl run -it --rm debug-dns --image=curlimages/curl --restart=Never -- \
  nslookup storage-node-0.storage-node-headless.default.svc.cluster.local
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      storage-node-0.storage-node-headless.default.svc.cluster.local
# → Address:   10.244.1.15
```

## Рекомендации и Best Practices

### 1. Хранилище на Bare-Metal / On-Premise

*   **Всегда используйте `volumeBindingMode: WaitForFirstConsumer`** в StorageClass. Без этого PVC связывается с PV на произвольной ноде еще до того, как планировщик вычислит свободную память или сработает `podAntiAffinity`, что приведет к вечному статусу `Pending`.
*   **Изоляция дискового ввода-вывода:** Для баз данных с интенсивной записью WAL (PostgreSQL, Kafka, etcd) выделяйте физические NVMe-накопители с прямым пробросом через Local Volume Provisioner или TopoLVM. Избегайте использования сетевых файловых систем (NFS) для транзакционных СУБД из-за рисков рассинхронизации блокировок POSIX и деградации производительности `fsync`. Подробнее: **[Local PV vs CSI](./statefulset_local_pv_vs_csi.md)**.
*   **Контроль размера PVC:** Заранее планируйте расширение дисков (`allowVolumeExpansion: true` в StorageClass).

### 2. Высокая доступность и планирование подов

*   **Распределение по серверам (Anti-Affinity):** Никогда не размещайте реплики одного StatefulSet на одном физическом сервере.
    ```yaml
    affinity:
      podAntiAffinity:
        requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchExpressions:
            - key: app.kubernetes.io/name
              operator: In
              values: ["storage-node"]
          topologyKey: "kubernetes.io/hostname"
    ```
*   **Распределение по стойкам / серверам питания:** Используйте `topologySpreadConstraints` с топологическими ключами физической инфраструктуры (`topology.kubernetes.io/zone` или кастомными метками серверных шкафов `rack: rack-1`).
*   **Защита кворума через PDB:** Создавайте манифест `PodDisruptionBudget` для каждого StatefulSet. Для кластера из 3 реплик задавайте `maxUnavailable: 1` или `minAvailable: 2`. Это защитит кластер от разрушения кворума при одновременном выполнении drain на нескольких узлах. Подробнее: **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)**.

### 3. Пробы и Graceful Shutdown

*   **Startup Probe для тяжелого старта:** Для баз данных, выполняющих проверку целостности или накат журнала WAL при перезапуске, обязательна `startupProbe` с большим порогом ошибок (`failureThreshold: 30`, `periodSeconds: 10`). Без нее стандартная `livenessProbe` начнет убивать под во время восстановления данных, создавая бесконечный цикл перезапусков.
*   **Увеличенный `terminationGracePeriodSeconds`:** Значение по умолчанию (30 секунд) недостаточно для корректной остановки СУБД. Выставляйте от 60 до 300 секунд, чтобы база успела сбросить грязные страницы памяти на диск и корректно закрыть клиентские соединения.
*   **Использование `preStop` хуков:** Для баз данных с репликацией запускайте в `preStop` скрипт понижения статуса мастера (demote/failover), чтобы передать роль лидера до того, как текущий под перестанет отвечать.

### 4. Безопасность и разграничение прав

*   **Не запускайте поды от `root`:** Указывайте `runAsNonRoot: true` и фиксированный `runAsUser`.
*   **Управление правами на смонтированный том:** Всегда декларируйте `fsGroup` в `securityContext` пода. Это гарантирует, что том, смонтированный от блочного CSI, получит нужные права доступа для приложения.
*   **Политика `fsGroupChangePolicy: "OnRootMismatch"`:** Предотвращает медленный рекурсивный `chown` миллионов файлов на диске при каждом перезапуске пода, сокращая время старта контейнера с десятков минут до секунд.

### 5. Эксплуатация в GitOps (ArgoCD / Flux)

*   **Исключение `spec.replicas`:** При динамическом масштабировании настраивайте `ignoreDifferences` в ArgoCD Application, чтобы контроллер непрерывной доставки не откатывал число подов назад.
*   **Управление ревизиями:** Не редактируйте объекты `ControllerRevision` вручную. Все обновления конфигураций шаблона должны проводиться через единый источник правды (git commit).

Подробный разбор практик см. в документе **[Лучшие практики StatefulSet](./statefulset_best_practices.md)**.

## Дополнительная информация

### Возможности и хронология развития механизма в Kubernetes

*   **`minReadySeconds`** (GA v1.25): обязательная пауза между обновлением подов для стабилизации прогрева кэшей и репликации.
*   **Non-Graceful Node Shutdown** (GA v1.28): штатная обработка аварийного падения серверов через taint `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` с автоматической очисткой томов CSI.
*   **Произвольный стартовый индекс (`ordinals.start`)** (GA v1.31): возможность задавать начальный номер подов (например, реплики 3..5), что упрощает миграцию шардов между кластерами.
*   **Политика сохранения PVC (`persistentVolumeClaimRetentionPolicy`)** (GA v1.32): декларативное управление удалением PVC при `whenDeleted` и `whenScaled`.
*   **Метка индекса пода (`apps.kubernetes.io/pod-index`)** (GA v1.32): системная метка для прямой адресации трафика и алертинга.
*   **Параллельное обновление (`maxUnavailable`)** (Beta v1.35, дефолт `1` в v1.37): контролируемое ускорение rollout для больших кластеров.
*   **Стратегия `Recreate`** (Alpha v1.37, gate `StatefulSetRecreateStrategy`): полная остановка всех подов перед созданием новых для несовместимых версий ПО.

### Архитектурные ограничения и подводные камни

1.  **Отсутствие автоматического Failover при падении ноды:** StatefulSet проектировался исходя из приоритета **целостности данных (Consistency)** над доступностью (Availability) согласно CAP-теореме. Автоматический перенос пода без аппаратного подтверждения отключения старого узла запрещен для предотвращения Split-brain.
2.  **Иммутабельность `volumeClaimTemplates`:** Шаблоны PVC нельзя модифицировать после применения. Если требуется сменить StorageClass или базовую конфигурацию дисков, требуется миграция данных или воссоздание объекта с сохранением существующих PV.
3.  **Смерть лидера с индексом `0`:** Во многих самописных скриптах роль мастера жестко завязана на под `*-0`. При обновлении по стратегии `RollingUpdate` под `0` обновляется **последним**, но при начальном запуске создается первым. Архитектура распределенного софта должна опираться на динамические выборы лидера (etcd, Raft, Paxos), а не на хардкод индекса.
4.  **Сложность изменения размера томов:** Увеличение размера PVC поддерживается современными CSI-драйверами онлайн, но сам манифест StatefulSet не принимает новое значение `spec.volumeClaimTemplates.resources.requests.storage`. Процедура выполняется редактированием конкретных объектов PVC и каскадным пересозданием StatefulSet при необходимости.

### Чек-лист проверки готовности StatefulSet к Production

Перед запуском критичных баз данных и брокеров в On-Premise кластере убедитесь, что:

- [ ] Создан Headless Service (`clusterIP: None`) с флагом `publishNotReadyAddresses: true`.
- [ ] В StorageClass используется режим `volumeBindingMode: WaitForFirstConsumer`.
- [ ] Настроены жесткие `resources.requests` и `resources.limits` по CPU и Memory (QoS: Guaranteed).
- [ ] Настроена `startupProbe` для предотвращения рестарта подов во время восстановления данных и WAL replay.
- [ ] Значение `terminationGracePeriodSeconds` увеличено до 60–300 секунд под требования СУБД.
- [ ] В `securityContext` пода заданы `fsGroup` и `fsGroupChangePolicy: "OnRootMismatch"`.
- [ ] Настроен `podAntiAffinity` для запрета запуска двух реплик на одном физическом сервере.
- [ ] Создан `PodDisruptionBudget` с защитой кворума (`maxUnavailable: 1` или `minAvailable: 2`).
- [ ] Протестирован сценарий планового обслуживания (`kubectl drain`) узла.
- [ ] Отработан регламент аварийного восстановления упавшего сервера с использованием `out-of-service` taint.
- [ ] Регламентировано резервное копирование (CSI VolumeSnapshots + логические дампы баз данных).

### См. также

*   **[Ключевые концепции StatefulSet](./statefulset_core_concepts.md)** — архитектурные механизмы идентификации, сетевые FQDN, жизненный цикл и спецификация.
*   **[StatefulSet vs Deployment](./statefulset_vs_deployment.md)** — детальный сравнительный анализ, матрица выбора и сценарий миграции нагрузки.
*   **[Лучшие практики StatefulSet](./statefulset_best_practices.md)** — руководство по обеспечению высокой доступности, безопасности и мониторингу в On-Premise кластерах.
*   **[Практическое руководство](./statefulset_practical_guide.md)** — развертывание кластеров Nginx и MySQL, изменение размера томов и force-delete учения.
*   **[Local PV vs CSI](./statefulset_local_pv_vs_csi.md)** — выбор между локальными дисками и распределенным сетевым хранилищем.
*   **[Sidecar-контейнеры экспортеров](./statefulset_exporter_sidecar.md)** — интеграция Prometheus-экспортеров с подами StatefulSet.
*   **[Headless Service](../../Networking/Service/service_type_headless.md)** — принципы функционирования headless-сервисов и CoreDNS.
*   **[Обслуживание узлов (Cordon/Drain)](../../Operations/node_maintenance.md)** — регламент вывода физических серверов на техническое обслуживание.
*   **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)** — защита кворума и допустимый уровень недоступности подов.
*   **[Резервное копирование и аварийное восстановление](../../Operations/backup-strategies.md)** — стратегии создания бэкапов etcd и дисков PVC.