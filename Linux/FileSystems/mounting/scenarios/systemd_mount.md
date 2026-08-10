# Определения

**Systemd mount units** — декларативный механизм управления файловыми системами в Linux, интегрированный в систему инициализации `systemd`. 

В отличие от статического `/etc/fstab`, юниты монтирования являются полноправными объектами системы, что позволяет использовать зависимости (Dependencies), мониторинг состояний и расширенное логирование.

Основные типы юнитов:
*   **.mount** — описывает параметры статического монтирования.
*   **.automount** — обеспечивает монтирование по требованию (при обращении к каталогу).

# Основные концепции

## Преимущества перед /etc/fstab

*   **Управление зависимостями**: Возможность задать строгий порядок запуска (например, монтировать только после активации VPN или разблокировки LUKS-контейнера).
*   **Изоляция и безопасность**: Использование `BindsTo` позволяет автоматически размонтировать ФС при исчезновении устройства (например, извлечении USB).
*   **Асинхронность**: Systemd распараллеливает процесс монтирования, что ускоряет загрузку.
*   **Логирование**: Все ошибки монтирования фиксируются в `journald` с привязкой к конкретному юниту.

## Правила именования и экранирование

Имя файла юнита должно строго соответствовать пути точки монтирования. Если путь содержит спецсимволы или имеет большую вложенность, необходимо использовать экранирование.

**Алгоритм именования:**
1.  Удаляется ведущий слеш.
2.  Все остальные слеши заменяются дефисами (`-`).
3.  Для сложных путей используйте утилиту `systemd-escape`:
    ```bash
    systemd-escape -p --suffix=mount "/mnt/my storage"
    # → mnt-my\x20storage.mount
    ```

## Генератор systemd-fstab-generator

В современных дистрибутивах `/etc/fstab` обрабатывается утилитой `systemd-fstab-generator`. Она динамически создает временные `.mount` юниты в `/run/systemd/generator/` при каждой загрузке или выполнении `systemctl daemon-reload`.

# Структура юнит-файла

### Секция [Unit]
*   **`BindsTo=`**: Жесткая привязка к устройству. Если устройство (например, `/dev/sdb1`) исчезает, юнит монтирования немедленно останавливается.
*   **`After=` / `Wants=`**: Зависимость от сетевых интерфейсов или других сервисов.

### Секция [Mount]
*   **`What=`**: Источник (UUID, LABEL, путь к устройству или сетевой адрес).
*   **`Where=`**: Абсолютный путь точки монтирования (должен совпадать с именем юнита).
*   **`Type=`**: Тип ФС.
*   **`Options=`**: Параметры (аналогично fstab).
*   **`LazyUnmount=yes`**: Аналог `umount -l`. Позволяет «отвязать» ФС немедленно, даже если она занята.
*   **`ForceUnmount=yes`**: Аналог `umount -f` (в основном для сетевых ФС).

### Секция [Automount]
*   **`Where=`**: Точка монтирования.
*   **`TimeoutIdleSec=`**: Время бездействия, после которого ФС будет автоматически размонтирована.

# Практические сценарии

## Сценарий 1: Сетевой ресурс (NFS) с ожиданием сети

**Файл `/etc/systemd/system/mnt-nfs.mount`**:
```ini
[Unit]
Description=Network Share (NFS)
After=network-online.target
Wants=network-online.target

[Mount]
What=192.168.1.10:/srv/data
Where=/mnt/nfs
Type=nfs
Options=rw,soft,timeo=50,_netdev
TimeoutSec=30

[Install]
WantedBy=multi-user.target
```

## Сценарий 2: USB-диск с автоматическим завершением (BindsTo)

Идеально для внешних дисков. Если диск извлечен, юнит переходит в статус `failed` или `inactive`, не блокируя систему.

**Файл `/etc/systemd/system/mnt-usb.mount`**:
```ini
[Unit]
Description=External USB Drive
BindsTo=dev-disk-by\x2duuid-A1B2\x2dC3D4.device
After=dev-disk-by\x2duuid-A1B2\x2dC3D4.device

[Mount]
What=/dev/disk/by-uuid/A1B2-C3D4
Where=/mnt/usb
Type=vfat
Options=defaults,nofail

[Install]
WantedBy=multi-user.target
```

## Сценарий 3: Автомонтирование по требованию (.automount)

Ресурс монтируется только тогда, когда пользователь или скрипт заходит в `/mnt/docs`.

**Файл `/etc/systemd/system/mnt-docs.automount`**:
```ini
[Unit]
Description=Automount Documents on Access

[Automount]
Where=/mnt/docs
TimeoutIdleSec=10min

[Install]
WantedBy=multi-user.target
```
*Важно: Соответствующий `mnt-docs.mount` должен быть создан, но его не нужно включать (`enable`).*

## Сценарий 4: Монтирование после разблокировки LUKS

```ini
[Unit]
Description=Encrypted Data Partition
After=cryptsetup.target
Requires=systemd-cryptsetup@secure_data.service

[Mount]
What=/dev/mapper/secure_data
Where=/mnt/secure
Type=ext4
```

# Управление и диагностика

### Основные команды
```bash
# Применение изменений
sudo systemctl daemon-reload

# Запуск и включение автозагрузки
sudo systemctl enable --now mnt-data.mount

# Просмотр статуса
systemctl status mnt-data.mount
# → Active: active (mounted) since ...

# Список всех юнитов монтирования
systemctl list-units --type=mount
```

### Анализ логов
```bash
# Логи конкретного юнита
journalctl -u mnt-data.mount -f

# Логи генератора fstab
journalctl -t systemd-fstab-generator
```

# Дополнительная информация

*   **[Конфигурация /etc/fstab](../fstab.md)** — сравнение подходов и базовые опции.
*   **[Команды монтирования](../commands.md)** — диагностика через `findmnt` и `mount`.
*   **[Автоматизация udev](./udev_mount.md)** — динамическое создание юнитов при подключении устройств.
*   **[Структура юнит-файлов](../../Core/systemd/systemd_unit_file_structure.md)** — подробный разбор секций `[Unit]` и `[Install]`.
