# Namespace

## Определения

**Namespace** (пространство имен) — это механизм для разделения одного физического кластера Kubernetes на несколько **виртуальных кластеров**. Он позволяет изолировать группы ресурсов, создавая для них отдельную рабочую область. Имена ресурсов должны быть уникальны в пределах одного `Namespace`, но могут повторяться в разных.

## Основные концепции

### Назначение

1. **Организация ресурсов:** Группировка объектов по проектам, командам или средам (например, `development`, `staging`, `production`). Это предотвращает хаос в кластере.
2. **Предотвращение конфликтов имен:** `Deployment` с именем `my-app` может существовать одновременно в `staging` и `production`, не мешая друг другу.
3. **Управление доступом (RBAC):** `Namespace` является основной единицей для применения политик безопасности. Можно предоставить команде разработчиков полные права в `dev-namespace`, но только на чтение в `prod-namespace`.
4. **Квотирование ресурсов (Resource Quotas):** Можно ограничить потребление CPU, памяти и количество создаваемых объектов (подов, сервисов) для каждого `Namespace`, чтобы гарантировать справедливое распределение ресурсов.
5. **Изоляция сетевых политик (Network Policies):** Сетевые политики применяются к подам внутри `Namespace`, позволяя контролировать входящий и исходящий трафик.

Пример Namespace с метками:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    environment: production
    team: platform
```

### Типы ресурсов

Не все ресурсы в Kubernetes привязаны к `Namespace`.

* **Namespaced-ресурсы** (существуют внутри `Namespace`):
  * Рабочие нагрузки: [Pod](./Pod/pod_overview.md), [Deployment](./Deployment/index.md), [StatefulSet](./statefulset.md), [DaemonSet](./daemonset.md), [Job](./job.md), [CronJob](./job.md).
  * Конфигурация и сервисы: [Service](../Networking/Service/service_overview.md), [Ingress](../Networking/Ingress/overview.md), [ConfigMap](./configmap.md), [Secret](./secrets/secrets_basics.md), `PersistentVolumeClaim`.
  * Политики: `NetworkPolicy`, `ResourceQuota`, `LimitRange`.

* **Cluster-wide ресурсы** (существуют на уровне всего кластера):
  * Инфраструктура: `Node`, `PersistentVolume`.
  * Безопасность и доступ: `ClusterRole`, `ClusterRoleBinding`.
  * Системные: `Namespace` (сам по себе), `StorageClass`.

### ResourceQuota и LimitRange

**ResourceQuota** — объект для ограничения суммарного потребления ресурсов всеми подами в Namespace:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute-quota
  namespace: production
spec:
  hard:
    requests.cpu: "10"
    requests.memory: 20Gi
    limits.cpu: "20"
    limits.memory: 40Gi
    pods: "50"
```

**LimitRange** — устанавливает ограничения по умолчанию для отдельных контейнеров в Namespace:

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: container-limits
  namespace: production
spec:
  limits:
  - type: Container
    default:
      cpu: "500m"
      memory: "512Mi"
    defaultRequest:
      cpu: "100m"
      memory: "128Mi"
```

## Стандартные Namespaces

При создании кластера Kubernetes инициализирует несколько пространств имен:

* `default`: Пространство имен по умолчанию для объектов, у которых оно не указано в манифесте. Если при создании ресурса не указать `namespace`, он будет помещен сюда.
  * **Лучшая практика — не использовать его для реальных проектов, а создавать отдельные `Namespace` для каждой команды или приложения.**
  * **Предупреждение:** Не удаляйте это пространство имен. Оно содержит важные системные компоненты, и его удаление может нарушить работу кластера.

* `kube-system`: Пространство имён для системных служебных объектов Kubernetes. В нем находятся все компоненты **control-plane**: `etcd`, `kube-api-server`, `kube-controller-manager`, `kube-scheduler`, а также системные сервисы, такие как `CoreDNS` и `kube-proxy`. Сюда же часто устанавливаются системные приложения, расширяющие функциональность кластера (например, сетевые плагины). **Не трогать!**

* `kube-public`: Создаваемое автоматически пространство имён, которое доступно для чтения всем пользователям, даже неаутентифицированным. Это пространство используется для публикации общедоступной информации о кластере. Например, `kubeadm` использует его для обмена информацией при присоединении новых узлов.

* `kube-node-lease`: Содержит объекты `Lease` для каждого узла. `kubelet` на каждом узле периодически обновляет свой объект `Lease`, сообщая control-plane о своей работоспособности (heartbeats). Это более легковесный механизм по сравнению со старым способом обновления всего объекта `Node`.

### Ограничения изоляции и удаление

Важно понимать, что `Namespace` **не обеспечивает** полную физическую изоляцию:

* **Узлы (Nodes):** Поды из разных `Namespace` могут работать на одном и том же узле.
* **Сеть:** По умолчанию поды из разных `Namespace` могут свободно общаться друг с другом. Для изоляции используются [NetworkPolicy](../Networking/Network/network_policy.md).

**Критически важное замечание:** Удаление `Namespace` приводит к **каскадному удалению всех ресурсов**, которые находятся внутри него: подов, деплойментов, сервисов и т.д. Эта операция необратима, поэтому выполняйте ее с особой осторожностью.

```bash
# Эта команда удалит НЕ ТОЛЬКО namespace, но и ВСЕ, что в нем находится!
kubectl delete namespace my-namespace
```

## Практические сценарии

### Создание Namespace

```bash
# 1. С помощью команды
kubectl create namespace my-namespace

# 2. С помощью манифеста (рекомендуется для GitOps)
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: my-namespace
  labels:
    environment: production
    team: platform
EOF
```

### Управление и просмотр

```bash
# Посмотреть все namespaces
kubectl get namespaces
# или
kubectl get ns 

# Получить поды из конкретного namespace
kubectl get pods -n my-namespace

# Получить поды из всех пространств имен
kubectl get pods --all-namespaces
# или
kubectl get pods -A

# Удалить namespace и все ресурсы внутри него
kubectl delete namespace my-namespace
```

### Проверка типа ресурса

Чтобы посмотреть, является ли ресурс namespaced, можно использовать команду:

```bash
kubectl api-resources --namespaced=true  # Ресурсы в Namespace
kubectl api-resources --namespaced=false # Ресурсы на уровне кластера
```

### Переключение контекста

Чтобы не указывать флаг `-n` каждый раз, можно изменить текущий `Namespace` в активном контексте `kubeconfig`.

```bash
# Установить my-namespace как основной для текущего контекста
kubectl config set-context --current --namespace=my-namespace

# Проверить текущий namespace
kubectl config view --minify | grep namespace
```

## Дополнительная информация

### Namespaces и Kubespray

Kubespray придерживается стандартов и не создает кастомных пространств имен. Он использует `kube-system` для развертывания всех своих управляемых компонентов.

Таким образом, после установки кластера через Kubespray, вы увидите те же четыре стандартных неймспейса:

* `default`
* `kube-system`
* `kube-public`
* `kube-node-lease`

В зависимости от вашей конфигурации, Kubespray добавит туда:

* **Сетевой плагин (CNI):** Calico, Flannel, Cilium и т.д.
* **DNS-компоненты:** CoreDNS, `dns-autoscaler`, `nodelocaldns`.
* **Ingress-контроллер:** Nginx, HAProxy и др.
* **Dashboard:** `kubernetes-dashboard` и `metrics-scraper`.
