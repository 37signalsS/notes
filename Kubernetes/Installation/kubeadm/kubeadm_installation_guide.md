# Руководство по подготовке узлов для установки Kubernetes через kubeadm

## Определения

**kubeadm** — официальная CLI-утилита для создания и управления жизненным циклом кластеров Kubernetes. Автоматизирует генерацию сертификатов, настройку статических подов Control Plane, создание токенов для присоединения узлов и управление обновлениями. Используется как стандартный инструмент для bare-metal развёртываний.

**CRI (Container Runtime Interface)** — стандарт интерфейса для взаимодействия `kubelet` со средой выполнения контейнеров. Начиная с Kubernetes v1.24 поддержка Docker через `dockershim` удалена; рекомендуемые CRI-совместимые рантаймы: `containerd` и `CRI-O`.

**containerd** — промышленная среда выполнения контейнеров, поддерживающая стандарт CRI. Является рекомендуемым Runtime для kubeadm-кластеров. Отвечает за скачивание образов, создание и запуск контейнеров через `runc`, управление снимками файловой системы и организацию сетевых интерфейсов через CRI.

**cgroup v2 (Control Groups version 2)** — современная подсистема ядра Linux для управления ресурсами CPU, памяти, I/O и сетью контейнеров. Единая иерархия (в отличие от v1) обеспечивает предсказуемое потребление ресурсов. Обязательна для стабильной работы Kubernetes 1.25+ на современных ядрах.

**nftables** — современная подсистема фильтрации пакетов в ядре Linux, заменяющая устаревший `iptables`. Рекомендуемый бэкенд для `kube-proxy` с версии v1.31. Обеспечивает лучшую производительность и простоту управления правилами.

**IPVS (IP Virtual Server)** — высокопроизводительный L4-балансировщик, встроенный в ядро Linux. Используется как альтернатива `iptables` для режима работы `kube-proxy` в кластерах с большим количеством сервисов (тысячи Service). Обеспечивает O(1) время поиска правила (vs O(n) в iptables).

**sysctl** — интерфейс для чтения и изменения параметров ядра Linux в runtime. Параметры сетевого стека (`ip_forward`, `bridge-nf-call-iptables`) и системы (`inotify`, `panic`) критически важны для стабильности Kubernetes.

**Chrony (NTP)** — демон синхронизации системного времени. Критически важен для HA-кластеров: распределённое хранилище `etcd` чувствительно к дрейфу часов между узлами; разница более нескольких секунд приводит к проблемам с сертификатами и потерей кворума.

**pause image (Sandbox Image)** — служебный контейнер в составе Pod, который «держит» сетевое пространство имён (Network Namespace) и IPC для пода. Все остальные контейнеры пода подключаются к его ресурсам. Версия pause-образа должна соответствовать версии Kubernetes (registry.k8s.io/pause:3.10 для v1.35+).

---

## Основные концепции

### Этапы развёртывания инфраструктуры

Процесс подготовки разделён на логические этапы, которые должны быть выполнены на **всех** узлах (Control Plane и Worker):

| Этап | Описание | Критичность |
| :--- | :--- | :--- |
| 1. Подготовка ОС | Обновление пакетов, уникальность имён, отключение swap | Обязательно |
| 2. Синхронизация времени | Настройка Chrony/NTP | Обязательно для HA |
| 3. Настройка ядра | Загрузка модулей (`overlay`, `br_netfilter`, IPVS) | Обязательно |
| 4. Параметры сети | `ip_forward`, `bridge-nf-call-iptables`, inotify | Обязательно |
| 5. Системные лимиты | `nofile`, `nproc` для контейнеров | Рекомендуется |
| 6. Конфигурация cgroups | Включение cgroup v2, настройка `SystemdCgroup` | Обязательно |
| 7. Сетевой экран | Открытие портов (iptables/firewalld/ufw) | Обязательно |
| 8. Установка Runtime | Установка и настройка `containerd` | Обязательно |
| 9. Установка компонентов | Пакеты `kubeadm`, `kubelet`, `kubectl` | Обязательно |
| 10. Верификация | Проверка готовности узла к инициализации | Обязательно |

### Совместимость и версии (2026)

| Компонент | Рекомендуемая версия | Поддерживаемые ОС |
| :--- | :--- | :--- |
| **Kubernetes** | v1.36.x | Ubuntu 22.04+, RHEL 9+, Debian 12+ |
| **containerd** | v2.0+ (рекомендуется) | Все вышеперечисленные |
| **Linux Kernel** | 5.15+ (рекомендуется 6.x) | Необходима поддержка cgroup v2 |
| **Systemd** | 245+ | Управляет ресурсами и автозагрузкой |

> **Примечание:** Kubernetes 1.37 уже доступен, но v1.36 является последней стабильной версией с полной поддержкой. Рекомендуется использовать v1.36.x для production-сред.

### Почему каждая настройка критична

| Настройка | Без неё | Почему это важно |
| :--- | :--- | :--- |
| **Swap отключён** | kubelet не запускается | kubelet не умеет учитывать подкачку при планировании ресурсов, что ведёт к непредсказуемому поведению подов |
| **ip_forward=1** | Поды не видят друг друга | Узел должен маршрутизировать пакеты между Pod-сетями на разных хостах |
| **bridge-nf-call-iptables** | Трафик между подами блокируется | Пакеты, проходящие через виртуальный мост, должны обрабатываться правилами iptables |
| **overlay + br_netfilter** | CNI не работает | Модули необходимы для виртуальных сетевых интерфейсов и контейнерных мостов |
| **SystemdCgroup=true** | kubelet и containerd конфликтуют | Разные драйверы ресурсов приводят к нестабильности: лимиты не применяются корректно |
| **cgroup v2** | Лимиты памяти/CPU не работают | Единая иерархия обеспечивает предсказуемое потребление ресурсов контейнерами |
| **Chrony/NTP** | etcd теряет кворум | etcd использует часы для leader election и логов; дрейф более 500мс вызывает конфликты |
| **Уникальные hostnames** | Конфликты в логах и API | Kubernetes идентифицирует узлы по имени хоста |

---

## Практические сценарии

### Шаг 1: Системные требования и ОС

#### Требования к ресурсам

| Тип узла | CPU | RAM | Disk | Сеть |
| :--- | :--- | :--- | :--- | :--- |
| **Control Plane** | 2+ vCPU (рекомендуется 4) | 4 ГБ+ (рекомендуется 8 ГБ) | 50 ГБ+ SSD | 1 Гбит/с |
| **Worker** | 2+ vCPU | 4 ГБ+ (рекомендуется 8 ГБ) | 50 ГБ+ | 1 Гбит/с |
| **etcd (отдельный)** | 2+ vCPU | 4 ГБ+ | 100 ГБ+ SSD | 1 Гбит/с |

#### Первичная настройка (Все узлы)

```bash
# 1. Обновление системы
sudo apt update && sudo apt upgrade -y

# 2. Установка необходимых пакетов
sudo apt install -y curl gnupg2 software-properties-common \
     apt-transport-https ca-certificates lsb-release \
     socat conntrack ipset

# 3. Отключение SWAP (обязательно)
sudo swapoff -a
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# 4. Уникальность имени хоста
sudo hostnamectl set-hostname master-1  # На каждом узле — уникальное имя

# 5. Проверка machine-id (важно для логов и сетевых плагинов)
cat /etc/machine-id
# На всех узлах machine-id должны быть уникальны
# Если одинаковы (например, при клонировании VM):
sudo rm /etc/machine-id && sudo systemd-machine-id-setup
```

### Шаг 2: Синхронизация времени (Chrony)

Для HA-кластера разница во времени между узлами не должна превышать нескольких миллисекунд.

```bash
# Установка и запуск Chrony
sudo apt install -y chrony
sudo systemctl enable --now chrony

# Проверка статуса синхронизации
chronyc tracking
# → Leap status: Normal
# → System time: 0.000001234 seconds fast of NTP time

# Проверка доступных серверов
chronyc sources -v
# →.should show NTP servers with ^* or ^+ prefix
```

**Важно:** В HA-кластерах все узлы должны синхронизироваться с одними и теми же NTP-серверами. Различные источники времени могут приводить к расхождениям.

### Шаг 3: Настройка ядра и сети

```bash
# Загрузка модулей при загрузке
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
ip_vs
ip_vs_rr
ip_vs_wrr
ip_vs_sh
nf_conntrack
EOF

# Загрузка модулей вручную (немедленно)
sudo modprobe overlay
sudo modprobe br_netfilter
sudo modprobe ip_vs
sudo modprobe ip_vs_rr
sudo modprobe ip_vs_wrr
sudo modprobe ip_vs_sh
sudo modprobe nf_conntrack

# Параметры sysctl
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
# Сетевой стек Kubernetes
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1

# Лимиты inotify (много подов = много watches)
fs.inotify.max_user_instances = 512
fs.inotify.max_user_watches   = 524288

# Стабильность ядра
kernel.panic                  = 10
kernel.panic_on_oops          = 1

# Фильтрация пакетов
net.ipv4.conf.all.rp_filter   = 1

# conntrack для IPVS
net.netfilter.nf_conntrack_max = 1048576
EOF

sudo sysctl --system
```

**Почему IPVS-модули:** Даже если вы планируете использовать режим `iptables` для `kube-proxy`, загрузка IPVS-модулей не повреждает систему и позволяет переключиться на IPVS в будущем без перезагрузки. В кластерах с >1000 Service IPVS обеспечивает O(1) время поиска правила вместо O(n).

### Шаг 4: Системные лимиты

Увеличение лимитов на количество дескрипторов файлов критично для узлов с большим количеством подов и контейнеров:

```bash
cat <<EOF | sudo tee /etc/security/limits.d/k8s.conf
* soft nofile 65536
* hard nofile 65536
* soft nproc 4096
* hard nproc 4096
EOF
```

### Шаг 5: Конфигурация cgroups v2

Для современных дистрибутивов (Ubuntu 22.04+, RHEL 9+) cgroups v2 обычно включен по умолчанию. Проверьте состояние:

```bash
# Проверка текущей версии cgroups
stat -fc %T /sys/fs/cgroup
# → Если результат 'cgroup2fs', настройка не требуется.
# → Если результат 'tmpfs', необходимо включить (см. ниже).
```

Если cgroups v2 не включен:

```bash
# 1. Редактирование GRUB
sudo sed -i 's/GRUB_CMDLINE_LINUX=""/GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=1"/' /etc/default/grub

# 2. Обновление GRUB
# Ubuntu/Debian:
sudo update-grub
# RHEL/CentOS:
# sudo grub2-mkconfig -o /boot/grub2/grub.cfg

# 3. Перезагрузка (обязательно!)
sudo reboot
```

### Шаг 6: Настройка сетевого экрана

Откройте порты согласно типу узла. Используйте **один** из вариантов ниже.

#### Control Plane узлы

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| 6443 | TCP | Kubernetes API Server |
| 2379-2380 | TCP | etcd server client API |
| 10250 | TCP | Kubelet API |
| 10259 | TCP | kube-scheduler |
| 10257 | TCP | kube-controller-manager |

#### Worker узлы

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| 10250 | TCP | Kubelet API |
| 30000-32767 | TCP | NodePort Services |

#### Вариант A: iptables/nftables

```bash
# Control Plane
sudo iptables -A INPUT -p tcp --dport 6443 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 2379:2380 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 10250 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 10259 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 10257 -j ACCEPT

# Worker
sudo iptables -A INPUT -p tcp --dport 10250 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 30000:32767 -j ACCEPT

# Сохранение правил (Ubuntu)
sudo iptables-save | sudo tee /etc/iptables/rules.v4

# Сохранение правил (RHEL/CentOS)
sudo dnf install -y iptables-services
sudo service iptables save
```

#### Вариант B: firewalld (RHEL/Rocky)

```bash
# Control Plane
sudo firewall-cmd --permanent --add-port=6443/tcp
sudo firewall-cmd --permanent --add-port=2379-2380/tcp
sudo firewall-cmd --permanent --add-port=10250/tcp
sudo firewall-cmd --permanent --add-port=10259/tcp
sudo firewall-cmd --permanent --add-port=10257/tcp
sudo firewall-cmd --reload

# Worker
sudo firewall-cmd --permanent --add-port=10250/tcp
sudo firewall-cmd --permanent --add-port=30000-32767/tcp
sudo firewall-cmd --reload

# Проверка
sudo firewall-cmd --list-ports
```

#### Вариант C: ufw (Ubuntu)

```bash
# Control Plane
sudo ufw allow 6443/tcp
sudo ufw allow 2379:2380/tcp
sudo ufw allow 10250/tcp
sudo ufw allow 10259/tcp
sudo ufw allow 10257/tcp
sudo ufw reload

# Worker
sudo ufw allow 10250/tcp
sudo ufw allow 30000:32767/tcp
sudo ufw reload

# Проверка
sudo ufw status
```

#### Вариант D: Отключение Firewall (для разработки/тестирования)

```bash
# Ubuntu/Debian
sudo ufw disable

# RHEL/Rocky
sudo systemctl stop firewalld
sudo systemctl disable firewalld
```

**Рекомендация:** В production используйте `iptables/nftables` или `firewalld`. Отключение firewall допустимо только в изолированных тестовых средах.

### Шаг 7: Установка и настройка containerd

#### Установка (Ubuntu/Debian)

```bash
# Установка необходимых пакетов
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg

# Добавление GPG-ключа Docker (официальный репозиторий)
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y containerd.io

# Проверка версии
containerd --version
# → containerd github.com/containerd/containerd v2.0.x ...
```

#### Установка (RHEL/Rocky Linux 9)

```bash
# Добавление репозитория Docker
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/rhel/docker-ce.repo

# Установка containerd
sudo dnf install -y containerd.io

# Проверка версии
containerd --version
```

#### Глубокая конфигурация containerd

```bash
# Генерация конфигурации по умолчанию
sudo mkdir -p /etc/containerd
containerd config default | sudo tee /etc/containerd/config.toml > /dev/null

# 1. Включение SystemdCgroup (критически важно!)
# Без этого kubelet и containerd будут использовать разные драйверы ресурсов
sudo sed -i 's/SystemdCgroup = false/SystemdCgroup = true/g' /etc/containerd/config.toml

# 2. Настройка актуальной версии pause-образа
# pause:3.10 — стандарт для Kubernetes v1.35+
sudo sed -i 's|sandbox_image = ".*"|sandbox_image = "registry.k8s.io/pause:3.10"|' /etc/containerd/config.toml

# 3. Настройка лимитов открытых файлов для контейнеров
sudo mkdir -p /etc/systemd/system/containerd.service.d
cat <<EOF | sudo tee /etc/systemd/system/containerd.service.d/limits.conf
[Service]
LimitNOFILE=1048576
LimitNPROC=infinity
LimitCORE=infinity
EOF

# 4. Перезапуск и включение автозагрузки
sudo systemctl daemon-reload
sudo systemctl restart containerd
sudo systemctl enable containerd

# 5. Проверка статуса
sudo systemctl status containerd
# → active (running)
```

**Почему SystemdCgroup=true:** В современных дистрибутивах Linux (Ubuntu 22.04+, RHEL 9+) `systemd` является менеджером ресурсов по умолчанию. `kubelet` также использует `systemd` как драйвер cgroups. Если `containerd` настроен на `cgroupfs` (по умолчанию), kubelet и containerd будут конфликтовать при управлении ресурсами контейнеров — лимиты памяти и CPU не будут применяться корректно.

#### Настройка реестров (опционально)

Если вы используете локальный реестр (Harbor, Nexus) или зеркала для ускорения скачивания:

```bash
# Редактирование /etc/containerd/config.toml
# Добавить в секцию [plugins."io.containerd.grpc.v1.cri".registry]:

# Пример: зеркало Docker Hub
# [plugins."io.containerd.grpc.v1.cri".registry.mirrors."docker.io"]
#   endpoint = ["https://mirror.example.com"]

# Пример: локальный реестр с TLS
# [plugins."io.containerd.grpc.v1.cri".registry.configs."harbor.internal".tls]
#   ca_file = "/etc/containerd/certs/harbor-ca.crt"

sudo systemctl restart containerd
```

### Шаг 8: Установка пакетов Kubernetes (v1.36)

Версии `kubeadm`, `kubelet` и `kubectl` **должны совпадать** между собой.

#### Установка (Ubuntu/Debian)

```bash
# Подготовка ключей (новый формат pkgs.k8s.io)
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl gpg

sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.36/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg

echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.36/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list

sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl

# Фиксация версий (prevent случайное обновление при apt upgrade)
sudo apt-mark hold kubelet kubeadm kubectl

# Включение автозагрузки kubelet
sudo systemctl enable --now kubelet

# Проверка версий
kubeadm version -o short
# → v1.36.x
kubelet --version
# → Kubernetes v1.36.x
```

#### Установка (RHEL/Rocky Linux 9)

```bash
cat <<EOF | sudo tee /etc/yum.repos.d/kubernetes.repo
[kubernetes]
name=Kubernetes
baseurl=https://pkgs.k8s.io/core:/stable:/v1.36/rpm/
enabled=1
gpgcheck=1
gpgkey=https://pkgs.k8s.io/core:/stable:/v1.36/rpm/repodata/repomd.xml.key
EOF

sudo dnf install -y kubelet kubeadm kubectl --disableexcludes=kubernetes
sudo systemctl enable --now kubelet

# Проверка версий
kubeadm version -o short
kubelet --version
```

**Почему apt-mark hold:** Без фиксации версий при обновлении системы (`apt upgrade` или `dnf update`) компоненты Kubernetes могут быть обновлены до несовместимых версий. Это приведёт к ошибкам при инициализации или присоединении узлов.

### Шаг 9: Настройка crictl

`crictl` — CLI-утилита для диагностики CRI-совместимых рантаймов. Настройка обязательна для быстрой отладки.

```bash
cat <<EOF | sudo tee /etc/crictl.yaml
runtime-endpoint: unix:///run/containerd/containerd.sock
image-endpoint: unix:///run/containerd/containerd.sock
timeout: 10
debug: false
EOF

# Проверка
sudo crictl info
# → Должен вывести JSON с конфигурацией containerd

sudo crictl ps -a
# → Список запущенных контейнеров (пустой, если кластер ещё не развёрнут)

sudo crictl images
# → Список доступных образов
```

### Шаг 10: Верификация готовности узла

Скрипт для полной проверки состояния узла перед запуском `kubeadm init`:

```bash
#!/bin/bash
echo "=== ПРОВЕРКА ГОТОВНОСТИ УЗЛА ==="

# 1. SWAP
if [ "$(swapon --show | wc -l)" -eq 0 ]; then
    echo "[OK] Swap отключен"
else
    echo "[FAIL] Swap активен! Выполните: sudo swapoff -a"
fi

# 2. Модули ядра
for mod in br_netfilter overlay ip_vs; do
    if lsmod | grep -q "$mod"; then
        echo "[OK] Модуль $mod загружен"
    else
        echo "[FAIL] Модуль $mod отсутствует!"
    fi
done

# 3. Sysctl
if [ "$(sysctl -n net.ipv4.ip_forward)" -eq 1 ]; then
    echo "[OK] IP Forwarding включен"
else
    echo "[FAIL] IP Forwarding выключен!"
fi

if [ "$(sysctl -n net.bridge.bridge-nf-call-iptables)" -eq 1 ]; then
    echo "[OK] bridge-nf-call-iptables включен"
else
    echo "[WARN] bridge-nf-call-iptables выключен"
fi

# 4. Cgroup v2
CGROUP_FS=$(stat -fc %T /sys/fs/cgroup 2>/dev/null)
if [ "$CGROUP_FS" = "cgroup2fs" ]; then
    echo "[OK] cgroup v2 активен"
else
    echo "[FAIL] cgroup v2 не активен (тип: $CGROUP_FS)"
fi

# 5. containerd
if systemctl is-active --quiet containerd; then
    echo "[OK] containerd активен"
else
    echo "[FAIL] containerd остановлен!"
fi

if [ -S /run/containerd/containerd.sock ]; then
    echo "[OK] Сокет containerd доступен"
else
    echo "[FAIL] Сокет containerd отсутствует!"
fi

# 6. Kubelet
if systemctl is-enabled --quiet kubelet; then
    echo "[OK] kubelet включен в автозагрузку"
else
    echo "[FAIL] kubelet не настроен на автозагрузку!"
fi

# 7. Версии
echo "--- ВЕРСИИ ---"
kubeadm version -o short
kubelet --version
containerd --version

# 8. Время (для HA)
if command -v chronyc &> /dev/null; then
    if chronyc tracking > /dev/null 2>&1; then
        echo "[OK] Chrony/NTP активен"
    else
        echo "[WARN] Chrony/NTP не отвечает"
    fi
else
    echo "[WARN] Chrony не установлен (критично для HA)"
fi

# 9. crictl
if sudo crictl info > /dev/null 2>&1; then
    echo "[OK] crictl подключается к containerd"
else
    echo "[FAIL] crictl не может подключиться к containerd"
fi

echo "=== ПРОВЕРКА ЗАВЕРШЕНА ==="
```

### Шаг 11: Pre-flight проверка kubeadm

```bash
# Запуск проверок без инициализации
sudo kubeadm init phase preflight

# Если есть ошибки, исправьте их перед запуском kubeadm init
# Типичные ошибки:
# - [ERROR CRI]: container runtime is not running → systemctl status containerd
# - [ERROR Port-10250]: Port 10250 is in use → fuser -k 10250/tcp
# - [ERROR Swap]: Running swap is enabled → sudo swapoff -a
```

### Шаг 12: Настройка для защищённых сред (Air-gapped)

Если кластер развёртывается без доступа к интернету:

```bash
# 1. Настройка прокси (если интернет доступен через прокси)
export HTTP_PROXY=http://proxy.example.com:8080
export HTTPS_PROXY=http://proxy.example.com:8080
export NO_PROXY=localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8

# Добавить в /etc/environment для persistent
cat <<EOF | sudo tee -a /etc/environment
HTTP_PROXY=http://proxy.example.com:8080
HTTPS_PROXY=http://proxy.example.com:8080
NO_PROXY=localhost,127.0.0.1,192.168.0.0/16,10.0.0.0/8
EOF

# 2. Настройка containerd для прокси
# В /etc/containerd/config.toml:
# [plugins."io.containerd.grpc.v1.cri".registry.configs."registry.k8s.io".tls]
#   ca_file = ""
# [plugins."io.containerd.grpc.v1.cri".registry.configs."registry.k8s.io".auth]
#   username = ""
#   password = ""

# 3. Предварительная загрузка образов (на машине с интернетом)
sudo crictl pull registry.k8s.io/pause:3.10
sudo crictl pull registry.k8s.io/kube-apiserver:v1.36.x
sudo crictl pull registry.k8s.io/kube-controller-manager:v1.36.x
sudo crictl pull registry.k8s.io/kube-scheduler:v1.36.x
sudo crictl pull registry.k8s.io/kube-proxy:v1.36.x
sudo crictl pull registry.k8s.io/coredns/coredns:v1.12.x

# 4. Сохранение и перенос образов
sudo crictl images | awk 'NR>1 {print $1":"$2}' > images.txt
# На целевом узле:
# while read img; do sudo crictl pull "$img"; done < images.txt
```

### Шаг 13: Откат и очистка

Если подготовка выполнена некорректно и необходим полный сброс:

```bash
# 1. Остановка сервисов
sudo systemctl stop kubelet
sudo systemctl stop containerd

# 2. Очистка конфигураций
sudo rm -rf /etc/containerd/config.toml
sudo rm -rf /etc/crictl.yaml
sudo rm -rf /etc/modules-load.d/k8s.conf
sudo rm -rf /etc/sysctl.d/k8s.conf
sudo rm -rf /etc/security/limits.d/k8s.conf

# 3. Откат SWAP
sudo sed -i '/#.*swap / s/^#//' /etc/fstab

# 4. Удаление пакетов Kubernetes
# Ubuntu/Debian:
sudo apt purge -y kubelet kubeadm kubectl
sudo apt autoremove -y
sudo apt-mark unhold kubelet kubeadm kubectl

# RHEL/CentOS:
# sudo dnf remove -y kubelet kubeadm kubectl

# 5. Удаление containerd
# Ubuntu/Debian:
sudo apt purge -y containerd.io
sudo rm -rf /etc/containerd /var/lib/containerd

# RHEL/CentOS:
# sudo dnf remove -y containerd.io

# 6. Применение sysctl
sudo sysctl --system

# 7. Перезагрузка
sudo reboot
```

---

## Дополнительная информация

### Безопасность

1. **Минимальные привилегии:** Не запускайте `kubeadm` от имени `root` без необходимости. Используйте `sudo` для каждой команды.
2. **GPG-ключи:** Всегда импортируйте GPG-ключи в `/etc/apt/keyrings/` (не используйте устаревший `apt-key add`).
3. **Репозитории:** Используйте только официальные репозитории (`pkgs.k8s.io`, `download.docker.com`).
4. **Брандмауэр:** Не отключайте firewall в production — настройте правила для необходимых портов.
5. **SELinux:** На RHEL/CentOS переведите в `Permissive` перед установкой; после стабилизации верните в `Enforcing` с правильными контекстами.

### Best Practices

1. **Начинайте с чистой ОС:** Избегайте клонирования VM с одинаковым `machine-id` — это приводит к конфликтам.
2. **Версионная согласованность:** `kubeadm`, `kubelet`, `kubectl` должны быть одной минорной версии.
3. **Фиксируйте версии:** Используйте `apt-mark hold` / `dnf versionlock` для предотвращения случайных обновлений.
4. **Раздельная сеть:** Control Plane и Worker узлы должны быть в одной L2/L3 сети (или иметь маршрутизацию).
5. **SSD для etcd:** Если etcd вынесен на отдельный диск, используйте SSD — etcd чувствителен к задержкам чтения/записи.
6. **Регулярно проверяйте:** Запускайте скрипт верификации (Шаг 10) после каждого обновления системы.
7. **Синхронизация времени:** Обязательно для HA — настройте Chrony до развёртывания kubeadm.
8. **Настройка inotify:** Увеличьте `fs.inotify.max_user_watches` до 524288+ для кластеров с >500 подов.
9. **Бэкап /etc/kubernetes:** После успешной инициализации сделайте бэкап всей директории `/etc/kubernetes/`.
10. **Документируйте:** Храните конфигурации sysctl и containerd в системе контроля версий.

### Диагностика типичных проблем

| Ошибка | Симптом | Причина | Решение |
| :--- | :--- | :--- | :--- |
| **`[ERROR CRI]: container runtime is not running`** | `kubeadm init phase preflight` падает | containerd не запущен или сокет недоступен | `systemctl status containerd`; `ls -la /run/containerd/containerd.sock` |
| **`[ERROR Port-10250]: Port 10250 is in use`** | preflight ошибка | kubelet уже запущен или другой процесс | `fuser -k 10250/tcp`; `systemctl stop kubelet` |
| **`[ERROR Swap]: Running swap is enabled`** | preflight ошибка | SWAP не отключен | `sudo swapoff -a`; проверить `/etc/fstab` |
| **kubelet не запускается** | `systemctl status kubelet` → failed | Неверный cgroup driver или не отключён swap | `journalctl -u kubelet -f`; проверить `config.toml` containerd |
| **`containerd: SystemdCgroup=false`** | Лимиты подов не применяются | containerd не настроен на systemd | `sed -i 's/SystemdCgroup = false/SystemdCgroup = true/' /etc/containerd/config.toml` |
| **`gpg: no valid OpenPGP data found`** | Ошибка apt update | Неверный ключ GPG | Удалите старый ключ, повторите импорт в `/etc/apt/keyrings/` |
| **cgroup2fs не найден** | LSTAT failed: no such file | cgroup v2 не включен | Добавить `systemd.unified_cgroup_hierarchy=1` в GRUB, перезагрузиться |
| **`inotify: too many open files`** | Поды в Pending | Лимит inotify исчерпан | Увеличить `fs.inotify.max_user_watches` до 524288 |
| **conntrack: table full** | Сетевые ошибки, трафик не проходит | Лимит conntrack исчерпан | Увеличить `net.netfilter.nf_conntrack_max` до 1048576 |
| **DNS не работает после init** | CoreDNS CrashLoopBackOff | Неверный `pod-network-cidr` или CNI не установлен | Установите Calico/Cilium: `kubectl apply -f <manifest>` |

### См. также

- **[Инициализация кластера](./cluster_initialization.md)** — следующий этап: запуск первого мастера через `kubeadm init`.
- **[Концепции HA](./ha_concepts.md)** — архитектура отказоустойчивого Control Plane, VRRP, Keepalived vs kube-vip.
- **[Настройка Keepalived и HAProxy](./keepalived_haproxy_setup.md)** — practical настройка балансировщиков для HA.
- **[Присоединение узлов](../HA_Cluster_Bare_Metal/node_joining.md)** — добавление Worker и Control Plane узлов через `kubeadm join`.
- **[Установка компонентов (HA)](../HA_Cluster_Bare_Metal/k8s_ha_component_installation.md)** — альтернативное руководство для HA-кластеров с расширенной настройкой containerd.
