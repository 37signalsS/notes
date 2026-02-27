# systemd-nspawn: Встроенная контейнеризация

## Определения

`systemd-nspawn` — это утилита, которую можно рассматривать как "chroot на стероидах". Она использует современные технологии ядра Linux (пространства имён, cgroups) для запуска легковесных контейнеров, которые глубоко интегрированы с основной хост-системой.

В отличие от Docker, `nspawn` не использует образы, а работает напрямую с корневой файловой системой (rootfs) другого дистрибутива, расположенной в директории.

## Основные концепции

Ключевые преимущества `systemd-nspawn` перед традиционным `chroot`:

- **Полная изоляция:** Автоматически создаёт отдельные пространства имён (namespaces) для:
  - Процессов (`PID`)
  - Файловой системы (`mount`)
  - Пользователей (`user`)
  - Сети (`network`)
  - Межпроцессного взаимодействия (`IPC`)
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
sudo mkdir /srv/my-container

# Устанавливаем минимальную систему Debian в эту директорию
sudo debootstrap stable /srv/my-container http://deb.debian.org/debian/
```

### 2. Запуск и управление

#### Интерактивный запуск

```bash
# Запустить контейнер из директории /srv/my-container и войти в него
sudo systemd-nspawn -D /srv/my-container

# Запустить контейнер с приватной виртуальной сетью
sudo systemd-nspawn -D /srv/my-container --network-veth

# Запустить и сразу выполнить команду
sudo systemd-nspawn -D /srv/my-container /bin/bash -c "ls -la /"
```

#### Утилита `machinectl`

`machinectl` — это `systemctl` для контейнеров и виртуальных машин.

```bash
# Показать список запущенных контейнеров ("машин")
machinectl list

# Войти в работающий контейнер (получить shell)
machinectl shell my-container

# Посмотреть статус машины
machinectl status my-container

# Остановить машину
machinectl stop my-container
```

#### Запуск как системная служба

`systemd` предоставляет шаблонный юнит `systemd-nspawn@.service`, который позволяет легко запускать `nspawn`-контейнеры как обычные службы. Имя экземпляра — это имя директории в `/srv` или `/var/lib/machines`.

Если наш контейнер находится в `/srv/my-container`, то служба будет называться `systemd-nspawn@my-container.service`.

```bash
# Запустить контейнер как службу
sudo systemctl start systemd-nspawn@my-container.service

# Включить автозапуск
sudo systemctl enable systemd-nspawn@my-container.service

# Проверить статус
systemctl status systemd-nspawn@my-container.service
```

## Дополнительная информация

- **[Обзор виртуализации в Linux](../../Virtualization/virtualization_overview.md)**: Для более широкого понимания различных технологий виртуализации и контейнеризации в Linux.
- **[Пространства имен (Namespaces) в Linux](../namespaces.md)**: Для углубленного изучения технологии изоляции, используемой `systemd-nspawn`.
- **[Контрольные группы (cgroups) в Linux](../cgroups.md)**: Для понимания механизмов управления ресурсами, применяемых `systemd-nspawn`.
