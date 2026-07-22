# StatefulSet: Практическое руководство

## Определения

**StatefulSet: Практическое руководство** — прикладной справочник по развертыванию, настройке и эксплуатации контроллера StatefulSet в кластере Kubernetes. Руководство содержит пошаговые сценарии использования механизмов стабильной идентификации и управления состоянием.

Теоретическую базу и описание механизмов работы см. в **[StatefulSet: Обзор](./statefulset_overview.md)** и **[Ключевые концепции](./statefulset_core_concepts.md)**.

## Основные концепции

Для успешного выполнения практических сценариев необходимо понимание роли следующих компонентов:

*   **Headless Service:** Сервис без ClusterIP, отвечающий за создание индивидуальных DNS-записей для каждого пода.
*   **PersistentVolumeClaim (PVC):** Декларативный запрос на выделение диска. В StatefulSet PVC генерируются автоматически для каждого индекса пода через шаблон `volumeClaimTemplates`.
*   **Идентификация:** Каждый под получает стабильное имя формата `название-sts-индекс` и FQDN (Fully Qualified Domain Name) формата `имя-пода.имя-сервиса.namespace.svc.cluster.local`.

Подробнее о сетевом взаимодействии: **[Headless Service](../../Networking/Service/service_type_headless.md)**.

## Практические сценарии

### Сценарий 1: Развертывание кластерного веб-сервера (Nginx)

Цель: запустить группу подов, где каждый экземпляр имеет собственную страницу `index.html` и настроенную политику удержания дисков.

#### Шаг 1: Создание сетевой инфраструктуры (Headless Service)

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-headless
spec:
  clusterIP: None
  selector:
    app: nginx-stateful
  ports:
  - port: 80
    name: web
```

#### Шаг 2: Создание контроллера StatefulSet (v1.32+)

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: web-app
spec:
  serviceName: "nginx-headless"
  replicas: 3
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain  # Сохранить данные при удалении StatefulSet
    whenScaled: Delete   # Удалить диск при уменьшении реплик (Scale down)
  selector:
    matchLabels:
      app: nginx-stateful
  template:
    metadata:
      labels:
        app: nginx-stateful
    spec:
      containers:
      - name: nginx
        image: nginx:1.27
        volumeMounts:
        - name: data
          mountPath: /usr/share/nginx/html
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
```

#### Шаг 3: Проверка персистентности данных

1.  Запишите данные в первый под:
    `kubectl exec web-app-0 -- sh -c 'echo "Pod 0 Data" > /usr/share/nginx/html/index.html'`
2.  Удалите под:
    `kubectl delete pod web-app-0`
3.  Проверьте данные после автоматического восстановления пода:
    `kubectl exec web-app-0 -- cat /usr/share/nginx/html/index.html`
    *Результат: Сообщение "Pod 0 Data" сохранено на диске.*

---

### Сценарий 2: Миграция между кластерами с использованием произвольных индексов (Ordinals)

Задача: Перенести нагрузку в новый кластер, начав нумерацию подов с индекса 3, чтобы избежать конфликтов с работающими подами 0-2 в старом кластере.

1.  **Создайте манифест** с параметром `ordinals`:
    ```yaml
    spec:
      replicas: 3
      ordinals:
        start: 3  # Поды будут называться web-app-3, web-app-4, web-app-5
    ```
2.  **Примените манифест** в новом кластере. После завершения миграции данных и переключения трафика параметр `start` можно удалить для возврата к стандартной нумерации (0, 1, 2) после планового перезапуска.

---

### Сценарий 3: Использование нативных Sidecar-контейнеров (v1.29+)

Для вспомогательных процессов (логирование, прокси), которые должны запускаться раньше основного приложения.

```yaml
spec:
  template:
    spec:
      initContainers:
      - name: log-agent
        image: fluent-bit:3.0
        restartPolicy: Always  # Делает init-контейнер нативным Sidecar
```
*Результат: `log-agent` будет запущен первым и продолжит работу на протяжении всего жизненного цикла пода.*

---

### Сценарий 4: Маршрутизация трафика на конкретный под

1.  **Создайте целевой сервис**, используя автоматическую метку индекса:
    ```yaml
    apiVersion: v1
    kind: Service
    metadata:
      name: web-app-0-direct
    spec:
      selector:
        apps.kubernetes.io/pod-index: "0" # Рекомендуемый способ в v1.31+
      ports:
      - port: 80
    ```

---

### Сценарий 5: Изменение размера диска (PVC)

**Проблема:** Поля в `volumeClaimTemplates` иммутабельны. Изменение `storage` в манифесте приведет к ошибке при `kubectl apply`.

**Решение (Manual Resizing):**
1.  **Обновите PVC:** Если StorageClass поддерживает `allowVolumeExpansion`, измените размер напрямую:
    ```bash
    kubectl patch pvc data-web-app-0 -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'
    ```
2.  **Временное удаление контроллера:** Чтобы обновить шаблон в StatefulSet без остановки работающих приложений:
    ```bash
    kubectl delete statefulset web-app --cascade=orphan
    ```
3.  **Применение нового манифеста:** Обновите значение в YAML и выполните `kubectl apply -f statefulset.yaml`. Контроллер "усыновит" (adopt) существующие поды и PVC.

## Диагностика и устранение неполадок

*   **Проверка событий:** `kubectl describe statefulset <name>`. Выявляет ошибки квот или проблемы с созданием PVC.
*   **Застревание в Pending:** `kubectl get pvc`. Если диски не создаются, проверьте `kubectl describe pvc <name>` — возможно, в зоне доступности (AZ) закончились ресурсы или неверно настроен StorageClass.
*   **Проверка DNS:**
    ```bash
    kubectl run dns-test --image=busybox:1.28 -it --rm -- restart=Never -- nslookup web-app-0.nginx-headless
    ```
*   **Принудительное удаление:** Избегайте `kubectl delete pod --force --grace-period=0`. Если под "завис" на неисправном узле, используйте механизм **Non-Graceful Node Shutdown** (метка `node.kubernetes.io/out-of-service=nodeshutdown`) для безопасного переноса пода.

## Дополнительная информация

### Рекомендации по эксплуатации

*   Никогда не удаляйте PVC вручную, если планируете восстанавливать под с теми же данными.
*   Используйте **[Лучшие практики](./statefulset_best_practices.md)** для настройки отказоустойчивости (PDB, Anti-Affinity).

### См. также

*   **[Обзор StatefulSet](./statefulset_overview.md)** — основы и архитектура.
*   **[Ключевые концепции](./statefulset_core_concepts.md)** — детальное описание механизмов.
*   **[StatefulSet vs Deployment](./statefulset_vs_deployment.md)** — выбор подходящего контроллера.
