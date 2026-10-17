# StatefulSet: Практическое руководство

**Актуально для:** Kubernetes 1.35–1.37

## Определения

*   **StatefulSet** — базовый контроллер рабочей нагрузки Kubernetes API (`apps/v1`), предназначенный для управления группой подов с сохранением уникального состояния, стабильных сетевых идентификаторов и детерминированного порядка жизненного цикла.
*   **Headless Service** — сетевой сервис без виртуального IP-кластера (`spec.clusterIP: None`), создающий прямые DNS A/AAAA- и SRV-записи для каждого индивидуального пода контроллера.
*   **VolumeClaimTemplates** — массив шаблонов PersistentVolumeClaim внутри спецификации StatefulSet, на основе которых контроллер автоматически генерирует персональный изолированный том для каждой создаваемой реплики.
*   **PersistentVolumeClaim (PVC)** — запрос на выделение дискового пространства в подсистеме хранения Kubernetes, привязываемый к конкретному индексу пода на весь срок существования рабочей нагрузки.
*   **Порядковый индекс (Ordinal Index)** — целочисленный номер (по умолчанию от `0` до `replicas - 1`), однозначно определяющий имя пода, сетевой FQDN, имя привязанного диска и очередность создания/удаления.
*   **Sticky Storage** — архитектурный принцип StatefulSet, согласно которому при падении или перезапуске пода с индексом $N$ ему повторно монтируется ровно тот же том PVC с индексом $N$.
*   **ControllerRevision** — версионированный объект снимка спецификации шаблона StatefulSet, используемый контроллером для поэтапного обновления и детерминированного отката к предыдущим ревизиям.
*   **Native Sidecar** — вспомогательный контейнер, описанный в блоке `initContainers` с директивой `restartPolicy: Always` (GA в Kubernetes v1.33), запускаемый строго до основного контейнера и завершаемый после него.
*   **VolumeAttributesClass** — объект управления параметрами дисков (GA в Kubernetes v1.34), позволяющий динамически изменять производительность (IOPS, throughput) существующего тома без его перемонтирования или пересоздания.

Теоретическую базу и описание внутренних механизмов контроллера см. в разделах **[StatefulSet: Обзор](./statefulset_overview.md)** и **[StatefulSet: Ключевые концепции](./statefulset_core_concepts.md)**.

## Архитектура и основные концепции

### Архитектурные компоненты и модель изоляции

Контроллер StatefulSet решает задачу управления нагрузками, требующими сохранения идентичности при любых сбоях физической инфраструктуры. В отличие от Deployment, где поды взаимозаменяемы и используют эфемерные имена (`pod-hash-random`), StatefulSet формирует предсказуемую топологию:

```
                  ┌──────────────────────────────────────────────┐
                  │          Headless Service (DNS)              │
                  │   mysql-headless.default.svc.cluster.local   │
                  └──────┬──────────────────┬─────────────────┬──┘
                         │                  │                 │
                DNS A    ▼         DNS A    ▼        DNS A    ▼
             ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
             │    mysql-0    │  │    mysql-1    │  │    mysql-2    │
             │ (Ordinal: 0)  │  │ (Ordinal: 1)  │  │ (Ordinal: 2)  │
             └───────┬───────┘  └───────┬───────┘  └───────┬───────┘
                     │                  │                  │
               Mount │            Mount │            Mount │
                     ▼                  ▼                  ▼
             ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
             │ PVC: data-    │  │ PVC: data-    │  │ PVC: data-    │
             │   mysql-0     │  │   mysql-1     │  │   mysql-2     │
             └───────┬───────┘  └───────┬───────┘  └───────┬───────┘
                     │                  │                  │
                     ▼                  ▼                  ▼
             ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
             │  PV (Disk 0)  │  │  PV (Disk 1)  │  │  PV (Disk 2)  │
             └───────────────┘  └───────────────┘  └───────────────┘
```

1.  **Сетевая идентичность:** каждый под получает предсказуемое доменное имя формата `$(pod-name).$(service-name).$(namespace).svc.cluster.local`. Имя сохраняется при любых перезапусках и миграциях между узлами.
2.  **Порядковый номер и метки:** каждому поду автоматически присваивается порядковый индекс. Системные метки пода:
    *   `statefulset.kubernetes.io/pod-name: $(pod-name)`
    *   `apps.kubernetes.io/pod-index: "$(ordinal)"` (стабильно с v1.32; позволяет маршрутизировать трафик сервисов и собирать метрики строго с определенных реплик без парсинга имен).
3.  **Жизненный цикл томов (`persistentVolumeClaimRetentionPolicy`):** механизм управления судьбой PVC при изменении масштаба и удалении контроллера (GA v1.32). Допустимые значения: `Retain` (сохранить PVC) и `Delete` (удалить PVC):
    *   `whenDeleted`: реакция на удаление объекта StatefulSet.
    *   `whenScaled`: реакция на уменьшение количества реплик (`scale down`).
4.  **Порядок развертывания (`podManagementPolicy`):**
    *   `OrderedReady` (по умолчанию): поды создаются последовательно от $0$ до $N-1$. Следующий под создается только после перехода предыдущего в статус `Running` и `Ready`. При масштабировании вниз поды удаляются строго в обратном порядке (от $N-1$ к $0$).
    *   `Parallel`: поды создаются и удаляются параллельно, без ожидания готовности соседей (применяется для пакетных вычислений и распределенных систем, самостоятельно управляющих кворумом).

### Предварительные требования к инфраструктуре (On-Premise / Bare-Metal)

1.  **Версия платформы:** Kubernetes **v1.35–v1.37**. Функционал `ordinals` стабилен с v1.31, `persistentVolumeClaimRetentionPolicy` и метка `apps.kubernetes.io/pod-index` — с v1.32, нативные sidecar-контейнеры — с v1.33, `VolumeAttributesClass` — с v1.34.
2.  **Утилита `kubectl`:** версии, соответствующей версии управляющего контура кластера.
3.  **Подсистема хранения данных:** локальный или блочный CSI-драйвер с поддержкой динамического провижининга (Ceph RBD, TopoLVM, LVM-Local, SAN/iSCSI).
    *   StorageClass должен иметь параметр `volumeBindingMode: WaitForFirstConsumer`, чтобы том создавался в той топологической зоне / на том узле, куда планировщик поместил под.
    *   Для динамического изменения размера требуется `allowVolumeExpansion: true`.
4.  **Сетевой плагин (CNI):** поддерживающий сетевые политики NetworkPolicy и корректную маршрутизацию доменных имен через CoreDNS.

Проверка готовности среды перед выполнением сценариев:

```bash
# Проверка версии сервера
kubectl version -o json | jq -r '.serverVersion.gitVersion'
# → v1.35.2

# Проверка параметров доступных StorageClass
kubectl get storageclass -o custom-columns=NAME:.metadata.name,PROVISIONER:.provisioner,BINDING:.volumeBindingMode,EXPAND:.allowVolumeExpansion
# → NAME                 PROVISIONER          BINDING                EXPAND
# → local-nvme-topolvm   topolvm.io           WaitForFirstConsumer   true
# → rbd-ceph-csi         rbd.csi.ceph.com     WaitForFirstConsumer   true
```

## Конфигурация и практические сценарии

### Сценарий 1: Развертывание отказоустойчивого веб-сервиса с удержанием дисков

Цель: развернуть кластерный сервис с уникальными страницами данных для каждого пода и настроенной политикой автоматической очистки томов при масштабировании, исключающей утечки дискового пространства на СХД.

#### Шаг 1: Создание сетевой инфраструктуры (Headless Service)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-headless
  labels:
    app.kubernetes.io/name: nginx-stateful
spec:
  clusterIP: None
  selector:
    app.kubernetes.io/name: nginx-stateful
  ports:
  - port: 80
    name: web
    targetPort: 80
```

#### Шаг 2: Создание контроллера StatefulSet

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web-app
spec:
  serviceName: "nginx-headless"
  replicas: 3
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain  # Сохранять данные при удалении StatefulSet
    whenScaled: Delete   # Автоматически удалять том при уменьшении числа реплик
  selector:
    matchLabels:
      app.kubernetes.io/name: nginx-stateful
  template:
    metadata:
      labels:
        app.kubernetes.io/name: nginx-stateful
    spec:
      containers:
      - name: nginx
        image: nginx:1.27.4-alpine
        ports:
        - containerPort: 80
          name: web
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "200m"
            memory: "256Mi"
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
```

Применение манифестов:

```bash
kubectl apply -f nginx-headless.yaml
# → service/nginx-headless created

kubectl apply -f web-app-statefulset.yaml
# → statefulset.apps/web-app created
```

#### Шаг 3: Проверка сохранения данных (Sticky Storage)

```bash
# 1. Запись уникальных данных на диск нулевой реплики
kubectl exec web-app-0 -- sh -c 'echo "Node Index 0 Payload" > /usr/share/nginx/html/index.html'

# 2. Удаление пода для проверки восстановления привязки диска
kubectl delete pod web-app-0
# → pod "web-app-0" deleted

# 3. Наблюдение за циклом пересоздания пода контроллером
kubectl get pods -l app.kubernetes.io/name=nginx-stateful -w
# → web-app-0   0/1     Pending             0          0s
# → web-app-0   0/1     ContainerCreating   0          2s
# → web-app-0   1/1     Running             0          4s

# 4. Проверка сохранности записанных данных
kubectl exec web-app-0 -- cat /usr/share/nginx/html/index.html
# → Node Index 0 Payload
```

Проверка созданных объектов PVC и их связки с индексами подов:

```bash
kubectl get pvc -l app.kubernetes.io/name=nginx-stateful
# → NAME             STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS         AGE
# → data-web-app-0   Bound    pvc-8f2b5a1c-34d2-45e6-a78b-90c12e345678   1Gi        RWO            rbd-ceph-csi         3m
# → data-web-app-1   Bound    pvc-1a4e6f8b-789a-4123-bcde-0123456789ab   1Gi        RWO            rbd-ceph-csi         3m
# → data-web-app-2   Bound    pvc-9c8d7e6f-5432-41ba-9876-fedcba987654   1Gi        RWO            rbd-ceph-csi         3m
```

---

### Сценарий 2: Развертывание реляционной базы данных (MySQL 8.4 LTS) с Production-параметрами

Цель: развернуть экземпляр СУБД с изоляцией паролей через Secret, классом обслуживания Guaranteed QoS, разделенными пробами готовности/живучести и Startup Probe для защиты процесса восстановления транзакций (InnoDB crash recovery).

```yaml
apiVersion: v1
kind: Service
metadata:
  name: mysql-db
  labels:
    app.kubernetes.io/name: mysql
spec:
  clusterIP: None
  selector:
    app.kubernetes.io/name: mysql
  ports:
  - port: 3306
    name: mysql
---
apiVersion: v1
kind: Secret
metadata:
  name: mysql-credentials
type: Opaque
stringData:
  ROOT_PASSWORD: "K8sSecureEnterprisePassword2026!"
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mysql
spec:
  serviceName: "mysql-db"
  replicas: 1
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain
    whenScaled: Retain
  selector:
    matchLabels:
      app.kubernetes.io/name: mysql
  template:
    metadata:
      labels:
        app.kubernetes.io/name: mysql
    spec:
      terminationGracePeriodSeconds: 120
      containers:
      - name: mysql
        image: mysql:8.4.3
        env:
        - name: MYSQL_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-credentials
              key: ROOT_PASSWORD
        ports:
        - containerPort: 3306
          name: mysql
        # Startup Probe предотвращает гибель пода при тяжелой инициализации или откате WAL
        startupProbe:
          tcpSocket:
            port: 3306
          initialDelaySeconds: 15
          periodSeconds: 10
          failureThreshold: 30   # Окно до 5 минут на старт сервиса
        readinessProbe:
          exec:
            command: ["sh", "-c", "mysqladmin ping -h 127.0.0.1 -uroot -p$MYSQL_ROOT_PASSWORD"]
          initialDelaySeconds: 10
          periodSeconds: 5
          timeoutSeconds: 2
        livenessProbe:
          tcpSocket:
            port: 3306
          periodSeconds: 15
          failureThreshold: 3
        # Guaranteed QoS: requests равны limits (защита от OOMKilled при нехватке памяти на узле)
        resources:
          requests:
            cpu: "2"
            memory: "4Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
        volumeMounts:
        - name: mysql-data
          mountPath: /var/lib/mysql
  volumeClaimTemplates:
  - metadata:
      name: mysql-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 50Gi
```

Пояснения к производственной конфигурации:
*   **Startup Probe:** пока проверка старта не пройдет успешно, `readinessProbe` и `livenessProbe` заморожены. Это защищает базу от циклического убийства демоном kubelet, если InnoDB выполняет накат журналов при старте после аварии.
*   **Guaranteed QoS:** равенство `requests` и `limits` присваивает поду наивысший приоритет живучести на узле Linux (OOM score -997). Под не будет завершен при вытеснении памяти.
*   **Ограничение официального образа:** переменные `MYSQL_*` применяются только при создании пустой базы данных. Несколько реплик манифеста не образуют кластерную репликацию автоматически. Полноценная настройка репликации требует операторов (CloudNativePG для PostgreSQL, Vitess / MySQL Operator для MySQL).

---

### Сценарий 3: Запуск и межкластерная миграция подов через `ordinals.start`

Цель: запустить группу реплик со смещением начального индекса (GA v1.31) для параллельной эксплуатации двух площадок или секционирования шардов без пересечения сетевых имен.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: cache-node
spec:
  serviceName: "cache-headless"
  replicas: 3
  ordinals:
    start: 3  # Создаст поды: cache-node-3, cache-node-4, cache-node-5
  selector:
    matchLabels:
      app.kubernetes.io/name: cache-cluster
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cache-cluster
    spec:
      containers:
      - name: redis
        image: redis:7.4.2-alpine
        ports:
        - containerPort: 6379
          name: redis
  volumeClaimTemplates:
  - metadata:
      name: cache-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

Валидация порядка запуска и меток:

```bash
kubectl apply -f cache-statefulset.yaml
# → statefulset.apps/cache-node created

# Проверка индексов через стандартную системную метку (GA v1.32)
kubectl get pods -l app.kubernetes.io/name=cache-cluster -L apps.kubernetes.io/pod-index,statefulset.kubernetes.io/pod-name
# → NAME           READY   STATUS    RESTARTS   AGE   POD-INDEX   POD-NAME
# → cache-node-3   1/1     Running   0          18s   3           cache-node-3
# → cache-node-4   1/1     Running   0          12s   4           cache-node-4
# → cache-node-5   1/1     Running   0          6s    5           cache-node-5
```

Правила эксплуатации `ordinals.start`:
1.  **Диапазоны не должны пересекаться:** при миграции между старым и новым контуром старый кластер использует `start: 0` (`0, 1, 2`), а новый — `start: 3` (`3, 4, 5`).
2.  **Иммутабельность рабочего диапазона:** изменение поля `ordinals.start` на работающем контроллере приведет к масштабированию и созданию новых подов, а старые тома останутся нескоординированными.

---

### Сценарий 4: Нативные Sidecar-контейнеры (`restartPolicy: Always`)

Цель: настроить вспомогательный контейнер (локальный аутентификационный прокси или агент мониторинга) с гарантированным запуском строго до старта основного сервиса и корректным завершением при выключении пода.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: secure-app
spec:
  serviceName: "secure-app-service"
  replicas: 2
  selector:
    matchLabels:
      app.kubernetes.io/name: secure-app
  template:
    metadata:
      labels:
        app.kubernetes.io/name: secure-app
    spec:
      initContainers:
      - name: auth-proxy
        image: quay.io/oauth2-proxy/oauth2-proxy:v7.8.1
        restartPolicy: Always  # Нативный Sidecar (GA v1.33)
        ports:
        - containerPort: 4180
          name: proxy
        readinessProbe:
          httpGet:
            path: /ping
            port: 4180
          initialDelaySeconds: 2
          periodSeconds: 3
        resources:
          requests:
            cpu: "100m"
            memory: "64Mi"
          limits:
            cpu: "200m"
            memory: "128Mi"
      containers:
      - name: backend
        image: nginx:1.27.4-alpine
        ports:
        - containerPort: 80
          name: http
        resources:
          requests:
            cpu: "200m"
            memory: "256Mi"
          limits:
            cpu: "500m"
            memory: "512Mi"
```

Особенности поведения нативных Sidecar в StatefulSet:
*   **Детерминированный старт:** `initContainer` с `restartPolicy: Always` стартует первым. Основной контейнер `backend` начинает запуск только тогда, когда `auth-proxy` перешел в состояние готовности (`Ready`) по результатам `readinessProbe`.
*   **Упорядоченный Rollout:** реплика StatefulSet переходит к запуску следующего индекса только после полной готовности всех основных и sidecar-контейнеров текущего пода.
*   **Корректный дренаж при остановке:** при удалении пода основной контейнер `backend` получает сигнал `SIGTERM` первым, выполняет сброс соединений, и только после его полной остановки сигнал на выключение получает `auth-proxy`.

---

### Сценарий 5: Изменение размера томов (Volume Resizing) и модификация шаблона

Поскольку массив `volumeClaimTemplates` в спецификации StatefulSet является неизменяемым (`immutable`), увеличение емкости дисков требует разделения на пошаговые операции.

#### Метод 5A: Онлайн/офлайн расширение существующих томов PVC

Применяется, когда StorageClass поддерживает динамическое расширение (`allowVolumeExpansion: true`), и необходимо увеличить емкость работающих дисков.

```bash
# 1. Проверка поддержки расширения классом хранения
kubectl get storageclass rbd-ceph-csi -o jsonpath='{.allowVolumeExpansion}{"\n"}'
# → true

# 2. Патч размера каждого PVC поочередно
kubectl patch pvc data-web-app-0 -p '{"spec":{"resources":{"requests":{"storage":"5Gi"}}}}'
# → persistentvolumeclaim/data-web-app-0 patched

# 3. Инспекция состояния PVC и файловой системы
kubectl describe pvc data-web-app-0 | grep -A2 "Conditions:"
# При онлайн-расширении CSI-плагин автоматически увеличивает емкость ФС.
# Если драйвер требует перемонтирования (FileSystemResizePending), перезапускаем под:
kubectl delete pod web-app-0
# → pod "web-app-0" deleted

# 4. Проверка итоговой емкости тома
kubectl get pvc data-web-app-0
# → NAME             STATUS   VOLUME       CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → data-web-app-0   Bound    pvc-8f2b…    5Gi        RWO            rbd-ceph-csi   10m
```

#### Метод 5B: Изменение шаблона через каскадное пересоздание без подов (`--cascade=orphan`)

Применяется, когда требуется обновить значение `storage` в самом манифесте StatefulSet для всех будущих реплик, не останавливая работу запущенных сервисов.

```bash
# 1. Удаление объекта StatefulSet с сохранением работающих подов
kubectl delete statefulset web-app --cascade=orphan
# → statefulset.apps "web-app" deleted

# 2. Обновление значения storage в манифесте (например, с 1Gi на 5Gi)
# 3. Применение обновленного манифеста
kubectl apply -f web-app-statefulset.yaml
# → statefulset.apps/web-app created

# 4. Контроллер автоматически подхватывает существующие поды без рестарта:
kubectl get statefulset web-app
# → NAME      READY   AGE
# → web-app   3/3     15s
```

#### Метод 5C: Изменение профиля производительности через `VolumeAttributesClass`

Начиная с Kubernetes v1.34 (GA), класс `VolumeAttributesClass` позволяет изменять параметры диска (IOPS, throughput) без изменения размера и без перезапуска подов.

```yaml
apiVersion: storage.k8s.io/v1
kind: VolumeAttributesClass
metadata:
  name: iops-gold
driverName: rbd.csi.ceph.com
parameters:
  iops: "5000"
  throughput: "250Mi"
```

Применение нового профиля производительности к существующему диску:

```bash
kubectl apply -f vac-gold.yaml
# → volumeattributesclass.storage.k8s.io/iops-gold created

# Патч класса атрибутов в работающем PVC
kubectl patch pvc data-web-app-0 -p '{"spec":{"volumeAttributesClassName":"iops-gold"}}'
# → persistentvolumeclaim/data-web-app-0 patched

# Проверка применения атрибутов
kubectl get pvc data-web-app-0 -o jsonpath='{.status.currentVolumeAttributesClassName}{"\n"}'
# → iops-gold
```

---

### Сценарий 6: Канареечное обновление через `partition` (Canary Rollout)

Цель: безопасно обновить StatefulSet из 3 реплик (`0`, `1`, `2`), выкатив новый релиз приложения только на один под с максимальным индексом (`web-app-2`), проверив его поведение под нагрузкой.

```bash
# 1. Фиксация границы обновления на индексе 2 (обновится только web-app-2)
kubectl patch statefulset web-app -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":2}}}}'
# → statefulset.apps/web-app patched

# 2. Обновление версии образа приложения в спецификации
kubectl set image statefulset/web-app nginx=nginx:1.27.4-alpine
# → statefulset.apps/web-app image updated

# 3. Наблюдение за обновлением единственного канареечного пода
kubectl rollout status statefulset/web-app
# → Waiting for partitioned rollout to finish: 1 out of 3 new pods have been updated...

# 4. Проверка версий контейнеров в подах
kubectl get pods -l app.kubernetes.io/name=nginx-stateful -o custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[0].image
# → NAME         IMAGE
# → web-app-0    nginx:1.27.0-alpine
# → web-app-1    nginx:1.27.0-alpine
# → web-app-2    nginx:1.27.4-alpine

# 5. Проверка стабильности и снятие барьера (раскатка на индексы 1 и 0)
kubectl patch statefulset web-app -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
# → statefulset.apps/web-app patched

# 6. Ожидание завершения полного обновления
kubectl rollout status statefulset/web-app --timeout=180s
# → statefulset rolling update complete 3 pods at revision web-app-798bf8d956...
```

## Операции и команды

### Сводная таблица команд администрирования

| Операция | Команда `kubectl` | Назначение |
|---|---|---|
| Инспекция контроллера | `kubectl get sts -o wide` | Просмотр числа готовых реплик, сервиса и базовых образов |
| Просмотр ревизий | `kubectl rollout history sts/<name>` | Список записанных ревизий `ControllerRevision` |
| Просмотр объектов ревизий | `kubectl get controllerrevisions -l <selector>` | Список физических объектов снимков шаблона |
| Откат к ревизии | `kubectl rollout undo sts/<name> --to-revision=<N>` | Возврат спецификации к указанной ревизии |
| Масштабирование | `kubectl scale sts/<name> --replicas=<N>` | Изменение числа реплик с соблюдением порядка индексов |
| Перезапуск подов | `kubectl rollout restart sts/<name>` | Поочередный рестарт подов от $N-1$ до $0$ |
| Патч границы обновления | `kubectl patch sts/<name> -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":N}}}}'` | Фиксация барьера канареечного обновления |
| Проверка привязки дисков | `kubectl get pvc -l <selector> -L volume` | Контроль статуса `Bound` и привязанных PV |

### Управление ревизиями и откат изменений

StatefulSet сохраняет историю изменений шаблона в объектах `ControllerRevision`:

```bash
# Просмотр истории ревизий
kubectl rollout history statefulset/web-app
# → statefulset.apps/web-app
# → REVISION  CHANGE-CAUSE
# → 1         <none>
# → 2         kubectl set image statefulset/web-app nginx=nginx:1.27.4-alpine

# Детальный просмотр конкретной ревизии
kubectl rollout history statefulset/web-app --revision=1
# → statefulset.apps/web-app with revision #1
# → Pod Template:
# →   Containers:
# →    nginx:
# →     Image:      nginx:1.27.0-alpine

# Экстренный откат к предыдущей рабочей ревизии
kubectl rollout undo statefulset/web-app --to-revision=1
# → statefulset.apps/web-app rolled back

kubectl rollout status statefulset/web-app --timeout=120s
# → statefulset rolling update complete 3 pods at revision web-app-6f97d5b8c...
```

### Полная очистка окружения (декомиссия)

При выводе сервиса из эксплуатации критически важен строгий порядок удаления компонентов во избежание блокировок CSI-драйвера и утечек дискового пространства:

```bash
# 1. Проверка политики удержания дисков контроллера
kubectl get statefulset web-app -o jsonpath='{.spec.persistentVolumeClaimRetentionPolicy}{"\n"}'
# → {"whenDeleted":"Retain","whenScaled":"Delete"}

# 2. Удаление контроллера StatefulSet (поды завершаются по очереди в обратном порядке)
kubectl delete statefulset web-app
# → statefulset.apps "web-app" deleted

# 3. Ручное удаление PVC (освобождает PV в соответствии с persistentVolumeReclaimPolicy)
kubectl delete pvc data-web-app-0 data-web-app-1 data-web-app-2
# → persistentvolumeclaim "data-web-app-0" deleted
# → persistentvolumeclaim "data-web-app-1" deleted
# → persistentvolumeclaim "data-web-app-2" deleted

# 4. Удаление Headless Service
kubectl delete service nginx-headless
# → service "nginx-headless" deleted

# 5. Очистка снимков томов при их наличии
kubectl get volumesnapshot -l app.kubernetes.io/name=nginx-stateful
kubectl delete volumesnapshot -l app.kubernetes.io/name=nginx-stateful
# → No resources found
```

## Диагностика и устранение неполадок

### Экспресс-диагностика DNS-идентификации

Проверка разрешения сетевых имен через временный диагностический под с инструментами `bind-tools`:

```bash
# Проверка разрешения A-записи конкретного пода
kubectl run dns-test --image=busybox:1.36.1 -it --rm --restart=Never -- nslookup web-app-0.nginx-headless
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      web-app-0.nginx-headless.default.svc.cluster.local
# → Address:   10.244.2.14

# Проверка SRV-записей именованных портов сервиса
kubectl run dns-srv-test --image=busybox:1.36.1 -it --rm --restart=Never -- nslookup -type=SRV _web._tcp.nginx-headless.default.svc.cluster.local
# → _web._tcp.nginx-headless.default.svc.cluster.local service = 0 33 80 web-app-0.nginx-headless.default.svc.cluster.local.
# → _web._tcp.nginx-headless.default.svc.cluster.local service = 0 33 80 web-app-1.nginx-headless.default.svc.cluster.local.
```

Если DNS-запись отсутствует:
1.  Убедитесь, что под перешел в состояние `Ready`. По умолчанию CoreDNS не публикует IP-адреса не готовых подов. Если требуется опрос до готовности (для инициализации кворума), включите `spec.publishNotReadyAddresses: true` в манифесте Headless Service.
2.  Проверьте соответствие селектора сервиса меткам шаблона пода (`labels`).

### Анализ застревания подов в статусе `Pending`

Если под StatefulSet не переходит в статус `Running`:

```bash
# 1. Проверка состояния PVC
kubectl get pvc -l app.kubernetes.io/name=web-app
# Если статус Pending — проблема в провижининге хранилища

# 2. Детальный анализ событий PVC
kubectl describe pvc data-web-app-0 | grep -A5 Events
# Типовая причина: StorageClass WaitForFirstConsumer ждет назначения пода на узел

# 3. Анализ событий пода
kubectl describe pod web-app-0 | grep -A10 Events
```

Типовые причины застревания:
*   `0/X nodes available: volume node affinity conflict`: том привязан к локальному диску конкретного узла, а узел занят или имеет несовместимые `taints`.
*   `Insufficient memory / cpu`: планировщик не может найти узел, удовлетворяющий запросам `resources.requests` с учетом правил анти-аффинити.

### Неплановый отказ узла (Non-Graceful Node Shutdown)

Если физический сервер аварийно отключился по питанию или потерял связь с сетью, Kubernetes переводит узел в состояние `NotReady`. При этом под StatefulSet переходит в статус `Terminating` или `Unknown`.

> [!CAUTION]
> **Никогда не выполняйте `kubectl delete pod --force --grace-period=0` без подтверждения изоляции узла!**
> Блочные тома (RWO) остаются примонтированными к мертвому узлу. Принудительное удаление приведет к запуску второго экземпляра пода на другом узле и одновременной записи в один диск двумя машинами (Multi-Attach / Split-Brain), что гарантированно разрушит файловую систему или базу данных.

Штатная процедура безопасного восстановления (GA с Kubernetes v1.28):

```bash
# 1. Фиксация неисправности узла
kubectl get nodes
# → worker-02   NotReady   <none>   14d   v1.35.2

# 2. Наложение специального системного taint out-of-service
kubectl taint nodes worker-02 node.kubernetes.io/out-of-service=nodeshutdown:NoExecute
# → node/worker-02 tainted

# 3. Kube-controller-manager безопасно отсоединяет том через VolumeAttachment
#    и пересоздает под с сохранением PVC на исправном узле
kubectl get pods -l app.kubernetes.io/name=web-app -o wide
# → web-app-1   1/1   Running   0   45s   10.244.3.18   worker-03

# 4. После физического ремонта или замены узла — обязательное снятие taint:
kubectl taint nodes worker-02 node.kubernetes.io/out-of-service:NoExecute-
# → node/worker-02 untainted
```

---

### SRE Runbook: ликвидация аварийных инцидентов

#### Инцидент 1: Под завис в `Terminating` на недоступном узле

*   **Симптом:** `web-app-0` висит в статусе `Terminating`, узел в `NotReady`, события выдают ошибку `VolumeAttachment: volume is still attached to node`.
*   **Причина:** Авария оборудования узла, kubelet не может подтвердить отмонтирование тома.
*   **Регламент действий:**
    1.  Убедиться через консоль IPMI/BMC, что физический узел действительно выключен или изолирован от сети.
    2.  Наложить taint `node.kubernetes.io/out-of-service=nodeshutdown:NoExecute` на упавший узел.
    3.  Дождаться, пока CSI-контроллер снимет блокировку `VolumeAttachment` и пересоздаст под на живом узле.
    4.  Принудительный `delete --force` допустим только как крайняя мера после подтверждения выключения питания старого узла.

#### Инцидент 2: RollingUpdate заблокирован

*   **Симптом:** `kubectl rollout status` зависает на этапе `Waiting for 1 pods to be ready...`.
*   **Причина:** Новый под упал в `CrashLoopBackOff` или не проходит `readinessProbe` из-за неверной конфигурации или ошибки приложения.
*   **Регламент действий:**
    1.  Выявить проблемный индекс: `kubectl get pods -l <selector>`.
    2.  Снять логи упавшего контейнера: `kubectl logs <pod-name> --previous --tail=100`.
    3.  Зафиксировать границу обновления, чтобы остановить деградацию остальных реплик:
        ```bash
        kubectl patch sts <name> -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":N}}}}'
        ```
    4.  Выполнить откат: `kubectl rollout undo sts/<name>`.

#### Инцидент 3: Потеря кворума кластера СУБД (все реплики `NotReady`)

*   **Симптом:** Все реплики базы данных перешли в статус `NotReady` или циклический рестарт.
*   **Причина:** Авария подсистемы хранения, переполнение диска журналов (WAL/binlog) или разрыв сети.
*   **Регламент действий:**
    1.  Проверить доступность дискового пространства внутри контейнеров:
        ```bash
        kubectl exec <pod-name> -- df -h
        ```
    2.  Если диск заполнен на 100%, выполнить аварийное расширение PVC (Сценарий 5A).
    3.  Проверить сетевую связность между репликами через Headless Service DNS.
    4.  Для Patroni/etcd: проверить статус кворума через утилиту управления оператора.

#### Инцидент 4: PVC в статусе `Pending`

*   **Симптом:** Под ожидает запуска, связанный PVC находится в состоянии `Pending`.
*   **Причина:** Исчерпание дискового пула на СХД, сбой CSI-драйвера или несоответствие топологии.
*   **Регламент действий:**
    1.  Инспектировать события: `kubectl describe pvc <pvc-name>`.
    2.  Проверить статус CSI-демонов: `kubectl get pods -n kube-system -l app=ceph-csi-rbd`.
    3.  Проверить свободное место на пуле хранения Ceph / LVM.

#### Инцидент 5: Критический replication lag

*   **Симптом:** Метрика отставания репликации превышает SLA (>30с), реплики отстают от лидера.
*   **Причина:** Нехватка ресурсов CPU/IOPS на узле реплики, долгие блокирующие транзакции.
*   **Регламент действий:**
    1.  Проверить текущие тяжелые запросы на мастере:
        ```bash
        kubectl exec mysql-0 -- mysql -e "SHOW FULL PROCESSLIST;"
        ```
    2.  Проверить задержки дискового ввода-вывода (IO await) на узле через Node Exporter.
    3.  При необходимости временно поднять `limits` по ресурсам или перевести под на более быстрый класс диска.

#### Инцидент 6: Переполнение файловой системы тома (DiskPressure)

*   **Симптом:** Алерт `KubePersistentVolumeFillingUp`, ошибки записи `No space left on device`.
*   **Причина:** Накопление временных таблиц, несжатых дампов или логов.
*   **Регламент действий:**
    1.  Локализовать точку заполнения:
        ```bash
        kubectl exec <pod-name> -- du -sh /var/lib/mysql/* | sort -rh | head -n 5
        ```
    2.  Удалить временные файлы (никогда не удалять активные сегменты данных вручную).
    3.  Немедленно увеличить емкость тома через `kubectl patch pvc`.

## Лучшие практики

### Чек-лист SRE перед вводом StatefulSet в эксплуатацию

- [ ] **StorageClass:** настроен с параметрами `volumeBindingMode: WaitForFirstConsumer` и `allowVolumeExpansion: true`.
- [ ] **PodDisruptionBudget (PDB):** создан объект PDB с формулой `minAvailable: ⌈N/2⌉ + 1` для защиты кворума при плановом дренаже серверов.
- [ ] **Качество обслуживания (QoS):** задан класс **Guaranteed** (`requests == limits`) для памяти и ядер, исключающий OOM-выселение.
- [ ] **Startup Probes:** сконфигурированы с достаточным запасом попыток (`failureThreshold * periodSeconds >= 300s`) для предотвращения убийства процесса при холодном старте или накате журналов.
- [ ] **Политика удержания:** выставлена в `whenDeleted: Retain` для предотвращения случайной потери данных при удалении манифестов.
- [ ] **Сетевая изоляция:** применены манифесты NetworkPolicy, ограничивающие доступ к портам базы данных только авторизованными подами бекенда.
- [ ] **Секреты:** учетные данные смонтированы через Kubernetes Secret или HashiCorp Vault Sidecar, открытый текст в манифестах отсутствует.
- [ ] **Метрики и мониторинг:** настроен экспорт метрик (mysqld_exporter, postgres_exporter) через Sidecar или аннотации сбора Prometheus.

### Регламент планового обслуживания серверов (Node Drain)

Перед выводом физического сервера на техническое обслуживание выполняется регламент дренажа с контролем бюджета доступности:

```bash
# 1. Проверка допустимого количества выселений в объекте PDB
kubectl get pdb
# → NAME         MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → mysql-pdb    1               N/A               1                     30d

# 2. Изоляция узла (запрет размещения новых подов)
kubectl cordon worker-01
# → node/worker-01 cordoned

# 3. Безопасное выселение подов с соблюдением PDB
kubectl drain worker-01 --ignore-daemonsets --delete-emptydir-data
# → evicting pod default/mysql-1
# → pod/mysql-1 evicted
# → node/worker-01 drained

# 4. Проверка запуска выселенного пода на другом сервере
kubectl rollout status statefulset/mysql --timeout=180s
# → Waiting for 1 pods to be ready...
# → statefulset rolling update complete 2 pods at revision mysql-68f7b...

# 5. Возврат узла в строй после завершения аппаратных работ
kubectl uncordon worker-01
# → node/worker-01 uncordoned
```

### Алгоритм безопасного бессбойного обновления баз данных

1.  **Канареечный rollout через `partition: N-1`:** обновить только последний под реплики, убедиться в стабильности replication lag и отсутствии ошибок в журналах.
2.  **Задержка завершения процесса (`terminationGracePeriodSeconds: 120-300`):** выделить процессу СУБД достаточное время для корректного сброса буферов (fsync dirty pages) и передачи лидерства.
3.  **Использование `preStop` hooks:** выполнять команду принудительного сброса контрольной точки (`CHECKPOINT` в PostgreSQL) перед отправкой `SIGTERM`.
4.  **Параметр `maxUnavailable: 1`:** никогда не допускать одновременного падения нескольких реплик в кворумных системах.

## Дополнительная информация

### См. также

*   **[StatefulSet: Обзор](./statefulset_overview.md)** — архитектурные основы, триада StatefulSet и базовая спецификация.
*   **[StatefulSet: Ключевые концепции](./statefulset_core_concepts.md)** — детальный разбор жизненного цикла, семантики At-Most-One и Split-Brain.
*   **[StatefulSet: Лучшие практики](./statefulset_best_practices.md)** — рекомендации по настройке высокой доступности, расчету PDB и анти-аффинити.
*   **[StatefulSet: Local PV vs hostPath vs CSI](./statefulset_local_pv_vs_csi.md)** — сравнение производительности и надежности локальных и сетевых СХД для баз данных.
*   **[StatefulSet: Мониторинг БД через Exporter Sidecar](./statefulset_exporter_sidecar.md)** — организация сбора метрик Prometheus через sidecar-контейнеры.
*   **[Сравнение Deployment, StatefulSet и DaemonSet](./statefulset_vs_deployment.md)** — алгоритм выбора контроллера под конкретную нагрузку.
*   **[StorageClass в Kubernetes](../../Storage/storageclass.md)** — параметры динамического провижининга, WaitForFirstConsumer и VolumeAttributesClass.
*   **[PersistentVolume и PersistentVolumeClaim](../../Storage/pv_and_pvc.md)** — управление жизненным циклом дисков в кластере.
*   **[Headless Service](../../Networking/Service/service_type_headless.md)** — внутренняя механика CoreDNS и безадресных сервисов.
*   **[PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md)** — защита критических сервисов от деградации при плановых работах.
*   **[Недоступность узла: поды в Terminating](../../Troubleshooting/Common_Errors/PodTerminating/node_unavailable_issues.md)** — диагностика сетевых сбоев и механизм out-of-service taint.