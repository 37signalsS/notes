# Операции Ceph: управление компонентами

## Определения

**Операции Ceph** — совокупность практических действий по управлению жизненным циклом компонентов кластера: OSD (Object Storage Daemon — демон хранения объектов), пулов, PG (Placement Group — группа размещения), MON (Monitor — монитор), MGR (Manager — менеджер) и MDS (Metadata Server — сервер метаданных).

> **Базовые концепции и архитектура:** [Администрирование Ceph — Обзор](./index.md)

---

## Базовые концепции

### Ключевые индикаторы состояния (`ceph status`)

Для оперативного контроля используются индикаторы, отображаемые в выводе команды `status`:

| Компонент | Норма | Предупреждение | Критическое |
|:----------|:------|:---------------|:------------|
| **MON (монитор)** | `quorum node1,node2,node3` | `quorum 0,1` (не все узлы) | Отсутствие кворума |
| **OSD (демон хранения объектов)** | `N up, N in` | `N-1 up, N in` | `0 up` (все демоны отключены) |
| **PG (Placement Group — группа размещения)** | `active+clean` | `recovering`, `degraded` | `down`, `incomplete` |

---

## Практические сценарии

### Проверка состояния кластера

```bash
# Быстрая проверка здоровья
ceph -s

# Подробный статус всех компонентов
ceph status

# Детализация текущих предупреждений и ошибок
ceph health detail

# Временное отключение (mute) предупреждений
ceph health mute
```

### Управление OSD (Object Storage Daemon)

```bash
# Список всех OSD с их физической топологией (карта CRUSH — Controlled Replication Under Scalable Hashing)
ceph osd tree

# Статус конкретного демона хранения
ceph osd stat <osd_id>

# Вывод OSD из эксплуатации (запуск перераспределения данных)
ceph osd out <osd_id>

# Возврат OSD в работу
ceph osd in <osd_id>

# Полное удаление OSD из кластера (например, для замены диска)
ceph osd purge <osd_id> --yes-i-really-mean-it
```

### Управление пулами

```bash
# Список существующих пулов
ceph osd pool ls

# Просмотр всех параметров пула
ceph osd pool get <pool_name> all

# Изменение количества групп размещения (PG)
ceph osd pool set <pool_name> pg_num <new_pg_num>
ceph osd pool set <pool_name> pgp_num <new_pgp_num>

# Настройка количества реплик
ceph osd pool set <pool_name> size 3

# Удаление пула (требует подтверждения безопасности в конфигурации)
ceph osd pool delete <pool_name> --yes-i-really-really-mean-it
```

> **Важно:** Любые изменения `pg_num` должны быть предварительно рассчитаны. См. [Расчет PG](../ceph_placement_groups.md).

### Управление мониторами (MON)

```bash
# Просмотр карты мониторов
ceph mon dump

# Добавление нового монитора в кластер
ceph mon add <mon_name> <ip:port>

# Удаление монитора
ceph mon remove <mon_name>

# Проверка текущего статуса кворума
ceph quorum_status
```

### Управление менеджерами (MGR)

```bash
# Статус активного и резервных менеджеров
ceph mgr dump

# Список и управление модулями (например, dashboard или prometheus)
ceph mgr module ls
ceph mgr module enable <module_name>

# Принудительный перезапуск менеджера
ceph mgr fail <mgr_name>
```

---

## Дополнительная информация

**Связанные темы:**
- [Администрирование Ceph — Обзор](./index.md) — базовые концепции и архитектура.
- [Мониторинг Ceph](./monitoring.md) — метрики, алерты и логирование.
- [Расчет PG](../ceph_placement_groups.md) — формулы для настройки групп размещения.
