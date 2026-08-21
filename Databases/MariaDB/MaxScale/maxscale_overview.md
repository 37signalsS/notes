# MariaDB MaxScale: Обзор и эксплуатация

## Определения

*   **MaxScale** — интеллектуальный прокси-сервер баз данных, разработанный MariaDB Corporation. Работает на уровне протокола (L7), понимая синтаксис MySQL/MariaDB. Обеспечивает маршрутизацию, безопасность, пулинг соединений и высокую доступность, отделяя приложение от физической топологии БД.
*   **Monitor (Монитор)** — внутренний модуль MaxScale, который отслеживает состояние узлов БД (мастер/реплика, статус Galera, лаг репликации) и обновляет внутренний список доступных серверов.
*   **Service (Сервис)** — логическая единица, определяющая, как обрабатывать входящие соединения. Каждый сервис связывает набор серверов с конкретным роутером (например, Read/Write Split).
*   **Listener (Слушатель)** — точка входа (IP и порт), через которую приложения подключаются к MaxScale. Каждый listener привязан к одному сервису.
*   **Router (Роутер)** — модуль, реализующий логику распределения запросов между серверами (readwritesplit, readconnroute, binlogrouter).
*   **Filter (Фильтр)** — модуль, модифицирующий запросы или результаты «на лету» (маскирование данных, SQL Firewall, логирование, кэширование).

## Базовые концепции

### Архитектура и модульность

MaxScale построен на базе плагинов, что позволяет гибко настраивать его поведение без изменения исходного кода:

1.  **Protocol Modules (Протоколы):** Реализуют протоколы взаимодействия с клиентами. Основной — `MariaDBClient` (совместимый с MySQL). Также поддерживается REST API для управления.
2.  **Router Modules (Роутеры):** Логика распределения запросов:
    *   `readwritesplit` — разделение чтения и записи (основной роутер для Galera и Master-Slave).
    *   `readconnroute` — простая балансировка нагрузки только для чтения.
    *   `binlogrouter` — проксирование репликации (MaxScale скачивает бинлоги с мастера и раздаёт репликам).
    *   `schemarouter` — маршрутизация по базам данных (для виртуальных схем).
3.  **Filter Modules (Фильтры):** Модификация запросов или результатов на лету:
    *   `masking` — динамическое маскирование чувствительных данных (PII).
    *   `dbfwfilter` — SQL Firewall (блокировка запросов по регулярным выражениям).
    *   `tee` — дублирование запросов в другой сервис (аудит, зеркалирование).
    *   `qlafilter` — логирование запросов в файл.
    *   `cache` — TTL-кэширование результатов запросов.

### Поток запроса через MaxScale

```
Client → Listener → [Filter 1] → [Filter N] → Router → Server (MariaDB)
                                        ↑
                                    Monitor (обновляет состояние серверов)
```

1.  Клиент устанавливает TCP-соединение с Listener.
2.  Listener использует Protocol Module для чтения MySQL-протокола.
3.  Запрос проходит через цепочку Filter-модулей (если настроены).
4.  Router решит, на какой сервер направить запрос, на основе правил и состояния серверов от Monitor.
5.  Monitor работает асинхронно, опрашивая серверы с заданным интервалом (`monitor_interval`).

### Преимущества для MariaDB Galera Cluster

MaxScale является де-факто стандартом для работы с Galera Cluster:

*   **Galera Monitor (`galeramon`):** Автоматически определяет `Primary Component` и направляет трафик только на валидные узлы. Отслеживает 상태 `synced`, `donor`, `joined` и исключает узлы в состоянии `primary-foothold` или `disconnected`.
*   **Auto-Failover:** При падении узла MaxScale мгновенно переключает соединения на другие доступные ноды без вмешательства SRE. Время переключения — миллисекунды (зависит от `monitor_interval`).
*   **Cooperative Monitoring:** Несколько инстансов MaxScale могут обмениваться данными о состоянии кластера для предотвращения Split-Brain. Каждый MaxScale проверяет, не контролирует ли другой прокси тот же набор серверов.
*   ** master-down-action:** При потере мастера в топологии Master-Slave MaxScale может автоматически переключить реплику в режим чтения/записи.

---

## Установка и предварительные требования

### Системные требования

| Параметр | Минимальный | Рекомендуемый |
| :--- | :--- | :--- |
| **CPU** | 1 ядро | 2+ ядра (зависимость от фильтров) |
| **RAM** | 512 MB | 2+ GB (особенно с masking/firewall) |
| **Диск** | 100 MB | SSD для логов и binlog (при binlogrouter) |
| **ОС** | Linux (RHEL 8+, Debian 10+, Ubuntu 20.04+) | Текущий стабильный релиз |
| **MariaDB Server** | 10.5+ (для target_server) | 10.6+ или 11.x |

### Установка из официального репозитория

**RHEL/CentOS/Rocky Linux:**
```bash
# Добавление репозитория MariaDB
curl -sS https://downloads.mariadb.com/keys/mariadb-package-signing-kek.gpg | sudo tee /etc/pki/rpm-gpg/RPM-GPG-KEY-MariaDB
sudo tee /etc/yum.repos.d/MariaDB-MaxScale.repo <<'EOF'
[mariadb-maxscale]
name = MariaDB MaxScale
baseurl = https://dlm.mariadb.com/repo/maxscale/latest/yum/9/x86_64
gpgkey = https://downloads.mariadb.com/keys/mariadb-package-signing-kek.gpg
gpgcheck = 1
enabled = 1
EOF

sudo dnf install -y maxscale
```

**Debian/Ubuntu:**
```bash
# Добавление репозитория MariaDB
sudo apt-get install -y curl apt-transport-https
curl -sS https://downloads.mariadb.com/keys/mariadb-package-signing-kek.gpg | sudo tee /etc/apt/trusted.gpg.d/mariadb-package-signing-kek.gpg
echo "deb https://dlm.mariadb.com/repo/maxscale/latest/deb $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/mariadb-maxscale.list

sudo apt-get update
sudo apt-get install -y maxscale
```

**Docker (для тестирования):**
```bash
docker run -d \
  --name maxscale \
  -p 3306:3306 \
  -v /etc/maxscale.cnf:/etc/maxscale.cnf \
  mariadb/maxscale:latest
```

### Проверка установки

```bash
# Проверка версии
maxscale --version
# → MaxScale 25.10.3

# Проверка статуса службы
systemctl status maxscale
# → active (running)

# Просмотр логов
journalctl -u maxscale -f
```

### Создание служебного пользователя в MariaDB

MaxScale требует отдельного пользователя для подключения к узлам БД. Этот пользователь используется монитором и роутером.

```sql
-- Выполните на каждом узле MariaDB
CREATE USER 'maxscale_user'@'%' IDENTIFIED BY 'СЛОЖНЫЙ_ПАРОЛЬ';
GRANT SELECT, PROCESS, REPLICATION CLIENT, RELOAD, SUPER ON *.* TO 'maxscale_user'@'%';

-- Для Galera Monitor дополнительно
GRANT ALL PRIVILEGES ON mysql.* TO 'maxscale_user'@'%';
FLUSH PRIVILEGES;
```

**Объяснение привилегий:**
- `SELECT, PROCESS` — мониторинг состояния сервера (`SHOW STATUS`, `SHOW PROCESSLIST`).
- `REPLICATION CLIENT` — проверка статуса репликации (`SHOW SLAVE STATUS`).
- `RELOAD` — перезагрузка данных (`FLUSH LOGS`).
- `SUPER` — управление переменными (для `read_only` и т.д.).
- Доступ к `mysql.*` — для чтения таблицы `slave_master_info` при настройке репликации.

---

## Практические сценарии

### Настройка Read/Write Split для Galera

**Prerequisites:** Развернутый Galera Cluster (минимум 3 узла) и установленный MaxScale.

**Шаг 1: Создание конфигурационного файла**

```ini
# /etc/maxscale.cnf

[maxscale]
# Количество рабочих потоков. auto = равно числу CPU-ядер
threads=auto

# Логирование (для отладки)
log_debug=0
log_info=1
logdir=/var/log/maxscale

# Максимальное количество соединений
max_connections=1000

# 1. Монитор для отслеживания состояния узлов Galera
[Galera-Monitor]
type=monitor
module=galeramon
# Список серверов через запятую (имена должны совпадать с секциями [server])
servers=db-node-1,db-node-2,db-node-3
user=maxscale_user
password=СЛОЖНЫЙ_ПАРОЛЬ
# Интервал опроса серверов (в миллисекундах)
monitor_interval=2000ms
# Включить Cooperative Monitoring для предотвращения Split-Brain
cooperative_monitoring=maxscaled=< maxscale_host >

# 2. Сервис для разделения чтения и записи
[RW-Split-Service]
type=service
router=readwritesplit
servers=db-node-1,db-node-2,db-node-3
user=maxscale_user
password=СЛОЖНЫЙ_ПАРОЛЬ
# Максимальный допустимый лаг реплики (в секундах)
max_slave_replication_lag=30
# Критерий выбора реплики: LEAST_CURRENT_OPERATIONS или LEAST_BEHIND_MASTER
router_options=slave_selection_criteria=LEAST_CURRENT_OPERATIONS
# Автоматическое создание соединений с репликами при старте
lazy_connect=true

# 3. Точка входа для приложений
[RW-Split-Listener]
type=listener
service=RW-Split-Service
protocol=MariaDBClient
# IP-адрес для прослушивания (0.0.0.0 = все интерфейсы)
address=0.0.0.0
port=3306
# Максимальное количество соединений через этот listener
max_connections=1000
```

**Шаг 2: Шифрование пароля (рекомендуется)**

```bash
# Шифрование пароля для конфигурационного файла
maxpasswd СЛОЖНЫЙ_ПАРОЛЬ
# → 5A5A... (зашифрованная строка)

# Используйте результат в конфигурации:
# password=5A5A...
```

**Шаг 3: Запуск и проверка**

```bash
# Запуск MaxScale
sudo systemctl start maxscale
sudo systemctl enable maxscale

# Проверка статуса
sudo systemctl status maxscale

# Проверка логов
sudo tail -f /var/log/maxscale/maxscale.log

# Проверка подключения через maxctrl
maxctrl list servers
# → Должны отобразиться все серверы со статусом "Master" или "Slave"
```

**Шаг 4: Валидация работы Read/Write Split**

```bash
# Подключение через MaxScale
mysql -u app_user -p -h <maxscale_host> -P 3306

# В интерактивном режиме MySQL:
SHOW VARIABLES LIKE 'read_only';
# → off (если подключены через RW-Split-Listener)

# Проверка маршрутизации запросов
maxctrl show service RW-Split-Service
# → В секции "Router statistics" отображается количество запросов на чтение/запись
```

### Маскирование данных (Data Masking)

MaxScale позволяет скрывать чувствительные данные (например, номера карт, email, телефоны) от определённых пользователей на уровне прокси без изменения данных на диске.

**Шаг 1: Определение правил маскирования**

```json
// /etc/maxscale.d/masking_rules.json
{
  "rules": [
    {
      "replace": { "column": "email", "match": "^(.*)@(.*)$" },
      "with": { "value": "****@\\2" }
    },
    {
      "replace": { "column": "phone", "match": "^(\\d{3})(\\d{4})(\\d{4})$" },
      "with": { "value": "\\1-XXXX-\\3" }
    },
    {
      "replace": { "column": "credit_card", "match": "^(\\d{4})(\\d{4})(\\d{4})(\\d{4})$" },
      "with": { "value": "\\1-XXXX-XXXX-\\4" }
    }
  ]
}
```

**Шаг 2: Подключение фильтра в конфигурации**

```ini
[Masking-Filter]
type=filter
module=masking
rules=/etc/maxscale.d/masking_rules.json

[RW-Split-Service]
# ... существующие параметры ...
filters=Masking-Filter
```

**Шаг 3: Валидация**

```sql
-- Подключение как пользователь, для которого действует маскирование
SELECT email, phone, credit_card FROM customers LIMIT 1;
-- → ****@example.com, 555-XXXX-6789, 4111-XXXX-XXXX-1234
```

---

## Управление и мониторинг

### Утилита управления `maxctrl`

`maxctrl` — основной инструмент управления MaxScale в командной строке.

**Просмотр состояния:**
```bash
# Состояние всех серверов БД
maxctrl list servers
# → server1    Master   ... 
# → server2    Slave    ...

# Детальная информация о конкретном сервере
maxctrl show server db-node-1

# Список сервисов
maxctrl list services

# Статистика маршрутизации для сервиса
maxctrl show service RW-Split-Service
# → Router statistics:_queries_total, queries_per_sec, etc.

# Список listener'ов
maxctrl list listeners
```

**Управление серверами:**
```bash
# Временно исключить сервер из балансировки (drain)
maxctrl alter server db-node-1 drain

# Вернуть сервер в работу
maxctrl alter server db-node-1 master

# Пометить сервер как offline (принудительно)
maxctrl alter server db-node-1 offline
```

**Управление конфигурацией:**
```bash
# Горячая перезагрузка конфигурации (без перезапуска MaxScale)
maxctrl reload config

# Просмотр текущей конфигурации
maxctrl show maxscale

# Перезапуск MaxScale
maxctrl restart
```

### Мониторинг через Prometheus

MaxScale предоставляет встроенный HTTP-интерфейс для экспозиции метрик.

**Включение в конфигурации:**
```ini
[maxscale]
# ... основные параметры ...
admin_host=127.0.0.1
admin_port=8989

# HTTP-сервер для метрик Prometheus
http_host=0.0.0.0
http_port=9090
```

**Ключевые метрики для мониторинга:**

| Метрика | Описание | Типичный порог |
| :--- | :--- | :--- |
| `maxscale_threads_running` | Количество активных потоков | > 80% от `threads` |
| `maxscale_sessions` | Текущее количество сессий | Зависит от `max_connections` |
| `maxscale_connections_total` | Общее количество соединений | Рост = проблема с пулингом |
| `maxscale_listeners_up` | Количество активных listener'ов | Должно совпадать с настроенным |
| `maxscale_server_status` | Статус сервера (1=up, 0=down) | 0 = проблема |
| `maxscale_router_queries_total` | Общее количество запросов | Мониторинг распределения |
| `maxscale_router_errors_total` | Количество ошибок маршрутизации | > 0 = проблема |

**Пример конфигурации Prometheus:**
```yaml
scrape_configs:
  - job_name: 'maxscale'
    static_configs:
      - targets: ['maxscale-host:9090']
    metrics_path: '/metrics'
```

### Логирование

```ini
[maxscale]
# Уровни логирования: 0=off, 1=error, 2=warning, 3=info, 4=debug
log_info=1
log_warning=1
log_debug=0
logdir=/var/log/maxscale
# Ротация логов (в МБ)
maxlog_size=100
# Логирование запросов (для отладки, НЕ для продакшена)
log_debug=false
```

---

## Best Practices

### Архитектурные рекомендации

1.  **Высокая доступность прокси:** Никогда не используйте один инстанс MaxScale. Разворачивайте минимум два узла в связке с **Keepalived (VRRP)** для плавающего VIP. Это исключает single point of failure на уровне прокси.
2.  **Изоляция ресурсов:** Размещайте MaxScale на отдельных виртуальных машинах или контейнерах. При высокой нагрузке (особенно с фильтрами маскирования) MaxScale потребляет значительные ресурсы CPU и памяти.
3.  **Безопасность паролей:** Используйте `maxpasswd` для шифрования паролей в конфигурационных файлах. Не храните пароли в открытом виде.

### Конфигурация

4.  **`threads=auto`:** В большинстве случаев автоматическое определение количества потоков работает оптимально. Вручную задавайте только при наличии конкретных причин.
5.  **`monitor_interval`:** Стандартное значение — 2000ms. Для критичных систем можно уменьшить до 1000ms, но это tăng нагрузку на серверы. Не рекомендуется ставить менее 500ms.
6.  **`max_slave_replication_lag`:** Для Galera — 30s (по умолчанию). Для классической репликации — 10-60s в зависимости от нагрузки.
7.  **`lazy_connect=true`:** Рекомендуется включить для снижения задержки при первом запросе от клиента.

### Мониторинг и алертинг

8.  **Настройте алерты:** Мониторьте `maxscale_server_status` (проверка что все серверы вверх) и `maxscale_router_errors_total` (ошибки маршрутизации).
9.  **Ротация логов:** Настройте `maxlog_size` и используйте logrotate для предотвращения заполнения диска.
10. **Регулярно проверяйте `maxctrl list servers`:** Убедитесь что все серверы в ожидаемом статусе (Master/Slave).

---

## Граничные случаи и ограничения

### Известные ограничения

1.  **Транзакции и Read/Write Split:** Если транзакция начинается с `SELECT` (автоматическое чтение), а затем выполняется `UPDATE`, MaxScale перенаправит `UPDATE` на мастер. Однако, если соединение уже привязано к реплике, `UPDATE` может завершиться ошибкой. Используйте `SELECT ... FOR UPDATE` для гарантии направления на мастер.
2.  **Временные таблицы:** Временные таблицы видны только в пределах одной сессии. При переключении соединения между серверами временные таблицы теряются.
3.  **Пользовательские переменные:** Переменные типа `@variable` не маршрутизируются и могут привести к некорректному поведению при переключении серверов.
4.  **Prepared Statements:** В некоторых сценариях prepared statements могут работать некорректно при переключении между мастером и репликой.
5.  **Глобальные блокировки:** `LOCK TABLES`, `FLUSH TABLES WITH READ LOCK` могут конфликтовать с работой роутера.

### Нестандартные сценарии

*   **Смешанные Galera + Classic Replication:** MaxScale может работать в обеих топологиях, но конфигурация монитора должна соответствовать типу репликации (galeramon vs mysqlmon).
*   **Каскадная репликация:** MaxScale не поддерживает каскадную репликацию (Slave → Slave). Все реплики должны быть подключены напрямую к мастеру.
*   **Большое количество баз данных:** При большом количестве баз данных Schema Router может потребовать дополнительной настройки фильтрации.

---

## Устранение неполадок (Troubleshooting)

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `All servers are down` | Монитор не может подключиться к БД под служебным пользователем. | Проверьте права пользователя `maxscale_user` на узлах БД (`SELECT`, `REPLICATION CLIENT`, `PROCESS`, `RELOAD`). Убедитесь, что `monitor_interval` корректен. |
| Трафик на запись идет на реплику | Ошибка в определении мастера монитором. | Проверьте `read_only` флаг на узлах MariaDB. Убедитесь, что монитор имеет доступ к чтению `slave_master_info` для определения топологии. |
| Высокая загрузка CPU на MaxScale | Слишком много фильтров или высокая частота опроса монитора. | Увеличьте `monitor_interval` или количество потоков (`threads`). Отключите неиспользуемые фильтры. |
| `Lost connection to MySQL server` | Сервер MariaDB перезапущен или таймаут соединения. | Проверьте `wait_timeout` на сервере. В MaxScale настройте `max_connections` и `connect_timeout`. |
| Запросы не попадают на реплики | Все реплики в статусе `slave` не определены или имеют лаг > `max_slave_replication_lag`. | Проверьте статус репликации на серверах: `SHOW SLAVE STATUS`. Увеличьте `max_slave_replication_lag`. |
| `Error: Listener on port 3306 already in use` | Другой процесс использует порт 3306. | Измените порт в конфигурации или остановите конфликтующий процесс (`lsof -i :3306`). |
| Ошибки в логах: `Authentication failed` | Неверные учётные данные для подключения к серверу. | Проверьте `user` и `password` в конфигурации MaxScale. Убедитесь, что пользователь создан на всех узлах MariaDB. |
| Высокий latency при первом запросе | `lazy_connect=true` отложенное создание соединений. | Это нормальное поведение. Для критичных приложений отключите `lazy_connect` или настройте пул соединений. |
| `Galera: Node is not a Primary Component` | Galera кластер потерял кворум. | Восстановите кворум на узлах Galera. MaxScale автоматически вернёт трафик после восстановления. |

---

## MaxScale vs ProxySQL: Сравнение для SRE

| Характеристика | MariaDB MaxScale | ProxySQL |
| :--- | :--- | :--- |
| **Failover** | **Нативный и автоматический** | Требует внешней логики (Orchestrator) |
| **Galera Support** | Глубокая интеграция (Galera Monitor) | Базовая поддержка через мониторинг переменных |
| **Лицензирование** | BSL (платно для кластеров >3 узлов) | GPL (всегда бесплатно) |
| **Управление** | Традиционные конфиг-файлы или REST API | SQL-интерфейс в рантайме |
| **Security** | Встроенный SQL Firewall (`dbfwfilter`) и Masking | Встроенный Query Firewall |
| **Кэширование** | Базовое (`cache` фильтр) | Продвинутое (Query Cache с TTL) |
| **Пулинг соединений** | Базовый | Продвинутый (Multiplexing) |
| **Поддержка версий** | MariaDB Server 10.5+ | MySQL 5.5+, MariaDB 10.0+ |
| **Протоколы репликации** | binlogrouter (нативная поддержка) | Не поддерживает проксирование репликации |

---

## Дополнительная информация

### См. также

*   **[Deep Dive: MaxScale](../maxscale.md)** — детальный разбор архитектуры, Binlog Router, SQL Firewall и SRE-практик.
*   **[Обзор ProxySQL](../../../MySQL/ProxySQL/proxysql_overview.md)** — альтернатива для экосистемы MySQL/MariaDB.
*   **[Отказоустойчивость MariaDB](../high_availability.md)** — Galera Cluster, Orchestrator и MaxScale в общей архитектуре HA.
