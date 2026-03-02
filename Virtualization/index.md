# Виртуализация — индекс

> **Навигация:** [Главная](../index.md) | [Виртуализация](./)

---

## Обзор

Виртуализация — технология создания виртуальных версий вычислительных ресурсов: ОС, серверов, устройств хранения, сетевых ресурсов.

**SSoT структура:**

| Файл | Описание |
| :--- | :--- |
| **[virtualization_overview.md](./virtualization_overview.md)** | **SSoT:** Общая виртуализация, типы, механизмы изоляции, KVM |
| **[virtual_machine_images.md](./virtual_machine_images.md)** | **SSoT:** Образы ВМ, форматы, qemu-img, снапшоты |
| **[nested_virtualization.md](./nested_virtualization.md)** | **SSoT:** Вложенная виртуализация (KVM) |

---

## Навигация по теме

### Основные файлы

- [Виртуализация и изоляция в Linux](./virtualization_overview.md) — определения, типы, KVM, контейнеры
- [Образы ВМ](./virtual_machine_images.md) — форматы, qemu-img, управление снапшотами
- [Вложенная виртуализация](./nested_virtualization.md) — KVM nested, уровни L0/L1/L2

### Связанные файлы (внешние)

| Файл | Описание |
| :--- | :--- |
| [VirtualBox](../virtualbox.md) | Установка и настройка VirtualBox на Arch Linux |
| [Docker overview](../Docker/docker_overview.md) | Контейнеризация, отличия от ВМ |
| [Podman architecture](../Podman/podman_daemonless_architecture.md) | Daemonless-контейнеры |
| [Vagrant workflow](../Vagrant/vagrant_basic_workflow.md) | Управление ВМ через Vagrant |
| [LVM snapshots](../FileSystems/LVM/snapshots.md) | Снапшоты LVM (для block passthrough) |

---

## Быстрый доступ

### Установка VirtualBox (Arch Linux)

```bash
sudo pacman -S virtualbox virtualbox-guest-iso
sudo usermod -aG vboxusers $USER
# Выход и повторный вход
```

Подробно: [VirtualBox](../virtualbox.md)

### Включение nested virtualization (KVM)

```bash
# Intel
echo "options kvm-intel nested=1" | sudo tee /etc/modprobe.d/kvm.conf
sudo modprobe -r kvm_intel && sudo modprobe kvm_intel

# AMD
echo "options kvm-amd nested=1" | sudo tee /etc/modprobe.d/kvm.conf
sudo modprobe -r kvm_amd && sudo modprobe kvm_amd
```

Подробно: [Nested Virtualization](./nested_virtualization.md)

### Создание образа qcow2

```bash
qemu-img create -f qcow2 disk.qcow2 50G
qemu-img snapshot -c snap1 disk.qcow2
```

Подробно: [Образы ВМ](./virtual_machine_images.md)

---

## Сравнение технологий

| Технология | Тип | Гипервизор | Ядро | Использование |
| :--- | :--- | :--- | :--- | :--- |
| **KVM** | Полная | Тип 1 | Свое | Продакшен, облака |
| **VirtualBox** | Полная | Тип 2 | Свое | Разработка, тесты |
| **Docker** | Контейнеры | - | Общее с хостом | Микросервисы, CI/CD |
| **Podman** | Контейнеры | - | Общее с хостом | Rootless, systemd |

---

## Рекомендации

**Выбор технологии:**

- **Продакшен (Linux):** KVM/QEMU
- **Рабочая станция (Windows/macOS гость):** VirtualBox
- **Микросервисы:** Docker/Podman
- **Тестирование гипервизоров:** Nested Virtualization
- **Инфраструктура как код:** Vagrant + KVM/VirtualBox

**Best practices:**

1. Регулярные снапшоты перед изменениями
2. Мониторинг дискового пространства
3. Изоляция сетей между уровнями виртуализации
4. Обновление гипервизоров (безопасность)
