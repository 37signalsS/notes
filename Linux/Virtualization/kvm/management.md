# Создание и управление виртуальными машинами KVM

## Определения

**QEMU** — эмулятор, способный запускать ВМ напрямую. Подходит для быстрых тестов без сохранения конфигурации. Подробнее: [KVM Overview](./overview.md).

**libvirt** — набор инструментов для управления ВМ с полным жизненным циклом: создание, запуск, остановка, миграция. Состоит из демона `libvirtd`, API и CLI-утилит (`virsh`, `virt-install`).

**virsh** — CLI-утилита для управления ВМ через libvirt. Работает с персистентными конфигурациями.

**virt-install** — CLI-утилита для создания ВМ с автоматической настройкой диска, сети, ISO-образа.

**osinfo-query** — утилита из пакета `libosinfo-bin` для получения идентификаторов ОС, используемых при создании ВМ.

## Базовые концепты

### Подходы к созданию ВМ

| Подход | Инструмент | Персистентность | Сценарий |
| :--- | :--- | :--- | :--- |
| **Одноразовый запуск** | `qemu-system-x86_64` | ❌ Нет | Быстрое тестирование, отладка |
| **Управляемая ВМ** | `virt-install` + `virsh` | ✅ Да | Production, долгосрочное использование |

### Пути по умолчанию

| Ресурс | Путь | Назначение |
| :--- | :--- | :--- |
| ISO-образы | `/var/lib/libvirt/boot/` | Установочные образы ОС |
| Диски ВМ | `/var/lib/libvirt/images/` | Файлы дисков (`qcow2`, `raw`) |
| Конфигурации ВМ | `/etc/libvirt/qemu/` | XML-конфигурации libvirt |

### Форматы дисков

Для ВМ KVM рекомендуются форматы `qcow2` (снапшоты, thin provisioning) или `raw` (максимальная производительность). Подробнее: [VM Images](./../vm_images/basic_concepts.md).

## Практические сценарии

### Сценарий 1: Быстрый запуск ВМ через QEMU

Одноразовый запуск без сохранения состояния после закрытия терминала:

```bash
qemu-system-x86_64 \
  -enable-kvm \
  -m 1G \
  -cpu host \
  -drive file=focal-server-cloudimg-amd64-disk-kvm.img,format=qcow2 \
  -netdev user,id=net0 \
  -device virtio-net-pci,netdev=net0 \
  -nographic
```

| Параметр | Описание |
| :--- | :--- |
| `-enable-kvm` | Аппаратное ускорение |
| `-m 1G` | Выделение 1 ГБ RAM |
| `-cpu host` | Проброс CPU хоста без эмуляции |
| `-nographic` | Запуск без GUI (серверный режим) |

### Сценарий 2: Создание управляемой ВМ через libvirt

**Шаг 1: Загрузка ISO-образа**

```bash
sudo wget -O /var/lib/libvirt/boot/ubuntu24.iso \
  https://releases.ubuntu.com/24.04/ubuntu-24.04-live-server-amd64.iso
```

**Шаг 2: Определение идентификатора ОС**

```bash
sudo apt install libosinfo-bin
osinfo-query os | grep -i ubuntu | grep 24.04
```

**Шаг 3: Создание ВМ через `virt-install`**

```bash
sudo virt-install \
    --name=ubuntu-lts-vm \
    --os-variant=ubuntu24.04 \
    --vcpu=1 \
    --ram=2048 \
    --graphics vnc \
    --cdrom=/var/lib/libvirt/boot/ubuntu24.iso \
    --network bridge:virbr0,model=virtio \
    --disk path=/var/lib/libvirt/images/ubuntu-lts-vm.qcow2,size=20,bus=virtio,format=qcow2
```

| Параметр | Описание |
| :--- | :--- |
| `--name` | Имя ВМ |
| `--os-variant` | Идентификатор ОС из `osinfo-query` |
| `--vcpu` | Количество виртуальных CPU |
| `--ram` | Объём RAM (МБ) |
| `--cdrom` | Путь к ISO-образу |
| `--network` | Сеть: мост + модель драйвера |
| `--disk` | Диск: путь, размер (ГБ), шина, формат |

После запуска начнётся стандартный процесс установки ОС.

### Сценарий 3: Управление ВМ через `virsh`

| Действие | Команда |
| :--- | :--- |
| Список запущенных ВМ | `sudo virsh list` |
| Все ВМ (вкл. выключенные) | `sudo virsh list --all` |
| Запуск ВМ | `sudo virsh start имя_машины` |
| Штатное выключение (ACPI) | `sudo virsh shutdown имя_машины` |
| Принудительное выключение | `sudo virsh destroy имя_машины` |
| Перезагрузка | `sudo virsh reboot имя_машины` |
| Приостановка | `sudo virsh suspend имя_машины` |
| Возобновление | `sudo virsh resume имя_машины` |
| Редактирование конфигурации | `virsh edit имя_машины` |
| Удаление ВМ (без дисков) | `virsh undefine имя_машины` |
| VNC-порт для подключения | `sudo virsh vncdisplay имя_машины` |

**Важно:** Команда `destroy` только останавливает ВМ. Файл образа диска в `/var/lib/libvirt/images/` необходимо удалять вручную.

## Дополнительная информация

### Форматы образов дисков

Детальное описание форматов (`qcow2`, `raw`, `vmdk`), снапшотов и утилиты `qemu-img`: [VM Images](./../vm_images/definitions.md).

### Решение проблем

Проблемы с производительностью, миграцией и CPU-совместимостью: [KVM Troubleshooting](./troubleshooting.md).

### Вложенная виртуализация

Настройка CPU-модели `host-model` и `host-passthrough` для вложенных ВМ: [Nested Virtualization](../nested_virtualization/practical_scenarios.md).
