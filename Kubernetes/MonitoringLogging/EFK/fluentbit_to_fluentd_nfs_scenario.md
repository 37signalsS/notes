# Практический сценарий: Настройка роутинга логов FluentBit -> Fluentd -> NFS

## Определения

*   **FluentBit**: Легковесный агент сбора логов, установленный на каждом узле кластера. См. [Сравнение Fluentd и Fluent Bit](./fluentbit/fluent_comparison.md).
*   **Fluentd**: Более мощный агрегатор логов, используемый в данном сценарии как центральный роутер.
*   **NFS (Network File System)**: Сетевая файловая система, используемая как внешнее хранилище для логов.
*   **PersistentVolume (PV)**: Ресурс Kubernetes, представляющий физическое хранилище (в данном случае, NFS-ресурс).
*   **PersistentVolumeClaim (PVC)**: Запрос пода на выделение хранилища. Подробнее см. [Хранение данных: PV, PVC и StorageClass](../../Storage/pv_and_pvc.md).
*   **Pod Anti-Affinity**: Правило планирования, запрещающее размещение подов на одном и том же узле. Подробнее см. [Управление размещением подов: Affinity и Anti-Affinity](../../Scheduling/affinity.md).

## Архитектура решения

Данный сценарий реализует отказоустойчивую архитектуру сбора и хранения логов, где Fluentd выступает в роли промежуточного звена (роутера) между сборщиками FluentBit и конечным файловым хранилищем на NFS.

```mermaid
graph TD
    subgraph Kubernetes Cluster
        subgraph Nodes
            N1[Node 1: FluentBit]
            N2[Node 2: FluentBit]
            NN[Node N: FluentBit]
        end

        subgraph Fluentd Aggregator (StatefulSet)
            F1[Fluentd Pod 1]
            F2[Fluentd Pod 2]
        end

        N1 -- forward --> F1
        N2 -- forward --> F2
        NN -- forward --> F1
        F1 -- Writes logs --> NFS
        F2 -- Writes logs --> NFS
    end

    subgraph External Storage
        NFS[NFS Share:/logs]
    end

    style F1 fill:#f9f,stroke:#333,stroke-width:2px
    style F2 fill:#f9f,stroke:#333,stroke-width:2px
```

## Практическая реализация

### Шаг 1: Настройка хранилища (NFS)

Прежде чем разворачивать Fluentd, необходимо предоставить ему постоянное хранилище.

1.  **Настройте NFS-сервер**: Убедитесь, что у вас есть работающий NFS-сервер и экспортированная директория (например, `/var/k8s-logs`). Убедитесь, что на всех узлах Kubernetes установлен пакет `nfs-common` (или `nfs-utils`).

2.  **Создайте PersistentVolume (PV)**:
    Это задача администратора кластера. Создается объект `PersistentVolume`, который описывает NFS-ресурс.

    ```yaml
    # 01-nfs-pv.yaml
    apiVersion: v1
    kind: PersistentVolume
    metadata:
      name: fluentd-log-storage-pv
    spec:
      capacity:
        storage: 10Gi
      accessModes:
        - ReadWriteMany # NFS поддерживает этот режим
      persistentVolumeReclaimPolicy: Retain
      nfs:
        path: /var/k8s-logs # Путь на NFS-сервере
        server: 192.168.1.100 # IP-адрес вашего NFS-сервера
    ```

3.  **Создайте PersistentVolumeClaim (PVC)**:
    Это запрос от приложения (Fluentd) на выделение хранилища.

    ```yaml
    # 02-fluentd-pvc.yaml
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
      name: fluentd-logs-pvc
      namespace: logging # Убедитесь, что namespace существует
    spec:
      accessModes:
        - ReadWriteMany
      resources:
        requests:
          storage: 10Gi
      # Имя StorageClass не указываем, чтобы PVC связался с нашим PV вручную
      storageClassName: ""
    ```

4.  **Примените манифесты и проверьте**:
    ```bash
    kubectl create ns logging
    kubectl apply -f 01-nfs-pv.yaml
    kubectl apply -f 02-fluentd-pvc.yaml
    kubectl get pvc -n logging # Статус должен быть "Bound"
    ```

### Шаг 2: Настройка и развертывание Fluentd

1.  **Создайте `ConfigMap` для `fluent.conf`**:

    ```yaml
    # 03-fluentd-config.yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: fluentd-config
      namespace: logging
    data:
      fluent.conf: |
        # Принимаем логи от FluentBit
        <source>
          @type forward
          port 24224
          bind 0.0.0.0
        </source>

        # Записываем логи приложений в один файл
        <match example-app.**>
          @type file
          path /fluentd/log/example-app.log
          append true
          <buffer>
            # ВНИМАНИЕ: memory-буфер с immediate flush подходит для отладки,
            # но в production он может привести к потере данных при перезапуске пода.
            # Для надежности используйте file-буфер.
            # См. https://docs.fluentd.org/configuration/buffer-section
            @type memory
            flush_mode immediate
          </buffer>
          <format>
            @type json
          </format>
        </match>

        # Записываем системные логи в другой файл
        <match syslog.**>
          @type file
          path /fluentd/log/syslog.log
          append true
          <buffer>
            @type memory
            flush_mode immediate
          </buffer>
          <format>
            @type json
          </format>
        </match>
    ```
    *   `@type forward`: Принимает логи по протоколу forward.
    *   `@type file`: Указывает, что вывод будет в файл.
    *   `path /fluentd/log/...`: Путь внутри контейнера, куда будет смонтирован NFS-том.
    *   `append true`: Критически важный параметр. Позволяет нескольким репликам Fluentd дописывать логи в один и тот же файл без конфликтов.
    *   `buffer`: Конфигурация буферизации. Использование `file`-буфера — одна из ключевых причин применения Fluentd в качестве агрегатора. См. [Сравнение Fluentd и Fluent Bit](./fluentbit/fluent_comparison.md#буферизация-и-надежность).

2.  **Создайте `Deployment` для Fluentd**:

    ```yaml
    # 04-fluentd-deployment.yaml
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: fluentd-router
      namespace: logging
    spec:
      replicas: 2
      selector:
        matchLabels:
          app: fluentd-router
      template:
        metadata:
          labels:
            app: fluentd-router
        spec:
          # Правило для раскидывания подов по разным нодам
          affinity:
            podAntiAffinity:
              requiredDuringSchedulingIgnoredDuringExecution:
              - labelSelector:
                  matchExpressions:
                  - key: app
                    operator: In
                    values:
                    - fluentd-router
                topologyKey: "kubernetes.io/hostname"
          containers:
          - name: fluentd
            image: fluent/fluentd:v1.17-debian
            resources:
              requests:
                cpu: 100m
                memory: 200Mi
              limits:
                memory: 400Mi # Ограничение, чтобы избежать OOMKilled
            ports:
            - containerPort: 24224
            volumeMounts:
            - name: config-volume
              mountPath: /fluentd/etc
            - name: log-storage
              mountPath: /fluentd/log
          volumes:
          - name: config-volume
            configMap:
              name: fluentd-config
          - name: log-storage
            persistentVolumeClaim:
              claimName: fluentd-logs-pvc
    ```

3.  **Создайте `Service` для Fluentd**:

    ```yaml
    # 05-fluentd-service.yaml
    apiVersion: v1
    kind: Service
    metadata:
      name: fluentd-service
      namespace: logging
    spec:
      selector:
        app: fluentd-router
      ports:
      - name: forward-port
        protocol: TCP
        port: 24224
        targetPort: 24224
    ```

4.  **Примените манифесты**:
    ```bash
    kubectl apply -f 03-fluentd-config.yaml
    kubectl apply -f 04-fluentd-deployment.yaml
    kubectl apply -f 05-fluentd-service.yaml
    ```

### Шаг 3: Перенастройка FluentBit

Теперь нужно изменить конфигурацию FluentBit, чтобы он отправлял логи не в Elasticsearch, а на наш новый сервис Fluentd.

1.  **Найдите `ConfigMap` вашего FluentBit**. Обычно он называется `fluent-bit-config` в неймспейсе, где развернут FluentBit.
2.  **Отредактируйте секцию `[OUTPUT]`**:
    Замените существующий `[OUTPUT]` (например, для Elasticsearch) на новый.

    **Было (пример):**
    ```ini
    [OUTPUT]
        Name            es
        Match           *
        Host            elasticsearch-master.logging.svc.cluster.local
        ...
    ```

    **Стало:**
    ```ini
    [OUTPUT]
        Name      forward
        Match     *
        Host      fluentd-service.logging.svc.cluster.local # FQDN нашего сервиса Fluentd
        Port      24224
        Retry_Limit False
    ```
3.  **Примените изменения** и перезапустите поды FluentBit, чтобы они подхватили новую конфигурацию (`kubectl rollout restart daemonset/fluent-bit -n <namespace>`).

### Шаг 4: Проверка

1.  Запустите приложение, которое генерирует логи.
2.  Проверьте содержимое файлов на вашем NFS-сервере в директории, которую вы экспортировали (например, `/var/k8s-logs`). Должны появиться файлы `example-app.log` и `syslog.log` с логами в формате JSON.
3.  Убедитесь, что поды Fluentd распределены по разным узлам (`kubectl get pods -n logging -o wide`).