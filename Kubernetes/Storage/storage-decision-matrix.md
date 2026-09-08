# Матрица выбора хранилища для Kubernetes

## Определения

**Storage Decision Matrix** — систематизированная таблица соответствий между типами хранилищ, требованиями приложений и условиями эксплуатации. Позволяет администратору или архитектору быстро оптимальное решение для конкретного сценария, минимизируя ошибки проектирования.

**Access Mode (режим доступа)** — определяет, сколько подов и на каких узлах могут одновременно читать/писать данные: `ReadWriteOnce` (RWO), `ReadOnlyMany` (ROX), `ReadWriteMany` (RWX), `ReadWriteOncePod` (RWOP).

**Consistency Model (модель согласованности)** — гарантии целостности данных при конкурентном доступе: crash-consistent (снимки уровня СХД), application-consistent (с хуками приложения), strict consistency (блокировки на уровне ФС).

**RPO/RTO** — Recovery Point Objective (максимальная потеря данных) и Recovery Time Objective (время восстановления). Определяют выбор между реплицируемыми и нереплицируемыми решениями.

**Связанные темы:**
- [Сравнение CSI-драйверов](./CSI/csi_drivers_comparison.md) — технические возможности конкретных драйверов.
- [PV и PVC](./pv_and_pvc.md) — базовые концепции хранения.
- [StorageClass](./storageclass.md) — параметры динамического выделения.
- [Longhorn](./longhorn.md) — распределённое блочное хранилище.
- [Ceph — обзор](./Ceph/ceph_overview.md) — SDS-платформа.

---

## Теоретический блок

### Ключевые критерии выбора

| Критерий | Вопрос для принятия решения |
|:---|:---|
| **Тип нагрузки** | Транзакционная (OLTP), аналитическая (OLAP), файловая, архивная? |
| **Режим доступа** | Один под (RWO) или несколько (RWX)? Несколько подов на одном узле (RWO допускает)? |
| **Производительность** | Сколько IOPS? Какая задержка допустима? Нужна ли высокая throughput? |
| **Отказоустойчивость** | Что при потере узла? Данные должны пережить mất 1 узла, 2, или всего кластера? |
| **Масштабируемость** | Нужно расширять объём на лету? Нужно горизонтальное масштабирование? |
| **Стоимость** | Бюджет на SSD/NVMe? Готовность к платить за избыточность? |
| **Сложность** | Есть ли expertise для Ceph/Longhorn? Нужно простое решение? |

### Классификация решений по типу

| Тип | Примеры | Access Modes | Отказоустойчивость | Сложность |
|:---|:---|:---|:---|:---|
| **Локальное** | Local Path, HostPath, TopoLVM, OpenEBS LocalPV | RWO | Нет (потеря узла = потеря данных) | Низкая |
| **Блочное распределённое** | Longhorn, Ceph RBD, LINSTOR/DRBD | RWO, RWOP | Да (репликация) | Средняя–Высокая |
| **Файловое** | NFS, CephFS, JuiceFS | RWX | Зависит от настройки | Средняя |
| **Объектное** | MinIO (S3 CSI), Ceph RGW | RWX (через FUSE) | Да (ерasure coding) | Средняя |
| **Enterprise SAN** | vSphere CSI, Portworx | RWO, RWX | Да | Высокая |

---

## Практический блок

### Матрица: Тип приложения → Рекомендуемое хранилище

| Приложение | Тип нагрузки | Access Mode | Рекомендация | Обоснование |
|:---|:---|:---|:---|:---|
| **PostgreSQL / MySQL (OLTP)** | Транзакционная, высокие IOPS | RWO | **Ceph RBD** или **Longhorn** (replication ≥ 3) | Блочное хранилище, низкая задержка, отказоустойчивость |
| **PostgreSQL / MySQL (OLTP)** | Транзакционная, max IOPS | RWO | **Local PV (NVMe)** | Минимальная задержка, нет overhead репликации (данные на уровне приложения) |
| **MongoDB** | Транзакционная + документы | RWO | **Ceph RBD** или **Longhorn** | Блочное, crash-consistent снимки |
| **Redis (с персистентностью)** | Мелкие блоки, высокий IOPS | RWO | **Local PV (NVMe)** или **Ceph RBD** | Минимальная задержка критична |
| **Kafka** | Sequential write, high throughput | RWO | **Local PV** или **Ceph RBD** | throughput важнее IOPS |
| **Elasticsearch / OpenSearch** | Mixed I/O, bulk write | RWO | **Ceph RBD** или **Local PV** | Блочное для data-нодов |
| **Нармониторинг (Prometheus)** | Sequential write | RWO | **Longhorn** или **Ceph RBD** | Средние IOPS, нужна availability |
| **CI/CD артефакты** | Read-heavy, shared | RWX | **NFS** или **CephFS** | Общий доступ с многих подов |
| **Статический контент (nginx)** | Read-heavy, shared | RWX | **NFS** или **S3 CSI** | RWX, низкая стоимость |
| **Grafana (плагины, аватары)** | Shared, low IOPS | RWX | **NFS** или **CephFS** | RWX обязателен для HA |
| **MinIO (S3-хранилище)** | Object storage backend | RWX | **Ceph RBD** или **Local PV** | Данные MinIO внутри себя |
| **Временные вычисления** | Ephemeral, high speed | RWO | **Generic Ephemeral Volume** | Автоочистка при завершении пода |
| **Edge / IoT (однонодовый)** | Local, low resource | RWO | **Local Path Provisioner** | Минимальный overhead |

### Матрица: Условия эксплуатации → Рекомендуемое хранилище

| Условие | Рекомендация | Избегать |
|:---|:---|:---|
| **Dev/Test (1-2 узла)** | Local Path Provisioner, Longhorn (replicas=1) | Ceph (избыточная сложность) |
| **Production (3-5 узлов)** | Longhorn (replicas=3), Ceph RBD | Local PV (нет HA), NFS для БД |
| **Production (10+ узлов)** | Ceph RBD, CephFS, LINSTOR | Longhorn (ограничение на число реплик) |
| **High IOPS (OLTP, БД)** | Ceph RBD на NVMe, Local PV NVMe | NFS, HDD-based хранилища |
| **High Throughput (логи, архивы)** | NFS, CephFS, S3 CSI | Local PV (нет shared access) |
| **Мультизональный кластер** | Ceph (crush rules), NFS (сетевое) | Longhorn (нет мультизональной репликации) |
| **Air-gapped среда** | Longhorn (air-gapped), Ceph (cephadm) | Облачные CSI-драйверы |
| **Мало ресурсов (edge)** | Local Path Provisioner | Ceph, Longhorn |

### Матрица: RPO/RTO → Стратегия репликации

| RPO | RTO | Решение | Механизм |
|:---|:---|:---|:---|
| 0 (нет потерь) | < 1 мин | Синхронная репликация (Ceph RBD replica 3, DRBD Protocol C) | Данные записываются на все реплики до подтверждения |
| < 15 мин | < 15 мин | Асинхронная репликация (Ceph RBD mirroring, Longhorn DR) | Периодическая синхронизация |
| < 1 ч | < 1 ч | CSI Snapshots + Velero Schedule | Снимки каждые 15-60 мин |
| < 24 ч | < 4 ч | Ежедневные CSI Snapshots + Velero | Полный бэкап + инкрементальные снимки |
| Не критично | < 24 ч | Ручные бэкапы | Регулярный экспорт данных |

### Когда что использовать: Quick Reference

```
Нужен RWX (общий доступ)?
├─ Да → NFS или CephFS
│   ├─ Простое решение → NFS
│   ├─ Высокая производительность → CephFS
│   └─ Нужны снимки → CephFS (CSI snapshots)
└─ Нет → RWO достаточно
    ├─ Максимальные IOPS → Local PV (NVMe)
    ├─ Нужна отказоустойчивость → Ceph RBD или Longhorn
    │   ├─ До 5 узлов → Longhorn
    │   └─ 10+ узлов → Ceph RBD
    └─ Dev/Test → Local Path Provisioner

Нужны снимки (snapshots)?
├─ Да → CSI-драйвер с поддержкой snapshots
│   ├─ Ceph RBD → нативные снимки
│   ├─ Longhorn → снимки + backup в S3
│   └─ NFS → архивы .tar.gz (не нативные снимки)
└─ Нет → любое решение

Нужно расширение тома (expansion)?
├─ Да → StorageClass с allowVolumeExpansion: true
│   └─ Все современные CSI-драйверы поддерживают
└─ Нет → любой StorageClass
```

---

## Дополнительная информация

### Типичные ошибки выбора

| Ошибка | Последствия | Решение |
|:---|:---|:---|
| NFS для PostgreSQL/MySQL | Проблемы с блокировками, порча данных, низкие IOPS | Использовать Ceph RBD или Longhorn (RWO) |
| Local PV для critical production данных | Потеря узла = потеря данных | Использовать реплицируемое хранилище |
| Ceph для dev/test (1-2 узла) | Избыточная сложность, высокий overhead | Local Path Provisioner |
| RWX для транзакционных БД | Проблемы с блокировками файловой системы | RWO + один писатель |
| Longhorn replicas=1 в production | Нет отказоустойчивости | replicas ≥ 3 |

### См. также

- [Сравнение CSI-драйверов](./CSI/csi_drivers_comparison.md) — технические возможности драйверов.
- [Storage Capacity Planning](./storage-capacity-planning.md) — расчёт объёмов.
- [Storage Performance Testing](./storage-performance-testing.md) — тестирование производительности.
- [StatefulSet и хранилище](../Base/StatefulSet/statefulset_core_concepts.md) — паттерны для stateful-приложений.
