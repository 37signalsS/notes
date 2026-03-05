# Операции Ceph: управление компонентами

## Определения

**Операции Ceph** — управление компонентами кластера: OSD, пулы, мониторы, MGR, MDS, PG.

> **Навигация:** [Главная Administration](./index.md) | [Мониторинг](./monitoring.md)

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

# Только ошибки
ceph health mute
```

#### Анализ вывода ceph status

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

**Ключевые индикаторы:**

**Мониторы (mon):**

* `quorum node1,node2,node3` — все мониторы в кворуме (норма)
* `quorum 0,1` — кворум есть, но не все мониторы (требуется проверка)

**OSD:**

* `3 up, 3 in` — все OSD работают (норма)
* `2 up, 3 in` — один OSD недоступен (требуется восстановление)
* `3 up, 2 in` — один OSD исключен из кластера

**PG:**

* `active+clean` — норма
* `recovering` — идет восстановление
* `degraded` — не все реплики доступны
* `down` — критическая ошибка

---

### Управление OSD

```bash
# Список OSD с топологией
ceph osd tree

# Статус конкретного OSD
ceph osd stat <osd_id>

# Вывод OSD из кластера
ceph osd out <osd_id>

# Возврат OSD в кластер
ceph osd in <osd_id>

# Удаление OSD (после замены диска)
ceph osd purge <osd_id> --yes-i-really-mean-it
```

---

### Управление пулами

```bash
# Список пулов
ceph osd pool ls

# Информация о пуле
ceph osd pool get <pool_name> all

# Изменение количества PG
ceph osd pool set <pool_name> pg_num <new_pg_num>
ceph osd pool set <pool_name> pgp_num <new_pgp_num>

# Изменение размера репликации
ceph osd pool set <pool_name> size 3

# Удаление пула (осторожно!)
ceph osd pool delete <pool_name> --yes-i-really-really-mean-it
```

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

# Включение модуля (например, dashboard)
ceph mgr module enable dashboard

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
ceph pg dump_undersed
ceph pg dump_incomplete

# Детали по конкретной PG
ceph pg <pg_id> query

# Восстановление PG (осторожно!)
ceph pg repair <pg_id>
```

---

## Additional Information

### Связанные темы

* **[Обзор Ceph](../ceph_overview.md)** — общая информация о Ceph
* **[Расчет PG](../ceph_placement_groups.md)** — расчет Placement Groups
