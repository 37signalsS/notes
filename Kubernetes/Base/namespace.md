# Namespace

**Namespace** (пространство имен) — это механизм для разделения одного физического кластера Kubernetes на несколько **виртуальных кластеров**. Он позволяет изолировать группы ресурсов, создавая для них отдельную рабочую область.

Имена ресурсов должны быть уникальны в пределах одного `Namespace`, но могут повторяться в разных.

## Зачем нужны Namespaces?

1.  **Организация ресурсов:** Группировка объектов по проектам, командам или средам (например, `development`, `staging`, `production`). Это предотвращает хаос в кластере.
2.  **Предотвращение конфликтов имен:** `Deployment` с именем `my-app` может существовать одновременно в `staging` и `production`, не мешая друг другу.
3.  **Управление доступом (RBAC):** `Namespace` является основной единицей для применения политик безопасности. Можно предоставить команде разработчиков полные права в `dev-namespace`, но только на чтение в `prod-namespace`.
4.  **Квотирование ресурсов (Resource Quotas):** Можно ограничить потребление CPU, памяти и количество создаваемых объектов (подов, сервисов) для каждого `Namespace`, чтобы гарантировать справедливое распределение ресурсов.
5.  **Изоляция сетевых политик (Network Policies):** Сетевые политики применяются к подам внутри `Namespace`, позволяя контролировать входящий и исходящий трафик.

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


## Ресурсы и Namespaces

Не все ресурсы в Kubernetes привязаны к `Namespace`.

*   **Namespaced-ресурсы** (существуют внутри `Namespace`):

    *   Рабочие нагрузки: [Pod](./pod.md), [Deployment](./deployment_and_rolling_update.md), [StatefulSet](./statefulset.md), [DaemonSet](./daemonset.md), [Job](./job.md), CronJob.
    *   Конфигурация и сервисы: [Service](../Networking/service.md), [Ingress](../Networking/ingress.md), [ConfigMap](./configmap.md), [Secret](./secret.md), PersistentVolumeClaim.
    *   Политики: `NetworkPolicy`, [ResourceQuota](../Scheduling/qos_limit_and_requests.md#ограничение-суммарного-потребления-с-resourcequota).

*   **Cluster-wide ресурсы** (существуют на уровне всего кластера):

    *   Инфраструктура: `Node`, `PersistentVolume`.
    *   Безопасность и доступ: `ClusterRole`, `ClusterRoleBinding`.
    *   Системные: `Namespace` (сам по себе), `StorageClass`, `APIService`.

Чтобы посмотреть, является ли ресурс namespaced, можно использовать команду:

```bash
kubectl api-resources --namespaced=true  # Ресурсы в Namespace
kubectl api-resources --namespaced=false # Ресурсы на уровне кластера
```

## Стандартные Namespaces

При создании кластера Kubernetes инициализирует несколько пространств имен:

*   `default`: Пространство имен по умолчанию для объектов, у которых оно не указано в манифесте. Используется, когда иное пространство имен не задано. **Лучшая практика — не использовать его для реальных проектов, а создавать отдельные `Namespace`.**
*   `kube-system`: Пространство имён для системных служебных объектов Kubernetes. В нем находятся все компоненты control-plane и другие системные объекты, созданные и управляемые Kubernetes (CoreDNS, `kube-proxy` и т.д.). **Не трогать!**
*   `kube-public`: Создаваемое автоматически пространство имён, которое доступно для чтения пользователями (даже неаутентифицированными). Данное пространство имён обычно используется кластером, если ресурсы должны быть общедоступными, например, для публикации информации о кластере.
*   `kube-node-lease`: Для объектов `Lease`, которые отслеживают доступность узлов (heartbeats).

## Работа с Namespaces

#### Создание

```bash
# 1. С помощью команды
kubectl create namespace my-namespace

# 2. С помощью манифеста (рекомендуется для GitOps)
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: my-namespace
EOF
```

#### Просмотр и управление

```bash
# Посмотреть все namespaces
kubectl get namespaces
# или
kubectl get ns # вывод списка неймспейсов

# Получить поды из конкретного namespace
kubectl get pods -n my-namespace

# Получить поды из всех пространств имен
kubectl get pods --all-namespaces
# или
kubectl get pods -A

# Удалить namespace и все ресурсы внутри него
kubectl delete namespace my-namespace
```

#### Переключение контекста

Чтобы не указывать флаг `-n` каждый раз, можно изменить текущий `Namespace` в активном контексте `kubeconfig`.

```bash
# Установить my-namespace как основной для текущего контекста
kubectl config set-context --current --namespace=my-namespace

# Проверить текущий namespace
kubectl config view --minify | grep namespace
```

## Что не изолирует Namespace?

Важно понимать, что `Namespace` **не обеспечивает** полную изоляцию:

*   **Узлы (Nodes):** Поды из разных `Namespace` могут работать на одном и том же узле.
*   **Сеть:** По умолчанию поды из разных `Namespace` могут свободно общаться друг с другом. Для изоляции используются [NetworkPolicy](../Networking/network.md).
*   **Физические ресурсы:** `Namespace` ограничивает ресурсы логически через квоты, но не гарантирует физического разделения CPU или памяти.

## Namespaces и Kubespray

Kubespray придерживается стандартов и не создает кастомных пространств имен. Он использует `kube-system` для развертывания всех своих управляемых компонентов.

Таким образом, после установки кластера через Kubespray, вы увидите те же четыре стандартных неймспейса:

*   `default`
*   `kube-system`
*   `kube-public`
*   `kube-node-lease`

Однако, `kube-system` будет содержать значительно больше подов, чем при "чистой" установке через `kubeadm`. В зависимости от вашей конфигурации, Kubespray добавит туда:

*   **Сетевой плагин (CNI):** Calico, Flannel, Cilium и т.д.
*   **DNS-компоненты:** CoreDNS, а также может добавить `dns-autoscaler` и `nodelocaldns`.
*   **Ingress-контроллер:** Nginx, HAProxy и др.
*   **Dashboard:** `kubernetes-dashboard` и `metrics-scraper`.
