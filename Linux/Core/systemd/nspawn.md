# systemd-nspawn: Встроенная контейнеризация

## Определения

* **`systemd-nspawn`** — это системная утилита для запуска легковесных контейнеров (пространств имён) в Linux. Её часто называют «chroot на стероидах», так как она использует современные механизмы ядра (Namespaces, Cgroups) для полной изоляции файловой системы, процессов, сети и пользователей.
* **Системный контейнер** — в отличие от прикладных контейнеров (Docker), ориентированных на запуск одного приложения, `nspawn` предназначен для запуска полноценной операционной системы с собственным init-процессом (PID 1).

## Основные концепции

### Сравнение с Docker и виртуальными машинами

| Характеристика | systemd-nspawn | Docker / Podman | Виртуальные машины |
| :--- | :--- | :--- | :--- |
| **Цель** | Системный контейнер (Full OS) | Прикладной контейнер (App) | Полная виртуализация (HW) |
| **Рантайм** | Без демона (часть systemd) | Демон (dockerd) или без него | Гипервизор (KVM, ESXi) |
| **Образы** | Директории, tar, raw-образы | OCI-слои | ISO, vmdk, qcow2 |
| **Изоляция** | Высокая (Namespaces, Cgroups) | Высокая | Максимальная (аппаратная) |
| **Накладные расходы** | Практически отсутствуют | Низкие | Значительные |

### Технологии изоляции и интеграция

`systemd-nspawn` обеспечивает глубокую интеграцию с экосистемой systemd:
* **Изоляция:** Автоматическое создание пространств имён (`PID`, `mount`, `user`, `network`, `IPC`).
* **Журналирование:** Логи контейнера напрямую доступны на хосте через `journalctl -M <имя>`.
* **Управление:** Единый интерфейс управления через `machinectl`.
* **Ресурсы:** Ограничение CPU и RAM через cgroups v2.

### Работа с образами

Хотя `nspawn` не использует многослойные образы Docker, он поддерживает:
* **Директории:** Простые деревья файлов (rootfs).
* **Архивы:** `.tar.gz`, `.tar.xz`.
* **Дисковые образы:** `.raw`, `.qcow2` (через loop-устройства).
* **Импорт:** `machinectl pull-dkr` позволяет скачивать и конвертировать образы из Docker Hub.

## Практические сценарии

### 1. Подготовка окружения

Для запуска нужен корень файловой системы (rootfs).

```bash
# Установка debootstrap (для Debian/Ubuntu)
sudo apt install debootstrap

# Создание директории контейнера
sudo mkdir -p /var/lib/machines/my-debian

# Развертывание минимальной ОС
sudo debootstrap stable /var/lib/machines/my-debian http://deb.debian.org/debian/
```

### 2. Режимы запуска и изоляции

#### Интерактивный и системный запуск
```bash
# Простой запуск (аналог chroot с изоляцией)
sudo systemd-nspawn -D /var/lib/machines/my-debian

# Запуск с загрузкой init-системы (полноценная ОС)
sudo systemd-nspawn -D /var/lib/machines/my-debian --boot --network-veth
```

#### Эфемерный режим (Ephemeral)
Позволяет запустить контейнер на временном снимке (snapshot). Все изменения будут стерты после остановки.
```bash
# Запуск временной копии
sudo systemd-nspawn -x -D /var/lib/machines/my-debian
```

#### Изоляция пользователей (User Namespaces)
Безопасный режим, при котором root в контейнере не является root на хосте.
```bash
# Автоматическое назначение диапазона UID/GID
sudo systemd-nspawn -U -D /var/lib/machines/my-debian
```

### 3. Настройка через файлы конфигурации (.nspawn)

Настройки контейнера можно описать в файле `/etc/systemd/nspawn/my-debian.nspawn`. Это позволяет избежать длинных командных строк.

```ini
[Exec]
Boot=yes
Capability=CAP_NET_ADMIN

[Network]
VirtualEthernet=yes
Bridge=br0
```

### 4. Управление через machinectl

Утилита `machinectl` — основной интерфейс для работы с образами и запущенными контейнерами.

```bash
# Список всех машин (контейнеров)
machinectl list
# → список активных контейнеров и их параметров

# Вход в работающий контейнер (shell)
machinectl shell my-debian
# → открытие новой сессии внутри контейнера

# Скачивание образа из Docker Registry
sudo machinectl pull-dkr library/debian --verify=no
# → загрузка и конвертация образа в /var/lib/machines/debian

# Клонирование контейнера
sudo machinectl clone my-debian backup-debian
```

### 5. Запуск как системная служба

Для постоянной работы контейнеров используется шаблонный юнит `systemd-nspawn@.service`.

```bash
# Включение автозапуска для контейнера в /var/lib/machines/my-debian
sudo systemctl enable --now systemd-nspawn@my-debian.service

# Проверка состояния
systemctl status systemd-nspawn@my-debian.service
# → статус юнита: active (running)
```

## Дополнительная информация

### См. также
* [Механизм Control Groups (cgroups)](../cgroups.md) — управление ресурсами.
* [Пространства имён (Namespaces)](../namespaces.md) — основы изоляции в Linux.
* [Утилита chroot](../chroot.md) — классический метод смены корня.
* [Обзор systemd units](./systemd_units_overview.md) — работа с системными службами.
