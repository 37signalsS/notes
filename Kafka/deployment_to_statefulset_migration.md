# Миграция Kafka с Deployment на StatefulSet без потери данных

## Определения

* **Kafka**: Распределенная потоковая платформа, часто используемая для построения конвейеров данных реального времени. Является **stateful** приложением, то есть хранит свое состояние (данные) на диске, требуя стабильной идентификации и персистентного хранения.
* **Deployment (Kubernetes)**: Объект Kubernetes, предназначенный для управления **stateless** приложениями. Обеспечивает декларативное обновление подов, но не гарантирует порядок или стабильную сетевую идентичность/хранилище.
* **StatefulSet (Kubernetes)**: Объект Kubernetes, предназначенный для управления **stateful** приложениями. Гарантирует стабильную сетевую идентификацию, упорядоченные развертывания/масштабирования/удаления и ассоциирует персистентное хранилище с каждым подом.
* **PersistentVolumeClaim (PVC)**: Запрос пользователя на выделение дискового пространства в кластере Kubernetes.
* **Zookeeper/KRaft**: Системы координации, используемые Kafka для управления метаданными кластера и поддержания консенсуса между брокерами.

## Основные концепции

Использование `Deployment` для управления stateful-приложениями, таким как Kafka, является анти-паттерном в Kubernetes. `Deployment` не обеспечивает стабильную сетевую идентичность и постоянное хранилище, что критически важно для Kafka и приводит к потере данных и нестабильной работе кластера.

**`StatefulSet`** — это единственно правильный объект Kubernetes для запуска подобных систем.

> Подробное объяснение проблем `Deployment` и преимуществ `StatefulSet` для приложений с состоянием находится в основном документе: **[StatefulSet в Kubernetes](../Kubernetes/Base/statefulset.md)**.

## Практические сценарии

### План миграции на `StatefulSet`

**КЛЮЧЕВОЕ ПРЕДУПРЕЖДЕНИЕ:** Этот процесс сопряжен с риском и требует полной остановки записи в Kafka. Обязательно **сделайте бэкап** ваших данных перед началом! Используйте `Velero` или снепшоты на уровне хранилища. Сначала протестируйте процедуру в staging-окружении.

Основная стратегия: создать новый `StatefulSet` с новыми дисками (PVC), а затем скопировать данные со старых дисков на новые с помощью временных подов.

### Шаг 1: Подготовка

1. **Остановите продюсеров**: Запретите любую запись в топики Kafka.
2. **Определите ресурсы**: Получите имена вашего `Deployment`, `Service` и, самое главное, `PersistentVolumeClaim` (PVC), которые он использует.

    ```bash
    # Имя деплоймента
    kubectl get deployment | grep kafka
    
    # Имена PVC, которые используют поды деплоймента
    kubectl get pvc -l app=<метка-вашего-деплоймента>
    # Пример: kubectl get pvc -l app=kafka-deployment
    ```

    Допустим, вы нашли 3 PVC: `kafka-pvc-0`, `kafka-pvc-1`, `kafka-pvc-2`.

3. **Создайте манифест для `StatefulSet` (`kafka-sts.yaml`)**:
    * Он должен иметь `replicas` такое же, как у `Deployment`.
    * Он должен использовать `volumeClaimTemplates` для автоматического создания PVC с предсказуемыми именами (например, `datadir-kafka-0`, `datadir-kafka-1`, ...).
    * Остальные параметры (образы, порты, конфигурация) должны соответствовать вашему `Deployment`.

    ```yaml
    # Пример kafka-sts.yaml
    apiVersion: apps/v1
    kind: StatefulSet
    metadata:
      name: kafka
    spec:
      serviceName: "kafka-headless" # Важно для DNS
      replicas: 3
      selector:
        matchLabels:
          app: kafka # Должно совпадать с template.metadata.labels
      template:
        metadata:
          labels:
            app: kafka
        spec:
          containers:
          - name: kafka
            image: your-kafka-image:tag
            ports:
            - containerPort: 9092
            volumeMounts:
            - name: datadir
              mountPath: /var/lib/kafka/data
      volumeClaimTemplates:
      - metadata:
          name: datadir
        spec:
          accessModes: [ "ReadWriteOnce" ]
          storageClassName: your-storage-class
          resources:
            requests:
              storage: 10Gi # Размер должен быть не меньше старого
    ```

### Шаг 2: Выполнение миграции

1. **Остановите старый `Deployment`**: Это освободит PVC и остановит поды Kafka.

    ```bash
    kubectl scale deployment <имя-вашего-деплоймента> --replicas=0
    ```

2. **Разверните новый `StatefulSet`**: Это создаст новые поды Kafka и новые, **пустые** PVC (`datadir-kafka-0`, `datadir-kafka-1`, `datadir-kafka-2`).

    ```bash
    kubectl apply -f kafka-sts.yaml
    ```

3. **Остановите `StatefulSet`**: Нам нужны только его PVC, а не запущенные поды.

    ```bash
    kubectl scale statefulset kafka --replicas=0
    ```

4. **Миграция данных (по одному для каждого брокера)**:
    Создайте временный под для копирования данных со старого PVC на новый. Повторите этот шаг для каждой пары дисков (старый-новый).

    ```yaml
    # Пример манифеста для копирования данных для брокера-0
    # Файл: copy-pod-0.yaml
    apiVersion: v1
    kind: Pod
    metadata:
      name: data-copier-0
    spec:
      containers:
      - name: copier
        image: alpine # Или любой другой образ с rsync
        command: ["/bin/sh", "-c"]
        args:
          - >
            apk add rsync &&
            echo 'Starting copy...' &&
            rsync -av /from/ /to/ &&
            echo 'Copy finished!' &&
            sleep 3600
        volumeMounts:
        - name: old-data
          mountPath: /from
        - name: new-data
          mountPath: /to
      volumes:
      - name: old-data
        persistentVolumeClaim:
          claimName: kafka-pvc-0 # <-- Имя старого PVC для брокера 0
      - name: new-data
        persistentVolumeClaim:
          claimName: datadir-kafka-0 # <-- Имя нового PVC для брокера 0
    ```

    * Создайте и запустите этот под: `kubectl apply -f copy-pod-0.yaml`
    * Следите за логами: `kubectl logs -f data-copier-0`
    * **Дождитесь окончания копирования.**
    * Удалите под: `kubectl delete pod data-copier-0`
    * **Повторите для `kafka-pvc-1` -> `datadir-kafka-1` и т.д.**

### Шаг 3: Запуск и проверка

1. **Запустите новый `StatefulSet`**:

    ```bash
    kubectl scale statefulset kafka --replicas=3
    ```

    `StatefulSet` запустит поды по порядку (`kafka-0`, `kafka-1`, `kafka-2`), и они подключат уже наполненные данными диски.

2. **Проверьте логи** каждого пода Kafka. Убедитесь, что они стартуют нормально, видят свои данные и собираются в кластер.

3. **Проведите smoke-тестирование**: Запустите тестовых консьюмеров, чтобы убедиться, что они могут прочитать старые данные из топиков.

## Дополнительная информация

### Очистка

После того как вы на 100% уверены, что новый `StatefulSet` работает корректно и все данные на месте:

1. **Удалите старый `Deployment`**:

    ```bash
    kubectl delete deployment <имя-вашего-деплоймента>
    ```

2. **Удалите старые PVC**:

    ```bash
    kubectl delete pvc kafka-pvc-0 kafka-pvc-1 kafka-pvc-2
    ```

3. Обновите DNS-записи или конфигурацию `Service`, если это необходимо, чтобы они указывали на поды нового `StatefulSet`.
4. Разрешите продюсерам снова отправлять сообщения.
