# Миграция Kafka с Deployment на StatefulSet без потери данных

## Часть 1: Почему Kafka в виде `Deployment` — это проблема

`Deployment` предназначен для **stateless** (не хранящих состояние) приложений. Kafka является **stateful**. Использование `Deployment` приводит к критическим проблемам:

1.  **Нестабильная сетевая идентичность:** При любом перезапуске или обновлении пода `Deployment` создает новый под с новым именем и, следовательно, новым hostname. Брокеры Kafka и клиенты полагаются на стабильные, предсказуемые имена (например, `kafka-0`, `kafka-1`). Постоянная смена имен вносит хаос в кластер: Zookeeper/KRaft теряет "старые" брокеры и видит "новые", что провоцирует постоянные ребалансировки и потерю синхронизации.

2.  **Некорректная работа с хранилищем:** `Deployment` не предназначен для управления уникальными дисками для каждого пода.
    *   **Один PVC на всех:** Если в `Deployment` указан один `PersistentVolumeClaim`, все поды будут пытаться подключиться к одному и тому же диску, что немедленно приведет к порче данных, так как каждый брокер Kafka требует эксклюзивного доступа к своему хранилищу.
    *   **Потеря данных:** Даже если вы использовали один под с одним PVC, при любом сбое, требующем пересоздания пода на другой ноде, связь с этим хранилищем может быть не гарантирована так, как это делает `StatefulSet`.

3.  **Неупорядоченные обновления:** `Deployment` может останавливать и обновлять поды в произвольном порядке. Для распределенных систем, как Kafka, критически важны упорядоченные, последовательные обновления (сначала `kafka-0`, потом `kafka-1` и т.д.), которые `StatefulSet` обеспечивает по умолчанию.

---

## Часть 2: План миграции на `StatefulSet`

**КЛЮЧЕВОЕ ПРЕДУПРЕЖДЕНИЕ:** Этот процесс сопряжен с риском и требует полной остановки записи в Kafka. Обязательно **сделайте бэкап** ваших данных перед началом! Используйте `Velero` или снепшоты на уровне хранилища. Сначала протестируйте процедуру в staging-окружении.

Основная стратегия: создать новый `StatefulSet` с новыми дисками (PVC), а затем скопировать данные со старых дисков на новые с помощью временных подов.

### Шаг 1: Подготовка

1.  **Остановите продюсеров:** Запретите любую запись в топики Kafka.
2.  **Определите ресурсы:** Получите имена вашего `Deployment`, `Service` и, самое главное, `PersistentVolumeClaim` (PVC), которые он использует.
    ```bash
    # Имя деплоймента
    kubectl get deployment | grep kafka
    
    # Имена PVC, которые используют поды деплоймента
    kubectl get pvc -l app=<метка-вашего-деплоймента>
    # Пример: kubectl get pvc -l app=kafka-deployment
    ```
    Допустим, вы нашли 3 PVC: `kafka-pvc-0`, `kafka-pvc-1`, `kafka-pvc-2`.

3.  **Создайте манифест для `StatefulSet` (`kafka-sts.yaml`):**
    *   Он должен иметь `replicas` такое же, как у `Deployment`.
    *   Он должен использовать `volumeClaimTemplates` для автоматического создания PVC с предсказуемыми именами (например, `datadir-kafka-0`, `datadir-kafka-1`, ...).
    *   Остальные параметры (образы, порты, конфигурация) должны соответствовать вашему `Deployment`.

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

1.  **Остановите старый `Deployment`:** Это освободит PVC и остановит поды Kafka.
    ```bash
    kubectl scale deployment <имя-вашего-деплоймента> --replicas=0
    ```

2.  **Разверните новый `StatefulSet`:** Это создаст новые поды Kafka и новые, **пустые** PVC (`datadir-kafka-0`, `datadir-kafka-1`, `datadir-kafka-2`).
    ```bash
    kubectl apply -f kafka-sts.yaml
    ```

3.  **Остановите `StatefulSet`:** Нам нужны только его PVC, а не запущенные поды.
    ```bash
    kubectl scale statefulset kafka --replicas=0
    ```

4.  **Миграция данных (по одному для каждого брокера):**
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

    *   Создайте и запустите этот под: `kubectl apply -f copy-pod-0.yaml`
    *   Следите за логами: `kubectl logs -f data-copier-0`
    *   **Дождитесь окончания копирования.**
    *   Удалите под: `kubectl delete pod data-copier-0`
    *   **Повторите для `kafka-pvc-1` -> `datadir-kafka-1` и т.д.**

### Шаг 3: Запуск и проверка

1.  **Запустите новый `StatefulSet`:**
    ```bash
    kubectl scale statefulset kafka --replicas=3
    ```
    `StatefulSet` запустит поды по порядку (`kafka-0`, `kafka-1`, `kafka-2`), и они подключат уже наполненные данными диски.

2.  **Проверьте логи** каждого пода Kafka. Убедитесь, что они стартуют нормально, видят свои данные и собираются в кластер.

3.  **Проведите smoke-тестирование:** Запустите тестовых консьюмеров, чтобы убедиться, что они могут прочитать старые данные из топиков.

### Шаг 4: Очистка

После того как вы на 100% уверены, что новый `StatefulSet` работает корректно и все данные на месте:

1.  **Удалите старый `Deployment`:**
    ```bash
    kubectl delete deployment <имя-вашего-деплоймента>
    ```
2.  **Удалите старые PVC:**
    ```bash
    kubectl delete pvc kafka-pvc-0 kafka-pvc-1 kafka-pvc-2
    ```
3.  Обновите DNS-записи или конфигурацию `Service`, если это необходимо, чтобы они указывали на поды нового `StatefulSet`.
4.  Разрешите продюсерам снова отправлять сообщения.
