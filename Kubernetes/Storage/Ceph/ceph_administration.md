# Администрирование Ceph

## Определения

**`ceph status`** — основная команда для проверки здоровья и состояния кластера. Выводит сводку по всем компонентам: MON, MGR, OSD, MDS, PG, пулы.

## Основные концепции

Вывод команды `ceph status` организован по секциям, отражающим различные аспекты работы кластера:

1. **`cluster`**: Общая информация о кластере.
    * **`id`**: Уникальный идентификатор кластера.
    * **`health`**: Общее состояние здоровья кластера.
2. **`services`**: Информация о состоянии ключевых демонов Ceph.
    * **`mon` (мониторы)**: Отвечают за поддержание карты кластера и обеспечение кворума.
    * **`mgr` (менеджеры)**: Предоставляют дополнительные интерфейсы мониторинга и управления.
    * **`mds` (серверы метаданных)**: Используются для CephFS, управляют метаданными файловой системы.
    * **`osd` (демоны хранения объектов)**: Хранят данные, обрабатывают репликацию и восстановление.
3. **`data`**: Сводная информация о данных, хранимых в кластере.
    * **`pools`**: Логические разделы для хранения объектов.
    * **`objects`**: Количество хранимых объектов.
    * **`usage`**: Использование дискового пространства.
    * **`pgs` (Placement Groups)**: Группы размещения, в которых хранятся объекты.

## Практические сценарии

### Проверка состояния кластера с помощью `ceph status`

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

#### Анализ вывода

1. **`cluster`**:
    * **`id`**: Уникальный идентификатор кластера в шестнадцатеричном формате.
    * **`health`**: Общее состояние кластера.
        * `HEALTH_OK`: Идеальное состояние, все в порядке.
        * `HEALTH_WARN`, `HEALTH_ERR`: Указывают на наличие проблем, требующих внимания.

2. **`services`**:
    * **`mon`**: Состояние демонов-мониторов. `3 daemons, quorum node1,node2,node3` означает, что все три монитора работают и достигли кворума, что критически важно для стабильности кластера.
    * **`mgr`**: Состояние демонов-менеджеров. `ingress1(active, since 2m), standbys: node1, node2` показывает одного активного менеджера и остальных в режиме ожидания, готовых к переключению.
    * **`mds`**: Состояние серверов метаданных для CephFS. `cephfs:1 {0=ingress1=up:active} 2 up:standby` указывает на один активный MDS для файловой системы `cephfs` и другие в режиме ожидания.
    * **`osd`**: Состояние демонов хранения. `3 osds: 3 up (since 2m), 3 in (since 2m)` означает, что все 3 OSD запущены (`up`) и активно участвуют в распределении данных (`in`).

3. **`data`**:
    * **`pools`**: Сводка по пулам. `2 pools, 64 pgs` показывает наличие 2 пулов и 64 Placement Group в сумме.
    * **`objects`**: Количество объектов и общий объем данных, хранящихся в кластере. `0 objects, 0 B` типично для нового кластера.
    * **`usage`**: Использование дискового пространства.
        * `3.0 GiB used`: Место, занятое служебными данными Ceph (например, для CephFS).
        * `27 GiB / 30 GiB avail`: `30 GiB` — это общая "сырая" емкость всех OSD-дисков. `27 GiB` — доступное пространство.
        * **Важно**: Доступное пространство не равно полезному пространству для записи. Из-за фактора репликации (по умолчанию `size=3`), запись 1 ГБ данных займет 3 ГБ на дисках. Таким образом, из 27 ГБ доступного пространства полезными для записи будут только 9 ГБ (27 / 3).
    * **`pgs`**: Состояние Placement Group.
        * `64 active+clean`: Идеальное состояние. Все 64 PG активны и "чисты" (все реплики в порядке).
        * При возникновении проблем (например, ребалансировка, восстановление), здесь будут отображаться другие состояния PG (например, `recovering`, `backfilling`, `degraded`), указывающие на текущий статус или неисправность.

#### Ключевые индикаторы

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

### Использование дискового пространства

```
usage: 10 GiB used, 80 GiB / 90 GiB avail
```

**Важно**: Доступное пространство ≠ полезное пространство для записи.

При репликации `size=3`:

* Из 80 GiB доступного полезно только ~26.7 GiB (80 / 3)
* 1 GiB данных занимает 3 GiB на дисках

## Практические сценарии

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

### Балансировка кластера

```bash
# Статус балансировки
ceph osd df

# Запуск балансировки
ceph osd reweight-by-utilization

# Ручная балансировка
ceph osd reweight <osd_id> <weight>
```

### Работа с ключами доступа

```bash
# Список ключей
ceph auth list

# Экспорт ключа
ceph auth get client.admin -o /etc/ceph/ceph.client.admin.keyring

# Создание пользователя
ceph auth get-or-create client.<name> mon 'allow r' osd 'allow rw pool=<pool>'

# Удаление пользователя
ceph auth del client.<name>
```

### Логирование

```bash
# Просмотр логов в реальном времени
ceph -w

# Последние события
ceph log last 100

# Дамп логов
ceph log dump
```

## Дополнительная информация

### Рекомендуемые практики

| Задача | Частота | Примечание |
|--------|---------|------------|
| Проверка `ceph -s` | Ежедневно | Быстрый мониторинг |
| Проверка дискового пространства | Еженедельно | Планирование расширения |
| Аудит пользователей | Ежемесячно | Безопасность |
| Тестирование бэкапа | Ежемесячно | Восстановление данных |
| Обновление Ceph | По выходу stable | Следить за EOL версий |

### Автоматизация мониторинга

Пример Prometheus-алертов:

```yaml
# ceph_alerts.yml
groups:
- name: ceph
  rules:
  - alert: CephHealthWarning
    expr: ceph_health_status == 1
    for: 5m
    labels:
      severity: warning
  - alert: CephHealthError
    expr: ceph_health_status == 2
    for: 1m
    labels:
      severity: critical
  - alert: CephOSDDown
    expr: ceph_osd_up == 0
    for: 5m
    labels:
      severity: warning
```

### Ссылки

* [Обзор Ceph](ceph_overview.md)
* [Расчет PG](ceph_placement_groups.md)
* [Официальная документация](https://docs.ceph.com/en/latest/admin/)
