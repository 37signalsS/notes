# Подготовка узлов HA кластера Kubernetes

## Определения

**Node Preparation** — процесс предварительной настройки всех узлов кластера (Control Plane и Worker) перед установкой компонентов Kubernetes.

**cgroups v2** — версия контрольных групп Linux, обязательная для Kubernetes 1.24+. Управляет ресурсами контейнеров.

**SWAP** — область подкачки на диске. Kubernetes требует отключения SWAP для предсказуемого управления памятью.

**CNI (Container Network Interface)** — стандартный интерфейс для подключения контейнеров к сети.

---

## Основные концепции

### Почему требуется подготовка?

Kubernetes предъявляет специфические требования к ОС:

- **Отключенный SWAP** — `kubelet` не работает с SWAP
- **Отключенный Firewall** — предотвращение блокировки межподового и сервисного трафика
- **SELinux в режиме Permissive/Disabled** — предотвращение блокировки доступа к файловой системе и сокетам
- **cgroups v2** — требуется для управления ресурсами подов
- **Сетевые модули** — `br_netfilter`, `overlay` для работы CNI
- **Sysctl параметры** — включение IP forwarding, iptables для сетевой политики

### Область применения

Эти шаги выполняются **на каждом узле** кластера:

- Control Plane узлы (мастеры)
- Worker узлы

---

## Практические сценарии

### Шаг 1: Обновление системы

```bash
# Обновление пакетов
sudo apt update
sudo apt upgrade -y

# Проверка доступных ядер после обновления
ls /boot/vmlinuz-*
```

> **Важно**: НЕ перезагружаем систему до завершения всех настроек.

### Шаг 2: Настройка имени хоста и `/etc/hosts`

#### Установка hostname

```bash
# Присвоить уникальное имя каждому узлу
sudo hostnamectl set-hostname <имя-узла>
# Примеры: master-1, master-2, worker-1
```

#### Настройка `/etc/hosts`

На **каждом** узле добавить IP-адреса всех участников:

```bash
# /etc/hosts
<IP-балансировщика>    kubeapi-vip
<IP-master-1>          master-1
<IP-master-2>          master-2
<IP-master-3>          master-3
<IP-worker-1>          worker-1
<IP-worker-2>          worker-2
```

> **NOTE**: Для production использовать внутренний DNS-сервер вместо ручного `/etc/hosts`.

### Шаг 3: Проверка текущего состояния

```bash
# Текущее ядро
uname -r

# Доступные ядра
ls /boot/vmlinuz-*

# Версия cgroups
stat -fc %T /sys/fs/cgroup
# Ожидается: cgroup2fs

# Активный SWAP
swapon --show
# Ожидается: пусто (0 активных)

# Загруженные сетевые модули
lsmod | grep -E "br_netfilter|overlay"

# Текущие контейнеры (если есть)
docker ps --format "table {{.Names}} {{.Status}}"
```

### Шаг 4: Отключение SWAP

```bash
# Немедленно отключить SWAP
sudo swapoff -a

# Закомментировать SWAP в /etc/fstab (перманентное отключение)
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# Проверка: должно быть 0 активных
swapon --show | wc -l
```

### Шаг 5: Отключение Firewall

Для корректной работы сетевых плагинов (CNI) и маршрутизации трафика рекомендуется отключить встроенные службы фильтрации или настроить их согласно [официальным портам K8s](https://kubernetes.io/docs/reference/networking/ports-and-protocols/).

#### Ubuntu (ufw)

```bash
sudo ufw disable
```

#### RHEL/CentOS/Rocky (firewalld)

```bash
sudo systemctl stop firewalld
sudo systemctl disable firewalld
```

### Шаг 6: Настройка SELinux

Для Kubernetes рекомендуется перевести SELinux в режим `permissive` (особенно на RHEL-based системах).

```bash
# Временное отключение
sudo setenforce 0

# Перманентное отключение (требуется перезагрузка для полной смены контекстов, но Permissive применяется сразу)
sudo sed -i 's/^SELINUX=enforcing$/SELINUX=permissive/' /etc/selinux/config
```

### Шаг 7: Настройка cgroups v2 в GRUB

```bash
# Добавить параметр ядра для включения cgroups v2
sudo sed -i 's/GRUB_CMDLINE_LINUX=""/GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=1"/' /etc/default/grub

# Обновить конфигурацию GRUB
sudo update-grub

# Проверка
grep GRUB_CMDLINE_LINUX /etc/default/grub
```

### Шаг 8: Загрузка сетевых модулей

```bash
# Загрузить модули немедленно
sudo modprobe br_netfilter
sudo modprobe overlay

# Добавить в автозагрузку
echo -e "br_netfilter\noverlay" | sudo tee /etc/modules-load.d/k8s.conf

# Проверка
lsmod | grep -E "br_netfilter|overlay"
```

### Шаг 9: Настройка sysctl параметров

```bash
# Создать конфигурационный файл
cat <<EOF | sudo tee /etc/sysctl.d/99-kubernetes.conf
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.netfilter.nf_conntrack_max = 262144
EOF

# Применить настройки
sudo sysctl --system

# Проверка
sysctl net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables
```

**Описание параметров**:

- `net.ipv4.ip_forward = 1` — включение маршрутизации между подами (подробнее в [sysctl](../../../Linux/Core/kernel/sysctl.md))
- `bridge-nf-call-iptables = 1` — передача трафика bridge через iptables (требуется для NetworkPolicy)
- `nf_conntrack_max` — максимальное количество отслеживаемых соединений

### Шаг 10: Итоговая проверка готовности

```bash
echo "=== Проверка готовности узла ==="

# 1. SWAP
swap_count=$(swapon --show | wc -l)
echo "1. SWAP: $swap_count активных (должно быть 0)"

# 2. Cgroups
cgroup_type=$(stat -fc %T /sys/fs/cgroup)
echo "2. Cgroups: $cgroup_type (должно быть cgroup2fs)"

# 3. Сеть
ip_forward=$(sysctl -n net.ipv4.ip_forward)
echo "3. IP Forward: $ip_forward (должно быть 1)"

# 4. Модули
br_count=$(lsmod | grep -c br_netfilter)
overlay_count=$(lsmod | grep -c overlay)
echo "4. Модули: br_netfilter=$br_count, overlay=$overlay_count (должно быть 1+)"

# Итог
if [ "$swap_count" -eq 0 ] && [ "$cgroup_type" = "cgroup2fs" ] && [ "$ip_forward" -eq 1 ] && [ "$br_count" -ge 1 ] && [ "$overlay_count" -ge 1 ]; then
    echo "✅ Узел готов к установке Kubernetes"
else
    echo "❌ Узел НЕ готов. Проверьте настройки выше."
fi
```

---

## Дополнительная информация

### Что НЕ делается на этом этапе

**Перезагрузка** — выполняется позже, после установки всех компонентов. **Установка Kubernetes** — следующий этап ([component installation](./k8s_ha_component_installation.md)). **Изменение существующих контейнеров** — Docker/containerd продолжают работать.

### Следующие шаги

После подготовки всех узлов: установка `containerd`, установка `kubeadm`/`kubelet`/`kubectl`, перезагрузка всех узлов, инициализация кластера.

### Интеграция с документацией

Подготовка узлов — **шаг 2** после [требований к среде](./k8s_ha_environment_requirements.md) и перед [установкой компонентов](./k8s_ha_component_installation.md). Подробнее о containerd — в [alternative runtimes](../../../Docker/alternative_runtimes_and_tools.md), о CNI — в [CNI definitions](../../Networking/Network/CNI/definitions.md).
