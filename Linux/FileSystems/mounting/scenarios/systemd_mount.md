# Определения

**Systemd mount units** — современный механизм управления монтированием файловых систем в Linux, альтернатива `/etc/fstab` (file systems table). Позволяет гибко управлять точками монтирования через юниты `systemd`.

Основные типы юнитов:

* **`.mount`** — определяет, что и как монтировать; прямой аналог записи в `fstab`.
* **`.automount`** — монтирование по требованию при первом обращении к каталогу.

# Основные концепции

## Преимущества Systemd

* **Управление зависимостями**: Позволяет указать, что ресурс нужно монтировать только после выполнения определенного условия (например, после появления сети с помощью `After=network-online.target`).
* **Параллелизация**: `systemd` может монтировать ресурсы параллельно, ускоряя загрузку системы.
* **Простота отладки**: Статус монтирования легко проверить стандартными командами `systemd` (`systemctl status`, `journalctl`).
* **Таймауты**: Гибкое управление таймаутами ожидания устройства и монтирования.

## Именование юнитов

Имя юнита генерируется из пути к точке монтирования. Все слеши (`/`) заменяются на дефисы (`-`), а ведущий слеш удаляется. Например:

* Точка монтирования `/mnt/data` соответствует юниту `mnt-data.mount`.
* Точка монтирования `/home/user/share` соответствует юниту `home-user-share.mount`.

Файлы юнитов размещаются в `/etc/systemd/system/`.

## Ключевые директивы

### [Unit]

* `Description` — описание юнита
* `After` — монтирование после указанного юнита (например, `network-online.target`)
* `Requires` — жёсткая зависимость
* `Wants` — мягкая зависимость

### [Mount]

* `What` — устройство или источник (например, `//server/share`, `UUID` (Universally Unique Identifier))
* `Where` — точка монтирования (должна совпадать с именем юнита)
* `Type` — тип файловой системы
* `Options` — опции монтирования (аналогично fstab)
* `TimeoutSec` — таймаут монтирования в секундах

### [Automount]

* `Where` — точка монтирования
* `TimeoutIdleSec` — время бездействия перед размонтированием
* `DirectoryMode` — права на директорию автомонтирования

### [Install]

* `WantedBy` — целевая цель для активации (обычно `multi-user.target`)

# Практические сценарии

## Сценарий 1: Постоянное монтирование через .mount юнит

Этот сценарий — аналог записи в `fstab` и используется для монтирования ресурсов при загрузке системы.

### Шаг 1: Создание .mount юнита

Создайте файл `/etc/systemd/system/mnt-share.mount` для монтирования сетевой папки CIFS (Common Internet File System).

```ini
# /etc/systemd/system/mnt-share.mount
[Unit]
Description=Mount network share
After=network-online.target
Wants=network-online.target

[Mount]
What=//192.168.1.10/share
Where=/mnt/share
Type=cifs
Options=credentials=/etc/smb.cred,_netdev
TimeoutSec=30

[Install]
WantedBy=multi-user.target
```

**Важные опции:**

* `After=network-online.target` — гарантирует, что сеть полностью поднята перед монтированием
* `TimeoutSec=30` — таймаут ожидания монтирования
* `_netdev` в `Options` — указывает на сетевое устройство
* `credentials=/etc/smb.cred` — путь к файлу с учетными данными SMB (Server Message Block)

### Шаг 2: Активация юнита

```bash
# 1. Создать точку монтирования
sudo mkdir -p /mnt/share

# 2. Перечитать конфигурацию systemd
sudo systemctl daemon-reload

# 3. Включить и запустить монтирование
sudo systemctl enable --now mnt-share.mount

# 4. Проверить статус
sudo systemctl status mnt-share.mount

# 5. Просмотр логов при проблемах
journalctl -u mnt-share.mount -f
```

## Сценарий 2: Монтирование по требованию через .automount юнит

Этот сценарий позволяет монтировать ресурс только при первом обращении к нему, ускоряя загрузку. Он является альтернативой `autofs`.

> **Альтернатива через /etc/fstab:** Вместо создания отдельного `.automount` юнита можно использовать опцию `x-systemd.automount` в `/etc/fstab`. Подробнее см. в разделе [**Файл /etc/fstab**](../fstab.md#опции-systemd-x-systemd).

### Шаг 1: Создание .mount юнита

Сначала создается `.mount` юнит, как в примере выше, но его **не нужно включать (enable)**. `systemd` найдет и использует его сам.

### Шаг 2: Создание .automount юнита

Создайте файл `/etc/systemd/system/mnt-share.automount`.

```ini
# /etc/systemd/system/mnt-share.automount
[Unit]
Description=Automount network share

[Automount]
Where=/mnt/share
TimeoutIdleSec=600
DirectoryMode=0755

[Install]
WantedBy=multi-user.target
```

*`TimeoutIdleSec=600`* отмонтирует ресурс после 10 минут бездействия.

### Шаг 3: Активация юнита

Включать и запускать нужно **только .automount юнит**.

```bash
# 1. Создать точку монтирования
sudo mkdir -p /mnt/share

# 2. Перечитать конфигурацию systemd
sudo systemctl daemon-reload

# 3. Включить и запустить только automount юнит
sudo systemctl enable --now mnt-share.automount

# 4. Проверить статус
sudo systemctl status mnt-share.automount

# 5. Проверить автоматическое монтирование
ls /mnt/share  # вызовет монтирование
findmnt /mnt/share  # проверка
```

## Сценарий 3: Сравнение — юниты systemd и fstab

| Критерий | systemd mount units | /etc/fstab |
| :--- | :--- | :--- |
| **Сложность** | Выше (отдельные файлы) | Ниже (один файл) |
| **Гибкость** | Высокая (зависимости, таймауты) | Ограниченная |
| **Отладка** | Удобно (`journalctl`, `systemctl`) | Сложнее |
| **Сетевые ресурсы** | Рекомендуется | Требует `_netdev` |
| **Автомонтирование** | `.automount` юниты | `x-systemd.automount` |
| **Best practice** | Для сложных сценариев | Для простых локальных ФС |

# Дополнительная информация

Традиционный способ монтирования описан в [fstab.md](../fstab.md). Другой механизм монтирования по требованию — [Autofs](./autofs_mount.md). Подробная документация: `man systemd.mount` и `man systemd.automount`. Общий обзор всех способов монтирования — в [главном файле раздела](../index.md).
