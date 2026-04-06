# NFS: Безопасность и аутентификация

## Definitions

**NFS-безопасность** — совокупность механизмов аутентификации, авторизации, шифрования и сетевого экранирования для защиты NFS-трафика и данных. Ключевые аспекты: методы аутентификации (sys/krb5), security-флаги (`sec=`), файрвол-правила, root_squash.

## Basic Concepts

### Методы аутентификации

| Метод | Описание | Безопасность | Применение |
| :--- | :--- | :--- | :--- |
| `sys` (AUTH_SYS/UNIX) | Аутентификация на основе UID/GID | Минимальная, UID подделывается | Доверенные изолированные сети |
| `krb5` (AUTH_GSSAPI) | Аутентификация через Kerberos | Средняя, проверка подлинности | Базовая защита в продакшене |
| `krb5i` | Kerberos + проверка целостности | Высокая, защита от модификации | Чувствительные данные |
| `krb5p` | Kerberos + шифрование трафика | Наивысшая, но ниже производительность | Конфиденциальные данные |

### Security-флаги в `/etc/exports`

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

### Файрвол для NFS

**NFSv4 (рекомендуется):** использует только порт **2049/tcp**.

```bash
# ufw
sudo ufw allow from 10.0.0.0/24 to any port 2049 proto tcp

# firewalld
sudo firewall-cmd --permanent --add-service=nfs
sudo firewall-cmd --reload
```

**NFSv3 (не рекомендуется):** требует порты `rpcbind` (111), `mountd`, `statd`, `lockd`. Фиксация портов в `/etc/default/nfs-kernel-server`:

```bash
RPCMOUNTDOPTS="--port 892"
STATDOPTS="--port 893 --outgoing-port 894"
# Для iptables/nftables: откройте порты 111, 2049, 892, 893, 894
```

Подробные концепции файрволов: [firewall_concepts.md](../../../../Networking/Concepts/firewall_concepts.md), практические сценарии: [firewall_common.md](../../../../Linux/Networking/Settings/tools/firewall_common.md).

## Practical Scenarios

### Монтирование с Kerberos

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

### Настройка Kerberos для NFS

1. Получите principal для NFS-сервера: `kadmin -q "addprinc -randkey nfs/server.example.com"`
2. Экспортируйте keytab: `kadmin -q "ktadd /etc/krb5.keytab nfs/server.example.com"`
3. Перезапустите NFS-сервер: `sudo systemctl restart nfs-kernel-server`
4. На клиенте получите пользовательский билет: `kinit user@REALM`
5. Смонтируйте шару с нужным уровнем security

Подробная настройка Kerberos: [kerberos.md](../../../../Security/Concepts/kerberos.md).

### Рекомендации по безопасности

1. **Используйте NFSv4 + Kerberos** (`sec=krb5p`) в продакшене.
2. **Ограничивайте доступ по IP** в `/etc/exports` — избегайте wildcard `*`.
3. **Используйте `root_squash`** (по умолчанию) — маппинг root клиента в `nobody`.
4. **Выделенная сеть/VLAN** для NFS-трафика.
5. **Файрвол** — разрешайте 2049/tcp только из доверенных подсетей.
6. **Избегайте `no_root_squash`** — только при обоснованной необходимости.
7. **Для NFSv3** зафиксируйте порты и ограничьте файрволом.

## Additional Information

Смежные руководства: базовые концепции NFS ([nfs_basics.md](./nfs_basics.md)), настройка сервера/клиента ([nfs_setup.md](./nfs_setup.md)), производительность NFS ([nfs_performance.md](./nfs_performance.md)), устранение неполадок ([nfs_troubleshooting.md](./nfs_troubleshooting.md)), Kerberos ([kerberos.md](../../../../Security/Concepts/kerberos.md)), концепции файрволов ([firewall_concepts.md](../../../../Networking/Concepts/firewall_concepts.md)), настройка файрволов ([firewall_common.md](../../../../Linux/Networking/Settings/tools/firewall_common.md)).
