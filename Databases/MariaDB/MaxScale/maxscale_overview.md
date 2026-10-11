# MariaDB MaxScale: Обзор и эксплуатация

**Актуально для:** MaxScale 25.10.x (GA 25.10.4, 2026-09-17)

## Определения

*   **MaxScale** — интеллектуальный прокси-сервер баз данных от MariaDB Corporation. Работает на уровне протокола (L7), понимая синтаксис MySQL/MariaDB: маршрутизирует запросы, пулит соединения, обеспечивает безопасность и высокую доступность, отделяя приложение от физической топологии БД. Начиная с серии 25.01 — продукт с проприетарной лицензией: для старта требуется `license_key`.
*   **Monitor (Монитор)** — модуль, отслеживающий состояние узлов БД (мастер/реплика, состояния Galera, лаг репликации) и обновляющий статусы серверов. Основные: `mariadbmon` (Primary-Replica) и `galeramon` (Galera).
*   **Service (Сервис)** — логическая единица, связывающая набор серверов с роутером (и, опционально, фильтрами). Каждый сервис — отдельная точка маршрутизации.
*   **Listener (Слушатель)** — точка входа (IP и порт), через которую приложения подключаются к MaxScale. Каждый listener привязан ровно к одному сервису; у одного сервиса может быть несколько listener'ов.
*   **Router (Роутер)** — модуль логики распределения запросов (`readwritesplit`, `readconnroute`, `binlogrouter`, `schemarouter` и др.).
*   **Filter (Фильтр)** — модуль, модифицирующий запросы или результаты «на лету» (маскирование, firewall, логирование, перезапись).
*   **Module command** — команда модуля, вызываемая через `maxctrl call command` (например, `switchover`, `failover`, `bootstrap`).
*   **MaxGUI** — веб-интерфейс управления и мониторинга, живущий на admin-порте REST API (8989).
*   **license_key** — JWT-ключ лицензии MariaDB; MaxScale не стартует без валидного ключа (начиная с 25.01).
*   **persistdir** — каталог (`/var/lib/maxscale/maxscale.cnf.d/`), где хранятся изменения конфигурации, сделанные в рантайме через `maxctrl`/REST API.

## Базовые концепции

### Архитектура и модульность

MaxScale построен на плагинах (разделяемых библиотеках в `libdir`), что позволяет гибко настраивать поведение без изменения исходного кода:

1.  **Protocol Modules (Протоколы):** реализуют протоколы взаимодействия с клиентами. Основной — `MariaDBClient` (совместимый с MySQL); также `MariaDBBackend` для соединений с серверами БД и REST API для управления.
2.  **Router Modules (Роутеры):** логика распределения запросов:
    *   `readwritesplit` — разделение чтения и записи (основной роутер для Primary-Replica и Galera).
    *   `readconnroute` — балансировка соединений (connection routing: соединение привязывается к одному серверу).
    *   `binlogrouter` — проксирование репликации (MaxScale скачивает бинлоги с Primary и раздаёт репликам).
    *   `schemarouter` — маршрутизация по базам данных (для виртуальных схем).
3.  **Filter Modules (Фильтры):** модификация запросов или результатов на лету:
    *   `masking` — динамическое маскирование чувствительных данных (PII).
    *   `firewall` — SQL Firewall (allowlist запросов; заменяет legacy `dbfwfilter`, доступен с 25.10).
    *   `regexfilter` — перезапись запросов по регулярному выражению.
    *   `tee` — дублирование запросов в другой сервис (аудит, зеркалирование).
    *   `qlafilter` — логирование запросов в файл.
    *   `cache` — TTL-кэширование результатов запросов.
4.  **Monitor Modules (Мониторы):** `mariadbmon`, `galeramon`, `csmon` (ColumnStore) и др. Монитор — источник истины о топологии для роутеров.

### Поток запроса через MaxScale

```
Client → Listener → [Filter 1] → [Filter N] → Router → Server (MariaDB)
                                        ↑
                                    Monitor (обновляет статусы серверов)
```

1.  Клиент устанавливает TCP-соединение с Listener.
2.  Listener использует Protocol Module для чтения MySQL-протокола; аутентификация клиента проверяется по данным, которые сервисный пользователь получает с бэкендов.
3.  Запрос проходит через цепочку Filter-модулей (если настроены).
4.  Router решает, на какой сервер направить запрос, на основе правил и состояния серверов от Monitor.
5.  Monitor работает асинхронно, опрашивая серверы с заданным интервалом (`monitor_interval`, default 2s).

### Статусы серверов

Монитор (или администратор вручную) присваивает серверам статусы; роутеры маршрутизируют по ним:

| Статус | Смысл |
| :--- | :--- |
| `Running` | Сервер работает и доступен. |
| `Master` | Сервер — Primary (цель записей). |
| `Slave` | Сервер — реплика (цель чтений). |
| `Synced` | Узел Galera синхронизирован с кластером. |
| `Draining` | Новые соединения не создаются; существующие дорабатываются. |
| `Drained` | Draining завершился: число соединений упало до 0. |
| `Maintenance` | Сервер изъят из эксплуатации: соединения не создаются, существующие закрываются. |
| `Auth Error` | Монитор не может подключиться под своим пользователем (нехватка привилегий). |
| `Slave of External Master` | Реплика внешнего, не мониторируемого Primary. |
| `Master Stickiness` | Галера-узел с `disable_master_failback=true`: статус Primary не возвращается исходному узлу. |

### Галера-специфика: что видит galeramon

Galera Monitor проверяет WSREP-переменные узла. Если узел непригоден, он теряет статусы `Read`/`Write`, но остаётся в состоянии `Running`:

*   `wsrep_ready=0` — WSREP-система не готова, узел не принимает запросы.
*   `wsrep_desync=1` — узел десинхронизирован и не участвует в репликации.
*   `wsrep_reject_queries=[ALL|ALL_KILL]` — запросы запрещены.
*   `wsrep_sst_donor_rejects_queries=1` — donor-узел отклоняет запросы (обрабатывается как `wsrep_reject_queries=ALL`).
*   `wsrep_local_state != 4` (или `!= 2` при `available_when_donor=true`) — узел не в состоянии Sync.

По умолчанию galeramon выбирает Primary-узел с наименьшим `wsrep_local_index` — поэтому несколько MaxScale всегда выбирают один и тот же узел для записи без дополнительной координации. Для управляемого выбора: `use_priority=true` + `priority=<int>` на серверах (отрицательный `priority` — узел никогда не станет Primary), либо `root_node_as_master=true` (только узел с `wsrep_local_index=0`).

Начиная с MaxScale 25.10.2, galeramon поддерживает MariaDB Advanced Cluster (RAFT): лидер получает статус `Write`; пока лидер не найден, кластер считается нерабочим и чтения, и записи отключены. Тип кластера определяется автоматически по `wsrep_provider_name`; при Advanced Cluster параметры `disable_master_failback`, `disable_master_role_setting`, `use_priority` и `root_node_as_master` неэффективны. Смешивание Galera и Advanced Cluster узлов запрещено — монитор снимает все `Read`/`Write` статусы.

### Координация нескольких MaxScale

*   **mariadbmon (Primary-Replica):** несколько MaxScale согласуют, кто выполняет failover/switchover, через блокировки `cooperative_monitoring_locks` (подробнее — **[Failover и Switchover](./maxscale_failover.md)**).
*   **galeramon (Galera):** координация не требуется для выбора узла записи — все мониторы детерминированно выбирают один узел (наименьший `wsrep_local_index` / `use_priority` / Advanced Cluster leader).

## Установка и предварительные требования

### Лицензирование (обязательный шаг)

MaxScale серий 25.01+ — продукт с проприетарной лицензией. **Без валидного `license_key` MaxScale не стартует.** Ключ — JWT, выпущенный в [MariaDB License Portal](https://customers.mariadb.com/license/):

```ini
# /etc/maxscale.cnf
[maxscale]
# либо сам ключ:
license_key=eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6...
# либо абсолютный путь к файлу с ключом (относительный путь трактуется как сам ключ и не стартует):
# license_key=/etc/maxscale-license.key
```

*   Валидация: локально (подпись против встроенных публичных ключей MariaDB) + онлайн (`customers.mariadb.com/license/activated/`; при отсутствии outbound HTTPS — откат на локальную проверку).
*   Проверка при старте и затем каждые 3 часа. Истёкший/невалидный/отсутствующий ключ — MaxScale не стартует. Истёкший ключ в работающем процессе — предупреждение `License is no longer valid.`, трафик продолжает обслуживаться.
*   В логе пишется оставшийся срок: `License expires in 27 days at <date>` (severity: notice >30 дней, warning <30 дней, error — expired).
*   Смена ключа в рантайме: `maxctrl alter maxscale license_key=<new-key>`.
*   **MaxScale Trial** — бесплатный ключ оценочной лицензии (customers.mariadb.com/license/maxscale-trial/), tar-пакет на [mariadb.com/downloads/community/maxscale](https://mariadb.com/downloads/community/maxscale/). Ограничение — 15 одновременных соединений. Пакеты: `maxscale-common`, `maxscale-trial` (сам MaxScale), `maxscale-maxctrl` (Node.js CLI), `maxscale-maxctrl2` (нативная альтернатива maxctrl), `maxscale-exasol` (exasolrouter). Trial и Enterprise не могут быть установлены одновременно; конфигурация на 100% совместима.

### Системные требования

| Параметр | Рекомендация |
| :--- | :--- |
| **Размещение** | Отдельный хост от БД (официальная рекомендация — во избежание конкуренции за ресурсы) |
| **CPU** | `threads=auto` использует все vCPU; учитывайте нагрузку фильтров (masking/firewall) |
| **RAM** | Зависит от числа сессий и фильтров; query classifier cache по умолчанию — 15% доступной памяти |
| **Диск** | Логи (`logdir`), при binlogrouter — `datadir` |
| **ОС** | RHEL/Rocky/Alma Linux, Debian/Ubuntu, SLES |
| **MariaDB Server** | Актуальные релизы 10.x / 11.x (матрица совместимости — в release notes) |
| **vm.overcommit_memory** | Должно быть `0` (default в Linux). MaxScale предполагает успешность аллокаций; при `=2` процесс может упасть с SIGSEGV |
| **maxctrl** | Требует Node.js (мин. 10, рекомендуется LTS); альтернатива — нативный `maxctrl2` |

### Установка из пакетов

Рекомендуемый способ — MariaDB package repository (инструкции по настройке репозитория — в [Installation Guide](https://mariadb.com/docs/maxscale/maxscale-management/deployment/installation-and-configuration/maxscale-installation-guide.md)); MaxScale скачивается с [mariadb.com/downloads/enterprise/enterprise-maxscale](https://mariadb.com/downloads/enterprise/enterprise-maxscale/) (требуется подписка):

```bash
# RHEL/Rocky/Alma Linux (после включения репозитория):
sudo dnf install maxscale

# Debian/Ubuntu:
sudo apt update
sudo apt install maxscale

# SLES:
sudo zypper install maxscale
```

Пакет `maxscale-maxctrl` (CLI) ставится как слабая зависимость; чтобы пропустить его: `dnf install --setopt install_weak_deps=False maxscale` / `apt install --no-install-recommends maxscale`. Отдельные RPM/DEB: `dnf install /path/to/maxscale-*.rpm`. Tarball — для дистрибутивов без пакетов или для установки нескольких версий рядом.

### Docker (для тестирования)

Образ находится в **приватном** MariaDB Enterprise Registry (не на Docker Hub); требуется Customer Download Token:

```bash
# Авторизация в registry
echo "<ENTERPRISE_TOKEN>" | docker login docker.mariadb.com -u <your-mariadb.id-email> --password-stdin

# Базовый запуск (по умолчанию поднят только REST API на 8989, admin:mariadb)
docker run -d -p 8989:8989 --name mxs docker.mariadb.com/maxscale:latest

# С прокси-портом
docker run -d -p 3306:3306 -p 8989:8989 --name mxs docker.mariadb.com/maxscale:latest

# С собственной конфигурацией
docker run -d -p 8989:8989 --name mxs -v /path/to/custom.cnf:/etc/maxscale.cnf.d/custom.cnf docker.mariadb.com/maxscale:latest
```

### Проверка установки

```bash
maxscale --version
# → MaxScale 25.10.4

systemctl status maxscale
# → active (running)

# Логи по умолчанию пишутся в файл (syslog=false по умолчанию):
tail -f /var/log/maxscale/maxscale.log
# Для вывода в journald включите syslog=true в [maxscale]
```

### Служебные пользователи в MariaDB

MaxScale использует **двух** пользователей: сервисный (сервисы загружают с бэкендов учётные записи клиентов) и мониторный (проверка состояния и кластерные операции). Один пользователь на обе роли допустим, если у него есть все нужные гранты. Гранты монитора зависят от типа монитора и версии сервера — см. **[Failover](./maxscale_failover.md)** (mariadbmon) и раздел про galeramon ниже.

**Сервисный пользователь** (каноничный набор, выполняется на Primary; для Galera — на любом узле):

```sql
CREATE USER 'maxscale'@'<maxscale_host>' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';
GRANT SELECT ON mysql.user      TO 'maxscale'@'<maxscale_host>';
GRANT SELECT ON mysql.db        TO 'maxscale'@'<maxscale_host>';
GRANT SELECT ON mysql.tables_priv   TO 'maxscale'@'<maxscale_host>';
GRANT SELECT ON mysql.columns_priv  TO 'maxscale'@'<maxscale_host>';
GRANT SELECT ON mysql.procs_priv    TO 'maxscale'@'<maxscale_host>';
GRANT SELECT ON mysql.proxies_priv  TO 'maxscale'@'<maxscale_host>';
GRANT SELECT ON mysql.roles_mapping TO 'maxscale'@'<maxscale_host>';
GRANT SELECT ON mysql.global_priv   TO 'maxscale'@'<maxscale_host>';
GRANT SHOW DATABASES ON *.* TO 'maxscale'@'<maxscale_host>';
```

**galeramon** требует только `GRANT REPLICA MONITOR ON *.*` (для MariaDB 11.0.1+; в более старых — `REPLICATION CLIENT`). `SUPER` нужен лишь при `set_donor_nodes=true`. `GRANT ALL ON mysql.*` не требуется.

**Пользователи клиентов — двойные гранты.** БД видят всех клиентов как подключающихся с адреса MaxScale, поэтому для `'jdoe'@'client-host'` нужен второй аккаунт `'jdoe'@'maxscale-host'` с тем же паролем и грантами (либо один аккаунт с wildcard `'jdoe'@'%'`, что удобнее, но менее безопасно).

## Практические сценарии

### Шаг 1: Минимальная конфигурация Read/Write Split для Galera

**Prerequisites:** Galera Cluster (≥3 узла), установленный MaxScale, `license_key`, служебный пользователь. Полный разбор параметров роутера — в **[Read/Write Split](./maxscale_readwritesplit.md)**.

```ini
# /etc/maxscale.cnf

[maxscale]
threads=auto          # = числу vCPU (default)
license_key=eyJhbGci...  # обязательный ключ лицензии

# 1. Монитор Galera-кластера
[Galera-Monitor]
type=monitor
module=galeramon
servers=db-node-1,db-node-2,db-node-3
user=maxscale
password=СЛОЖНЫЙ_ПАРОЛЬ
monitor_interval=2000ms   # default 2s; минимум 100ms
# available_when_donor=true  # считать donor-узлы полноценными при неблокирующем SST
# use_priority=true          # управляемый выбор Primary через priority=<int> на серверах

# 2. Сервис разделения чтения и записи
[RW-Split-Service]
type=service
router=readwritesplit
servers=db-node-1,db-node-2,db-node-3
user=maxscale
password=СЛОЖНЫЙ_ПАРОЛЬ
# slave_selection_criteria=least_current_operations  # default
# max_replication_lag для Galera не применим: у Galera нет понятия лага репликации
# lazy_connect=true  # создавать бэкенд-соединения только по запросу (экономит соединения при коротких клиентских сессиях)

# 3. Точка входа для приложений
[RW-Split-Listener]
type=listener
service=RW-Split-Service
protocol=MariaDBClient
address=0.0.0.0
port=3306
```

> Не используйте в секции galeramon параметр `cooperative_monitoring` — его не существует; координация нескольких MaxScale для Galera не нужна (детерминированный выбор Primary). `cooperative_monitoring_locks` — параметр mariadbmon, см. **[Failover](./maxscale_failover.md)**.

### Шаг 2: Шифрование пароля (рекомендуется)

```bash
# 1. Генерация ключа шифрования (один раз; ключ сохраняется в datadir=/var/lib/maxscale)
sudo -u maxscale maxkeys

# 2. Шифрование пароля
maxpasswd СЛОЖНЫЙ_ПАРОЛЬ
# → 96F99AA1315BDC3604B006F427DD9484

# 3. Используйте результат в конфигурации:
# password=96F99AA1315BDC3604B006F427DD9484
```

Если ключ лежит не в `datadir`, задайте `datadir=<каталог_с_ключом>` в `[maxscale]`. За расположение файла `.secrets` отвечает `secretsdir`.

### Шаг 3: Запуск и валидация

```bash
sudo systemctl start maxscale
sudo systemctl enable maxscale

# Ожидаемый вывод: сервис, серверы, listener
maxctrl list services
# ┌──────────────────┬────────────────┬─────────────┬───────────────────┬───────────────────────────┐
# │ Service          │ Router         │ Connections │ Total Connections │ Servers                   │
# ├──────────────────┼────────────────┼─────────────┼───────────────────┼───────────────────────────┤
# │ RW-Split-Service │ readwritesplit │ 1           │ 1                 │ db-node-1, db-node-2, ... │
# └──────────────────┴────────────────┴─────────────┴───────────────────┴───────────────────────────┘

maxctrl list servers
# ┌───────────┬─────────────┬──────┬─────────────┬─────────────────┬───────────┐
# │ Server    │ Address     │ Port │ Connections │ State           │ GTID      │
# ├───────────┼─────────────┼──────┼─────────────┼─────────────────┼───────────┤
# │ db-node-1 │ 192.168.2.1 │ 3306 │ 0           │ Master, Running │ 0-3000-62 │
# │ db-node-2 │ 192.168.2.2 │ 3306 │ 0           │ Slave, Running  │ 0-3000-62 │
# └───────────┴─────────────┴──────┴─────────────┴─────────────────┴───────────┘

maxctrl list listeners RW-Split-Service
# ┌───────────────────┬──────┬──────┬─────────┐
# │ Name              │ Port │ Host │ State   │
# ├───────────────────┼──────┼──────┼─────────┤
# │ RW-Split-Listener │ 3306 │      │ Running │
# └───────────────────┴──────┴──────┴─────────┘

# Проверка маршрутизации: запись идёт на Master, чтение — на реплики
mysql -u app_user -p -h <maxscale_host> -P 3306
SELECT @@hostname;  -- повторные вызовы могут показать разные реплики
```

### Шаг 4: Плановое выключение узла (maintenance / drain)

```bash
# drain: новые соединения не создаются, существующие дорабатывают запросы
maxctrl set server db-node-2 drain

# maintenance: соединения закрываются при следующем запросе; --force закрывает немедленно
maxctrl set server db-node-2 maintenance

# Вернуть узел в строй
maxctrl clear server db-node-2 maintenance

# Важно: сервер в состоянии Master нельзя drain'ить — сначала switchover (mariadbmon),
# затем drain. Maintenance снимается на каждом MaxScale отдельно.
```

## Управление и мониторинг

### Утилита управления `maxctrl`

`maxctrl` — CLI-клиент, общающийся с MaxScale через REST API. Defaults: хост `127.0.0.1:8989`, пользователь `admin`, пароль `mariadb` (**смените их в production**). Настройки по умолчанию можно зафиксировать в `~/.maxctrl.cnf` (секция `[maxctrl]`, ключи `u`/`p`; файл должен быть доступен только владельцу, иначе maxctrl откажется его читать). Для удалённого управления: `--hosts HOST:PORT` и TLS-флаги (`-s/--secure`, `--tls-ca-cert` и др.).

```bash
# Состояние объектов
maxctrl list servers | services | listeners | monitors | sessions | filters | threads
maxctrl show server db-node-1        # Parameters, Statistics, Master ID, Node ID...
maxctrl show service RW-Split-Service  # включая Router Diagnostics

# Управление серверами (статусы — через set/clear, не alter)
maxctrl set server db-node-1 drain|maintenance|offline
maxctrl clear server db-node-1 maintenance

# Управление объектами в рантайме (изменения сохраняются в persistdir)
maxctrl create server db-node-4 192.168.0.104 3306
maxctrl alter server db-node-1 port 3307
maxctrl destroy server db-node-4 --force
maxctrl link monitor Galera-Monitor db-node-4
maxctrl create user ops-user ops-password --type=admin   # админ-аккаунт REST API
maxctrl alter maxscale license_key=<new-key>

# Ротация логов (лог-файл, admin audit, qlafilter)
maxctrl rotate logs

# Перезагрузка конфигурации сессии (использует актуальную конфигурацию сервиса)
maxctrl reload session <id>

# Активные запросы (требует retain_last_statements > 0)
maxctrl list queries --max-length=0
```

Ограничения: `maxctrl` не работает, если systemd-юнит задан с `MemoryDenyWriteExecute=true`. Параметры, не помеченные как Dynamic, меняются только через destroy/recreate объекта.

### Мониторинг метрик

Встроенного Prometheus-эндпоинта нет. Метрики экспортируются через OpenTelemetry (OTLP push на коллектор) или читаются через REST API. Включение: `telemetry=true`, `telemetry_url` (default `http://localhost:4318/v1/metrics`), **`telemetry_update_interval`** (default 60s — параметр именно с таким именем), `telemetry_attributes`, `telemetry_sql_count` (50). Полный список метрик, алерты и конфиг OTel Collector — в **[Мониторинг](./maxscale_monitoring.md)**.

### Логирование

```ini
[maxscale]
# Пишем в файл (default) и/или в journald
maxlog=true        # default: писать в maxscale.log
syslog=false       # default: не писать в journald (включите для journalctl -u maxscale)
log_warning=true   # default
log_notice=true    # default
log_info=false     # default; включайте для диагностики маршрутизации
log_debug=false    # default; для разработки, в release-сборке может быть неэффективен
logdir=/var/log/maxscale
# Подавление повторяющихся ошибок: 10 раз за 1s → пауза 10s (default)
log_throttling=10, 1000ms, 10000ms
# Предупреждать о подключениях клиентов с SUPER (диагностика помех switchover)
log_warn_super_user=true
```

Миллисекундные метки — `ms_timestamp=true`; имена функций в сообщениях — `log_augmentation=1`. Low-overhead трассировка — `trace_file_dir` + `trace_file_size` (файлы `maxscale.trace.N`, symlink `maxscale.trace` с 24.08.1).

### MaxGUI и REST API

REST API слушает `admin_host=127.0.0.1:admin_port=8989` (default). Для доступа по сети: `admin_host=0.0.0.0`. MaxGUI по умолчанию требует HTTPS (`admin_secure_gui=true`); отключение `admin_secure_gui=false` допустимо только в изолированной тестовой среде — иначе учётные данные идут открытым текстом. Аудит вызовов REST API: `admin_audit=true` (файл `admin_audit_file=/var/log/maxscale/admin_audit.csv`). SSO через OIDC: `admin_oidc_url`, `admin_oidc_client_id` и др. Блокировка хоста после 10 ошибок аутентификации: `max_auth_errors_until_block`. TLS для admin-интерфейса и защита учётных данных — в **[Безопасность](./maxscale_security.md)** и **[REST API](./maxscale_rest_api.md)**.

## Best Practices

### Архитектурные

1.  **Высокая доступность прокси:** никогда не один инстанс MaxScale. Минимум два узла + Keepalived (VRRP) для плавающего VIP — иначе прокси сам является SPOF. Для координации failover между инстансами — `cooperative_monitoring_locks` (**[Failover](./maxscale_failover.md)**).
2.  **Изоляция ресурсов:** отдельный хост/контейнер; при masking/firewall потребление CPU и RAM заметно растёт.
3.  **Лицензия:** контролируйте оставшийся срок (`License expires in N days` в логе), обновляйте ключ до истечения; держите `license_key` в системе управления конфигурациями.

### Конфигурация

4.  **`threads=auto`** — оптимален в большинстве случаев; ручное значение — только при доказательствах (см. Производительность). Hard limit — `threads_max` (default 256).
5.  **`monitor_interval=2000ms`** — стандарт (min 100ms). Уменьшайте только для критичных систем: каждый опрос — нагрузка на БД.
6.  **`max_replication_lag`** — default `0s` (отключено). Включайте только для классической репликации (для Galera параметр бессмысленен — лага нет); значение — из SLA на свежесть данных. Реплика отключается от маршрутизации при лаге > `max_replication_lag`, а её соединения сбрасываются при лаге > `MAX(300, 2*max_replication_lag)`.
7.  **`lazy_connect`** — default `false` (соединения создаются при старте сессии, первый запрос быстрее). `true` экономит бэкенд-соединения при коротких клиентских сессиях, но добавляет latency на первый запрос.
8.  **`log_warn_super_user=true`** — ловит клиентов с SUPER, которые обходят `read_only` и ломают switchover.
9.  **Шифрование паролей:** `maxkeys` + `maxpasswd`; не храните пароли открытым текстом.
10. **TLS:** `require_secure_transport=true` (25.10+) принудительно включает TLS для listener'ов, server'ов и REST API; Unix-сокеты считаются безопасными. На одном listener'е нельзя одновременно принимать шифрованные и открытые соединения — для legacy-клиентов отдельный listener.
11. **Бэкап персистентной конфигурации:** регулярно резервируйте `persistdir` (`/var/lib/maxscale/maxscale.cnf.d/`) — изменения через `maxctrl` сохраняются там и перекрывают `/etc/maxscale.cnf` для затронутых объектов.
12. **Обновление параметров монитора (25.10):** `backend_write_timeout` (игнорируется с 25.10.0), `backend_read_timeout` (игнорируется с 25.08.0), `backend_connect_timeout` (alias `backend_timeout` с 25.10.0), `query_retries`/`query_retry_timeout` (игнорируются) — используйте единый `backend_timeout` (default 3s).

### Мониторинг и алертинг

13. Алерты по `maxscale.server.status` (Down), ошибкам сервисов, статусу лицензии и полю `primary` монитора — список метрик в **[Мониторинг](./maxscale_monitoring.md)**.
14. Ротация логов через logrotate (`maxlog_size` — такого параметра нет; встроенной ротации по размеру не предусмотрено).
15. Регулярно проверяйте `maxctrl list servers` и статус `Auth Error` (проблема с грантами монитора).

## Граничные случаи и ограничения

1.  **Транзакции и Read/Write Split:** транзакция целиком на одном сервере; если транзакция начинается с `SELECT` и затем идёт `UPDATE`, запрос направляется на Primary. `SELECT ... FOR UPDATE` гарантирует направление на Primary.
2.  **Временные таблицы:** `strict_tmp_tables=true` (default с 24.02) запрещает переключение сервера, пока в сессии есть временные таблицы — сессия закрывается при потере Primary вместо «исчезновения» таблиц.
3.  **Пользовательские переменные:** маршрутизируются: `use_sql_variables_in=all` (default) отправляет `SET` и чтение `@var` на все серверы; `=master` — только на Primary. DML с `@var` — всегда на Primary.
4.  **Prepared Statements:** при `causal_reads` синхронизация идёт отдельным пакетом перед `COM_STMT_EXECUTE`; при таймауте causal read сессия пересоздаётся — включайте session-command history.
5.  **Глобальные блокировки:** `LOCK TABLES`, `FLUSH TABLES WITH READ LOCK` конфликтуют с работой роутера.
6.  **Ограничения TLS (25.10):** один режим (шифрованный/открытый) на listener; для смешанных клиентов — отдельные listener'ы.
7.  **Устаревшие параметры (25.10+):** `backend_write_timeout`, `backend_read_timeout`, `backend_connect_timeout`, `query_retries`, `query_retry_timeout` игнорируются; `passive` deprecated с 25.01 (используйте cooperative monitoring); `optimistic_trx` перенесён в фильтр OptimisticTrx (25.01).
8.  **Конфигурационная синхронизация:** `config_sync_cluster` синхронизирует объекты между MaxScale через таблицу `mysql.maxscale_config` (интервал 5s); `bootstrap`/`discover-replicas` с ней несовместимы.
9.  **Аутентификация:** после 10 ошибок подряд хост блокируется (`max_auth_errors_until_block`); `enable_root_user=false` по умолчанию — root не подключается через MaxScale.
10. **Смешанные топологии:** Galera и классическая репликация требуют разных мониторов (galeramon vs mariadbmon); реплики, реплицирующиеся с Galera-узлов, galeramon видит как `Read, Running`.

## Устранение неполадок (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| MaxScale не стартует, в логе `Invalid license key` / `License is no longer valid` | Нет/невалидный/истёкший `license_key`; относительный путь к файлу ключа | Установите ключ или абсолютный путь в `[maxscale]`; обновите ключ в License Portal; `maxctrl alter maxscale license_key=<new-key>` |
| `All servers are down` | Монитор не подключается под своим пользователем | Проверьте гранты (`Auth Error` в `maxctrl list servers`), `user`/`password`, `monitor_interval` |
| Сервер в статусе `Auth Error` | Не хватает привилегий мониторному пользователю | Дайте требуемые гранты (REPLICA MONITOR и др.) |
| Трафик на запись идёт на реплику | Монитор не определил Primary | Для mariadbmon — проверьте `read_only` и GTID; для Galera — `wsrep_local_state`, `wsrep_ready`; `maxctrl show monitor <name>` |
| Высокая загрузка CPU MaxScale | Много фильтров, частый опрос монитора, обратные DNS-lookups | Увеличьте `monitor_interval`, отключите неиспользуемые фильтры, включите `skip_name_resolve=true` и заводите пользователей по IP |
| `Lost connection to MySQL server` | Сервер перезапущен или таймаут | Проверьте `wait_timeout` на сервере; `connection_keepalive` (default 300s) и `max_connections` сервиса |
| Запросы не попадают на реплики | Реплики в лаге > `max_replication_lag` или без статуса `Slave` | `SHOW REPLICA STATUS` на реплике; увеличьте `max_replication_lag` |
| `Listener on port 3306 already in use` | Порт занят другим процессом | Другой порт или остановите конфликтующий процесс (`lsof -i :3306`) |
| `Authentication failed` в логах | Неверные учётные данные или нет второго аккаунта клиента на хосте MaxScale | Проверьте `user`/`password`; создайте `'user'@'<maxscale_host>'` (двойные гранты) |
| Высокий latency первого запроса | `lazy_connect=true` | Нормальное поведение; для критичных приложений отключите `lazy_connect` |
| `Galera: Node is not a Primary Component` | Кластер потерял кворум | Восстановите кворум; MaxScale вернёт трафик автоматически |
| `require_secure_transport` блокирует запуск | Есть объекты без TLS | Включите `ssl=true` на всех listener'ах и server'ах |
| `maxctrl` не работает, хотя MaxScale жив | SystemD-юнит с `MemoryDenyWriteExecute=true` | Уберите опцию из юнита |
| `journalctl -u maxscale` пуст | `syslog=false` по умолчанию | Смотрите `/var/log/maxscale/maxscale.log` или включите `syslog=true` |
| Изменения в `/etc/maxscale.cnf` не применяются | Для объекта есть запись в `persistdir` | Удалите файл объекта из `/var/lib/maxscale/maxscale.cnf.d/` и перезапустите MaxScale |

## MaxScale vs ProxySQL: Сравнение для SRE

| Характеристика | MariaDB MaxScale | ProxySQL |
| :--- | :--- | :--- |
| **Failover** | Нативный автоматический (mariadbmon) | Требует внешней логики (Orchestrator) |
| **Galera Support** | Глубокая интеграция (galeramon, Advanced Cluster с 25.10.2) | Базовая поддержка через мониторинг переменных |
| **Лицензирование** | Проприетарная лицензия; `license_key` обязателен для старта (с серии 25.01; ранее — BSL 1.1). Бесплатный Trial-ключ (лимит 15 соединений) | GPL (бесплатно) |
| **Управление** | Конфиг-файлы + REST API + `maxctrl`/`maxctrl2` | SQL-интерфейс в рантайме |
| **Security** | Встроенные `firewall` и `masking` | Встроенный Query Firewall |
| **Кэширование** | `cache` фильтр | Продвинутое кэширование запросов |
| **Пулинг соединений** | Idle session pool (`idle_session_pool_time`, `multiplex_timeout`) | Продвинутый multiplexing |
| **Поддержка версий** | MariaDB Server 10.x / 11.x | MySQL 5.5+, MariaDB 10.0+ |
| **Проксирование репликации** | binlogrouter (нативно) | Не поддерживает |

## Безопасность и шифрование

TLS для клиентских listener'ов и соединений с серверами БД, защита REST API, firewall/masking — подробно в **[Безопасность](./maxscale_security.md)**. Ключевые моменты:

```ini
[RW-Split-Listener]
type=listener
service=RW-Split-Service
ssl=true
ssl_key=/certs/maxscale-listener-key.pem
ssl_cert=/certs/maxscale-listener-cert.pem
ssl_ca=/certs/ca-cert.pem

[MariaDB-Server1]
type=server
address=db-node-1.example.com
port=3306
ssl=true
ssl_verify_peer_certificate=true
ssl_ca=/certs/mariadb-ca.pem
```

Глобальное принуждение к TLS: `require_secure_transport=true` в `[maxscale]` (статический параметр; KafkaImporter тоже потребует SSL; Unix-сокеты безопасны без TLS). Проверка admin-TLS: `maxctrl --secure --tls-ca-cert=/certs/ca-cert.pem show maxscale`. Управление ключами шифрования: `key_manager=none|file|kmip|vault`.

## Резервное копирование и восстановление конфигурации

MaxScale хранит конфигурацию в двух местах:

1.  **Статическая:** `/etc/maxscale.cnf` и `/etc/maxscale.cnf.d/` (рекурсивно читаются файлы `*.cnf`), `/etc/maxscale.modules.d/` — для модулей.
2.  **Персистентная (runtime-изменения):** `persistdir` = `/var/lib/maxscale/maxscale.cnf.d/` (по умолчанию). Для затронутого объекта запись в persistdir перекрывает `/etc/maxscale.cnf`.

Полностью «летучий» режим (как `SET GLOBAL` в MariaDB): `persist_runtime_changes=false` + `load_persisted_configs=false` в `[maxscale]`.

```bash
# Бэкап
sudo cp /etc/maxscale.cnf /data/backups/maxscale/maxscale.cnf
sudo cp -r /etc/maxscale.cnf.d /data/backups/maxscale/static.d
sudo cp -r /var/lib/maxscale/maxscale.cnf.d /data/backups/maxscale/persisted.d

# Восстановление
sudo systemctl stop maxscale
sudo cp /data/backups/maxscale/maxscale.cnf /etc/maxscale.cnf
sudo cp -r /data/backups/maxscale/static.d/* /etc/maxscale.cnf.d/
sudo cp -r /data/backups/maxscale/persisted.d/* /var/lib/maxscale/maxscale.cnf.d/
sudo systemctl start maxscale
```

**Рекомендация:** держите конфигурацию в Ansible/Puppet/Chef; любые изменения через `maxctrl` документируйте и отражайте в статической конфигурации.

## Обновление MaxScale

### Процедура

```bash
# 1. Бэкап конфигурации (см. выше), включая persistdir
# 2. Проверка release notes на предмет изменений параметров
# 3. Тестовое обновление в стенде
sudo systemctl stop maxscale

# RHEL/Rocky/Alma:
sudo dnf update maxscale
# Debian/Ubuntu:
sudo apt-get update && sudo apt-get install --only-upgrade maxscale

maxscale --version
# → MaxScale 25.10.4

sudo systemctl start maxscale
maxctrl list servers
```

Перед обновлением убедитесь, что `license_key` присутствует и валиден — без него обновлённый MaxScale не стартует. Релизы серии выходят примерно раз в квартал; патчи безопасности выкатываются одновременно для всех поддерживаемых серий (23.02/23.08/24.02/25.01/25.10).

### Критические изменения при переходе на 25.10

*   Игнорируются: `backend_write_timeout` (25.10.0), `backend_read_timeout` (25.08.0), `query_retries`, `query_retry_timeout`; `backend_connect_timeout` — alias `backend_timeout` (25.10.0). Удалены: `execdir` (25.10), `cachedir` и `language` (25.08). Deprecated: `query_classifier` (23.08), `passive` (25.01).
*   **Новые привилегии сервисного пользователя:** `GRANT SELECT ON mysql.global_priv` — требуется для поддержки аутентификации с множественными механизмами (уже входит в каноничный набор выше).

### Откат на предыдущую версию

```bash
sudo systemctl stop maxscale
sudo dnf remove maxscale            # или apt remove
sudo dnf install maxscale-25.01.8   # конкретная версия
sudo systemctl start maxscale
```

## Ротация логов и централизованный сбор

```bash
sudo tee /etc/logrotate.d/maxscale <<'EOF'
/var/log/maxscale/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    sharedscripts
    postrotate
        # maxctrl rotate logs закрывает и пересоздаёт лог-файл
        if test -n "$(ps acx | grep maxscale)"; then
            /usr/bin/maxctrl rotate logs
        fi
    endscript
}
EOF
```

Альтернатива — сигнал `USR1` (PID-файл с 24.08.1 в `/run/maxscale/`):

```bash
    postrotate
        kill -USR1 $(cat /run/maxscale/maxscale.pid)
    endscript
```

Для централизованного сбора: `syslog=true` (journald) или `rsyslog` forwarding. `journalctl -u maxscale` показывает логи MaxScale только при `syslog=true`.

## Производительность и тюнинг

### Потоки

```ini
[maxscale]
threads=auto        # = vCPU (default); в контейнерах учитываются квоты cgroup (с 24.08)
threads_max=256     # hard limit (default)
# Перебалансировка нагрузки между потоками (отключена по умолчанию)
# rebalance_period=10s
# rebalance_threshold=20
# rebalance_window=10
```

Проверка загрузки потоков: `maxctrl list threads` (Load 1s/1m/1h, число FDs). Увеличивайте `threads` вручную только при доказанной нехватке: высокая загрузка CPU процессом MaxScale при растущем числе сессий.

### Соединения и пулинг

```ini
[RW-Split-Service]
max_connections=1000        # default 0 = без лимита (15 в Trial)
max_slave_connections=255   # default; жёсткий лимит реплик на сессию
slave_connections=1         # default 255 (soft limit); =1 рекомендуется для коротких клиентских сессий
connection_keepalive=300s   # default; keep-alive idle-бэкенд-соединений (auto_tune)
```

`lazy_connect=true` — создавать бэкенд-соединения только при первом запросе (экономия соединений при коротких сессиях; первый запрос медленнее). Подробно о пулинге — **[Пулинг соединений](./maxscale_connection_pooling.md)**.

### Интервал мониторинга и лаг

```ini
[Galera-Monitor]
monitor_interval=2000ms   # стандарт; <1000ms — повышенная нагрузка на БД
```

```ini
[RW-Split-Service]
max_replication_lag=30    # только классическая репликация; default 0 = отключено
```

Значение лага — из SLA: `<10s` для жёстких требований к свежести, `30s` стандарт, `>60s` для аналитики. Для гарантированной причинно-следственной свежести используйте `causal_reads`, а не `max_replication_lag`.

### Другие рычаги

*   `query_classifier_cache_size` — default 15% доступной памяти; статистика через `maxctrl show threads` (QC cache hits/misses/evictions).
*   `writeq_high_water=65536` / `writeq_low_water=1024` (defaults) — throttling буфера записи.
*   `skip_name_resolve=true` — отключить обратные DNS-lookups (медленные при больших объёмах аутентификации); заводите пользователей по IP.

## Дополнительная информация

### См. также

*   **[Failover и Switchover (mariadbmon)](./maxscale_failover.md)** — автоматический failover, switchover, rejoin, координация нескольких MaxScale, гранты для кластерных операций.
*   **[Read/Write Split](./maxscale_readwritesplit.md)** — slave_selection_criteria, causal_reads, transaction_replay, OptimisticTrx.
*   **[Пулинг соединений](./maxscale_connection_pooling.md)** — persistpoolmax, connection sharing, multiplexing.
*   **[Безопасность](./maxscale_security.md)** — firewall filter, masking, regexfilter, readonly filter, безопасность REST API.
*   **[Мониторинг](./maxscale_monitoring.md)** — telemetry/OpenTelemetry, эталонный список метрик, алерты, MaxGUI.
*   **[REST API и автоматизация maxctrl](./maxscale_rest_api.md)** — curl, runtime-объекты, module commands, Ansible-паттерны.
*   **[Binlog Router](./maxscale_binlogrouter.md)** — прокси репликации, GTID, архивирование бинлогов.
*   **[Readconnroute и schemarouter](./maxscale_routers.md)** — балансировка соединений, шардирование.
*   **[Обзор ProxySQL](../../MySQL/ProxySQL/proxysql_overview.md)** — альтернатива для экосистемы MySQL/MariaDB.
*   **[Отказоустойчивость MariaDB](../high_availability.md)** — Galera Cluster, Orchestrator и MaxScale в общей архитектуре HA.

### Официальная документация

*   [About MariaDB MaxScale](https://mariadb.com/docs/maxscale/maxscale-architecture/mariadb-maxscale-guide.md) — концепции и архитектура.
*   [MaxScale Installation Guide](https://mariadb.com/docs/maxscale/maxscale-management/deployment/installation-and-configuration/maxscale-installation-guide.md)
*   [MaxScale Configuration Guide](https://mariadb.com/docs/maxscale/maxscale-management/deployment/installation-and-configuration/maxscale-configuration-guide.md) — полный справочник параметров.
*   [MaxScale Configuration Settings](https://mariadb.com/docs/maxscale/reference/maxscale-configuration-settings.md) — defaults и dynamic-флаги всех параметров.
*   [Galera Monitor](https://mariadb.com/docs/maxscale/reference/maxscale-monitors/galera-monitor.md), [MariaDB Monitor](https://mariadb.com/docs/maxscale/reference/maxscale-monitors/mariadb-monitor.md), [Common Monitor Parameters](https://mariadb.com/docs/maxscale/reference/maxscale-monitors/common-monitor-parameters.md)
*   [Readwritesplit Router](https://mariadb.com/docs/maxscale/reference/maxscale-routers/maxscale-readwritesplit.md)
*   [MaxCtrl Reference](https://mariadb.com/docs/maxscale/reference/maxscale-maxctrl.md), [Administration Tutorial](https://mariadb.com/docs/maxscale/mariadb-maxscale-tutorials/maxscale-administration-tutorial.md)
*   [Install a MaxScale License Key](https://mariadb.com/docs/maxscale/maxscale-management/deployment/installation-and-configuration/maxscale-license-key.md), [MaxScale Trial](https://mariadb.com/docs/maxscale/maxscale-use-cases/maxscale-trial.md)
*   [Deploy MaxScale with Docker](https://mariadb.com/docs/maxscale/maxscale-management/deployment/installation-and-configuration/deploy-maxscale-with-docker.md)
*   [All MaxScale Releases](https://mariadb.com/docs/release-notes/maxscale/all-releases.md)
