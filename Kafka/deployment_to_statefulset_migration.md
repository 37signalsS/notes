# Миграция Kafka с Deployment на StatefulSet без потери данных

Данное руководство описывает процесс перевода кластера Apache Kafka в Kubernetes из объекта `Deployment` в `StatefulSet`. Такая миграция критически важна для обеспечения стабильной сетевой идентичности брокеров и надежной привязки персистентных дисков.

---

## Определения

- **Apache Kafka:** Распределенная потоковая платформа с сохранением состояния (Stateful). Для корректной работы кластера брокерам требуются уникальные неизменяемые идентификаторы и постоянные хранилища данных.
- **StatefulSet (StS):** Контроллер Kubernetes, предназначенный для управления приложениями с состоянием. Обеспечивает строгий порядок запуска/остановки подов, стабильные DNS-имена (например, `kafka-0.kafka-headless`) и гарантированную связь конкретного пода с конкретным PVC (PersistentVolumeClaim).
- **Deployment:** Контроллер для приложений без состояния (Stateless). В отличие от StS, поды в Deployment взаимозаменяемы, имеют случайные имена (хеш-суффиксы) и не гарантируют сохранение связи с конкретным диском при перезапуске на другом узле.
- **Headless Service:** Сервис Kubernetes с `clusterIP: None`. Позволяет обращаться напрямую к IP-адресам подов через DNS-записи вида `<pod-name>.<service-name>.<namespace>.svc.cluster.local`. Это критически важно для механизма обнаружения (discovery) брокеров Kafka.
- **PVC (PersistentVolumeClaim):** Абстракция Kubernetes для запроса дискового пространства. В StatefulSet PVC создаются автоматически для каждого пода через `volumeClaimTemplates`.
- **Advertised Listeners:** Конфигурационный параметр Kafka, определяющий адрес, который брокер передает клиентам (продюсерам и консьюмерам) для подключения.
- **KRaft (Kafka Raft):** Современный протокол консенсуса (начиная с Kafka 3.3), заменяющий ZooKeeper и позволяющий управлять метаданными внутри самого кластера Kafka.

---

## Основные концепции

### Проблемы использования Deployment для Kafka

Использование `Deployment` для управления Kafka является антипаттерном в Kubernetes по следующим причинам:
1. **Нестабильные идентификаторы:** При перезапуске под получает новое имя и IP. Это ломает внутренние протоколы Kafka, которые полагаются на стабильный список брокеров.
2. **Сложность с PVC:** В `Deployment` крайне сложно сопоставить конкретный под с конкретным томом данных. Если в кластере 3 брокера, Deployment может запустить два пода на одном узле, пытаясь подключить один и тот же диск, что приведет к ошибкам `Multi-Attach`.
3. **Advertised Listeners:** В `Deployment` невозможно настроить уникальный внешний адрес для каждого брокера без использования сложных Sidecar-контейнеров или внешних скриптов.

### Преимущества StatefulSet

1. **Предсказуемый DNS:** Каждый под имеет индекс (0, 1, 2). Это позволяет настроить `ADVERTISED_LISTENERS` вида `kafka-0.kafka-headless.svc.cluster.local:9092`.
2. **Липкие диски (Sticky Storage):** Под `kafka-0` всегда будет подключать PVC `data-kafka-0`, даже если он переедет на другую физическую ноду.
3. **Упорядоченность:** StatefulSet обновляет поды по одному, дожидаясь их готовности (`Readiness`), что минимизирует риск падения всего кластера Kafka.

---

## Практические сценарии

### План миграции (In-place Migration)

**ВНИМАНИЕ:** Данный процесс сопряжен с риском. Перед началом **обязательно сделайте бэкап** данных (например, через снапшоты облачного провайдера или **[Velero](../Kubernetes/ToolsUtilities/velero-overview.md)**). Процедура требует остановки записи в Kafka.

#### Шаг 1: Подготовка инфраструктуры

1. **Остановка продюсеров:** Прекратите любую запись в топики Kafka.
2. **Анализ текущих PVC:** Получите список дисков, которые сейчас использует ваш `Deployment`.
   ```bash
   kubectl get pvc -l app=kafka-old
   ```
   *Допустим, найдены PVC: `kafka-pvc-0`, `kafka-pvc-1`, `kafka-pvc-2`.*

3. **Создание Headless Service:**
   ```yaml
   apiVersion: v1
   kind: Service
   metadata:
     name: kafka-headless
   spec:
     clusterIP: None
     selector:
       app: kafka-new
     ports:
     - port: 9092
       name: broker
   ```

#### Шаг 2: Создание манифеста StatefulSet

Подготовьте файл `kafka-sts.yaml`. Важно сопоставить `broker.id` с индексом пода.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: kafka
spec:
  serviceName: "kafka-headless"
  replicas: 3
  selector:
    matchLabels:
      app: kafka-new
  template:
    metadata:
      labels:
        app: kafka-new
    spec:
      containers:
      - name: kafka
        image: bitnami/kafka:3.7.0
        env:
        - name: KAFKA_CFG_NODE_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name # Логика извлечения индекса из имени
        - name: KAFKA_CFG_ADVERTISED_LISTENERS
          value: "PLAINTEXT://$(MY_POD_NAME).kafka-headless.svc.cluster.local:9092"
        volumeMounts:
        - name: data
          mountPath: /bitnami/kafka
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: [ "ReadWriteOnce" ]
      storageClassName: "ssd-storage"
      resources:
        requests:
          storage: 50Gi
```

#### Шаг 3: Перенос данных

1. **Остановка старого Deployment:**
   ```bash
   kubectl scale deployment kafka-old --replicas=0
   ```
2. **Инициализация новых PVC:** Примените манифест StS и сразу уменьшите количество реплик до 0. Это создаст пустые тома.
   ```bash
   kubectl apply -f kafka-sts.yaml
   kubectl scale statefulset kafka --replicas=0
   ```
3. **Копирование данных (rsync):** Запустите временный под для переноса данных между томами. Повторите для каждого индекса.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: data-migrator-0
spec:
  containers:
  - name: rsync
    image: alpine:latest
    command: ["/bin/sh", "-c", "apk add rsync && rsync -avP /src/ /dst/ && sleep 3600"]
    volumeMounts:
    - name: source
      mountPath: /src
    - name: destination
      mountPath: /dst
  volumes:
  - name: source
    persistentVolumeClaim:
      claimName: kafka-pvc-0 # PVC от Deployment
  - name: destination
    persistentVolumeClaim:
      claimName: data-kafka-0 # PVC от StatefulSet
```

#### Шаг 4: Запуск и валидация

1. **Запуск StatefulSet:**
   ```bash
   kubectl scale statefulset kafka --replicas=3
   ```
2. **Проверка логов:** Убедитесь, что брокеры видят свои старые сегменты логов (файл `meta.properties` в корне данных должен быть корректным).
3. **Smoke-тест:** Убедитесь, что консьюмеры могут прочитать данные, записанные до миграции.

---

## Дополнительная информация

### Нюансы и риски

- **Broker IDs:** Если в `Deployment` использовались случайные `broker.id`, после миграции необходимо либо обновить их в `meta.properties`, либо настроить маппинг в StS. Несоответствие ID приведет к тому, что брокер будет считаться новым, и начнется полная репликация данных (что долго и нагружает сеть).
- **ZooKeeper Chroot:** Если вы использовали ZooKeeper в `Deployment`, убедитесь, что путь подключения в StS совпадает до символа.
- **Очистка:** Удаляйте старые PVC и Deployment только после полной уверенности в сохранности данных в новом StatefulSet.

### См. также

- **[Обзор Apache Kafka](./kafka_overview.md)** — общие принципы работы платформы.
- **[StatefulSet в Kubernetes](../Kubernetes/Base/StatefulSet/statefulset_overview.md)** — подробное руководство по работе StS.
- **[Гарантии доставки](./delivery_guarantees.md)** — семантика и надежность данных в Kafka.
