# NFS: Устранение неполадок

## Definitions

**NFS-диагностика** — процесс выявления и устранения проблем подключения, монтирования, производительности и безопасности NFS. Ключевые симптомы: зависания, stale file handle, permission denied, таймауты, Kerberos-ошибки.

## Basic Concepts

### Инструменты диагностики

| Утилита | Назначение | Пример |
| :--- | :--- | :--- |
| `exportfs -v` | Проверка экспортов на сервере | `exportfs -v` |
| `showmount -e` | Проверка доступных экспортов с клиента | `showmount -e <IP_сервера>` |
| `nfsstat -c` | Статистика клиента NFS | `nfsstat -c` |
| `nfsstat -s` | Статистика сервера NFS | `nfsstat -s` |
| `rpcinfo` | Проверка RPC-служб | `rpcinfo -p <IP_сервера>` |
| `nc` | Проверка доступности портов | `nc -zv <IP> 2049` |

### Логи

```bash
# Журнал NFS на сервере (Debian/Ubuntu)
journalctl -u nfs-kernel-server -f

# Журнал NFS на клиенте
journalctl -u nfs-client.target -f

# Общие системные логи
dmesg | grep -i nfs

# Подробный лог ядра NFS
cat /proc/fs/nfsd/clients/*/info 2>/dev/null
```

## Practical Scenarios

### Диагностика подключений

```bash
# 1. Проверка службы на сервере
systemctl status nfs-kernel-server

# 2. Проверка экспортов на сервере
exportfs -v

# 3. Проверка доступных ресурсов на клиенте
showmount -e <IP_сервера>

# 4. Проверка сетевой доступности
ping -c 5 <IP_сервера>

# 5. Проверка порта 2049 (NFSv4)
nc -zv <IP_сервера> 2049

# 6. Проверка RPC-служб (NFSv3)
rpcinfo -p <IP_сервера>
```

### Монтирование «зависает» или `df` не отвечает

**Причина:** Недоступность NFS-сервера при опции `hard` на клиенте.

**Решение:**

1. Проверьте сетевое соединение: `ping <IP_сервера>`
2. Проверьте службу на сервере: `systemctl status nfs-kernel-server`
3. Если сервер недоступен — размонтируйте лениво: `sudo umount -l /mnt/nfs`
4. После восстановления сервера перемонтируйте: `sudo mount -a`

### Ошибка `Stale file handle`

**Причина:** Файл или директория на сервере были удалены/переименованы, но клиент держит старую inode.

**Решение:**

```bash
# Размонтирование с флагом stale
sudo umount -f /mnt/nfs/stale_path 2>/dev/null || sudo umount -l /mnt/nfs/stale_path

# Перемонтирование
sudo mount -a

# На сервере: проверьте, что экспортируемая директория существует
ls -la /srv/nfs/shared
exportfs -v
```

### Ошибка `Permission denied`

**Причины:**

| Причина | Диагностика | Решение |
| :--- | :--- | :--- |
| Клиент не в `/etc/exports` | `cat /etc/exports` | Добавить IP/подсеть клиента |
| Блокировка файрволом | `sudo ufw status` / `firewall-cmd --list-all` | Открыть порт 2049/tcp |
| UID/GID mismatch | `id` на клиенте и сервере | Централизованная аутентификация (LDAP/NIS) |
| root_squash | Проверьте `exportfs -v` | Использовать обычного пользователя или `no_root_squash` (не рекомендуется) |
| Неправильный sec= | `mount | grep nfs` | Указать корректный `sec=` (sys/krb5/krb5i/krb5p) |

### Ошибка `mount.nfs: Connection timed out`

**Причины:** Сетевые проблемы, файрвол блокирует RPC-порты.

**Решение:**

1. `ping <IP_сервера>` — проверка связности
2. `nc -zv <IP_сервера> 2049` — проверка порта NFS
3. Проверьте файрвол на сервере (ufw/firewalld/iptables)
4. Для NFSv3 убедитесь, что открыты порты 111 (rpcbind), mountd, statd

### Ошибка Kerberos (`Permission denied`, `Authentication failed`)

**Причины:** Истёк TGT-билет, рассинхронизация времени, некорректный principal.

**Решение:**

```bash
# Проверка билета
klist

# Получение нового билета
kinit user@REALM

# Проверка синхронизации времени (допустимое расхождение ≤ 5 мин)
timedatectl status

# Синхронизация времени
sudo systemctl restart systemd-timesyncd

# Проверка keytab на сервере
sudo klist -k /etc/krb5.keytab
```

Подробная настройка Kerberos: [nfs_security.md](./nfs_security.md).

### Проблема: медленная производительность

**Диагностика:**

```bash
# Статистика NFS на клиенте (повторы, таймауты)
nfsstat -c

# Статистика NFS на сервере
nfsstat -s

# I/O-нагрузка на сервере
iostat -x 1

# Сетевые задержки
ping -c 20 <IP_сервера>
```

**Решение:** Проверьте параметры монтирования (`rsize`, `wsize`, `noatime`), выделенную сеть, MTU. Подробно: [nfs_performance.md](./nfs_performance.md).

## Additional Information

Смежные руководства: базовые концепции NFS ([nfs_basics.md](./nfs_basics.md)), настройка сервера/клиента ([nfs_setup.md](./nfs_setup.md)), безопасность NFS ([nfs_security.md](./nfs_security.md)), производительность ([nfs_performance.md](./nfs_performance.md)).
