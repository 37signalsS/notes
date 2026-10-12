# Миграция Kafka с Deployment на StatefulSet без потери данных

**Актуально для:** Apache Kafka 3.8 / 3.9 / 4.0 (KRaft), Kubernetes 1.28–1.32

Данное руководство описывает инженерную процедуру перевода кластера Apache Kafka в Kubernetes из контроллера `Deployment` в нативный для stateful-нагрузок `StatefulSet`. Рассмотрены архитектурные риски старой схемы, детальные сценарии миграции (zero-copy перепривязка существующих томов, rsync-синхронизация и zero-downtime расширение кластера в режиме KRaft), диагностика инцидентов и эксплуатационные best practices системного администрирования и SRE.

---

## Определения

- **Apache Kafka:** Распределенная событийно-ориентированная платформа потоковой обработки данных. Работает с сохранением состояния (stateful), опираясь на неизменяемые журналы сообщений (commit log) на дисках и уникальные числовые идентификаторы брокеров (`node.id` в KRaft / `broker.id` в ZooKeeper).
- **StatefulSet (StS):** Контроллер Kubernetes, предназначенный для управления приложениями с сохранением состояния. Гарантирует уникальные и стабильные сетевые идентификаторы подов (порядковый индекс от 0 до N-1), сохранение соответствия конкретного пода его персистентному тому (PVC) при любых перезапусках, а также упорядоченный запуск и остановку.
- **Headless Service:** Сервис Kubernetes с параметром `spec.clusterIP: None`. В отличие от стандартного ClusterIP, не выполняет балансировку нагрузки между подами, а возвращает в DNS A/AAAA-записи с прямыми IP-адресами всех готовых подов. Необходим для формирования стабильных FQDN брокеров Kafka вида `<pod-name>.<service-name>.<namespace>.svc.cluster.local`.
- **PersistentVolume (PV) и PersistentVolumeClaim (PVC):** Абстракции блочного или сетевого хранилища в Kubernetes. PV представляет собой физический том в инфраструктуре хранения, PVC — декларативный запрос пода на выделение тома с заданным `accessModes` и размером.
- **VolumeClaimTemplates:** Секция спецификации `StatefulSet`, автоматически генерирующая индивидуальный PVC для каждого экземпляра пода по шаблону `<шаблон>-<sts-name>-<индекс>`.
- **VolumeAttachment:** Объект Kubernetes API, связывающий PV с конкретным узлом кластера через CSI-драйвер. Зависший `VolumeAttachment` является главной причиной ошибки `Multi-Attach error` при переносе томов.
- **KRaft (Kafka Raft):** Протокол консенсуса, исключивший зависимость Kafka от ZooKeeper (полностью удален в Kafka 4.0). Кворум контроллеров управляет схемой метаданных кластера напрямую через выделенный топик `@metadata`.
- **meta.properties:** Файл метаданных брокера в корневой директории данных (`log.dirs`), фиксирующий `version`, `cluster.id` и `node.id`. Расхождение значений в файле и в конфигурации брокера блокирует инициализацию процесса Kafka.
- **Advertised Listeners:** Сетевые адреса и порты, которые брокер отправляет клиентам в ответе на запрос метаданных (`MetadataRequest`). Клиент подключается к конкретному лидеру партиции исключительно по адресу из `advertised.listeners`.
- **Ordinal Index (`apps.kubernetes.io/pod-index`):** Порядковый номер реплики в `StatefulSet` (начиная с 0), доступный как суффикс имени пода и как стандартный лейбл пода (GA в Kubernetes 1.32, доступен в 1.28+).

---

## Основные концепции и архитектура

### Почему Deployment для Kafka — критический антипаттерн

Использование `Deployment` для Kafka приводит к фундаментальным проблемам надежности в production:

1. **Нестабильная сетевая идентичность:** При любом рестарте или обновлении под `Deployment` получает случайный хэш в имени (`kafka-7d8b9c6f5-xk2lp`) и новый IP-адрес. Внутренние протоколы репликации Kafka и клиенты теряют адресацию брокера до обновления кэша DNS.
2. **Проблема привязки хранилища:** `Deployment` не имеет механизма автоматического распределения независимых дисков по репликам. Если манифест использует один PVC на несколько реплик с `ReadWriteOnce` (RWO), поды на других узлах падают с ошибкой `CrashLoopBackOff` или `Multi-Attach`. Если использовались отдельные Deployment на каждый брокер — управление конфигурацией, секретами и обновлениями превращается в дублирование манифестов.
3. **Advertised Listeners в динамической среде:** Брокер должен объявлять клиентам свой персональный сетевой адрес. В `Deployment` невозможно из единого шаблона назначить уникальный `KAFKA_CFG_ADVERTISED_LISTENERS` для каждого пода без сложных внешних скриптов.
4. **Неконтролируемый Rolling Update:** Контроллер `Deployment` может остановить одновременно несколько подов или запустить новые реплики до завершения синхронизации реплик (ISR), что приводит к потере кворума партиций (`UnderReplicatedPartitions > 0`) и отказу в обслуживании продюсеров с `acks=all`.

### Архитектурные преимущества StatefulSet

```
                                  ┌────────────────────────┐
                                  │ kafka-headless Service │
                                  │   (clusterIP: None)    │
                                  └───────────┬────────────┘
                                              │
              ┌───────────────────────────────┼───────────────────────────────┐
              │                               │                               │
              ▼                               ▼                               ▼
    ┌───────────────────┐           ┌───────────────────┐           ┌───────────────────┐
    │    Pod: kafka-0   │           │    Pod: kafka-1   │           │    Pod: kafka-2   │
    │  node.id = 0      │           │  node.id = 1      │           │  node.id = 2      │
    │ FQDN: kafka-0...  │           │ FQDN: kafka-1...  │           │ FQDN: kafka-2...  │
    └─────────┬─────────┘           └─────────┬─────────┘           └─────────┬─────────┘
              │                               │                               │
              ▼                               ▼                               ▼
    ┌───────────────────┐           ┌───────────────────┐           ┌───────────────────┐
    │ PVC: data-kafka-0 │           │ PVC: data-kafka-1 │           │ PVC: data-kafka-2 │
    │ (Sticky Storage)  │           │ (Sticky Storage)  │           │ (Sticky Storage)  │
    └───────────────────┘           └───────────────────┘           └───────────────────┘
```

1. **Предсказуемый DNS:** Имена подов строго детерминированы: `kafka-0`, `kafka-1`, `kafka-2`. В сочетании с Headless Service каждый брокер получает неизменный FQDN: `kafka-0.kafka-headless.<namespace>.svc.cluster.local`.
2. **Sticky Storage:** Под с индексом `N` гарантированно монтирует только PVC `data-kafka-N`. При аварии узла и перезапуске пода на другом сервере Kubernetes автоматически переподключает именно его диск.
3. **Упорядоченный жизненный цикл:** По умолчанию `StatefulSet` выполняет операции строго по очереди (0 → 1 → 2 при запуске и 2 → 1 → 0 при остановке), что защищает кворум метаданных KRaft.

### Архитектура метаданных в режиме KRaft

В режиме KRaft метаданные кластера хранятся в специальном журнале на диске. Ключевые параметры согласованности:

- **`cluster.id`:** Уникальный 16-байтный Base64-идентификатор кластера, генерируемый утилитой `kafka-storage.sh random-cluster-id`. Он одинаков для всех узлов кластера.
- **`node.id`:** Уникальный числовой идентификатор узла (0, 1, 2...). Задается в конфигурации брокера и жестко записывается в `/data/meta.properties`.
- **`controller.quorum.voters`:** Статический список участников кворума вида `0@kafka-0.kafka-headless:9093,1@kafka-1.kafka-headless:9093,2@kafka-2.kafka-headless:9093`. Изменение сетевых имен требует пересмотра этого списка.

### Сравнение стратегий миграции

| Параметр | Стратегия 1: In-Place Adoption (Zero-Copy) | Стратегия 2: Data Copy (Rsync Job) | Стратегия 3: Zero-Downtime Cluster Expansion |
| :--- | :--- | :--- | :--- |
| **Downtime кластера** | Минимальный (5–15 минут на рестарт) | Зависит от объема данных (часы на терабайт) | **0 минут** (без остановки продюсеров/консьюмеров) |
| **Копирование данных** | Нет (перепривязка существующих PV) | Полное копирование файлов на новые тома | Сетевая репликация силами самой Kafka |
| **Требования к диску** | Тот же StorageClass, сохранение PV | Двойной объем дискового пространства | Дополнительные диски для новых брокеров |
| **Сложность отката** | Средняя (повторная привязка к Deployment) | Низкая (старые поды и PVC остаются нетронутыми) | Минимальная (удаление новых брокеров) |
| **Рекомендуемый кейс** | Большие кластеры (> 500 ГБ на брокер), допустимо окно ТО | Смена CSI-драйвера, миграция между StorageClass | Высоконагруженный production без окон обслуживания |

---

## Практические сценарии

### Сценарий 1: In-Place перепривязка существующих PV без копирования данных (Zero-Copy)

Сценарий рассчитан на перевод кластера из отдельных подов `Deployment` (или единичных Deployment на каждый брокер) в единый `StatefulSet` с сохранением существующих томов.

#### Шаг 1: Фиксация соответствия PV и брокеров

Определите, какой PV содержит данные какого брокера:

```bash
kubectl get pvc -n kafka -o custom-columns=NAME:.metadata.name,VOLUME:.spec.volumeName,STATUS:.status.phase
# → NAME                 VOLUME                                     STATUS
# → data-old-broker-0    pvc-11111111-2222-3333-4444-555555555555   Bound
# → data-old-broker-1    pvc-66666666-7777-8888-9999-aaaaaaaaaaaa   Bound
# → data-old-broker-2    pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff   Bound
```

Зафиксируйте соответствие:
- `pvc-11111111-2222-3333-4444-555555555555` → `node.id=0` (будущий `data-kafka-0`)
- `pvc-66666666-7777-8888-9999-aaaaaaaaaaaa` → `node.id=1` (будущий `data-kafka-1`)
- `pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff` → `node.id=2` (будущий `data-kafka-2`)

#### Шаг 2: Перевод политики удержания PV в Retain

Измените `persistentVolumeReclaimPolicy` на `Retain`, чтобы Kubernetes не удалил физические тома при удалении старых PVC:

```bash
for pv in pvc-11111111-2222-3333-4444-555555555555 pvc-66666666-7777-8888-9999-aaaaaaaaaaaa pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff; do
  kubectl patch pv $pv -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
done
# → persistentvolume/pvc-11111111-2222-3333-4444-555555555555 patched
# → persistentvolume/pvc-66666666-7777-8888-9999-aaaaaaaaaaaa patched
# → persistentvolume/pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff patched
```

Убедитесь, что политика изменена:

```bash
kubectl get pv | grep -E 'pvc-11111111|pvc-66666666|pvc-bbbbbbbb'
# → pvc-11111111-2222-3333-4444-555555555555   100Gi   RWO   Retain   Bound   kafka/data-old-broker-0
# → pvc-66666666-7777-8888-9999-aaaaaaaaaaaa   100Gi   RWO   Retain   Bound   kafka/data-old-broker-1
# → pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff   100Gi   RWO   Retain   Bound   kafka/data-old-broker-2
```

#### Шаг 3: Остановка старых подов и удаление старых PVC

1. Остановите продюсеры или переведите их в паузу.
2. Масштабируйте старый `Deployment` в 0:

```bash
kubectl scale deployment kafka-old --replicas=0 -n kafka
# → deployment.apps/kafka-old scaled

kubectl wait --for=delete pod -l app=kafka-old -n kafka --timeout=120s
# → condition met
```

3. Удалите старые PVC:

```bash
kubectl delete pvc data-old-broker-0 data-old-broker-1 data-old-broker-2 -n kafka
# → persistentvolumeclaim "data-old-broker-0" deleted
# → persistentvolumeclaim "data-old-broker-1" deleted
# → persistentvolumeclaim "data-old-broker-2" deleted
```

4. После удаления PVC статус PV перейдет в `Released`. Чтобы новый PVC мог подключиться к этому PV, очистите ссылку `spec.claimRef`:

```bash
for pv in pvc-11111111-2222-3333-4444-555555555555 pvc-66666666-7777-8888-9999-aaaaaaaaaaaa pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff; do
  kubectl patch pv $pv -p '{"spec":{"claimRef": null}}'
done
# → persistentvolume/pvc-11111111-2222-3333-4444-555555555555 patched
# → persistentvolume/pvc-66666666-7777-8888-9999-aaaaaaaaaaaa patched
# → persistentvolume/pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff patched
```

Статус PV должен стать `Available`:

```bash
kubectl get pv | grep -E 'pvc-11111111|pvc-66666666|pvc-bbbbbbbb'
# → pvc-11111111-2222-3333-4444-555555555555   100Gi   RWO   Retain   Available
# → pvc-66666666-7777-8888-9999-aaaaaaaaaaaa   100Gi   RWO   Retain   Available
# → pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff   100Gi   RWO   Retain   Available
```

#### Шаг 4: Создание Headless Service

Создайте манифест `kafka-headless-service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: kafka-headless
  namespace: kafka
  labels:
    app.kubernetes.io/name: kafka
spec:
  clusterIP: None
  publishNotReadyAddresses: true # Критично для KRaft во время bootstrap кворума
  ports:
  - name: client
    port: 9092
    targetPort: 9092
  - name: controller
    port: 9093
    targetPort: 9093
  selector:
    app.kubernetes.io/name: kafka
```

Примените манифест:

```bash
kubectl apply -f kafka-headless-service.yaml
# → service/kafka-headless created
```

#### Шаг 5: Предсоздание PVC по соглашению StatefulSet

`StatefulSet` с именем `kafka` и `volumeClaimTemplates.metadata.name: data` ожидает PVC с именами `data-kafka-0`, `data-kafka-1`, `data-kafka-2`. Предсоздайте эти PVC с явной привязкой к освобожденным PV (`volumeName`):

```yaml
# precreated-pvcs.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-kafka-0
  namespace: kafka
spec:
  accessModes: [ "ReadWriteOnce" ]
  storageClassName: "standard" # Укажите используемый StorageClass
  volumeName: "pvc-11111111-2222-3333-4444-555555555555"
  resources:
    requests:
      storage: 100Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-kafka-1
  namespace: kafka
spec:
  accessModes: [ "ReadWriteOnce" ]
  storageClassName: "standard"
  volumeName: "pvc-66666666-7777-8888-9999-aaaaaaaaaaaa"
  resources:
    requests:
      storage: 100Gi
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-kafka-2
  namespace: kafka
spec:
  accessModes: [ "ReadWriteOnce" ]
  storageClassName: "standard"
  volumeName: "pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
  resources:
    requests:
      storage: 100Gi
```

Примените манифест:

```bash
kubectl apply -f precreated-pvcs.yaml
# → persistentvolumeclaim/data-kafka-0 created
# → persistentvolumeclaim/data-kafka-1 created
# → persistentvolumeclaim/data-kafka-2 created
```

Проверьте, что статус всех PVC перешел в `Bound`:

```bash
kubectl get pvc -n kafka -l app.kubernetes.io/name!=old
# → NAME           STATUS   VOLUME                                     CAPACITY   ACCESS MODES
# → data-kafka-0   Bound    pvc-11111111-2222-3333-4444-555555555555   100Gi      RWO
# → data-kafka-1   Bound    pvc-66666666-7777-8888-9999-aaaaaaaaaaaa   100Gi      RWO
# → data-kafka-2   Bound    pvc-bbbbbbbb-cccc-dddd-eeee-ffffffffffff   100Gi      RWO
```

#### Шаг 6: Проверка и адаптация meta.properties

Перед запуском брокеров убедитесь, что в файле `meta.properties` на каждом диске записан тот же `node.id`, который получит под:
- `data-kafka-0` → `node.id=0`
- `data-kafka-1` → `node.id=1`
- `data-kafka-2` → `node.id=2`

Для проверки и редактирования используйте временный отладочный под:

```bash
kubectl run kafka-meta-check --rm -it --restart=Never -n kafka \
  --image=busybox:1.36 \
  --overrides='{
    "spec": {
      "volumes": [{"name": "vol", "persistentVolumeClaim": {"claimName": "data-kafka-0"}}],
      "containers": [{"name": "c", "image": "busybox:1.36", "command": ["sh"], "stdin": true, "tty": true, "volumeMounts": [{"name": "vol", "mountPath": "/mnt"}]}]
    }
  }'
```

Внутри пода:

```sh
# Проверка текущего meta.properties
cat /mnt/meta.properties
# → version=1
# → cluster.id=4L622nShT-eMCtK--X86sw
# → node.id=0

# Если node.id отличается от индекса пода, отредактируйте файл:
# sed -i 's/^node.id=.*/node.id=0/' /mnt/meta.properties
exit
```

Повторите проверку для `data-kafka-1` и `data-kafka-2`.

#### Шаг 7: Развертывание production-манифеста StatefulSet

Создайте манифест `kafka-statefulset.yaml`. Обратите внимание на корректное извлечение `MY_POD_NAME` и вычисление числового `node.id` через `HOSTNAME`:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: kafka
  namespace: kafka
  labels:
    app.kubernetes.io/name: kafka
spec:
  serviceName: "kafka-headless"
  replicas: 3
  podManagementPolicy: OrderedReady
  updateStrategy:
    type: RollingUpdate
  selector:
    matchLabels:
      app.kubernetes.io/name: kafka
  template:
    metadata:
      labels:
        app.kubernetes.io/name: kafka
    spec:
      terminationGracePeriodSeconds: 120
      securityContext:
        fsGroup: 1001
        runAsUser: 1001
        runAsNonRoot: true
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
          - weight: 100
            podAffinityTerm:
              labelSelector:
                matchExpressions:
                - key: app.kubernetes.io/name
                  operator: In
                  values: ["kafka"]
              topologyKey: "kubernetes.io/hostname"
      containers:
      - name: kafka
        image: bitnami/kafka:3.9.0
        imagePullPolicy: IfNotPresent
        command:
        - /bin/bash
        - -ec
        - |
          # Извлекаем порядковый индекс пода (kafka-0 -> 0)
          export KAFKA_CFG_NODE_ID=${HOSTNAME##*-}
          # Формируем advertised listener с полным FQDN
          export KAFKA_CFG_ADVERTISED_LISTENERS="PLAINTEXT://${MY_POD_NAME}.kafka-headless.kafka.svc.cluster.local:9092"
          # Запуск стандартного entrypoint Bitnami
          exec /entrypoint.sh /run.sh
        env:
        - name: MY_POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: KAFKA_KRAFT_CLUSTER_ID
          value: "4L622nShT-eMCtK--X86sw"
        - name: KAFKA_CFG_PROCESS_ROLES
          value: "broker,controller"
        - name: KAFKA_CFG_CONTROLLER_QUORUM_VOTERS
          value: "0@kafka-0.kafka-headless.kafka.svc.cluster.local:9093,1@kafka-1.kafka-headless.kafka.svc.cluster.local:9093,2@kafka-2.kafka-headless.kafka.svc.cluster.local:9093"
        - name: KAFKA_CFG_LISTENERS
          value: "PLAINTEXT://:9092,CONTROLLER://:9093"
        - name: KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP
          value: "CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT"
        - name: KAFKA_CFG_CONTROLLER_LISTENER_NAMES
          value: "CONTROLLER"
        - name: KAFKA_CFG_INTER_BROKER_LISTENER_NAME
          value: "PLAINTEXT"
        - name: KAFKA_CFG_DEFAULT_REPLICATION_FACTOR
          value: "3"
        - name: KAFKA_CFG_MIN_INSYNC_REPLICAS
          value: "2"
        - name: KAFKA_CFG_OFFSETS_TOPIC_REPLICATION_FACTOR
          value: "3"
        - name: KAFKA_CFG_TRANSACTION_STATE_LOG_REPLICATION_FACTOR
          value: "3"
        - name: KAFKA_CFG_TRANSACTION_STATE_LOG_MIN_ISR
          value: "2"
        - name: KAFKA_CFG_LOG_DIRS
          value: "/bitnami/kafka/data"
        ports:
        - name: client
          containerPort: 9092
        - name: controller
          containerPort: 9093
        resources:
          requests:
            cpu: 1000m
            memory: 2Gi
          limits:
            cpu: 2000m
            memory: 4Gi
        readinessProbe:
          tcpSocket:
            port: 9092
          initialDelaySeconds: 15
          periodSeconds: 10
          timeoutSeconds: 5
        livenessProbe:
          tcpSocket:
            port: 9092
          initialDelaySeconds: 30
          periodSeconds: 15
          timeoutSeconds: 5
        volumeMounts:
        - name: data
          mountPath: /bitnami/kafka/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: "standard"
      resources:
        requests:
          storage: 100Gi
```

Запустите StatefulSet:

```bash
kubectl apply -f kafka-statefulset.yaml
# → statefulset.apps/kafka created

kubectl rollout status statefulset/kafka -n kafka --timeout=300s
# → Waiting for 3 pods to be ready...
# → partition 0: statefulset rolling update complete 3 pods at revision kafka-69d84bf4b...
```

---

### Сценарий 2: Миграция с физическим переносом данных (Rsync Migration Job)

Используется, когда тома привязаны к старому StorageClass, требуют изменения файловой системы или когда организация требует оставить исходные тома нетронутыми в качестве моментального снапшота.

```
┌────────────────────────┐                   ┌────────────────────────┐
│ Старый PVC (Deployment)│ ──[ rsync -aHAX ]─▶ │  Новый PVC (StS)       │
│  data-old-broker-0     │   в Migration Job  │  data-kafka-0          │
└────────────────────────┘                   └────────────────────────┘
```

#### Шаг 1: Создание пустых томов нового StatefulSet

1. Примените `kafka-headless-service.yaml`.
2. Создайте `StatefulSet`, но с `replicas: 0`:

```bash
kubectl scale statefulset kafka --replicas=0 -n kafka
# → statefulset.apps/kafka scaled
```

3. Вручную создайте пустые целевые PVC: `data-kafka-0`, `data-kafka-1`, `data-kafka-2`.

#### Шаг 2: Запуск Kubernetes Job для копирования

Создайте манифест `migration-rsync-job.yaml` для брокера 0:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: kafka-data-sync-0
  namespace: kafka
spec:
  backoffLimit: 2
  template:
    metadata:
      labels:
        job: kafka-data-sync-0
    spec:
      restartPolicy: OnFailure
      securityContext:
        runAsUser: 0 # Root нужен для сохранения исходных UID/GID
      containers:
      - name: rsync
        image: alpine:3.20
        command:
        - /bin/sh
        - -ec
        - |
          apk add --no-cache rsync coreutils
          echo "=== Начинаем синхронизацию данных брокера 0 ==="
          rsync -aHAX --delete --info=progress2 /src-data/ /dst-data/
          echo "=== Проверяем права доступа (UID 1001 для Kafka) ==="
          chown -R 1001:1001 /dst-data/
          ls -la /dst-data/
          echo "=== Синхронизация успешно завершена ==="
        volumeMounts:
        - name: source-volume
          mountPath: /src-data
          readOnly: true
        - name: dest-volume
          mountPath: /dst-data
      volumes:
      - name: source-volume
        persistentVolumeClaim:
          claimName: data-old-broker-0
      - name: dest-volume
        persistentVolumeClaim:
          claimName: data-kafka-0
```

Запустите Job и дождитесь завершения:

```bash
kubectl apply -f migration-rsync-job.yaml
# → job.batch/kafka-data-sync-0 created

kubectl wait --for=condition=complete job/kafka-data-sync-0 -n kafka --timeout=1800s
# → job.batch/kafka-data-sync-0 condition met
```

Повторите процедуру для узлов 1 и 2, затем масштабируйте `StatefulSet` до 3 реплик:

```bash
kubectl scale statefulset kafka --replicas=3 -n kafka
# → statefulset.apps/kafka scaled
```

---

### Сценарий 3: Zero-Downtime миграция через расширение кластера (Side-by-Side Replication)

Если остановка записи в кластер недопустима, применяется стратегия параллельного запуска:

1. **Развертывание StatefulSet рядом:** Запустите `StatefulSet` с `node.id=3,4,5` в том же namespace. Новые брокеры подключаются к существующему кворуму KRaft (`controller.quorum.voters`).
2. **Перераспределение партиций:** Сгенерируйте и примените JSON-план перемещения реплик со старых брокеров (0, 1, 2) на новые брокеры (3, 4, 5).
3. **Ожидание синхронизации:** Дождитесь, пока `UnderReplicatedPartitions` станет равным 0.
4. **Вывод старых подов:** Отключите старые поды `Deployment`. При необходимости выполните миграцию ролей контроллеров кворума через `kafka-metadata-shell.sh` или динамическое изменение кворума.

---

## Операции и команды

### 1. Верификация кворума метаданных KRaft

```bash
kubectl exec -it kafka-0 -n kafka -- /opt/bitnami/kafka/bin/kafka-metadata-quorum.sh \
  --bootstrap-server localhost:9092 describe --status
# → ClusterId:              4L622nShT-eMCtK--X86sw
# → LeaderId:               0
# → LeaderEpoch:            12
# → HighWatermark:          48102
# → MaxFollowerLag:         0
# → MaxFollowerLagTimeMs:   14
# → CurrentVoters:          [{"id": 0, "directoryId": "...", "endpoints": ["CONTROLLER://kafka-0.kafka-headless.kafka.svc.cluster.local:9093"]}, {"id": 1, "directoryId": "...", "endpoints": ["CONTROLLER://kafka-1.kafka-headless.kafka.svc.cluster.local:9093"]}, {"id": 2, "directoryId": "...", "endpoints": ["CONTROLLER://kafka-2.kafka-headless.kafka.svc.cluster.local:9093"]}]
```

### 2. Проверка задержки репликации контроллеров

```bash
kubectl exec -it kafka-0 -n kafka -- /opt/bitnami/kafka/bin/kafka-metadata-quorum.sh \
  --bootstrap-server localhost:9092 describe --replication
# → NodeId  LogEndOffset  Lag  LastFetchTimestamp  LastCaughtUpTimestamp  Status
# → 0       48105         0    1710000000000       1710000000000          Leader
# → 1       48105         0    1710000000000       1710000000000          Follower
# → 2       48105         0    1710000000000       1710000000000          Follower
```

### 3. Проверка недореплицированных партиций данных

Перед возобновлением трафика клиентов убедитесь в отсутствии отставших реплик:

```bash
kubectl exec -it kafka-0 -n kafka -- /opt/bitnami/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 --describe --under-replicated-partitions
# → (пустой вывод означает, что все партиции полностью синхронизированы в ISR)
```

### 4. Проверка доступности брокеров через Headless DNS

Выполните трассировку разрешения сетевых имен брокеров внутри пода:

```bash
kubectl exec -it kafka-0 -n kafka -- nslookup kafka-1.kafka-headless.kafka.svc.cluster.local
# → Server:         10.96.0.10
# → Address:        10.96.0.10#53
# → Name:   kafka-1.kafka-headless.kafka.svc.cluster.local
# → Address: 10.244.2.45
```

### 5. Проверка состояния подключений томов (CSI VolumeAttachment)

```bash
kubectl get volumeattachment
# → NAME                                                                   ATTACHER             NODE         ATTACHED   AGE
# → csi-1111111111111111111111111111111111111111111111111111111111111111   csi.local.driver     k8s-node-1   true       15m
# → csi-2222222222222222222222222222222222222222222222222222222222222222   csi.local.driver     k8s-node-2   true       14m
# → csi-3333333333333333333333333333333333333333333333333333333333333333   csi.local.driver     k8s-node-3   true       14m
```

---

## Диагностика и устранение неисправностей (Troubleshooting)

### Типовые сбои при миграции

| Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `InconsistentNodeIdException` | Значение `node.id` в `meta.properties` не совпадает с `KAFKA_CFG_NODE_ID` брокера. | `kubectl logs kafka-0 -n kafka \| grep -i InconsistentNodeId` | Привести переменную окружения пода или `meta.properties` на диске к единому значению. |
| `InconsistentClusterIdException` | Кластер форматировался с другим `cluster.id`, чем сохранен в `meta.properties`. | `kubectl logs kafka-0 -n kafka \| grep -i InconsistentClusterId` | Использовать оригинальный `KAFKA_KRAFT_CLUSTER_ID`, извлеченный из существующего `meta.properties`. |
| `Multi-Attach error for volume` | Предыдущий под `Deployment` завершился некорректно, узел удерживает диск через CSI. | `kubectl describe pod kafka-0 -n kafka \| grep -A 5 FailedAttachVolume` | Найти зависший объект: `kubectl get volumeattachment`, принудительно удалить старый под или очистить `VolumeAttachment`. |
| `CrashLoopBackOff: NumberFormatException` | Попытка передать имя пода (`kafka-0`) вместо целого числа в `node.id`. | `kubectl logs kafka-0 -n kafka \| grep NumberFormatException` | Использовать скрипт отсечения префикса: `export KAFKA_CFG_NODE_ID=${HOSTNAME##*-}` в entrypoint. |
| `ConnectionRefused` / `UnknownHostException` у клиентов | Клиенты не могут разрешить DNS-имя из `advertised.listeners`. | `kubectl exec -it client-pod -- nc -zv kafka-0.kafka-headless 9092` | Убедиться, что Headless Service существует, селекторы совпадают, а `advertised.listeners` содержит верный domain. |
| `UnderReplicatedPartitions > 0` | Брокер запущен с пустым диском или отстает репликация после простоя. | `kafka-topics.sh --describe --under-replicated-partitions` | Дождаться вычитки логов репликами; проверить дисковую утилизацию `iostat` и сеть между узлами. |

### Детальные сценарии решения проблем

#### 1. Устранение зависшей блокировки VolumeAttachment

Если pod `kafka-0` находится в статусе `ContainerCreating` с ошибкой:
```
Multi-Attach error for volume "pvc-11111111" Volume is already exclusively attached to one node and can't be attached to another
```

1. Определите имя зависшего объекта:
```bash
kubectl get volumeattachment | grep pvc-11111111
# → csi-1111111111111111111111111111111111111111111111111111111111111111
```
2. Проверьте, завершился ли старый pod на указанном узле. Если старый pod уже удален, удалите зависший attachment:
```bash
kubectl delete volumeattachment csi-1111111111111111111111111111111111111111111111111111111111111111
# → volumeattachment.storage.k8s.io "csi-1111111111111111111111111111111111111111111111111111111111111111" deleted
```
3. Kubernetes автоматически пересоздаст attachment на новом узле для пода `kafka-0`.

#### 2. Исправление ошибки несовпадения прав доступа на диске (Permission Denied)

Если контейнер падает с ошибкой:
```
java.io.FileNotFoundException: /bitnami/kafka/data/meta.properties (Permission denied)
```

Причина: старый `Deployment` работал под другим UID (например, root или 1000), а StatefulSet запущен с `runAsUser: 1001`.
Решение: добавьте `initContainer` в манифест `StatefulSet`:

```yaml
initContainers:
- name: fix-permissions
  image: busybox:1.36
  securityContext:
    runAsUser: 0
  command: ['sh', '-c', 'chown -R 1001:1001 /bitnami/kafka/data']
  volumeMounts:
  - name: data
    mountPath: /bitnami/kafka/data
```

---

## Рекомендации и лучшие практики (Best Practices)

### 1. Отказоустойчивость и топология планирования

- **PodAntiAffinity:** Обязательно настраивайте анти-аффинити по физическим серверам (`kubernetes.io/hostname`), чтобы брокеры одного кластера не оказались на одном узле Kubernetes:
  ```yaml
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchExpressions:
          - key: app.kubernetes.io/name
            operator: In
            values: ["kafka"]
        topologyKey: "kubernetes.io/hostname"
  ```
- **PodDisruptionBudget (PDB):** Установите PDB с `maxUnavailable: 1`, чтобы предотвратить одновременный дрейнаж нескольких узлов с брокерами во время регламентных работ на кластере (`kubectl drain`):
  ```yaml
  apiVersion: policy/v1
  kind: PodDisruptionBudget
  metadata:
    name: kafka-pdb
    namespace: kafka
  spec:
    maxUnavailable: 1
    selector:
      matchLabels:
        app.kubernetes.io/name: kafka
  ```

### 2. Настройки хранилища и CSI

- **WaitForFirstConsumer:** Всегда настраивайте `StorageClass` с `volumeBindingMode: WaitForFirstConsumer`. Это гарантирует, что том выделится в той же зоне доступности и на том узле, где Kubernetes запланировал запуск пода.
- **PersistentVolume Retention:** В production-среде храните физические тома с `persistentVolumeReclaimPolicy: Retain`. Это защищает от безвозвратного удаления данных при случайном удалении `StatefulSet` или PVC.
- **Каскадное изменение размера томов:** Поле `volumeClaimTemplates` иммутабельно. Если в будущем потребуется увеличить размер диска, нельзя просто изменить манифест `StatefulSet`. Процедура:
  1. Изменить `spec.resources.requests.storage` непосредственно в каждом PVC (`kubectl edit pvc data-kafka-0`).
  2. Дождаться, пока CSI-драйвер расширит файловую систему тома.
  3. Удалить объект `StatefulSet` с ключом `--cascade=orphan` (`kubectl delete sts kafka --cascade=orphan`).
  4. Применить обновленный манифест `StatefulSet` с новым размером тома в шаблоне.

### 3. Graceful Shutdown и целостность журнала

- **TerminationGracePeriodSeconds:** Установите `terminationGracePeriodSeconds: 120` (или до 300 при больших объемах памяти). Kafka требуется время для корректного сброса страниц операционной системы на диск (`fsync`), передачи лидерства партиций другим брокерам (`controlled.shutdown`) и сохранения файла `clean-shutdown-marker`.
- **PreStop Hook:** Для форсированного сброса журналов при остановке можно использовать хук:
  ```yaml
  lifecycle:
    preStop:
      exec:
        command: ["/bin/sh", "-c", "sync"]
  ```

### 4. Чек-лист системного администратора перед миграцией

- [ ] Созданы моментальные снимки (снапшоты) всех существующих PV.
- [ ] Зафиксированы значения `cluster.id` и `node.id` для каждого диска.
- [ ] Проверен и настроен `Headless Service` с флагом `publishNotReadyAddresses: true`.
- [ ] Политика `persistentVolumeReclaimPolicy` переведена в `Retain`.
- [ ] Остановлены или переведены в режим ожидания продюсеры сообщений.
- [ ] Проверено отсутствие недореплицированных партиций (`UnderReplicatedPartitions == 0`).
- [ ] Подготовлены манифесты отката (rollback plan) на случай непредвиденных сбоев.

---

## Дополнительная информация

### Нюансы эксплуатации

- **Операторы Kubernetes:** Для крупных промышленных инсталляций управление манифестами вручную заменяется на **[Strimzi Kafka Operator](./strimzi_kafka_operator.md)**. Strimzi использует кастомный ресурс `StrimziPodSet`, обеспечивая еще более гибкое управление per-broker дисками и автоматические rolling updates.
- **Очистка старых ресурсов:** Удаляйте резервные тома и старый `Deployment` только после подтверждения стабильной работы кластера в течение полного бизнес-цикла (не менее 24–48 часов) и валидации метрик лага консьюмеров.
- **Сетевая изоляция:** Убедитесь, что `NetworkPolicy` разрешает входящий трафик на порт `9093` между подами самого `StatefulSet` для межброкерского взаимодействия и кворума контроллеров KRaft.

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — основы архитектуры, формат топиков и принципы работы KRaft.
- **[Strimzi Kafka Operator](./strimzi_kafka_operator.md)** — промышленный стандарт управления Kafka в Kubernetes.
- **[CLI-утилиты Kafka](./kafka_cli_tools.md)** — полное руководство по консольным утилитам администрирования.
- **[Troubleshooting Playbook для Kafka](./kafka_troubleshooting_playbook.md)** — алгоритмы локализации аварий и метрики здоровья брокеров.
- **[Гарантии доставки](./delivery_guarantees.md)** — семантика at-least-once, acks=all и идемпотентность.
- **[StatefulSet: ключевые концепции](../Kubernetes/Base/StatefulSet/statefulset_core_concepts.md)** — архитектура контроллера, headless-сервисы и volumeClaimTemplates.
- **[StatefulSet vs Deployment](../Kubernetes/Base/StatefulSet/statefulset_vs_deployment.md)** — сравнение контроллеров и общие паттерны миграции.
- **[StatefulSet: практическое руководство](../Kubernetes/Base/StatefulSet/statefulset_practical_guide.md)** — каскадное расширение томов и управление ординалами.
