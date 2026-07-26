# Установка и настройка KVM

В данном файле приведено пошаговое руководство по подготовке системы, установке программного стека KVM/QEMU и расширенной настройке среды (сети, проброс устройств). Архитектурный обзор доступен в [KVM — Обзор и архитектура](./overview.md).

## Термины и архитектура

Основные определения (KVM, QEMU, libvirt, virtio) и описание архитектуры взаимодействия компонентов представлены в разделе **[KVM — Обзор и архитектура](./overview.md#определения)**.

## Базовые концепции

### Требования к системе и среде

Для полноценной работы гипервизора необходимо выполнение следующих условий:

| Параметр | Описание | Метод проверки |
| :--- | :--- | :--- |
| **Виртуализация CPU** | Поддержка инструкций VMX (Intel) или SVM (AMD). | Флаги в `/proc/cpuinfo` |
| **BIOS/UEFI** | Аппаратная виртуализация должна быть включена в прошивке. | Утилита `kvm-ok` |
| **IOMMU (VT-d/AMD-Vi)** | Требуется для прямого проброса PCI-устройств в ВМ. | Параметры ядра (GRUB) |
| **Группы прав** | Доступ пользователя к сокету управления libvirt. | Группа `libvirt` |

### Компоненты программного стека

Рекомендуемый набор пакетов для дистрибутивов Debian/Ubuntu:

- `qemu-system-x86`: Основной эмулятор и виртуализатор для архитектуры x86_64.
- `libvirt-daemon-system`: Системные службы (демон `libvirtd`) и конфигурационные файлы.
- `libvirt-clients`: Набор CLI-утилит (`virsh`, `virt-install`, `virt-xml`).
- `bridge-utils`: Инструменты для создания классических сетевых мостов (L2).
- `virt-manager`: Графический интерфейс управления (требует X11/Wayland).

## Практические сценарии

### Сценарий 1: Проверка и подготовка оборудования

Этот этап выполняется ДО установки пакетов.

**1. Проверка флагов аппаратной виртуализации:**
```bash
grep -Eoc '(vmx|svm)' /proc/cpuinfo
# → результат > 0 означает наличие поддержка
```

**2. Использование cpu-checker:**
```bash
sudo apt update && sudo apt install -y cpu-checker
sudo kvm-ok
# → Ожидается: "KVM acceleration can be used"
```

**3. Активация IOMMU (для Passthrough):**
Если планируется проброс видеокарт или сетевых адаптеров, добавьте параметры в `/etc/default/grub` (подробнее: [Настройка GRUB](../../SystemAdministration/grub.md)):
- Для Intel: `intel_iommu=on iommu=pt`
- Для AMD: `amd_iommu=on iommu=pt`
*После изменения выполните `sudo update-grub` и перезагрузитесь.*

### Сценарий 2: Установка и базовая настройка

**1. Установка стека KVM/libvirt:**
```bash
sudo apt install -y qemu-system-x86 libvirt-daemon-system libvirt-clients bridge-utils virt-manager
```

**2. Настройка прав доступа:**
Добавьте текущего пользователя в группы, чтобы управлять ВМ без `sudo`:
```bash
sudo adduser $USER libvirt
sudo adduser $USER kvm
# → Перезайдите в систему для применения групп.
```

**3. Проверка состояния служб:**
```bash
sudo systemctl enable --now libvirtd
virsh uri
# → Ожидается: qemu:///system
```

### Сценарий 3: Настройка сетевого моста (L2 Bridge)

Для предоставления ВМ прямого доступа в локальную сеть необходимо создать мост на хосте. В Ubuntu это делается через Netplan (подробнее: [Настройка Netplan](../../Networking/Settings/Persistent_Network/ubuntu_netplan.md)).

**Пример `/etc/netplan/01-netcfg.yaml`:**
```yaml
network:
  version: 2
  ethernets:
    enp3s0:
      dhcp4: no
  bridges:
    br0:
      interfaces: [enp3s0]
      dhcp4: yes
      parameters:
        stp: false
```
*После применения (`netplan apply`) используйте `br0` в настройках сети ВМ.*

### Сценарий 4: Проверка вложенной виртуализации (Nested)

Позволяет запускать KVM внутри ВМ. По умолчанию часто выключено.

```bash
# Проверка статуса в ядре
cat /sys/module/kvm_intel/parameters/nested
# → Y означает "включено" (для AMD файл kvm_amd)

# Если выключено (N), активируйте через конфиг модуля:
echo "options kvm_intel nested=1" | sudo tee /etc/modprobe.d/kvm-nested.conf
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — SSoT по терминологии и принципам работы.
- [Управление виртуальными машинами](./management.md) — работа с `virsh` и создание первой ВМ.
- [Linux Bridge: Концепции](../../Networking/Concepts/linux_bridge.md) — глубокое погружение в работу мостов.
- [Вложенная виртуализация](../nested_virtualization/practical_scenarios.md) — детальная настройка Nested VT-x.
