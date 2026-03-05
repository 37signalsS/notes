# NFS: Безопасность

## Аутентификация

### AUTH_SYS (UNIX)

По умолчанию, основана на UID/GID. **Небезопасно в ненадёжных сетях.**

### Kerberos (AUTH_GSSAPI)

Рекомендуется для продакшена. Обеспечивает аутентификацию, целостность и шифрование.

| Режим | Описание |
| :--- | :--- |
| `krb5` | Аутентификация |
| `krb5i` | Аутентификация + целостность |
| `krb5p` | Аутентификация + целостность + шифрование (наивысшая безопасность, ниже производительность) |

Подробности настройки Kerberos см. [Kerberos](../../../Security/Concepts/kerberos.md).

## Секьюрити-флаги в `/etc/exports`

```ini
# Стандартная UNIX-аутентификация (по умолчанию)
/srv/nfs/data 10.0.0.0/24(rw,sync,sec=sys)

# Kerberos-аутентификация
/srv/nfs/secure 10.0.0.0/24(rw,sync,sec=krb5)

# Kerberos с проверкой целостности
/srv/nfs/integrity 10.0.0.0/24(rw,sync,sec=krb5i)

# Kerberos с шифрованием (максимальная безопасность)
/srv/nfs/encrypted 10.0.0.0/24(rw,sync,sec=krb5p)
```

## Настройка файрвола

### NFSv4 (рекомендуется)

Использует только порт **2049/tcp**.

```bash
# Для ufw
sudo ufw allow from 10.0.0.0/24 to any port 2049 proto tcp

# Для firewalld
sudo firewall-cmd --permanent --add-service=nfs
sudo firewall-cmd --reload
```

### NFSv3 (не рекомендуется)

Требует дополнительные порты для `rpcbind` (111), `mountd`, `statd`, `lockd`.

```bash
# Фиксация портов в /etc/default/nfs-kernel-server (Debian/Ubuntu)
RPCMOUNTDOPTS="--port 892"
STATDOPTS="--port 893 --outgoing-port 894"

# Для iptables/nftables добавьте правила для портов 111, 2049, 892, 893, 894
```

Подробнее см. [Настройка файрвола в Linux](../Settings/linux_firewall_management.md).

## Монтирование с Kerberos

**Временное монтирование:**

```bash
sudo mount -t nfs4 -o sec=krb5p 10.0.0.5:/srv/nfs/shared /mnt/nfs/shared
```

**Через `/etc/fstab`:**

```ini
10.0.0.5:/srv/nfs/shared  /mnt/nfs/shared  nfs4  hard,sec=krb5p,_netdev  0  0
```

**Проверка билета Kerberos:**

```bash
# Проверка билета
klist

# Получение нового билета
kinit user@REALM
```

## Связанные документы

- [Базовые концепции](./nfs_basics.md)
- [Настройка NFS](./nfs_setup.md)
- [Kerberos: централизованная аутентификация](../../../Security/Concepts/kerberos.md)
- [Настройка файрвола](../Settings/linux_firewall_management.md)
