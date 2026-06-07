# systemd-nspawn: Встроенная контейнеризация

## Определения

`systemd-nspawn` — это утилита, которую можно рассматривать как "chroot на стероидах". Она использует современные технологии ядра Linux (пространства имён, cgroups) для запуска легковесных контейнеров, которые глубоко интегрированы с основной хост-системой.

В отличие от Docker, `nspawn` не использует образы, а работает напрямую с корневой файловой системой rootfs (Root File System) другого дистрибутива, расположенной в директории.

**Архитектурное положение:** systemd-nspawn занимает промежуточное положение между:

- **Docker/Podman** (OCI (Open Container Initiative)-образы, слои, сеть, реестры)
- **Виртуальными машинами VM (Virtual Machine)** (гипервизор, собственное ядро)

Это **системный контейнер на уровне ОС (Операционная система)**: изолированный процесс со своим корнем файловой системы, PID (Process ID)-пространством и сетью. Ядро при этом общее с хостом.

## Основные концепции

### Когда использовать systemd-nspawn

| Сценарий | Рекомендация |
| :--- | :--- |
| **Docker/Podman** | Когда нужны образы, реестры, оркестрация, микросервисы |
| **systemd-nspawn** | Когда нужно: <br>• Быстро поднять изолированное окружение для теста или сборки <br>• Запустить другой дистрибутив на том же хосте без VM <br>• Отлаживать chroot, но с нормальной изоляцией <br>• Не тащить Docker на минималистичный сервер |

### Преимущества перед альтернативами

- **Никакого демона** — не требует отдельного сервиса в продакшене
- **Никакого рантайма** — не нужны containerd, runc, crun
- **Никакой регистрации** — не нужен Docker Hub или другие реестры
- **Нулевые накладные расходы** — весит ноль байт сверх того, что уже есть в systemd
- **Готов "из коробки"** — часть systemd, доступен сразу после установки

Ключевые преимущества `systemd-nspawn` перед традиционным `chroot`:

- **Полная изоляция:** Автоматически создаёт отдельные пространства имён (namespaces) для:
  - Процессов (`PID`)
  - Файловой системы (`mount`)
  - Пользователей (`user`)
  - Сети (`network`)
  - Межпроцессного взаимодействия (`IPC (Inter-Process Communication)`)
- **Простота использования:** Может работать с готовыми образами системы (например, созданными через `debootstrap`) или простыми директориями.
- **Глубокая интеграция с `systemd`:**
  - Контейнером можно управлять как обычной системной службой (`systemd-nspawn@.service`).
  - Полная поддержка логирования через `journald` хоста (включая машинный журнал).
  - Управляется через утилиту `machinectl`.

## Практические сценарии

### 1. Подготовка окружения

Для запуска контейнера нужна его корневая файловая система. Для Debian/Ubuntu ее можно создать с помощью `debootstrap`.

```bash
# Устанавливаем debootstrap
sudo apt install debootstrap

# Создаем директорию для нашего контейнера
sudo mkdir -p /var/lib/machines/mydebian

# Устанавливаем минимальную систему Debian в эту директорию
sudo debootstrap stable /var/lib/machines/mydebian http://deb.debian.org/debian/
```

> **Примечание:** systemd-nspawn работает с директориями в `/var/lib/machines` или `/srv`. Использование `/var/lib/machines` предпочтительнее для интеграции с `machinectl`.

### 2. Запуск и управление

#### Интерактивный запуск

```bash
# Запустить контейнер из директории и войти в него
sudo systemd-nspawn -D /var/lib/machines/mydebian

# Запустить контейнер с приватной виртуальной сетью (veth (Virtual Ethernet)-пара)
sudo systemd-nspawn -D /var/lib/machines/mydebian --network-veth

# Запустить и сразу выполнить команду
sudo systemd-nspawn -D /var/lib/machines/mydebian /bin/bash -c "ls -la /"

# Запуск как полноценный systemd-контейнер (с init-процессом)
sudo systemd-nspawn -D /var/lib/machines/mydebian --boot --network-veth
```

#### Утилита `machinectl`

`machinectl` — это `systemctl` для контейнеров и виртуальных машин.

```bash
# Показать список запущенных контейнеров ("машин")
machinectl list
# → список запущенных машин и их параметров (STATUS, PATH, ADDRESS)

# Войти в работающий контейнер (получить shell)
machinectl shell mydebian
# → открытие новой shell-сессии внутри контейнера

# Посмотреть статус машины
machinectl status mydebian
# → детальная информация о состоянии контейнера и процессах в нем

# Остановить машину
machinectl stop mydebian

# Запустить машину
machinectl start mydebian
```

#### Запуск как системная служба

`systemd` предоставляет шаблонный юнит `systemd-nspawn@.service`, который позволяет легко запускать `nspawn`-контейнеры как обычные службы. Имя экземпляра — это имя директории в `/var/lib/machines` или `/srv`.

Если наш контейнер находится в `/var/lib/machines/mydebian`, то служба будет называться `systemd-nspawn@mydebian.service`.

```bash
# Запустить контейнер как службу
sudo systemctl start systemd-nspawn@mydebian.service

# Включить автозапуск
sudo systemctl enable systemd-nspawn@mydebian.service

# Проверить статус
systemctl status systemd-nspawn@mydebian.service
# → статус системного юнита (active/running)
```

### 3. Минимальный пример: быстрый тест изоляции

```bash
# Создаём тестовое окружение
sudo debootstrap stable /var/lib/machines/testenv

# Запускаем изолированно
systemd-nspawn -D /var/lib/machines/testenv

# Внутри контейнера:
# - Отдельная файловая система
# - Отдельные PID (первый процесс имеет PID 1)
# - Отдельное пространство имён
# - Но общее ядро с хостом
```

## Дополнительная информация

Альтернативы контейнеризации: [Docker](../../../Docker/docker_overview.md), [Podman vs Docker](../../../Podman/podman_vs_docker.md). Общий обзор: [Виртуализация в Linux](../../Virtualization/virtualization_overview.md). Технологии изоляции: [Namespaces](../namespaces.md), [Cgroups](../cgroups.md). Интеграция: [Systemd units](./systemd_units_overview.md), [Docker и systemd](../../../Docker/docker_systemd.md).
