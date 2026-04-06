# NFS: Базовые концепции

## Definitions

**NFS (Network File System)** — протокол распределённой файловой системы, позволяющий клиентам монтировать удалённые директории сервера как локальные. Работает поверх RPC, использует порт 2049/TCP (NFSv4+).

## Basic Concepts

### Клиент-серверная модель

- **NFS-сервер** — экспортирует (предоставляет) директории через `/etc/exports`
- **NFS-клиент** — монтирует экспорты в свою ФС через `mount -t nfs4`
- **RPC/rpcbind** — служба обнаружения портов (для NFSv4 необязательна, весь трафик через 2049)

### Версии NFS

| Версия | Транспорт | Состояние | Безопасность | Примечание |
| :--- | :--- | :--- | :--- | :--- |
| **NFSv3** | UDP/TCP | Устарела | Отсутствует (sec=sys) | Stateless, несколько портов |
| **NFSv4** | TCP only | Рекомендуется | sec=krb5/krb5i/krb5p | Stateful, один порт (2049) |
| **NFSv4.1** | TCP only | Стабильна | sec=krb5/krb5i/krb5p | pNFS для кластеров/HPC |
| **NFSv4.2** | TCP only | Актуальная | sec=krb5/krb5i/krb5p | Server-side copy, sparse files, LABELS |

### Безопасность: root_squash

Функция по умолчанию: запросы от `root` клиента выполняются сервером от имени `nobody:nogroup`. Предотвращает эскалацию привилегий. Отключается опцией `no_root_squash` (только для доверенных сетей).

### Маппинг UID/GID

NFS оперирует числовыми UID/GID. Для корректного доступа в многохостовых средах требуется централизованная идентификация:

- **NIS** — устаревший, не рекомендуется
- **LDAP/SSSD** — современный стандарт ([LDAP и SSSD](../../../SystemAdministration/Users/LDAP_SSSD/index.md))
- **FreeIPA** — LDAP + Kerberos + DNS

### Архитектура

```
┌─────────────┐         ┌─────────────┐
│ NFS-клиент  │ ──────► │ NFS-сервер  │
│ 10.0.0.10   │  :2049  │ 10.0.0.5    │
│             │  TCP    │             │
└─────────────┘         └─────────────┘
      │                        │
      ▼                        ▼
  /mnt/nfs/shared        /srv/nfs/shared
```

## Practical Scenarios

### Проверка версии NFS на клиенте

```bash
nfsstat -m          # Статистика монтирования
cat /proc/mounts | grep nfs  # Активные NFS-монтирования
```

### Диагностика RPC

```bash
rpcinfo -p 10.0.0.5   # Проверка служб (NFSv3)
systemctl status rpcbind  # Статус rpcbind
```

## Additional Information

Подробные руководства: настройка сервера/клиента и fstab ([nfs_setup.md](./nfs_setup.md)), Kerberos и файрвол ([nfs_security.md](./nfs_security.md)), оптимизация rsize/wsize и pNFS ([nfs_performance.md](./nfs_performance.md)), диагностика stale mounts ([nfs_troubleshooting.md](./nfs_troubleshooting.md)). Краткая справка — [index.md](./index.md).
