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
