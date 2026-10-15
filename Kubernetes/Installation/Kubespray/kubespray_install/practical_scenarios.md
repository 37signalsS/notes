# Kubespray: Установка — Практические сценарии

## Определения

**Сценарий развертывания** — последовательность операций по подготовке инфраструктуры, конфигурации Ansible и запуску плейбуков для создания или изменения кластера Kubernetes.

**Кастомизация (Customization)** — адаптация параметров Kubespray (через `group_vars`) под требования безопасности, сетевой топологии или специфических версий компонентов.

**Inventory Builder** — встроенный инструмент Kubespray (`contrib/inventory_builder/inventory.py`) для автоматической генерации файла `hosts.yaml` на основе списка IP-адресов.

**Day 0/1/2 Operations** — классификация этапов жизненного цикла: подготовка (Day 0), развертывание (Day 1) и обслуживание/масштабирование/обновление (Day 2).

**Теги (Tags)** — механизм Ansible для точечного запуска отдельных ролей внутри плейбука (например, `--tags=certificates` запускает только ротацию сертификатов).

**Переменные окружения (Extra Vars)** — параметры, передаваемые через `-e key=value` при запуске плейбука. Имеют наивысший приоритет среди всех переменных Kubespray.

---

## Основные концепции

### Жизненный цикл управления

Практическая работа с Kubespray не ограничивается разовой установкой и делится на этапы:

1.  **Подготовка (Day 0):** Настройка Control Node, проверка SSH-доступа, выбор сетевого плагина и CRI.
2.  **Развертывание (Day 1):** Инициализация кластера через `cluster.yml`.
3.  **Эксплуатация (Day 2):** Добавление узлов (`scale.yml`), удаление узлов (`remove-node.yml`), обновление версии (`upgrade-cluster.yml`) и ротация сертификатов.

Операции Day 2 подробно описаны в **[Управлении кластером](../cluster_management.md)**.

### Принцип декларативности

Любое изменение в кластере должно начинаться с изменения кода (инвентаря или переменных) и завершаться запуском соответствующего плейбука. Прямая модификация узлов через `kubectl` или SSH без отражения в Ansible-конфигурации нарушает принцип идемпотентности.

### Идемпотентность повторных запусков

Kubespray проектировался для безопасного повторного запуска. Если кластер уже соответствует описанному состоянию, плейбук не внесет изменений. Это означает:
- Повторный `cluster.yml` не переустановит компоненты, если они уже настроены корректно.
- Проверяйте выполнение через `--check` (dry-run) перед реальным запуском в production.
- Используйте теги для точечного воздействия на конкретные компоненты без полного перезапуска.

---

## Практические сценарии

### 1. Подготовка окружения и зависимостей (Control Node)

#### Цель

Настроить машину управления (Control Node) с Ansible и Python-зависимостями Kubespray.

#### Предусловия

- ОС Ubuntu 22.04/24.04 (или совместимый дистрибутив).
- Доступ к публичным репозиториям пакетов (или настроенный локальный зеркало для offline-режима).
- Права `sudo` на Control Node.

#### Пошаговая инструкция

1.  **Установка системных пакетов:**
    ```bash
    sudo apt update && sudo apt install -y \
      git python3-pip python3-venv software-properties-common
    ```

2.  **Клонирование репозитория и настройка venv:**
    ```bash
    git clone https://github.com/kubernetes-sigs/kubespray.git
    cd kubespray
    git checkout v2.28.0  # Используйте стабильную версию, соответствующую нужной версии K8s
    python3 -m venv venv
    source venv/bin/activate
    pip install -U pip
    pip install -r requirements.txt
    ```

3.  **Проверка версий (ожидаемый результат):**
    ```bash
    ansible --version
    # → ansible [core 2.16.x]

    python3 --version
    # → Python 3.12.x
    ```

#### Ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `ModuleNotFoundError: No module named 'pkg_resources'` | Устаревший pip или отсутствие `setuptools` | `pip install setuptools` |
| `ERROR! the role 'xxx' was not found` | Несовместимая версия Kubespray и Ansible | Используйте версию из `requirements.txt` |

---

### 2. Настройка инвентаря и SSH-доступа

#### Цель

Создать inventory-файл и убедиться в работоспособности SSH-соединения со всеми узлами.

#### Предусловия

- IP-адреса всех узлов кластера (Control Plane, Worker, etcd).
- SSH-ключ (`ed25519` рекомендуется) с правами `sudo` на целевых узлах.
- Установленные Python и pip на всех целевых узлах.

#### Пошаговая инструкция

1.  **Генерация SSH-ключа и дистрибуция:**
    ```bash
    ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_kubespray
    # Копирование на все узлы (включая masters, workers, etcd)
    for host in 10.128.0.10 10.128.0.11 10.128.0.12 10.128.0.13; do
      ssh-copy-id -i ~/.ssh/id_kubespray.pub user@${host}
    done
    ```

2.  **Автоматическая генерация инвентаря:**
    ```bash
    cp -rfp inventory/sample inventory/my_cluster
    IPS=(10.128.0.10 10.128.0.11 10.128.0.12 10.128.0.13)
    CONFIG_FILE=inventory/my_cluster/hosts.yaml \
      python3 contrib/inventory_builder/inventory.py ${IPS[@]}
    ```

3.  **Проверка SSH-доступа:**
    ```bash
    ansible -i inventory/my_cluster/hosts.yaml all -m ping --become
    # → 10.128.0.10 | SUCCESS => { "changed": false, "ping": "pong" }
    # → 10.128.0.11 | SUCCESS => { "changed": false, "ping": "pong" }
    # → ...
    ```

4.  **Верификация структуры инвентаря:**
    ```bash
    cat inventory/my_cluster/hosts.yaml
    # → all:
    # →   hosts:
    # →     node1:
    # →       ansible_host: 10.128.0.10
    # →     node2:
    # →       ansible_host: 10.128.0.11
    # →     ...
    # →   children:
    # →     kube_control_plane:
    # →       hosts:
    # →         node1:
    # →     kube_node:
    # →       hosts:
    # →         node2:
    # →         node3:
    # →     etcd:
    # →       hosts:
    # →         node1:
    ```

#### Автоматическое назначение ролей

Inventory Builder назначает роли по порядку: первый узел — Control Plane + etcd, остальные — Worker. Если нужно изменить роли вручную, отредактируйте `hosts.yaml` и переместите узлы между группами.

---

### 3. Конфигурация сетевых плагинов (CNI)

#### Цель

Выбрать и настроить CNI-плагин в `inventory/my_cluster/group_vars/k8s_cluster/k8s-cluster.yml`.

#### Сравнение плагинов

| Плагин | Метод | Особенности | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Calico** | VXLAN/BGP | NetworkPolicy, BGP-маршрутизация, GlobalNetworkPolicy | Production, нужна NetworkPolicy |
| **Cilium** | eBPF | Высокая производительность, замена kube-proxy, L7-политики | Современные ядра (5.10+), eBPF |
| **Flannel** | VXLAN | Простая настройка, только L3 | Dev/тест, простые сценарии |

#### Сценарий: Calico (BGP)

```yaml
# inventory/my_cluster/group_vars/k8s_cluster/k8s-cluster.yml
kube_network_plugin: calico
calico_network_backend: "bird"   # BGP-режим (требует поддержки BGP в сети)
# calico_network_backend: "vxlan"  # VXLAN-режим (если BGP запрещен)

# Диапазоны CIDR (не пересекаются с диапазонами подов/сервисов хостов)
kube_pods_subnet: 10.233.64.0/18
kube_service_subnet: 10.233.0.0/18
```

#### Сценарий: Cilium (eBPF)

```yaml
# inventory/my_cluster/group_vars/k8s_cluster/k8s-cluster.yml
kube_network_plugin: cilium
cilium_version: "v1.16.5"
cilium_kube_proxy_replacement: true     # Полная замена kube-proxy
cilium_enable_prometheus: true          # Метрики для Prometheus
cilium_hubble_enabled: true             # Наблюдаемость сети
```

> [!IMPORTANT]
> Cilium требует ядра Linux 5.10+ и включенную поддержку eBPF. Проверьте: `grep CONFIG_BPF /boot/config-$(uname -r)`.

#### Сценарий: Flannel (простая сеть)

```yaml
# inventory/my_cluster/group_vars/k8s_cluster/k8s-cluster.yml
kube_network_plugin: flannel
flannel_network_backend: "vxlan"
```

> [!NOTE]
> Flannel не поддерживает NetworkPolicy. Если политики сетевого доступа необходимы, выбирайте Calico или Cilium.

---

### 4. Первичная верификация кластера после установки

#### Цель

Убедиться, что кластер развернут корректно и все системные компоненты работают.

#### Предусловия

- Успешно завершенный плейбук `cluster.yml`.
- Установлен `kubectl` на Control Node (или доступ через `admin.conf`).

#### Пошаговая инструкция

1.  **Проверка узлов:**
    ```bash
    kubectl get nodes -o wide
    # → NAME     STATUS   ROLES           AGE   VERSION   INTERNAL-IP   ...
    # → node-1   Ready    control-plane   10m   v1.35.4   10.128.0.10   ...
    # → node-2   Ready    <none>          10m   v1.35.4   10.128.0.11   ...
    # → node-3   Ready    <none>          10m   v1.35.4   10.128.0.12   ...
    ```
    **Ожидаемый результат:** все узлы в статусе `Ready`. Статус `NotReady` указывает на проблему с CNI или kubelet.

2.  **Проверка системных подов:**
    ```bash
    kubectl get pods -n kube-system -o wide
    # → NAME                                       READY   STATUS    RESTARTS   AGE
    # → coredns-668f9bd67b-xxxxx                   1/1     Running   0          10m
    # → kube-apiserver-node-1                      1/1     Running   0          10m
    # → kube-controller-manager-node-1             1/1     Running   0          10m
    # → kube-scheduler-node-1                      1/1     Running   0          10m
    # → kube-proxy-xxxxx                           1/1     Running   0          10m
    # → kube-proxy-yyyyy                           1/1     Running   0          10m
    # → calico-node-xxxxx                          2/2     Running   0          10m  # (или cilium/flannel)
    # → calico-kube-controllers-668f9bd67b-zzzzz   1/1     Running   0          10m
    # → etcd-node-1                                1/1     Running   0          10m
    ```

3.  **Проверка DNS-резолвинга:**
    ```bash
    kubectl run dns-test --image=busybox:1.36 --restart=Never --rm -it -- nslookup kubernetes.default
    # → Server:    10.233.0.10
    # → Name:      kubernetes.default.svc.cluster.local
    # → Address:   10.233.0.1
    ```

4.  **Проверка версии API-сервера:**
    ```bash
    kubectl version --short
    # → Client Version: v1.35.4
    # → Server Version: v1.35.4
    ```

#### Типовые проблемы после установки

| Симптом | Вероятная причина | Диагностика |
| :--- | :--- | :--- |
| Узел `NotReady` | CNI не установлен или ошибки сети | `kubectl describe node <name>` → Conditions → NetworkUnavailable |
| CoreDNS CrashLoopBackOff | Проблема с сетью или ресурсами | `kubectl logs -n kube-system coredns-xxx` |
| API Server не отвечает | etcd недоступен или ошибки TLS | `sudo crictl ps -a` → проверка etcd-подов |

---

### 5. Установка и проверка аддонов

#### Цель

Установить базовые аддоны (Metrics Server, MetalLB) и убедиться в их работоспособности.

#### Предусловия

- Кластер в статусе `Ready` (см. сценарий 4).
- Доступ к публичным реестрам образов (или настроенный локальный Harbor).

#### Установка Metrics Server

Metrics Server необходим для `kubectl top` и Horizontal Pod Autoscaler (HPA).

1.  **Включение в `addons.yml`:**
    ```yaml
    # inventory/my_cluster/group_vars/k8s_cluster/addons.yml
    metrics_server_enabled: true
    ```

2.  **Запуск обновления кластера для применения:**
    ```bash
    ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
      cluster.yml --tags=addons
    ```

3.  **Проверка:**
    ```bash
    kubectl top nodes
    # → NAME     CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
    # → node-1   125m         6%     1024Mi          25%
    # → node-2   89m          4%     876Mi           21%
    ```

#### Установка MetalLB (bare-metal LoadBalancer)

MetalLB предоставляет внешние IP-адреса для Service типа `LoadBalancer` в bare-metal средах.

1.  **Включение в `addons.yml`:**
    ```yaml
    # inventory/my_cluster/group_vars/k8s_cluster/addons.yml
    metallb_enabled: true
    metallb_speaker_enabled: true
    metallb_ip_range: "10.128.0.200-10.128.0.250"  # Диапазон внешних IP
    ```

2.  **Запуск:**
    ```bash
    ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
      cluster.yml --tags=addons
    ```

3.  **Проверка (создайте тестовый Service):**
    ```bash
    kubectl create deployment nginx --image=nginx:latest --replicas=2
    kubectl expose deployment nginx --port=80 --type=LoadBalancer

    kubectl get svc nginx
    # → NAME    TYPE           CLUSTER-IP     EXTERNAL-IP     PORT(S)        AGE
    # → nginx   LoadBalancer   10.233.0.100   10.128.0.200   80:3xxxx/TCP   30s
    ```

> [!NOTE]
> Дополнительные аддоны (Ingress-NGINX, cert-manager, Dashboard) описаны в **[Примерах конфигураций](../examples.md)**.

---

### 6. Настройка доступа и управление kubeconfig

#### Цель

Настроить доступ к кластеру через `kubectl` на нескольких машинах и управлять контекстами.

#### Получение kubeconfig

```bash
# Копирование admin.conf с Control Node на локальную машину
scp user@10.128.0.10:/etc/kubernetes/admin.conf ~/.kube/config

# Или, если kubeconfig_localhost=true в group_vars:
cp inventory/my_cluster/artifacts/admin.conf ~/.kube/config
chmod 600 ~/.kube/config
```

#### Управление несколькими кластерами

```bash
# Переименование текущего контекста
kubectl config rename-context $(kubectl config current-context) prod-cluster

# Добавление второго кластера
scp user@10.128.0.20:/etc/kubernetes/admin.conf ~/.kube/dev-cluster.yaml
kubectl config --kubeconfig=~/.kube/dev-cluster.yaml rename-context \
  $(kubectl config --kubeconfig=~/.kube/dev-cluster.yaml current-context) dev-cluster

# Переключение между кластерами
export KUBECONFIG=~/.kube/config:~/.kube/dev-cluster.yaml
kubectl config get-contexts -o name
# → prod-cluster
# → dev-cluster

kubectl config use-context dev-cluster
```

#### Проверка доступа

```bash
kubectl cluster-info
# → Kubernetes control plane is running at https://10.128.0.10:6443
# → CoreDNS is running at https://10.128.0.10:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy

kubectl auth can-i get nodes
# → yes

kubectl auth can-i create deployments --as=system:anonymous
# → no
```

> [!IMPORTANT]
> Файл `admin.conf` содержит root-доступ к кластеру. Храните его с правами `600` и никогда не коммитьте в Git. Подробности — в **[Дополнительной информации](./additional_info.md)**.

---

### 7. Проверка сертификатов и плановая ротация

#### Цель

Убедиться, что сертификаты компонентов валидны и запланировать ротацию до истечения.

#### Проверка сроков действия

```bash
# На любом Control Plane узле
sudo kubeadm certs check-expiration
# → CERTIFICATE                EXPIRES                  RESIDUAL TIME   ...
# → admin.conf                 Dec 30, 2026 23:59 UTC   364d
# → apiserver                  Dec 30, 2026 23:59 UTC   364d
# → apiserver-kubelet-client   Dec 30, 2026 23:59 UTC   364d
# → front-proxy-client         Dec 30, 2026 23:59 UTC   364d
# → etcd/healthcheck-client    Dec 30, 2026 23:59 UTC   364d
# → ...
```

#### Плановая ротация через Kubespray

Если до истечения сертификатов осталось менее 30 дней, выполните ротацию:

```bash
# Ротация всех сертификатов + kubeadm-конфигурации
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml --tags=certificates,kubeadm
```

#### Ротация только etcd-сертификатов

```bash
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml --tags=etcd
```

> [!NOTE]
> При обновлении Kubernetes через `upgrade-cluster.yml` сертификаты продлеваются автоматически. Ручная ротация нужна только между обновлениями версий. Подробности — в **[Управлении сертификатами](../../Operations/certificate_management.md)**.

---

### 8. Резервное копирование etcd перед обновлением

#### Цель

Создать снапшот etcd перед risky-операциями (обновление версии, ротация CA, масштабирование Control Plane).

#### Создание снапшота

```bash
# На любом Control Plane узле
sudo ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-$(date +%Y%m%d-%H%M).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key

# Проверка целостности
sudo ETCDCTL_API=3 etcdctl snapshot status /backup/etcd-20260831-1200.db -w table
# → +---------+----------+------------+------------+--------------+
# │ DB SIZE | FRAGS    │ DB SIZE IN │ VERSION    │ TABLE KEYS   │
# +---------+----------+------------+------------+--------------+
# │ 5.0 MB  │ 0        │ 5242880    │ 3.5.x      │ 42           │
# +---------+----------+------------+------------+--------------+
```

#### Автоматизация по расписанию

```bash
# Ежедневный бэкап с очисткой старше 7 дней
echo "0 2 * * * root ETCDCTL_API=3 etcdctl snapshot save /backup/etcd-\$(date +\\%Y\\%m\\%d-\\%H\\%M).db \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
  && find /backup -name 'etcd-*.db' -mtime +7 -delete" | sudo tee /etc/cron.d/etcd-backup
```

#### Восстановление из снапшота

Восстановление требует остановки Control Plane. Полная процедура описана в **[Дополнительной информации](./additional_info.md)** и **[etcd: практические сценарии](../../../Concepts/etcd_operations.md)**.

---

### 9. Переменные окружения и теги (Продвинутый Ansible)

#### Цель

Использовать `-e` для временного переопределения переменных и теги для точечного запуска ролей.

#### Переопределение переменных через `-e`

```bash
# Установка конкретной версии Kubernetes без изменения group_vars
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml -e "kube_version=v1.35.4"

# Временное включение метрик
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml -e "metrics_server_enabled=true"

# Комбинирование нескольких переменных
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml -e "kube_version=v1.35.4" -e "calico_network_backend=bird"
```

> [!IMPORTANT]
> Переменные `-e` имеют наивысший приоритет и перезаписывают все остальные источники. Используйте их для тестирования, но не для долгосрочных изменений — для этого редактируйте `group_vars`.

#### Использование тегов

Теги позволяют запустить только определенные роли внутри плейбука:

```bash
# Только скачивание образов (подготовка к offline-установке)
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml --tags=download

# Только настройка CNI (без перезапуска Control Plane)
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml --tags=network

# Только аддоны (Metrics Server, MetalLB и др.)
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml --tags=addons

# Исключение тега (все кроме etcd)
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml --skip-tags=etcd
```

#### Dry-run (проверка без изменений)

```bash
ansible-playbook -i inventory/my_cluster/hosts.yaml --become \
  cluster.yml --check --diff
# → Показывает, какие изменения были бы применены, без реального выполнения
```

### 10. Preflight-проверка узлов перед установкой

#### Цель

Проверить соответствие узлов требованиям Kubernetes (ОС, Python, swap, модули ядра, IP-forwarding) до запуска `cluster.yml`, чтобы не обнаруживать проблемы на середине развертывания.

#### Плейбук проверки

Kubespray не включает отдельный preflight-плейбук, но паттерн проверки — Ansible `command` с `register` и `assert`:

```yaml
# playbooks/preflight.yml (кастомный плейбук)
- name: Preflight checks
  hosts: k8s_cluster
  become: true
  gather_facts: true
  tasks:
    - name: Check active swap devices
      command: swapon --show
      register: active_swap
      changed_when: false

    - name: Assert base prerequisites
      ansible.builtin.assert:
        that:
          - ansible_system == "Linux"
          - ansible_distribution in ["Ubuntu", "Debian"]
          - ansible_python_version is version("3", ">=")
          - active_swap.stdout == ""

    - name: Gather loaded kernel modules
      command: lsmod
      register: lsmod_output
      changed_when: false

    - name: Set loaded modules fact
      ansible.builtin.set_fact:
        loaded_modules: "{{ lsmod_output.stdout_lines | map('regex_replace', '^(\\S+).*', '\\1') | list }}"

    - name: Assert required kernel modules
      ansible.builtin.assert:
        that:
          - "'overlay' in loaded_modules"
          - "'br_netfilter' in loaded_modules"

    - name: Check IP forwarding
      command: sysctl -n net.ipv4.ip_forward
      register: ip_forward
      changed_when: false

    - name: Assert IP forwarding enabled
      ansible.builtin.assert:
        that:
          - ip_forward.stdout == "1"
```

Запуск:

```bash
ansible-playbook -i inventory/my_cluster/hosts.yaml playbooks/preflight.yml
```

#### Что проверяет Kubespray сам

Часть этих условий Kubespray закрывает в своих ролях, поэтому preflight-плейбук нужен в первую очередь для раннего обнаружения проблем:

| Условие | Где закрывается в Kubespray |
| :--- | :--- |
| Swap отключен | `roles/kubernetes/preinstall/tasks/0010-swapoff.yml` (при `kubelet_fail_swap_on`) |
| `net.ipv4.ip_forward=1` | `roles/kubernetes/preinstall/tasks/0080-system-configurations.yml` |
| Модуль `br_netfilter` | `roles/kubernetes/node/tasks/main.yml` (загрузка + persist в `/etc/modules-load.d/kubespray-br_netfilter.conf`) |
| Модуль `overlay` | `roles/container-engine/containerd/templates/containerd.service.j2` (`ExecStartPre=-/sbin/modprobe overlay`) |

---

## Устранение неполадок

### Типовые ошибки при развертывании

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `UNREACHABLE! Failed to connect to the host via ssh` | Нет SSH-доступа или не установлен Python | Проверьте SSH: `ssh user@host`. Установите Python: `sudo apt install python3` |
| `Failed to connect to the host via ssh: Permission denied (publickey)` | Неверный ключ или права на `~/.ssh` | `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys` |
| `The full traceback is: ... kubeadm: command not found` | Kubespray не смог установить kubeadm | Проверьте интернет-доступ и версию Kubespray |
| `etcd cluster is unavailable` | etcd не запущен или кворум потерян | `sudo crictl ps -a \| grep etcd` → проверка логов |
| `error: unable to recognize`: no matches for kind | API-версия манифеста не поддерживается | Обновите Kubespray до версии, поддерживающей нужную версию K8s |
| `Connection reset by peer` | Сетевой сбой или firewall | Проверьте порты: `nc -zv host 6443` |

### Полезные команды диагностики

```bash
# Сбор логов kubeadm (при ошибке инициализации)
sudo journalctl -u kubelet -f --no-pager | tail -50

# Проверка статуса containerd
sudo systemctl status containerd
sudo crictl ps -a

# Проверка конфигурации kubelet
sudo cat /var/lib/kubelet/config.yaml

# Просмотр Ansible-логов с увеличенной детализацией
ansible-playbook ... -vvv
```

---

### 11. Выделенный Control Plane и два Worker'а для разгрузки перегруженного узла

#### Цель

Разделить роли Control Plane (etcd, API-сервер, scheduler, controller-manager) и рабочие нагрузки на отдельные VM, чтобы устранить конкуренцию за CPU, которая маскируется под «медленные диски». На тестовом стенде один узел тянет всё: Control Plane + etcd + тяжёлую БД (ClickHouse) — и упирается в CPU. Лечится это не быстрым диском, а разнесением ролей: выделенный Control Plane под taint + два Worker'а под нагрузку.

#### Предусловия

- 3 VM с Ubuntu 24.04 (cgroups v2 по умолчанию).
- SSH-доступ по ключу с `sudo` (можно с паролем — используйте `-K`).
- Python 3 на всех узлах.
- Синхронизация времени (chrony) — etcd чувствителен к расхождению часов.
- Фаервол отключен или открыты порты K8s/etcd/Cilium.

#### Диагностика: точно ли диск?

На узле, где «тормозят диски», проверьте, на чём встают задачи — на I/O или на CPU:

```bash
nproc                                       # сколько ядер реально есть
cat /proc/loadavg                           # load относительно ядер
cat /proc/pressure/cpu /proc/pressure/io    # PSI: % времени в ожидании за 10/60/300с
vmstat 1 3                                  # 'wa' = iowait%, 'b' = процессы, заблокированные на I/O
```

**Интерпретация:**

- `wa` низкий (единицы процентов), `b ≈ 0`, PSI io низкий, а PSI cpu высокий и `load` больше числа ядер → **узкое место в CPU**. Диск ни при чём: fsync etcd, kubelet, API-сервер и приложение ждут процессор.
- `wa` высокий, процессы в D-состоянии → проблема в хранилище (другая история).

#### Архитектура: 1 Control Plane + 2 Worker'а

| Узел | IP | Роли | Примечание |
|------|-----|------|------------|
| `cp1` | 10.0.0.10 | control-plane + etcd | Выделенный, под taint `NoSchedule` |
| `worker1` | 10.0.0.11 | worker | Тяжёлая нагрузка (БД) |
| `worker2` | 10.0.0.12 | worker | Всё остальное |

**Почему не 3 Control Plane?** Три дали бы etcd-HA (кворум из 3 переживает один отказ), но вернули бы оверхед Control Plane на каждый узел — обратное изоляции. На тесте цель — разгрузка, а не HA. Один член etcd нормально; вырасти в 3-узловый HA-Control Plane позже — правка inventory (см. раздел Day-2).

#### Подготовка управляющей машины

```bash
git clone -b v2.31.0 https://github.com/kubernetes-sigs/kubespray.git
cd kubespray

python3 -m venv .venv && source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt   # прибивает ansible==11.13.0 → ansible-core 2.18.x
```

> **Важно:** `v2.31.0` (апрель 2026) поддерживает Kubernetes до 1.35.4, Cilium 1.19.3 и Ubuntu 24.04. `requirements.txt` прибивает `ansible==11.13.0` (ansible-core 2.18.x); метаданные роли требуют `>=2.18.0,<2.19.0`. **Не делайте `apt install ansible`** — там 2.19+, и проверка синтаксиса упадёт.

#### Inventory

```bash
cp -rfp inventory/sample inventory/mycluster
```

`inventory/mycluster/inventory.ini`:

```ini
[kube_control_plane]
cp1 ansible_host=10.0.0.10 ip=10.0.0.10 ansible_user=ubuntu etcd_member_name=etcd1

[etcd:children]
kube_control_plane

[kube_node]
worker1 ansible_host=10.0.0.11 ip=10.0.0.11 ansible_user=ubuntu
worker2 ansible_host=10.0.0.12 ip=10.0.0.12 ansible_user=ubuntu
```

**Ключевые поля:**
- `ansible_host=` — адрес для SSH.
- `ip=` — адрес для бинда kubelet/etcd. Задавайте явно; на VM с несколькими NIC автоопределённый IP часто не тот.
- `[etcd:children] kube_control_plane` кладёт etcd на Control Plane узлы. Ровно один хост в `[kube_control_plane]` → ровно один член etcd.
- **`cp1` НЕ указан в `[kube_node]`** — это делает его выделенным Control Plane: он подключается как control-plane узел (kubelet работает, но висит taint `NoSchedule`) и никогда не становится целью планирования для нагрузки.

#### Конфигурация кластера

Файлы в `inventory/mycluster/group_vars/`:

**k8s_cluster/k8s-cluster.yml**
```yaml
kube_version: v1.35.4

kube_network_plugin: cilium

container_manager: containerd

kubeconfig_localhost: true
kubectl_localhost: true

supplementary_addresses_in_ssl_keys:
  - 10.0.0.10
```

**k8s_cluster/addons.yml**
```yaml
helm_enabled: true
local_path_provisioner_enabled: true   # Kubespray по умолчанию НЕ ставит StorageClass
```

**k8s_cluster/k8s-net-cilium.yml**
```yaml
cilium_version: "1.19.3"

cilium_kube_proxy_replacement: true

cilium_l2announcements: false
cilium_loadbalancer_ip_pools: []
```

**Как убирается kube-proxy:**  
При `kube_network_plugin: cilium` и `cilium_kube_proxy_replacement: true` Kubespray добавляет `addon/kube-proxy` в пропускаемые фазы `kubeadm init` — kube-proxy не создаётся вовсе. Нужны **оба** условия. В v2.31.0 принимается булево `true` (строки `"strict"` в 1.19 устарели). `kube_proxy_remove: true` не нужен — это запасной вариант для других CNI.

#### Запуск установки

```bash
ansible-playbook -i inventory/mycluster/inventory.ini \
  --become --become-user=root \
  --ask-become-pass \
  cluster.yml
```

- `--become` поднимает права до root; `--ask-become-pass` (`-K`) спрашивает sudo-пароль один раз.
- Если SSH тоже по паролю — добавьте `-k`.
- Время: ~20–30 минут на 3 VM. Прогон идемпотентен — повтор сходится.

#### Держим Control Plane выделенным и изолируем тяжёлую нагрузку

**Не снимайте taint с cp1.** Kubespray ставит `node-role.kubernetes.io/control-plane:NoSchedule` — это ровно то, что нужно.

```bash
kubectl get node cp1 -o jsonpath='{.spec.taints}'
# [{"effect":"NoSchedule","key":"node-role.kubernetes.io/control-plane"}]
```

**Прибейте тяжёлую нагрузку к worker1.** Повесьте taint, чтобы его терпела только БД:

```bash
kubectl taint nodes worker1 dedicated=db:NoSchedule
```

В pod spec базы:

```yaml
spec:
  nodeSelector:
    kubernetes.io/hostname: worker1
  tolerations:
    - key: dedicated
      value: db
      effect: NoSchedule
  containers:
    - name: clickhouse
      resources:
        requests: { cpu: "6", memory: 24Gi }
        limits:   { cpu: "10", memory: 32Gi }
```

**Остальное** планируется на worker2 (и никогда — на Control Plane). Для реплицируемых нагрузок используйте anti-affinity:

```yaml
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels: { app: my-api }
          topologyKey: kubernetes.io/hostname
```

**Проставьте остальным шумным подам (сборщики логов, сайдкары) явные CPU requests** — поды без них тихо забивают узел.

#### Storage в multi-node кластере

Kubespray по умолчанию не ставит StorageClass. Варианты:

| Provisioner | Под переехал на другой узел | Цена по CPU | Когда |
|-------------|----------------------------|-------------|-------|
| local-path (встроенный addon) | PV прибит к ноде → под остаётся на своей ноде | ~ноль | Тестовые данные, привязка к ноде ок |
| NFS subdir | Данные едут (сетевой том) | Низкая | Общие файлы / RWX; экспортирующая нода — SPOF |
| Longhorn (Helm) | Реплика уже на целевой ноде → едут | Высокая (engine + реплика, iSCSI) | Данные должны пережить падение ноды |

На стенде с дефицитом CPU: **local-path** (дешевле всего) или **NFS** (лёгкий, RWX) против Longhorn — синхронная репликация и per-volume engine у Longhorn добавляют ровно тот CPU, который вы пытаетесь освободить. `local_path_provisioner_enabled: true` создаёт дефолтный StorageClass `local-path`; его PV прибиты к ноде, так что прибитый под БД и его данные остаются вместе на worker1.

#### Получение kubeconfig

```bash
export KUBECONFIG=$PWD/inventory/mycluster/artifacts/admin.conf
kubectl get nodes -o wide
```

```
NAME      STATUS   ROLES           AGE   VERSION    INTERNAL-IP
cp1       Ready    control-plane   9m    v1.35.4    10.0.0.10
worker1   Ready    <none>          7m    v1.35.4    10.0.0.11
worker2   Ready    <none>          7m    v1.35.4    10.0.0.12
```

`server:` в `admin.conf` указывает на IP cp1. Если ходите по другому адресу — NAT, hostname, jump-хост — поправьте `server:` и убедитесь, что адрес был в `supplementary_addresses_in_ssl_keys`, иначе TLS отклонит соединение.

#### Day-2: масштабируем воркеры, растём в HA

Тот же inventory ведёт lifecycle-плейбуки:

```bash
# Добавить worker3: дописать в [kube_node], затем
ansible-playbook -i inventory/mycluster/inventory.ini --become -K scale.yml

# Аккуратно drain и удалить узел
ansible-playbook -i inventory/mycluster/inventory.ini --become -K \
  -e node=worker2 remove-node.yml

# Плавный апгрейд версии по одному узлу (сперва поднять kube_version)
ansible-playbook -i inventory/mycluster/inventory.ini --become -K upgrade-cluster.yml

# Снести k8s/etcd/CNI со всех хостов до голой ОС — деструктивно
ansible-playbook -i inventory/mycluster/inventory.ini --become -K reset.yml
```

**Расти в HA Control Plane:** добавьте ещё два хоста в `[kube_control_plane]`, чтобы у etcd стало 3 члена (нечётный счёт, переживающий отказ), и запустите `upgrade-cluster.yml`. Добавить воркеры — `scale.yml` после дописывания хоста. Inventory и есть кластер — никакой пересборки.

#### Типовые проблемы

| Симптом | Причина | Решение |
|---------|---------|---------|
| Добавил воркер, но на него ничего не переехало | Поды без resource requests не перебалансируются | Проставьте requests/limits, разместите taint'ом/anti-affinity, пере-раскатайте |
| Случайно снял taint с Control Plane | Мышечная память от одно-/двухузловых кластеров | Верните: `kubectl taint nodes cp1 node-role.kubernetes.io/control-plane=:NoSchedule` |
| `ansible-core version is not supported` | Запустили Ansible вне venv / `apt install ansible` | Пересоздайте venv, `pip install -r requirements.txt` |
| Сбор фактов падает: `/usr/bin/python3 not found` | Минимальный образ без Python | `ssh ubuntu@host sudo apt-get install -y python3` |
| Missing sudo password | sudo без NOPASSWD | Добавьте `-K` (и `-k` если SSH по паролю) |
| etcd нездоров / установка виснет на join | Расхождение часов или чётный счёт etcd | Ровно 1 хост в `[etcd]`, chrony на всех узлах |
| Поды Pending / kube-proxy всё ещё есть | Firewall режет CNI/etcd или не включена замена | `ufw disable`; проверьте `cilium_kube_proxy_replacement: true` и `kube_network_plugin: cilium` |

#### Итого

- Симптом «медленные диски» → причина **конкуренция за CPU**. Проверяйте `wa`/PSI до закупки хранилища.
- Разнесите роли по VM: выделенный Control Plane под taint + два Worker'а. etcd и API-сервер перестают конкурировать с CPU приложений; два Worker'а удваивают планируемую ёмкость.
- Ноды сами по себе нагрузку не разносят. Проставьте requests/limits, прибейте доминирующую нагрузку к своему Worker'у, используйте anti-affinity для реплик — **один большой под не делится**.
- Cilium с `cilium_kube_proxy_replacement: true` убирает kube-proxy целиком — но только если задан и `kube_network_plugin: cilium`.
- Хранилище выбирайте по бюджету CPU: local-path или NFS против Longhorn на нагруженном стенде.
- Inventory и есть кластер. Добавляйте воркеры через `scale.yml`; вырастите в 3-узловой HA-Control Plane позже — перенос хостов в `[kube_control_plane]`, правка, а не пересборка.

---

## Дополнительная информация

### Действия после развертывания
1.  **Верификация:** Детальные инструкции по проверке статуса узлов и системных подов — в руководстве **[Проверка работоспособности кластера](../../HA_Cluster_Bare_Metal/k8s_ha_cluster_verification.md)**.
2.  **Настройка доступа:** Методы подключения через `kubectl` и работа с артефактами описаны в **[Дополнительной информации](./additional_info.md)** и **[Kubeconfig и подключение](../../Operations/kubeconfig_and_connection.md)**.
3.  **HA-режим:** Если требуется высокая доступность API-сервера, см. **[Развертывание HA-кластера](../HA/index.md)**.
4.  **Day 2 операции:** Масштабирование, обновление, удаление узлов — в **[Управлении кластером](../cluster_management.md)**.

### См. также
- **[Определения](./definitions.md)** — глоссарий терминов и описание плейбуков.
- **[Основные концепции](./basic_concepts.md)** — архитектурные требования и системные параметры.
- **[Обзор Kubespray](../overview.md)** — матрица совместимости и возможности.

### Внешние ресурсы
- [Kubespray Official Documentation](https://kubespray.io/#/)
- [Cilium Installation with Kubespray](https://docs.cilium.io/en/stable/installation/k8s-install-kubespray/)
