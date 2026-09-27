# Определения

**Systemd mount units** — декларативный механизм управления файловыми системами в Linux, интегрированный в систему инициализации `systemd`. 

В отличие от статического `/etc/fstab`, юниты монтирования являются полноправными объектами системы, что позволяет использовать зависимости (Dependencies), мониторинг состояний и расширенное логирование.

**Жизненный цикл mount-юнита:**
1.  **Генерация:** При загрузке или `systemctl daemon-reload` утилита `systemd-fstab-generator` динамически создает временные `.mount` юниты из `/etc/fstab` в `/run/systemd/generator/`.
2.  **Активация:** Юнит запускается по зависимостям (`After=`, `Wants=`, `Requires=`) и монтирует ФС.
3.  **Работа:** Systemd отслеживает состояние. При исчезновении устройства (например, извлечении USB) `BindsTo=` автоматически размонтирует ФС и переведет юнит в `failed`.
4.  **Остановка:** При бездействии (`.automount`) или выключении системы юнит размонтирует ФС.

Основные типы юнитов:
*   **.mount** — описывает параметры статического монтирования.
*   **.automount** — обеспечивает монтирование по требованию (при обращении к каталогу).

# Основные концепции

## Преимущества перед /etc/fstab

*   **Управление зависимостями**: Возможность задать строгий порядок запуска (например, монтировать только после активации VPN или разблокировки LUKS-контейнера).
*   **Изоляция и безопасность**: Использование `BindsTo` позволяет автоматически размонтировать ФС при исчезновении устройства (например, извлечении USB).
*   **Асинхронность**: Systemd распараллеливает процесс монтирования, что ускоряет загрузку.
*   **Логирование**: Все ошибки монтирования фиксируются в `journald` с привязкой к конкретному юниту.

## Генератор systemd-fstab-generator и типы юнитов

В современных дистрибутивах `/etc/fstab` обрабатывается утилитой `systemd-fstab-generator`. Она динамически создает временные `.mount` юниты в `/run/systemd/generator/` при каждой загрузке или выполнении `systemctl daemon-reload`.

**Важно:** Юниты, созданные генератором, являются **транзиентными**. Они пересоздаются при каждом `daemon-reload`. Если вы хотите permanent-конфигурацию, создавайте статические юниты в `/etc/systemd/system/`.

**Отличия транзиентных и статических юнитов:**
*   **Транзиентные** (из fstab/generator): Пересоздаются при `daemon-reload`. Изменения в fstab применяются сразу после перезагрузки генератора.
*   **Статические** (в `/etc/systemd/system/`): Сохраняются между перезагрузками. Требуют ручного `daemon-reload` после изменения файла.

## Правила именования и экранирование

Имя файла юнита должно строго соответствовать пути точки монтирования. Если путь содержит спецсимволы или имеет большую вложенность, необходимо использовать экранирование.

**Алгоритм именования:**
1.  Удаляется ведущий слеш.
2.  Все остальные слеши заменяются дефисами (`-`).
3.  Для сложных путей используйте утилиту `systemd-escape`:
    ```bash
    systemd-escape -p --suffix=mount "/mnt/my storage"
    # → mnt-my\x20storage.mount
    
    systemd-escape -p --suffix=mount "/mnt/data/2024.01"
    # → mnt-data-2024\x2e01.mount
    ```

**Коварные случаи:**
*   Пути с точками: `systemd-escape` экранирует точки как `\x2e`.
*   Пути с `/` на конце: trailing slash игнорируется при экранировании.
*   Длинные пути (>255 символов): systemd может обрезать имя юнита. Используйте символические ссылки для сокращения.

## Дополнительные директивы systemd

### Секция [Unit]

*   **`PartOf=`**: При остановке указанного юнита текущий юнит также останавливается. Аналогично `BindsTo=`, но без автоматического запуска при старте зависимости.
    ```ini
    PartOf=mnt-data.mount
    ```
*   **`StopWhenUnneeded=yes`**: Автоматически размонтирует ФС, когда нет активных юнитов, зависящих от этого mount-юнита. Полезно для временных ресурсов.
*   **`ConditionPathExists=`**: Монтировать только если путь существует.
    ```ini
    ConditionPathExists=/dev/disk/by-uuid/A1B2-C3D4
    ```
*   **`ConditionPathIsDirectory=`**: Монтировать только если путь — директория.

### Секция [Mount]

*   **`TimeoutStopSec=`**: Время ожидания перед принудительным размонтированием при остановке юнита.
    ```ini
    TimeoutStopSec=30
    ```
*   **`SloppyOptions=yes`**: Разрешает неизвестные опции монтирования (полезно для совместимости).

## Структура юнит-файла

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

## Подготовка окружения

### Установка и проверка утилит

Systemd встроен в ядро дистрибутива, но для работы с mount-юнитами требуются стандартные утилиты:

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y systemd util-linux
# → success

# RHEL/CentOS/Rocky
sudo dnf install -y systemd util-linux
# → success
```

**Проверка версии systemd:**
```bash
systemctl --version
# → systemd 252 (252.4-1)
```

**Проверка утилит:**
```bash
systemd-escape --version
systemctl --version
findmnt --version
```

### Создание точки монтирования

Все mount-юниты требуют существующей директории:

```bash
sudo mkdir -p /mnt/nfs
sudo chown root:root /mnt/nfs
sudo chmod 755 /mnt/nfs
```

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

**Применение:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mnt-nfs.mount
# → Created symlink /etc/systemd/system/multi-user.target.wants/mnt-nfs.mount
# → Active: active (mounted) since ...
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
Options=noatime,nosuid,nodev
```

## Сценарий 5: Монтирование SMB/CIFS ресурса

Автоматическое монтирование Windows-шара или Samba-ресурса с файлом учетных данных.

**Файл `/etc/systemd/system/mnt-smb.mount`**:
```ini
[Unit]
Description=SMB Share
After=network-online.target
Wants=network-online.target

[Mount]
What=//fileserver.local/share
Where=/mnt/smb
Type=cifs
Options=credentials=/etc/samba/creds,rw,soft,timeo=50,_netdev,vers=3.0
TimeoutSec=30

[Install]
WantedBy=multi-user.target
```

**Файл `/etc/samba/creds`**:
```text
username=srv_account
password=SecurePass123
domain=EXAMPLE
```

**Права доступа:**
```bash
sudo chmod 600 /etc/samba/creds
# → только root может читать файл с учетными данными
```

**Применение:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mnt-smb.mount
```

> **Безопасность:** Никогда не храните пароли в открытом виде в юнитах. Используйте файл `credentials` с правами `600`. Для production рассмотрите `cifs-utils` с Kerberos (`sec=krb5`).

## Сценарий 6: Монтирование с условиями (Condition...)

Монтировать ФС только при выполнении определенных условий.

```ini
[Unit]
Description=Conditional Mount
ConditionPathExists=/dev/disk/by-uuid/A1B2-C3D4
ConditionPathIsDirectory=/mnt/data

[Mount]
What=/dev/disk/by-uuid/A1B2-C3D4
Where=/mnt/data
Type=ext4
Options=defaults,nofail

[Install]
WantedBy=multi-user.target
```

**Директивы `Condition...`:**
*   `ConditionPathExists=`: Путь существует.
*   `ConditionPathIsDirectory=`: Путь является директорией.
*   `ConditionPathIsSymbolicLink=`: Путь является симлинком.
*   `ConditionKernelCommandLine=`: Проверка параметров ядра.
*   `ConditionVirtualization=`: Проверка, запущено ли в виртуализации.

# Управление и диагностика

## Применение изменений

```bash
# Применение изменений к конфигурации systemd
sudo systemctl daemon-reload

# Запуск и включение автозагрузки
sudo systemctl enable --now mnt-data.mount

# Просмотр статуса
systemctl status mnt-data.mount
# → Active: active (mounted) since ...
```

## Валидация конфигурации

```bash
# Проверка синтаксиса юнита
systemd-analyze verify mnt-data.mount

# Проверка зависимостей
systemctl list-dependencies mnt-data.mount

# Проверка, что юнит будет запущен при загрузке
systemctl is-enabled mnt-data.mount
# → enabled
```

## Анализ логов

```bash
# Логи конкретного юнита
journalctl -u mnt-data.mount -f

# Логи загрузки
journalctl -b | grep mnt-data.mount

# Логи генератора fstab
journalctl -t systemd-fstab-generator
```

## Инспекция монтирований

```bash
# Список всех юнитов монтирования
systemctl list-units --type=mount

# Дерево всех смонтированных систем
findmnt

# Проверка конкретной точки
findmnt /mnt/nfs
# → TARGET   SOURCE          FSTYPE OPTIONS
# → /mnt/nfs 192.168.1.10:/srv/nfs nfs4   rw,relatime,vers=4.2,...

# Проверка, что точка является automount
findmnt -t autofs
# → /mnt/docs autofs rw,relatime,fd=...
```

# Диагностика и типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `mnt-nfs.mount: Job failed` | Сервер недоступен или неверные опции | Проверьте сеть, `showmount -e server`, логи `journalctl -u mnt-nfs.mount` |
| `systemd[1]: Failed to mount` | Ошибка в секции [Mount] или тип ФС | Проверьте синтаксис, установите `nfs-utils` или `cifs-utils` |
| `Unit mnt-nfs.mount entered failed state` | Бракованное устройство (BindsTo) | Проверьте `lsblk`, подключите устройство заново |
| `Mount point /mnt/nfs is not empty` | Директория не пуста | Очистите директорию или используйте `x-systemd.mount-timeout=`
| `TimeoutStartSec exceeded` | Сервер не отвечает | Увеличьте `TimeoutSec=` в [Unit] или проверьте сеть |
| `Stale file handle` | NFS-экспорт удален на сервере | `sudo exportfs -ra` на сервере; перезапуск autofs на клиенте |
| `Permission denied (13)` | Несовпадение UID/GID или root_squash | Проверьте `/etc/idmapd.conf` и опции экспорта |

### Пошаговая диагностика

```bash
# 1. Проверка статуса юнита
systemctl status mnt-nfs.mount
# → Active: failed (Result: exit-code) since ...

# 2. Просмотр журнала
journalctl -u mnt-nfs.mount -b
# → mount: wrong fs type, bad option, bad superblock...

# 3. Проверка доступности сервера
showmount -e 192.168.1.10
# → Export list for 192.168.1.10:
# → /srv/data *

# 4. Ручное монтирование для диагностики
sudo mount -t nfs -o rw,soft,timeo=50 192.168.1.10:/srv/data /mnt/nfs
# → выведет точную ошибку

# 5. Проверка сети
ping -c 3 192.168.1.10
ss -tnp | grep :2049
```

# Мониторинг и алертинг

```bash
# Проверка статуса всех mount-юнитов
systemctl list-units --type=mount --all

# Проверка, что automount активен
systemctl is-active mnt-docs.automount
# → active

# Мониторинг NFS-монтирований
findmnt -t nfs4 -o TARGET,SOURCE,FSTYPE,OPTIONS

# Скрипт проверки здоровья
#!/usr/bin/env bash
EXPECTED_MOUNTS=(
    "/mnt/nfs:192.168.1.10:/srv/data:nfs4"
    "/mnt/usb:/dev/disk/by-uuid/A1B2-C3D4:vfat"
)

for entry in "${EXPECTED_MOUNTS[@]}"; do
    IFS=':' read -r mountpoint source fstype <<< "$entry"
    
    if [[ ! -d "$mountpoint" ]]; then
        echo "FAIL: $mountpoint — точка не существует"
        continue
    fi
    
    if ! mountpoint -q "$mountpoint"; then
        echo "FAIL: $mountpoint — не смонтировано"
        continue
    fi
    
    actual_source=$(findmnt -no SOURCE "$mountpoint")
    if [[ "$actual_source" != *"$source"* ]]; then
        echo "FAIL: $mountpoint — источник $actual_source не соответствует $source"
        continue
    fi
    
    echo "OK: $mountpoint"
done
```

# Безопасность

## Опции монтирования

Для повышения безопасности используйте следующие опции в секции `[Mount]`:

*   **`nosuid`** — игнорирует SUID/SGID биты на разделе (предотвращает повышение привилегий).
*   **`noexec`** — запрещает выполнение бинарных файлов на разделе (для `/tmp`, `/var`, сетевых шаров).
*   **`nodev`** — запрещает интерпретацию блочных/символьных устройств на разделе.

Пример безопасной конфигурации для `/mnt/data`:
```ini
[Mount]
What=/dev/sdb1
Where=/mnt/data
Type=ext4
Options=defaults,noatime,nosuid,nodev,noexec
```

## Права на файлы конфигурации

```bash
# Права на учетные данные CIFS
sudo chmod 600 /etc/samba/creds

# Права на скрипты-обработчики
sudo chmod 755 /usr/local/bin/luks-handler.sh

# Права на юниты
sudo chmod 644 /etc/systemd/system/mnt-*.mount
```

# Управление конфигурацией (Ansible)

Для массового развертывания используйте модуль `ansible.builtin.template`:

```yaml
---
- name: Deploy Systemd Mount Units
  hosts: all
  become: true
  tasks:
    - name: Install required packages
      ansible.builtin.apt:
        name:
          - systemd
          - nfs-common
          - cifs-utils
        state: present
      when: ansible_os_family == "Debian"

    - name: Install required packages (RHEL)
      ansible.builtin.dnf:
        name:
          - systemd
          - nfs-utils
          - cifs-utils
        state: present
      when: ansible_os_family == "RedHat"

    - name: Deploy mnt-nfs.mount
      ansible.builtin.template:
        src: templates/mnt-nfs.mount.j2
        dest: /etc/systemd/system/mnt-nfs.mount
        owner: root
        group: root
        mode: '0644'
      notify: Reload systemd

    - name: Deploy mnt-smb.mount
      ansible.builtin.template:
        src: templates/mnt-smb.mount.j2
        dest: /etc/systemd/system/mnt-smb.mount
        owner: root
        group: root
        mode: '0644'
      notify: Reload systemd

    - name: Deploy credentials file
      ansible.builtin.template:
        src: templates/smb.creds.j2
        dest: /etc/samba/creds
        owner: root
        group: root
        mode: '0600'
      notify: Reload systemd

    - name: Ensure mount units are running and enabled
      ansible.builtin.systemd:
        name: "{{ item }}"
        state: started
        enabled: true
        daemon_reload: true
      loop:
        - mnt-nfs.mount
        - mnt-smb.mount

  handlers:
    - name: Reload systemd
      ansible.builtin.systemd:
        daemon_reload: true
```

**Шаблон `templates/mnt-nfs.mount.j2`:**
```ini
[Unit]
Description=NFS Share
After=network-online.target
Wants=network-online.target

[Mount]
What={{ nfs_server }}:/srv/data
Where=/mnt/nfs
Type=nfs
Options=rw,soft,timeo=50,_netdev
TimeoutSec=30

[Install]
WantedBy=multi-user.target
```

> **Правило:** Всегда используйте шаблоны и уведомления (`notify`) для перезагрузки systemd daemon после изменения конфигурации.

# Практические рекомендации для SRE

*   **Идемпотентность:** Автоматизируйте развертывание через Ansible/Puppet/Chef. Никаких ручных редактирований.
*   **Резервное копирование:** Сохраняйте версии `/etc/systemd/system/*.mount` в Git.
*   **Именование:** Используйте префикс `mnt-` или `data-` для однозначной идентификации. Следуйте алгоритму `systemd-escape` для сложных путей.
*   **Логирование:** Настройте централизованный сбор логов `journalctl -u mnt-*.mount` через ELK/Graylog.
*   **Документация:** Ведите реестр всех точек монтирования с указанием владельца, SLA и escalation-цепочки.
*   **Тестирование:** Перед внесением изменений в production тестируйте на staging-сервере с аналогичной конфигурацией.
*   **Мониторинг:** Добавьте проверки на `systemctl is-active mnt-*.mount` и `findmnt -t nfs4` в ваши health-checks.
*   **Аудит:** Регулярно проверяйте `/etc/systemd/system/` на наличие устаревших юнитов (отключенные серверы, уволенные сотрудники).

# Очистка и удаление правил

Для удаления mount-юнита:

1.  **Остановите и отключите юнит:**
    ```bash
    sudo systemctl stop mnt-nfs.mount
    sudo systemctl disable mnt-nfs.mount
    ```
2.  **Удалите файл юнита:**
    ```bash
    sudo rm /etc/systemd/system/mnt-nfs.mount
    ```
3.  **Удалите связанные файлы (credentials, скрипты):**
    ```bash
    sudo rm /etc/samba/creds
    ```
4.  **Перезагрузите конфигурацию systemd:**
    ```bash
    sudo systemctl daemon-reload
    ```
5.  **Принудительно размонтируйте зависшие точки:**
    ```bash
    sudo umount -l /mnt/nfs
    # → ленивое размонтирование (очистка после закрытия дескрипторов)
    ```

6.  **Сброс failed-состояния (если необходимо):**
    ```bash
    sudo systemctl reset-failed mnt-nfs.mount
    ```

# Дополнительная информация

*   **[Конфигурация /etc/fstab](../fstab.md)** — сравнение подходов и опции `x-systemd.*`.
*   **[Команды монтирования](../commands.md)** — диагностика через `findmnt`, `systemd-mount`.
*   **[Автоматизация udev](./udev_mount.md)** — динамическое создание юнитов при подключении устройств.
*   **[Перемонтирование (remont)](../remount.md)** — изменение опций на лету, drop-in переопределения.
*   **[Автомонтирование Autofs](./autofs_mount.md)** — альтернатива для сложных корпоративных сценариев.
*   **[NFS: Диагностика](../../../Networking/Services/nfs/nfs_troubleshooting.md)** — устранение неполадок NFS с systemd.
*   **[Структура юнит-файлов](../../Core/systemd/systemd_unit_file_structure.md)** — подробный разбор секций `[Unit]` и `[Install]`.
