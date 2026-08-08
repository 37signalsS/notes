# Подготовка узлов HA кластера Kubernetes

## Определения

**Подготовка узлов (Node Preparation)** — процесс предварительной настройки операционной системы на всех серверах будущего кластера (Control Plane и Worker) для обеспечения стабильной работы компонентов Kubernetes и Container Runtime.

**cgroups v2** — современная версия контрольных групп Linux. Начиная с Kubernetes 1.25+ (полная поддержка с 1.22), является предпочтительным механизмом управления ресурсами. Необходима для корректной работы лимитов памяти и CPU.

**SWAP (Раздел подкачки)** — область на диске, используемая ОС при нехватке оперативной памяти. Kubernetes требует полного отключения SWAP, так как `kubelet` не умеет учитывать подкачку при планировании ресурсов, что ведет к непредсказуемому поведению подов.

**Синхронизация времени (NTP)** — критически важный процесс для HA-кластеров. Распределенное хранилище `etcd` чувствительно к разнице во времени между узлами; значительный дрейф часов приводит к потере кворума.

---

## Основные концепции

### Зачем нужна подготовка?

Kubernetes — это сложная распределенная система, которая накладывает жесткие требования к конфигурации ядра и сетевого стека Linux:

- **Предсказуемость ресурсов**: отключение SWAP и настройка cgroups обеспечивают соответствие реального потребления ресурсов заданным лимитам.
- **Сетевая связность**: модули `br_netfilter` и `overlay` позволяют трафику проходить через виртуальные мосты и туннели, что необходимо для работы CNI (Container Network Interface).
- **Маршрутизация**: параметр `ip_forward` превращает узел в маршрутизатор, позволяя передавать пакеты между подами на разных хостах.
- **Стабильность etcd**: точное время на всех мастерах предотвращает конфликты при записи в базу данных кластера.

### Область применения

Инструкции данного раздела применимы ко всем типам узлов кластера на базе Linux (Ubuntu, Debian, RHEL/Rocky):
- Control Plane узлы (мастеры)
- Worker узлы

---

## Практические сценарии

### Шаг 1: Обновление системы и установка базовых пакетов

Перед началом настройки необходимо обновить индекс пакетов и установить утилиты, необходимые для работы Kubernetes и сетевой диагностики.

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка необходимых пакетов
sudo apt install -y curl gnupg2 software-properties-common \
     apt-transport-https ca-certificates lsb-release \
     socat conntrack ipset chrony
```

### Шаг 2: Синхронизация времени (Chrony)

Для HA-кластера разница во времени между узлами не должна превышать нескольких миллисекунд.

```bash
# Запуск и включение службы синхронизации
sudo systemctl enable --now chrony

# Проверка статуса синхронизации
chronyc tracking
# → Проверьте поле 'Leap status', должно быть 'Normal'
```

### Шаг 3: Настройка имен хостов и локального разрешения

Каждый узел должен иметь уникальное имя (hostname), которое будет использоваться в Kubernetes API.

#### Установка hostname
```bash
# На каждом узле (замените на соответствующее имя)
sudo hostnamectl set-hostname node-1
```

#### Настройка /etc/hosts
На **всех** узлах добавьте записи обо всех участниках кластера и Virtual IP (VIP) балансировщика. Это обеспечит работу кластера даже при временной недоступности DNS.

```bash
# /etc/hosts
192.168.1.100  kube-api-vip
192.168.1.11   master-1
192.168.1.12   master-2
192.168.1.13   master-3
192.168.1.21   worker-1
192.168.1.22   worker-2
```

### Шаг 4: Отключение SWAP

Kubernetes не поддерживает работу с включенным SWAP (за исключением экспериментальных функций в последних версиях, которые не рекомендуются для production).

```bash
# Немедленное отключение
sudo swapoff -a

# Перманентное отключение в fstab
sudo sed -i '/ swap / s/^\(.*\)$/#\1/g' /etc/fstab

# Проверка (должно быть 0)
free -m | grep Swap
```

### Шаг 5: Загрузка модулей ядра

Для работы сетевого моста и контейнеризации требуются специфические модули. Также рекомендуется загрузить модули для поддержки IPVS (высокопроизводительный режим работы Service).

```bash
# Создание конфигурационного файла для автозагрузки
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
ip_vs
ip_vs_rr
ip_vs_wrr
ip_vs_sh
nf_conntrack
EOF

# Загрузка модулей вручную
sudo modprobe overlay
sudo modprobe br_netfilter
sudo modprobe ip_vs
sudo modprobe ip_vs_rr
sudo modprobe ip_vs_wrr
sudo modprobe ip_vs_sh
sudo modprobe nf_conntrack
```

### Шаг 6: Настройка параметров sysctl

Настройка сетевого стека для корректной работы мостов и маршрутизации.

```bash
cat <<EOF | sudo tee /etc/sysctl.d/99-kubernetes.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1

# Увеличение лимитов на количество открытых файлов и процессов
fs.inotify.max_user_instances = 512
fs.inotify.max_user_watches   = 524288
kernel.panic                  = 10
kernel.panic_on_oops          = 1
net.ipv4.conf.all.rp_filter   = 1
EOF

# Применение параметров
sudo sysctl --system
```

### Шаг 7: Настройка cgroups v2

Для современных дистрибутивов (Ubuntu 22.04+, RHEL 9+) cgroups v2 обычно включен по умолчанию. Проверьте состояние:

```bash
stat -fc %T /sys/fs/cgroup
# → Если результат 'cgroup2fs', настройка не требуется.
# → Если результат 'tmpfs', необходимо добавить параметры загрузки GRUB.
```

Если требуется включение (старые ядра или специфичные дистрибутивы):
1. Отредактируйте `/etc/default/grub`.
2. Добавьте `systemd.unified_cgroup_hierarchy=1` в `GRUB_CMDLINE_LINUX`.
3. Выполните `sudo update-grub` (Debian/Ubuntu) или `sudo grub2-mkconfig -o /boot/grub2/grub.cfg` (RHEL).

### Шаг 8: Настройка системных лимитов

Увеличение лимитов на количество дескрипторов файлов важно для узлов с большим количеством подов.

```bash
cat <<EOF | sudo tee /etc/security/limits.d/k8s.conf
* soft nofile 65536
* hard nofile 65536
* soft nproc 4096
* hard nproc 4096
EOF
```

### Шаг 9: Безопасность и Firewall

Для корректной работы CNI и API рекомендуется либо полностью отключить Firewall (на время установки), либо настроить правила согласно официальной документации.

#### Отключение Firewall
```bash
# Ubuntu/Debian
sudo ufw disable

# RHEL/Rocky
sudo systemctl stop firewalld
sudo systemctl disable firewalld
```

#### Настройка SELinux (для RHEL-based)
Переведите SELinux в режим `Permissive`, чтобы разрешить контейнерам доступ к файловой системе хоста.

```bash
sudo setenforce 0
sudo sed -i 's/^SELINUX=enforcing$/SELINUX=permissive/' /etc/selinux/config
```

### Шаг 10: Итоговая проверка готовности

Скрипт для быстрой проверки состояния узла перед установкой компонентов Kubernetes.

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
```

---

## Дополнительная информация

### Важные замечания

- **Перезагрузка**: Рекомендуется выполнить перезагрузку узла после настройки GRUB или SELinux, чтобы убедиться, что все параметры применились корректно.
- **Интерференция**: Если на узлах установлен `NetworkManager`, убедитесь, что он не управляет интерфейсами, созданными Kubernetes/CNI. Рекомендуется добавить `unmanaged-devices` в конфигурацию NetworkManager.

### Следующие шаги

После завершения подготовки всех узлов переходите к следующему этапу:
1. **[Установка компонентов](./k8s_ha_component_installation.md)** — установка `containerd`, `kubelet` и `kubeadm`.
2. **[Инициализация первого мастера](../kubeadm/cluster_initialization.md)** — запуск кластера.

### Интеграция с документацией

Данный файл является вторым шагом в процессе развертывания HA кластера.
- Предыдущий шаг: **[Требования к среде](./k8s_ha_environment_requirements.md)**
- Справочник по сетевым портам: **[Kubernetes Ports and Protocols](https://kubernetes.io/docs/reference/networking/ports-and-protocols/)**
- Подробнее о cgroups v2: **[Kubernetes cgroup v2 documentation](https://kubernetes.io/docs/concepts/architecture/nodes/#cgroup-v2)**
