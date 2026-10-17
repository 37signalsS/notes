# Обзор Red Hat OpenShift

**Актуально для:** Red Hat OpenShift Container Platform (OCP) 4.14–4.18+ (Bare-Metal / On-Premises)

---

## Определения

**Red Hat OpenShift Container Platform (OCP)** — коммерческий дистрибутив Kubernetes корпоративного уровня, разработанный Red Hat на базе Enterprise Linux (RHEL/RHCOS). Представляет собой интегрированную платформу PaaS/CaaS для on-premise и bare-metal инфраструктур, включающую механизмы декларативного управления операционной системой узлов (MCO), сквозного обновления компонентов кластера (CVO), встроенный жизненный цикл операторов (OLM) и расширенную модель безопасности (SCC).

**OKD (Origin Kubernetes Distribution)** — открытый upstream-дистрибутив сообщества, являющийся основой для коммерческих версий OpenShift. Включает базовые компоненты платформы, консоль и операторы, но поставляется без коммерческой поддержки и сертификации Red Hat.

**RHCOS (Red Hat Enterprise Linux CoreOS)** — специализированная неизменяемая (immutable) операционная система для узлов OpenShift 4.x. Файловая система `/usr` монтируется только для чтения, управление пакетами через традиционный менеджер исключено, а любые изменения конфигурации (ядро, sysctl, systemd, файлы) применяются централизованно через Machine Config Operator и утилиту Ignition при загрузке.

**CRI-O** — легковесная среда выполнения контейнеров, разработанная специально под требования Kubernetes Container Runtime Interface (CRI). Является единственным штатным CRI-рантаймом в OpenShift. Выполняет запуск OCI-контейнеров через низкоуровневые рантаймы `runc` или `crun`. Подробнее: [Container Runtime в Kubernetes](./Concepts/container_runtime.md).

**MCO (Machine Config Operator)** — кластерный оператор, управляющий конфигурацией операционной системы RHCOS на всех узлах. Транслирует манифесты `MachineConfig` в конфигурации Ignition и контролирует rolling-обновление и перезагрузку узлов через пулы `MachineConfigPool`.

**CVO (Cluster Version Operator)** — оператор, управляющий жизненным циклом самого кластера OpenShift. Отслеживает манифесты всех базовых операторов платформы, проверяет доступность версий в каналах обновления (`fast`, `stable`, `eus`) и выполняет скоординированное обновление компонентов без прерывания рабочих нагрузок.

**SCC (Security Context Constraints)** — встроенный в OpenShift механизм управления привилегиями подов, предшествовавший Pod Security Standards (PSS) и обеспечивающий гранулярный контроль доступа к системным ресурсам ядра. Контролирует запуск от root, использование host-сети, монтирование hostPath, добавление Linux capabilities и назначение SELinux-меток.

**OLM (Operator Lifecycle Manager)** — подсистема управления операторами в кластере. Обеспечивает каталог операторов (CatalogSource), автоматическое разрешение зависимостей, разграничение прав (OperatorGroup) и подписку на обновления (Subscription/CSV).

**Routes** — встроенный ресурс OpenShift для публикации сервисов во внешнюю сеть на уровне L7 через HAProxy-роутер (`openshift-ingress-operator`). Поддерживает режимы шифрования `edge`, `passthrough`, `reencrypt` и открытый HTTP.

**Projects** — расширение стандартных `Namespace` Kubernetes в OpenShift. Включает декларативный запрос на создание (`ProjectRequest`), автоматическое выделение уникального диапазона UID/GID для запуска контейнеров и ролевые привязки администраторов проекта.

**ImageStreams** — абстракция виртуального реестра образов в OpenShift, отслеживающая теги и SHA256-дайджесты внешних и внутренних контейнерных образов. Позволяет автоматически триггерить пересборку или деплой приложений при обновлении базового образа.

**BuildConfig и S2I (Source-to-Image)** — встроенная система сборки контейнеров внутри кластера. Механизм S2I принимает исходный код из Git и готовый builder-образ среды разработки, собирая рабочий образ без необходимости писать `Dockerfile`.

**`oc`** — официальный консольный клиент OpenShift. Является полным надмножеством `kubectl`, дополненным командами управления проектами (`oc project`), операторами (`oc get co`), роутами (`oc expose`), сборками (`oc start-build`) и системным администрированием (`oc adm`).

**`must-gather`** — официальный инструмент SRE/DevOps для сбора полного диагностического архива кластера (состояния операторов, аудит, метрики, логи) без необходимости ручного обхода узлов.

---

## Архитектура и основные концепции

### Архитектура OpenShift 4 в On-Premises / Bare-Metal

OpenShift 4 построен на парадигме **Everything-as-an-Operator** («всё управляется операторами») и концепции неизменяемой инфраструктуры. Все компоненты платформы — от сетевого стека до системных служб ОС узла — функционируют как контроллеры, постоянно приводящие фактическое состояние к желаемому.

```
+-------------------------------------------------------------------------------+
|                             OpenShift Web Console / oc CLI                    |
+-------------------------------------------------------------------------------+
                                        | (HTTPS / REST API)
                                        v
+-------------------------------------------------------------------------------+
|                       CONTROL PLANE (3+ узла, RHCOS)                          |
|  +-------------------+  +--------------------+  +--------------------------+  |
|  | OpenShift API     |  | Kube API Server    |  | etcd Cluster             |  |
|  | Server (OAuth/SCC)|  | (v1.29 - v1.31+)   |  | (Высокая I/O скорость)   |  |
|  +-------------------+  +--------------------+  +--------------------------+  |
|  +-------------------+  +--------------------+  +--------------------------+  |
|  | CVO               |  | MCO                |  | Kube Controller Manager  |  |
|  | (Cluster Version) |  | (Machine Config)   |  | & Kube Scheduler         |  |
|  +-------------------+  +--------------------+  +--------------------------+  |
+-------------------------------------------------------------------------------+
                                        | (Overlay: GENEVE / Port 6081)
                                        v
+-------------------------------------------------------------------------------+
|                         WORKER PLANE (RHCOS / RHEL)                           |
|  +-------------------------------------------------------------------------+  |
|  | Kubelet  <--->  CRI-O Runtime  <--->  OCI (runc / crun)                 |  |
|  +-------------------------------------------------------------------------+  |
|  +-------------------------------------------------------------------------+  |
|  | OVN-Kubernetes CNI Node Agent (ovn-k8s, Open vSwitch)                   |  |
|  +-------------------------------------------------------------------------+  |
|  +-------------------+  +--------------------+  +--------------------------+  |
|  | Ingress Router    |  | Monitoring Stack   |  | Workload Pods            |  |
|  | (HAProxy Pods)    |  | (Prometheus/NodeExp|  | (Non-root, restricted-v2)|  |
|  +-------------------+  +--------------------+  +--------------------------+  |
+-------------------------------------------------------------------------------+
```

#### Компоненты Control Plane (Мастер-узлы)

Control Plane развёртывается минимум на трёх физических серверах или виртуальных машинах для обеспечения отказоустойчивости кворума etcd.

| Компонент | Назначение в архитектуре |
| :--- | :--- |
| **Kube API Server & OpenShift API Server** | Обработка запросов REST API, валидация и мутация манифестов, аутентификация через OAuth и авторизация RBAC. |
| **etcd** | Распределённое хранилище состояния кластера (RAFT). Требует строгого контроля дисковых задержек (`fsync` p99 < 10 мс). |
| **Cluster Version Operator (CVO)** | Центральный оператор обновлений. Управляет версионированием и порядком выкатки всех `ClusterOperators`. |
| **Machine Config Operator (MCO)** | Управление операционной системой узлов. Генерирует файлы конфигурации Ignition, применяет обновления ядра, драйверов и сервисов systemd. |
| **Kube Controller Manager & Scheduler** | Управление репликацией, эндпоинтами и размещением подов на узлах с учётом taint/toleration и affinity. |
| **Operator Lifecycle Manager (OLM)** | Обслуживание подсистемы операторов, контроль версий CRD и прав доступа ServiceAccount. |

#### Компоненты Worker Plane (Рабочие узлы)

| Компонент | Назначение в архитектуре |
| :--- | :--- |
| **Kubelet** | Агент взаимодействия с Control Plane. Получает спецификации подов (PodSpec) и транслирует команды в рантайм. |
| **CRI-O** | Единственный штатный CRI-совместимый рантайм контейнеров в OpenShift, работающий напрямую с ядром через `runc`/`crun`. |
| **OVN-Kubernetes Node** | Агент сетевого плагина OVN (Open Virtual Network). Управляет локальным Open vSwitch (OVS), туннелями GENEVE и flow-правилами. |
| **Machine Config Daemon (MCD)** | Локальный агент на каждом узле, выполняющий применение конфигураций `MachineConfig`, перезагрузку и подтверждение готовности узла. |

#### Встроенные платформенные сервисы

1. **Внутренний реестр (OpenShift Image Registry):** OCI-реестр, интегрированный с кластерной аутентификацией и хранилищем (ODF/NFS/S3).
2. **Стек мониторинга (Cluster Monitoring Operator):** Prometheus, Thanos Querier, Alertmanager, Grafana (только для чтения системных метрик) и node-exporter.
3. **Маршрутизация (Ingress Operator):** Развёртывает и контролирует пул подов HAProxy, обрабатывающих входящий внешний L7-трафик на портах 80/443.
4. **Стек сбора логов (Cluster Logging Operator):** Сбор системных и прикладных логов через Vector/Fluentd с экспортом в OpenSearch/Elasticsearch или внешний SIEM.

---

### Сравнение OpenShift и ванильного Kubernetes

| Критерий | Red Hat OpenShift (OCP) | Kubernetes (Vanilla) |
| :--- | :--- | :--- |
| **Безопасность контейнеров** | **SCC (Security Context Constraints)** включены по умолчанию. Контейнеры запускаются от случайного UID из диапазона проекта; root блокируется без явного grant. | **PSS (Pod Security Standards)**. По умолчанию разрешительный (Privileged), требует ручной настройки `AdmissionConfiguration` или меток пространств имён. |
| **Управление операционной системой** | **Декларативное через MCO**. ОС узлов (RHCOS) неизменяема. Обновления ОС, параметры ядра, NTP, SSH управляются через CRD `MachineConfig`. | **Императивное ручное или внешнее**. Управление ОС через Ansible, Puppet, bash-скрипты или cloud-init. ОС не синхронизирована с состоянием K8s. |
| **Среда выполнения (Runtime)** | **CRI-O** (строго зафиксирован и протестирован в связке с версией платформы). | **containerd** или **CRI-O** (выбирается и настраивается администратором вручную). |
| **Жизненный цикл кластера** | **Автоматизирован через CVO**. Обновление кластера одной командой (`oc adm upgrade`), включая ОС хостов, CNI, CRI-O и K8s. | **Ручное поэтапное обновление**. Отдельное обновление `kubeadm`, `kubelet`, пакетов ОС хоста, CNI-плагина и компонентов Control Plane. |
| **Сетевой плагин (CNI)** | **OVN-Kubernetes** по умолчанию. Поддержка Egress IP, Egress Firewall, UDN, BGP/FRR из коробки. | Сторонний плагин (Cilium, Calico, Flannel), настраиваемый администратором самостоятельно. |
| **Маршрутизация (L7 Ingress)** | **Встроенный Route** на базе HAProxy Operator с поддержкой Edge/Passthrough/Reencrypt TLS. Поддержка Gateway API (GA). | Требует самостоятельной установки Ingress Controller (Nginx Ingress, Traefik, Contour, Envoy). |
| **Интерфейс управления** | **`oc` CLI** + полнофункциональная Web Console (режимы Administrator и Developer Topology) с поддержкой OAuth. | **`kubectl` CLI**. Веб-консоль (Kubernetes Dashboard) требует отдельной установки и настройки. |
| **Мультитенантность** | **Projects**. Автоматическая изоляция, квоты, шаблоны проектов, разделение ролей и изоляция UID/GID. | **Namespaces**. Базовая логическая изоляция, требующая ручного создания RoleBinding, NetworkPolicy и ResourceQuota. |

---

### Сетевое взаимодействие в On-Premises

#### Сетевой плагин OVN-Kubernetes

OpenShift использует **OVN-Kubernetes** в качестве базового CNI-плагина:
- **Инкапсуляция трафика:** Межузловое взаимодействие подов выполняется через туннели **GENEVE (UDP-порт 6081)**.
- **Распределённая маршрутизация:** Каждый узел содержит виртуальный коммутатор Open vSwitch, обеспечивающий маршрутизацию на уровне ядра Linux без двойного NAT.
- **Egress IP:** Позволяет назначить фиксированный публичный или корпоративный IP-адрес для исходящего трафика подов определённого проекта. Критично для интеграции со старыми корпоративными межсетевыми экранами (Firewall/CheckPoint).
- **Egress Firewall (EgressNetworkPolicy):** Блокировка или разрешение доступа из подов проекта к определённым внешним IP-адресам, CIDR или DNS-доменам за пределами кластера.

#### Маршрутизация внешнего трафика: Routes и Ingress Controller

Штатный роутер OpenShift реализован на базе HAProxy. Поддерживаются следующие типы TLS-терминации:

| Режим Route | Описание | Точка терминации TLS |
| :--- | :--- | :--- |
| **Edge** | Внешний TLS-трафик расшифровывается на роутере HAProxy и передаётся в под по незашифрованному HTTP. | HAProxy Router |
| **Passthrough** | Зашифрованный TLS-трафик передаётся напрямую в под без расшифровки на роутере (SNI-маршрутизация). Требуется для mTLS и сквозного шифрования. | Контейнер приложения |
| **Reencrypt** | Трафик расшифровывается на роутере с внешним сертификатом и повторно шифруется внутренним кластерным сертификатом перед отправкой в под. | HAProxy Router + Контейнер |
| **Insecure / None** | Простой HTTP-трафик без шифрования (может настраиваться на принудительный редирект HTTP -> HTTPS). | Отсутствует |

#### User Defined Networks (UDN) и BGP на On-Premises

- **User Defined Networks (UDN):** Механизм создания изолированных L2/L3 сетей для отдельных проектов или виртуальных машин (OpenShift Virtualization), изолирующий сетевой стек тенантов на уровне контроллеров OVN.
- **BGP Integration (MetalLB / FRR-k8s):** В on-premise ЦОД без внешних облачных балансировщиков OpenShift использует MetalLB с демоном FRR для анонсирования IP-адресов сервисов типа `LoadBalancer` и Ingress VIP напрямую в коммутаторы ядра сети (ToR / Spine-Leaf) по протоколу BGP.

---

### Хранение данных в On-Premises

- **OpenShift Data Foundation (ODF):** Программно-определяемая СХД на базе Ceph, Rook и NooBaa, развёртываемая непосредственно на узлах кластера. Предоставляет:
  - `Ceph-RBD` — блочные устройства с поддержкой ReadWriteOnce (RWO) и высокой производительностью для СУБД.
  - `CephFS` — распределённая файловая система с поддержкой ReadWriteMany (RWX).
  - `NooBaa (MCG)` — S3-совместимое объектное хранилище с гибридной репликацией.
- **LVM Storage Operator (LVMO):** Оператор для динамического выделения блочных Persistent Volumes из локальных дисков (NVMe/SSD/HDD) узлов bare-metal без использования распределённых СХД.
- **Традиционные Enterprise CSI:** Поддержка интеграции с аппаратными SAN/NAS хранилищами через специализированные CSI-драйверы (iSCSI, Fibre Channel, NFS).

---

### Модель безопасности: SCC и Проекты

#### Архитектура Security Context Constraints (SCC)

OpenShift блокирует запуск привилегированных контейнеров по умолчанию. При попытке создания пода Admission Controller проверяет, какому SCC соответствует ServiceAccount пода:

1. **`restricted-v2`** (стандарт по умолчанию в OCP 4.11+):
   - Запрещает root (UID выделяется динамически из диапазона проекта).
   - Запрещает эскалацию привилегий (`allowPrivilegeEscalation: false`).
   - Сбрасывает все Linux capabilities (`drop: ["ALL"]`), разрешает добавление только `NET_BIND_SERVICE`.
   - Применяет профиль seccomp `RuntimeDefault`.
2. **`restricted`** (устаревший стандарт OCP 3.x/4.x): аналогичен restricted-v2, но допускает пустой seccomp.
3. **`nonroot`**: разрешает любой ненулевой UID (например, жестко заданный `runAsUser: 10001` в Dockerfile), не требуя попадания в диапазон проекта.
4. **`anyuid`**: разрешает запуск контейнера от UID 0 (root), но без доступа к host-ресурсам.
5. **`hostmount-anyuid`**: разрешает монтирование томов `hostPath` и запуск от любого UID.
6. **`privileged`**: снимает все ограничения (эквивалентно `docker run --privileged`). Доступен только системным сервисам.

#### Выделение UID/GID в Projects

При создании проекта OpenShift генерирует аннотации с уникальными диапазонами:
- `openshift.io/sa.scc.uid-range: 1000640000/10000` (разрешены UID от 1000640000 до 1000649999).
- `openshift.io/sa.scc.supplemental-groups: 1000640000/10000`.

---

### Методы установки в On-Premises (Без Cloud)

1. **Agent-Based Installer (ABI):** Рекомендуемый современный метод для On-Premises и Air-Gapped (изолированных) сред. Генерирует единый загрузочный образ ISO, содержащий инсталлятор, агент обнаружения оборудования и конфигурацию Ignition. Не требует отдельной bootstrap-виртуальной машины.
2. **User-Provisioned Infrastructure (UPI):** Метод, при котором системный администратор вручную подготавливает физические серверы, сеть, DNS-записи, балансировщики нагрузки (HAProxy/Keepalived) и загружает ноды по PXE/iPXE с передачей Ignition-файлов.
3. **Installer-Provisioned Infrastructure (IPI) на Bare-Metal:** Автоматизированная установка на «голое железо». Инсталлятор управляет серверами через интерфейсы IPMI / Redfish / iLO / iDRAC с использованием встроенного сервиса Ironic.

---

## Требования к ресурсам в On-Premises

| Роль узла | Минимальные ресурсы | Рекомендуемые ресурсы (Production) | Требования к дискам |
| :--- | :--- | :--- | :--- |
| **Control Plane (3 узла)** | 4 vCPU, 16 GB RAM | 8 vCPU, 32 GB RAM | Выделенный NVMe/SSD, задержка `fsync` p99 < 10 мс, минимум 120 GB |
| **Worker Nodes (от 2 узлов)** | 4 vCPU, 16 GB RAM | 16+ vCPU, 64+ GB RAM | SSD/NVMe от 120 GB (под контейнеры и образы CRI-O) |
| **ODF Storage Nodes (3 узла)** | 8 vCPU, 32 GB RAM | 16 vCPU, 64 GB RAM | Выделенные неразмеченные NVMe/SSD диски под OSD Ceph |

---

## Практические сценарии

### Предварительные требования

Перед началом работы убедитесь в наличии:
1. Доступа к кластеру OpenShift 4.14+ с правами `cluster-admin`.
2. Установленной утилиты `oc` соответствующей версии.
3. Настроенного файла `kubeconfig` (по умолчанию `~/.kube/config`).

```bash
# Проверка версии клиента и сервера
oc version
# → Client Version: 4.17.0
# → Kustomize Version: v5.4.2
# → Server Version: 4.17.0
# → Kubernetes Version: v1.30.4
```

---

### Сценарий 1: Проверка состояния кластера и ClusterOperators

Для администратора OpenShift первичная диагностика начинается не с подов, а со статуса **ClusterOperators** (`co`).

```bash
# Проверка состояния всех кластерных операторов
oc get co
# → NAME                                       VERSION   AVAILABLE   PROGRESSING   DEGRADED   SINCE
# → authentication                             4.17.0    True        False         False      45d
# → console                                    4.17.0    True        False         False      45d
# → etcd                                       4.17.0    True        False         False      45d
# → ingress                                    4.17.0    True        False         False      45d
# → kube-apiserver                             4.17.0    True        False         False      45d
# → machine-config                             4.17.0    True        False         False      45d
# → network                                    4.17.0    True        False         False      45d

# Фильтрация проблемных операторов
oc get co -o json | jq -r '.items[] | select(.status.conditions[] | select((.type=="Degraded" and .status=="True") or (.type=="Available" and .status=="False"))) | .metadata.name'
# → (Вывод пуст, если все операторы здоровы)

# Проверка узлов кластера
oc get nodes -o wide
# → NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP    OS-IMAGE
# → master-0   Ready    control-plane   45d   v1.30.4   192.168.10.11  Red Hat Enterprise Linux CoreOS 417.94...
# → master-1   Ready    control-plane   45d   v1.30.4   192.168.10.12  Red Hat Enterprise Linux CoreOS 417.94...
# → master-2   Ready    control-plane   45d   v1.30.4   192.168.10.13  Red Hat Enterprise Linux CoreOS 417.94...
# → worker-0   Ready    worker          45d   v1.30.4   192.168.10.21  Red Hat Enterprise Linux CoreOS 417.94...
# → worker-1   Ready    worker          45d   v1.30.4   192.168.10.22  Red Hat Enterprise Linux CoreOS 417.94...

# Проверка потребления ресурсов узлами
oc adm top nodes
# → NAME       CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
# → master-0   850m         10%    9120Mi          28%
# → master-1   790m         9%     8950Mi          27%
# → master-2   810m         10%    9010Mi          28%
# → worker-0   1450m        9%     24500Mi         38%
# → worker-1   1620m        10%    26100Mi         40%
```

---

### Сценарий 2: Управление проектами и правами доступа (RBAC)

```bash
# Создание нового изолированного проекта
oc new-project finance-app --description="Финансовый сервис" --display-name="Finance Core"
# → Now using project "finance-app" on server "https://api.ocp.datacenter.local:6443".

# Проверка выделенного диапазона UID/GID для проекта
oc get project finance-app -o yaml | grep -A2 "annotations:"
# → annotations:
# →   openshift.io/sa.scc.supplemental-groups: 1000720000/10000
# →   openshift.io/sa.scc.uid-range: 1000720000/10000

# Создание сервисного аккаунта для приложения
oc create serviceaccount app-runner -n finance-app
# → serviceaccount/app-runner created

# Назначение роли администратора проекта пользователю
oc adm policy add-role-to-user admin ivan.petrov -n finance-app
# → clusterrole.rbac.authorization.k8s.io/admin added: "ivan.petrov"

# Проверка назначенных ролей в пространстве имён
oc get rolebindings -n finance-app
# → NAME                    ROLE                                  AGE
# → admin                   ClusterRole/admin                     35s
# → system:image-builders   ClusterRole/system:image-builder      2m
# → system:image-pullers    ClusterRole/system:image-puller       2m
```

---

### Сценарий 3: Настройка и аудит безопасности SCC

Если контейнер стороннего приложения требует запуска от фиксированного UID (например, `1000`) или сохранения сетевых capabilities, ему назначается подходящий SCC.

```bash
# Просмотр списка системных SCC
oc get scc
# → NAME               PRIV    CAPS         SELINUX     RUNASUSER          FSGROUP     PRIORITY
# → anyuid             false   []           MustRunAs   RunAsAny           RunAsAny    10
# → hostaccess         false   []           MustRunAs   MustRunAsRange     MustRunAs   <none>
# → privileged         true    [*]          RunAsAny    RunAsAny           RunAsAny    <none>
# → restricted         false   []           MustRunAs   MustRunAsRange     MustRunAs   <none>
# → restricted-v2      false   ["NET_BIND"] MustRunAs   MustRunAsRange     MustRunAs   <none>

# Назначение SCC 'nonroot' сервисному аккаунту приложения
oc adm policy add-scc-to-user nonroot -z app-runner -n finance-app
# → clusterrole.rbac.authorization.k8s.io/system:openshift:scc:nonroot added: "system:serviceaccount:finance-app:app-runner"

# Проверка, кто имеет право использовать privileged SCC
oc adm policy who-can use scc privileged
# → Resource:  securitycontextconstraints.security.openshift.io
# → User:      system:admin
# → Groups:    system:cluster-admins
# → ServiceAccounts: openshift-sdn:sdn, openshift-multus:multus
```

---

### Сценарий 4: Настройка Ingress и публикация через Routes

#### Создание Edge Route с принудительным TLS

```yaml
# edge-route.yaml
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: finance-web
  namespace: finance-app
spec:
  host: finance.apps.datacenter.local
  to:
    kind: Service
    name: finance-web-svc
    weight: 100
  port:
    targetPort: 8080
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

```bash
# Применение Route
oc apply -f edge-route.yaml
# → route.route.openshift.io/finance-web created

# Проверка статуса маршрутизации
oc get route finance-web -n finance-app
# → NAME          HOST/PORT                       PATH   SERVICES          PORT       TERMINATION          WILDCARD
# → finance-web   finance.apps.datacenter.local          finance-web-svc   8080       edge/Redirect        None

# Проверка admission статуса маршрута роутером HAProxy
oc get route finance-web -n finance-app -o jsonpath='{.status.ingress[0].conditions[0].status}'
# → True
```

#### Тюнинг IngressController в On-Premises

Администратор может масштабировать число реплик роутера и настраивать привязку к физическим интерфейсам:

```bash
# Просмотр конфигурации IngressController по умолчанию
oc get ingresscontroller default -n openshift-ingress-operator -o yaml | grep -A5 "spec:"
# → spec:
# →   replicas: 2
# →   endpointPublishingStrategy:
# →     type: NodePortService

# Масштабирование IngressController до 3 реплик
oc patch ingresscontroller default -n openshift-ingress-operator --type=merge -p '{"spec":{"replicas":3}}'
# → ingresscontroller.operator.openshift.io/default patched
```

---

### Сценарий 5: Администрирование ОС узлов через MachineConfig (MCO)

В OpenShift параметры ядра Linux (`sysctl`), настройки службы NTP (`chronyd`) и системные лимиты применяются исключительно через `MachineConfig`.

```yaml
# 99-worker-kernel-sysctl.yaml
apiVersion: machineconfiguration.openshift.io/v1
kind: MachineConfig
metadata:
  labels:
    machineconfiguration.openshift.io/role: worker
  name: 99-worker-kernel-sysctl
spec:
  config:
    ignition:
      version: 3.2.0
    storage:
      files:
      - path: /etc/sysctl.d/99-custom-network.conf
        mode: 420
        overwrite: true
        contents:
          source: data:text/plain;charset=utf-8;base64,bmV0LmNvcmUuc29tYXhjb25uID0gNjU1MzUKbmV0LmlwdjQudGNwX21heFfc3luX2JhY2tsb2cgPSA2NTUzNQo=
```

```bash
# Применение MachineConfig к пулу worker
oc apply -f 99-worker-kernel-sysctl.yaml
# → machineconfig.machineconfiguration.openshift.io/99-worker-kernel-sysctl created

# Наблюдение за состоянием пулов узлов (MachineConfigPool)
oc get mcp
# → NAME     CONFIG                                             UPDATED   UPDATING   DEGRADED   MACHINECOUNT   READYMACHINECOUNT   UPDATEDMACHINECOUNT   DEGRADEDMACHINECOUNT
# → master   rendered-master-47f1c1f2b6e5e8e19b99008e7b165241   True      False      False      3              3                   3                     0
# → worker   rendered-worker-91a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6   False     True       False      2              1                   1                     0

# Примечание: MCO поочередно переводит ноды в cordon, выполняет drain, применяет изменения и перезагружает узел
```

---

### Сценарий 6: Day-2 обслуживание и отладка узлов RHCOS

#### Вывод узла на регламентные работы

```bash
# Блокировка планирования новых подов на узел
oc adm cordon worker-0
# → node/worker-0 cordoned

# Вытеснение подов с узла
oc adm drain worker-0 --ignore-daemonsets --delete-emptydir-data --force
# → evicting pod finance-app/finance-web-74b8686d65-g4nfx
# → node/worker-0 drained
```

#### Интерактивная отладка через `oc debug node`

Так как прямой SSH-доступ к RHCOS не рекомендуется, администраторы используют `oc debug node`, запускающий привилегированный pod с полным доступом к файловой системе хоста:

```bash
# Подключение к консоли хоста worker-0
oc debug node/worker-0
# → Starting pod/worker-0-debug ...
# → To use host binaries, run `chroot /host`

# Переход в корневую файловую систему хоста
chroot /host

# Проверка статуса сервисов kubelet и cri-o
systemctl status kubelet
# → ● kubelet.service - Kubernetes Kubelet
# →    Loaded: loaded (/etc/systemd/system/kubelet.service; enabled; vendor preset: enabled)
# →    Active: active (running) since Tue 2026-09-01 10:00:00 UTC; 45d ago

# Проверка контейнеров на уровне рантайма CRI-O
crictl ps
# → CONTAINER     IMAGE              CREATED         STATE     NAME           ATTEMPT    POD ID
# → d1f2e3a4b5c6   registry.local...  5 minutes ago   Running   finance-web    0          a1b2c3d4e5f6

# Просмотр логов рантайма
journalctl -u crio -n 50 --no-pager

# Выход из режима отладки
exit
exit
# → Removing debug pod ...
```

```bash
# Возврат узла в работу после обслуживания
oc adm uncordon worker-0
# → node/worker-0 uncordoned
```

---

### Сценарий 7: Развертывание production-workload под `restricted-v2`

```yaml
# finance-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: finance-web
  namespace: finance-app
  labels:
    app: finance-web
spec:
  replicas: 2
  selector:
    matchLabels:
      app: finance-web
  template:
    metadata:
      labels:
        app: finance-web
    spec:
      serviceAccountName: app-runner
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: web
        image: image-registry.openshift-image-registry.svc:5000/finance-app/finance-web:v1.0
        ports:
        - containerPort: 8080
          protocol: TCP
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          capabilities:
            drop:
            - ALL
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
          limits:
            cpu: 500m
            memory: 512Mi
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 10
        livenessProbe:
          httpGet:
            path: /healthz
            port: 8080
          initialDelaySeconds: 15
          periodSeconds: 20
```

```bash
# Применение манифеста
oc apply -f finance-deployment.yaml
# → deployment.apps/finance-web created

# Контроль rollout
oc rollout status deployment/finance-web -n finance-app
# → deployment "finance-web" successfully rolled out

# Проверка соответствия SCC
oc get pod -l app=finance-web -n finance-app -o jsonpath='{.items[0].metadata.annotations.openshift\.io/scc}'
# → restricted-v2
```

---

### Сценарий 8: Управление операторами через OLM в изолированном контуре (Air-Gapped)

В закрытом корпоративном контуре операторы устанавливаются из локального зеркала (Private Registry).

```yaml
# internal-subscription.yaml
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: odf-operator
  namespace: openshift-storage
spec:
  channel: stable-4.17
  name: odf-operator
  source: internal-redhat-catalog
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

```bash
# Проверка созданной подписки
oc apply -f internal-subscription.yaml
# → subscription.operators.coreos.com/odf-operator created

# Проверка статуса ClusterServiceVersion (CSV)
oc get csv -n openshift-storage
# → NAME                              DISPLAY                              VERSION   REPLACES   PHASE
# → odf-operator.v4.17.0              OpenShift Data Foundation Operator   4.17.0               Succeeded
```

---

### Сценарий 9: Резервное копирование etcd в On-Premises

OpenShift 4 предоставляет штатный скрипт резервного копирования `/usr/local/bin/cluster-backup.sh`, сохраняющий снапшот etcd и статические манифесты Control Plane.

```bash
# Запуск резервного копирования etcd через oc debug на master-узле
oc debug node/master-0 -- chroot /host /usr/local/bin/cluster-backup.sh /home/core/assets/backup
# → Starting pod/master-0-debug ...
# → Executing cluster-backup.sh ...
# → snapshot db and kube resources are successfully saved to /home/core/assets/backup!

# Проверка созданного файла снапшота на master-узле
oc debug node/master-0 -- chroot /host ls -lh /home/core/assets/backup
# → -rw-------. 1 root root 142M Sep 03 14:00 snapshot_2026-09-03_140000.db
# → -rw-------. 1 root root  45K Sep 03 14:00 static_kuberesources_2026-09-03_140000.tar.gz

# Проверка валидности снапшота etcdctl
oc debug node/master-0 -- chroot /host etcdctl --write-out=table snapshot status /home/core/assets/backup/snapshot_2026-09-03_140000.db
# → +----------+----------+------------+------------+
# → |   HASH   | REVISION | TOTAL KEYS | TOTAL SIZE |
# → +----------+----------+------------+------------+
# → | 38ac4f21 | 8519420  |      41280 |     142 MB |
# → +----------+----------+------------+------------+
```

---

## Операции и команды

Справочная таблица основных команд `oc` и `oc adm` для DevOps, SRE и системных администраторов:

| Команда | Описание | Пример использования |
| :--- | :--- | :--- |
| `oc get co` | Проверка состояния всех ClusterOperators | `oc get co` |
| `oc get mcp` | Проверка статуса пулов конфигураций MachineConfig | `oc get mcp` |
| `oc adm top nodes` | Мониторинг потребления CPU и памяти узлами | `oc adm top nodes` |
| `oc adm cordon / uncordon` | Запрет / разрешение планирования подов на узел | `oc adm cordon <node-name>` |
| `oc adm drain` | Безопасное вытеснение подов перед обслуживанием | `oc adm drain <node-name> --ignore-daemonsets --delete-emptydir-data` |
| `oc debug node/<name>` | Отладка операционной системы RHCOS в контейнере хоста | `oc debug node/master-0` |
| `oc adm policy who-can` | Аудит RBAC: определение субъектов, имеющих право на действие | `oc adm policy who-can use scc privileged` |
| `oc adm policy add-scc-to-user` | Назначение SCC сервисному аккаунту или пользователю | `oc adm policy add-scc-to-user anyuid -z my-sa -n my-ns` |
| `oc create route` | Быстрое создание L7 маршрута | `oc create route edge --service=my-svc --hostname=app.example.local` |
| `oc get clusterversion` | Просмотр текущей версии и доступных обновлений | `oc get clusterversion` |
| `oc adm upgrade` | Запуск обновления кластера до целевой версии | `oc adm upgrade --to-latest=true` |
| `oc adm must-gather` | Сбор полного диагностического архива кластера | `oc adm must-gather --dest-dir=/tmp/must-gather` |

---

## Устранение неполадок

### Систематическая диагностика SRE

При возникновении сбоев в OpenShift расследование выполняется по иерархической схеме:
1. **Состояние кластерных операторов:** `oc get co` — выявление деградировавших подсистем.
2. **Состояние узлов и пулов MCO:** `oc get nodes`, `oc get mcp`.
3. **Логи и события в пространстве имён оператора:** `oc logs -n openshift-<subsystem>` и `oc get events -n openshift-<subsystem>`.
4. **Низкоуровневая диагностика узлов:** `oc debug node/<node>` -> `journalctl -u kubelet` / `journalctl -u crio`.

---

### Анализ типовых инцидентов

#### 1. ClusterOperator перешёл в статус Degraded

**Симптом:** `oc get co` показывает `Degraded=True` для оператора (например, `machine-config` или `ingress`).

**Диагностика:**
```bash
# Детальный просмотр условий (Conditions) оператора
oc describe co machine-config | grep -A15 "Conditions:"
# → Conditions:
# →   Type         Status   Reason                Message
# →   Degraded     True     NodeUpdateDegraded    Node worker-1 failed to apply MachineConfig: timed out waiting for node reboot
# →   Available    True     AsExpected            All nodes are running expected version
# →   Progressing  False    AsExpected            Configuration is complete
```

**Решение:**
1. Определить проблемный узел: `oc get mcp` и `oc describe mcp worker`.
2. Подключиться к узлу через `oc debug node/worker-1` и проверить системные логи демона: `journalctl -u machine-config-daemon -n 100 --no-pager`.
3. В случае зависания перезагрузки проверить консоль сервера через IPMI/iLO или перезапустить службу `machine-config-daemon`.

---

#### 2. Ошибка запуска пода: `unable to validate against any security context constraint`

**Симптом:** Под находится в состоянии `FailedCreate` или Deployment не создает реплики.

**Диагностика:**
```bash
# Просмотр событий ReplicaSet
oc get events -n finance-app --sort-by='.lastTimestamp'
# → 45s Warning FailedCreate replicaset/finance-web-74b8686d65 Error creating: pods "finance-web-74b8686d65-g4nfx" is forbidden: unable to validate against any security context constraint: [provider "restricted-v2": Forbidden: not usable by user or serviceaccount, spec.containers[0].securityContext.runAsUser: Invalid value: 0: must be in the ranges: [1000720000, 1000729999]]
```

**Решение:**
1. Ошибка указывает, что контейнер пытается запуститься с `UID: 0` (root), тогда как проект разрешает диапазон `1000720000 - 1000729999`.
2. Если запуск от root не обязателен — убрать директиву `runAsUser: 0` или исправить `USER` в Dockerfile.
3. Если запуск от любого UID необходим — предоставить сервисному аккаунту SCC `anyuid`:
   ```bash
   oc adm policy add-scc-to-user anyuid -z app-runner -n finance-app
   # → clusterrole.rbac.authorization.k8s.io/system:openshift:scc:anyuid added
   ```

---

#### 3. Узел в статусе NotReady на RHCOS

**Симптом:** `oc get nodes` возвращает `worker-2 NotReady`.

**Диагностика:**
```bash
# Проверка условий узла
oc describe node worker-2 | grep -A8 "Conditions:"
# → Ready  False  KubeletNotReady  container runtime network not ready: NetworkReady=false reason:NetworkPluginNotReady message:Network plugin returns error: cni plugin not initialized

# Подключение к хосту и анализ логов CNI и OVN
oc debug node/worker-2
chroot /host
journalctl -u ovs-vswitchd -n 30 --no-pager
journalctl -u ovn-controller -n 30 --no-pager
```

**Решение:**
1. Проверить доступность GENEVE-порта 6081/UDP между узлами через сетевой межсетевой экран ЦОД.
2. Проверить заполненность дискового пространства `/var/lib/containers` и `/var/log`: `df -h`.
3. Перезапустить службу рантайма: `systemctl restart crio`.

---

#### 4. Сбор полного диагностического архива через `must-gather`

Инструмент `must-gather` запускает специальный под с набором диагностических скриптов, сохраняя дампы всех ресурсов, логи операторов, метрики и конфигурации узлов в локальную директорию:

```bash
# Базовый запуск сбора данных о кластере
oc adm must-gather --dest-dir=/var/log/ocp-must-gather-$(date +%Y%m%d)
# → [must-gather      ] OUT Using must-gather plugin-in image: .../openshift/ose-must-gather:latest
# → [must-gather      ] OUT Gathering data for ns/openshift-monitoring ...
# → [must-gather      ] OUT Gathering data for ns/openshift-kube-apiserver ...
# → [must-gather      ] OUT Done gathering data. Output is in /var/log/ocp-must-gather-20260903

# Сбор расширенных сетевых данных (OVN-Kubernetes)
oc adm must-gather --image=registry.redhat.io/openshift4/network-tools-rhel9:latest --dest-dir=/var/log/ovn-gather
```

---

### Матрица типовых проблем и решений

| Проблема / Симптом | Вероятная причина | Команда первичной диагностики | Действие по устранению |
| :--- | :--- | :--- | :--- |
| **`ImagePullBackOff` в Internal Registry** | Сервисный аккаунт не имеет роли `system:image-puller` или квота диска реестра исчерпана | `oc describe pod <pod-name>` | Проверить `oc get clusteroperator image-registry`, настроить PVC для хранилища реестра. |
| **`MachineConfigPool Degraded`** | Сбой применения конфигурации Ignition, таймаут ребута узла | `oc get mcp`, `oc describe mcp <pool>` | Подключиться через `oc debug node/<node>`, проверить `journalctl -u machine-config-daemon`. |
| **`Route Admitted: False`** | Конфликт DNS-имени маршрута, дублирование хоста в другом проекте | `oc describe route <route-name>` | Изменить `spec.host` или проверить права в IngressController (`routeAdmissionPolicy`). |
| **Высокая задержка etcd (`etcd_disk_wal_fsync_duration_seconds`)** | Медленная дисковая подсистема на master-узлах (I/O contention) | `oc -n openshift-monitoring exec prometheus-k8s-0 ...` | Перенести `/var/lib/etcd` на выделенные NVMe диски, исключить разделение SAN-LUN с тяжелыми нагрузками. |
| **`CrashLoopBackOff` в HAProxy Ingress Router** | Нехватка системных дескрипторов файлов (`sysctl fs.file-max`) или конфликт портов 80/443 | `oc logs -n openshift-ingress -l app=router` | Проверить `LimitNOFILE` в systemd роутера или увеличить реплики роутера на другие узлы. |

---

## Лучшие практики

### Безопасность и управление доступом

1. **Никогда не использовать `privileged` SCC для прикладных сервисов.** Если контейнеру требуются специфические права, назначайте гранулярные роли: `anyuid` (только для root UID без доступа к host), `nonroot` (для фиксированных ненулевых UID) или кастомный SCC с точечным добавлением `capabilities` (например, `NET_BIND_SERVICE`).
2. **Не модифицировать стандартные системные SCC.** Все обновления OpenShift перезаписывают дефолтные SCC (`restricted`, `restricted-v2`, `privileged`). Для специфических требований создавайте отдельный именованный манифест `SecurityContextConstraints`.
3. **Обязательное квотирование ресурсов в проектах.** Развёртывайте `LimitRange` и `ResourceQuota` в каждом пользовательском пространстве имён для защиты Control Plane от исчерпания памяти и CPU.

### Управление инфраструктурой и узлами (MCO)

1. **Создание выделенных `MachineConfigPool` под разные роли.** Не применяйте специфические настройки (например, Realtime-ядро, hugepages или тюнинг сети) напрямую к пулу `worker`. Создайте пул `worker-infra` или `worker-database` с селектором узлов, чтобы избежать одновременного ребута всего кластера.
2. **Приостановка обновлений пулов при регламентных работах.** Используйте `spec.paused: true` в манифесте `MachineConfigPool` перед массовым внесением изменений в `MachineConfig`, чтобы контролировать точный момент выкатки и перезагрузки узлов.

### Высокая доступность и эксплуатация etcd в On-Premises

1. **Строгая изоляция дисков etcd.** etcd крайне чувствителен к операциям записи в WAL. Размещение базы etcd на общих шпиндельных дисках (HDD) или перегруженных общих SAN LUN приводит к сбоям кворума кластера при любой высокой нагрузке. Требуются локальные NVMe/SSD диски с временем отклика `fsync` p99 < 10 мс.
2. **Автоматизация регулярного резервного копирования etcd.** Настройте кластерный `CronJob`, выполняющий `/usr/local/bin/cluster-backup.sh` не реже одного раза в сутки с ротацией и выгрузкой снапшотов на внешний защищённый сервер.

### Сетевая организация в On-Premises

1. **Использование Egress IP для внешних шлюзов.** Если поды обращаются к внешним защищённым банковским шлюзам или СУБД со строгими белыми списками IP, настраивайте `EgressIP` на уровне проекта, а не выпускайте трафик через NAT-адреса случайных рабочих узлов.
2. **Сетевая изоляция проектов через NetworkPolicy.** По умолчанию в OVN-Kubernetes поды между разными проектами имеют полную сетевую связность. Применяйте стандартную политику «запретить всё, кроме разрешённого» во всех производственных средах.

---

## Дополнительная информация

### Официальные источники

- [Официальная документация Red Hat OpenShift Container Platform](https://docs.openshift.com/)
- [Upstream проект OKD — документация и архитектура](https://docs.okd.io/)
- [Архитектура и исходный код Machine Config Operator (MCO)](https://github.com/openshift/machine-config-operator)
- [Спецификация и руководство по CRI-O](https://cri-o.io/)
- [OVN-Kubernetes Architecture and Documentation](https://github.com/ovn-org/ovn-kubernetes)

### См. также

- [Kubernetes: Обзор и ключевые концепции](./kubernetes_overview.md)
- [Container Runtime в Kubernetes](./Concepts/container_runtime.md)
- [Kubernetes-операторы: автоматизация управления приложениями](./Concepts/kubernetes_operators.md)
