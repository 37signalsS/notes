# NFS (Network File System): Обзор

**NFS (Network File System)** — протокол распределенной файловой системы, позволяющий пользователям получать доступ к файлам и каталогам на удаленных компьютерах, управляя ими как локальными.

## Структура документации

| Файл | Описание |
| :--- | :--- |
| [nfs_basics.md](./nfs_basics.md) | Базовые концепции, версии, архитектура |
| [nfs_setup.md](./nfs_setup.md) | Настройка сервера и клиента, монтирование |
| [nfs_security.md](./nfs_security.md) | Безопасность, Kerberos, файрвол |
| [nfs_performance.md](./nfs_performance.md) | Оптимизация, диагностика производительности |
| [nfs_troubleshooting.md](./nfs_troubleshooting.md) | Устранение неполадок |

## Краткая справка

### Версии NFS

| Версия | Особенности | Статус |
| :--- | :--- | :--- |
| **NFSv3** | Stateless, UDP/TCP, нет встроенной безопасности | Устарела, не рекомендуется |
| **NFSv4** | Stateful, только TCP, встроенный security, один порт (2049) | Рекомендуется |
| **NFSv4.1** | Поддержка параллельного NFS (pNFS) для кластеров | Для HPC/кластеров |
| **NFSv4.2** | Server-side copy, sparse files, application I/O hints | Актуальная (2025-2026) |

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

## Связанные темы

- [Samba: SMB для Windows-сетей](../samba/)
- [AutoFS: монтирование по требованию](../../../FileSystems/mounting/scenarios/autofs_mount.md)
- [Kerberos: централизованная аутентификация](../../../../Security/Concepts/kerberos.md)
- [iSCSI: блочный доступ по сети](../iSCSI.md)
- [Настройка файрвола](../Settings/tools/linux_firewall_management.md)
