# Kubespray: Offline установка — Шаг 1: Подготовка виртуальных серверов

## Определения

**Подготовка виртуальных машин (VM Preparation)** — процесс первичной настройки узлов перед развёртыванием Kubernetes, включающий выделение ресурсов, установку ОС, конфигурацию SSH и системных параметров ядра. Этот этап является отправной точкой критического пути: без корректно подготовленных узлов невозможна автоматизация через Ansible.

**k8s-ans-bootstrap** — вспомогательный Ansible-плейбук для автоматизации базовой подготовки узлов (отключение swap, настройка сетевых модулей, установка python3-apt и т.д.). Используется как альтернатива ручной настройке, позволяя привести операционную систему к состоянию, соответствующему требованиям Kubernetes, за один запуск.

**Ansible Control Node (Узел управления)** — сервер, с которого запускаются плейбуки Ansible для развертывания и управления кластером. В offline-сценарии это `master-1` (192.168.1.101). Требования: Python 3.10+, установленный Ansible, SSH-доступ по ключам ко всем целевым узлам.

**Become (Привилегии sudo)** — механизм Ansible для выполнения задач от имени суперпользователя (`root`). На целевых узлах должен быть настроен беспарольный sudo для пользователя автоматизации, чтобы плейбуки не останавливались на запросе пароля.

**Синхронизация времени (NTP/Chrony)** — критически важный процесс для кластера. etcd чувствителен к разнице во времени между узлами: даже расхождение в несколько секунд приводит к невалидности TLS-сертификатов и потере кворума. В offline-среде необходимо настроить локальный NTP-источник или внутренний сервер времени.

**Hostname (Имя хоста)** — уникальное, стабильное имя узла, которое Kubernetes использует для идентификации нод в API. Kubespray требует, чтобы имя не менялось после перезагрузки. Рекомендуется формат FQDN (например, `master-1.domain.local`).

**sysctl** — утилита для динамической настройки параметров ядра Linux без перезагрузки. Kubernetes требует включения параметров маршрутизации (`ip_forward`), фильтрации трафика на виртуальных мостах (`bridge-nf-call-iptables`) и увеличения лимитов на открытые файлы.

**Модули ядра (Kernel Modules)** — загружаемые динамически компоненты ядра, расширяющие его функциональность. Kubernetes требует модулей `overlay` (для виртуальных файловых систем контейнеров) и `br_netfilter` (для фильтрации трафика на сетевых мостах). Модули `ip_vs*` загружаются для поддержки IPVS — высокопроизводительного режима работы Service.

**cgroups v2** — современная версия контрольных групп Linux, обеспечивающая изоляцию ресурсов (CPU, память) для контейнеров. Kubernetes 1.25+ использует cgroups v2 по умолчанию. Проверяется командой `stat -fc %T /sys/fs/cgroup` — результат `cgroup2fs` означает корректную настройку.

---

## Основные концепции

### Критичность этого этапа

Подготовка узлов — это фундамент всего развёртывания. Ошибки на этом этапе имеют мультипликативный эффект:

- **Неверный hostname** → Ansible не сможет идентифицировать узлы → kubeadm init завершится с ошибкой.
- **Активный SWAP** → kubelet не запустится → ни один под не будет создан.
- **Отсутствие модулей ядра** → сетевой стек CNI не работает → поды не пингуются между узлами.
- **Рассинхронизация времени** → TLS-сертификаты невалидны → API-сервер недоступен.
- **Нет беспарольного sudo** → каждый запуск Ansible требует ручного ввода пароля → автоматизация невозможна.

Стоимость исправления ошибки на этом этапе минимальна (нет зависимых компонентов), в то время как исправление после deploy кластера требует полного переустановки.

### Требования к операционной системе

Kubespray официально поддерживает Ubuntu 22.04/24.04 LTS, Debian 11/12, RHEL/Rocky 8/9. Для offline-установки рекомендуется **Ubuntu 24.04 LTS** по следующим причинам:

- **Долгосрочная поддержка (LTS):** 5 лет обновлений безопасности (до 2029).
- **APT-пакеты:** более широкий выбор пакетов по сравнению с Debian.
- **systemd по умолчанию:** корректная работа с cgroups v2 без дополнительной настройки GRUB.
- **Нет SELinux:** отсутствие дополнительной настройки Mandatory Access Control (в отличие от RHEL).

### Минимальная конфигурация виртуальных машин

Параметры ресурсов (CPU/RAM/SSD) для каждого узла должны соответствовать **[Инфраструктурному плану](./offline_practical.md#инфраструктурный-план-кластера)**. Ключевые требования:

| Параметр | Control Plane | Worker | Причина |
| :--- | :--- | :--- | :--- |
| **CPU** | 2 ядра | 4 ядра | etcd чувствителен к CPU-bound нагрузке |
| **RAM** | 4 ГБ | 8 ГБ | Minimum для kubelet + системные поды |
| **Диск** | 50 ГБ SSD | 100 ГБ SSD | etcd требует SSD (fsync задержки <1 мс) |
| **Сеть** | 1 Гбит/с | 1 Гбит/с | Сетевой стек CNI генерирует значительный трафик |

**Почему SSD обязателен:** etcd выполняет синхронную запись (fsync) при каждой транзакции. HDD добавляет задержки 5-15 мс против 0.1 мс для SSD, что вызывает таймауты и расщепление кластера etcd.

### Сетевые порты

Перед подготовкой узлов убедитесь, что следующие порты доступны между всеми участниками кластера:

| Порт | Протокол | Назначение | Между какими узлами |
| :--- | :--- | :--- | :--- |
| **22** | TCP | SSH (Ansible) | Control Node -> Все узлы |
| **6443** | TCP | Kubernetes API Server | Control Plane <-> Все узлы |
| **2379-2380** | TCP | etcd client & peer | Control Plane <-> Control Plane |
| **10250** | TCP | kubelet API | Control Plane <-> Worker |
| **10251** | TCP | kube-scheduler | Control Plane <-> Control Plane |
| **10252** | TCP | kube-controller-manager | Control Plane <-> Control Plane |
| **30000-32767** | TCP | NodePort Services | Внешний доступ к Service |
| **8472** | UDP | VXLAN (Cilium) | Между всеми узлами (CNI) |

> **Важно:** Сетевые задержки между узлами etcd не должны превышать 10 мс. Это критично для стабильности кворума. Если узлы расположены в разных стойках илиДата-центрах — проверьте RTT командой `ping`.

---

## Практические сценарии

### Полный алгоритм подготовки узлов

Данный сценарий описывает пошаговую подготовку **каждого узла** кластера. Выполняется на всех 7 узлах (pc-inet, harbor, master-1..3, node-1..2) после развёртывания ВМ и назначения IP-адресов.

#### Шаг 1.1: Обновление системы и установка базовых пакетов

На **каждом узле** выполните:

```bash
# Обновление индекса пакетов и установка зависимостей
sudo apt update && sudo apt upgrade -y

# Установка пакетов, необходимых для работы Kubernetes и диагностики
sudo apt install -y curl gnupg2 software-properties-common \
     apt-transport-https ca-certificates lsb-release \
     socat conntrack ipset chrony python3 python3-apt
```

**Почему именно эти пакеты:**
- `python3`, `python3-apt` — требуются Ansible для управления пакетами на целевых узлах.
- `chrony` — синхронизация времени (критично для etcd и TLS).
- `socat` — используется kubeadm для проксирования API-сервера.
- `conntrack` — отслеживание сетевых соединений (требуется CNI).
- `ipset` — используется kube-proxy для оптимизации правил iptables.
- `lsb-release` — определение версии дистрибутива.

**Валидация:**
```bash
python3 --version && python3-apt --version
# → Python 3.12.x

apt list --installed | grep -E "chrony|socat|conntrack"
# → chrony, socat, conntrack установлены
```

#### Шаг 1.2: Синхронизация времени (Chrony)

**Почему это критично:** Сертификаты Kubernetes и Harbor привязаны к времени. Если часы на узле отстают/опережают, TLS-Handshake завершается неудачей. В offline-среде нет доступа к внешним NTP-серверам, поэтому необходимо настроить локальный источник.

На **каждом узле** выполните:

```bash
# Запуск и включение службы синхронизации
sudo systemctl enable --now chrony

# Если есть внутренний NTP-сервер — настройте /etc/chrony/chrony.conf:
# server 192.168.1.1 iburst
# Или если NTP-сервера нет — локальный stratum (на harbor или master-1):
# pool 127.127.1.0 iburst

# Проверка статуса синхронизации
chronyc tracking
# → Проверьте поле 'Leap status', должно быть 'Normal'
# → System time : 0.000001234 seconds fast of NTP time
```

> **Совет для offline-среды:** Если внутренний NTP-сервер недоступен, настройте один узел (например, harbor) как локальный NTP-источник, а остальные — как клиентов. Подробности в **[Chrony — NTP-сервер](../../../../Linux/Networking/Services/chrony_ntp.md)**.

**Валидация:**
```bash
# На всех узлах проверьте разницу во времени
chronyc tracking | grep "System time"
# → System time : 0.000001234 seconds fast of NTP time
# → Допустимо: расхождение не более 1-2 секунд
```

#### Шаг 1.3: Настройка имён хостов (Hostname)

Каждый узел должен иметь уникальное, стабильное имя. Kubernetes использует hostname для идентификации нод в API.

На **каждом узле** выполните:

```bash
# Установка hostname (замените на соответствующее имя)
sudo hostnamectl set-hostname master-1  # или harbor, pc-inet, master-2, ...

# Проверка
hostname
# → master-1
```

#### Шаг 1.4: Настройка /etc/hosts

На **всех** узлах добавьте записи обо всех участниках кластера. Это обеспечит работу DNS-разрешения даже при временной недоступности DNS-сервера.

```bash
# Добавление записей (выполните на каждом узле)
cat <<EOF | sudo tee -a /etc/hosts
# Kubespray Offline Cluster
192.168.1.99    pc-inet
192.168.1.100   harbor
192.168.1.101   master-1
192.168.1.102   master-2
192.168.1.103   master-3
192.168.1.104   node-1
192.168.1.105   node-2
EOF
```

**Валидация:**
```bash
# Проверка разрешения имён
for host in pc-inet harbor master-1 master-2 master-3 node-1 node-2; do
  ping -c 1 -W 1 $host >/dev/null 2>&1 && echo "$host: OK" || echo "$host: FAILED"
done
# → Ожидаемый результат: все 7 хостов отвечают
```

#### Шаг 1.5: Отключение SWAP

Kubernetes не поддерживает работу с включенным SWAP (за исключением экспериментальных функций, которые не рекомендуются для production). kubelet не умеет учитывать подкачку при планировании ресурсов, что ведет к непредсказуемому поведению подов.

На **каждом узле** выполните:

```bash
# Немедленное отключение
sudo swapoff -a

# Перманентное отключение в fstab (чтобы не включался после перезагрузки)
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# Проверка (должно быть 0 записей)
free -m | grep Swap
# → Swap:            0          0          0
```

#### Шаг 1.6: Загрузка модулей ядра

Для работы сетевого моста и контейнеризации требуются специальные модули ядра. Также загружаются модули для поддержки IPVS — высокопроизводительного режима работы Service.

На **каждом узле** выполните:

```bash
# Создание конфигурационного файла для автозагрузки модулей
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
ip_vs
ip_vs_rr
ip_vs_wrr
ip_vs_sh
nf_conntrack
EOF

# Ручная загрузка модулей (без перезагрузки)
sudo modprobe overlay
sudo modprobe br_netfilter
sudo modprobe ip_vs
sudo modprobe ip_vs_rr
sudo modprobe ip_vs_wrr
sudo modprobe ip_vs_sh
sudo modprobe nf_conntrack
```

**Почему именно эти модули:**
- `overlay` —_overlay filesystem для контейнерных образов (используется containerd).
- `br_netfilter` — фильтрация трафика на виртуальных мостах (необходимо для работы iptables с подами).
- `ip_vs*` — IP Virtual Server, высокопроизводительный балансировщик трафика для Service (альтернатива iptables-based kube-proxy).
- `nf_conntrack` — отслеживание сетевых соединений (требуется для корректной работы NAT).

**Валидация:**
```bash
# Проверка загруженных модулей
lsmod | grep -E "overlay|br_netfilter|ip_vs"
# → overlay                1xxxx  0
# → br_netfilter           1xxxx  0
# → ip_vs                  1xxxx  0
```

#### Шаг 1.7: Настройка параметров sysctl

Настройка сетевого стека для корректной работы мостов, маршрутизации и увеличения лимитов на количество открытых файлов.

На **каждом узле** выполните:

```bash
cat <<EOF | sudo tee /etc/sysctl.d/99-kubernetes.conf
# Маршрутизация и фильтрация трафика на виртуальных мостах
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1

# Увеличение лимитов на количество открытых файлов и процессов
# Критично для узлов с большим количеством подов
fs.inotify.max_user_instances = 512
fs.inotify.max_user_watches   = 524288

# Автоперезагрузка при панике ядра (10 секунд)
kernel.panic                  = 10
kernel.panic_on_oops          = 1

# Strict reverse path filtering (безопасность сети)
net.ipv4.conf.all.rp_filter   = 1
EOF

# Применение параметров без перезагрузки
sudo sysctl --system
```

**Почему эти параметры критичны:**
- `ip_forward=1` — превращает узел в маршрутизатор, позволяя передавать пакеты между подами на разных хостах.
- `bridge-nf-call-iptables=1` — направляет трафик через виртуальный мост на обработку в iptables (необходимо для NetworkPolicy и Service).
- `inotify.max_user_watches` — предотвращает ошибки «No space left on device» при большом количестве подов и Watching конфигурационных файлов.

**Валидация:**
```bash
# Проверка критических параметров
sysctl net.ipv4.ip_forward net.bridge.bridge-nf-call-iptables
# → net.ipv4.ip_forward = 1
# → net.bridge.bridge-nf-call-iptables = 1
```

#### Шаг 1.8: Проверка cgroups v2

Современные версии Kubespray (v2.24+) ориентированы на использование cgroups v2. Ubuntu 24.04 включает cgroups v2 по умолчанию.

На **каждом узле** выполните:

```bash
stat -fc %T /sys/fs/cgroup
# → cgroup2fs — OK (настройка не требуется)
# → tmpfs — необходимо включить в GRUB: systemd.unified_cgroup_hierarchy=1
```

Если результат `tmpfs` (старые ядра или специфичные дистрибутивы):

```bash
# Редактирование GRUB
sudo sed -i 's/GRUB_CMDLINE_LINUX=""/GRUB_CMDLINE_LINUX="systemd.unified_cgroup_hierarchy=1"/' /etc/default/grub
sudo update-grub

# Перезагрузка для применения
sudo reboot
```

#### Шаг 1.9: Настройка Firewall

Для корректной работы CNI и Kubernetes API необходимо обеспечить доступность портов из таблицы выше. Рекомендуется **временно отключить Firewall** на время установки, затем настроить правила согласно документации.

На **каждом узле** выполните:

```bash
# Ubuntu/Debian: временное отключение
sudo ufw disable

# Или включение特定 портов (альтернатива полному отключению):
# sudo ufw allow 22/tcp    # SSH
# sudo ufw allow 6443/tcp  # Kubernetes API
# sudo ufw allow 10250/tcp # kubelet API
# sudo ufw reload
```

> **Важно:** В production-среде Firewall должен быть активен. Отключение допускается только на этапе установки и диагностики.

#### Шаг 1.10: Настройка системных лимитов

Увеличение лимитов на количество дескрипторов файлов и процессов. Это предотвращает ошибки при большом количестве подов.

На **каждом узле** выполните:

```bash
cat <<EOF | sudo tee /etc/security/limits.d/k8s.conf
* soft nofile 65536
* hard nofile 65536
* soft nproc 4096
* hard nproc 4096
EOF
```

#### Шаг 1.11: Проверка SSH-доступа с master-1

После подготовки всех узлов необходимо убедиться в работоспособности SSH-соединения с `master-1` (Ansible Control Node).

**1. Генерация ключа на master-1:**

```bash
# На master-1
ssh-keygen -t rsa -b 4096 -N "" -f ~/.ssh/id_rsa
# → Generating public/private rsa key pair.
# → Параметр -t rsa chosen для максимальной совместимости.
# → Альтернатива: ssh-keygen -t ed25519 (более быстрый, но менее совместимый).
```

**2. Добавление ключа в ssh-agent:**

```bash
eval $(ssh-agent -s)
ssh-add ~/.ssh/id_rsa
# → Identity added: /home/admin/.ssh/id_rsa
```

**3. Копирование ключа на все узлы:**

```bash
# Инфраструктурные узлы
ssh-copy-id admin@192.168.1.99   # pc-inet
ssh-copy-id admin@192.168.1.100  # harbor

# Узлы Kubernetes
ssh-copy-id admin@192.168.1.101  # master-1 (self)
ssh-copy-id admin@192.168.1.102  # master-2
ssh-copy-id admin@192.168.1.103  # master-3
ssh-copy-id admin@192.168.1.104  # node-1
ssh-copy-id admin@192.168.1.105  # node-2
```

**4. Проверка беспарольного sudo:**

```bash
ssh admin@192.168.1.102 "sudo whoami"
# → root
```

**5. Проверка SSH-доступа ко всем узлам:**

```bash
for ip in 192.168.1.{99,100,101,102,103,104,105}; do
  ssh -o BatchMode=yes admin@$ip "hostname" 2>/dev/null && echo "$ip: SSH OK" || echo "$ip: SSH FAILED"
done
# → Ожидаемый результат: все 7 IP отвечают
```

### Автоматизация подготовки через k8s-ans-bootstrap

Вместо ручного выполнения шагов 1.1-1.10 можно использовать Ansible-плейбук, который выполняет все операции автоматически.

**1. Клонирование репозитория (выполняется на pc-inet или master-1):**

```bash
git clone https://github.com/ZM56/k8s-ans-bootstrap.git
# → Cloning into 'k8s-ans-bootstrap'...
```

**2. Настройка inventory.ini:**

Отредактируйте файл `inventory.ini`, указав IP всех узлов согласно **[Инфраструктурному плану](./offline_practical.md#инфраструктурный-план-кластера)**:

```ini
[all]
master-1 ansible_host=192.168.1.101
master-2 ansible_host=192.168.1.102
master-3 ansible_host=192.168.1.103
node-1   ansible_host=192.168.1.104
node-2   ansible_host=192.168.1.105
harbor   ansible_host=192.168.1.100
pc-inet  ansible_host=192.168.1.99

[all:vars]
ansible_user=admin
ansible_become=yes
```

**3. Запуск плейбука:**

```bash
cd k8s-ans-bootstrap
ansible-playbook -i inventory.ini play.yml -u admin -b
# → PLAY RECAP ***************** master-1 : ok=15 changed=10 ...
```

**Что выполняет плейбук k8s-ans-bootstrap:**
- Обновление системы и установка базовых пакетов
- Отключение SWAP
- Настройка модулей ядра (overlay, br_netfilter)
- Применение параметров sysctl
- Проверка cgroups v2
- Установка python3-apt и зависимостей Ansible

### Итоговая проверка готовности узла

Скрипт для быстрой проверки состояния узла перед запуском Ansible-плейбуков. Выполните на **любом** узле:

```bash
#!/bin/bash
echo "--- ПРОВЕРКА ГОТОВНОСТИ УЗЛА ---"

# 1. SWAP
if [ "$(swapon --show | wc -l)" -eq 0 ]; then
    echo "[OK] Swap отключен"
else
    echo "[FAIL] Swap активен!"
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

# 4. Время
if chronyc tracking > /dev/null 2>&1; then
    echo "[OK] Служба времени активна"
else
    echo "[FAIL] Проблемы с синхронизацией времени!"
fi

# 5. Python
if python3 --version > /dev/null 2>&1; then
    echo "[OK] Python3 установлен"
else
    echo "[FAIL] Python3 не найден!"
fi

# 6. SSH
if ssh -o BatchMode=yes localhost "echo ok" > /dev/null 2>&1; then
    echo "[OK] SSH работает"
else
    echo "[WARN] SSH-ключи могут быть не настроены"
fi

echo "--- ПРОВЕРКА ЗАВЕРШЕНА ---"
```

> Подробный алгоритм глубокой настройки ОС доступен в **[SSoT: Подготовка узлов](../../HA_Cluster_Bare_Metal/k8s_ha_node_preparation.md)**.

---

## Дополнительная информация

### Типовые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied (publickey)` | SSH-ключ не скопирован или ssh-agent не запущен | `ssh-copy-id`, `eval $(ssh-agent -s)`, `ssh-add` |
| `sudo: a password is required` | Не настроен NOPASSWD для sudo | Добавьте в `/etc/sudoers.d/<user>`: `user ALL=(ALL) NOPASSWD:ALL` |
| `swap is active` | SWAP не отключен или включился после перезагрузки | `swapoff -a`, закомментируйте swap в `/etc/fstab` |
| `cgroup2fs` не отображается | cgroups v2 не включен | Параметр GRUB `systemd.unified_cgroup_hierarchy=1` + `update-grub` + reboot |
| `No route to host` | Firewall блокирует порты | Откройте порты из таблицы или `ufw disable` на время установки |
| `Connection refused` (SSH) | SSH-сервис не запущен или порт 22 заблокирован | `sudo systemctl enable --now ssh`, проверьте Firewall |
| `Module br_netfilter not found` | Модуль не загружен | `sudo modprobe br_netfilter`, добавьте в `/etc/modules-load.d/k8s.conf` |
| `System time off by N sec` | Рассинхронизация NTP | Настройте `chrony`, укажите внутренний NTP-сервер |

### Оптимизации для offline-среды

- **Локальный APT-кэш:** настройте `apt-cacher-ng` или `squid-deb-proxy` на pc-inet для кэширования пакетов. Это ускорит установку пакетов на остальных узлах.
- **Параллельная подготовка:** если используется k8s-ans-bootstrap, увеличьте `forks` в `ansible.cfg` для параллельной подготовки всех узлов.
- **Шаблон VM:** создайте один шаблон ВМ с подготовленной ОС и клонируйте его для всех узлов. Это исключает необходимость повторения шагов 1.1-1.10.
- **Preseed/Autoinstall:** для массового развёртывания используйте Ubuntu Autoinstall (cloud-init) с предустановленными пакетами и параметрами.

### Перезагрузка после настройки

После выполнения шагов 1.1-1.10 рекомендуется **перезагрузить все узлы** для применения изменений GRUB (cgroups v2), модулей ядра и параметров sysctl:

```bash
# На всех узлах (с master-1)
for ip in 192.168.1.{99,100,101,102,103,104,105}; do
  ssh admin@$ip "sudo reboot" &
done
wait
# → Все узлы перезагружаются одновременно

# Ожидание восстановления SSH-доступа (1-2 минуты)
sleep 120
for ip in 192.168.1.{99,100,101,102,103,104,105}; do
  ssh -o BatchMode=yes admin@$ip "hostname" 2>/dev/null && echo "$ip: OK" || echo "$ip: PENDING"
done
```

### См. также

- **[SSoT: Подготовка узлов K8s](../../HA_Cluster_Bare_Metal/k8s_ha_node_preparation.md)** — универсальный справочник по настройке ОС (sysctl, модули, cgroups).
- **[Шаг 2: Подготовка окружения с интернетом](./step2_internet_env.md)** — следующий этап (загрузка артефактов).
- **[Практические сценарии offline-установки](./offline_practical.md)** — сводная таблица и IP-план.
