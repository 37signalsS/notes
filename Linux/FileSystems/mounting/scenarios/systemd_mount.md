# Определения

**Systemd mount units** — это современный механизм управления монтированием файловых систем в Linux, который является альтернативой традиционному файлу `/etc/fstab`. Он позволяет гибко управлять точками монтирования с помощью юнитов `systemd`.

Существует два основных типа юнитов:
*   **`.mount`**: Определяет, как и что монтировать. Прямой аналог записи в `fstab`.
*   **`.automount`**: Обеспечивает монтирование по требованию при первом обращении к указанному каталогу.

# Основные концепции

## Преимущества Systemd
*   **Управление зависимостями**: Позволяет указать, что ресурс нужно монтировать только после выполнения определенного условия (например, после появления сети с помощью `After=network-online.target`).
*   **Параллелизация**: `systemd` может монтировать ресурсы параллельно, ускоряя загрузку системы.
*   **Простота отладки**: Статус монтирования легко проверить стандартными командами `systemd` (`systemctl status`, `journalctl`).

## Именование юнитов
Имя юнита генерируется из пути к точке монтирования. Все слеши (`/`) заменяются на дефисы (`-`), а ведущий слеш удаляется. Например:
*   Точка монтирования `/mnt/data` соответствует юниту `mnt-data.mount`.
*   Точка монтирования `/home/user/share` соответствует юниту `home-user-share.mount`.

Файлы юнитов размещаются в `/etc/systemd/system/`.

# Практические сценарии

## 1. Постоянное монтирование с помощью `.mount`

Этот сценарий — аналог записи в `fstab` и используется для монтирования ресурсов при загрузке системы.

### Шаг 1: Создание `.mount` юнита
Создайте файл `/etc/systemd/system/mnt-share.mount` для монтирования сетевой CIFS-папки.

```ini
# /etc/systemd/system/mnt-share.mount
[Unit]
Description=Mount network share
After=network-online.target

[Mount]
What=//192.168.1.10/share
Where=/mnt/share
Type=cifs
Options=credentials=/etc/smb.cred,_netdev

[Install]
WantedBy=multi-user.target
```

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
```

## 2. Монтирование по требованию с помощью `.automount`

Этот сценарий позволяет монтировать ресурс только при первом обращении к нему, ускоряя загрузку. Он является альтернативой `autofs`.

### Шаг 1: Создание `.mount` юнита
Сначала создается `.mount` юнит, как в примере выше, но его **не нужно включать (`enable`)**. `systemd` найдет и использует его сам.

### Шаг 2: Создание `.automount` юнита
Создайте файл `/etc/systemd/system/mnt-share.automount`.

```ini
# /etc/systemd/system/mnt-share.automount
[Unit]
Description=Automount network share

[Automount]
Where=/mnt/share
TimeoutIdleSec=600

[Install]
WantedBy=multi-user.target
```
*`TimeoutIdleSec=600`* отмонтирует ресурс после 10 минут бездействия.

### Шаг 3: Активация юнита
Включать и запускать нужно **только `.automount` юнит**.

```bash
# 1. Создать точку монтирования
sudo mkdir -p /mnt/share

# 2. Перечитать конфигурацию systemd
sudo systemctl daemon-reload

# 3. Включить и запустить только automount юнит
sudo systemctl enable --now mnt-share.automount

# 4. Проверить статус
sudo systemctl status mnt-share.automount
```
При первой попытке доступа к `/mnt/share` `systemd` автоматически запустит `mnt-share.mount`.

# Дополнительная информация

*   **Сравнение**:
    *   Традиционный способ монтирования описан в [**fstab.md**](../fstab.md).
    *   Другой механизм монтирования по требованию — [**Autofs**](./autofs_mount.md).
*   **Документация**: Подробную информацию можно найти в официальной документации: `man systemd.mount` и `man systemd.automount`.
*   **Обзор**: Общая информация о всех способах монтирования доступна в [**главном файле раздела**](../index.md).
