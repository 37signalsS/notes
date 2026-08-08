# StatefulSet: Практическое руководство

## Определения

**StatefulSet: Практическое руководство** — прикладной справочник по развертыванию, настройке и эксплуатации контроллера StatefulSet в кластере Kubernetes. Руководство содержит пошаговые сценарии использования механизмов стабильной идентификации, управления состоянием и решения эксплуатационных задач.

Теоретическую базу и описание механизмов работы см. в разделах **[StatefulSet: Обзор](./statefulset_overview.md)** и **[Ключевые концепции](./statefulset_core_concepts.md)**.

## Основные концепции

Для успешного выполнения практических сценариев необходимо понимание роли следующих компонентов:

*   **Headless Service:** Сервис без ClusterIP, отвечающий за создание индивидуальных DNS-записей для каждого пода через механизм `endpoints`.
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

```bash
# 1. Запись данных в первый под
kubectl exec web-app-0 -- sh -c 'echo "Pod 0 Data" > /usr/share/nginx/html/index.html'

# 2. Удаление пода
kubectl delete pod web-app-0
# → pod "web-app-0" deleted

# 3. Наблюдение за восстановлением
kubectl get pods -w -l app=nginx-stateful
# → web-app-0   0/1     Pending             0          0s
# → web-app-0   0/1     ContainerCreating   0          1s
# → web-app-0   1/1     Running             0          5s

# 4. Проверка данных
kubectl exec web-app-0 -- cat /usr/share/nginx/html/index.html
# → Pod 0 Data
```

---

### Сценарий 2: Развертывание базы данных MySQL (Best Practices)

Использование секретов для паролей и выделенных лимитов ресурсов.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mysql-pass
stringData:
  password: "super-strong-password"
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: mysql
spec:
  selector:
    matchLabels:
      app: mysql
  serviceName: "mysql"
  replicas: 3
  template:
    metadata:
      labels:
        app: mysql
    spec:
      containers:
      - name: mysql
        image: mysql:8.0
        env:
        - name: MYSQL_ROOT_PASSWORD
          valueFrom:
            secretKeyRef:
              name: mysql-pass
              key: password
        ports:
        - containerPort: 3306
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "1"
            memory: "2Gi"
        volumeMounts:
        - name: data
          mountPath: /var/lib/mysql
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

---

### Сценарий 3: Миграция между кластерами через Ordinals

Задача: Запустить поды в новом кластере с индексов 3-5, чтобы избежать конфликтов имен при параллельной работе двух площадок.

```yaml
spec:
  replicas: 3
  ordinals:
    start: 3  # Создаст поды: web-app-3, web-app-4, web-app-5
```

```bash
kubectl apply -f statefulset.yaml
# → statefulset.apps/web-app created

kubectl get pods
# → web-app-3   1/1     Running   0          10s
# → web-app-4   1/1     Running   0          5s
# → web-app-5   1/1     Running   0          1s
```

---

### Сценарий 4: Нативные Sidecar-контейнеры (v1.29+)

Для вспомогательных процессов (например, аутентифицирующего прокси или сборщика логов).

```yaml
spec:
  template:
    spec:
      initContainers:
      - name: auth-proxy
        image: oauth2-proxy:latest
        restartPolicy: Always  # GA в v1.29: контейнер работает как Sidecar
```

---

### Сценарий 5: Изменение размера диска (Manual Resizing)

Поскольку `volumeClaimTemplates` иммутабельны, увеличение размера требует каскадного обновления.

1.  **Обновите PVC напрямую** (если StorageClass поддерживает `allowVolumeExpansion`):
    ```bash
    kubectl patch pvc data-web-app-0 -p '{"spec":{"resources":{"requests":{"storage":"2Gi"}}}}'
    # → persistentvolumeclaim/data-web-app-0 patched
    ```
2.  **Удалите StatefulSet без удаления подов** (Cascade Orphan):
    ```bash
    kubectl delete statefulset web-app --cascade=orphan
    # → statefulset.apps "web-app" deleted (поды остались работать)
    ```
3.  **Обновите YAML** (замените `1Gi` на `2Gi` в `volumeClaimTemplates`) и примените:
    ```bash
    kubectl apply -f statefulset.yaml
    # → statefulset.apps/web-app created
    ```
    Контроллер «усыновит» существующие поды и PVC с новыми параметрами.

## Диагностика и устранение неполадок

### Проверка DNS-идентификации

Самый быстрый способ проверить работу Headless Service:
```bash
kubectl run dns-debug --image=busybox:1.28 -it --rm --restart=Never -- nslookup web-app-0.nginx-headless
# → Server:    10.96.0.10
# → Address:   10.96.0.10#53
# → Name:      web-app-0.nginx-headless.default.svc.cluster.local
# → Address:   10.244.1.5
```

### Анализ застревания в Pending

Если под не переходит в `Running`:
1.  `kubectl get pvc`: Проверьте статус `Bound`.
2.  `kubectl describe pvc <name>`: Ищите ошибки `VolumeBinding` (например, нехватка места в AZ).
3.  `kubectl describe pod <name>`: Проверьте события планировщика и анти-аффинити правил.

### Безопасное принудительное удаление

Если узел упал и под «завис» в `Terminating`:
1.  **Никогда** не используйте `--force` просто так.
2.  Пометьте узел как неисправный (v1.28+):
    ```bash
    kubectl patch node <node-name> -p '{"metadata":{"labels":{"node.kubernetes.io/out-of-service":"nodeshutdown"}}}'
    ```
3.  Kubernetes безопасно отмонтирует тома и пересоздаст под на другом узле.

## Дополнительная информация

### Рекомендации

*   Всегда используйте **Startup Probes** для БД с длительным восстановлением после сбоя.
*   Никогда не храните конфиги внутри образа; используйте **ConfigMap** и монтируйте их как файлы.

### См. также

*   **[Обзор StatefulSet](./statefulset_overview.md)** — основы и архитектура.
*   **[Ключевые концепции](./statefulset_core_concepts.md)** — детальное описание механизмов.
*   **[Лучшие практики](./statefulset_best_practices.md)** — рекомендации по настройке HA и безопасности.
