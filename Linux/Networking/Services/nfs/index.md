# NFS (Network File System)

## Definitions → Basic Concepts → Practical Scenarios → Additional Information

**NFS (Network File System)** — протокол распределённой файловой системы, позволяющий пользователям получать доступ к файлам и каталогам на удалённых компьютерах, управляя ими как локальными. Используется преимущественно в UNIX-средах для обмена файлами по сети.

## Basic Concepts

Базовая архитектура: клиент монтирует экспортированную директорию сервера в свою файловую систему через порт 2049/TCP (NFSv4+).

| Версия | Особенности | Статус |
| :--- | :--- | :--- |
| **NFSv3** | Stateless, UDP/TCP, нет встроенной безопасности | Устарела, не рекомендуется |
| **NFSv4** | Stateful, только TCP, встроенный security, один порт (2049) | Рекомендуется |
| **NFSv4.1** | Поддержка параллельного NFS (pNFS) для кластеров | Для HPC/кластеров |
| **NFSv4.2** | Server-side copy, sparse files, application I/O hints | Актуальная (2025-2026) |

**Ключевые концепции:**

- **Клиент-серверная модель** — сервер экспортирует директории, клиент монтирует
- **RPC/rpcbind** — механизм обнаружения служб (для NFSv4 менее критичен)
- **root_squash** — маппинг root клиента в nobody:nogroup для безопасности
- **UID/GID маппинг** — требует централизованной идентификации (NIS, LDAP)

Подробная архитектура и версии → [nfs_basics.md](./nfs_basics.md)

## Practical Scenarios

### Быстрый старт

**Сервер (Debian/Ubuntu):**

```bash
sudo apt-get install -y nfs-kernel-server
sudo mkdir -p /srv/nfs/shared
echo "/srv/nfs/shared 10.0.0.0/24(rw,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -a
sudo systemctl restart nfs-kernel-server
```

**Клиент:**

```bash
sudo apt-get install -y nfs-common
sudo mount -t nfs4 10.0.0.5:/srv/nfs/shared /mnt/nfs/shared
```

### Основные сценарии

- **Настройка сервера/клиента, монтирование, fstab** → [nfs_setup.md](./nfs_setup.md)
- **Безопасность: Kerberos (sec=krb5/firewall)** → [nfs_security.md](./nfs_security.md)
- **Оптимизация: rsize/wsize, nfsstat, pNFS** → [nfs_performance.md](./nfs_performance.md)
- **Диагностика: staled mounts, таймауты** → [nfs_troubleshooting.md](./nfs_troubleshooting.md)

## Additional Information

**Связанные протоколы:**

- [Samba: SMB для Windows-сетей](../samba/index.md) — альтернатива для Windows-сред
- [iSCSI: блочный доступ по сети](../../iSCSI/index.md) — блочное хранилище вместо файлового
- [AutoFS: монтирование по требованию](../../../FileSystems/mounting/scenarios/autofs_mount.md) — динамическое монтирование NFS
- [Kerberos: централизованная аутентификация](../../../../Security/Concepts/kerberos.md) — для NFSv4 security (sec=krb5)
