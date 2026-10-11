# Шардинг MySQL: эксплуатационные аспекты

**Актуально для:** MySQL 8.4 LTS (MySQL-специфика проверена по MySQL 8.4
Reference Manual; инструменты — по документации Vitess, Percona Toolkit и
gh-ost)

MySQL не имеет встроенной поддержки шардинга: в документации Vitess это
сформулировано прямо — MySQL не поддерживает шардинг нативно, поэтому код
шардинга и логику маршрутизации приходится писать самостоятельно. Это значит,
что шардинг в MySQL — не настройка сервера, а архитектурное решение с
эксплуатационными последствиями: DDL, бэкапы, миграции, генерация
идентификаторов и транзакции перестают быть операциями над одной базой.

Теория шардинга — методы распределения данных, архитектурные уровни, пороги
принятия решения, процедура решардинга — изложена в
**[Шардирование баз данных](../Concepts/sharding.md)**. Этот файл описывает
только то, что специфично для MySQL: какие инструменты умеют работать с
несколькими шардами, как в MySQL генерируются идентификаторы, и почему
внешние ключи не переживают шардинг.

## Определения

| Термин | Значение |
| :--- | :--- |
| Шард (shard) | Независимый экземпляр MySQL со своей копией части данных; обычно у шарда есть реплики |
| Шардирование | Разделение данных по нескольким серверам для горизонтального масштабирования записи |
| Шардинг-ключ (sharding key) | Атрибут, по которому строка выбирает свой шард; определяет равномерность распределения |
| Scatter-gather | Запрос, который отправляется на все шарды и собирается из ответов; цена — рост задержки с ростом числа шардов |
| Keyspace / Shard (Vitess) | Keyspace — логическая база данных; shard — её физический фрагмент с идентичной схемой |
| Vindex (Vitess) | Правило вычисления шардинг-ключа строки; основной (primary) vindex определяет маршрутизацию |
| Resharding (Vitess) | Процесс изменения схемы шардинга с копированием, проверкой и поддержанием актуальности данных на новых шардах |
| `auto_increment_increment` | Параметр сессии, управляющий шагом `AUTO_INCREMENT`; в шардированной схеме используется для разведения диапазонов идентификаторов |

## Предварительные требования

### Аппаратные требования

| Компонент | Минимум | Рекомендуется | Обоснование |
| :--- | :--- | :--- | :--- |
| **CPU** | 4 vCPU на шард | 8+ vCPU для OLTP, 16+ для аналитики | Параллелизм на уровне шарда |
| **RAM** | 8 ГБ на шард | 32–128 ГБ | buffer pool должен покрывать working set |
| **Диск (datadir)** | 500 ГБ SSD | NVMe, отдельный volume для redo/binlog | Минимизация IO wait при параллельной записи |
| **Сеть** | 1 Гбит/с | 10 Гбит/с+ (RoCE/InfiniBand) | Cross-shard операции чувствительны к latency |

### Сетевые порты

Шардированный кластер MySQL/Vitess требует открытых портов на всех узлах:

| Порт | Протокол | Сервис | Назначение |
| :--- | :--- | :--- | :--- |
| 3306 | TCP | MySQL | Client connections (через vtgate или напрямую) |
| 15991 | TCP | vtgate | MySQL protocol endpoint (приложение подключается сюда) |
| 16332–16344 | TCP | vttablet | gRPC / health check / query сервис |
| 22 | TCP | SSH | bastion доступ к нодам |
| 18152 | TCP | Prometheus | Экспорт метрик |

Настройка firewall (`ufw`):

```bash
# Открыть порты для внутренней сети шардов
ufw allow from 10.0.0.0/8 to any port 3306,15991,16332:16344,18152
# Bastion: только SSH
ufw allow 22/tcp
```

### ОС и зависимости

| Требование | Значение |
| :--- | :--- |
| **ОС** | Ubuntu 24.04 LTS / RHEL 9.x (kernel 5.14+) |
| **MySQL** | 8.4 LTS |
| **Vitess** | 24.0 (текущий stable на 2026-го) |
| **Topology** | etcd 3.5+ (рекомендуется) или ZooKeeper 3.8+ |
| **Monitoring** | Prometheus 3.x + Grafana 11.x |
| **NTP** | chrony — синхронизация времени между всеми узлами (< 10 мс отклонение) |
| **DNS** | Forward + reverse DNS для всех узлов кластера |

### SELinux / AppArmor

```bash
# Проверить статус
sestatus  # SELinux
aa-status  # AppArmor

# Если SELinux включён — добавить порты
semanage port -a -t mysqld_port_t -p tcp 15991
semanage port -a -t mysqld_port_t -p tcp 16332-16344
```

### Предварительная проверка

```bash
# 1. Проверить связность между узлами
nc -zv shard1-01.internal 3306
nc -zv shard1-01.internal 15991

# 2. Проверить версии
mysql --version  # → mysql  8.4.x
vtgate -version  # → 24.0.x

# 3. DNS
nslookup shard1-01.internal
nslookup 10.0.1.11  # reverse DNS
```

## Теоретический блок

### Почему в MySQL нет «нативного» шардинга

Ни в 5.7, ни в 8.0, ни в 8.4 документация MySQL не описывает механизма
шардинга, который распределял бы таблицу по нескольким серверам: ни
`shard_map`, ни `SHOW SHARDING HOSTS` в документации отсутствуют. Официальная
позиция экосистемы зафиксирована в документации Vitess: MySQL не имеет
нативной поддержки шардинга.

Отсюда следует ключевое операционное следствие: **шардинг в MySQL всегда
реализуется слоем сверху** — прокси (Vitess, собственный код) или логикой в
приложении. Инструменты, которые мы привыкли считать «умеющими в кластер»,
имеют чёткие ограничения (см. ниже).

Vitess — документированное решение этой задачи: open-source система
кластеризации баз данных для горизонтального масштабирования MySQL,
распределяющая данные по нескольким экземплярам MySQL через шардинг и
предоставляющая приложению единый интерфейс. Запросы работают так, будто
попадают в один сервер MySQL, но Vitess сам маршрутизирует их в нужные
шарды. Архитектурные элементы:

- **vtgate** — лёгкий прокси-сервер, который маршрутизирует трафик к нужным
  VTTablet-серверам и возвращает клиенту объединённый результат; понимает
  MySQL-протокол и gRPC-протокол Vitess;
- **VTTablet** — агент рядом с каждым экземпляром MySQL;
- **Topology Service** — etcd, ZooKeeper или Consul;
- **VSchema** — описание организации данных внутри keyspace и shard; для
  шардированных keyspace задаётся список vindex для каждой таблицы, а также
  генераторы последовательностей, работающие подобно `AUTO_INCREMENT`.

Keyspace бывает sharded или unsharded: unsharded отображается напрямую на одну
базу MySQL, sharded — строки разбиты по базам с идентичной схемой. Обычно
шард — это primary и его реплики, то есть шардинг ортогонален репликации:
репликация даёт отказоустойчивость внутри шарда, шардинг — масштабирование
записи между шардами.

### Выбор шардинг-ключа

Percona формулирует это прямо: выбор шардинг-ключа — самая важная часть
реализации шардинга. Правила, которые следуют из этого:

- **Ключ должен быть единицей, общей для группы связанных записей.** Если
  строки, которые всегда читаются вместе, попадут в разные шарды, каждая такая
  операция превращается в scatter-gather.
- **Недостаточная селективность** — данные разделятся неравномерно, часть
  шардов вырастет до объёма остальных вместе взятых.
- **Избыточная селективность** — логически связанные единицы распадутся по
  разным шардам (идентификатор отдельной записи форума вместо идентификатора
  пользователя).
- Следствие для проектирования: шардинг-ключ — это решение, которое
  фиксируется в схеме данных и в коде приложения; смена ключа после
  наполнения таблиц означает решардинг.

### Генерация идентификаторов в шардированной схеме

В MySQL параметры `auto_increment_increment` и `auto_increment_offset` имеют
область Global и Session, значение по умолчанию `1` и диапазон `1..65535`.
Документация прямо говорит, что они предназначены для использования с
циклической (source-to-source) репликацией и позволяют управлять поведением
колонок `AUTO_INCREMENT`.

Критическая для шардинга особенность, которую часто понимают неправильно:
значение, установленное на уровне сессии, влияет на **все** колонки
`AUTO_INCREMENT` во всех таблицах, куда эта сессия вставляет данные, в течение
сессии, если значения не меняются. Это значит:

- `SET SESSION auto_increment_increment = 64; SET SESSION auto_increment_offset = N;`
  разводит диапазоны идентификаторов между **сессиями**, а не между таблицами
  и не между шардами автоматически;
- в шардированной схеме каждая сессия записи должна получить свой
  `offset`, иначе на разных шардах будут генерироваться пересекающиеся
  диапазоны;
- для сессий, которые не пишут вообще, параметры не имеют значения; проблема
  возникает ровно там, где есть запись.

Альтернативный документированный механизм — последовательности Vitess,
описанные в VSchema и работающие подобно колонкам `AUTO_INCREMENT` MySQL.
Практический вывод: идентификаторы в шардированной схеме — отдельная задача
проектирования, а не следствие `AUTO_INCREMENT` по умолчанию.

### Что не работает «из коробки» на нескольких шардах

| Задача | Инструмент | Проверенный статус |
| :--- | :--- | :--- |
| DDL на одном шарде | `pt-online-schema-change` | Принимает ровно один DSN позиционным аргументом: `pt-online-schema-change [OPTIONS] DSN`. Списка DSN в `--alter` не существует — `--alter` принимает список ALTER-операций через запятую |
| Обход реплик при DDL | `pt-online-schema-change` | `--recursion-method` со значениями `processlist`, `hosts`, `dsn`, `none`; по умолчанию `processlist,hosts`. Значение `none` означает «не искать реплики» |
| DDL на нескольких независимых шардах | `gh-ost` | Флага мультихостового режима нет: полный перечень флагов и реестр флагов в исходном коде не содержат `--all-servers` или иного варианта для набора серверов. Модель gh-ost — один master и его реплики |
| Решардинг | официального инструмента MySQL нет | Документированный механизм — Resharding в Vitess: данные копируются, проверяются и поддерживаются в актуальном состоянии на новых шардах, пока существующие шарды продолжают обслуживать чтение и запись; заявленная недоступность записи — несколько секунд |
| Внешние ключи между шардами | нет | Ограничение FK проверяются InnoDB в пределах одного сервера; ссылка на строку другого шарда для InnoDB невозможна, а партиционированные таблицы InnoDB вообще не поддерживают FK |
| Транзакции, охватывающие шарды | нет | Транзакция существует в пределах одного сервера. Проблема и решения — в [Распределённые транзакции](../Concepts/distributed_transactions.md) |

Практический вывод: **кросс-шардовый DDL и решардинг нельзя закрыть
существующими инструментами по одному шарду**. Это работа для оркестратора
(внешнего планировщика с проверкой результата на каждом шарде) либо для
специализированной системы шардинга.

## Практический блок

### 1. Проверить, не упёрся ли инстанс в шардирование

Признаки, по которым шардирование обсуждают на конкретной базе, а не в
абстракции:

```sql
-- Объём данных
SELECT TABLE_NAME,
       TABLE_ROWS,
       ROUND(DATA_LENGTH / 1024 / 1024 / 1024, 1) AS data_gb,
       ROUND(INDEX_LENGTH / 1024 / 1024 / 1024, 1) AS index_gb
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'shop'
ORDER BY DATA_LENGTH + INDEX_LENGTH DESC
LIMIT 5;
```

```text
# → TABLE_NAME | TABLE_ROWS | data_gb | index_gb
# → events     | 8900000000 |   812.0 |    244.1
```

```sql
-- Пиковая запись: операций в секунду
SHOW GLOBAL STATUS LIKE 'Innodb_rows_read';
SHOW GLOBAL STATUS LIKE 'Innodb_rows_inserted';
```

```text
# → Variable_name         | Value
# → Innodb_rows_inserted  | 184529301
```

Пороговые значения и методы расчёта приведены в
**[Шардирование баз данных](../Concepts/sharding.md)** (раздел «Пороги для
принятия решения о шардинге»). Локальные узкие места проверяются раньше
шардинга — см.
**[Диагностика дисковых узких мест в базах данных](../db_disk_bottleneck_troubleshooting.md)**
и **[Индексация](./indexing.md)**.

### 2. Развести идентификаторы между шардами

Каждая сессия записи получает свой диапазон. При трёх шардах и шаге 3:

```sql
-- Сессия, пишущая на шард 1
SET SESSION auto_increment_offset = 1;
SET SESSION auto_increment_increment = 3;
INSERT INTO orders (customer_id, total) VALUES (17, 199.00);

-- Сессия, пишущая на шард 2
SET SESSION auto_increment_offset = 2;
SET SESSION auto_increment_increment = 3;

-- Сессия, пишущая на шард 3
SET SESSION auto_increment_offset = 3;
SET SESSION auto_increment_increment = 3;
```

```text
# → SELECT @@SESSION.auto_increment_increment, @@SESSION.auto_increment_offset;
# → auto_increment_increment | auto_increment_offset
# → 3                       | 1
```

Проверка результата: идентификаторы на разных шардах не должны
пересекаться.

```sql
SELECT id FROM orders WHERE customer_id = 17 ORDER BY id DESC LIMIT 5;
```

```text
# → id
# → 1207
```

Обязательное условие: параметры задаются **на каждое соединение**, а не
один раз. Обычное соединение без этих `SET SESSION` немедленно нарушает
схему — и, что хуже, нарушение не даёт ошибки.

### 3. DDL на каждом шарде: только оркестратор

Ни `pt-online-schema-change`, ни `gh-ost` не выполняют DDL на наборе
независимых шардов. Практический подход — внешний цикл с проверкой на каждом
шарде:

```bash
#!/usr/bin/env bash
# DDL на каждом шарде с валидацией результата
set -u
SHARDS=(shard1.internal:3306 shard2.internal:3306 shard3.internal:3306)

for shard in "${SHARDS[@]}"; do
  host=${shard%%:*}
  echo "==> ${host}"
  mysql -h "${host}" -u dba -p --batch --skip-column-names -e "
    ALTER TABLE orders
      ADD COLUMN paid_at DATETIME NULL,
      ALGORITHM=INPLACE, LOCK=NONE;" || {
      echo "ОШИБКА на ${host} — остановка"; exit 1
      }
  # Валидация: колонка есть и таблица доступна на запись
  col=$(mysql -h "${host}" -u dba -p --batch --skip-column-names -e "
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA='shop' AND TABLE_NAME='orders'
      AND COLUMN_NAME='paid_at';")
  [ "${col}" = "1" ] || { echo "Нет колонки на ${host}"; exit 1; }
done
echo "DDL применён на всех шардах"
```

Ключевые требования к такому оркестратору:

- **остановка на первом шарде, где операция не удалась** — иначе схемы
  разъедутся;
- **проверка результата на каждом шарде**, а не только код возврата;
- **повторяемость**: операция должна безопасно повторяться (идемпотентный
  `IF NOT EXISTS` или предварительная проверка) — иначе повтор после сбоя
  упадёт на части шардов;
- **окно на каждое ALTER**: на каждом шарде длится своё, суммарное окно
  складывается.

Схему `ALGORITHM`/`LOCK` и выбор инструмента под одну таблицу см. в
**[Онлайн-изменение схемы](./Operations/online-schema-change.md)**.

### 4. Решардинг

Официального инструмента решардинга в MySQL нет. Документированный механизм —
Resharding в Vitess: Vitess копирует, проверяет и поддерживает данные на новых
шардах в актуальном состоянии, пока существующие шарды продолжают обслуживать
живые запросы чтения и записи; заявленная недоступность записи — несколько
секунд.

Практические требования к решардингу, следующие из архитектуры MySQL:

1. **Сначала шардинг-ключ, потом шардирование.** Данные одного шарда должны
   переживать переезд без изменения идентификатора записи.
2. **Решардинг переносит данные, а не меняет модель данных.** Нельзя
   одновременно менять шардинг-ключ и добавлять FK — а FK и не переживут
   разбиения (см. следующий сценарий).
3. **Проверка согласованности до и после.** Для пары «источник — шард» до
   переезда сверяются контрольные суммы (см.
   **[Проверка согласованности репликации](./replication/consistency_checks.md)**).
4. **Бэкап всех шардов.** Решардинг затрагивает несколько инстансов; точка
   отката — покомпонентная, а не «один дамп».

### 5. Внешние ключи и шардирование

Ограничение FK проверяются InnoDB в пределах одного сервера. Отсюда два
следствия для шардированной схемы:

- **FK между шардами невозможны**: проверка целостности требует доступа к
  родительской строке, а она лежит на другом сервере. Ссылочная целостность
  между шардами обеспечивается на уровне приложения, и это отдельная
  ответственность кода.
- **FK и партиционирование внутри шарда несовместимы**: InnoDB не поддерживает
  внешние ключи для таблиц с определённым пользователем секционированием. То
  есть шард не может одновременно быть секционирован по дате и иметь внешние
  ключи — подробности в
  **[Внешние ключи (FOREIGN KEY) и ссылочная целостность](./foreign_keys.md)**.

Практический вывод: на этапе проектирования шардированной базы внешние ключи
либо не применяются вовсе, либо применяются только внутри одного шарда, и тогда
шард не партиционируется. Менять это после наполнения данных дорого.

### 6. Транзакции и согласованность между шардами

Транзакция в MySQL существует в пределах одного сервера. Операция, охватывающая
несколько шардов, требует внешнего протокола — компенсирующих транзакций либо
двухфазной фиксации; механизмы и компромиссы разобраны в
**[Распределённые транзакции](../Concepts/distributed_transactions.md)**,
теоретические аспекты — в **[CAP-теорема](../Concepts/cap_theorem.md)**.

Что должен учитывать эксплуататор шардированной базы:

- **шардинг-ключ определяет, какие операции остаются одношардовыми**, а
  scatter-gather постепенно становится нормой для отчётных запросов: с ростом
  числа шардов время ответа растёт линейно;
- **транзакция, задевающая два шарда, не является ACID-транзакцией** MySQL —
  это внешний протокол со своими правилами компенсации;
- **мониторинг шардов** — это мониторинг N независимых инстансов: лаг
  репликации внутри шарда (см.
  **[Мониторинг лага репликации](./replication/lag_monitoring.md)**) плюс
  контроль разброса данных между шардами, который в общей практике
  отслеживается на уровне метрик keyspace.

### 7. Что покрывают стандартные инструменты базы

Инструменты базы данных не знают о шардах, и их использование требует
пересчёта:

| Задача | Как выполняется в шардированной схеме |
| :--- | :--- |
| Физический бэкап | По одному на каждый шард; процедура и проверка — в [Резервное копирование и восстановление](./backup_and_recovery/overview.md) |
| Логический дамп | Отдельно на каждый шард; слияние дампов — задача оркестратора |
| PITR | Отдельно по бинарным логам каждого шарда; единая точка времени восстановления согласуется вручную |
| Восстановление шарда | Из состояния кластера (SST) либо из физического бэкапа шарда |
| Проверка согласованности | По парам «источник → шард», а не «весь датасет» |
| Маршрутизация запросов | Прокси или логика приложения; ProxySQL решает вопрос маршрутизации и отказоустойчивости, но не шардинга данных |

Практическая ошибка, которую чаще всего допускают: попытка «просто включить
решардинг» на существующей базе. Оба документированных подхода требуют
изменения схемы данных — добавления шардинг-ключа в VSchema или изменения
структуры хранения. Это задача проектирования, а не настройки.

## Мониторинг и наблюдаемость

Шардированная система требует мониторинга на трёх уровнях: MySQL внутри шарда,
Vitess (vtgate/vttablet) и приложение.

### Ключевые метрики Vitess

| Метрика | Источник | Алерт | Порог |
| :--- | :--- | :--- | :--- |
| **Vtgate QPS / latency** | `vtgate.info/QPS`, `vtgate.info/Latency` | P99 > 50 мс | < 20 мс |
| **Vtgate error rate** | `vtgate.info/ErrorCounters` | > 1% | < 0.1% |
| **Vtgate connection count** | `vtgate.info/ConnPool` | > 80% от `vtgate.conn_pool.size` | < 70% |
| **Vttablet health** | `vttablet.debug/Healthy` | ≠ 1 | — |
| **VReplication lag** | `vttablet.debug/Replication` | > 30 сек | < 5 сек |
| **Tablet throttler paused** | `vttablet.throttler/Paused` | > 0 | — |

### Ключевые метрики MySQL (на каждом шарде)

```sql
-- Репликация внутри шарда
SHOW SLAVE STATUS;
-- Seconds_Behind_Master: мониторить > 30 сек

-- Нагрузка на шард
SHOW GLOBAL STATUS LIKE 'Innodb_rows_inserted';
SHOW GLOBAL STATUS LIKE 'Threads_connected';
-- Threads_connected > 80% max_connections → алерт
```

### Мониторинг перекоса данных (data skew)

```sql
-- Размер таблицы на каждом шарде
SELECT
    @@hostname AS host,
    TABLE_NAME,
    ROUND(DATA_LENGTH / 1024 / 1024 / 1024, 1) AS data_gb
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'shop' AND TABLE_NAME = 'orders'
ORDER BY DATA_LENGTH DESC;

-- Распределение ключей по шардам через vtgate
SELECT
    SHARD('shop.customer:id') AS shard,
    COUNT(*) AS row_count
FROM orders
GROUP BY 1
ORDER BY 2 DESC;
```

### Метрики через Prometheus

```bash
# Vtgate metrics
curl -s http://vtgate-01:15100/debug/vars | jq '.vtgate'

# Vttablet health
curl -s http://vttablet-01:16100/debug/vars | jq '.TabletHealthCheck'

# MySQL exporter (per-shard)
curl -s http://shard1-01:9104/metrics | grep mysql_slave_status_seconds_behind_master
```

### Vtgate Tablet Throttler

Vitess 24.0 включает **tablet throttler** — автоматическая пауза трафика на
перегруженном шарде для предотвращения каскадных сбоев:

```bash
# Проверить статус
vtctldclient GetTabletThrottler --keyspace shop --shard -80

# Включить/отключить
vtctldclient UpdateThrottler --keyspace shop --enable
```

## Диагностика и устранение неисправностей

| Ошибка | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Hot shard** | Один шард загружен на 90%+, остальные простаивают | `top` на каждом шарде; QPS по шардам; `SELECT SHARD(...) ... GROUP BY` | Пересмотр ключа шардирования; вынос "горячего" tenant на выделенный шард |
| **Cross-shard JOIN медленный** | Запрос требует данных с нескольких шардов | `EXPLAIN` на vtgate; slow query log vtgate | Денормализация или реплицируемая справочная таблица на каждом шарде |
| **Vtgate: no healthy tablet** | Ни один tablet в keyspace/shard не здоров | `vtctldclient ListAllTablets --keyspace shop` | Восстановить недоступный tablet; проверить topology service |
| **Replica lag > 30сек** | Перегрузка репликации внутри шарда | `SHOW SLAVE STATUS` на каждом реплике | Добавить реплик; оптимизировать запись; включить throttler |
| **VReplication lag** | vreplication отстаёт от оригинала | `vtctldclient VDiff --keyspace shop --workflow ...` | Проверить `cell` маршрутизацию; увеличить `--cells` в workflow |
| **`errno 1236`: binlog position** | GTID inconsistency между шардами | `GTID_SUBSET` на каждом шарде; `SHOW MASTER STATUS` | Синхронизировать позиции; использовать `--reset` для репликации |

### Методы диагностики

#### Проверка статуса всех шардов

```bash
# Список всех tablet-ов в keyspace
vtctldclient ListAllTablets --keyspace shop

# Статус VSchema (что распределено как)
mysql -h vtgate -P 15991 -u root -e "
  SHOW VSCHEMA TABLES;
  SHOW VSCHEMA DISTRIBUTING;
"
```

#### Проверка VReplication lag

```bash
# Статус всех воркеров vreplication
vtctldclient VReplication --keyspace shop --all-tablets --show

# Или через MySQL протокол:
mysql -h vtgate -P 15991 -e "
  SELECT workflow, source, message, state
  FROM _vt.vreplication
  WHERE keyspace_id = 'shop'
  ORDER BY workflow;
"
```

#### Мониторинг cross-shard запросов

```bash
# Включить slow query log в vtgate
# В /etc/vitess/vtgate.yaml:
#   query_timeout: 30000  # 30 сек

# Или через SQL:
mysql -h vtgate -P 15991 -e "
  ALTER INSTANCE SET GLOBAL vtgate_query_timeout = '30s';
"
```

### Recovery procedures

#### Восстановление после потери primary шарда

```bash
# 1. Назначить новый primary через vtctld
vtctldclient ChangeTabletState \
  --keyspace shop --shard -80 \
  --tablet-type primary

# 2. Или через VTOrc (автоматический failover):
vtctldclient VTOrcApply --keyspace shop

# 3. Проверить
vtctldclient ListAllTablets --keyspace shop --filter TABLET_TYPE=PRIMARY
```

#### Восстановление после split-brain (resharding)

```bash
# 1. Проверить согласованность данных после resharding
vtctldclient VDiff \
  --keyspace shop \
  --source-shards -80,80- \
  --target-shards -40,40-80,80-c0,c0- \
  --compare-rules

# 2. Если есть расхождения — остановить workflow
vtctldclient StopReshard --keyspace shop --uuid <workflow_uuid>

# 3. Исправить и перезапустить
```

## Лучшие практики

### VSchema и шардинг-ключ

1. **Primary Vindex определяет распределение.** Выбор vindex критичен:
   хеш-ключ (`hash`) для равномерного распределения, диапазонный (`range`) для
   последовательных ключей, lookup для FK-подобного маршрута.
2. **Не используйте `auto_increment` для PK в шардированных таблицах.**
   Используйте Vitess sequences или внешний генератор ID.
3. **Согласуйте VSchema со схемой данных.** VSchema должен быть загружен
   до первой записи:

```bash
vtctldclient ApplyVschema --keyspace shop --vschema-file ./vschema.json

# Проверить:
mysql -h vtgate -P 15991 -e "SHOW VSCHEMA DISTRIBUTING;"
```

### Идентификаторы и Vitess sequences

Vitess предоставляет sequences — безопасная замена `auto_increment`:

```sql
-- 1. Создать таблицу-генератор последовательностей
CREATE TABLE order_seq (
  next_id BIGINT AUTO_INCREMENT,
  PRIMARY KEY (next_id)
) ENGINE=InnoDB;

-- 2. Использовать в INSERT
INSERT INTO orders (id, customer_id, total)
  VALUES (NEXT_VALUE(order_seq.next_id), 17, 199.00);
```

### Управление DDL

1. **Используйте `vtctldclient ApplySchema`** вместо прямого `ALTER TABLE` —
   Vitess рассылает DDL на все шарды атомарно.
2. **`ALGORITHM=INPLACE, LOCK=NONE`** для индексов и колонок.
3. **Тестируйте на одном шарде** перед массовым применением.
4. **Избегайте `DROP TABLE`** в процессе resharding.

### Бэкап и DR

1. **Бэкапируйте каждый шард независимо** через `xtrabackup` на vttablet.
2. **Синхронность snapshots**: если нужен согласованный момент времени —
   остановите запись на всех шардах, создайте бэкапы, возобновите.
3. **Тестируйте restore** минимум раз в квартал на всех шардах.

### Security

1. **TLS между vtgate и MySQL** — настройте в vttablet конфиге.
2. **Network isolation** — каждый шард в отдельном VLAN; доступ только
   с vtgate/bastion.
3. **Минимальные привилегии** — приложение подключается через vtgate,
   не напрямую к MySQL.

## Операционные процедуры

### Resharding в Vitess (MoveTables)

Vitess 24.0 поддерживает online resharding через MoveTables workflow:

```bash
# 1. Обновить VSchema для целевых шардов
vtctldclient ApplyVSchema --keyspace shop - <<'EOF'
{
  "sharded": true,
  "vindexes": {
    "hash": "hash"
  },
  "tables": {
    "orders": {
      "column_vindex": [
        {
          "column": "customer_id",
          "name": "hash"
        }
      ]
    }
  }
}
EOF

# 2. Создать workflow resharding (источник: 2 шарда → цель: 4 шарда)
vtctldclient Reshard --keyspace shop \
  --source-shards -80,80- \
  --target-shards -40,40-80,80-c0,c0- \
  --workflow resharding_2026

# 3. Запустить и дождаться синхронизации
vtctldclient StartReshard --keyspace shop --workflow resharding_2026
vtctldclient VDiff --keyspace shop --workflow resharding_2026 --limit 10
vtctldclient ShowReshard --keyspace shop --workflow resharding_2026

# 4. Cutover — несколько секунд read-only downtime
vtctldclient CutOverReshard --keyspace shop --workflow resharding_2026

# 5. Очистка
vtctldclient CancelReshard --keyspace shop --workflow resharding_2026
vtctldclient DeleteKeyspace --keyspace shop --tables
```

### Добавление нового шарда

```bash
# 1. Создать tablet для нового шарда
vtctldclient AddTablets --keyspace shop --shard c0- \
  --tablet-hostname new-shard-01.internal:15257 \
  --tablet-type replica

# 2. Применить VSchema с новым диапазоном
vtctldclient ApplyVSchema --keyspace shop --vschema-file updated_vschema.json
```

### Rolling restart shard'а

```bash
# 1. Drain трафик через throttler
vtctldclient TabletThrottlerEnable --keyspace shop --shard -80

# 2. Перезапустить vttablet
systemctl restart vttablet

# 3. Проверить health
vtctldclient ListAllTablets --keyspace shop --shard -80
```

## Граничные случаи

### Сетевой разрыв между vtgate и шардами

При потере связи vtgate с отдельным шардом:
- **CP-подход**: cross-shard запросы завершаются ошибкой;
- **AP-подход**: vtgate обслуживает доступные шарды, cross-shard — с ошибкой.

**Митигация**: Cell-based Architecture, retry с backoff на уровне приложения.

### Версионный дисбаланс

При добавлении нового шарда с новой версией MySQL:
- Physical репликация может отказать из-за несовместимости формата binlog.
- **Правило:** версия нового шарда ≥ версии существующих, не более чем на 1 minor.

### Большие транзакции

```sql
-- Мониторинг long-running транзакций (>60 сек)
SELECT trx_id, trx_started, trx_mysql_thread_id, trx_query
FROM INFORMATION_SCHEMA.INNODB_TRX
WHERE trx_started < NOW() - INTERVAL 60 SECOND;
```

> **Рекомендация:** разбивайте транзакции на пачки ≤ 1000 строк. Vitess
> оптимизирует batch INSERT через vtgate.

### Один выживший шард после катастрофы

1. Не используйте оставшийся шард как authoritative source без проверки.
2. Восстанавливайте из бэкапа, а не с другого шарда.
3. Включите read-only режим на оставшемся шарде.

## Дополнительная информация

### См. также

- **[Шардирование баз данных](../Concepts/sharding.md)** — методы
  распределения данных, архитектурные уровни, пороги, процедура решардинга,
  мониторинг перекоса данных.
- **[Распределённые транзакции](../Concepts/distributed_transactions.md)** —
  2PC и Saga для операций между узлами.
- **[CAP-теорема](../Concepts/cap_theorem.md)** — почему шардинг влияет на
  согласованность.
- **[Внешние ключи (FOREIGN KEY) и ссылочная целостность](./foreign_keys.md)** —
  почему FK не переживают шардинг и секционирование.
- **[Онлайн-изменение схемы](./Operations/online-schema-change.md)** — выбор
  инструмента для одного шарда; ограничения инструментов на наборе шардов.
- **[ProxySQL: обзор](./ProxySQL/proxysql_overview.md)** — маршрутизация,
  отказоустойчивость и ограничения прокси-подхода.
- **[Высокая доступность MySQL](./high_availability.md)** — репликация внутри
  шарда.

### Официальная документация

- [Vitess — What is Vitess](https://vitess.io/docs/24.0/overview/whatisvitess) — MySQL не имеет нативного шардинга; архитектура
- [Vitess — VTGate](https://vitess.io/docs/24.0/concepts/vtgate) и [VSchema](https://vitess.io/docs/24.0/concepts/vschema) — маршрутизация, vindex, последовательности
- [Vitess — Sharding](https://vitess.io/docs/24.0/reference/features/sharding) — keyspace, shard, Resharding
- [auto_increment_increment / auto_increment_offset](https://docs.oracle.com/cd/E17952_01/mysql-8.4-en/replication-options-source.html) — область, значения, семантика для `AUTO_INCREMENT`
- [Percona Toolkit: pt-online-schema-change](https://docs.percona.com/percona-toolkit/pt-online-schema-change.html) — один DSN, `--alter`, `--recursion-method`
- [gh-ost: Command Line Flags](https://github.com/github/gh-ost/blob/master/doc/command-line-flags.md) и [Requirements and Limitations](https://github.com/github/gh-ost/blob/master/doc/requirements-and-limitations.md) — модель master + реплики
- [Horizontal Scaling in MySQL: Sharding Followup](https://www.percona.com/blog/horizontal-scaling-in-mysql-sharding-followup/) — выбор шардинг-ключа