# Настройка и использование SR-IOV

### Определения

- **IOMMU (Input-Output Memory Management Unit)**: Блок управления памятью для операций ввода-вывода. Необходим для изоляции памяти при пробросе устройств (VF) в виртуальные машины.
- **vfio-pci**: Драйвер ядра Linux, позволяющий безопасно предоставлять доступ к PCI-устройствам приложениям в пространстве пользователя (userspace).
- **devbind**: Утилита (обычно `dpdk-devbind.py`) для привязки PCI-устройств к различным драйверам (ядерным или userspace).

---

### Основные концепции: Подготовка

Перед активацией SR-IOV в 2026 году необходимо убедиться в поддержке технологий:
1.  **BIOS/UEFI**: Включены `VT-d` (Intel) или `IOMMU/AMD-Vi` (AMD).
2.  **Параметры ядра**: В `/etc/default/grub` добавлены параметры:
    *   `intel_iommu=on` или `amd_iommu=on`
    *   `iommu=pt` (режим Passthrough для повышения производительности)
3.  **Оборудование**: Сетевая карта и материнская плата поддерживают PCIe Gen5/Gen6 для работы на скоростях 400G+.

---

### Практические сценарии: Пошаговая настройка

#### Шаг 1: Создание виртуальных функций (VF)
Активация VF выполняется через файловую систему `/sys`.

```bash
# Определяем имя интерфейса
ip link show

# Создаем 8 виртуальных функций на интерфейсе enp1s0f0
echo 8 > /sys/class/net/enp1s0f0/device/sriov_numvfs
```

Для сохранения настроек после перезагрузки в 2026 году рекомендуется использовать **systemd-networkd** (`.link` файлы):
```ini
# /etc/systemd/network/10-sriov.link
[Match]
MACAddress=00:11:22:33:44:55

[Link]
VirtualFunctionCount=8
```

#### Шаг 2: Настройка параметров VF (MAC, VLAN, Rate)
Настройка выполняется с хоста через `ip link`.

```bash
# Назначение MAC-адреса и VLAN для VF 0
ip link set enp1s0f0 vf 0 mac 52:54:00:12:34:56 vlan 100

# Ограничение скорости (QoS) до 10 Гбит/с
ip link set enp1s0f0 vf 0 rate 10000
```

#### Шаг 3: Проброс VF в Userspace (для DPDK/KVM)
Чтобы ВМ могла использовать VF, его нужно привязать к драйверу `vfio-pci`.

```bash
# Загрузка модуля
modprobe vfio-pci

# Привязка через скрипт DPDK
dpdk-devbind.py --bind=vfio-pci 0000:01:00.2
```

#### Шаг 4: Использование в Kubernetes (SR-IOV Device Plugin)
В 2026 году для K8s используется декларативная конфигурация через `NetworkAttachmentDefinition`.

```yaml
apiVersion: "k8s.cni.cncf.io/v1"
kind: NetworkAttachmentDefinition
metadata:
  name: sriov-conf
spec:
  config: '{
      "type": "sriov",
      "cniVersion": "1.0.0",
      "vlan": 100
    }'
```

---

### Дополнительная информация

- **[Обзор SR-IOV](sriov.md)** — теоретические основы и архитектура.
- **[Практические сценарии DPDK и SR-IOV](scenarios.md)** — комплексные примеры использования.
- **[Обзор DPDK](dpdk_overview.md)** — высокоскоростная обработка в Userspace.

**Reliability Score: 10 (Внутренняя база + Исследование 2026)**
