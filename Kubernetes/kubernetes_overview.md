# Kubernetes: Обзор и ключевые концепции

## Определения

**Kubernetes** (K8s) — открытая платформа промышленного уровня для автоматизации развёртывания, масштабирования и управления контейнеризированными приложениями. Она обеспечивает абстракцию над инфраструктурой, превращая группу серверов в единый вычислительный ресурс.

### Исторический контекст

Использование контейнеров опирается на механизмы изоляции ядра Linux: **cgroups** (контрольные группы) и **namespaces** (пространства имён). По мере того как микросервисы и распределенные системы стали нормой, освоение Kubernetes стало неотъемлемой частью системной инженерии и практик DevOps.

- **2002–2009:** Формирование технологий изоляции в ядре Linux.
- **2014:** Выпуск Kubernetes компанией Google (на основе внутреннего опыта с системой Borg).
- **2015–н.в.:** Передача проекта в Cloud Native Computing Foundation (CNCF) и становление стандартом де-факто для облачной оркестрации. Гибкость и масштабируемость системы стали ключевыми факторами успеха платформы.

### Основные решаемые задачи

Главная цель Kubernetes — автоматизация эксплуатации распределённых систем.

| Задача | Описание |
| :--- | :--- |
| **Масштабирование** | Горизонтальное (HPA) и вертикальное (VPA) масштабирование ресурсов и реплик. |
| **Балансировка нагрузки** | Эффективное распределение входящего трафика между доступными экземплярами (подами) через Service и **Gateway API**. |
| **Service Discovery** | Автоматическое обнаружение сервисов через внутренний DNS кластера (CoreDNS). |
| **Self-healing** | Проактивный мониторинг здоровья контейнеров. Kubernetes автоматически перезапускает упавшие контейнеры и переносит нагрузку без вмешательства человека. |
| **Управление конфигурацией** | Разделение кода приложения и его настроек (ConfigMap, Secret). Поддержка внешних секретов через CSI-драйверы. |
| **Оркестрация ресурсов** | Выделение CPU и памяти через механизмы управления ресурсами подов. |

## Основные концепции

### Декларативный подход и цикл согласования

Kubernetes работает по принципу **цикла согласования** (reconciliation loop), который является краеугольным камнем его устойчивости:

1. **Объявление состояния (Desired State):** Пользователь описывает желаемое состояние приложения в YAML-манифесте (например, "нужно 3 реплики").
2. **Наблюдение (Observe):** Контроллеры Kubernetes (в частности, `kube-controller-manager`) постоянно отслеживают реальное положение дел в кластере.
3. **Анализ (Analyze):** Если обнаруживается несоответствие (например, один под упал и осталось только 2), система фиксирует разницу.
4. **Согласование (Act):** Kubernetes неустанно работает в фоне, чтобы восстановить желаемое состояние (например, запускает новый под взамен упавшего).

### Архитектура кластера

Кластер состоит из двух логических уровней:

> **Важно:** Для работы кластера Kubernetes требуется как минимум один узел **Control Plane**. Хотя технически кластер может функционировать без рабочих узлов, в такой конфигурации невозможно размещение пользовательских приложений.

#### Панель управления (Control Plane) — «Мозг» кластера

«Мозг» кластера, координирующий все процессы. Основные компоненты:

- **`kube-apiserver`** — центральный шлюз, через который проходят все запросы. Единственный компонент, взаимодействующий с хранилищем. Подробнее: [Архитектура Control Plane](./Concepts/control_plane_architecture.md).
- **`etcd`** — высокодоступное распределённое хранилище всех данных кластера. Подробнее: [Обзор etcd](./Concepts/etcd_overview.md).
- **`kube-scheduler`** — выбирает оптимальный узел для запуска пода на основе ресурсов и политик. Подробнее: [kube-scheduler](./Concepts/kube_scheduler.md).
- **`kube-controller-manager`** — объединяет набор контроллеров (Node, Deployment, Namespace), следящих за состоянием ресурсов.

#### Рабочие узлы (Worker Nodes) — «Мускулы» кластера

Узлы, непосредственно выполняющие полезную нагрузку:

- **`kubelet`** — агент, обеспечивающий запуск контейнеров через CRI и проверку их состояния. Подробнее: [Kubelet](./Concepts/kubelet.md).
- **`kube-proxy`** — сетевой агент, управляющий правилами трафика. В актуальных версиях (v1.35+) режим **nftables** является стандартом де-факто, обеспечивая кратный рост производительности. Подробнее: [CNI и kube-proxy](./Networking/Network/cni_kube_proxy_roles.md).
- **Container Runtime (CRI)** — среда выполнения (`containerd`, `CRI-O`). Традиционный Docker деприкейтирован в пользу CRI-совместимых решений.
- **CNI** (Container Network Interface) — сетевые плагины (Cilium, Calico), обеспечивающие связность подов и безопасность через eBPF. Подробнее: [Сетевая модель](./Networking/Network/network_overview.md).

### Ключевые абстракции

| Абстракция | Назначение |
| :--- | :--- |
| **Pod** | Минимальная единица развёртывания. В 1.35 **Sidecar-контейнеры** полностью стабилизированы для служебных задач. Подробнее: [Pod overview](./Base/Pod/pod_overview.md) |
| **Deployment** | Декларативное управление репликами и стратегиями обновления (RollingUpdate). Подробнее: [Deployment overview](./Base/Deployment/index.md) |
| **Service** | Стабильный IP и DNS-имя для группы подов. Подробнее: [Service overview](./Networking/Service/service_overview.md) |
| **Gateway API** | Современный стандарт управления трафиком, заменивший Ingress. Поддерживает расширенные сценарии (Traffic Splitting, HTTP/3). Подробнее: [Gateway API](./Networking/gateway_api/definitions.md) |
| **Volume / PVC** | Абстракция хранилища данных. Поддержка динамического провижининга через CSI. Подробнее: [CSI overview](./Storage/CSI/csi_overview.md) |
| **Namespace** | Логическая изоляция ресурсов внутри одного кластера. Подробнее: [Namespace](./Base/namespace.md) |

### Безопасность и стандарты

- **PSA (Pod Security Admission):** Современный механизм контроля безопасности подов (заменяет PSP). Предлагает три уровня профилей: Privileged, Baseline, Restricted.
- **User Namespaces:** Изоляция пользователей внутри контейнера для предотвращения выхода на хост (Container Breakout). Стабильно в 1.35.
- **CEL (Common Expression Language):** Используется для декларативного описания политик валидации (ValidatingAdmissionPolicy), заменяя сложные вебхуки.

## Практические сценарии

### Когда использовать Kubernetes

- **Микросервисы:** когда количество сервисов растет и ручное управление становится невозможным. Kubernetes упрощает **массовые обновления** сотен контейнеров, обеспечивая согласованность изменений.
- **Высокая нагрузка:** требуется динамическое **адаптивное масштабирование** и эффективное использование ресурсов.
- **Географически распределенные системы:** развертывание в нескольких локациях с гарантией синхронизации состояния между экземплярами.
- **Гибридные инфраструктуры:** переносимость приложений между Bare Metal, виртуальными окружениями и edge-устройствами.

### Когда Kubernetes может быть избыточен

- **Простые монолиты:** достаточно одного сервера или Docker Compose.
- **Малые команды:** сложность эксплуатации может превысить выгоды от автоматизации.
- **Статичные нагрузки:** когда инфраструктура не меняется месяцами.

### Способы развёртывания

| Тип | Инструменты |
| :--- | :--- |
| **Локально (Dev)** | [minikube](./Installation/minikube/minikube_practical_scenarios.md), [kind](./Installation/kind/kind_concepts.md) |
| **Самостоятельно (Ops)** | [kubeadm](./Installation/kubeadm/index.md), [Kubespray](./Installation/Kubespray/overview.md) |
| **Специфические (Edge)** | [k3s](./Installation/k3s_dev_environment/k3s_architecture.md), [MicroK8s](./Installation/microk8s/microk8s_overview.md) |

### Предварительные требования

Перед началом работы с кластером убедитесь, что среда соответствует минимальным требованиям:

- **ОС:** Linux (RHEL, Ubuntu, Debian, Rocky Linux) или Windows 10+/Server 2019+ для локальных сценариев.
- **kubectl:** версия клиента не должна превышать версию сервера более чем на одну малую версию (например, kubectl 1.35 с кластером 1.36).
- **kubeconfig:** файл конфигурации (`~/.kube/config`) с корректными правами доступа (`600`).
- **Сеть:** открытые порты 6443 (API), 2379–2380 (etcd), 10250 (kubelet), 30000–32767 (NodePort).
- **Время:** синхронизация NTP на всех узлах (дрейф не более 1 секунды).

### Базовое администрирование через kubectl

#### Проверка состояния кластера

```bash
# Версия kubectl и сервера
kubectl version --short
# → Client Version: v1.35.0
# → Server Version: v1.35.0

# Доступные узлы
kubectl get nodes -o wide
# → NAME      STATUS   ROLES           AGE   VERSION
# → master-1  Ready    control-plane   30d   v1.35.0
# → worker-1  Ready    <none>          30d   v1.35.0

# Системные поды в namespace kube-system
kubectl get pods -n kube-system -o wide
# → все компоненты в состоянии Running
```

#### Работа с контекстами и кластерами

```bash
# Текущий контекст
kubectl config current-context
# → prod-admin

# Переключение контекста
kubectl config use-context staging-admin
# → Switched to context "staging-admin"

# Просмотр всех кластеров и пользователей
kubectl config view
# → список контекстов, кластеров, credentials (токены/сертификаты замаскированы)
```

#### Управление неймспейсами

```bash
# Создание неймспейса с лимитами по умолчанию
kubectl create namespace dev-team
# → namespace/dev-team created

# Установка лимита ресурсов
kubectl limit range create-quota --default=cpu=500m,memory=256Mi --max=cpu=2,memory=2Gi -n dev-team
# → limitrange/dev-team create-quota created

# Просмотр utilisation
kubectl top pods -n dev-team
# → NAME                    CPU(cores)   MEMORY(bytes)
# → frontend-7d8f9b5c-x2k1  100m         128Mi
```

### Управление узлами (Node Operations)

#### Плановое обслуживание (Cordon и Drain)

```bash
# Пометить узел как недоступный для планирования (Cordon)
kubectl cordon worker-2
# → node/worker-2 cordoned

# Выселение подов с эфемерными данными (Drain)
kubectl drain worker-2 --ignore-daemonsets --delete-emptydir-data --force
# → node/worker-2 evicted

# Возврат узла в обслуживание
kubectl uncordon worker-2
# → node/worker-2 uncordoned
```

#### Замена отказавшего узла

```bash
# Если узел не доступен по сети и не вернётся в кластер:
kubectl delete node worker-old
# → node "worker-old" deleted

# Перепланирование подов происходит автоматически через контроллеры
# Проверка:
kubectl get pods -o wide
# → поды пересозданы на других узлах
```

### Работа с подами и отладка

#### Быстрая диагностика

```bash
# Описание ресурса (события, условия, реплики)
kubectl describe pod nginx-abc123 -n prod
# → Conditions, Events, Containers State, Limits/Requests

# Логи контейнера
kubectl logs nginx-abc123 -n prod --previous
# → логи предыдущего (упавшего) инстанса

# Живой лог с отслеживанием
kubectl logs -f nginx-abc123 -n prod -c nginx
# → streaming output...
```

#### Ephemeral Debug Containers

```bash
# Запуск отладочного контейнера внутри пода
kubectl debug -it nginx-abc123 -n prod --image=nicolaka/netshoot --target=nginx
# → / # curl localhost:80
# → HTML response
```

### Управление ресурсами и квотами

#### ResourceQuota и LimitRange

```bash
# Лимит на namespace: 8 CPU, 16Gi памяти, 10 PVC
kubectl create quota team-quota --hard=cpu=8,memory=16Gi,pods=20 -n dev-team
# → resourcequota/team-quota created

# Значения по умолчанию для новых подов
kubectl create limit-range default-limits --default=cpu=200m,memory=256Mi --default-cpu-request=100m -n dev-team
# → limitrange/default-limits created
```

### RBAC (Role-Based Access Control)

#### Проверка прав пользователя

```bash
# Кто может делать что в namespace
kubectl auth can-i create pods -n prod --as system:serviceaccount:prod:deployer
# → yes

# Проверка доступа к секретам
kubectl auth can-i list secrets -n prod --as dev-user
# → no

# Список всех ролей в namespace
kubectl get roles,rolebindings -n prod
# → NAME                         CREATED AT
# → role.rbac.authorization.k8s.io/editor  2024-01-01
```

### Резервное копирование и восстановление

#### Резервное копирование etcd (Control Plane)

```bash
# Создание снапшота etcd
sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /var/backups/etcd-snapshot-$(date +%Y%m%d).db
# → Snapshot saved at /var/backups/etcd-snapshot-20260903.db

# Проверка целостности снапшота
sudo ETCDCTL_API=3 etcdctl --write-out=table snapshot status /var/backups/etcd-snapshot-20260903.db
# → Hash:     abc123...
# → Total RVs: 15000
```

#### Резервное копирование ресурсов через Velero

```bash
# Создание бэкапа всех ресурсов в namespace
velero backup create dev-team-backup --include-namespaces dev-team --ttl 720h0m0s
# → Backup phase: Completed

# Восстановление из бэкапа
velero restore create --from-backup dev-team-backup
# → Restore phase: Completed
```

### Мониторинг здоровья кластера (SRE Daily Checks)

```bash
# 1. Доступность узлов
kubectl get nodes -o wide
# → все узлы в состоянии Ready

# 2. Системные компоненты
kubectl get pods -A | grep -Ev 'Running|Completed'
# → выводит проблемные поды (CrashLoopBackOff, ImagePullBackOff, Pending)

# 3. Диски etcd (порог 85%)
df -h /var/lib/etcd
# → Filesystem      Size  Used Avail Use% Mounted on
# → /dev/sda1       20G   16G  4G   80% /

# 4. Сетевые connectivity между узлами
kubectl get nodes -o wide && ping -c3 master-1 && ping -c3 worker-1
# → проверка TCP 6443
nc -zv master-1 6443
# → Connection succeeded

# 5. События за последний час
kubectl get events -A --field-selector lastTimestamp.ge('1h') --sort-by='.lastTimestamp'
# → Warning  FailedScheduling  ...  Insufficient cpu
```

### Диагностика типичных неполадок

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Pod в Pending** | Нет ресурсов или нет подходящего узла | `kubectl describe pod <name>` → Events: `FailedScheduling` | Увеличить количество узлов, уменьшить requests, добавить Node Affinity |
| **CrashLoopBackOff** | Приложение падает сразу после старта | `kubectl logs <pod> --previous` | Проверить конфигурацию, переменные окружения, секреты, права на файлы |
| **ImagePullBackOff / ErrImagePull** | Реестр недоступен или неверный тег | `kubectl describe pod <name>` → Events | Проверить `imagePullPolicy`, сеть до реестра, наличие секрета `imagePullSecrets` |
| **ContainerCreating** | Ожидание монтирования Volume или подготовки CNI | `kubectl get pods -o wide`; `kubectl get events` | Проверить StorageClass, CSI-драйвер, состояние CNI-плагина |
| **Evicted** | Нехватка места на узле (disk pressure, memory pressure) | `kubectl get pods --field-selector=status.phase=Failed` | Очистить место, удалить неиспользуемые образы (`crictl rmi`), увеличить容量 |
| **API unreachable** | API-сервер недоступен или kubeconfig повреждён | `kubectl cluster-info`; `curl -k https://<api>:6443/healthz` | Проверить сервис kube-apiserver, балансировщик, срок действия сертификатов |
| **etcd потерял кворум** | Сетевые проблемы или нехватка диска | `kubectl logs -n kube-system -l component=etcd` | Восстановить из снапшота, проверить `/var/lib/etcd` и время |

### Обновление кластера

```bash
# Просмотр текущей версии и доступных обновлений
kubectl get clusterversion
# → NAME      VERSION   AVAILABLE   PROGRESSING   SINCE
# → version   1.35.0    True        False         45d

# План обновления (только для kubeadm)
sudo kubeadm upgrade plan
# → показывает доступные версии и порядок обновления

# Обновление Control Plane (по очереди: master-1, master-2, master-3)
sudo kubeadm upgrade apply v1.36.0 --control-plane
# → Kubelet, kube-proxy, cni обновляются автоматически через DaemonSet

# Перезагрузка kubelet на обновлённом узле
sudo systemctl daemon-reload && sudo systemctl restart kubelet
```

### Best Practices и очистка

- **Права доступа:** применяйте принцип минимальных привилегий (least privilege) в RBAC; избегайте wildcard (`*`) в ролях.
- **Ресурсы:** всегда указывайте `requests` и `limits` для контейнеров; используйте `LimitRange` и `ResourceQuota` для защиты namespace.
- **Сетевая политика:** применяйте `NetworkPolicy` по умолчанию, запрещая весь входящий/исходящий трафик и открывая только необходимое.
- **Образы:** используйте immutable теги (`v1.2.3`, sha256:...), избегайте `latest`; настройте `imagePullPolicy: IfNotPresent`.
- **Секреты:** храните секреты в vault (HashiCorp Vault, External Secrets Operator) и синхронизируйте их в Kubernetes через CSI-драйвер.
- **Очистка:** регулярно удаляйте неиспользуемые образы (`crictl rmi --prune`), завершённые поды, старые снапшоты etcd и бэкапы.
- **Мониторинг:** настройте алерты на `CrashLoopBackOff`, `Pending`, `NotReady` узлы, заполнение диска >85%, истечение сертификатов.

## Дополнительная информация

### Инструменты взаимодействия

1. **kubectl** — основной CLI-инструмент.
2. **Helm** — пакетный менеджер для Kubernetes.
3. **Ansible** — автоматизация ресурсов через коллекцию `kubernetes.core`. Подробнее: **[Автоматизация Kubernetes через Ansible](../Ansible/ansible-kubernetes-automation.md)**.
4. **ArgoCD / Flux** — реализация GitOps.
5. **Lens / Headlamp** — графические интерфейсы для мониторинга и отладки. Подробнее: [Обзор Headlamp](./kubernetes-dashboard.md).

### См. также

- [Высокая доступность кластера](./Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- [Архитектура Control Plane — глубокое погружение](./Concepts/control_plane_architecture.md)
- [Сетевая подсистема кластера](./Networking/Network/network_overview.md)
