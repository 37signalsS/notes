### 2. Подготовка всех узлов (Master и Worker)

Следующие шаги выполняются на **каждом** узле будущего кластера.

#### Обновление системы

```bash
sudo apt-get update && sudo apt-get upgrade -y
```

#### Настройка имен хостов и `/etc/hosts`

Присвойте уникальное имя каждому узлу (`master-1`, `master-2`, `worker-1` и т.д.):

```bash
sudo hostnamectl set-hostname <имя-узла>
```

На каждом узле добавьте в `/etc/hosts` IP-адреса всех участников кластера.

```
# /etc/hosts
<IP-адрес-балансировщика> kubeapi-vip
<IP-адрес-мастера-1> master-1
<IP-адрес-мастера-2> master-2
<IP-адрес-мастера-3> master-3
<IP-адрес-воркера-1> worker-1
...
```

> **NOTE:** Для продуктивных сред рекомендуется использовать внутренний DNS-сервер вместо ручного редактирования `/etc/hosts`.

#### Предварительная проверка и настройка системы

Эти шаги выполняются на **каждом** сервере будущего кластера.

##### 1. Проверка текущего состояния (на ВСЕХ серверах)

Текущее ядро

```bash
uname -r
```

Доступные ядра

```bash
ls /boot/vmlinuz-*
```

Cgroups версия

```bash
stat -fc %T /sys/fs/cgroup
```

Активный SWAP

```bash
swapon --show
```

Загруженные сетевые модули

```bash
lsmod | grep -E "br_netfilter|overlay"
```

Текущие контейнеры

```bash
docker ps --format "table {{.Names}}	{{.Status}}"
```

##### 2. Обновление системы (по одному серверу)

```bash
sudo apt update
sudo apt upgrade -y
```

Проверка доступных ядер после обновления

```bash
ls /boot/vmlinuz-*  # Должно быть новое ядро (в моем случае это 6.8.0-90)
```

> **ВАЖНО:** НЕ перезагружаем пока! Сначала выполним все настройки.

##### 3. Настройка системных параметров

1. Отключаем SWAP

```bash
sudo swapoff -a
sudo sed -i '/ swap / s/^/#/' /etc/fstab
echo "SWAP отключен: $(swapon --show | wc -l) активных"
```

1. Настраиваем cgroups v2 в GRUB

```bash
sudo sed -i 's/GRUB_CMDLINE_LINUX=""/GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=1"/' /etc/default/grub
sudo update-grub
echo "GRUB обновлён: $(grep GRUB_CMDLINE_LINUX /etc/default/grub)"
```

1. Загружаем сетевые модули

```bash
sudo modprobe br_netfilter
sudo modprobe overlay
echo -e "br_netfilter
overlay" | sudo tee /etc/modules-load.d/k8s.conf
echo "Модули загружены:"
lsmod | grep -E "br_netfilter|overlay"
```

1. Настраиваем sysctl параметры

```bash
cat <<EOF | sudo tee /etc/sysctl.d/99-kubernetes.conf
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.netfilter.nf_conntrack_max = 262144
EOF

sudo sysctl --system
echo "Проверка параметров:"
sysctl net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables net.bridge.bridge-nf-call-ip6tables
```

##### 4. Быстрая проверка готовности

После выполнения всех команд на каждом сервере у вас будет:

1. Система готова к работе с Kubernetes:
SWAP полностью отключен (swapon --show = 0 активных)
Cgroups v2 активирован (stat -fc %T /sys/fs/cgroup = cgroup2fs)
GRUB настроен с параметром systemd.unified_cgroup_hierarchy=1
Сетевые модули загружены (br_netfilter, overlay)
Sysctl параметры установлены (ip_forward=1, bridge-nf-call-iptables=1)

2. Все проверки пройдены:

```bash
1. SWAP: $(swapon --show | wc -l) активных (должно быть 0)
2. Cgroups: $(stat -fc %T /sys/fs/cgroup) (должно быть cgroup2fs)
3. Сеть: ip_forward=$(sysctl -n net.ipv4.ip_forward) (должно быть 1)
4. Модули: br_netfilter=$(lsmod | grep -c br_netfilter), overlay=$(lsmod | grep -c overlay)
```

##### 5. Что НЕ сделано (и не должно быть сделано сейчас)

* Перезагрузка (выполним позже, после всех настроек)
* Установка Kubernetes компонентов (это следующий этап)
* Изменение работы существующих контейнеров (они работают как и раньше)