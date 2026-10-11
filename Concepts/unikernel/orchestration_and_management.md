# Оркестрация и управление Unikernel

**Актуально для:** Unikraft v0.21.0, KraftKit v0.12.15, Nanos (актуальная ветка), MirageOS v4.11.x, OSv v0.57.0; примеры для on-premise развёртываний

## Предварительные требования

### Аппаратные требования (хост)

- **CPU:** x86_64 с поддержкой аппаратной виртуализации (Intel VT-x / AMD-V). Минимум 4 cores для production.
- **RAM:** 4 ГБ минимум (для хоста + 2-3 юникернелов). Для продакшена — 16+ ГБ.
- **Диск:** SSD/NVMe для golden images и snapshot'ов. Минимум 20 ГБ свободного места.
- **Сеть:** NIC с поддержкой VLAN (802.1Q), bonding (LACP), multi-queue.

### Программные требования (on-premise, Linux хост)

| Компонент | Версия | Назначение |
| :--- | :--- | :--- |
| **QEMU** | ≥ 7.2 | Эмуляция/виртуализация |
| **Kernel** | ≥ 5.15 | Драйверы virtio, KVM |
| **libvirt** | ≥ 9.0 | Управление VM lifecycle |
| **KraftKit** | v0.12.15 | Сборка и запуск юникернелов |
| **Python** | ≥ 3.10 | Ansible, libvirt Python bindings |
| **Terraform** | ≥ 1.7 | IaC для KVM |
| **Podman** | ≥ 4.8 | Регистрарий образов (on-premise) |
| **Podman** | ≥ 4.8 | Регистрарий образов (on-premise) |
| **chrony** | ≥ 4.3 | NTP-синхронизация хоста |

### Инициализация хоста

```bash
# Проверка аппаратной виртуализации
grep -E 'vmx|svm' /proc/cpuinfo
# → vmx (Intel) или svm (AMD)

# Загрузка модулей KVM
sudo modprobe kvm_intel   # или kvm_amd
sudo modprobe virtio

# Включение IP forwarding (если юникернелы должны быть доступны извне)
sudo sysctl -w net.ipv4.ip_forward=1
echo 'net.ipv4.ip_forward = 1' | sudo tee -a /etc/sysctl.d/99-unikernel.conf

# Добавление пользователя в группы
sudo usermod -aG kvm $USER
sudo usermod -aG libvirt $USER

# Перезагрузка для применения групп
newgrp kvm
newgrp libvirt
```

## Определения

**Оркестрация и управление юникернелами** — это совокупность методов, инструментов и практик для развёртывания, масштабирования, наблюдения и обновления юникернелов в production-среде. В отличие от контейнеров, юникернелы не имеют стандартного CRI и orchestrator'а, поэтому оркестрация строится на уровне гипервизора (KVM/QEMU) или через надстройки Kubernetes (KubeVirt).

Базовая информация об архитектуре — в [Обзоре Unikernel](./unikernel_overview.md), сравнение с другими технологиями — в [Преимуществах и ограничениях](./unikernel_advantages_disadvantages.md).

## Основные концепции

### Архитектура управления

Юникернел не имеет встроенного runtime для управления (нет systemd, нет SSH, нет API-сервера). Управление строится тремя слоями:

1. **Библиотечный слой (KraftKit / OPS / libvirt):** CLI-инструменты для сборки, запуска и остановки инстансов.
2. **Слой гипервизора (KVM/QEMU):** Ядро виртуализации, обеспечивающее аппаратную изоляцию.
3. **Слой оркестрации (KubeVirt / Ansible / Terraform / скрипты):** Автоматизация жизненного цикла на уровне инфраструктуры.

### Сравнение методов развёртывания

| Метод | Управление | Масштабирование | Сложность |
| :--- | :--- | :--- | :--- |
| **QEMU + systemd** | `virsh`, `systemctl` | Ручное / скрипты | Низкая |
| **QEMU + libvirt** | `virsh`, `virt-manager` | Автоматическое (CPU/RAM limits) | Средняя |
| **KubeVirt** | Kubernetes API | Нативное (HPA, node selector) | Высокая |
| **Firecracker + containerd** | Kubernetes API | Нативное | Высокая |

### Жизненный цикл инстанса

```
Сборка → Регистрация → Запуск → Проверка → Трафик → Мониторинг → Остановка → Очистка
```

**Ключевое отличие от Docker:** В Docker `docker run` = запуск существующего образа. В юникернеле `kraft run` = сборка ELF-бинарника + упаковка в bootable disk + запуск. Это делает immutable infrastructure обязательным, а not-in-place updates — невозможными.

## Практические сценарии

### 1. Управление через libvirt/virsh

libvirt — стандартный инструмент для управления KVM/QEMU в Linux. Подходит для сред, где не требуется Kubernetes.

#### Установка и настройка

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y \
  qemu-system-x86 qemu-utils \
  libvirt-daemon-system libvirt-clients \
  bridge-utils virtinst virt-manager

# Добавление пользователя в группы
sudo usermod -aG kvm $USER
sudo usermod -aG libvirt $USER

# Включение и запуск libvirtd
sudo systemctl enable --now libvirtd
```

#### Создание VM с юникернелом

```bash
# Создание пула хранилища
virsh pool-create-as --name unikernels --type dir --target /var/lib/libvirt/images/unikernels

# Импорт образа
sudo cp build/my-service-qemu-x86_64 /var/lib/libvirt/images/unikernels/

# Создание XML-дефиниции
cat <<EOF > /tmp/unikernel.xml
<domain type='kvm'>
  <name>my-service</name>
  <memory unit='M'>256</memory>
  <vcpu placement='static'>2</vcpu>
  <os>
    <type arch='x86_64' machine='pc'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
  </features>
  <cpu mode='host-passthrough'/>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='/var/lib/libvirt/images/unikernels/my-service-qemu-x86_64'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='bridge'>
      <source bridge='br0'/>
      <model type='virtio'/>
    </interface>
    <console type='pty'/>
  </devices>
</domain>
EOF

# Запуск
virsh define /tmp/unikernel.xml
virsh start my-service

# Проверка
virsh list
# → my-service  running
```

#### Управление жизненным циклом

```bash
# Остановка
virsh shutdown my-service
# или принудительно
virsh destroy my-service

# Статус
virsh domstate my-service
# → running

# Консоль (если доступна)
virsh console my-service

# Удаление
virsh undefine my-service
```

### 2. Автоматизация через Ansible

Ansible используется для управления конфигурацией хостов, развертывания юникернелов и интеграции с существующей инфраструктурой.

#### Структура плейбука

```yaml
---
- name: Deploy Unikernel on KVM host
  hosts: kvm_hosts
  become: yes
  vars:
    unikernel_name: my-service
    unikernel_image: /var/lib/libvirt/images/unikernels/my-service-qemu-x86_64
    unikernel_memory: 256
    unikernel_vcpus: 2
    unikernel_bridge: br0

  tasks:
    - name: Ensure libvirt is installed
      apt:
        name:
          - qemu-system-x86
          - libvirt-daemon-system
          - bridge-utils
        state: present
        update_cache: yes

    - name: Ensure kvm group exists
      group:
        name: kvm
        state: present

    - name: Ensure user is in kvm group
      user:
        name: "{{ ansible_user }}"
        groups: kvm
        append: yes

    - name: Ensure libvirtd is running
      systemd:
        name: libvirtd
        state: started
        enabled: yes

    - name: Deploy unikernel image
      copy:
        src: "{{ unikernel_image }}"
        dest: "/var/lib/libvirt/images/unikernels/{{ unikernel_name }}.qcow2"
        mode: '0644'

    - name: Create libvirt XML definition
      template:
        src: templates/unikernel.xml.j2
        dest: "/tmp/{{ unikernel_name }}.xml"
      delegate_to: localhost

    - name: Define VM in libvirt
      command: virsh define /tmp/{{ unikernel_name }}.xml
      args:
        creates: "/etc/libvirt/qemu/{{ unikernel_name }}.xml"

    - name: Start VM
      command: virsh start {{ unikernel_name }}
      register: virsh_start
      changed_when: "' started' in virsh_start.stdout"

    - name: Wait for VM to be ready
      wait_for:
        host: "{{ ansible_host }}"
        port: 8080
        delay: 10
        timeout: 60
```

#### Шаблон XML

```jinja2
<!-- templates/unikernel.xml.j2 -->
<domain type='kvm'>
  <name>{{ unikernel_name }}</name>
  <memory unit='M'>{{ unikernel_memory }}</memory>
  <vcpu placement='static'>{{ unikernel_vcpus }}</vcpu>
  <os>
    <type arch='x86_64' machine='pc'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
  </features>
  <cpu mode='host-passthrough'/>
  <devices>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='/var/lib/libvirt/images/unikernels/{{ unikernel_name }}.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <interface type='bridge'>
      <source bridge='{{ unikernel_bridge }}'/>
      <model type='virtio'/>
    </interface>
    <console type='pty'/>
  </devices>
</domain>
```

### 3. Инфраструктура как код (Terraform)

Terraform используется для управления инфраструктурой KVM-хостов и ВМ. Подходит для сред, где требуется reproducible инфраструктура.

#### Структура модуля

```hcl
# modules/unikernel/main.tf
resource "libvirt_volume" "unikernel" {
  name   = "${var.name}-disk"
  pool   = var.storage_pool
  source = var.image_path
  format = "qcow2"
}

resource "libvirt_domain" "unikernel" {
  name   = var.name
  memory = var.memory_mb
  vcpu   = var.vcpu

  cpu {
    mode = "host-passthrough"
  }

  boot_device {
    dev = ["hd"]
  }

  disk {
    volume_id = libvirt_volume.unikernel.id
  }

  network_interface {
    bridge = var.network_bridge
    model  = "virtio"
  }

  console {
    type        = "pty"
    target_port = "0"
    target_type = "serial"
  }
}
```

#### Использование модуля

```hcl
# environments/prod/unikernels.tf
module "dns_server" {
  source = "../../modules/unikernel"

  name          = "dns-server"
  image_path    = "/var/lib/libvirt/images/unikernels/dns-server.qcow2"
  memory_mb     = 256
  vcpu          = 2
  network_bridge = "br0"
  storage_pool  = "unikernels"

  tags = {
    service = "dns"
    env     = "prod"
  }
}
```

### 4. Kubernetes: KubeVirt

KubeVirt позволяет запускать виртуальные машины (в том числе с юникернелами) как нативные ресурсы Kubernetes.

#### Установка KubeVirt

```bash
# Создание CRD
kubectl create -f https://github.com/kubevirt/kubevirt/releases/latest/download/kubevirt-operator.yaml

# Дождаться готовности
kubectl -n kubevirt wait pod -l kubevirt.io=kubevirt --for=condition=Ready
```

#### Создание VirtualMachine

```yaml
apiVersion: kubevirt.io/v1
kind: VirtualMachine
metadata:
  name: unikernel-dns
  namespace: default
spec:
  running: true
  template:
    spec:
      domain:
        cpu:
          cores: 2
        devices:
          disks:
            - disk:
                bus: virtio
              name: containerdisk
          interfaces:
            - masquerade: {}
              model: virtio
              name: default
        resources:
          requests:
            memory: 256Mi
      evictionStrategy: LiveMigrate
      networks:
        - name: default
          pod: {}
      volumes:
        - containerDisk:
            image: registry.example.com/unikernel-dns:v1
          name: containerdisk
```

#### Service и доступ

```yaml
apiVersion: v1
kind: Service
metadata:
  name: unikernel-dns
spec:
  ports:
    - port: 53
      protocol: UDP
  selector:
    kubevirt.io/domain: unikernel-dns
```

### 5. Обнаружение сервисов (Service Discovery)

Юникернелы не имеют встроенного service discovery. Применяются три подхода:

1. **Статический DNS:** Записи в BIND/PowerDNS с фиксированными IP.
2. **Consul/Nomad:** Регистрация внешнего скрипта при запуске инстанса.
3. **Prometheus SD:** Файловый или HTTP-based discovery для мониторинга.

#### Пример: Consul integration

```bash
#!/bin/bash
# /usr/local/bin/register-unikernel.sh
# Регистрация юникернела в Consul

UNIKERNEL_NAME="dns-server"
UNIKERNEL_IP="10.0.0.10"
UNIKERNEL_PORT="53"

curl -X PUT http://localhost:8500/v1/agent/service/register \
  -d "{
    \"ID\": \"${UNIKERNEL_NAME}\",
    \"Name\": \"${UNIKERNEL_NAME}\",
    \"Address\": \"${UNIKERNEL_IP}\",
    \"Port\": ${UNIKERNEL_PORT},
    \"Check\": {
      \"TCP\": \"${UNIKERNEL_IP}:${UNIKERNEL_PORT}\",
      \"Interval\": \"10s\",
      \"Timeout\": \"1s\"
    }
  }"
```

### 6. Стратегии развёртывания

#### Blue-Green

```
Blue (v1) — 100% трафика
    ↓
Запуск Green (v2) параллельно
    ↓
Валидация Green (curl, nmap, метрики)
    ↓
Переключение трафика на Green
    ↓
Остановка Blue
```

```bash
# Запуск Green
kraft run --headless --background --name my-service-green -p 8081:80 ./build/my-app-v2

# Валидация
curl -s http://localhost:8081/health | jq .status
# → "ok"

# Переключение трафика (через nginx upstream)
sed -i 's/my-service-blue:8080/my-service-green:8081/' /etc/nginx/upstream.conf
nginx -s reload

# Остановка Blue
kraft stop my-service-blue
```

#### Canary

```
Stable (v1) — 95% трафика
Canary (v2) — 5% трафика
    ↓
Мониторинг error rate, latency p99
    ↓
Если OK → увеличиваем вес Canary
    ↓
Полный rollout
```

```bash
# Запуск Canary (1 инстанс из 20)
kraft run --headless --background --name my-service-canary -p 8081:80 ./build/my-app-v2

# Валидация через 5 минут
for i in {1..50}; do
  curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/
done | grep -c "200" | awk '{print $1/50*100 "% успешных"}'
```

### 7. Мониторинг и алертинг

Подробные практические сценарии, правила Prometheus и Grafana-дашборды см. в SSoT:
[Мониторинг и алертинг](./monitoring_and_alerting.md).

### 8. Capacity planning

#### Методология

1. **Определите baseline:** Замерьте RAM/CPU/диск под типичную нагрузку.
2. **Учтите overhead QEMU:** ~5-10% RAM на инстанс.
3. **Расчитайте плотность:** Начните с 20-30 юникернелов на хост (16 cores, 32 GB RAM).
4. **Запланируйте запас:** 20% на пиковые нагрузки.

#### Формула

```
Плотность = (Общая RAM - RAM_под_систему) / (RAM_на_инстанс + overhead_QEMU)

Пример:
(32 ГБ - 2 ГБ) / (64 МБ + 8 МБ) = 375 инстансов (теоретический максимум)
Практический максимум: 20-30 инстансов (с запасом)
```

## Валидация и проверка работоспособности

- **Запуск инстанса:** `kraft ps` / `virsh list` должны показыватьRunning.
- **Сетевая связность:** `ping`, `nmap`, `curl` с хоста.
- **Логи:** `tail -f /var/log/unikernel/*.log`, `journalctl -u libvirtd`.
- **Метрики:** `ps aux | grep qemu`, `virt-top`, Prometheus + Node Exporter.
- **Старт:** < 100 мс от команды до первого ответа.

## Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **"Operation not permitted"** | Нет доступа к KVM | Проверить группу `kvm`, права на `/dev/kvm`. |
| **Kernel Panic** | Неверный драйвер гипервизора | Проверить `virtio-net` в конфигурации. |
| **Сеть не работает** | Отсутствует TAP/bridge | Проверить `ip link show`, `brctl show`. |
| **Юникернел не отвечает** | Приложение слушает на 127.0.0.1 | Переключить на `0.0.0.0:PORT`. |
| **Высокое потребление RAM** | Отладочные символы | Пересобрать с `--strip`. |
| **VM не стартует** | Конфликт имен или ресурсы заняты | `virsh list --all`, проверить UUID и MAC. |
| **Консоль не работает** | Отсутствует PTY или serial console | Добавить `<console type='pty'/>` в XML. |
| **Трафик не проходит** | Firewall на хосте блокирует bridge | Проверить `iptables -L -v -n`, `nft list ruleset`. |
| **VMI в Terminating** | Ошибка graceful shutdown | `virtctl stop <vmi> --grace-period=0 --force`. |

## Лучшие практики

### Проектирование инфраструктуры

- **Один мост на подсеть:** Не смешивайте VLAN-подсети на одном мосту без VLAN-aware режима.
- **Golden Image:** Храните предварительно собранные образы в registry (Podman/Docker) с тегированием по дате и коммиту.
- **Иммутабельность:** Никогда не изменяйте запущенный инстанс. Развертывайте новый образ и останавливайте старый.
- **Разделение сред:** Разделите `libvirt` pools и networks для dev/staging/prod.

### Безопасность

- **RBAC для libvirt:** Используйте Polkit для ограничения прав на управление VM. Только admin-пользователи должны иметь доступ к `virsh`.
- **Изоляция сети:** Каждый юникернел должен иметь отдельный TAP-интерфейс. Используйте VLAN-aware мост для сегрегации.
- **Подпись образов:** Подписывайте golden images с помощью `cosign` или `gpg`. Проверяйте подпись перед запуском.
- **SBOM:** Генерируйте SBOM (Syft) для каждого образа и храните в registry.
- **Ограничение ресурсов:** Используйте cgroups для ограничения RAM/CPU на уровне хоста.

### Производительность

- **MTU 1450 для TAP:** Учитывайте overhead virtio-net (12 байт). Настройте MTU=1450 на TAP-интерфейсе.
- **CPU host-passthrough:** Используйте `host-passthrough` для доступа к аппаратным инструкциям (AES-NI, AVX).
- **IOThreads:** Для storage-heavy workloads распределите I/O по отдельным потокам.
- **Huge Pages:** Для memory-heavy workloads (≥ 4 ГБ) используйте 2M или 1G huge pages.
- **NUMA affinity:** Привязывайте vCPU к NUMA-ноде хоста для снижения latency.

### Отказоустойчивость

- **Live Migration:** Используйте KubeVirt `VirtualMachineMigration` или `virsh migrate` для миграции ВМ между хостами без даунтайма.
- **Multi-host pools:** Распределяйте инстансы по нескольким хостам. Один хост ≠ single point of failure.
- **Health checks:** Настройте HTTP/TCP health checks через `virtctl` или Prometheus blackbox exporter.
- **Auto-restart:** Используйте `systemd` или libvirt `on_poweroff` для автоматического перезапуска упавших инстансов.

### Управление образами

- **Registry:** Храните образы в on-premise registry (Podman/Distribution). Используйте дайджесты вместо тегов.
- **Ротация:** Удаляйте образы старше 30 дней. Используйте `skopeo` для управления lifecycle.
- **Кэширование:** Настройте `kraft` для кэширования слоев сборки (`KRAFTCACHE`).

## Граничные случаи

### Миграция и live migration

- **Post-copy migration:** При network-heavy workloads используйте post-copy для снижения downtime. Но учтите risk — если целевой хост недоступен, ВМ может упасть.
- **NUMA constraints:** Live migration не работает между хостами с разной топологией NUMA. Проверяйте совместимость перед миграцией.
- **Дисковые подписи:** После migration обновите `virtio` disk signatures, если используется `qcow2` с backing file.

### Проблемы с KVM

- **Nested virtualization:** Для запуска KVM внутри KVM (например, для CI/CD) требуется включить nested VT-x/AMD-V на хосте. Производительность падает на 20-30%.
- **Overcommit:** Переcommit RAM (> 1.5x физической) приводит к OOM-Killer. Мониторьте `kvm` memory ballooning.
- **IOMMU groups:** Для PCI passthrough убедитесь что устройство находится в отдельном IOMMU group. Иначе sharing устройств между ВМ невозможно.

### Проблемы с libvirt

- **Lock файлы:** `virsh` создаёт lock файлы в `/var/run/libvirt/`. Удаление lock вручную приведёт к corrupted state.
- **Storage pools:** Если pool недоступен, ВМ не стартует. Мониторьте `virsh pool-list --all`.
- **Secrets:** Credentials для storage pools хранятся в libvirt secrets. Резервное копирование `/etc/libvirt/secrets` обязательно.

### Проблемы с сетью

- **MAC-адреса:** Дублирование MAC на одном мосте приведёт к broadcast storms. Используйте predictable naming или statically assigned MAC.
- **TAP-утечки:** Неудалённые TAP-интерфейсы после crash ВМ потребляют память хоста. Автоматизируйте cleanup через `udev` rules.
- **VLAN-aware bridge + old kernel:** На ядрах < 5.10 VLAN-aware мост с bonding может работать некорректно. Обновите ядро или используйте традиционные VLAN-под-интерфейсы.

### Capacity edge cases

- **Плотность vs Latency:** Увеличение плотности (> 30 инстансов на хост) снижает latency из-за contention. Для latency-sensitive workloads ограничьте плотность 10-15.
- **QEMU overhead:** На процессорах без VT-x/AMD-V QEMU работает в режиме TCG (emulation) с производительностью в 5-10 раз ниже. Никогда не используйте это в production.
- **Thundering herd:** При массовом старте юникернелов (например, после power loss) одновременные disk I/O могут заблокировать хост. Используйте staggered startup с задержкой.

## Дополнительная информация

### См. также
- [Обзор Unikernel](./unikernel_overview.md) — базовые концепции.
- [Преимущества и ограничения](./unikernel_advantages_disadvantages.md) — анализ сильных/слабых сторон.
- [Популярные Unikernel-проекты](./popular_unikernels.md) — выбор фреймворка.
- [Сценарии использования](./use_cases.md) — практические примеры.
- [Безопасность и hardening](./security_hardening.md) — сканирование, SBOM, подпись, compliance.
- [Мониторинг и алертинг](./monitoring_and_alerting.md) — Prometheus, Grafana, SLO/SLI.
- [Сеть: продвинутые сценарии](./networking_advanced.md) — VLAN, bonding, nftables.
- [Хранилище и резервное копирование](./storage_and_backup.md) — NFS, Ceph, iSCSI, backup.
- [Производительность и тюнинг](./performance_tuning.md) — KVM/QEMU, benchmarks.

### Ссылки
- [KubeVirt: KVM в Kubernetes](../../Linux/Virtualization/kvm/kubevirt.md)
- [Автоматизация KVM: Ansible, Terraform](../../Linux/Virtualization/kvm/kvm_automation.md)
- [Оптимизация KVM (2025–2026)](../../Linux/Virtualization/kvm/performance_tuning_2026.md)
- [Мониторинг KVM](../../Linux/Virtualization/kvm/kvm_monitoring.md)
- [Обнаружение сервисов (обзор)](../../Concepts/service-discovery-overview.md)
- [Blue/Green развёртывание](../../CI-CD/Deployment_Strategies/blue_green_deployment.md)
- [Canary развёртывание](../../CI-CD/Deployment_Strategies/canary_deployment.md)
