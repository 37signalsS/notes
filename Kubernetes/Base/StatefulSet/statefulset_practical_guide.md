# StatefulSet: Практическое руководство

## Определения

**StatefulSet** — контроллер Kubernetes для управления stateful-приложениями, требующими стабильных сетевых идентификаторов и персистентного хранилища.

> **SSoT:** Полное описание концепций см. в **[Ключевые концепции StatefulSet](./statefulset_core_concepts.md)**.

## Основные концепции

### Архитектурные компоненты

Для работы StatefulSet требуется комбинация компонентов:

| Компонент | Назначение |
|-----------|------------|
| **StatefulSet** | Главный оркестратор: предоставляет подам стабильные имена и привязывает к дискам |
| **Headless Service** | Сервис с `clusterIP: None` для стабильных DNS-имен подов |
| **PersistentVolumeClaim (PVC)** | Запрос пода на выделение диска; создается автоматически через `volumeClaimTemplates` |
| **PersistentVolume (PV)** | Физическое хранилище (NFS, Ceph, диск облачного провайдера) |

Подробнее: [Headless Service](../../Networking/Service/service_type_headless.md), [PV и PVC](../../Storage/pv_and_pvc.md).

### Именование и DNS

- **Формат имени пода:** `<имя-StatefulSet>-<порядковый-номер>` (например, `kafka-0`, `kafka-1`)
- **DNS-запись:** `pod-ordinal.service.namespace.svc.cluster.local`
- **Метка для таргетирования:** `statefulset.kubernetes.io/pod-name: <pod-name>`

### Хранилище

- **Имя PVC:** `<имя-claim>-<имя-pod>` (например, `data-kafka-0`)
- **Сохранение:** PVC сохраняется после удаления пода
- **Важно:** При удалении StatefulSet PVC **не удаляются автоматически**

## Практические сценарии

### Сценарий 1: Stateful-приложения (Kafka, базы данных)

**Проблема:** При развертывании Kafka через `Deployment` под теряет связь со своим диском при рестарте, что приводит к **потере данных**.

**Решение:** `StatefulSet` гарантирует:

1. Стабильное имя: `kafka-0`, `kafka-1`
2. Стабильный PVC: `data-kafka-0` для `kafka-0`, `data-kafka-1` для `kafka-1`
3. Подключение к тому же PVC при пересоздании даже на другой ноде

### Сценарий 2: Развертывание Nginx с StatefulSet

Развертывание stateful-приложения на базе Nginx, где каждый экземпляр имеет собственный `index.html`.

#### Шаг 1: Создание Headless Service

```yaml
# service-headless.yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app-headless
spec:
  clusterIP: None # Ключевой параметр "безголового" сервиса
  selector:
    app: my-stateful-app
  ports:
  - port: 80
    name: web
```

Применение:

```bash
kubectl apply -f service-headless.yaml
```

#### Шаг 2: Создание StatefulSet

```yaml
# statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: my-app
spec:
  serviceName: "my-app-headless" # Должен соответствовать имени Headless Service
  replicas: 2
  selector:
    matchLabels:
      app: my-stateful-app
  template:
    metadata:
      labels:
        app: my-stateful-app
    spec:
      containers:
      - name: nginx
        image: nginx:1.25.5
        ports:
        - containerPort: 80
          name: web
        volumeMounts:
        - name: data-volume
          mountPath: /usr/share/nginx/html
        env:
        - name: POD_IP
          valueFrom:
            fieldRef:
              fieldPath: status.podIP
  volumeClaimTemplates:
  - metadata:
      name: data-volume
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 1Gi
```

Применение:

```bash
kubectl apply -f statefulset.yaml
```

#### Шаг 3: Проверка развертывания

**Проверка подов и PVC:**

```bash
kubectl get pods,pvc -l app=my-stateful-app
```

Ожидаемый вывод:

- Поды: `my-app-0`, `my-app-1` (создаются последовательно)
- PVC: `data-volume-my-app-0`, `data-volume-my-app-1`

**Запись уникальных данных в каждый под:**

```bash
kubectl exec my-app-0 -- /bin/sh -c 'echo "Hello from Pod 0" > /usr/share/nginx/html/index.html'
kubectl exec my-app-1 -- /bin/sh -c 'echo "Hello from Pod 1" > /usr/share/nginx/html/index.html'
```

**Проверка восстановления состояния:**

```bash
kubectl delete pod my-app-1
kubectl get pods # Дождаться восстановления my-app-1
kubectl exec my-app-1 -- cat /usr/share/nginx/html/index.html
# Вывод: Hello from Pod 1 (данные сохранены)
```

**Проверка DNS:**

```bash
kubectl run -it --rm --image=busybox dns-test -- /bin/sh

# Внутри dns-test пода:
nslookup my-app-headless
# Вернет IP обоих подов

nslookup my-app-0.my-app-headless
# Вернет IP конкретного пода
```

### Сценарий 3: Публикация конкретного пода через Ingress

**Проблема:** Стабильное DNS-имя пода доступно только внутри кластера. `Ingress` требует имя сервиса, а не FQDN пода.

**Решение:** Создать `Service` типа `ClusterIP`, нацеленный на конкретный под через метку `statefulset.kubernetes.io/pod-name`.

#### Шаг 1: Сервис для конкретного пода

```yaml
# service-for-pod-0.yaml
apiVersion: v1
kind: Service
metadata:
  name: my-app-0-service
spec:
  selector:
    statefulset.kubernetes.io/pod-name: my-app-0 # Метка уникальна для пода
  ports:
  - protocol: TCP
    port: 80
    targetPort: 80
```

Применение:

```bash
kubectl apply -f service-for-pod-0.yaml
```

#### Шаг 2: Ingress для сервиса

```yaml
# ingress-for-pod-0.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-app-0-ingress
spec:
  rules:
  - host: "app-0.example.com"
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-app-0-service
            port:
              number: 80
```

Применение:

```bash
kubectl apply -f ingress-for-pod-0.yaml
```

Результат: Трафик на `app-0.example.com` направляется только на `my-app-0`.

### Сценарий 4: Масштабирование с проверкой порядка

**Увеличение масштаба:**

```bash
kubectl scale statefulset my-app --replicas=5
kubectl get pods -w
# Поды создаются последовательно: my-app-2, my-app-3, my-app-4
```

**Уменьшение масштаба:**

```bash
kubectl scale statefulset my-app --replicas=2
kubectl get pods -w
# Поды удаляются в обратном порядке: my-app-4, my-app-3, my-app-2
```

### Сценарий 5: Диагностика проблем

**Проверка событий StatefulSet:**

```bash
kubectl describe statefulset my-app
```

**Проверка PVC:**

```bash
kubectl get pvc -l app=my-stateful-app
```

**Проверка меток подов:**

```bash
kubectl get pods --show-labels -l app=my-stateful-app
```

**Проверка порядка создания через события:**

```bash
kubectl get events --field-selector involvedObject.kind=StatefulSet
```

## Дополнительная информация

### Связанные документы

- **[Ключевые концепции](./statefulset_core_concepts.md)** (SSoT) — детальное описание принципов работы
- **[StatefulSet vs Deployment](./statefulset_vs_deployment.md)** — сравнение контроллеров
- **[Лучшие практики](./statefulset_best_practices.md)** — рекомендации по эксплуатации
- **[Headless Service](../../Networking/Service/service_type_headless.md)** — DNS для StatefulSet
- **[PV и PVC](../../Storage/pv_and_pvc.md)** — управление хранилищем

### Ограничения

- Не поддерживает автоматическое восстановление при сбое ноды (требуется ручное вмешательство или оператор)
- `ReadWriteOnce` тома ограничивают размещение пода одной зоной
- Удаление StatefulSet не удаляет PVC автоматически
- Масштабирование медленнее Deployment из-за упорядоченного создания

### Дополнительные ресурсы

- [Официальная документация Kubernetes: StatefulSet](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
- [Официальная документация: Headless Service](https://kubernetes.io/docs/concepts/services-networking/service/#headless-services)
