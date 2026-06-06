# Пространства имен (Namespace)

## Определения

**Namespace (Пространство имен)** — это объект **API (Application Programming Interface)** в Kubernetes, предназначенный для логического разделения одного физического кластера на несколько виртуальных кластеров. Он обеспечивает изолированную рабочую область для группы ресурсов, что позволяет разным командам или проектам работать в одном кластере, не мешая друг другу.

Имена ресурсов (например, подов или сервисов) должны быть уникальными только в пределах одного `Namespace`.

## Основные концепции

### Назначение

1.  **Организация ресурсов:** группировка объектов по проектам, командам или средам исполнения: **dev (development)**, **staging**, **prod (production)**.
2.  **Предотвращение конфликтов имен:** позволяет запускать несколько экземпляров одного приложения (например, с именем `web-app`) в разных пространствах имен без конфликтов.
3.  **Управление доступом (RBAC):** `Namespace` является основной единицей для применения политик **RBAC (Role-Based Access Control)**. Можно гибко ограничивать права пользователей (например, полный доступ в `dev` и только чтение в `prod`).
4.  **Квотирование ресурсов (Resource Quotas):** механизм ограничения потребления вычислительных ресурсов — **CPU (Central Processing Unit)** и оперативной памяти, а также количества объектов (подов, сервисов) для конкретной команды.
5.  **Изоляция сетевых политик (Network Policies):** позволяет контролировать сетевое взаимодействие между подами внутри одного `Namespace` и между разными пространствами имен.

### Типы ресурсов

В Kubernetes ресурсы делятся на те, что привязаны к пространству имен, и общекластерные.

*   **Namespaced-ресурсы (внутри Namespace):**
    *   Рабочие нагрузки: [Pod](./Pod/pod_overview.md), [Deployment](./Deployment/index.md), [StatefulSet](./StatefulSet/statefulset_overview.md), [DaemonSet](./daemonset.md), [Job](./job.md), [CronJob](./job.md).
    *   Конфигурация и сервисы: [Service](../Networking/Service/service_overview.md), [Ingress](../Networking/Ingress/overview.md), [ConfigMap](./configmap.md), [Secret](./secrets/secrets_basics.md), `PersistentVolumeClaim`.
    *   Политики: `NetworkPolicy`, `ResourceQuota`, `LimitRange`.

## Практические сценарии

### Создание и просмотр

```bash
# Создание через CLI (Command Line Interface)
kubectl create namespace my-project

# Создание через манифест (рекомендуется для GitOps)
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: my-project
  labels:
    environment: staging
    team: backend
EOF

# Список всех пространств имен
kubectl get namespaces
```

### Управление ресурсами

```bash
# Получить поды из конкретного namespace
kubectl get pods -n my-project

# Получить поды из всех пространств имен (All namespaces)
kubectl get pods -A

# Удаление namespace (вместе со всеми ресурсами внутри!)
kubectl delete namespace my-project
```

### Проверка области действия ресурса

Команда позволяет узнать, относится ли тип ресурса к `Namespace` или является общекластерным:

```bash
kubectl api-resources --namespaced=true  # Ресурсы внутри Namespace
kubectl api-resources --namespaced=false # Cluster-wide ресурсы
```

### Настройка контекста по умолчанию

Чтобы не указывать флаг `-n` при каждой команде, можно изменить текущее пространство имен в контексте **kubeconfig**:

```bash
# Установить пространство имен по умолчанию
kubectl config set-context --current --namespace=my-project

# Проверить текущую настройку
kubectl config view --minify | grep namespace
```

## Дополнительная информация

### Общекластерные ресурсы (Cluster-wide)

Ресурсы, которые существуют на уровне всего кластера и не зависят от `Namespace`:

*   **Инфраструктура:** `Node` (узлы), `PersistentVolume` (физические тома).
*   **Безопасность:** `ClusterRole`, `ClusterRoleBinding`.
*   **Системные:** `Namespace`, `StorageClass`.

### Ресурсные квоты и лимиты

*   **ResourceQuota:** объект для ограничения суммарного потребления ресурсов в рамках `Namespace` (например, не более 10 ядер CPU на всё пространство имен).
*   **LimitRange:** устанавливает ограничения по умолчанию (requests/limits) для каждого отдельного контейнера, если они не указаны разработчиком.

### Стандартные пространства имен

При установке кластера (например, через **Kubespray**) создаются системные `Namespace`:

*   **`default`**: используется по умолчанию, если иное не указано. Рекомендуется избегать его использования для рабочих приложений.
*   **`kube-system`**: для служебных объектов Kubernetes и компонентов **Control Plane** (API-сервер, планировщик, сетевые плагины **CNI**).
*   **`kube-public`**: содержит общедоступную информацию о кластере, доступную даже неаутентифицированным пользователям.
*   **`kube-node-lease`**: используется для хранения объектов аренды (**Lease**) узлов, которые служат сигналами работоспособности (**heartbeats**).

### Ограничения изоляции

`Namespace` обеспечивает логическую, но не физическую изоляцию:
*   Поды из разных пространств имен могут работать на одном и том же узле.
*   По умолчанию сетевой трафик между `Namespace` разрешен. Для блокировки необходимо настраивать [NetworkPolicy](../Networking/Network/network_policy.md).

**Внимание:** удаление `Namespace` приводит к каскадному удалению всех ресурсов, находящихся внутри него. Операция необратима.

### См. также
*   [Управление доступом RBAC](../Troubleshooting/Common_Errors/ApiAccessForbidden/rbac_objects.md)
*   [Сетевые политики](../Networking/Network/network_policy.md)
*   [Квоты и лимиты ресурсов](../Scheduling/qos_limit_and_requests.md)
