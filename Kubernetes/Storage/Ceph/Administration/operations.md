# Операции Ceph: управление компонентами

## Definitions

**Операции Ceph** — управление компонентами кластера: OSD, пулы, мониторы, MGR, MDS, PG.

---

## Basic Concepts

### Иерархия компонентов

Кластер Ceph управляется через централизованный CLI `ceph`, который взаимодействует с демонами в строгой иерархии:

1. **MON** (мониторы) — хранят карту кластера, обеспечивают кворум
2. **MGR** (менеджеры) — метрики, модули, внешние API
3. **OSD** (демоны хранения) — хранение данных на дисках, репликация
4. **MDS** (серверы метаданных) — метаданные для CephFS

### Placement Groups (PG)

PG — внутренняя абстракция для распределения объектов по OSD. Каждый пул делится на PG, PG распределяются по OSD через алгоритм CRUSH.

> **Расчёт:** [ceph_placement_groups.md](../ceph_placement_groups.md)

### Режимы здоровья

| Статус | Описание |
|--------|----------|
| `HEALTH_OK` | Все компоненты работают штатно |
| `HEALTH_WARN` | Есть предупреждения, работа продолжается |
| `HEALTH_ERR` | Критические ошибки, требуется вмешательство |

### Ключевые индикаторы `ceph status`

| Компонент | Норма | Предупреждение | Критическое |
|-----------|-------|----------------|-------------|
| **MON** | `quorum node1,node2,node3` | `quorum 0,1` (не все) | Нет кворума |
| **OSD** | `3 up, 3 in` | `2 up, 3 in` | `0 up` |
| **PG** | `active+clean` | `recovering`, `degraded` | `down` |

---

## Practical Scenarios

### Проверка состояния кластера

```bash
# Быстрая проверка
ceph -s

# Подробный статус
ceph status

# Детали здоровья
ceph health detail

# Отключение предупреждений (временное)
ceph health mute
```

Пример вывода команды `ceph status`:

```
$ ceph status

  cluster:
    id:     a1b2c3d4-...
    health: HEALTH_OK

  services:
    mon: 3 daemons, quorum node1,node2,node3 (age 2m)
    mgr: node1(active, since 2m), standbys: node2, node3
    mds: cephfs:1 {0=node1=up:active} 2 up:standby
    osd: 3 osds: 3 up (since 2m), 3 in (since 2m)

  data:
    pools:   2 pools, 64 pgs
    objects: 100 objects, 10 GiB
    usage:   10 GiB used, 80 GiB / 90 GiB avail
    pgs:     64 active+clean
```

---

### Управление OSD

```bash
# Список OSD с топологией
ceph osd tree

# Статус конкретного OSD
ceph osd stat <osd_id>

# Вывод OSD из кластера (данные реплицируются)
ceph osd out <osd_id>

# Возврат OSD в кластер
ceph osd in <osd_id>

# Удаление OSD (после замены диска, данные удаляются)
ceph osd purge <osd_id> --yes-i-really-mean-it
```

---

### Управление пулами

```bash
# Список пулов
ceph osd pool ls

# Информация о пуле
ceph osd pool get <pool_name> all

# Изменение количества PG (увеличение)
ceph osd pool set <pool_name> pg_num <new_pg_num>
ceph osd pool set <pool_name> pgp_num <new_pgp_num>

# Изменение размера репликации
ceph osd pool set <pool_name> size 3

# Удаление пула (требует подтверждения безопасности)
ceph osd pool delete <pool_name> --yes-i-really-really-mean-it
```

> **Важно:** Уменьшение `pg_num` возможно, но требует осторожности. См. [Расчет PG](../ceph_placement_groups.md).

---

### Управление мониторами

```bash
# Список мониторов
ceph mon dump

# Добавление монитора
ceph mon add <mon_name> <ip:port>

# Удаление монитора
ceph mon remove <mon_name>

# Проверка кворума
ceph quorum_status
```

---

### Управление MGR

```bash
# Статус менеджеров
ceph mgr dump

# Список доступных модулей
ceph mgr module ls

# Включение модуля (например, dashboard или prometheus)
ceph mgr module enable dashboard
ceph mgr module enable prometheus

# Перезапуск MGR
ceph mgr fail <mgr_name>
```

---

### Управление MDS (для CephFS)

```bash
# Статус MDS
ceph mds stat

# Детальная информация
ceph mds dump

# Изменение количества активных MDS
ceph fs set cephfs max_mds 2

# Перезапуск MDS
ceph mds fail <mds_name>
```

---

### Диагностика PG

```bash
# Статус PG
ceph pg stat

# PG в неоптимальном состоянии
ceph pg dump_stale
ceph pg dump_incomplete

# Детали по конкретной PG
ceph pg <pg_id> query

# Восстановление PG (осторожно!)
ceph pg repair <pg_id>
```

---

## Additional Information

**Связанные темы:** [Обзор Ceph](../ceph_overview.md) · [Расчет PG](../ceph_placement_groups.md) · [Мониторинг Ceph](./monitoring.md) · [Главная Administration](./index.md) · [Настройка CephFS](../cephfs_setup_and_usage/practical_scenarios.md)
