# NFS — настройка сервера и клиента

---

## Определения

**NFS-настройка** — процесс конфигурации сервера для экспорта файловых ресурсов и клиента для их монтирования. Включает управление правами доступа, маппинг пользователей и обеспечение стабильности сетевого соединения.

**Экспорт (Export)** — директория на сервере, доступная для монтирования удалённым клиентам. Конфигурируется в файле `/etc/exports`.

---

## Основные концепции

### Компоненты системы

1.  **nfs-server (или nfs-kernel-server):** Основной демон сервера, обрабатывающий запросы ввода-вывода.
2.  **rpc.idmapd:** Демон маппинга имен пользователей и групп для NFSv4. Обеспечивает согласованность прав, когда UID/GID на клиенте и сервере не совпадают.
3.  **rpcbind:** Служба сопоставления портов RPC. Необходима для NFSv3; в чистых средах NFSv4 может быть отключена.
4.  **exportfs:** Утилита для управления списком экспортируемых директорий. Позволяет обновлять конфигурацию без остановки демона.
5.  **rpc.gssd:** Демон на клиенте, реализующий RPCSEC_GSS-аутентификацию (Kerberos). Подробная настройка описана в [NFS: Безопасность](./nfs_security.md).
6.  **rpc.svcgssd:** Демон на сервере для обработки GSS-API-запросов. Включите только при использовании `sec=krb5*`.

### Параметры экспорта (`/etc/exports`)

| Опция | Описание |
| :--- | :--- |
| `rw` / `ro` | Разрешение записи или только чтение. |
| `sync` | Синхронная запись: подтверждение клиенту только после записи на физический диск (безопасно). |
| `async` | Асинхронная запись: высокая производительность, но риск повреждения данных при сбое питания. |
| `root_squash` | Преобразует `root` клиента в `nobody` на сервере. **Рекомендуется** для безопасности. |
| `no_root_squash` | Позволяет `root` клиента сохранять права `root` на сервере. Использовать с осторожностью. |
| `all_squash` | Маппит всех пользователей в анонимного (`anonuid`/`anongid`). Идеально для публичных хранилищ. |
| `anonuid` / `anongid` | Используется с `all_squash` для явного указания UID/GID анонимного пользователя. |
| `no_subtree_check` | Отключает проверку того, что запрашиваемый файл находится именно в экспортируемом поддереве. Повышает производительность. |

### Параметры монтирования (fstab)

| Опция | Описание |
| :--- | :--- |
| `nfsvers=4.2` | Явное указание версии протокола для стабильности. |
| `hard` | Клиент будет бесконечно повторять попытки при недоступности сервера (защита от повреждения данных). |
| `soft` | Клиент вернет ошибку после `retrans` попыток. Риск повреждения данных в некоторых приложениях. |
| `timeo=600` | Таймаут RPC-запроса (в децисекундах, 600 = 60 сек). |
| `rsize` / `wsize` | Максимальный размер блока данных (в байтах) для чтения/записи. Обычно `1048576` (1МБ). |
| `nconnect=N` | (NFSv4.2+) Использование N параллельных TCP-соединений для одного монтирования. Повышает пропускную способность. |
| `_netdev` | Откладывает монтирование до поднятия сетевых интерфейсов. |
| `noatime` | Отключает обновление времени доступа при чтении. Снижает нагрузку на метаданные. |
| `actimeo=60` | TTL кэша атрибутов (секунды). Уменьшает количество GETATTR-запросов при работе с мелкими файлами. |
| `fsc` | Включает FS-Cache (локальное кэширование на диске клиента через `cachefilesd`). |
| `intr` / `nointr` | `intr` разрешает прерывание зависших запросов сигналами (устарело в современных ядрах); `nointr` — поведение по умолчанию. |

### Виртуальное корневое дерево NFSv4 (Pseudo Root)

В отличие от NFSv3, NFSv4 требует наличия виртуального корневого дерева (pseudo root), к которому монтируются все экспорты. Это позволяет использовать единый корневой путь для всех ресурсов, упрощая администрирование и правила сетевого экрана. Сервер объединяет все экспорты под одним корнем, а клиент монтирует путь внутри pseudo-root, а не директорию напрямую.

### Современная конфигурация (`/etc/nfs.conf`)

Современные дистрибутивы используют единый конфигурационный файл `/etc/nfs.conf` вместо отдельных файлов `/etc/default/nfs-kernel-server` (Debian) или `/etc/sysconfig/nfs` (RHEL). Файл имеет секции `[nfsd]`, `[mountd]`, `[statd]`, `[lockd]`.

Пример настройки количества потоков демона:
```ini
[nfsd]
threads=128
```

Проверка текущего значения:
```bash
cat /proc/fs/nfsd/threads
# → 128
```

---

## Практические сценарии

### Развёртывание NFS-сервера

#### Шаг 1. Установка пакетов

**Debian/Ubuntu:**
```bash
sudo apt update && sudo apt install -y nfs-kernel-server
# → success
```

**RHEL/CentOS/Rocky:**
```bash
sudo dnf install -y nfs-utils
sudo systemctl enable --now nfs-server
# → success
```

#### Шаг 2. Конфигурация домена идентификации

Для корректного маппинга имен в NFSv4 отредактируйте `/etc/idmapd.conf` на всех узлах:
```ini
[General]
Domain = example.local  # Должно быть идентично на сервере и клиенте
```

#### Шаг 3. Настройка экспорта

1.  Создайте и подготовьте директорию:
    ```bash
    sudo mkdir -p /srv/nfs/shared
    sudo chown nobody:nogroup /srv/nfs/shared  # На RHEL: nfsnobody или nobody
    ```
2.  Добавьте правило в `/etc/exports`:
    ```text
    /srv/nfs/shared 10.0.0.0/24(rw,sync,no_subtree_check,root_squash)
    ```
3.  Примените изменения:
    ```bash
    sudo exportfs -ra
    sudo exportfs -v
    # → /srv/nfs/shared 10.0.0.0/24(rw,wdelay,root_squash,no_subtree_check,...)
    ```

#### Шаг 4. Настройка сервера через `/etc/nfs.conf`

Настройка количества потоков демона `nfsd` через современный конфигурационный файл:
```ini
# /etc/nfs.conf
[nfsd]
threads=128
```

Примените изменения:
```bash
sudo systemctl restart nfs-server
cat /proc/fs/nfsd/threads
# → 128
```

### Настройка NFS-клиента

1.  **Установка утилит:**
    ```bash
    # Debian/Ubuntu: sudo apt install nfs-common
    # RHEL/CentOS: sudo dnf install nfs-utils
    ```

2.  **Проверка доступных ресурсов:**
    ```bash
    showmount -e 10.0.0.5
    # → Export list for 10.0.0.5: /srv/nfs/shared 10.0.0.0/24
    ```

3.  **Постоянное монтирование (`/etc/fstab`):**
    ```text
    10.0.0.5:/srv/nfs/shared  /mnt/shared  nfs  nfsvers=4.2,hard,timeo=600,nconnect=4,_netdev  0 0
    ```

4.  **Активация монтирования:**
    ```bash
    sudo mkdir -p /mnt/shared
    sudo mount -a
    # → success
    ```

### Монтирование через systemd-юнит

Для интеграции с systemd и автоматического монтирования после готовности сети используйте отдельный mount-юнит вместо fstab. Это даёт лучший контроль над порядком запуска и зависимостями.

Создайте файл `/etc/systemd/system/mnt-shared.mount`:
```ini
[Unit]
Description=NFS Shared Directory
After=network-online.target
Wants=network-online.target

[Mount]
What=10.0.0.5:/srv/nfs/shared
Where=/mnt/shared
Type=nfs
Options=nfsvers=4.2,hard,timeo=600,nconnect=4,_netdev

[Install]
WantedBy=multi-user.target
```

Активируйте:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mnt-shared.mount
# → success
```

### Расширенное управление экспортами (`exportfs`)

Помимо базового `exportfs -ra`, утилита позволяет тонко управлять экспортами:

```bash
# Добавить отдельный экспорт с индивидуальными опциями
sudo exportfs -o rw,sync,root_squash 10.0.0.42:/srv/nfs/secure

# Удалить экспорт без перезапуска демона
sudo exportfs -u 10.0.0.42:/srv/nfs/secure

# Просмотр всех активных экспортов
sudo exportfs -v
# → /srv/nfs/shared 10.0.0.0/24(rw,wdelay,root_squash,no_subtree_check,...)
```

### Верификация и диагностика

Проверьте параметры активного соединения:
```bash
nfsstat -m
# → /mnt/shared from 10.0.0.5:/srv/nfs/shared
# → Flags: rw,relatime,vers=4.2,rsize=1048576,wsize=1048576,namlen=255,hard,proto=tcp,nconnect=4,...
```

Дополнительные проверки:
```bash
# Проверка зарегистрированных RPC-служб на сервере
rpcinfo -p 10.0.0.5
# → program 100003 version 4 ready and waiting

# Просмотр статистики монтирования
cat /proc/self/mountstats | grep -A5 "/mnt/shared"
# → device 10.0.0.5:/srv/nfs/shared mounted on /mnt/shared

# Проверка потока nfsd на сервере
cat /proc/fs/nfsd/threads
# → 128
```

---

## Дополнительная информация

### Настройка Сетевого экрана

- **UFW:** `sudo ufw allow from 10.0.0.0/24 to any port 2049 proto tcp`
- **Firewalld:** `sudo firewall-cmd --permanent --add-service=nfs && sudo firewall-cmd --reload`
- **iptables / nftables (ручные правила):**
  ```bash
  # iptables
  sudo iptables -A INPUT -p tcp --dport 2049 -s 10.0.0.0/24 -j ACCEPT
  sudo iptables -A INPUT -p tcp --dport 2049 -j DROP

  # nftables
  sudo nft add rule inet filter input tcp dport 2049 ip saddr 10.0.0.0/24 accept
  sudo nft add rule inet filter input tcp dport 2049 drop
  ```

### Особенности SELinux (RHEL)

Если на сервере включен SELinux, необходимо разрешить экспорт директорий:
```bash
# Для существующих директорий
sudo chcon -t nfs_t /srv/nfs/shared
# Постоянная метка
sudo semanage fcontext -a -t nfs_t "/srv/nfs/shared(/.*)?"
sudo restorecon -Rv /srv/nfs/shared
```

### Устранение неполадок

- **Зависание при `ls` или `df`:** Сервер недоступен. Если монтирование `hard`, процессы уйдут в состояние `D` (uninterruptible sleep). Используйте `umount -l /mnt/shared` для отложенного размонтирования.
- **Все файлы принадлежат `nobody`:** Ошибка маппинга `idmapd`. Проверьте параметр `Domain` в `/etc/idmapd.conf` и перезапустите `nfs-idmapd`.
- **Ошибка "Protocol not supported":** Проверьте, что версия, указанная в `nfsvers`, поддерживается сервером (`rpcinfo -p`).

### Резервное копирование и восстановление

NFS-ресурсы следует монтировать с опцией `hard` для предотвращения повреждения данных при сбоях. При создании резервных копий:

1. Используйте `rsync` с опцией `--timeout` для долгих операций.
2. Для снапшотов LVM/ZFS на сервере предпочитайте `sync` запись.
3. После восстановления данных проверяйте `nfsstat -m` на клиентах — наличие `wsize`/`rsize` ниже ожидаемого может указывать на разрыв сессии.

### Продакшен-чеклист

Перед выводом NFS-сервиса в production убедитесь:

- [ ] Используется только NFSv4.2 (отключите NFSv3 в `/etc/nfs.conf` или `/etc/default/nfs-kernel-server`).
- [ ] `root_squash` применён ко всем экспортам.
- [ ] Экспорт ограничен конкретными IP-адресами (не именами хостов).
- [ ] Порты 2049/tcp разрешены только в доверенной подсети.
- [ ] На клиентах установлен `_netdev` в fstab или используется systemd mount-юнит.
- [ ] Проверен статус `nfs-idmapd` на сервере и клиенте (`systemctl status nfs-idmapd`).
- [ ] SELinux-метки применены на сервере при необходимости (`semanage fcontext`, `restorecon`).

### Связанные темы

- **[Базовые концепции NFS](./index.md)** — архитектура, версии и блокировки.
- **[Безопасность NFS](./nfs_security.md)** — настройка Kerberos (RPCSEC_GSS) и списки доступа.
- **[Производительность](./nfs_performance.md)** — глубокий тюнинг `rsize`/`wsize` и pNFS.
- **[Высокая доступность (HA)](./nfs_ha.md)** — DRBD + Pacemaker, Keepalived, failover.
- **[Мониторинг](./nfs_monitoring.md)** — Prometheus, node_exporter, Grafana.
- **[Выбор ФС](./nfs_filesystem.md)** — XFS vs ext4 для NFS-сервера.
- **[Резервное копирование](./nfs_backup.md)** — rsync, borgbackup, LVM снапшоты.
- **[Автоматическое монтирование](../../../../Linux/FileSystems/mounting/scenarios/autofs_mount.md)** — динамическое подключение через AutoFS.
- **[Systemd mount-юниты](../../../../Linux/FileSystems/mounting/scenarios/systemd_mount.md)** — монтирование через systemd.
