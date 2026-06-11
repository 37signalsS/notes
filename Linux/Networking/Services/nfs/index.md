# NFS — сетевая файловая система

## Определения

**NFS (Network File System)** — протокол распределённой файловой системы, позволяющий пользователям получать доступ к файлам и каталогам на удалённых компьютерах и управлять ими как локальными. Используется преимущественно в UNIX-подобных операционных системах для обмена файлами по сети. Работает поверх **RPC (Remote Procedure Call)**, использует порт 2049/TCP (для NFSv4+).

## Основные концепции

### Базовая архитектура

NFS работает по клиент-серверной модели:

- **NFS-сервер** — экспортирует (предоставляет) директории через файл конфигурации `/etc/exports`.
- **NFS-клиент** — монтирует экспортированные директории в свою файловую систему.

### Версии NFS

| Версия | Особенности | Транспорт | Статус |
| :--- | :--- | :--- | :--- |
| **NFSv3** | Stateless, требует rpcbind, нет встроенной безопасности | UDP/TCP | Устарела |
| **NFSv4** | Stateful, один порт (2049), встроенная безопасность | Только TCP | Рекомендуется |
| **NFSv4.1** | Поддержка параллельного NFS (pNFS) для кластеров | Только TCP | Для **HPC (High Performance Computing)** |
| **NFSv4.2** | Server-side copy, sparse files, application I/O hints | Только TCP | Актуальная |

### Безопасность и маппинг

- **root_squash** — функция безопасности, при которой запросы от `root` клиента выполняются сервером от имени анонимного пользователя (`nobody:nogroup`). Это предотвращает получение неограниченного доступа к файловой системе сервера.
- **Маппинг UID/GID (User ID / Group ID)** — NFS оперирует числовыми идентификаторами. Для корректного разделения прав доступа требуется централизованная система идентификации:
  - [LDAP и SSSD](../../../SystemAdministration/Users/LDAP_SSSD/index.md) — современный стандарт.
  - [Kerberos](../../../../Security/Concepts/kerberos.md) — для аутентификации (sec=krb5).

## Практические сценарии

### Быстрый старт

**Настройка сервера (Debian/Ubuntu):**

```bash
sudo apt-get update && sudo apt-get install -y nfs-kernel-server
sudo mkdir -p /srv/nfs/shared
echo "/srv/nfs/shared 10.0.0.0/24(rw,sync,no_subtree_check)" | sudo tee -a /etc/exports
sudo exportfs -a
sudo systemctl restart nfs-kernel-server
```

**Настройка клиента:**

```bash
sudo apt-get update && sudo apt-get install -y nfs-common
sudo mkdir -p /mnt/nfs/shared
sudo mount -t nfs4 10.0.0.5:/srv/nfs/shared /mnt/nfs/shared
```

### Основные руководства

Для детального изучения конкретных аспектов используйте следующие материалы:

- **Установка и настройка:** пакеты, `/etc/exports`, fstab → [nfs_setup.md](./nfs_setup.md)
- **Безопасность:** Kerberos, firewall, права доступа → [nfs_security.md](./nfs_security.md)
- **Производительность:** оптимизация rsize/wsize, nfsstat, pNFS → [nfs_performance.md](./nfs_performance.md)
- **Диагностика:** решение проблем со stale mounts и таймаутами → [nfs_troubleshooting.md](./nfs_troubleshooting.md)

## Дополнительная информация

**Связанные технологии:**

- [Samba: протокол SMB для Windows-сетей](../samba/index.md) — интеграция с Windows.
- [iSCSI: блочный доступ по сети](../../iSCSI/index.md) — блочное хранилище вместо файлового.
- [AutoFS: монтирование по требованию](../../../FileSystems/mounting/scenarios/autofs_mount.md) — динамическое монтирование.
