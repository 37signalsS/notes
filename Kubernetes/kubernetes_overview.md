# Kubernetes: Обзор и ключевые концепции

**Актуально для:** Kubernetes 1.30–1.35+

---

## Определения

**Kubernetes (K8s)** — открытая платформа оркестрации контейнеров производственного уровня, предназначенная для автоматизации развертывания, масштабирования, сетевой связности и управления жизненным циклом контейнеризированных приложений на пуле физических или виртуальных серверов (Bare-Metal / On-Premises).

**Control Plane (Плоскость управления)** — набор управляющих компонентов кластера, принимающих глобальные решения о состоянии инфраструктуры (планирование подов, обнаружение отказов, поддержание кворума, согласование декларативного состояния).

**Data Plane (Плоскость данных / Worker Nodes)** — совокупность рабочих узлов кластера, на которых под управлением локальных системных агентов непосредственно выполняются пользовательские контейнерные нагрузки.

**Pod (Под)** — наименьшая атомарная единица развертывания в Kubernetes, представляющая собой группу из одного или нескольких тесно связанных контейнеров, разделяющих сетевой стек (IP-адрес и порты), IPC-пространство, тома хранения и запускаемых на общем хосте.

**CRI (Container Runtime Interface)** — стандартизированный gRPC-интерфейс плагинов между узловым агентом `kubelet` и средой выполнения контейнеров (containerd, CRI-O), абстрагирующий механизмы изоляции ядра Linux (namespaces, cgroups).

**CNI (Container Network Interface)** — спецификация и библиотеки плагинов (Cilium, Calico, Flannel), отвечающие за выделение сетевых интерфейсов подам, маршрутизацию трафика между узлами кластера и применение политик фильтрации.

**CSI (Container Storage Interface)** — стандарт подключения блочных и файловых хранилищ к контейнерам, позволяющий сторонним СХД (Ceph, NFS, iSCSI, локальные диски) интегрироваться с Kubernetes через динамический провижининг томов.

**Цикл согласования (Reconciliation Loop)** — непрерывный итеративный процесс работы внутренних контроллеров Kubernetes: наблюдение за текущим состоянием ресурсов (Observe), выявление отклонений от манифеста (Analyze) и выполнение корректирующих действий для приведения системы к желаемому виду (Act).

**Kubeconfig** — файл конфигурации доступа (по умолчанию `~/.kube/config`), содержащий параметры кластеров (API endpoints, CA-сертификаты), учетные данные пользователей (клиентские сертификаты, токены) и контексты (связки кластер-пользователь-неймспейс).

**Декларативное управление состоянием** — парадигма управления инфраструктурой, при которой инженер описывает целевое конечное состояние системы в манифестах (YAML/JSON), а платформа самостоятельно вычисляет и выполняет переходы между состояниями.

### Исторический контекст

Изоляция контейнеров в Linux опирается на механизмы ядра: контрольные группы (**cgroups**) и пространства имен (**namespaces**). По мере развития микросервисной архитектуры и распределенных сред возникла потребность в оркестрации сотен и тысяч связанных процессов.

- **2002–2009:** Интеграция cgroups и namespaces в ядро Linux. Эксплуатация внутренних распределенных систем Google (Borg и Omega).
- **2014:** Анонс и публикация Kubernetes компанией Google как открытого проекта с архитектурой, основанной на опыте Borg.
- **2015–н.в.:** Передача проекта в Cloud Native Computing Foundation (CNCF), отказ от встроенного рантайма Docker (деприкация Dockershim в v1.20, полное удаление в v1.24) в пользу прямого CRI (containerd, CRI-O), переход на cgroup v2 и сетевые подсистемы на базе eBPF и nftables.

### Основные решаемые задачи

| Задача | Механизм реализации в Kubernetes |
| :--- | :--- |
| **Горизонтальное масштабирование** | Автоматическое увеличение или уменьшение числа реплик (HPA — Horizontal Pod Autoscaler) по метрикам CPU, памяти или внешним счетчикам. |
| **Балансировка нагрузки** | Распределение входящего трафика между подами через абстракции `Service` (ClusterIP, NodePort, LoadBalancer на базе MetalLB) и `Gateway API` / `Ingress`. |
| **Service Discovery** | Автоматическое разрешение имен подов и сервисов через кластерный DNS (CoreDNS) без жесткой привязки к конкретным IP-адресам. |
| **Самовосстановление (Self-Healing)** | Проверка здоровья контейнеров через пробы (liveness, readiness, startup), автоматический перезапуск упавших процессов и перепланирование подов при падении узла. |
| **Управление конфигурациями и секретами** | Безопасная передача конфигурационных файлов (`ConfigMap`) и учетных данных (`Secret`) в контейнеры без пересборки образов. Шифрование в etcd на уровне диска. |
| **Оркестрация хранилища** | Автоматическое подключение и монтирование томов (`PersistentVolume`, `PersistentVolumeClaim`) через драйверы CSI при перемещении пода между серверами. |
| **Контроль распределения ресурсов** | Гарантированное резервирование (requests) и ограничение потребления (limits) CPU и памяти для изоляции "шумных соседей" (Noisy Neighbors). |

---

## Основные концепции и архитектура

### Декларативный подход и цикл согласования

Вся работа Kubernetes строится вокруг концепции контроллеров и цикла согласования (Reconciliation Loop):

1. **Объявление состояния (Desired State):** Администратор или пайплайн развертывания передает YAML-манифест в API-сервер (например, `spec.replicas: 3`).
2. **Фиксация в хранилище:** `kube-apiserver` проверяет права, валидирует схему и атомарно записывает объект в `etcd`.
3. **Наблюдение (Observe):** Контроллер соответствующего ресурса (например, `DeploymentController` внутри `kube-controller-manager`) слушает события изменений через механизм Watch в API-сервере.
4. **Анализ (Analyze):** Контроллер сравнивает желаемое число реплик (`spec.replicas = 3`) с фактическим состоянием (`status.readyReplicas = 2`).
5. **Согласование (Act):** Контроллер создает объект Pod, `kube-scheduler` назначает ему подходящий рабочий узел, а локальный `kubelet` инициирует запуск контейнеров через CRI.

```
+-------------------------------------------------------------------+
|                        kube-apiserver                             |
+-------------------+-----------------------+-----------------------+
                    ^                       ^
     Запись/чтение  |        События Watch  |  Создание подов
                    v                       v
            +---------------+   +-----------------------+
            |     etcd      |   | kube-controller-mgr   |
            +---------------+   +-----------------------+
                                            |
                                            v Планирование
                                +-----------------------+
                                |    kube-scheduler     |
                                +-----------------------+
                                            |
                                            v Назначение узла
+ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
| Worker Node                                                       |
|   +---------------+      +------------------+     +-----------+   |
|   |    kubelet    | ---> | CRI (containerd) | --> | Pods / VM |   |
|   +---------------+      +------------------+     +-----------+   |
|           |                                                       |
|   +---------------+      +------------------+                     |
|   |  kube-proxy   | ---> | nftables/iptables|                     |
|   +---------------+      +------------------+                     |
+ - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - +
```

### Архитектура кластера

Кластер делится на уровень управления (Control Plane) и уровень выполнения рабочих нагрузок (Worker Nodes).

#### Панель управления (Control Plane)

Компоненты плоскости управления поддерживают целостность кластера и могут быть запущены в режиме высокой доступности (HA) на 3 или 5 серверах:

- **`kube-apiserver`** — REST API-шлюз кластера. Единственный компонент, имеющий прямой доступ к базе данных `etcd`. Все остальные компоненты взаимодействуют исключительно через него. Подробнее: [Архитектура Control Plane](./Concepts/control_plane_architecture.md).
- **`etcd`** — отказоустойчивое распределенное хранилище типа ключ-значение на базе алгоритма консенсуса Raft. Хранит полное состояние всех ресурсов кластера. Подробнее: [Обзор etcd](./Concepts/etcd_overview.md) и [Операции с etcd](./Concepts/etcd_operations.md).
- **`kube-scheduler`** — планировщик, выбирающий оптимальный узел для размещения пода с учетом доступных ресурсов, affinity/anti-affinity, taints/tolerations и топологии сбоев. Подробнее: [kube-scheduler](./Concepts/kube_scheduler.md).
- **`kube-controller-manager`** — процесс, объединяющий базовые циклы управления (Node Lifecycle Controller, ReplicaSet Controller, EndpointSlice Controller, ServiceAccount Controller).

#### Рабочие узлы (Worker Nodes)

Узлы, на которых выполняются контейнеризированные сервисы:

- **`kubelet`** — основной системный демон узла (systemd unit). Регистрирует узел в API-сервере, отслеживает спецификации подов (через API или статические манифесты в `/etc/kubernetes/manifests`), взаимодействует с рантаймом по CRI и сообщает статус контейнеров. Подробнее: [Kubelet](./Concepts/kubelet.md).
- **`kube-proxy`** — сетевой прокси узла, транслирующий виртуальные IP-адреса `Service` в реальные сетевые маршруты к подам. В современных релизах (v1.30+) поддерживает режимы `iptables`, `ipvs` и стабильный режим `nftables`. Подробнее: [kube-proxy](./Networking/Network/kube-proxy.md) и [Роли CNI и kube-proxy](./Networking/Network/cni_kube_proxy_roles.md).
- **Container Runtime (CRI)** — низкоуровневая среда запуска контейнеров (`containerd`, `CRI-O`). Управляет жизненным циклом образов, контейнеров и пространств имен хоста. Подробнее: [Container Runtime](./Concepts/container_runtime.md).
- **CNI-плагин** — агент сетевой связности (Cilium, Calico), реализующий межподовую маршрутизацию без NAT, сетевую инкапсуляцию (VXLAN/Geneve) или прямую маршрутизацию (BGP), а также политики безопасности `NetworkPolicy`. Подробнее: [Сетевая модель](./Networking/Network/network_overview.md).

#### Высокая доступность Control Plane (HA Topology)

В производственных bare-metal средах разворачиваются две основные топологии:
1. **Stacked etcd:** База данных `etcd` запущена на тех же 3–5 узлах Control Plane в виде статических подов. Перед инстансами `kube-apiserver` устанавливается внешний балансировщик (HAProxy + Keepalived с плавающим виртуальным IP — VIP).
2. **External etcd:** Узлы `etcd` вынесены на отдельный кластер физических серверов с выделенными быстрыми NVMe-дисками.

### Системные требования и низкоуровневая интеграция хоста

Для корректной работы системных демонов Kubernetes на Linux-хостах необходима предварительная подготовка ядра:

1. **Отключение подкачки (Swap):** По умолчанию `kubelet` требует полного отключения swap (`swapoff -a`), так как планировщик полагается на детерминированные объемы RAM. Начиная с v1.30+ поддерживается контролируемый swap через параметр `NodeSwap` в конфигурации kubelet, но в production рекомендуется его отключение.
2. **Модули ядра:** Обязательна загрузка модулей мостовой фильтрации и оверлейной файловой системы:
   ```bash
   sudo modprobe overlay
   sudo modprobe br_netfilter
   ```
3. **Параметры Sysctl:** Маршрутизация сетевых пакетов через iptables/nftables:
   ```bash
   sudo sysctl -w net.bridge.bridge-nf-call-iptables=1
   sudo sysctl -w net.bridge.bridge-nf-call-ip6tables=1
   sudo sysctl -w net.ipv4.ip_forward=1
   ```
4. **Cgroups v2 и драйвер systemd:** Современные релизы требуют использования `cgroup v2` и единого менеджера cgroup `systemd` как в настройках `containerd` (`SystemdCgroup = true`), так и в `kubelet` (`cgroupDriver: systemd`). Несовпадение драйверов приводит к нестабильности и крашам узла.

### Ключевые абстракции кластера

Все сущности в Kubernetes сгруппированы по функциональным слоям:

| Категория | Ресурс | Назначение | Документация |
| :--- | :--- | :--- | :--- |
| **Вычислительная нагрузка (Workloads)** | **Pod** | Атомарный строительный блок. Содержит рабочие контейнеры, init-контейнеры и sidecar-контейнеры. | [Pod overview](./Base/Pod/pod_overview.md) |
| | **Deployment** | Декларативное управление stateless-приложениями, поддержка стратегий обновления (RollingUpdate, Recreate). | [Deployment overview](./Base/Deployment/index.md) |
| | **StatefulSet** | Управление stateful-нагрузками с постоянными идентификаторами, стабильными DNS-именами и персональными PVC. | [StatefulSet](./Base/StatefulSet/statefulset_overview.md) |
| | **DaemonSet** | Гарантированный запуск одной копии пода на каждом (или выбранном) узле кластера (агенты мониторинга, CNI, сборщики логов). | [DaemonSet](./Base/daemonset.md) |
| | **Job / CronJob** | Однократные пакетные задачи до успешного завершения и регламентные периодические задачи по расписанию. | [Job и CronJob](./Base/job.md) |
| **Конфигурация и секреты** | **ConfigMap** | Хранение неконфиденциальных данных конфигурации, переменных окружения и монтируемых файлов. | [ConfigMap](./Base/configmap.md) |
| | **Secret** | Хранение токенов, паролей и ключей TLS в кодировке Base64 с ограничением RBAC и шифрованием в etcd. | [Управление секретами](./Base/secrets/creating_secrets.md) |
| **Сетевая связность** | **Service** | Стабильный L4 IP-адрес (ClusterIP, NodePort, LoadBalancer) и запись DNS для группы эфемерных подов. | [Service overview](./Networking/Service/service_overview.md) |
| | **Gateway API / Ingress** | Маршрутизация L7-трафика (HTTP/HTTPS, gRPC), TLS-терминация, канареечные релизы и разделение трафика. | [Gateway API](./Networking/gateway_api/definitions.md) |
| | **MetalLB** | Реализация балансировщика сервисов типа `LoadBalancer` для On-Premises и Bare-Metal через ARP/BGP. | [MetalLB](./Networking/metallb.md) |
| | **NetworkPolicy** | Межподовый файрвол, определяющий правила изоляции входящего и исходящего трафика по лейблам и CIDR. | [NetworkPolicy](./Networking/Network/network_policy.md) |
| **Хранилище данных** | **PV / PVC** | `PersistentVolume` — физический том в СХД; `PersistentVolumeClaim` — запрос приложения на выделение тома. | [PV и PVC](./Storage/pv_and_pvc.md) |
| | **StorageClass** | Описание типа СХД и параметров динамического создания томов через CSI-плагины. | [StorageClass](./Storage/storageclass.md) |
| **Изоляция и квоты** | **Namespace** | Логическое разделение ресурсов, политик RBAC и лимитов потребления внутри одного кластера. | [Namespace](./Base/namespace.md) |
| | **ResourceQuota / LimitRange**| Ограничение суммарного потребления ресурсов командой и задание дефолтных requests/limits для контейнеров. | [Архитектура Control Plane](./Concepts/control_plane_architecture.md) |

### Безопасность и политики управления

1. **RBAC (Role-Based Access Control):** Разграничение доступа к ресурсам API через объекты `Role` / `ClusterRole` (наборы разрешенных глаголов: `get`, `list`, `watch`, `create`) и `RoleBinding` / `ClusterRoleBinding` (привязка к пользователям, группам или `ServiceAccount`). Подробнее: [Обзор RBAC](./Security/rbac/rbac_overview.md).
2. **Pod Security Admission (PSA):** Встроенный контроллер допуска, проверяющий поды на соответствие трем стандартным профилям Pod Security Standards:
   - `Privileged` — отсутствие ограничений (для системных агентов, CNI, storage).
   - `Baseline` — запрет явного повышения привилегий, ограничение доступа к хостовой сети и портам.
   - `Restricted` — запуск без root (`runAsNonRoot: true`), запрет privilege escalation, обязательный сброс capabilities (`drop: ["ALL"]`), read-only root filesystem.
3. **ValidatingAdmissionPolicy (CEL):** Декларативная валидация манифестов с помощью Common Expression Language без необходимости написания и поддержки внешних вебхуков допуска.
4. **User Namespaces:** Изоляция UID/GID контейнера от пространства пользователей хоста (UID 0 внутри контейнера отображается на непривилегированный UID на хосте), предотвращающая побег из контейнера (container breakout).

---

## Практические сценарии и администрирование

### Когда использовать Kubernetes

- **Высокая плотность сервисов:** Десятки и сотни микросервисов со сложной топологией связности и частыми релизами.
- **Требования к отказоустойчивости (High Availability):** Автоматический перезапуск сервисов при падении процессов и прозрачный перенос нагрузок при аварии физического сервера.
- **Эффективное использование серверных мощностей:** Уплотнение нагрузок (bin-packing) за счет строгого распределения requests и limits.
- **Стандартизация инфраструктуры:** Единый интерфейс развертывания приложений независимо от физической площадки или конфигурации оборудования.

### Когда Kubernetes избыточен

- **Простые статичные монолиты:** Один или два независимых сервиса, для которых достаточно стандартного демона systemd, Docker Compose или Podman.
- **Ограниченные ресурсы команды:** В штате нет выделенных инженеров для поддержки Control Plane, регулярных апгрейдов кластера, настройки резервного копирования etcd и траблшутинга сети.
- **Строгие требования к предельно низкой сетевой задержке (Ultra-low latency):** Накладные расходы на виртуализацию сети CNI, оверлеи (VXLAN) и трансляцию правил `kube-proxy` могут быть неприемлемы для специализированных HPC/финансовых задач без прямого HostNetwork/SR-IOV.

### Способы развёртывания (On-Premises / Bare-Metal / Dev)

| Назначение | Инструменты | Особенности | Документация |
| :--- | :--- | :--- | :--- |
| **Локальная разработка и тестирование** | **minikube**, **kind** | Быстрый запуск одноузлового кластера в Docker/VM на рабочей станции инженера. | [Сценарии minikube](./Installation/minikube/minikube_practical_scenarios.md), [Обзор kind](./Installation/kind/kind_concepts.md) |
| **Производственные Bare-Metal кластеры** | **kubeadm** | Стандартный CLI-инструмент инициализации и апгрейда сертифицированных CNCF кластеров. | [Развертывание kubeadm](./Installation/kubeadm/index.md) |
| **Автоматизация крупных площадок** | **Kubespray** | Плейбуки Ansible для развертывания отказоустойчивых production-кластеров на парке серверов. | [Обзор Kubespray](./Installation/Kubespray/overview.md) |
| **Легковесные и Edge-окружения** | **k3s**, **MicroK8s** | Оптимизированные дистрибутивы с минимальным потреблением RAM, заменой etcd на SQLite (в одиночном режиме) и встроенными компонентами. | [Архитектура k3s](./Installation/k3s_dev_environment/k3s_architecture.md), [Обзор MicroK8s](./Installation/microk8s/microk8s_overview.md) |
| **Отказоустойчивый стек на голом железе** | **HA Bare-Metal** | Схема с 3 master-узлами, Keepalived VIP, HAProxy и Ceph CSI хранилищем. | [HA кластер на Bare-Metal](./Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md) |

### Предварительные требования к инфраструктуре

Перед началом эксплуатации убедитесь в выполнении базовых требований:
- **Операционная система:** Linux (Ubuntu 22.04/24.04 LTS, Debian 12, RHEL/Rocky Linux 9).
- **Синхронизация времени:** Демон `chrony` или `systemd-timesyncd` на всех узлах. Рассинхронизация более 500 мс нарушает кворум etcd и валидацию TLS-сертификатов.
- **Сетевые порты:**
  - Control Plane: `6443/TCP` (API-сервер), `2379-2380/TCP` (клиенты и пиры etcd), `10250/TCP` (Kubelet API), `10257/TCP` (Controller Manager), `10259/TCP` (Scheduler).
  - Worker Nodes: `10250/TCP` (Kubelet API), `10256/TCP` (Kube-proxy health check), `30000-32767/TCP` (NodePort диапазон сервисов).
  - CNI трафик: например, `8472/UDP` (Flannel/VXLAN) или `4789/UDP` (Calico/VXLAN), либо прямое BGP-взаимодействие (`179/TCP`).

---

### Базовое администрирование через kubectl

#### 1. Проверка состояния кластера и узлов

```bash
# Проверка версии клиента и сервера
kubectl version
# → Client Version: v1.35.0
# → Kustomize Version: v5.5.0
# → Server Version: v1.35.0

# Просмотр рабочих и управляющих узлов
kubectl get nodes -o wide
# → NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    OS-IMAGE             KERNEL-VERSION
# → master-01  Ready    control-plane   45d   v1.35.0   192.168.1.10   Ubuntu 24.04 LTS     6.8.0-45-generic
# → worker-01  Ready    <none>          45d   v1.35.0   192.168.1.20   Ubuntu 24.04 LTS     6.8.0-45-generic
# → worker-02  Ready    <none>          45d   v1.35.0   192.168.1.21   Ubuntu 24.04 LTS     6.8.0-45-generic

# Проверка системных подов Control Plane и CNI
kubectl get pods -n kube-system -o wide
# → Все поды (coredns, etcd, kube-apiserver, kube-proxy, cilium/calico) находятся в состоянии Running
```

#### 2. Работа с конфигурацией и контекстами (kubeconfig)

```bash
# Просмотр текущего активного контекста
kubectl config current-context
# → kubernetes-admin@cluster.local

# Список доступных контекстов в kubeconfig
kubectl config get-contexts
# → CURRENT   NAME                          CLUSTER         AUTHINFO           NAMESPACE
# → *         kubernetes-admin@prod         prod-cluster    kubernetes-admin   default
# →           kubernetes-admin@stage        stage-cluster   kubernetes-admin   default

# Переключение на другой контекст
kubectl config use-context kubernetes-admin@stage
# → Switched to context "kubernetes-admin@stage".
```

#### 3. Изоляция и управление ресурсами Namespace

Создание изолированного пространства имен с квотами:

```bash
# Создание namespace
kubectl create namespace prod-apps
# → namespace/prod-apps created

# Создание жесткой квоты на namespace (ResourceQuota)
kubectl create quota prod-quota \
  --hard=requests.cpu=4,requests.memory=8Gi,limits.cpu=8,limits.memory=16Gi,pods=20 \
  -n prod-apps
# → resourcequota/prod-quota created

# Проверка применения квоты
kubectl get resourcequota prod-quota -n prod-apps
# → NAME         AGE   REQUEST                                       LIMIT
# → prod-quota   10s   requests.cpu: 0/4, requests.memory: 0/8Gi   limits.cpu: 0/8, limits.memory: 0/16Gi
```

Для установки дефолтных значений CPU/памяти контейнерам применяется декларативный манифест `LimitRange`:

```bash
cat <<EOF | kubectl apply -n prod-apps -f -
apiVersion: v1
kind: LimitRange
metadata:
  name: default-container-limits
spec:
  limits:
  - default:
      cpu: 500m
      memory: 512Mi
    defaultRequest:
      cpu: 100m
      memory: 128Mi
    type: Container
EOF
# → limitrange/default-container-limits created
```

---

### Управление жизненным циклом узлов (Node Maintenance)

Плановое обслуживание физического сервера (замена оборудования, обновление ядра, апгрейд дистрибутива):

```bash
# 1. Запретить планирование новых подов на узел (Cordon)
kubectl cordon worker-01
# → node/worker-01 cordoned

# 2. Безопасно выселить все запущенные поды (Drain)
# Флаг --ignore-daemonsets обязателен для сохранения системных демонов (CNI, kube-proxy)
# Флаг --delete-emptydir-data разрешает удаление подов с временными томами emptyDir
kubectl drain worker-01 --ignore-daemonsets --delete-emptydir-data --force
# → evicting pod prod-apps/web-server-7b448f766-4k9xl
# → evicting pod prod-apps/api-service-59bc9d59f-d2zqw
# → node/worker-01 drained

# 3. Выполнение работ на физическом сервере (перезагрузка, замена диска)
# sudo reboot

# 4. Возврат узла в строй после успешной загрузки (Uncordon)
kubectl uncordon worker-01
# → node/worker-01 uncordoned
```

Подробнее о регламентах вывода узлов: [Обслуживание узлов](./Operations/node_maintenance.md).

---

### Диагностика и отладка нагрузок

#### 1. Детальная инспекция ресурса и событий

```bash
# Просмотр событий и описания пода
kubectl describe pod web-server-7b448f766-4k9xl -n prod-apps
# → Look at: Conditions, Volumes, Events (Warning FailedScheduling, BackOff и т.д.)

# Просмотр всех недавних предупреждений в кластере
kubectl get events -A --field-selector type=Warning --sort-by='.metadata.creationTimestamp'
# → 10m  Warning  FailedScheduling  pod/db-0  0/3 nodes available: 3 Insufficient memory.
```

#### 2. Анализ логов

```bash
# Просмотр логов контейнера в реальном времени
kubectl logs -f web-server-7b448f766-4k9xl -c nginx -n prod-apps --tail=100
# → 192.168.1.1 - [17/Oct/2026:21:00:00 +0000] "GET /healthz HTTP/1.1" 200 ...

# Просмотр логов предыдущего упавшего экземпляра контейнера (после рестарта)
kubectl logs web-server-7b448f766-4k9xl -c nginx -n prod-apps --previous
# → [emerg] 1#1: host not found in upstream "database.internal" in /etc/nginx/nginx.conf:23
```

#### 3. Интерактивная отладка и Ephemeral Containers

Если контейнер не содержит утилит (distroless/scratch образ), к поду подключается эфемерный отладочный контейнер с набором сетевых утилит:

```bash
# Подключение эфемерного контейнера с инструментами netshoot
kubectl debug -it web-server-7b448f766-4k9xl -n prod-apps \
  --image=nicolaka/netshoot \
  --target=nginx
# → Target container "nginx" will share process namespace with debug container.
# → If you don't see a command prompt, try pressing enter.
# / # curl -I http://127.0.0.1:80
# → HTTP/1.1 200 OK
```

---

### Резервное копирование и Disaster Recovery (etcd)

В On-Premises окружении регулярный бэкап `etcd` является критической задачей администратора:

#### Создание снапшота базы данных etcd

```bash
# Выполняется на любом узле Control Plane от имени суперпользователя
sudo ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /var/backups/etcd-snapshot-$(date +%Y%m%d_%H%M%S).db
# → Snapshot saved at /var/backups/etcd-snapshot-20261017_210000.db

# Валидация целостности созданного снапшота
sudo ETCDCTL_API=3 etcdctl --write-out=table snapshot status /var/backups/etcd-snapshot-20261017_210000.db
# → +----------+----------+------------+------------+
# → |   HASH   | REVISION | TOTAL KEYS | TOTAL SIZE |
# → +----------+----------+------------+------------+
# → | d41d8cd9 |   145892 |       4210 |      18 MB |
# → +----------+----------+------------+------------+
```

#### Процедура восстановления etcd (Disaster Recovery)

1. Остановить `kube-apiserver` на всех master-узлах (переместить манифесты из `/etc/kubernetes/manifests/` во временный каталог).
2. Выполнить восстановление снапшота в новый каталог данных:
   ```bash
   sudo ETCDCTL_API=3 etcdctl snapshot restore /var/backups/etcd-snapshot-20261017_210000.db \
     --data-dir=/var/lib/etcd-restored
   ```
3. Обновить параметр `--data-dir=/var/lib/etcd-restored` в `/etc/kubernetes/manifests/etcd.yaml`.
4. Вернуть манифесты Control Plane обратно в `/etc/kubernetes/manifests/` и дождаться запуска подов.

Подробнее о стратегиях резервного копирования: [Стратегии бэкапа в Kubernetes](./Operations/backup-strategies.md).

---

### Регламент обновления кластера (kubeadm Upgrade)

В соответствии с политикой поддержки версий Kubernetes (N-1), обновление выполняется строго последовательно, без пропуска минорных версий (например, `1.34.x` -> `1.35.x`).

#### 1. Обновление первого узла Control Plane

```bash
# 1. Запретить размещение нагрузок и выселить поды
kubectl cordon master-01
kubectl drain master-01 --ignore-daemonsets --delete-emptydir-data

# 2. Обновить пакетный менеджер и версию утилиты kubeadm
sudo apt-get update && sudo apt-get install -y --allow-change-held-packages kubeadm=1.35.1-1.1

# 3. Проверить план обновления компонентов кластера
sudo kubeadm upgrade plan
# → Components that can be upgraded:
# → kube-apiserver v1.34.3 -> v1.35.1
# → kube-controller-manager v1.34.3 -> v1.35.1
# → kube-scheduler v1.34.3 -> v1.35.1
# → kube-proxy v1.34.3 -> v1.35.1

# 4. Применить обновление плоскости управления
sudo kubeadm upgrade apply v1.35.1 -y
# → [upgrade/successful] SUCCESS! Your cluster was upgraded to "v1.35.1".

# 5. Обновить kubelet и kubectl на узле
sudo apt-get install -y --allow-change-held-packages kubelet=1.35.1-1.1 kubectl=1.35.1-1.1
sudo systemctl daemon-reload && sudo systemctl restart kubelet

# 6. Вернуть master-узел в строй
kubectl uncordon master-01
```

#### 2. Обновление остальных узлов Control Plane и Worker Nodes

Для всех остальных управляющих и рабочих узлов процедура идентична:

```bash
# На управляющей машине:
kubectl cordon worker-01
kubectl drain worker-01 --ignore-daemonsets --delete-emptydir-data

# На самом узле worker-01:
sudo apt-get update && sudo apt-get install -y --allow-change-held-packages kubeadm=1.35.1-1.1
sudo kubeadm upgrade node
sudo apt-get install -y --allow-change-held-packages kubelet=1.35.1-1.1
sudo systemctl daemon-reload && sudo systemctl restart kubelet

# На управляющей машине:
kubectl uncordon worker-01
```

Подробнее о регламентах апгрейда: [Обновление кластеров](./Operations/upgrading_clusters.md).

---

## Диагностика и устранение неполадок

### Алгоритм расследования инцидентов SRE

При возникновении сбоя диагностика выполняется сверху вниз:

1. **Проверка доступности API-сервера:** `kubectl cluster-info` и проверка ответа `curl -k https://<API_VIP>:6443/livez`.
2. **Проверка состояния узлов:** `kubectl get nodes` (поиск статусов `NotReady`, проверка условий `DiskPressure`, `MemoryPressure`, `PIDPressure`).
3. **Локализация проблемных подов:** `kubectl get pods -A | grep -Ev 'Running|Completed'`.
4. **Анализ манифеста и событий:** `kubectl describe pod <pod-name> -n <namespace>` (блок `Events:` внизу вывода).
5. **Анализ логов приложения:** `kubectl logs <pod-name> -c <container> --previous`.
6. **Проверка системных демонов узла:** `systemctl status kubelet`, `journalctl -u kubelet -n 100 --no-pager`, `systemctl status containerd`.
7. **Проверка сети и DNS:** запуск тестового пода с `dig`/`nslookup` для валидации CoreDNS.

### Матрица типовых неисправностей

| Симптом | Первопричина | Метод диагностики | Способ решения |
| :--- | :--- | :--- | :--- |
| **Pod в статусе Pending** | Нехватка CPU/RAM на узлах; ограничения `nodeSelector`, `affinity`; неподходящие `taints`; PVC не может привязаться к PV. | `kubectl describe pod <name>` → раздел `Events: FailedScheduling`. | Снизить requests приложения, добавить воркер-узлы, исправить селекторы или добавить соответствующие `tolerations`. Проверить статус PVC. |
| **CrashLoopBackOff (Exit Code 1)** | Ошибка конфигурации приложения, неверные переменные окружения, битый конфигурационный файл. | `kubectl logs <pod> --previous` | Исправить переменные окружения, аргументы запуска в `command`/`args` или смонтированный `ConfigMap`. |
| **CrashLoopBackOff (Exit Code 137 / OOMKilled)** | Приложение превысило лимит оперативной памяти (`spec.containers[*].resources.limits.memory`) и было уничтожено ядром через Linux OOM Killer. | `kubectl describe pod <name>` → `Last State: Terminated, Reason: OOMKilled, Exit Code: 137`. | Увеличить `limits.memory` в манифесте, оптимизировать профиль потребления памяти (например, heap size JVM, утечки памяти). |
| **CrashLoopBackOff (Exit Code 127)** | Не найден исполняемый файл или библиотека в образе контейнера. | `kubectl logs <pod>` → `exec: "...": executable file not found in $PATH`. | Проверить директиву `command` в манифесте или `ENTRYPOINT`/`PATH` в Dockerfile. |
| **ImagePullBackOff / ErrImagePull** | Ошибка авторизации в реестре образов, неверное имя/тег образа, отсутствие сетевого доступа к реестру с узла. | `kubectl describe pod <name>` → `Events: Failed to pull image ... unauthorized`. | Создать и привязать секрет типа `docker-registry` через `imagePullSecrets`, проверить сетевую связность и валидность тега. |
| **CreateContainerConfigError** | Ссылка на несуществующий `ConfigMap` или `Secret` в секциях `envFrom` или `volumes`. | `kubectl describe pod <name>` → `Events: configmap "app-cfg" not found`. | Создать недостающий ConfigMap/Secret или исправить опечатку в имени ресурса в манифесте пода. |
| **Pod в статусе Evicted** | Узел испытывает дефицит ресурсов (DiskPressure, MemoryPressure). Kubelet вытесняет поды с более низким приоритетом QoS. | `kubectl get pod <name> -o yaml` → `status.reason: Evicted`. `kubectl describe node <node>`. | Очистить дисковое пространство на узле (`sudo crictl rmi --prune`), проверить ротацию логов `/var/log`, увеличить объем дискового пространства или перенести нагрузки. |
| **Узел в статусе NotReady** | Kubelet упал, containerd завис, исчерпаны дескрипторы/PID, сетевой разрыв между узлом и API-сервером. | `ssh <node> "sudo systemctl status kubelet containerd"` и чтение `journalctl -u kubelet -e`. | Перезапустить `containerd` и `kubelet`, проверить системные лимиты ядра (`sysctl fs.file-max`, `kernel.pid_max`), устранить сетевую изоляцию. |
| **Сбой CoreDNS / Имена не резолвятся** | Зацикливание DNS-запросов (loopback в `/etc/resolv.conf`), сетевая политика блокирует порт 53 UDP, поды CoreDNS не запущены. | `kubectl run -it --rm test-dns --image=busybox:1.36 -- nslookup kubernetes.default`. | Проверить статус подов CoreDNS, исключить локальные DNS-петли в `/etc/resolv.conf` хоста, проверить политики `NetworkPolicy`. |
| **Срок действия сертификатов истек** | Прошел 1 год с момента установки/последнего обновления сертификатов кластера kubeadm. API-сервер не стартует. | `sudo kubeadm certs check-expiration`. | Выполнить продление сертификатов: `sudo kubeadm certs renew all`, затем перезапустить системные поды Control Plane. Подробнее: [Ротация сертификатов](./Operations/certificate_management.md). |

---

## Рекомендации и Best Practices

### Управление ресурсами и планирование

- **Обязательное задание Requests и Limits:** Никогда не развертывайте поды в production без указания `resources.requests` и `resources.limits`.
  - Установка одинаковых `requests` и `limits` переводит под в класс обслуживания **Guaranteed**, гарантируя защиту от вытеснения при дефиците памяти.
  - Разные значения формируют класс **Burstable** (допускается кратковременный всплеск потребления).
- **Защита Namespace:** Всегда настраивайте `LimitRange` (для подстановки дефолтных значений тем, кто забыл их указать) и `ResourceQuota` (для предотвращения исчерпания ресурсов кластера одной командой).
- **PodDisruptionBudget (PDB):** Для критичных сервисов обязательно создавайте манифесты `PodDisruptionBudget` с параметром `minAvailable` или `maxUnavailable`. Это защищает сервис от даунтайма при выполнении административных операций `kubectl drain`.

### Пробы здоровья (Health Checks)

- **Разделение Liveness и Readiness проб:**
  - `readinessProbe` отвечает за подачу трафика на под через сервис. Если база данных временно недоступна — readiness должна вернуть ошибку, исключив под из балансировки, но НЕ перезагружая его.
  - `livenessProbe` отвечает за выявление необратимых зависаний (deadlock). Ошибка приводит к перезапуску контейнера. Никогда не включайте проверку внешних зависимостей (БД, кэш) в liveness-пробу, иначе падение БД вызовет лавинообразный перезапуск всех микросервисов в кластере (Cascading Failure).
- **Использование StartupProbe:** Для медленно стартующих приложений (например, Java/Spring Boot) используйте `startupProbe`, чтобы liveness-проба не убивала контейнер во время инициализации.

### Эксплуатация инфраструктуры и безопасность

- **Отказ от Root-прав:** Задавайте в `securityContext` параметры:
  ```yaml
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop:
        - ALL
  ```
- **Сетевая изоляция (Default Deny):** По умолчанию межподовый трафик в кластере полностью открыт. Создавайте политику `default-deny` для каждого namespace, открывая только явно разрешенные порты и ingress/egress направления.
- **Производительность дисков etcd:** Для серверов Control Plane используйте только локальные NVMe/SSD накопители. Задержка операции записи на диск (`fsync latency`) для etcd не должна превышать 10 мс (99-й перцентиль). Размещение каталога `/var/lib/etcd` на сетевых файловых системах (NFS, медленный SAN) категорически запрещено.
- **Регулярная очистка образов:** Настройте параметры очистки мусора (Garbage Collection) в `kubelet` (`imageGCHighThresholdPercent: 80`, `imageGCLowThresholdPercent: 70`) либо автоматизируйте регламентную очистку через системный cron: `crictl rmi --prune`.

---

## Дополнительная информация

### Инструменты экосистемы администрирования

- **`kubectl`** — основной консольный клиент для декларативного и императивного управления ресурсами.
- **`Helm`** — пакетный менеджер для шаблонизации, версионирования и комплексной установки приложений в виде чартов.
- **`Kustomize`** — нативный инструмент кастомизации манифестов без шаблонизации, встроенный непосредственно в `kubectl` (`kubectl apply -k`). Подробнее: [Kustomize](./kustomize.md).
- **`k9s`** — интерактивный терминальный UI для мониторинга, просмотра логов, управления ресурсами и быстрой отладки подов.
- **`Headlamp` / `Lens`** — графические панели управления для комплексного мониторинга состояния кластеров. Подробнее: [Обзор Headlamp](./kubernetes-dashboard.md).
- **`MetalLB`** — сетевой контроллер, реализующий поддержку сервисов типа `LoadBalancer` в On-Premises и Bare-Metal инсталляциях. Подробнее: [MetalLB](./Networking/metallb.md).
- **`Velero`** — инструмент создания резервных копий манифестов объектов и персистентных томов с выгрузкой в локальное S3/NFS хранилище.

### См. также

- [Архитектура Control Plane — детальное руководство](./Concepts/control_plane_architecture.md)
- [Внутреннее устройство и эксплуатация etcd](./Concepts/etcd_overview.md)
- [Настройка и тюнинг сетевой подсистемы кластера](./Networking/Network/network_overview.md)
- [Регламенты обслуживания и вывода узлов](./Operations/node_maintenance.md)
- [Пошаговый регламент обновления кластеров](./Operations/upgrading_clusters.md)
- [Стратегии резервного копирования и DR](./Operations/backup-strategies.md)
- [Управление сертификатами и предотвращение сбоев TLS](./Operations/certificate_management.md)
- [Развертывание отказоустойчивого Bare-Metal кластера](./Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- [Диагностика и устранение неполадок в Kubernetes](./Troubleshooting/troubleshooting_overview.md)
- [Автоматизация управления кластером через Ansible](../Ansible/ansible-kubernetes-automation.md)
