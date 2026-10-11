# Percona XtraDB Cluster (PXC): синхронная репликация для MySQL

**Актуально для:** Percona XtraDB Cluster 8.4 (проверено по документации Percona XtraDB Cluster 8.4)

PXC — это Percona Server for MySQL с подключённой библиотекой Galera
(протокол репликации на основе write-set от Codership). Каждый узел кластера
полноценен: он принимает запись, применяет изменения, отправленные соседями, и
хранит одинаковые данные. Отличие от классической асинхронной репликации MySQL
в том, что узлы согласуют порядок применения изменений через кворум, поэтому
вторичный узел никогда не отстаёт по-настоящему — он либо синхронизирован, либо
выбывает.

PXC 8.4 — актуальная ветка; ветки PXC 8.0 и 5.7 объявлены устаревшими (EOL).
Ветка 8.4 следует за MySQL 8.4 LTS.

Теория кластерных архитектур, механизм конфликтов multi-master, QDevice и
failover для Galera в MariaDB разобраны в
**[Отказоустойчивость MariaDB](../MariaDB/high_availability.md)** — здесь только
специфика PXC как дистрибутива для MySQL и эксплуатационные детали, которых
нет в файле про MariaDB.

## Предварительные требования

### Аппаратные требования

| Компонент | Минимальный | Рекомендуемый |
| :--- | :--- | :--- |
| **CPU** | 4 ядра | 8+ ядер (Galera — CPU-bound на сертификацию) |
| **RAM** | 8 ГБ | 32+ ГБ (`innodb_buffer_pool_size` ≈ 70% RAM) |
| **Диск** | SSD, 100 ГБ | NVMe, отдельный volume для datadir, binlog и tmpdir |
| **Сеть** | 1 Гбит/с | 10 Гбит/с между узлами (latency < 1 мс для commit) |

> **Критично:** PXC требует низкой сетевой задержки между узлами. Вольтфлекс (высокая latency) приводит к росту `wsrep_local_recv_queue` и flow control.

### Сетевые порты

Все порты должны быть открыты между узлами кластера и между кластером и ProxySQL:

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| **3306** | TCP | MySQL клиентские соединения |
| **4444** | TCP | SST (xtrabackup-v2) — передача снимка состояния |
| **4567** | TCP | Galera group communication (certification, app buffer) |
| **4568** | TCP | IST (Incremental State Transfer) — порт = 4567 + 1 по умолчанию |

Проверка открытых портов:

```bash
# На каждом узле — проверка доступности портов кластера
for port in 3306 4444 4567 4568; do
  ss -tlnp | grep ":$port" && echo "Port $port is listening" || echo "Port $port is NOT listening"
done

# Межхостовая проверка
nc -zv 10.0.1.12 4567
# → Connection to 10.0.1.12 4567 port [tcp/*] succeeded!
```

Настройка firewall (iptables пример):

```bash
# Открыть порты для подсети кластера
iptables -A INPUT -p tcp -s 10.0.1.0/24 --dport 3306  -j ACCEPT
iptables -A INPUT -p tcp -s 10.0.1.0/24 --dport 4444  -j ACCEPT
iptables -A INPUT -p tcp -s 10.0.1.0/24 --dport 4567  -j ACCEPT
iptables -A INPUT -p tcp -s 10.0.1.0/24 --dport 4568  -j ACCEPT
```

### Программные требования

- **Percona XtraDB Cluster 8.4.x** — актуальная LTS-ветка; ветки 8.0 и 5.7 EOL.
- **Percona XtraBackup 8.4.x** — версия должна совпадать с PXC (major.minor).
- **Chrony или NTP** — синхронизация времени (дрейф < 100 мс).
- **SELinux / AppArmor** — настроены на разрешение доступа mysqld к datadir и log-файлам.

SELinux (RHEL/CentOS):

```bash
# Проверить статус
sestatus
# → SELinux status: enabled

# Разрешить типичные контексты для PXC
semanage port -a -t mysqld_port_t -p tcp 4567
semanage port -a -t mysqld_port_t -p tcp 4568
semanage port -a -t mysqld_port_t -p tcp 4444
setsebool -P mysql_connect_any 1
```

AppArmor (Debian/Ubuntu):

```bash
# Проверить профиль
aa-status | grep mysql

# Добавить пути в профиль, если datadir нестандартный
echo "  /u01/mysql/ r," >> /etc/apparmor.d/local/usr.sbin.mysqld
echo "  /u01/mysql/** rwk," >> /etc/apparmor.d/local/usr.sbin.mysqld
systemctl reload apparmor
```

### Предварительная проверка конфигурации

Перед запуском кластера проверьте конфиг:

```bash
mysqld --validate-config --user=mysql
# → (пустой вывод — конфиг валиден)

# Проверить, что binlog_format = ROW (обязательно для PXC)
mysqld --verbose --help 2>/dev/null | grep binlog_format
# → binlog_format                           | row
```

## Определения

| Термин | Значение |
| :--- | :--- |
| Galera / wsrep | Библиотека и набор переменных `wsrep_*`, реализующие репликацию на основе write-set |
| `wsrep_*` | Системные переменные, настраивающие участие узла в Galera: адрес кластера, имя кластера, метод SST, режим применения |
| SST (State Snapshot Transfer) | Механизм передачи полного состояния от донору присоединяющемуся узлу |
| Донор (Donor) | Узел, отдающий своё состояние присоединяющемуся узлу |
| Кворум | Требуемое число доступных узлов, при котором кластер сохраняет работоспособность |
| `wsrep_OSU_method` | Способ выполнения DDL в кластере: TOI, RSU или NBO |
| `pxc_strict_mode` | Режим проверки неподдерживаемых и экспериментальных возможностей |
| `pxc_encrypt_cluster_traffic` | Автоматическая настройка шифрования между узлами кластера |
| `proxysql-admin` | Утилита PXC для автоматической настройки ProxySQL (один writer + hostgroups Galera) |

## Теоретический блок

### Что даёт кластер и какие ограничения накладывает

Репликация в PXC работает **только для InnoDB**. Записи в таблицы других
движков не реплицируются.

Ограничения, которые важнее архитектурных преимуществ:

- **XA-транзакции не поддерживаются** — из-за возможного отката на фазе
  фиксации.
- **`LOCK TABLES` и `UNLOCK TABLES` не поддерживаются в multi-source
  конфигурациях.**
- **Функции блокировок `GET_LOCK()` и `RELEASE_LOCK()` не поддерживаются.**
- **Журнал запросов не может направляться в таблицу** — требуется
  `log_output = FILE`.
- **Размер транзакции ограничен** параметрами `wsrep_max_ws_rows` и
  `wsrep_max_ws_size`. `LOAD DATA INFILE` фиксирует транзакцию каждые
  10 000 строк.
- **У каждой таблицы должен быть первичный ключ.** `DELETE` по таблице без
  первичного ключа не поддерживается. При `pxc_strict_mode` в режимах
  `ENFORCING` или `MASTER` параметр `sql_require_primary_key` устанавливается в
  `ON`.
- **Минимальная рекомендуемая конфигурация — три узла.** Третий узел может
  работать в роли арбитра.

Практический вывод: PXC — это кластер для InnoDB-приложения с первичными
ключами на всех таблицах. Если в приложении есть `LOCK TABLES`, XA или
`GET_LOCK()`, вариант не подходит без переработки.

### Состояния узла

Состояние узла видно в `wsrep_local_state` и его описание в
`wsrep_local_state_comment`:

| Значение `wsrep_local_state` | Комментарий | Смысл |
| :--- | :--- | :--- |
| `1` | Joining | Узел присоединяется к кластеру |
| `2` | Donor/Desynced | Узел выступает донором для присоединяющегося узла либо десинхронизирован |
| `3` | Joined | Узел присоединился к кластеру |
| `4` | Synced | Узел синхронизирован с кластером |

Состояние кластера видно в `wsrep_cluster_status`. Документированные значения:
`Primary` (кластер работоспособен и имеет кворум), `Non-Primary`
(кворум потерян, кластер не принимает изменения), `Disconnected` (нет связи с
кластером).

Правило эксплуатации: запись возможна только на узлах в состоянии `Synced`
при `wsrep_cluster_status = Primary`. Узел `Donor/Desynced` принимает
`SELECT`, но не должен получать запись — это диагностическая ошибка
конфигурации или процедуры обслуживания.

### Кворум и split brain

Кворум в Galera определяется алгоритмом Dynamic Linear Voting (DLV): кворум
сохраняется, если сумма весов узлов в новой компоненте строго превышает половину
предыдущей Primary-компоненты за вычетом узлов, покинувших кластер штатно.

PXC **не разрешает split brain автоматически**; минимальная рекомендация — три
узла. Если кластер разделён и каждая половина сохранила кворум (например, в
сети с несимметричным разделением), обслуживание входящего трафика можно
разрешить принудительно:

```ini
[mysqld]
# Разрешить узлу принимать трафик при split brain — с большой осторожностью
wsrep_provider_options="pc.ignore_sb=yes"
```

Это сознательный обход защиты: две расходящиеся группы будут принимать
конфликтующую запись, и слияние данных потребует ручного разрешения
конфликтов. В штатной эксплуатации параметр не применяют — его используют как
временную меру при плановом разделении сети.

### Метод выполнения DDL в кластере (wsrep_OSU_method)

| Метод | Поведение |
| :--- | :--- |
| TOI (Total Order Isolation) | Метод по умолчанию. Блокирует остальные транзакции, пока DDL выполняется на всех узлах в одном порядке репликации |
| RSU (Rolling Schema Upgrade) | Десинхронизирует узел, кластер не блокируется. Операция ручная, узел возвращается в `Synced` после применения |
| NBO (Non-Blocking Operation) | Появился в PXC 8.0.25+. Более эффективная стратегия блокирования, чем TOI. Поддерживает `ALTER TABLE`, `ALTER INDEX`, `CREATE INDEX`, `DROP INDEX`. Не поддерживает конфликтующие DDL по одной таблице; `lock_wait_timeout` следует задавать низким, поскольку его значение по умолчанию может приводить к практически бесконечному ожиданию |

Выбор метода — решение уровня эксплуатации: TOI проще и предсказуемее, NBO
меньше блокирует кластер, но требует проверки совместимости операции и
настроенного короткого `lock_wait_timeout`.

### SST: как присоединить или заменить узел

Поддерживаемые методы `wsrep_sst_method`:

| Метод | Статус |
| :--- | :--- |
| `xtrabackup-v2` | Метод по умолчанию и рекомендуемый. Использует backup locks; провайдер Galera продолжает работать без паузы |
| `clone` | Появился в PXC 8.4.4-4. Использует нативный механизм clone из MySQL, быстрее и экономнее по ресурсам |
| `rsync` | Legacy |
| `mysqldump` | Legacy |

Процесс SST использует порт `4444` для передачи данных между узлами.

### Прочие переменные PXC

- **`pxc_strict_mode`** — по умолчанию `ENFORCING` (и `DISABLED`, когда узел
  работает сам по себе или находится в стадии bootstrap). Допустимые значения:
  `DISABLED`, `PERMISSIVE`, `ENFORCING`, `MASTER`. В режимах `ENFORCING` и
  `MASTER` включается `sql_require_primary_key`.
- **`pxc_encrypt_cluster_traffic`** — по умолчанию `ON` в PXC 8.4: шифрование
  между узлами настраивается автоматически.
- **`wsrep_sync_wait`** — по умолчанию `0`; область Session и Global, динамическая.
  Управляет проверками причинно-следственной связи кластера для отдельных
  операторов.
- **`wsrep_applier_threads`** — по умолчанию `1`; количество потоков применения.
  Увеличение повышает пропускную способность применения.
- **`binlog_format`** — в PXC 8.4 значение, отличное от `ROW`, недопустимо ни при
  старте, ни в рантайме, независимо от `pxc_strict_mode`.
- **`proxysql-admin`** — входит в поставку PXC и умеет автоматически настраивать
  ProxySQL: режим одного writer и Galera-hostgroups.

Ограничения по платформам и режимам, влияющие на фактическую отдачу от
настроек Galera (из документации): кластерные механизмы недоступны при
установленном thread pool plugin; на macOS отсутствует API привязки потоков к
CPU; на FreeBSD и Solaris приоритеты игнорируются с предупреждением
`Attribute thread_priority is ignored (using default value)`.

## Практический блок

### 1. Проверить состояние узла и кластера

```sql
SHOW GLOBAL STATUS WHERE Variable_name IN
  ('wsrep_cluster_status', 'wsrep_cluster_size',
   'wsrep_local_state', 'wsrep_local_state_comment',
   'wsrep_ready', 'wsrep_connected');
```

```text
# → Variable_name             | Value
# → wsrep_cluster_status      | Primary
# → wsrep_cluster_size        | 3
# → wsrep_local_state         | 4
# → wsrep_local_state_comment | Synced
# → wsrep_ready               | ON
# → wsrep_connected           | ON
```

Это первая команда при любом инциденте: `Non-Primary` означает потерю кворума и
невозможность записи на всех узлах сразу, а не «реплику отстаёт, подождём».

Полный набор переменных узла:

```sql
SELECT VARIABLE_NAME, VARIABLE_VALUE
FROM performance_schema.global_variables
WHERE VARIABLE_NAME LIKE 'wsrep\_%'
ORDER BY VARIABLE_NAME;
```

```text
# → VARIABLE_NAME                  | VARIABLE_VALUE
# → wsrep_cluster_address           | gcomm://10.0.1.11,10.0.1.12,10.0.1.13
# → wsrep_cluster_name              | shop-cluster
# → wsrep_cluster_size              | 3
# → wsrep_local_state_comment       | Synced
# → wsrep_node_name                 | pxc-node-1
# → wsrep_on                        | ON
# → wsrep_sst_method                | xtrabackup-v2
```

### 2. Развёртывание кластера из трёх узлов

Адрес кластера перечисляет **все** узлы, включая текущий:

```ini
[mysqld]
# Идентификация узла — уникальное имя в пределах кластера
wsrep_node_name=pxc-node-1

# Имя кластера — одинаковое на всех узлах
wsrep_cluster_name=shop-cluster

# Список всех узлов кластера
wsrep_cluster_address=gcomm://10.0.1.11,10.0.1.12,10.0.1.13

# Метод передачи состояния присоединяющемуся узлу
wsrep_sst_method=xtrabackup-v2

# TLS между узлами — по умолчанию ON в 8.4, фиксируем явно
pxc_encrypt_cluster_traffic=ON

# Гарантия наличия первичных ключей
pxc_strict_mode=ENFORCING

server_id=11
```

```bash
sudo -u mysql mysqld --validate-config
# → (пустой вывод при отсутствии ошибок)
```

Первый узел кластера поднимается в режиме bootstrap — сервис запускается
отдельным юнитом:

```bash
sudo systemctl start mysql@bootstrap.service
sudo systemctl status mysql@bootstrap.service
# → Active: active (running)
```

После успешного bootstrap этот узел живёт обычной службой:

```bash
sudo systemctl enable --now mysql
```

Порядок в кластере из трёх узлов:

1. Поднять первый узел через `mysql@bootstrap.service`.
2. Поднять второй и третий обычной службой — они присоединятся по адресу
   кластера, состояние получат через SST.
3. Проверить на каждом узле `wsrep_cluster_status = Primary`,
   `wsrep_local_state_comment = Synced`, `wsrep_cluster_size = 3`.

Ошибка при join — самая частая при развёртывании. Проверяйте по порядку:
свободен ли порт `4444`, разрешён ли `pc.ignore_sb` в состоянии узла, совпадают ли
`wsrep_cluster_name` и `wsrep_cluster_address` на всех узлах, одинаковы ли
`wsrep_sst_method` и параметры TLS.

### 3. Замена упавшего узла

```bash
# На вышедшем узле: остановить службу, очистить состояние кластера
sudo systemctl stop mysql
sudo systemctl reset-failed mysql

# Сохранить адрес узла перед переустановкой — он участвует в wsrep_cluster_address
grep wsrep /etc/mysql/percona-server.cnf
```

Порядок восстановления:

1. Поднять узел с тем же `wsrep_node_name` и тем же составом
   `wsrep_cluster_address`.
2. Узел присоединится и получит состояние через SST (порт `4444`).
3. Проверить `wsrep_local_state_comment = Synced` и
   `wsrep_cluster_size = 3`.

Полное восстановление узла из физического бэкапа — отдельная процедура;
заготовки по физическим бэкапам, PITR и их проверке находятся в
**[Резервное копирование и восстановление](./backup_and_recovery/overview.md)**.

### 4. DDL в кластере: нельзя «просто ALTER»

```sql
-- Проверить метод выполнения DDL до операции
SHOW VARIABLES LIKE 'wsrep_OSU_method';
# → wsrep_OSU_method | TOI
```

```sql
-- DDL выполняется на всех узлах в одном порядке репликации
ALTER TABLE orders ADD COLUMN paid_at DATETIME NULL;
```

Для NBO-метода задайте разумный таймаут ожидания блокировки заранее:

```ini
[mysqld]
# При wsrep_OSU_method=NBO значение по умолчанию может приводить
# к практически бесконечному ожиданию
lock_wait_timeout=5
```

Сценарий Rolling Schema Upgrade (RSU) применяется, когда блокировка кластера
недопустима: узел десинхронизируется, DDL выполняется на нём отдельно, после
применения узел возвращается в синхронное состояние и догоняет изменения.

Важно: таблицы с внешними ключами нельзя мигрировать через `gh-ost` (см.
**[Внешние ключи (FOREIGN KEY) и ссылочная целостность](./foreign_keys.md)**).
В кластере, где DDL выполняется на всех узлах сразу, вопрос выбора инструмента
обычно снимается: используется `wsrep_OSU_method`.

### 5. Мониторинг и алерты

Обязательные метрики — состояние кластера, состояние узла и готовность:

```sql
SHOW GLOBAL STATUS WHERE Variable_name IN
  ('wsrep_cluster_status', 'wsrep_ready', 'wsrep_local_state_comment',
   'wsrep_cluster_size', 'wsrep_local_recv_queue_avg');
```

```text
# → Variable_name              | Value
# → wsrep_cluster_status       | Primary
# → wsrep_ready                | ON
# → wsrep_local_state_comment  | Synced
# → wsrep_cluster_size         | 3
# → wsrep_local_recv_queue_avg    | 0
```

Значения, требующие реакции:

| Метрика | Состояние | Действие |
| :--- | :--- | :--- |
| `wsrep_cluster_status` | `Non-Primary` | Запись недоступна на всех узлах. Искать потерю кворума: упавший узел или сетевой разрыв |
| `wsrep_cluster_status` | `Disconnected` | Узел изолирован от кластера |
| `wsrep_ready` | `OFF` | Узел не готов принимать трафик |
| `wsrep_local_state_comment` | `Donor/Desynced` | Узел не принимает запись: либо донор, либо десинхронизирован намеренно |
| `wsrep_cluster_size` | меньше ожидаемого | Кластер деградировал; проверить состояние остальных узлов |
| `wsrep_local_recv_queue_avg` | растёт | Применение изменений не успевает за сетью: сеть медленнее кластера. Порог реакции — > 1.0 при длительности более 60 секунд |

Методы мониторинга и алертинга — в
**[Мониторинг MySQL](./monitoring.md)**; правила hostgroups для Galera в
ProxySQL — в **[ProxySQL: Failover](./ProxySQL/proxysql_failover.md)**.

### 6. Интеграция с ProxySQL

PXC поставляет `proxysql-admin` — утилиту, которая конфигурирует ProxySQL под
кластер: режим одного writer и Galera-hostgroups, что соответствует схеме
`mysql_galera_hostgroups`, описанной в
**[ProxySQL: Failover](./ProxySQL/proxysql_failover.md)**.

Проверка после настройки:

```sql
-- В admin-интерфейсе ProxySQL
SELECT hostgroup_id, hostname, port, status, max_wsrep_lag
FROM mysql_galera_hostgroups;
```

```text
# → hostgroup_id | hostname      | port | status | max_wsrep_lag
# → 10           | pxc-node-1    | 3306 |        |               |
# → 11           | pxc-node-2    | 3306 |        |               |
# → 11           | pxc-node-3    | 3306 |        |               |
```

### 7. Проверка после изменений

Проверять состояние нужно на каждом узле отдельно — внешний SQL-запрос к
кластеру не может показать состояние соседей и вводит в заблуждение:

```sql
-- Выполнять на каждом узле
SHOW GLOBAL STATUS WHERE Variable_name IN
  ('wsrep_cluster_status', 'wsrep_cluster_size',
   'wsrep_local_state_comment', 'wsrep_ready');
```

```text
# → Variable_name             | Value
# → wsrep_cluster_status      | Primary
# → wsrep_cluster_size        | 3
# → wsrep_local_state_comment | Synced
# → wsrep_ready               | ON
```

Дополнительно после обслуживания:

- сверить `wsrep_cluster_size` с ожидаемым числом узлов;
- убедиться, что `wsrep_sst_method` одинаков на всех узлах (применяется при
  присоединении, но расхождение приведёт к отказу нового узла);
- проверить, что `binlog_format = ROW` во всех конфигурациях кластера —
  в 8.4 другое значение недопустимо.

## Диагностика и устранение неисправностей

### Типичные ошибки и решения

| Ошибка | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **SST fail: Connection refused на порт 4444** | Donor или firewall блокирует порт 4444 | `nmap -p 4444 donor_ip`, проверить `wsrep_sst_donor` | Открыть порт 4444 между узлами; указать явный `wsrep_sst_donor` |
| **SST fail: `xtrabackup: [ERROR] unknown variable`** | Конфликт опций в `my.cnf` | Добавить `--no-defaults` к xtrabackup в `wsrep_sst_auth` | Проверить секции `[mysqld]` на orphaned переменные |
| **Node stuck в `Joining`, не переходит в `Synced`** | Мismatch `wsrep_cluster_name` или `wsrep_cluster_address` | `SHOW STATUS LIKE 'wsrep_local_state_comment'` | Убедиться, что все узлы используют одинаковые `wsrep_cluster_name` и `wsrep_cluster_address` |
| **`wsrep_cluster_status = Non-Primary`** | Потеря кворума (split-brain защита) | `SHOW STATUS LIKE 'wsrep_cluster_status'` | Восстановить кворум: поднять минимум floor(N/2)+1 узлов; либо `pc.bootstrap=yes` на одном узле (с осторожностью) |
| **`wsrep_cluster_status = Disconnected`** | Узел изолирован от кластера (сеть/сертификация) | `ping donor_ip`, проверить `gmcast.listen_addr` | Проверить сеть между узлами, firewall, `bind-address` |
| **`wsrep_ready = OFF`** | Узел не готов принимать трафик | `SHOW STATUS LIKE 'wsrep_ready'` | Подождать завершения SST/IST, проверить лог ошибок |
| **`Donor/Desynced` при записи** | Узел донорит или десинхронизирован | `SHOW STATUS LIKE 'wsrep_local_state_comment'` | Не направлять запись на donor — проверить конфигурацию ProxySQL/VIP |
| **`wsrep_local_recv_queue_avg > 1.0`** | Flow control: сеть медленнее применения | `SHOW STATUS LIKE 'wsrep_local_recv_queue_avg'` | Проверить сеть (bandwidth, latency), увеличить `wsrep_flow_control_limit` |
| **Certification failure / `wsrep_conflicts_total` растёт** | Конфликты записи на разных узлах | `SHOW STATUS LIKE 'wsrep_conflicts_total'`, `wsrep_conflict_status` | Проанализировать конфликты: `wsrep_last_committed`, `wsrep_last_conflict` |
| **`FLUSH LOGS` не ротирует error log** | MySQL 8.x: `FLUSH LOGS` ротирует все логи, но error log ротируется только через перезапуск или logrotate | Проверить, что `log_error` указывает на файл, а не `stderr` | Использовать logrotate с `postrotate: mysqladmin flush-logs` |
| **`ERROR 3185 (Can't start server: Bad InnoDB`) при bootstrap** | Повреждение `grastate.dat` или `gvwstate.dat` | Проверить `/var/lib/mysql/grastate.dat`. Перезагрузка кластера с `pc.bootstrap` | Остановить все узлы, восстановить `grastate.dat` из бэкапа, bootstrap с `--wsrep-new-cluster` |
| **`wsrep_local_state_comment = Synced, но wsrep_cluster_size = 1`** | Кластер деградировал до одного узла | `SHOW STATUS LIKE 'wsrep_cluster_size'` | Восстановить остальные узлы кластера |

### Методы диагностики

#### Проверка статуса всех узлов

```bash
# Скрипт для проверки всех узлов кластера
for node in 10.0.1.11 10.0.1.12 10.0.1.13; do
  echo "=== Node: $node ==="
  mysql -h "$node" -u root -p"$(cat /root/.my.cnf | grep password | awk -F= '{print $2}')" -e "
    SELECT 'cluster_status' AS var, wsrep_cluster_status AS val
    UNION SELECT 'cluster_size', wsrep_cluster_size
    UNION SELECT 'node_state', wsrep_local_state_comment
    UNION SELECT 'ready', wsrep_ready
    UNION SELECT 'connected', wsrep_connected;" 2>/dev/null || echo "UNREACHABLE"
done
```

#### Проверка SST/IST в логах

```bash
# Прочитать логи Galera на проблемном узле
grep -i "sst\|ist\|donor\|join" /var/lib/mysql/*.err
grep -i "flow-control\|desync\|pause" /var/lib/mysql/*.err

# Проверить таймауты SST
grep "SST.*timeout\|SST.*complete" /var/lib/mysql/*.err
```

#### Flow control

```sql
-- Мониторинг flow control
SHOW STATUS LIKE 'wsrep_flow_control_paused';
SHOW STATUS LIKE 'wsrep_flow_control_sent';
SHOW STATUS LIKE 'wsrep_flow_control_recv';

-- Допустимые пороги
-- wsrep_flow_control_paused > 0.5 — серьёзный backpressure
-- wsrep_flow_control_paused > 0.1 — требует внимания
```

### Recovery procedures

#### Восстановление потерянного кворума (bootstrap)

Когда большинство узлов недоступно, оставшийся узел нужно перевести в режим bootstrap:

```bash
# 1. Убедиться, что остальные узлы действительно недоступны
# 2. Остановить MySQL на узле-спасителе
sudo systemctl stop mysql

# 3. Запустить с bootstrap (перезапуск кластера с нуля)
sudo systemctl start mysql@bootstrap
# или:
sudo -u mysql mysqld --bootstrap --wsrep-new-cluster
```

#### Восстановление после split-brain

Если два узла продолжают работу с `wsrep_cluster_status=Primary` в разных сетевых сегментах:

```sql
-- 1. Остановить запись на обоих сегментах
STOP SESSION TRANSACTION;

-- 2. Определить, какой сегмент сохраняет актуальные данные
--    (обычно — больший по количеству узлов или с более поздними GTID)

-- 3. На менее актуальном сегменте:
SET GLOBAL wsrep_cluster_address = 'gcomm://10.0.1.11,10.0.1.12,10.0.1.13';
```

## Лучшие практики

### Архитектура и развертывание

1. **Минимум три узла.** PXC требует кворум — два узла могут выйти из синхронизации при любой перезагрузке. Третий узел может быть арбитром.
2. **Выделенная сеть для репликации.** Galera-sensitive: latency < 1 мс, bandwidth ≥ 1 Гбит/с между узлами. Используйте отдельный VLAN или интерфейс.
3. **Отдельный volume для datadir, binlog и redo.** SSD/NVMe с низкой latency. Не используйте общие NFS/FS для datadir.
4. **`pxc_encrypt_cluster_traffic=ON`** (по умолчанию в 8.4) — шифруйте traffic между узлами.
5. **Всегда используйте `wsrep_sst_donor`** для контроля выбора донора в SST.
6. **`wsrep_sst_method = xtrabackup-v2`** — метод по умолчанию и рекомендуемый. `clone` (8.4.4+) быстрее, но требует MySQL 8.0+.
7. **`innodb_flush_log_at_trx_commit = 1`** — обязательно для синхронной репликации (иначе данные могут потеряться при падении).

### Backup и disaster recovery

1. **Не используйте SST как backup.** SST — это синхронизация состояния, а не резервная копия. Для бэкапов используйте Percona XtraBackup или `xtrabackup` SST-метод на выделенном donor.
2. **Регулярная проверка бэкапов** — минимум раз в квартал проводите test restore в изолированной среде. RTO/RPO фиксируйте.
3. **`FLUSH TABLES WITH READ LOCK` + `xtrabackup --backup`** для согласованного состояния при использовании внешнего бэкапа.
4. **Ротация binlog** — `binlog_expire_logs_seconds = 86400` (24ч) для PITR; мониторьте `log_space_used`.

### Мониторинг

1. **Алерты на `wsrep_cluster_status ≠ Primary`** — немедленный escalation.
2. **Алерты на `wsrep_local_recv_queue_avg > 1.0` более 60 секунд** — flow control.
3. **Алерты на `wsrep_cluster_size` < ожидаемого** — degradation.
4. **Мониторинг конфликтов** — `wsrep_conflicts_total`, `wsrep_cert_failures`.
5. **Метрики применения** — `wsrep_app_queue_avg`, `wsrep_local_recv_queue_avg`.

### Безопасность

1. **TLS между узлами** — `pxc_encrypt_cluster_traffic=ON` покрывает intra-cluster.
2. **Сетевые ограничения** — firewall только на порты 3306/4444/4567/4568.
3. **Отдельный пользователь для SST** — `wsrep_sst_auth` с минимальными правами.
4. **`pxc_strict_mode = ENFORCING`** — предотвращает экспериментальные операции в продакшене.

### Очистка и откат

#### Отключение general log (если включён для диагностики)

```sql
SET GLOBAL general_log = OFF;
SHOW VARIABLES LIKE 'general_log%';
```

#### Откат `pxc_strict_mode`

```sql
SET GLOBAL pxc_strict_mode = 'PERMISSIVE';
-- или для автономного узла:
SET GLOBAL pxc_strict_mode = 'DISABLED';
SHOW VARIABLES LIKE 'pxc_strict_mode';
```

#### Откат `wsrep_desync`

```sql
SET GLOBAL wsrep_desync = OFF;
SHOW STATUS LIKE 'wsrep_local_state_comment';
-- → Synced
```

## Операционные процедуры

### Плановое выключение и включение узла

```sql
-- 1. Десинхронизировать узел
SET GLOBAL wsrep_desync = ON;
-- 2. Дождаться опустошения очереди
SELECT wsrep_local_recv_queue_avg, wsrep_local_state_comment;
```

```bash
# 3. Остановить / перезапустить
sudo systemctl stop mysql
sudo systemctl start mysql
systemctl status mysql
# → Active: active (running)
```

```sql
-- 4. Снять десинхронизацию
SET GLOBAL wsrep_desync = OFF;
SHOW STATUS LIKE 'wsrep_local_state_comment';
-- → Synced
```

### Rolling restart

```bash
# Порядок: node-3 → node-2 → node-1
mysql -e "SET GLOBAL wsrep_desync = ON;"
sleep 5
sudo systemctl stop mysql
sudo systemctl start mysql

# Дождаться Synced
while true; do
  state=$(mysql -e "SHOW STATUS LIKE 'wsrep_local_state_comment';" -sN | awk '{print $2}')
  [[ "$state" == "Synced" ]] && break
  sleep 2
done

# Повторить для остальных узлов
```

### Плановое обновление minor-версии

```bash
# 1. Десинхронизировать и остановить
mysql -e "SET GLOBAL wsrep_desync = ON;"
sudo systemctl stop mysql

# 2. Обновить
sudo apt-get update
sudo apt-get install percona-xtradb-cluster-84

# 3. Запустить и проверить
sudo systemctl start mysql
mysql -e "SHOW STATUS LIKE 'wsrep_local_state_comment';"
# → Synced
mysql -e "SHOW STATUS LIKE 'wsrep_cluster_size';"
# → 3
```

> **Важно:** Major-версионные апгрейды требуют остановки кластера, восстановления из бэкапа и bootstrap. См. **[Обзор резервного копирования](./backup_and_recovery/overview.md)**.

### Decommission

```bash
# 1. Десинхронизировать
mysql -e "SET GLOBAL wsrep_desync = ON;"
sleep 5

# 2. Остановить
sudo systemctl stop mysql

# 3. Удалить из ProxySQL
mysql -u admin -p -h proxysql -P 6446 \
  -e "DELETE FROM mysql_servers WHERE hostname='10.0.1.13'; LOAD MYSQL SERVERS TO RUNTIME; SAVE MYSQL SERVERS TO DISK;"

# 4. Удалить из wsrep_cluster_address на остальных узлах
```

## Граничные случаи

### Bootstrap одиночного узла

```bash
sudo systemctl start mysql@bootstrap
mysql -e "SHOW STATUS LIKE 'wsrep_cluster_size';"
# → 1
```

### Сетевой разрыв

```bash
# Восстановить связь
mysql -e "SET GLOBAL wsrep_cluster_address = 'gcomm://';"
mysql -e "SET GLOBAL wsrep_cluster_address = 'gcomm://10.0.1.11,10.0.1.12,10.0.1.13';"
```

### Большие транзакции и flow control

```ini
[mysqld]
wsrep_max_ws_size = 2147483647
wsrep_max_ws_rows = 13107720
wsrep_provider_options = "gcache.size=2G; gcs.fc_limit=256; gcs.fc_factor=0.9"
```

```sql
SHOW STATUS LIKE 'wsrep_flow_control_paused';
SHOW STATUS LIKE 'wsrep_flow_control_sent';
SHOW STATUS LIKE 'wsrep_flow_control_recv';
```

### IST вместо SST

```sql
-- Проверить, что gcache достаточен для IST
SHOW VARIABLES LIKE 'wsrep_provider_options';
```

### `wsrep_sst_method = mysqldump` (legacy)

```bash
# Ограничения: медленнее на больших данных; требует блокировки таблиц; не подходит для продакшена > 10 ГБ
```

## Дополнительная информация

### См. также

- **[Отказоустойчивость MariaDB](../MariaDB/high_availability.md)** — теория
  Galera, конфликты multi-master, QDevice, rolling restart (механика общая для
  Galera и PXC).
- **[Высокая доступность MySQL](./high_availability.md)** — InnoDB Cluster,
  Group Replication, классическая репликация с Orchestrator: сравнение подходов.
- **[Orchestrator](./orchestrator.md)** — автоматический failover для
  асинхронной репликации (в PXC не применяется).
- **[ProxySQL: Failover](./ProxySQL/proxysql_failover.md)** — Galera-hostgroups,
  `max_wsrep_lag`, режим `SHUNNED`.
- **[Резервное копирование и восстановление](./backup_and_recovery/overview.md)** —
  физические бэкапы, PITR, проверка бэкапов.
- **[Внешние ключи (FOREIGN KEY) и ссылочная целостность](./foreign_keys.md)** —
  ограничения, которые влияют на выбор инструмента миграции схемы.
- **[Онлайн-изменение схемы](./Operations/online-schema-change.md)** —
  альтернативы `wsrep_OSU_method` для кластера без Galera.

### Официальная документация

- [Percona XtraDB Cluster 8.4 — Introduction](https://docs.percona.com/percona-xtradb-cluster/8.4/intro.html)
- [Limitations](https://docs.percona.com/percona-xtradb-cluster/8.4/limitation.html) — InnoDB, PK, XA, `LOCK TABLES`, размер транзакции, три узла
- [Configure Nodes](https://docs.percona.com/percona-xtradb-cluster/8.4/configure-nodes.html) — `wsrep_cluster_address`, `wsrep_cluster_name`, `pxc_strict_mode`
- [Bootstrap a Cluster](https://docs.percona.com/percona-xtradb-cluster/8.4/bootstrap.html)
- [State Snapshot Transfer](https://docs.percona.com/percona-xtradb-cluster/8.4/state-snapshot-transfer.html) и [Clone SST](https://docs.percona.com/percona-xtradb-cluster/8.4/clone-sst.html)
- [Online Schema Upgrade](https://docs.percona.com/percona-xtradb-cluster/8.4/online-schema-upgrade.html) и [Non-Blocking Operation](https://docs.percona.com/percona-xtradb-cluster/8.4/nbo.html) — TOI, RSU, NBO
- [wsrep Status Index](https://docs.percona.com/percona-xtradb-cluster/8.4/wsrep-status-index.html) — состояния узла и кластера
- [wsrep System Variables Index](https://docs.percona.com/percona-xtradb-cluster/8.4/wsrep-system-index.html) — значения по умолчанию
- [FAQ](https://docs.percona.com/percona-xtradb-cluster/8.4/faq.html) — кворум, split brain, `pc.ignore_sb`