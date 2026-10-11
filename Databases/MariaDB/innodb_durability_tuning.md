# InnoDB: долговечность и настройка записи

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

> [!warning] MariaDB и MySQL 8 diverged в этой области
> В MySQL 8.0.30+ / 8.4 параметры `innodb_log_file_size` и `innodb_log_files_in_group` заменены на `innodb_redo_log_capacity`, а `innodb_flush_log_at_trx_commit` не имеет значения `3`. В MariaDB `innodb_redo_log_capacity` **не существует**, `innodb_log_files_in_group` **не существует**, а значение `3` у `innodb_flush_log_at_trx_commit` — штатное. Конфигурация, перенесённая из MySQL 8, в MariaDB неверна.

## Определения

| Термин | Значение |
|---|---|
| **Redo log (WAL)** | Физический журнал InnoDB, обеспечивающий атомарность и долговечность. В MariaDB это единственный файл `ib_logfile0` кругового формата |
| **Log buffer** | Буфер в памяти, куда пишутся redo-записи перед сбросом в файл. Размер — `innodb_log_buffer_size` |
| **LSN (Log Sequence Number)** | Монотонный номер позиции в redo log. Checkpoint продвигает LSN, до которого изменения гарантированно попали в таблицы |
| **Checkpoint** | Процесс применения redo к страницам таблиц и продвижения checkpoint LSN. Запускается, когда redo log заполняется, и при достижении `innodb_max_dirty_pages_pct` грязных страниц |
| **Dirty page** | Страница в buffer pool, изменённая в памяти, но ещё не записанная в файл таблицы |
| **Doublewrite buffer** | Буфер (128 страниц) для защиты от torn page при сбросе страниц на диск |
| **Undo log** | Журнал отката изменений, необходимый для MVCC, откатов транзакций и crash recovery |
| **Page flushing** | Фоновый процесс записи грязных страниц из buffer pool в файлы таблиц |
| **Adaptive flushing** | Динамическое регулирование скорости page flushing, чтобы сглаживать всплески I/O |
| **Binlog group commit** | Группировка коммитов для совместного fsync binlog; см. [transactions_and_locking.md](./transactions_and_locking.md) |
| **Torn page** | Страница, записанная лишь частично из-за сбоя питания или ошибки контроллера |

## Основные концепции

### Путь от `COMMIT` до диска

Долговечность транзакции в InnoDB обеспечивается двумя независимыми механизмами, и важно понимать, что они включаются в разные моменты:

1. **WAL-путь (долговечность коммита).** Изменения попадают в log buffer и в грязные страницы buffer pool. При `COMMIT` redo-записи сбрасываются в `ib_logfile0` согласно `innodb_flush_log_at_trx_commit`. Именно этот шаг определяет, переживёт ли подтверждённый коммит сбой питания.
2. **Checkpoint-путь (перенос изменений в таблицы).** Грязные страницы независимо от коммитов сбрасываются в файлы таблиц фоновым процессом, а redo-применение двигает checkpoint LSN. Это путь, который «догоняет» WAL, а не тот, который создаёт гарантию.

Отсюда следует практический вывод: **спад производительности после `COMMIT` — это работа второго пути (page flushing), а не первого.** Если fsync на коммит дорог, страдает только первый путь.

Отдельный слой — **долговечность binlog**, задаваемая `sync_binlog`. Если binlog включён,redo log и binlog должны быть согласованы, иначе PITR и репликация разъезжаются с таблицами.

### Три слоя долговечности и их значения по умолчанию

| Слой | Параметр | Что контролирует | Default MariaDB |
|---|---|---|---|
| Сброс при коммите | `innodb_flush_log_at_trx_commit` | Окно потери подтверждённых коммитов при сбое ОС или питания | `1` |
| Период фонового сброса | `innodb_flush_log_at_timeout` | Интервал фоновой записи и сброса redo log, если flush не произошёл на коммите | `1` (диапазон `0`…`2700`) |
| Долговечность binlog | `sync_binlog` | Сколько событий binlog накопить перед сбросом на диск | **`0`** |
| Скорость переноса в таблицы | `innodb_io_capacity`, `innodb_io_capacity_max`, `innodb_max_dirty_pages_pct` | Нагрузка на I/O и лаг сброса грязных страниц | `200`, `2000` (или `2 × innodb_io_capacity`), `90.000000` |

Значения `innodb_flush_log_at_trx_commit` (Scope: Global, Dynamic: Yes, Data Type: enumeration):

| Значение | Поведение | Последствие сбоя |
|---|---|---|
| `0` | На коммите ничего не делается; log buffer пишется и сбрасывается раз в секунду | Авария процесса стирает до секунды транзакций |
| `1` | Log buffer сбрасывается на диск после каждой транзакции | Полное соответствие ACID; значение по умолчанию |
| `2` | Log buffer пишется в файл после каждого коммита, сброс — раз в `innodb_flush_log_at_timeout` секунд | Сбой ОС или питания может потерять последнюю секунду транзакций |
| `3` | Log buffer пишется и сбрасывается на диск **на обеих фазах — prepare и commit** | Как при `1`: подтверждённые коммиты не теряются. Медленнее `1`, лишний flush на prepare обычно избыточен |

> [!danger] `sync_binlog` по умолчанию в MariaDB равен `0`
> MySQL 8 по умолчанию использует `sync_binlog=1`. В MariaDB default — `0`, то есть сброс binlog передаётся операционной системе. Любой инстанс MariaDB с включённым binlog, полагающийся на дефолт, теряет события при сбое питания и не может обеспечить PITR. Для репликации и PITR `sync_binlog=1` нужно задавать явно.
>
> Отдельно: `binlog_error_action` (MySQL-параметр, определяющий поведение при ошибке записи binlog) в MariaDB **не существует**.

### Почему в MariaDB нет `innodb_redo_log_capacity`

MariaDB применяет подход с фиксированным размером файла redo log:

- `innodb_log_file_size` — размер каждого файла redo log в группе, по умолчанию `100663296` (96 МБ), диапазон от 4 МБ до 512 ГБ, **динамический с MariaDB 10.9** (в 10.8 и старше требует перезапуска).
- `innodb_log_group_home_dir` — путь к файлам; если не задан, создаётся единственный `ib_logfile0` в каталоге данных.
- `innodb_log_files_in_group`, как в MySQL, **отсутствует** — файл один.

Размер redo log и объём лога — не одно и то же. Чем больше `innodb_log_file_size`, тем реже срабатывает checkpoint и тем меньше I/O на фоне flush, но тем дольше crash recovery. Документация отмечает, что recovery не расходует память, поэтому увеличение размера безопасно и может осмысленно превышать `innodb_buffer_pool_size`.

Общая теория WAL и различие физического (redo) и логического (binlog) уровней разобраны в [write_ahead_log.md](../Concepts/write_ahead_log.md).

### Механизм page flushing

Checkpoint наступает, когда redo log заполняется, а адаптивное сбрасывание включается, когда достигнут нижний порог заполнения:

- `innodb_adaptive_flushing` (default `ON`, Dynamic: Yes) — сервер динамически регулирует скорость сброса грязных страниц, сглаживая всплески I/O. При `OFF` сброс происходит только при достижении `innodb_adaptive_flushing_lwm`.
- `innodb_adaptive_flushing_lwm` (default `10.000000`, диапазон `0`…`70`) — процент от объёма redo log, при достижении которого адаптивное сбрасывание включается. Действует даже при `innodb_adaptive_flushing=OFF`.
- `innodb_max_dirty_pages_pct` (default `90.000000`, диапазон `0`…`99.999`) — верхний предел доли грязных страниц в buffer pool, при котором форсируется сброс.
- `innodb_io_capacity` (default `200`, диапазон `100`…`4294967295`) — лимит I/O для фоновых задач, включая слияние change buffer и сброс страниц. Значение стоит выбирать по реальной производительности диска, а не по номиналу: завышенное значение вытесняет данные из буферов быстрее, чем нужно, снижая эффект кэширования.
- `innodb_io_capacity_max` (default `2000` или удвоенный `innodb_io_capacity`, что выше) — верхняя граница, до которой `innodb_io_capacity` временно расширяется в аварийных ситуациях.
- `innodb_flush_sync` (default `ON`) — при `ON` значение `innodb_io_capacity` игнорируется для всплесков I/O на чекпоинтах, то есть чекпоинт всегда получает полную полосу.
- `innodb_flush_neighbors` (default `1`, значения `0`, `1`, `2`) — сбрасывать ли соседние грязные страницы того же экстента. Переменная **игнорируется для табличных пространств, распознанных как размещённых на SSD** — для них применяется поведение `0`.

Размер buffer pool и его планирование вынесены в [configuration.md](./configuration.md). Здесь важна только граница, о которой редко пишут: `innodb_buffer_pool_size_max` — параметр только для чтения (Dynamic: No), задающий потолок `innodb_buffer_pool_size`.

> [!warning] Потолок buffer pool и версии
> До MariaDB 10.11.17, 11.4.11, 11.8.7 и 12.3.2 `innodb_buffer_pool_size_max` по умолчанию равнялся начальному `innodb_buffer_pool_size`, то есть `SET GLOBAL innodb_buffer_pool_size` **не мог увеличить** buffer pool, пока потолок не задан явно при старте (MDEV-38671). Начиная с этих релизов default — 8 ТиБ зарезервированного виртуального адресного пространства на 64-битных системах, кроме IBM AIX, и увеличение на лету работает без настройки. Сам параметр появился в MariaDB 10.11.12, 11.4.6 и 11.8.2.
>
> Дополнительно: автоматическое увеличение buffer pool не реализовано (MDEV-36197) — потолок обслуживает только ручной ресайз. Если задан `RLIMIT_AS`, default автоматически снижается до четверти лимита; на архитектурах ARM64, RISC-V, MIPS и LoongArch неудачная резервация повторяется с 128 ГиБ, а на остальных архитектурах это ошибка старта, требующая явного `innodb_buffer_pool_size_max`.

### Doublewrite

По умолчанию `innodb_doublewrite=ON` (Global). Данные сначала записываются в doublewrite buffer и только затем в файл таблицы — это защита от torn page. Буфер имеет фиксированный размер **128 страниц**; при нормальной работе `innodb_io_capacity` больше 128, то есть между батчами doublewrite буфер переиспользуется.

Версионная деталь: начиная с MariaDB 11.0.6 параметр стал **динамическим** (Dynamic: Yes) и получил третье значение:

| Значение | Когда доступно | Поведение |
|---|---|---|
| `ON` | Все версии | Запись через doublewrite buffer с синхронизацией. Default |
| `OFF` | Все версии | Отключает doublewrite. Даёт небольшой прирост и предполагает, что записи размером `innodb_page_size` атомарны |
| `fast` | С MariaDB 11.0.6 | Как `ON`, но записи **не синхронизируются** с файлами данных |

`fast` дополнительно всегда вызывает `os_file_flush()` для самого doublewrite buffer, что безопаснее при нескольких батчах между чекпоинтами. Условие безопасности: **doublewrite buffer (первый файл системного табличного пространства) и файлы данных должны находиться в одной файловой системе.**

> [!warning] Устаревшее взаимодействие с `innodb_flush_method`
> Deprecated стартовый параметр `innodb_flush_method=NO_FSYNC` приводит к тому, что `innodb_doublewrite=ON` превращается в `innodb_doublewrite=fast`, то есть InnoDB перестаёт делать устойчивые записи в файлы данных. Это делается непосредственно перед обновлением LSN чекпоинта, и в зависимости от файловой системы это может быть как безопасно, так и нет.

### Undo tablespaces

| Параметр | Значение |
|---|---|
| `innodb_undo_tablespaces` | Default `3` с MariaDB 11.0, `0` в 10.11. Диапазон: `0` или `2`…`95`. **Dynamic: No** |
| `innodb_undo_directory` | Default `NULL` — отдельные tablespace создаются в каталоге `datadir`. Путь относительный или абсолютный |
| `innodb_undo_log_truncate` | Default `OFF`. Помечает для усечения tablespace, превышающие `innodb_max_undo_log_size` |
| `innodb_max_undo_log_size` | Default `10485760` (10 МБ) |

Значение `0` означает, что все undo logs находятся в системном табличном пространстве. Значение `1` сбрасывается в `0`, так как для отдельных tablespace нужно `2` или больше. Размер одного undo tablespace по умолчанию — 10 МБ. До MariaDB 10.11.1 параметр необходимо задать **до инициализации InnoDB**, иначе сервер не стартует с ошибкой `InnoDB did not find the expected number of undo tablespaces`. С MariaDB 11.0 несколько undo tablespaces включены по умолчанию, чтобы освобождать место после всплесков undo log через `innodb_undo_log_truncate`.

Включение `innodb_undo_log_truncate` может вызывать задержки при тяжёлой записи — усечение блокирует работу при активной purge-активности.

### Режимы остановки `innodb_fast_shutdown`

Global, Dynamic: Yes, default `1`, диапазон `0`…`3`:

| Значение | Поведение |
|---|---|
| `0` | Медленная остановка: полный purge и слияние change buffer. В крайних случаях занимает часы |
| `1` | Default: быстрая остановка без полного purge и слияния change buffer |
| `2` | Redo log сбрасывается, выполняется «холодная» остановка, аналогичная крашу. Последующий старт делает crash recovery. Крайне быстро, но **рискует повреждением данных. Не подходит для обновления между мажорными версиями** |
| `3` | Активные транзакции не откатываются, но все изменённые страницы пишутся в файлы данных; откат выполняется фоновым потоком при следующем старте. Не задействует применение redo log при старте |

Остановка со значением `2` должна рассматриваться как аварийная мера. В штатном цикле `apt upgrade` / перезапуска в меньшую сторону используется `1`.

## Практические сценарии

### 1. Базовая конфигурация долговечности для production

Ориентир для одиночного инстанса без binlog:

```ini
[mariadb]
# WAL: полное соответствие ACID
innodb_flush_log_at_trx_commit      = 1
innodb_log_file_size                = 1G
innodb_log_buffer_size              = 64M

# Сброс грязных страниц
innodb_io_capacity                  = 2000
innodb_io_capacity_max              = 4000
innodb_max_dirty_pages_pct          = 60
innodb_flush_neighbors              = 0

# Целостность страниц
innodb_doublewrite                  = ON
```

Для MariaDB 11.0+ предпочтительнее управлять поведением сброса четырьмя булевыми параметрами вместо `innodb_flush_method` (см. следующий сценарий).

```bash
mariadb -e "SHOW VARIABLES WHERE Variable_name IN
  ('innodb_flush_log_at_trx_commit','innodb_log_file_size','innodb_log_buffer_size',
   'innodb_io_capacity','innodb_max_dirty_pages_pct','innodb_doublewrite');"
# → Variable_name                     | Value
# → innodb_doublewrite                 | ON
# → innodb_flush_log_at_trx_commit     | 1
# → innodb_io_capacity                 | 2000
# → innodb_log_buffer_size             | 67108864
# → innodb_log_file_size               | 1073741824
# → innodb_max_dirty_pages_pct         | 60.000000
```

### 2. Изменение размера redo log

С MariaDB 10.9 ресайз выполняется на лету:

```sql
SET GLOBAL innodb_log_file_size = 2147483648;
```

```bash
mariadb -e "SHOW VARIABLES LIKE 'innodb_log_file_size';"
# → Variable_name | Value
# → innodb_log_file_size | 2147483648
```

Ограничения, которые нужно учитывать до выполнения:

- Значение меньше `innodb_log_buffer_size` будет **отклонено**. Исключение — случай, когда лог расположен в файловой системе постоянной памяти (PMEM).
- Ресайз можно прервать, убив соединение, выполняющее `SET GLOBAL`.
- Суммарный размер лог-группы не может превышать 512 ГБ.
- В 10.8 и старше переменная не динамическая: требуется перезапуск, а файлы redo в 10.8+ нельзя удалять вручную для ресайза.

```bash
mariadb -e "SHOW WARNINGS;"
# → (пусто — SET GLOBAL принят)
```

Применять ресайз стоит в период низкой нагрузки: операция пересоздаёт лог и приостанавливает контрольную запись.

### 3. Переход с `innodb_flush_method` на четыре параметра

`innodb_flush_method` объявлен **deprecated с MariaDB 11.0**, остаётся доступным и не является динамическим. Управление поведением сброса передано четырём булевым динамическим параметрам:

| Параметр | Default | Introduced | Назначение |
|---|---|---|---|
| `innodb_log_file_buffering` | `OFF` | 10.8.4, 10.9.2 | Кэш файловой системы для `ib_logfile0` |
| `innodb_data_file_buffering` | `OFF` | 11.0.0 | Кэш файловой системы для файлов данных |
| `innodb_log_file_write_through` | `OFF` | 11.0.0 | Write-through для записи в лог |
| `innodb_data_file_write_through` | `OFF` | 11.0.0 | Write-through для записи в файлы данных |

Значения `innodb_flush_method` транслируются в них автоматически:

- `O_DSYNC` → `innodb_log_file_write_through=ON`, `innodb_data_file_write_through=ON`, `innodb_data_file_buffering=OFF` и, если поддерживается, `innodb_log_file_buffering=OFF`.
- `fsync`, `littlesync`, `nosync`, а также `normal` на Windows → все write-through выключены, `innodb_data_file_buffering=ON`.

Допустимые значения `innodb_flush_method` (Scope: Global, Dynamic: **No**): Unix — `fsync`, `O_DSYNC`, `littlesync`, `nosync`, `O_DIRECT`, `O_DIRECT_NO_FSYNC`; Windows — `unbuffered`, `async_unbuffered`, `normal`. Default — `O_DIRECT` на Unix с MariaDB 10.6.0.

```ini
[mariadb]
# Вместо innodb_flush_method = O_DIRECT
innodb_log_file_buffering            = OFF
innodb_data_file_buffering           = OFF
innodb_log_file_write_through        = OFF
innodb_data_file_write_through       = OFF
```

```bash
mariadb -e "SHOW VARIABLES WHERE Variable_name LIKE 'innodb%_buffering' OR Variable_name LIKE 'innodb%_write_through';"
# → Variable_name                  | Value
# → innodb_data_file_buffering     | OFF
# → innodb_data_file_write_through | OFF
# → innodb_log_file_buffering      | OFF
# → innodb_log_file_write_through  | OFF
```

> [!warning] `SET GLOBAL` для этих параметров может быть молча проигнорирован
> Изменение вступает в силу, только когда InnoDB держит открытым **один** лог-файл, что выполняется большую часть времени. Запрос игнорируется, пока идёт ресайз `innodb_log_file_size` кругового лога `ib_logfile0`. Настройка также не действует, когда лог отображён в постоянную память (PMEM). Поскольку запрос можно пропустить без ошибки, результат нужно проверять чтением значения обратно.
>
> ```sql
> SET GLOBAL innodb_log_file_buffering = ON;
> SELECT @@GLOBAL.innodb_log_file_buffering;
> ```
> Та же оговорка относится к `innodb_log_file_write_through` и `innodb_data_file_write_through`.

Параметр `innodb_log_file_buffering` (default `OFF`) связан с `innodb_flush_log_at_trx_commit=2`: запись в лог через кэш файловой системы обычно повышает пропускную способность на медленных накопителях и при малом числе одновременных транзакций. Если сервер стартует с `innodb_flush_log_at_trx_commit=2`, значение выставляется в `ON`; при установке `innodb_flush_method=O_DSYNC` — в `OFF`. На Linux, если размер физического блока не является степенью двойки в диапазоне 64…4096 байт, кэш файловой системы отключить нельзя и изменить параметр невозможно. На Linux и Windows с MariaDB 10.8.3 кэш файловой системы для redo log по умолчанию отключён.

### 4. Настройка page flushing под SSD и NVMe

Для твердотельных накопителей с малым временем seek:

- `innodb_flush_neighbors = 0` — прямой эффект отключения есть только на магнитных дисках. Документация отмечает, что статус SSD определяется под Windows и Linux, а для табличных пространств на SSD переменная **игнорируется** и применяется поведение `0`.
- `innodb_io_capacity` подбирается по фактической производительности: для NVMe это обычно тысячи IOPS, для SATA SSD — сотни. Завышенное значение снижает эффективность кэширования, поэтому при известных пиках допустимо стартовать с большим значением и снижать его для штатной работы.
- `innodb_max_dirty_pages_pct` ниже default `90` сокращает лаг сброса ценой более частых чекпоинтов. Значение `60` — разумный компромисс для SSD, для больших баз данных часто оставляют `90` ради снижения объёма flush.

### 5. Undo tablespaces на отдельном устройстве

Перенос undo на отдельное устройство уменьшает конкуренцию за I/O с таблицами:

```ini
[mariadb]
innodb_undo_tablespaces = 6
innodb_undo_directory   = /mnt/fastssd/mariadb/undo
innodb_undo_log_truncate = ON
innodb_max_undo_log_size = 10737418240
```

```bash
mariadb -e "SHOW VARIABLES WHERE Variable_name LIKE 'innodb_undo%' OR Variable_name LIKE 'innodb_max_undo%';"
# → Variable_name              | Value
# → innodb_max_undo_log_size   | 10737418240
# → innodb_undo_directory      | /mnt/fastssd/mariadb/undo
# → innodb_undo_log_truncate   | ON
# → innodb_undo_tablespaces    | 6
```

Параметры `innodb_undo_tablespaces` и `innodb_undo_directory` имеют **Dynamic: No** — изменение требует перезапуска. Увеличение числа tablespace расширяет доступный объём undo и упрощает возврат места после всплесков нагрузки, когда включён `innodb_undo_log_truncate`.

### 6. Диагностика состояния записи

```bash
mariadb -e "SHOW ENGINE INNODB STATUS\G" | sed -n '/FILE I\/O/,/^---/p'
# → ---
# → FILE I/O:
# →   The MySQL InnoDB engine is continuing to run ...
```

```bash
mariadb -e "SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_pages%';"
# → Variable_name                    | Value
# → Innodb_buffer_pool_pages_data    | 419430
# → Innodb_buffer_pool_pages_dirty   | 1203
# → Innodb_buffer_pool_pages_free    | 12288
# → Innodb_buffer_pool_pages_misc    | 5229
# → Innodb_buffer_pool_pages_total   | 439150
```

```sql
SELECT name, count
FROM information_schema.INNODB_METRICS
WHERE name LIKE 'log_pending%' AND enabled = 1;
-- → Активные метрики ожидания сброса лога: ненулевое значение означает,
--   что фоновый сброс не успевает за записью
```

```bash
mariadb -e "SHOW ENGINE INNODB STATUS\G" | sed -n '/LATEST DETECTED DATABASE TIME/,/^---/p'
mariadb -e "SHOW GLOBAL STATUS LIKE 'Innodb_rollback_on_timeout';"
```

Для наблюдения за фактическим сбросом используйте `SHOW ENGINE INNODB STATUS` (секция `FILE I/O`), состояние `Innodb_buffer_pool_pages_dirty` и метрики `information_schema.INNODB_METRICS` с фильтром по имени.

## Диагностика и устранение неисправностей

### `SET GLOBAL innodb_buffer_pool_size` не увеличивает buffer pool

Симптом: значение не изменилось, в журнале ошибок — `Warning 1292`.

Причина: значение упёрлось в `innodb_buffer_pool_size_max`, который только для чтения и по умолчанию равен начальному размеру buffer pool в версиях до 10.11.17, 11.4.11, 11.8.7 и 12.3.2.

```sql
SELECT @@GLOBAL.innodb_buffer_pool_size, @@GLOBAL.innodb_buffer_pool_size_max;
```

Решение: задать `innodb_buffer_pool_size_max` при старте либо обновиться до релиза, где default потолка — 8 ТиБ. Помните, что автоматического роста нет: потолок обслуживает только ручной ресайз.

### `SET GLOBAL innodb_log_file_size` отклонён

Симптом: ошибка вида `ERROR 1231 (42000): Variable 'innodb_log_file_size' can't be set to the value of ...`, размер не изменился.

Причины: новое значение меньше `innodb_log_buffer_size`, превышен суммарный лимит 512 ГБ, либо идёт конкурентная операция с лог-файлом.

```sql
SHOW VARIABLES WHERE Variable_name IN
  ('innodb_log_file_size','innodb_log_buffer_size','innodb_log_files_in_group');
```

Решение: уменьшить целевой размер ниже `innodb_log_buffer_size` или, наоборот, сначала увеличить буфер; выполнять ресайз в окно низкой нагрузки. Отсутствие `innodb_log_files_in_group` в выводе — норма для MariaDB, файл лога один.

### Всплески fsync и медленный `COMMIT` при `innodb_flush_log_at_trx_commit=1`

Наиболее частая причина медленных коммитов при корректной настройке долговечности — не `innodb_flush_log_at_trx_commit`, а перегруженное устройство: fsync на коммит конкурирует с фоновым page flushing.

```bash
mariadb -e "SHOW VARIABLES WHERE Variable_name IN ('innodb_flush_sync','innodb_io_capacity','innodb_io_capacity_max','innodb_adaptive_flushing');"
```

Решение по порядку: проверить фактическую IOPS и выставить `innodb_io_capacity` по нему; проверить состояние `Innodb_buffer_pool_pages_dirty` относительно `innodb_max_dirty_pages_pct`; оценить, не исчерпан ли ресурс под журналом (`ib_logfile0` на отдельном устройстве от redo и от данных); только после этого рассматривать ослабление гарантий до `2`. Если сброс лога отстаёт, полезно увеличить `innodb_flush_log_at_timeout`, чтобы уменьшить влияние на commit group — документация прямо называет это приёмом для снижения влияния на производительность binlog group commit.

### Длинные паузы при включённом `innodb_undo_log_truncate`

Симптом: периодические остановки при тяжёлой записи, `SHOW ENGINE INNODB STATUS` показывает активный purge.

Причина: усечение undo tablespace блокируется активной purge-активностью.

Решение: увеличить `innodb_max_undo_log_size`, чтобы усечения происходили реже, либо оставить `innodb_undo_log_truncate=OFF` в часы пиковой записи.

### Повреждение данных после аварийной остановки

Симптом: после `shutdown` со значением `innodb_fast_shutdown=2` последующий старт выполняет crash recovery, при определённых условиях — с повреждениями.

Решение: не использовать `2` в штатных процедурах. Документация прямо указывает, что этот режим не подходит для обновления между мажорными версиями. Если режим уже использован, см. [backup_and_recovery.md](./backup_and_recovery.md).

### Ошибка `InnoDB did not find the expected number of undo tablespaces`

Симптом: сервер не стартует, ошибка упоминает ожидаемое число undo tablespaces.

Причина: в версиях до MariaDB 10.11.1 `innodb_undo_tablespaces` необходимо задать до инициализации InnoDB. Уменьшение значения без соответствующего состояния datadir приводит к расхождению.

Решение: вернуть `innodb_undo_tablespaces` к предыдущему значению, либо указать фактическое число файлов `undoN` в каталоге данных.

### `innodb_doublewrite=fast` и устойчивость данных

Симптом: `innodb_flush_method` выставлен в deprecated-значение, а в выводе `innodb_doublewrite` вместо ожидаемого `ON` наблюдается `fast`.

Причина: `innodb_flush_method=NO_FSYNC` приводит к автоматической смене `innodb_doublewrite=ON` на `fast`, то есть InnoDB перестаёт делать устойчивые записи в файлы данных.

Решение: убрать `NO_FSYNC`, вернуть явное `innodb_doublewrite=ON`. Значение `fast` оставлять только при осознанном решении и при условии, что doublewrite buffer и файлы данных в одной файловой системе.

## Лучшие практики

- **Не ослабляйте `innodb_flush_log_at_trx_commit` ради скорости на боевой базе.** Значения `0` и `2` допустимы для загрузки данных на новый инстанс и для тестового стенда. Если `2` выбран осознанно, фиксировать приемлемый RPO явно.
- **Всегда задавайте `sync_binlog=1` при включённом binlog.** Default `0` в MariaDB не обеспечивает ни PITR, ни согласованности с репликами. См. [binary-logging.md](./security/binary-logging.md).
- **Размер redo log задайте с запасом и до старта системы.** Документация отмечает, что crash recovery не расходует память, поэтому увеличенный `innodb_log_file_size` безопасен; экономия на нём проявляется как постоянный I/O от flush.
- **Подбирайте `innodb_io_capacity` по факту, а не по паспорту диска.** Завышенное значение вытесняет данные из буферов быстрее, чем это полезно.
- **Проверяйте фактический результат `SET GLOBAL` для буферов и write-through.** Эти запросы могут быть молча проигнорированы; всегда читайте значение обратно.
- **На SSD полагайтесь на определение диска, а не на `innodb_flush_neighbors`.** Переменная игнорируется для табличных пространств на SSD.
- **Держите `innodb_doublewrite=ON`, если doublewrite buffer и данные в разных файловых системах.** Условие безопасности `fast` — их совпадение.
- **Задавайте `innodb_undo_tablespaces` и `innodb_undo_directory` до старта.** Оба параметра не динамические; ошибка числа tablespace останавливает сервер.
- **Планируйте место под временный лог онлайн-DDL.** `innodb_online_alter_log_max_size` (default `134217728`, Dynamic: Yes) ограничивает временный лог; при превышении операция онлайн-DDL завершается ошибкой, а все незакоммиченные изменения откатываются.
- **Используйте `innodb_fast_shutdown=1` как стандартный режим остановки.** Значения `2` и `3` — для аварийных сценариев, и `2` категорически не для обновления между мажорными версиями.

## Дополнительная информация

### Документация MariaDB

- [InnoDB System Variables](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-system-variables) — полный перечень переменных с default, range и версионными маркерами
- [InnoDB Redo Log](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-redo-log)
- [InnoDB Flush Method](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-flush-method)
- [Storage I/O: Buffering and Persistence](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/storage-io-buffering-and-persistence)
- [InnoDB Page Flushing](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/innodb-page-flushing)
- [Replication and Binary Log System Variables](https://mariadb.com/docs/server/ha-and-performance/standard-replication/replication-and-binary-log-system-variables) — `sync_binlog` и двоичный лог
- [Binary log group commit and innodb_flushing performance](https://mariadb.com/docs/server/server-usage/storage-engines/innodb/binary-log-group-commit-and-innodb-flushing-performance)

### Смежные документы базы знаний

- [Транзакции и блокировки](./transactions_and_locking.md) — isolation, таймауты блокировок, диагностика через Performance Schema
- [Конфигурация](./configuration.md) — планирование buffer pool и памяти сервера
- [Хранилища и движки](./storage_engines.md) — выбор движка, file-per-table
- [Backup and recovery](./backup_and_recovery.md) — PITR, binlog, восстановление
- [Двоичный лог](./security/binary-logging.md) — `sync_binlog`, GTID, очистка логов
- [Мониторинг](./monitoring.md) — метрики и сбор показателей
- [WAL](../Concepts/write_ahead_log.md) — общая теория журнала предзаписи
- [ACID](../Concepts/acid.md) — свойства транзакций и уровни изоляции
- [Долговечность транзакций в MySQL](../MySQL/transactions_and_durability.md) — commit groups, матрица долговечности, двухфазная фиксация между redo и binlog

### Примечание об источниках

- `innodb_buffer_pool_size_max`, `innodb_log_file_size`, `innodb_flush_log_at_trx_commit`, `innodb_flush_method`, четыре булевых параметра сброса, `innodb_io_capacity`, `innodb_io_capacity_max`, `innodb_max_dirty_pages_pct`, `innodb_adaptive_flushing`, `innodb_adaptive_flushing_lwm`, `innodb_flush_sync`, `innodb_flush_neighbors`, `innodb_doublewrite`, `innodb_undo_tablespaces`, `innodb_undo_directory`, `innodb_undo_log_truncate`, `innodb_max_undo_log_size`, `innodb_log_buffer_size`, `innodb_log_group_home_dir`, `innodb_fast_shutdown`, `innodb_online_alter_log_max_size` — InnoDB System Variables.
- `sync_binlog` (default `0`), отсутствие `binlog_error_action` — Replication and Binary Log System Variables и страницы отличий MariaDB от MySQL.
- Отсутствие `innodb_redo_log_capacity` и `innodb_log_files_in_group` подтверждено полным перечнем InnoDB System Variables.