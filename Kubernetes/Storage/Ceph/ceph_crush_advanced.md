# CRUSH: продвинутые темы

Руководство по углубленной работе с алгоритмом CRUSH и картой кластера Ceph. Документ актуален для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

> **Границы документа:** базовое описание CRUSH — в [Обзоре Ceph](./ceph_overview.md#алгоритм-crush); расчет Placement Groups — в [Расчете PG](./ceph_placement_groups.md); практические сценарии с device classes — в [Операциях Ceph](./Administration/operations.md#6-манипуляции-с-топологией-crush-и-балансировка).

## Определения

**CRUSH Map** — иерархическое описание физической топологии кластера (buckets и items), используемое алгоритмом CRUSH для вычисления расположения объектов без центрального индекса.

**CRUSH Tunables** — набор параметров, управляющих поведением алгоритма при выборе OSD. Влияют на балансировку, recovery и чувствительность к недавним изменениям в карте.

**Failure Domain** — уровень иерархии (host, rack, row, datacenter, region), на котором Ceph гарантирует разделение реплик данных. Выбор failure domain определяет отказоустойчивость кластера.

**Device Class** — логическая категория диска (`hdd`, `ssd`, `nvme`, `zns`), используемая для создания тиров хранения и ограничения пулов определенным классом устройств.

**CRUSH Rule** — шаблон размещения, определяющий:
- Тип replication или erasure coding
- Failure domain для разделения реплик
- Количество экземпляров (size/k/m)
- Используемый класс устройств

**CRUSH Peering** — процесс согласования расположения PG между OSD после изменения карты. CRUSH peering гарантирует, что PG могут быть восстановлены после изменения топологии.

## Базовые концепции

### Структура CRUSH-карты

```
root (default)
 ├── datacenter dc1
 │   ├── rack rack-a
 │   │   ├── host host-a
 │   │   │   ├── osd.0  (hdd)
 │   │   │   ├── osd.1  (hdd)
 │   │   │   └── osd.2  (ssd)
 │   │   └── host host-b
 │   │       ├── osd.3  (hdd)
 │   │       ├── osd.4  (hdd)
 │   │       └── osd.5  (ssd)
 │   └── rack rack-b
 │       ├── host host-c
 │       └── host host-d
 └── datacenter dc2
     ├── rack rack-c
     └── rack rack-d
```

**Компоненты карты:**
- **Buckets** — контейнеры (root, datacenter, rack, host, osd). Могут быть homogeneous или heterogeneous.
- **Items** — листья дерева (обычно osd.N).
- **Algorithms:** `tree` (современный, эффективный), `straw2` (по умолчанию в Squid/Tentacle/Umbrella), `crush-compat` (legacy).

### CRUSH Tunables

| Tunable | Назначение | Рекомендация (Squid/Tentacle/Umbrella) |
|---------|-----------|----------------------------------------|
| `recovery_size_autoset` | Автоматически подбирает размер recovery-чанков | `true` |
| `select_recency_count` | Количество последних изменений для учета при балансировке | `100` |
| `choose_local_tries` | Попытки выбора OSD на локальном узле перед переходом к удаленным | `0` |
| `choose_local_fallback_tries` | Fallback-попытки на локальном узле | `0` |
| `choose_total_tries` | Общее количество попыток выбора OSD | `50` |
| `chooseleaf_descend_once` | Ограничивает выбор leaf-OSD одной попыткой | `1` |

```bash
# Просмотр текущих tunables
ceph config get osd crush_tunables

# Установка рекомендуемых значений для Squid/Tentacle
ceph config set osd crush_tunables '{"recovery_size_autoset":true,"select_recency_count":100}'
```

### Failure Domain Design

Выбор failure domain определяет, на каком уровне Ceph будет разделять реплики:

| Domain | Отказоустойчивость | Пример использования |
|--------|-------------------|---------------------|
| `host` | Потеря одного сервера | Малая/средняя группа узлов |
| `rack` | Потеря стойки | Крупный кластер, >2 racks |
| `row` | Потеря ряда стоек | Многорастяжные ЦОДы |
| `datacenter` | Потеря ЦОД | Multi-site replication |
| `region` | Потеря региона | Geo-distributed clusters |

**Правила проектирования:**
- Минимальный recommendation: `host` для кластеров < 5 racks.
- Для multi-rack: `rack` как failure domain, иначе потеря стойки деградирует все PG.
- Для multi-datacenter: `datacenter` + EC правила с k=m распределением по sites.

## Практические сценарии

### 1. Просмотр и анализ CRUSH-карты

```bash
# Древовидная иерархия
ceph osd tree

# CRUSH map в текстовом виде
ceph osd getcrushmap -o /tmp/crushmap.bin
crushtool -d /tmp/crushmap.bin -o /tmp/crushmap.txt
less /tmp/crushmap.txt

# Проверка device classes
ceph osd crush class ls
ceph osd crush tree hdd
ceph osd crush tree nvme
```

### 2. Создание и применение CRUSH правил

#### 2.1 Replicated rule для HDD

```bash
# Создание правила
ceph osd crush rule create-replicated hdd_rule default host hdd

# Проверка
ceph osd crush rule ls
ceph osd crush rule dump hdd_rule

# Применение к пулу
ceph osd pool set <pool-name> crush_rule hdd_rule
```

#### 2.2 Replicated rule для NVMe

```bash
ceph osd crush rule create-replicated nvme_rule default host nvme
ceph osd pool set <pool-name> crush_rule nvme_rule
```

#### 2.3 EC rule с failure domain rack

```bash
# Создание профиля EC
ceph osd erasure-code-profile set ec-4-2 \
  k=4 m=2 \
  crush-failure-domain=rack \
  crush-device-class=hdd

# Создание правила на основе профиля
ceph osd crush rule create-replicated ec-rack-rules default rack ec-rack

# Создание EC-пула
ceph osd pool create ec-pool 128 erasure ec-4-2
ceph osd pool application enable ec-pool rgw
```

### 3. Управление device classes

```bash
# Назначение класса OSD
ceph osd crush set-device-class hdd osd.0 osd.1 osd.2
ceph osd crush set-device-class ssd osd.3 osd.4 osd.5
ceph osd crush set-device-class nvme osd.6 osd.7

# Удаление класса (сброс в None)
ceph osd crush rm-device-class hdd osd.0

# Создание кастомного класса
ceph osd crush class create zns
ceph osd crush set-device-class zns osd.8
```

### 4. CRUSH Tunables: настройка и версионирование

```bash
# Просмотр текущих значений
ceph config get osd crush_tunables

# Установка для Squid/Tentacle/Umbrella
ceph config set osd crush_tunables '{"recovery_size_autoset":true,"select_recency_count":100}'

# Проверка после изменений
ceph osd crush show-tunables
```

**Важно:** Tunables сохраняются в CRUSH map. При downgrade на старую версию Ceph могут потребоваться `crushtool -t` для конвертации.

### 5. CRUSH map backup и restore

```bash
# Backup
ceph osd getcrushmap -o /backup/ceph/crushmap-$(date +%F).bin

# Restore (осторожно!)
ceph osd setcrushmap -i /backup/ceph/crushmap-2026-09-30.bin

# Проверка после restore
ceph osd tree
ceph health detail
```

> **Предупреждение:** `setcrushmap` — опасная операция. Убедитесь, что кластер `HEALTH_OK` и нет активного recovery. Всегда тестируйте restore на тестовом кластере.

### 6. Балансировка и upmap

```bash
# Включение balancer
ceph balancer on
ceph balancer mode upmap

# План балансировки (без применения)
ceph balancer eval

# Применение плана
ceph balancer execute

# Проверка статуса
ceph balancer status
```

**Когда использовать upmap vs crush-compat:**
- `upmap` — точечная балансировка, минимальное перемещение данных. Подходит для production.
- `crush-compat` — глобальная перебалансировка, больше перемещений. Требуется для старых версий.

### 7. Advanced: создание кастомных bucket types

```bash
# Экспорт карты
crushtool -d /tmp/crushmap.bin -o /tmp/crushmap.txt

# Редактирование: добавление кастомного bucket
# В /tmp/crushmap.txt добавьте:
#   zone myzone {
#       id -100
#       alg straw2
#       hash 0
#       item host-e weight 1.000
#       item host-f weight 1.000
#   }

# Компиляция обратно
crushtool -c /tmp/crushmap.txt -o /tmp/crushmap-new.bin

# Применение
ceph osd setcrushmap -i /tmp/crushmap-new.bin
```

## Лучшие практики

### Проектирование

1. **Начинайте с `host` failure domain** для небольших кластеров (< 5 racks).
2. **Используйте `rack` или выше** для кластеров > 5 racks — иначе потеря стойки деградирует все PG.
3. **Разделяете данные по классам устройств** — HDD для cold data, NVMe для hot data.
4. **Не смешивайте диски разных размеров** в один failure domain без учета весов.
5. **Бэкап crushmap** перед каждым изменением.

### Эксплуатация

1. **Не редактируйте crushmap вручную в production** без тестирования.
2. **Используйте balancer** вместо ручного reweight — он учитывает PG distribution.
3. **Мониторьте дисбаланс** через `ceph osd df tree` и `ceph balancer eval`.
4. **Обновляйте tunables** при переходе на новую major версию Ceph.

### Ограничения

- `crushtool` работает offline; для применения нужен `ceph osd setcrushmap`.
- Изменение failure domain требует пересоздания пулов (PG пересчитаются).
- Некоторые tunables (например, `choose_total_tries`) влияют на производительность — тестируйте перед применением в production.

## Дополнительная информация

### См. также

- [Обзор Ceph](./ceph_overview.md) — CRUSH алгоритм, базовые понятия
- [Расчет PG](./ceph_placement_groups.md) — влияние CRUSH на PG placement
- [Операции Ceph](./Administration/operations.md) — device classes, CRUSH правила, balancer
- [Углубленная диагностика OSD/PG](./ceph_osd_troubleshooting.md) — recovery procedures
- [Сетевая архитектура](./ceph_networking.md) — failure domain design

### Официальные ресурсы

- [Ceph CRUSH Map](https://docs.ceph.com/en/latest/rados/operations/crush-map/) — официальное руководство
- [Ceph CRUSH Tunables](https://docs.ceph.com/en/latest/rados/configuration/crush-map/) — tunables reference
- [Ceph Balancer](https://docs.ceph.com/en/latest/rados/operations/balancer/) — балансировка нагрузки
