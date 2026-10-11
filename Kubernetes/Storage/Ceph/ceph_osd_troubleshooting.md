# Углубленная диагностика и восстановление OSD/PG

Руководство по расширенной диагностике и восстановлению после сбоев на уровне OSD и Placement Groups в кластере Ceph. Документ актуален для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

> **Границы документа:** базовое управление OSD (добавление, замена, удаление) описано в [Операциях Ceph](./Administration/operations.md#2-управление-osd-классические-и-crimson); общая диагностика кластера — в [Обзоре Ceph](./ceph_overview.md#состояние-кластера-и-решение-проблем-troubleshooting); наблюдаемость и scrubbing — в [Мониторинге Ceph](./Administration/monitoring.md).

## Определения

**OSD States (состояния OSD):**
- `in` / `out` — участвует ли OSD в распределении данных (CRUSH map).
- `up` / `down` — отвечает ли демон (процесс запущен, сеть доступна).
- `destroyed` — OSD помечен уничтоженным с сохранением ID для переиспользования.
- `stopped` — остановлен оркестратором `cephadm`.

**Peering** — процесс согласования состояния PG между всеми OSD, хранящими реплики этой PG. Peering завершается успешно, когда все реплики согласованы и PG переходит в `active`.

**Stale PG** — PG, для которой не удается запустить peering (нет доступных OSD или они не отвечают).

**Bit Rot** — "тихая" порча данных на уровне физических секторов диска, обнаруживаемая только Deep Scrubbing.

**Recovery vs Backfill:**
- **Recovery** — восстановление деградированных реплик внутри существующего набора OSD.
- **Backfill** — полное перераспределение PG на новые/пустые OSD после изменения карты CRUSH.

## Базовые концепции

### Жизненный цикл OSD: от установки до вывода

```
┌──────────┐    ceph orch apply osd    ┌──────────┐
│  Новый    │ ───────────────────────► │   OSD     │
│  диск     │                          │  up/in    │
└──────────┘                          └─────┬────┘
                                            │
                              Сбой диска/процесса
                                            ▼
┌──────────┐    ceph osd out/id     ┌──────────┐
│  Выход    │ ◄───────────────────── │   OSD     │
│  из строя │                        │  down/out │
└──────────┘                        └─────┬────┘
                                            │
                              Замена оборудования
                                            ▼
┌──────────┐    ceph orch osd rm    ┌──────────┐
│  Удаление │ ◄───────────────────── │   OSD     │
│  OSD      │                        │ destroyed │
└──────────┘                        └──────────┘
```

### Состояния PG и их интерпретация

| Состояние PG | Значение | Действие |
|--------------|----------|----------|
| `active+clean` | Нормальное состояние | — |
| `active+degraded` | Не хватает реплик | Ожидание recovery |
| `active+remapped` | PG временно перемещена | Ожидание backfill |
| `active+undersized` | Меньше реплик, чем `min_size` | Критично — проверяйте `min_size` |
| `incomplete` | Peering не удался | Данные недоступны |
| `stale` | PG не обновлялась долгое время | Проверяйте OSD и сеть |
| `backfilling` | Идет backfill | Мониторинг `ceph status` |
| `recovering` | Идет recovery | Мониторинг `ceph status` |
| `scrubbing` | Light scrub | Автоматически |
| `deep` | Deep scrub | Автоматически |

## Практические сценарии

### 1. Диагностика OSD в состоянии down

#### 1.1 Быстрая диагностика

```bash
# 1. Общий статус
ceph status
# → health: HEALTH_WARN
# → 1 osds down

# 2. Какой OSD down?
ceph osd tree
# → ID  CLASS  WEIGHT   TYPE NAME          STATUS
# → 5    hdd    1.0           osd.5            down  1.00

# 3. Проверка логов
journalctl -u ceph-osd@5 --since "1 hour ago"

# 4. Проверка доступности диска
ssh host-b "lsblk | grep sdb"
ssh host-b "smartctl -H /dev/sdb"
```

#### 1.2 OSD down, но диск здоров

```bash
# Перезапуск демона
ceph orch daemon restart osd.5

# Проверка
ceph osd tree
# → osd.5  up  1.00
```

#### 1.3 OSD down из-за проблем с диском

```bash
# 1. Вывести OSD из распределения
ceph osd out 5

# 2. Дождаться завершения recovery
ceph pg stat
# → 312 active+clean, 12 active+recovering

# 3. Заменить диск (см. Operations)
ceph orch osd rm 5 --replace
# → физическая замена диска
# → автоматическое пересоздание OSD
```

### 2. Восстановление после peering failure

#### 2.1 Диагностика

```bash
# Найти PG с peering problems
ceph health detail
# → PG <pg-id>: stale

# Детализация PG
ceph pg <pg-id> query
# → state: stale+active+undersized
# → acting: [5,7,9]
# → up: [5,7,9]

# Проверка, какие OSD доступны
ceph osd tree
# → osd.5  down
# → osd.7  up
# → osd.9  up
```

#### 2.2 Восстановление peering

```bash
# Вариант A: Вернуть OSD в up
ceph osd in 5
# → peering запустится автоматически

# Вариант B: Если OSD недоступен, использовать emergency repair
ceph pg <pg-id> repair

# Вариант C: Принудительный peering (опасно!)
ceph pg <pg-id> force-merge <pg-id> <pg-id>
```

> **Предупреждение:** принудительные операции (`force-*`, `repair`) могут привести к потере данных. Используйте только когда стандартный peering невозможен и у вас есть свежий бэкап.

### 3. Stuck PG: recovery/backfill завис

#### 3.1 Диагностика

```bash
# PG, которые долго не переходят в active+clean
ceph pg stat
# → 312 active+clean, 12 active+recovering

# Проверка конкретной PG
ceph pg <pg-id> query | grep -E 'state|since|mtime'
# → state: active+recovering
# → since: 3 days ago

# Проверка OSD, на которых находится PG
ceph pg map <pg-id>
# → osd.5 [5,7,9]
```

#### 3.2 Частые причины и решения

**Причина 1: Оставлены флаги `norecover`/`nobackfill`**

```bash
# Проверка активных флагов
ceph osd dump | grep flags

# Снятие флагов
ceph osd unset norecover
ceph osd unset nobackfill
```

**Причина 2: `backfillfull_ratio` превышен на целевых OSD**

```bash
# Проверка заполнения OSD
ceph osd df tree
# → osd.7  98% full (backfillfull_ratio = 0.9)

# Решения:
# 1. Освободить место (удалить снапшоты, расширить кластер)
# 2. Временно поднять порог (только для анализа!)
ceph osd set-backfillfull-ratio 0.95
# → после завершения backfill вернуть обратно
ceph osd set-backfillfull-ratio 0.9
```

**Причина 3: Низкая параллельность recovery**

```bash
# Повысить параллельность
ceph config set osd osd_max_backfills 2
ceph config set osd osd_recovery_max_active 4

# Или использовать mclock профиль
ceph config set osd osd_mclock_profile high_recovery_ops
```

**Причина 4: OSD в состоянии `full`/`nearfull`**

```bash
# Проверка порогов
ceph config get mon mon_osd_full_ratio
ceph config get mon mon_osd_nearfull_ratio

# Временное повышение (только для освобождения места!)
ceph osd set-full-ratio 0.97
# → удалите неиспользуемые данные
ceph osd set-full-ratio 0.95
```

### 4. Восстановление кворума MON

#### 4.1 Частичная потеря кворума (остался ≥1 MON)

```bash
# Проверка состояния MON
ceph mon stat
# → e5: 2 mons at {host-a=10.0.0.1:6789/0, host-b=10.0.0.2:6789/0}, election epoch 12, quorum 0,1 host-a,host-b

# Добавить недостающего MON
ceph orch apply mon --placement="3 host-a host-b host-c"
# → здоровые MON синхронизируют store нового MON
```

#### 4.2 Полная потеря кворума (все MON недоступны)

```bash
# Путь А: Есть свежий бэкап store MON
# 1. Остановить все демоны на узлах с MON
ceph orch daemon stop mon.host-a
ceph orch daemon stop mon.host-b
ceph orch daemon stop mon.host-c

# 2. Восстановить store из бэкапа
ceph-mon -i host-a --restore-backup /backup/mon-host-a/ --yes-i-really-mean-it
ceph-mon -i host-b --restore-backup /backup/mon-host-b/ --yes-i-really-mean-it

# 3. Запустить большинство MON
ceph orch daemon start mon.host-a
ceph orch daemon start mon.host-b

# 4. Проверить кворум
ceph mon stat
```

```bash
# Путь Б: Нет бэкапа, восстановление из данных OSD
# См. подробное руководство в [Операциях Ceph](./Administration/operations.md#82-потеря-кворума-mon)
```

### 5. Data Corruption: bit rot и inconsistent objects

#### 5.1 Обнаружение

```bash
# Deep scrub на подозрительной PG
ceph pg <pg-id> deep-scrub

# Просмотр результатов
ceph health detail
# → <pg-id>: 3 objects inconsistent

# Детализация
ceph pg <pg-id> query | grep -A5 "inconsistent"
```

#### 5.2 Восстановление

```bash
# Repair (автоматически исправляет inconsistent objects)
ceph pg <pg-id> repair

# Если repair не помогает — проверяйте резервные копии
# и контакты Ceph Foundation для enterprise-поддержки
```

> **Важно:** repair работает только если у Ceph есть валидная копия объекта на другом OSD. Если все реплики повреждены — данные теряются.

### 6. BlueStore: проверка и ремонт

#### 6.1 BlueStore fsck

```bash
# Проверка целостности BlueStore на OSD
ceph-bluestore-tool fsck --path /var/lib/ceph/osd/<cluster-id>/osd.<id>

# Просмотр метаданных
ceph-bluestore-tool show-label --path /var/lib/ceph/osd/<cluster-id>/osd.<id>
```

#### 6.2 Восстановление поврежденного OSD

```bash
# Экспорт данных из поврежденного OSD
ceph-objectstore-tool --data-path /var/lib/ceph/osd/<fsid>/osd.<id> \
  --type bluestore --op export --out /tmp/osd-export.bin

# Импорт в новый OSD
ceph-objectstore-tool --data-path /var/lib/ceph/osd/<fsid>/osd.<new-id> \
  --type bluestore --op import --in /tmp/osd-export.bin
```

### 7. Типовые инциденты: таблица быстрого поиска

| Симптом | Причина | Диагностика | Решение |
|----------|---------|-------------|---------|
| OSD down, диск не обнаружен | Аппаратный сбой | `lsblk`, `smartctl`, `journalctl` | Замена диска, `ceph orch osd rm --replace` |
| OSD down, диск есть, процесс упал | Ошибка ядра/памяти | `journalctl -u ceph-osd@<id>` | `ceph orch daemon restart osd.<id>` |
| PG stuck в recovering | Низкая параллельность | `ceph pg <pg-id> query` | Повысить `osd_max_backfills`, проверить `backfillfull` |
| PG stuck в backfilling | Целевые OSD полные | `ceph osd df tree` | Освободить место, поднять `backfillfull_ratio` временно |
| Peering failure | OSD недоступен | `ceph pg <pg-id> query` | Вернуть OSD в `in`, или `ceph pg repair` |
| Stale PG | MON не получили обновление | `ceph pg stat`, `ceph health detail` | Проверить сеть, вернуть OSD в `up` |
| inconsistent objects | Bit rot | `ceph pg <pg-id> deep-scrub` | `ceph pg <pg-id> repair` |
| MON lost quorum | Падение большинства MON | `ceph mon stat` | Добавить/восстановить MON |
| OSD full, запись заблокирована | `full_ratio` достигнут | `ceph df`, `ceph osd dump` | Освободить место, временно поднять порог |

## Лучшие практики

### Диагностика

1. **Триада диагностики при любом инциденте:**
   - `ceph status` — общая картина
   - `ceph health detail` — конкретные коды
   - `ceph df` + `ceph osd df tree` — заполнение и баланс

2. **Логирование:** перед деструктивными операциями соберите логи:
   ```bash
   journalctl -u ceph-osd@* -u ceph-mon@* -u ceph-mgr@* > /var/log/ceph-pre-incident-$(date +%F).log
   ```

3. **Верификация после восстановления:**
   ```bash
   ceph status                    # → HEALTH_OK
   ceph pg stat                   # → все PG active+clean
   ceph osd tree                  # → все OSD up/in
   ceph health detail             # → нет критических кодов
   ```

### Профилактика

- **Мониторинг SMART:** регулярный сбор `smartctl -a` для прогнозирования отказов.
- **Скорость scrubbing:** настройте `osd_scrub_begin_hour`/`osd_scrub_end_hour` для часов минимальной нагрузки.
- **Резервные копии:** бэкап состояния кластера еженедельно и перед каждым апгрейдом.
- **Game Day:** тренируйте процедуру восстановления кворума MON на тестовом кластере.

### Ограничения

- Принудительные операции (`force-*`, `repair`, `scrub cancel`) применяются только при исчерпании стандартных путей.
- Восстановление из `ceph-objectstore-tool` требует остановки OSD-демона.
- Полная потеря кворума MON без бэкапа — сценарий для enterprise-поддержки Ceph Foundation.

## Дополнительная информация

### См. также

- [Операции Ceph](./Administration/operations.md) — управление OSD, хостами, MON/MGR, аварийные процедуры
- [Мониторинг Ceph](./Administration/monitoring.md) — алертинг, метрики, scrubbing
- [Обзор Ceph](./ceph_overview.md) — состояния здоровья, базовая диагностика
- [Резервное копирование и DR](./ceph_backup_and_dr.md) — бэкап данных и конфигурации

### Официальные ресурсы

- [Ceph Troubleshooting Guide](https://docs.ceph.com/en/latest/rados/troubleshooting/) — официальные методики
- [Ceph OSD Troubleshooting](https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-osd/) — проблемы с OSD
- [Ceph Monitor Troubleshooting](https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-mon/) — проблемы с MON
- [Ceph PG Troubleshooting](https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-pg/) — проблемы с PG
