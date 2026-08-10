# Установка и настройка KVM

В данном файле приведено пошаговое руководство по подготовке системы, установке программного стека KVM/QEMU и расширенной настройке среды (сети, проброс устройств). Архитектурный обзор и теоретические основы доступны в [KVM — Обзор и архитектура](./overview.md).

## Определения

Основные определения (KVM, QEMU, libvirt, virtio) и описание архитектуры взаимодействия компонентов представлены в разделе **[KVM — Обзор и архитектура](./overview.md#определения)**.

## Базовые концепции

### Требования к системе и среде

Для полноценной работы гипервизора необходимо выполнение следующих условий:

| Параметр | Описание | Метод проверки |
| :--- | :--- | :--- |
| **Виртуализация CPU** | Поддержка инструкций VMX (Intel) или SVM (AMD). | `grep -Eoc '(vmx|svm)' /proc/cpuinfo` |
| **BIOS/UEFI** | Аппаратная виртуализация должна быть включена (Intel VT-d / AMD-V). | Утилита `virt-host-validate` |
| **IOMMU (VT-d/AMD-Vi)** | Требуется для прямого проброса PCI-устройств в ВМ. | `dmesg | grep -i iommu` |
| **UEFI Support** | Поддержка современной загрузки через GPT/Secure Boot. | Наличие пакета `ovmf` |
| **Группы прав** | Доступ пользователя к сокету управления libvirt. | Группы `libvirt` и `kvm` |

### Компоненты программного стека

Набор пакетов зависит от используемого дистрибутива, но функционально они идентичны.

#### Debian / Ubuntu (Apt)
- `qemu-system-x86`: Основной эмулятор и виртуализатор.
- `libvirt-daemon-system`: Демон `libvirtd` и системные конфиги.
- `libvirt-clients`: CLI-утилиты (`virsh`).
- `virtinst`: Утилита `virt-install`.
- `bridge-utils`: Устаревшие инструменты для L2 Bridge (заменяются `iproute2`).
- `ovmf`: UEFI прошивки для ВМ.

#### RHEL / CentOS / Rocky / AlmaLinux (Dnf)
- `qemu-kvm`: Оптимизированный QEMU для KVM.
- `libvirt`: Весь стек управления libvirt.
- `virt-install`: Инструмент создания ВМ.
- `virt-viewer`: Легковесная консоль для подключения к ВМ.

## Практические сценарии

### Сценарий 1: Проверка аппаратной готовности

Этот этап выполняется ДО установки пакетов для выявления потенциальных проблем.

**1. Проверка флагов процессора:**
```bash
grep -Eoc '(vmx|svm)' /proc/cpuinfo
# → результат > 0 означает наличие аппаратной поддержки.
```

**2. Глубокая валидация (рекомендуется):**
После установки пакета `libvirt-clients` используйте наиболее полную утилиту:
```bash
virt-host-validate qemu
# → Ожидается "PASS" для большинства критических проверок.
# → "WARN" по IOMMU допустим, если вы не планируете проброс PCI-устройств.
```

**3. Активация IOMMU (для Passthrough):**
Если планируется проброс видеокарт или сетевых адаптеров, добавьте параметры в `/etc/default/grub`:
- **Intel:** `intel_iommu=on iommu=pt`
- **AMD:** `amd_iommu=on iommu=pt`

Обновите конфигурацию и перезагрузитесь:
- Ubuntu: `sudo update-grub`
- RHEL: `sudo grub2-mkconfig -o /boot/grub2/grub.cfg`

### Сценарий 2: Установка стека виртуализации

#### Вариант А: Debian / Ubuntu 24.04+
```bash
sudo apt update
sudo apt install -y qemu-system-x86 libvirt-daemon-system libvirt-clients virtinst ovmf virt-manager
```

#### Вариант Б: RHEL 9 / AlmaLinux / Rocky
```bash
# Установка группы пакетов для виртуализации
sudo dnf groupinstall -y "Virtualization Host"
sudo dnf install -y virt-install virt-viewer
```

### Сценарий 3: Постустановочная настройка

**1. Активация служб:**
```bash
sudo systemctl enable --now libvirtd
# Проверка сокета
virsh uri # → Ожидается: qemu:///system
```

**2. Настройка прав доступа:**
Чтобы управлять ВМ без `sudo`, добавьте пользователя в соответствующие группы:
```bash
sudo usermod -aG libvirt $USER
sudo usermod -aG kvm $USER
# → Необходимо перевойти в сессию (logout/login).
```

**3. Проверка хранилища (Storage Pool):**
По умолчанию libvirt использует `/var/lib/libvirt/images`. Убедитесь, что пул активен:
```bash
virsh pool-list --all
# Если default пул не активен:
virsh pool-start default
virsh pool-autostart default
```

### Сценарий 4: Настройка сетевого моста (L2 Bridge)

Для предоставления ВМ доступа в физическую сеть хоста.

#### Способ 1: NetworkManager (nmcli) — универсальный для RHEL и современных Ubuntu
```bash
# Создание интерфейса моста
nmcli con add type bridge ifname br0 con-name br0
# Привязка физического интерфейса (напр. eth0) к мосту
nmcli con add type bridge-slave ifname eth0 con-name br0-slave master br0
# Поднятие моста
nmcli con up br0
```

#### Способ 2: Netplan (Ubuntu)
Пример `/etc/netplan/01-netcfg.yaml`:
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
Примените изменения: `sudo netplan apply`.

### Сценарий 5: Вложенная виртуализация (Nested Virtualization)

Позволяет запускать гипервизор (KVM) внутри виртуальной машины. 

Подробные инструкции по активации на хосте (L0) и настройке ВМ (L1) вынесены в специализированный SSoT-файл:
**[Вложенная виртуализация: Практические сценарии](../nested_virtualization/practical_scenarios.md)**.

Краткая проверка статуса:
```bash
# Для Intel
cat /sys/module/kvm_intel/parameters/nested
# → Y или 1 означает "включено"
```

## Дополнительная информация

- [KVM — Обзор и архитектура](./overview.md) — SSoT по теории и механизмам.
- [Управление виртуальными машинами](./management.md) — создание ВМ и работа с `virsh`.
- [Диагностика и решение проблем](./troubleshooting.md) — логи и типичные ошибки.
- [Вложенная виртуализация (Nested)](../nested_virtualization/practical_scenarios.md) — расширенная настройка.
- [Linux Bridge: Концепции](../../Networking/Concepts/linux_bridge.md) — архитектура L2-сетей.
- [Настройка GRUB](../../SystemAdministration/grub.md) — управление параметрами ядра.
