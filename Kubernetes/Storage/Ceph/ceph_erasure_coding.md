# Erasure Coding в Ceph: Практическое руководство

Документ охватывает теорию, создание и управление Erasure Coding (EC) пулами в Ceph. Является справочником для DevOps/SRE/sysadmin, принимающих решения о выборе между репликацией и EC, а также выполняющих настройку в продуктовых средах. Актуально для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

---

## Определения

**Erasure Coding (EC, коды стирания)** — метод хранения данных, при котором объект разбивается на `k` данныхых фрагментов и генерируется `m` контрольных (паритетных) фрагментов. Позволяет выдерживать выход из строя `m` OSD без потери данных, при этом потребляя `(k+m)/k` места вместо коэффициента репликации.

**Код Галоя (Reed-Solomon)** — класс кодов коррекции ошибок, используемых Ceph для EC. Позволяет восстановить данные по любым `k` фрагментам из `k+m` доступных.

**Erasure Code Profile (Профиль EC)** — именованный набор параметров EC: `k` (количество данныхых фрагментов), `m` (количество паритетных), `plugin` (алгоритм кодирования), `technique` (вариант алгоритма). Профиль создаётся один раз и переиспользуется для множества пулов.

**`allow_ec_overwrites`** — параметр пула, необходимый для CephFS с EC. Позволяет выполнять partial writes (запись отдельных блоков файла) без перезаписи всего объекта, что обеспечивает POSIX-совместимость.

**Minimum Persistent Size** — минимальный объём данных, который должен быть записан в EC-пул, чтобы Ceph гарантировал их сохранность. Равен `stripe_width * (k+m)/k`.

---

## Базовые концепции

### Репликация vs Erasure Coding

| Критерий | Репликация | Erasure Coding |
|----------|------------|----------------|
| **Хранение** | N копий | (k+m)/k объёма данных |
| **Потеря дисков** | N-1 дисков | m дисков |
| **Чтение** | С любой реплики (быстро) | Декодирование k из (k+m) |
| **Запись** | Параллельная на N OSD | Кодирование, запись на (k+m) OSD |
| **Восстановление** | Копирование целого объекта | Вычисление недостающих фрагментов |
| **Recovery I/O** | Среднее | Высокое (чтение k фрагментов для восстановления 1) |
| **Стоимость хранения** | Высокая (×3 при size=3) | Низкая (×1.5 при 4+2) |
| **Латентность записи** | Низкая | Средняя (кодирование) |
| **Сценарий** | Высокопроизводительные Нагрузки, СУБД | Холодные данные, архивы, бэкапы, медиа |

### Когда использовать Erasure Coding

**Используйте EC когда:**
- Объём данных большой (>10 ТБ) и стоимость хранения критична
- Данные преимущественно читаются (архивы, логи, медиа)
- Допустима повышенная латентность записи
- Кластер имеет достаточно OSD (минимум k+m, рекомендуется k+m+2 для балансировки)
- Используется CephFS с `allow_ec_overwrites`

**Не используйте EC когда:**
- Критична минимальная латентность записи (СУБД, OLTP)
- Маленький объём данных (накладные расходы на кодирование не окупаются)
- Кластер мал (<6 OSD — недостаточно для равномерного распределения)
- Частые partial writes без `allow_ec_overwrites`

### Формула расчёта ёмкости

```
Фактическое использование = Логический объём × (k+m)/k
```

Примеры:

| Профиль | Коэффициент | 1 ТБ данных физически | Доступная ёмкость |
|---------|-------------|----------------------|-------------------|
| 4+2 | 1.5x | 1.5 ТБ | 1 ТБ |
| 8+4 | 1.5x | 1.5 ТБ | 1 ТБ |
| 4+1 | 1.25x | 1.25 ТБ | 1 ТБ |
| 6+3 | 1.5x | 1.5 ТБ | 1 ТБ |
| Репликация 3x | 3x | 3 ТБ | 0.33 ТБ |

### Минимальное количество OSD

| Профиль | Минимум OSD | Рекомендуется |
|---------|-------------|---------------|
| 4+2 | 6 | 9-12+ |
| 8+4 | 12 | 15-18+ |
| 4+1 | 5 | 8+ |
| 6+3 | 9 | 12+ |

> **Важно:** при k+m OSD в кластере каждый OSD хранит ~100% своей доли. При потере m+1 OSD — данные потеряны. Рекомендуется иметь запас OSD для балансировки и recovery.

### Влияние на PG

PG в EC-пуле должны быть кратны `k`:

```bash
# Для EC 4+2 (k=4): pg_num должен быть кратен 4
ceph osd pool create ec-pool 256 256 erasure ec-profile
# 256 / 4 = 64 — корректно

# НЕКОРРЕКТНО:
ceph osd pool create ec-pool 100 100 erasure ec-profile
# 100 / 4 = 25 — не целое число → неравномерное распределение
```

См. подробности в [Расчёте PG](./ceph_placement_groups.md).

---

## Практические сценарии

### 1. Создание Erasure Code Profile

#### 1.1 Базовый профиль (Reed-Solomon)

```bash
# Профиль 4+2 (выдерживает потерю 2 OSD, коэффициент 1.5x)
ceph osd erasure-code-profile set ec-4-2 \
  plugin=jerasure \
  technique=reed_sol_r6_op \
  k=4 m=2 \
  crush-failure-domain=host \
  stripe_width=4194304

# Проверка созданного профиля
ceph osd erasure-code-profile get ec-4-2
```

#### 1.2 Профиль для CephFS (с allow_ec_overwrites)

```bash
# Профиль для CephFS data пула
ceph osd erasure-code-profile set cephfs-ec-profile \
  plugin=jerasure \
  technique=reed_sol_r6_op \
  k=4 m=2 \
  crush-failure-domain=host \
  stripe_width=4194304

# Проверка
ceph osd erasure-code-profile get cephfs-ec-profile
```

#### 1.3 Профиль с кастомным CRUSH-правилом

```bash
# Профиль с failure-domain "rack" (реплики EC в разных стойках)
ceph osd erasure-code-profile set ec-rack \
  plugin=jerasure \
  technique=reed_sol_r6_op \
  k=4 m=2 \
  crush-failure-domain=rack \
  stripe_width=4194304

# Создание CRUSH-правила для этого профиля
ceph osd crush rule create-replicated ec-rack-rules default rack ec-rack
```

### 2. Создание EC-пула

#### 2.1 Простой EC-пул

```bash
# Шаг 1: Создание пула (сначала как replicated, затем переключение)
ceph osd pool create ec-data 256 256 replicated

# Шаг 2: Применение EC-профиля
ceph osd pool set ec-data erasure_code_profile ec-4-2

# Шаг 3: Привязка к приложению
ceph osd pool application enable ec-data rgw

# Проверка
ceph osd pool ls detail | grep ec-data
# → pool 3 'ec-data' ... erasure_profile ec-4-2 ...
```

#### 2.2 EC-пул для CephFS (с overwrites)

```bash
# Шаг 1: Создание пула данных
ceph osd pool create cephfs-data-ec 256 256 replicated

# Шаг 2: Применение EC-профиля
ceph osd pool set cephfs-data-ec erasure_code_profile cephfs-ec-profile

# Шаг 3: Включение overwrites (ОБЯЗАТЕЛЬНО для CephFS)
ceph osd pool set cephfs-data-ec allow_ec_overwrites true

# Шаг 4: Привязка к приложению
ceph osd pool application enable cephfs-data-ec cephfs

# Шаг 5: Создание CephFS с EC-пулом данных
ceph fs new mycephfs cephfs-metadata cephfs-data-ec
```

> **Важно:** `allow_ec_overwrites` необходим для CephFS, так как файловая система выполняет частичную запись (append, truncate) без перезаписи всего объекта.

#### 2.3 EC-пул для RBD

```bash
# Шаг 1: Создание пула
ceph osd pool create ec-vms 256 256 replicated

# Шаг 2: Применение EC-профиля
ceph osd pool set ec-vms erasure_code_profile ec-4-2

# Шаг 3: Включение overwrites (для быстрого resize)
ceph osd pool set ec-vms allow_ec_overwrites true

# Шаг 4: Привязка к приложению
ceph osd pool application enable ec-vms rbd
```

### 3. Управление профилями

```bash
# Список всех профилей
ceph osd erasure-code-profile ls

# Просмотр параметров профиля
ceph osd erasure-code-profile get ec-4-2

# Изменение профиля (только неиспользуемых!)
# Для изменения — создайте новый профиль и мигрируйте данные

# Удаление профиля (только если нет пулов, использующих его)
ceph osd erasure-code-profile rm ec-4-2
```

### 4. Миграция данных из replicated в EC-пул

Ceph не поддерживает in-place конверсию пула. Миграция выполняется через копирование:

```bash
# Шаг 1: Создать EC-пул
ceph osd pool create ec-data-new 256 256 replicated
ceph osd pool set ec-data-new erasure_code_profile ec-4-2

# Шаг 2: Копировать данные (radoscp для объектов, rbd export/import для образов)
# Для объектов:
rados -p replicated-data ls | while read obj; do
  rados -p replicated-data get "$obj" /tmp/obj-copy
  rados -p ec-data-new put "$obj" /tmp/obj-copy
  rm /tmp/obj-copy
done

# Для RBD-образов:
for img in $(rbd ls replicated-vms); do
  rbd export "replicated-vms/$img" /tmp/img-backup
  rbd import /tmp/img-backup "ec-vms/$img"
  rm /tmp/img-backup
done

# Шаг 3: Обновить конфигурацию приложений на новый пул
# Шаг 4: Удалить старый replicated-пул
ceph osd pool delete replicated-data replicated-data --yes-i-really-really-mean-it
```

### 5. Проверка и мониторинг EC-пулов

```bash
# Статус PG для EC-пула
ceph pg dump | grep ec-data

# Проверка использования пространства
ceph df | grep ec-data
ceph osd df tree  # → проверка балансировки

# Проверка профиля пула
ceph osd pool get ec-data erasure_code_profile
# → erasure_code_profile: ec-4-2

# Проверка allow_ec_overwrites
ceph osd pool get ec-data allow_ec_overwrites
# → allow_ec_overwrites: true

# Мониторинг recovery после потери OSD
ceph -w | grep -i "recovery\|backfill"
```

### 6. Диагностика проблем с EC

| Проблема | Симптом | Причина | Решение |
|----------|---------|---------|---------|
| `HEALTH_WARN: PG_DEGRADED` | EC-пуль деградирован | OSD down, fewer than k+m OSD доступно | Вернуть OSD в `in`, дождаться recovery |
| `HEALTH_ERR: PG_INCOMPLETE` | Данные недоступны | Потеряно > m OSD в failure domain | Восстановление из бэкапа |
| `EC_OVERWRITES_NOT_SUPPORTED` | CephFS не работает с EC | `allow_ec_overwrites` не включен | `ceph osd pool set <pool> allow_ec_overwrites true` |
| Неравномерное распределение | Некоторые OSD перегружены | pg_num не кратен k | Пересоздать пул с правильным pg_num |
| Медленное восстановление | Recovery длится часами | Недостаточно OSD, медленная сеть | Добавить OSD, проверить cluster_network |

---

## Дополнительная информация

### Когда какой профиль использовать

| Сценарий | Профиль | Примечание |
|----------|---------|------------|
| Архив, бэкапы | 4+2 или 8+4 | Максимальная экономия места |
| Медиа (видео, изображения) | 4+2 | Крупные объекты, sequential read |
| CephFS (общие файлы) | 4+2 + overwrites | POSIX-совместимость |
| RBD (ВМ, тестовые среды) | 4+2 + overwrites | Экономия для холодных данных |
| Базы данных (OLTP) | **Репликация** | Не использовать EC из-за latency |

### Ограничения

- **Минимум OSD:** k+m для записи, k+m+2 для comfortable recovery
- **Latency записи:** выше, чем у репликации (кодирование)
- **Recovery I/O:** выше (чтение k фрагментов для восстановления 1)
- **Partial writes:** требуют `allow_ec_overwrites` (CephFS/RBD)
- **Нет in-place конверсии:** миграция через копирование данных

### См. также

- [Обзор Ceph](./ceph_overview.md) — архитектура RADOS и CRUSH
- [Расчет PG](./ceph_placement_groups.md) — расчёт PG для EC-пулов
- [Администрирование Ceph](./Administration/index.md) — управление кластером
- [Операции Ceph](./Administration/operations.md) — создание пулов и профилей
