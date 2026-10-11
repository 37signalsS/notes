# Kubespray: Установка — Основные концепции

## Определения

**Машина управления (Control Node)** — узел (физический сервер, виртуальная машина или контейнер), с которого инициируется процесс развертывания через Ansible. Требует наличия Python 3.10+, установленного Ansible и SSH-доступа к целевым узлам по ключам.

**Целевые узлы (Target Nodes)** — серверы, на которые развертываются компоненты Kubernetes. В рамках Kubespray узлы классифицируются по ролям:
- **Control Plane** — управление состоянием кластера (API-сервер, Scheduler, Controller Manager).
- **Worker** — запуск пользовательских контейнерных нагрузок.
- **etcd** — распределенное хранилище состояния кластера (могут быть совмещены с Control Plane или выделены на отдельные узлы для повышения производительности).

**Основные термины Kubespray** — детальное описание Inventory, Group vars, Playbooks, Become, CRI, Kubeadm и других терминов доступно в разделе **[Определения](./definitions.md)**.

---

## Основные концепции

### Логика работы

Kubespray является высокоуровневой автоматизированной оберткой над инструментом [kubeadm](../kubeadm/index.md), дополняя его возможностями по глубокой настройке ОС, сети и хранилищ.

1. **Идемпотентность:** плейбуки спроектированы так, что их повторный запуск приводит систему к целевому состоянию без нежелательных изменений, если текущее состояние уже соответствует описанному. Это достигается за счет проверки текущего состояния каждого ресурса перед применением изменений.
2. **Декларативность:** вся конфигурация кластера (версии компонентов, параметры CNI, runtime) описывается в YAML-файлах `group_vars`. Это позволяет хранить настройки в Git и реализовывать GitOps-подходы для инфраструктуры.
3. **Модульность:** гибкий выбор компонентов (Container Runtime, сетевые плагины, DNS, балансировщики) путем переопределения переменных без изменения кода самих ролей. Каждый компонент управляется отдельным Ansible-ролем, что позволяет включать или отключать их независимо.

### Архитектурные требования

- **Сетевая связность:** машина управления должна иметь устойчивый SSH-доступ ко всем узлам кластера. Между целевыми узлами должна быть обеспечена полная связность (см. требования к портам в документации). Сетевые задержки между узлами etcd не должны превышать 10 мс — это критично для стабильности кворума.
- **Привилегии:** выполнение задач на целевых узлах требует прав `root` (механизм `become` в Ansible). Рекомендуется настройка `sudo NOPASSWD` для пользователя автоматизации, чтобы избежать запросов пароля при каждом запуске плейбука.
- **Cgroups v2:** современные версии Kubespray ориентированы на использование Cgroup v2. Для старых дистрибутивов может потребоваться дополнительная настройка параметров ядра (параметр загрузки GRUB `systemd.unified_cgroup_hierarchy=1`).
- **Соответствие версий:** версии Kubespray, Ansible и Kubernetes жестко связаны. Актуальные требования зафиксированы в `requirements.txt` репозитория. Использование несовместимых версий приводит к ошибкам на этапе инициализации kubeadm.
- **Синхронизация времени (NTP):** критически важна для etcd. Распределенное хранилище чувствительно к разнице во времени между узлами; значительный дрейф часов приводит к потере кворума. Рекомендуется использование `chrony` или `systemd-timesyncd`.
- **Имена узлов (Hostname):** каждый узел должен иметь уникальное, стабильное имя хоста, которое не меняется после перезагрузки. Kubespray использует hostname для идентификации узлов в API Kubernetes. Рекомендуется FQDN-формат (например, `node-1.example.com`).

### Порядок выполнения плейбуков

Плейбук `cluster.yml` выполняется как последовательность plays с разными целевыми группами хостов. Порядок (Kubespray v2.30.0, `playbooks/cluster.yml`):

| # | Play | Целевые хосты | Что выполняется |
| :--- | :--- | :--- | :--- |
| 1 | `boilerplate.yml` | all | Общие проверки и предварительные задачи |
| 2 | `internal_facts.yml` | all | Сбор Ansible facts |
| 3 | Prepare for etcd install | `k8s_cluster:etcd` | Роли `kubespray_defaults`, `kubernetes/preinstall`, `container-engine`, `download` |
| 4 | Install etcd (`install_etcd.yml`) | `k8s_cluster:etcd` | Развертывание etcd |
| 5 | Install Kubernetes nodes | `k8s_cluster` | Роль `kubernetes/node` (настройка узлов, модули ядра) |
| 6 | Install the control plane | `kube_control_plane` | Роли `kubernetes/control-plane`, `kubernetes/client`, `kubernetes-apps/cluster_roles` |
| 7 | Invoke kubeadm and install a CNI | `k8s_cluster` | Роли `kubernetes/kubeadm`, `node-label`, `node-taint`, `kubernetes-apps/common_crds`, `network_plugin` |
| 8 | Install Calico Route Reflector | `calico_rr` | Route Reflector (только если используется) |
| 9 | Patch Kubernetes for Windows | `kube_control_plane[0]` | Патчи для Windows-узлов |
| 10 | Install Kubernetes apps | `kube_control_plane` | `external_cloud_controller`, `policy_controller`, `ingress_controller`, `external_provisioner`, `kubernetes-apps` |
| 11 | Apply resolv.conf changes | `k8s_cluster` | Роль `kubernetes/preinstall` (тег `dns_late`) |

Знание порядка полезно для диагностики: ошибка в play 3 (подготовка etcd) блокирует все последующие этапы, а ошибка в play 7 (kubeadm) означает, что etcd уже работает, но control plane не инициализирован.

### Модель запуска компонентов

Компоненты кластера запускаются двумя способами:

- **systemd-сервисы:** `kubelet` — на **каждом** узле кластера (и control plane, и workers); `etcd` — при схеме `etcd_deployment_type: host` (по умолчанию) также как systemd-сервис. Проверка: `systemctl is-active kubelet etcd`.
- **Статические поды (через CRI):** `kube-apiserver`, `kube-scheduler`, `kube-controller-manager` запускаются kubelet'ом как статические поды из манифестов в `/etc/kubernetes/manifests/`. Проверка: `kubectl get pods -n kube-system` или `sudo crictl pods`.

Control plane-узлы получают taint `node-role.kubernetes.io/control-plane:NoSchedule` (поведение `kubeadm init` по умолчанию с Kubernetes 1.24), поэтому пользовательские поды по умолчанию не планируются на мастерах.

### Сетевые порты

Для корректной работы кластера необходимо открыть следующие порты между узлами:

| Порт | Протокол | Назначение | Между какими узлами |
| :--- | :--- | :--- | :--- |
| **6443** | TCP | Kubernetes API Server | Control Plane <-> Все узлы |
| **2379-2380** | TCP | etcd client & peer | Control Plane (etcd) <-> Control Plane |
| **10250** | TCP | kubelet API | Control Plane <-> Worker |
| **10251** | TCP | kube-scheduler | Control Plane <-> Control Plane |
| **10252** | TCP | kube-controller-manager | Control Plane <-> Control Plane |
| **30000-32767** | TCP | NodePort Services | Внешний доступ к Service |
| **4789** | UDP | VXLAN (Calico/Flannel) | Между всеми узлами (CNI) |
| **8472** | UDP | VXLAN (Cilium) | Между всеми узлами (CNI) |

> [!IMPORTANT]
> Точные порты зависят от выбранного CNI-плагина. При использовании Calico с BGP потребуются дополнительные порты для BGP-сессий (179/tcp). Актуальный список — в [Kubernetes Ports and Protocols](https://kubernetes.io/docs/reference/networking/ports-and-protocols/).

---

## Практические сценарии

### Требования к инфраструктуре

#### Узлы кластера (Target Nodes)

| Параметр | Требование | Примечание |
| :--- | :--- | :--- |
| **ОС** | Ubuntu 22.04/24.04, Debian 11/12, Rocky 8/9, RHEL 8/9 | Поддержка актуальных дистрибутивов Linux |
| **Память** | 2 ГБ RAM (Worker), 4 ГБ+ RAM (Control Plane) | Минимум для стабильной работы etcd |
| **Ядра** | Минимум 2 vCPU | Требование kubeadm |
| **Диск** | 50 ГБ+ (SSD рекомендуется для etcd) | etcd чувствителен к задержкам ввода/вывода |
| **Сеть** | IPv4 / Dual-stack | Отключенный Firewall или открытые порты (см. таблицу выше) |
| **Безопасность** | SELinux: `permissive`, SWAP: **отключен** | Критично для Kubelet |
| **NTP** | `chrony` или `systemd-timesyncd` | Разница во времени не более 1–2 секунд |

#### Машина управления (Control Node)

- **Python 3.10+** и менеджер пакетов `pip`.
- **Ansible 2.14+** (строго согласно `requirements.txt`).
- **SSH-ключи:** настроенный доступ без пароля ко всем узлам.
- **Рекомендуется:** отдельная машина или VM, не входящая в состав кластера (для изоляции Control Node от рабочих нагрузок).

### Подготовка узлов

Перед запуском Kubespray рекомендуется выполнить базовую подготовку (подробно в **[Подготовке узлов](../../HA_Cluster_Bare_Metal/k8s_ha_node_preparation.md)**):

1. **Модули ядра:**
   ```bash
   # Загрузка необходимых модулей
   sudo modprobe overlay
   sudo modprobe br_netfilter

   # Модули для IPVS (опционально, но рекомендуется для production)
   sudo modprobe ip_vs
   sudo modprobe ip_vs_rr
   sudo modprobe ip_vs_wrr
   sudo modprobe ip_vs_sh
   sudo modprobe nf_conntrack

   # Автозагрузка модулей при перезагрузке
   cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
   overlay
   br_netfilter
   ip_vs
   ip_vs_rr
   ip_vs_wrr
   ip_vs_sh
   nf_conntrack
   EOF
   ```

2. **Параметры sysctl:**
   ```bash
   cat <<EOF | sudo tee /etc/sysctl.d/99-kubernetes.conf
   net.bridge.bridge-nf-call-iptables  = 1
   net.bridge.bridge-nf-call-ip6tables = 1
   net.ipv4.ip_forward                 = 1

   # Увеличение лимитов для inotify (важно для узлов с большим количеством подов)
   fs.inotify.max_user_instances = 512
   fs.inotify.max_user_watches   = 524288

   # Параметры безопасности и стабильности
   kernel.panic                  = 10
   kernel.panic_on_oops          = 1
   net.ipv4.conf.all.rp_filter   = 1
   EOF

   sudo sysctl --system
   ```

3. **Отключение SWAP:**
   ```bash
   sudo swapoff -a
   sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab
   # Проверка: free -m | grep Swap → Swap: 0 0 0
   ```

4. **Проверка cgroups v2:**
   ```bash
   stat -fc %T /sys/fs/cgroup
   # → cgroup2fs — OK
   # → tmpfs — необходимо включить в GRUB: systemd.unified_cgroup_hierarchy=1
   ```

### Настройка SSH-доступа и проверка связности

Kubespray подключается к узлам по SSH. Необходимо убедиться в работоспособности подключения перед запуском плейбуков.

1. **Генерация SSH-ключей** (если ключей еще нет):
   ```bash
   ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_kubespray
   ```

2. **Дистрибуция ключей на все узлы:**
   ```bash
   for host in 10.128.0.10 10.128.0.11 10.128.0.12 10.128.0.20 10.128.0.21; do
     ssh-copy-id -i ~/.ssh/id_kubespray.pub user@$host
   done
   ```

3. **Проверка подключения:**
   ```bash
   for host in 10.128.0.10 10.128.0.11 10.128.0.12 10.128.0.20 10.128.0.21; do
     ssh -i ~/.ssh/id_kubespray user@$host "hostname && uptime"
   done
   ```

4. **Проверка прав sudo** (должен работать без запроса пароля):
   ```bash
   ssh -i ~/.ssh/id_kubespray user@$host "sudo whoami"
   # → root
   ```

### Алгоритм развертывания

1. **Подготовка окружения (venv):**
   ```bash
   python3 -m venv venv && source venv/bin/activate
   pip install -U pip
   pip install -r requirements.txt
   ```

2. **Клонирование репозитория:**
   ```bash
   git clone --branch v2.31.0 --single-branch https://github.com/kubernetes-sigs/kubespray.git
   cd kubespray
   ```

3. **Конфигурация инвентаря:**
   ```bash
   cp -rfp inventory/sample inventory/my_cluster
   IPS=(10.128.0.10 10.128.0.11 10.128.0.12 10.128.0.20 10.128.0.21)
   CONFIG_FILE=inventory/my_cluster/hosts.yaml python3 contrib/inventory_builder/inventory.py ${IPS[@]}
   ```

4. **Настройка переменных:** Редактирование файлов в `inventory/my_cluster/group_vars/` (сеть, версии, аддоны).

5. **Проверка связности перед запуском:**
   ```bash
   ansible-playbook -i inventory/my_cluster/hosts.yaml cluster.yml --become --tags download -l all
   ```

6. **Запуск развертывания:**
   ```bash
   ansible-playbook -i inventory/my_cluster/hosts.yaml --become cluster.yml
   ```

7. **Валидация:**
   ```bash
   kubectl get nodes
   # → node1 Ready control-plane ...

   kubectl get pods -n kube-system
   # → Все поды в статусе Running

   kubectl cluster-info
   # → Kubernetes control plane is running at https://...
   ```

### Диагностика типичных ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `UNREACHABLE!` при подключении по SSH | Нет SSH-доступа или ключ не настроен | Проверьте SSH-ключи и права доступа: `ssh user@host` |
| `Missing sudo password` | Не настроен `NOPASSWD` для sudo | Добавьте в `/etc/sudoers.d/`: `user ALL=(ALL) NOPASSWD:ALL` |
| `Module failure` при установке пакетов | Несовместимая версия ОС или отсутствие репозитория | Проверьте поддержку ОС в матрице совместимости Kubespray |
| `etcd cluster is unavailable` | etcd не запущен или повреждены данные | Проверьте статус etcd на всех узлах: `systemctl status etcd` |
| `The connection to the server was refused` | API-сервер не запущен или порт 6443 закрыт | Проверьте: `systemctl status kubelet`, `ss -tlnp | grep 6443` |
| `unable to recognize`: no matches | CNI не установлен или не настроен | Убедитесь, что CNI-плагин выбран в `group_vars` и образы скачаны |
| Поды CoreDNS в `Pending` | CNI не работает или нет IP-адресов для подов | Проверьте CNI: `kubectl get pods -n kube-system -l k8s-app=calico-node` |

> [!TIP]
> При повторном запуске Kubespray автоматически определяет, какие задачи уже выполнены (идемпотентность). Повторный запуск безопасен и не приведет к потере данных.

---

## Дополнительная информация

### См. также
- **[Определения](./definitions.md)** — глоссарий терминов и описание плейбуков.
- **[Практические сценарии](./practical_scenarios.md)** — пошаговое руководство по развертыванию.
- **[Обзор Kubespray](../overview.md)** — архитектурные возможности и матрица совместимости.
- **[Подготовка узлов](../../HA_Cluster_Bare_Metal/k8s_ha_node_preparation.md)** — детальный гайд по настройке ОС.

### Внешние ресурсы
- [Official Kubespray Documentation](https://kubespray.io/)
- [Kubernetes Ports and Protocols](https://kubernetes.io/docs/reference/networking/ports-and-protocols/)
