# Etcd: распределённое хранилище Kubernetes

**Etcd** — распределённое согласованное хранилище ключ-значение, используемое в Kubernetes как единственный источник правды (Single Source of Truth).

## Навигация

### Основы

- **[Основы и архитектура](./etcd_basics.md)** — свойства, сравнение с альтернативами, роль в Kubernetes
- **[Практические сценарии](./etcd_operations.md)** — etcdctl, watch, эксплуатационные рекомендации
- **[Альтернативы и безопасность](./etcd_alternatives_and_security.md)** — Kine, шифрование данных

---

## Ключевые свойства

- **Согласованность (CP по CAP)** — строгая согласованность через кворум
- **Raft** — алгоритм консенсуса с лидером
- **Watch** — уведомления об изменениях в реальном времени
- **MVCC** — версионирование через ревизии

---

## Быстрый старт

```bash
export ETCDCTL_API=3

# Запись и чтение
etcdctl put foo bar
etcdctl get foo

# Создание снапшота
etcdctl snapshot save /backup/etcd.snap
```

---

## Связанные документы

- **[Архитектура Control Plane](./control_plane_architecture.md)** — роль etcd в управляющем слое
- **[Алгоритм Raft](../../etcd/raft_consensus.md)** — детали консенсуса
- **[MVCC и версионирование](../../etcd/mvcc_versioning_and_compaction.md)** — управление параллельным доступом
- **[Кластеризация и восстановление](../../etcd/clustering_and_recovery.md)** — развёртывание и бэкап
- **[Мониторинг etcd](../../etcd/etcd_monitoring.md)** — ключевые метрики и алертинг
- **[CAP-теорема](../../Databases/Concepts/cap_theorem.md)** — фундаментальные принципы распределённых систем
