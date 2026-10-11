# Мониторинг безопасности MariaDB

**Актуально для:** MariaDB 10.11 LTS / 11.4 LTS / 11.8 LTS / 12.3 LTS

## Определения

**Security-мониторинг** — непрерывное наблюдение за событиями и метриками, связанными с безопасностью: попытки аутентификации, изменения привилегий, отключение аудита, аномалии в трафике. Отличается от производительного мониторинга тем, что фокусируется на индикаторах компрометации (IOC), а не на ресурсах.

**IOC (Indicator of Compromise)** — признак компрометации: всплеск ошибок `Access denied`, новые привилегированные учётные записи, отключение `server_audit`, подключения с необычных хостов.

**SIEM (Security Information and Event Management)** — система сбора и корреляции событий безопасности. `server_audit` интегрируется через syslog.

**mysqld_exporter** — официальный Prometheus-экспортёр для MariaDB/MySQL: собирает `SHOW GLOBAL STATUS` и `SHOW GLOBAL VARIABLES` в метрики `mysql_global_status_*` / `mysql_global_variables_*`. Сроки TLS-сертификатов НЕ собирает — для этого нужен отдельный экспортёр или скрипт (см. Сценарий 4).

**Alert threshold** — порог срабатывания алерта. Для security-событий пороги обычно ниже, чем для производительных метрик: даже единичное отключение аудита — инцидент.

**Tamper-evidence** — свойство логов, при котором модификация обнаруживается (хеширование, подпись, отправка на внешний хост).

## Основные концепции

### Что именно мониторить

| Категория | Событие/метрика | Почему важно |
| :--- | :--- | :--- |
| Аутентификация | всплеск `Access denied` в error log, рост `Aborted_connects` | brute-force, подбор паролей |
| Квота соединений | рост `Connection_errors_max_connections` | DoS, исчерпание `max_connections`, перебор |
| Аудит | `server_audit_logging` перешёл в OFF | злоумышленник скрывает следы |
| Привилегии | изменения `mysql.user`, `mysql.db`, `mysql.tables_priv` | эскалация привилегий |
| Сеть | подключения с новых хостов/подсетей | несанкционированный доступ |
| TLS | истечение срока сертификата | сбой шифрования трафика |
| Конфигурация | изменения `my.cnf`, `plugin_load_add` | отключение защитных механизмов |
| Ресурсы | резкий рост `Max_used_connections` | DoS, пулы ботов |
| Данные | массовый `SELECT` из таблиц с ПДн | эксфильтрация данных |

### Источники данных

1. **Error log** — ошибки аутентификации, отказ плагинов. Без явного `log_error` на Linux с systemd — в journal (`journalctl -u mariadb`).
2. **server_audit** — CONNECT, QUERY, TABLE события (см. [Аудит](audit.md)).
3. **Бинарные логи** — DDL/DML для реконструкции (см. [Бинарное логирование](binary-logging.md)).
4. **Статусные переменные** — `Aborted_connects`, `Connection_errors_max_connections`, `Max_used_connections` (через `SHOW GLOBAL STATUS` / экспортёр).
5. **ОС** — доступ к файлам datadir, процессы (auditd, AIDE).

### Почему мониторинг — отдельный слой

Аудит фиксирует события для расследования (post-mortem), мониторинг обнаруживает инцидент в реальном времени. Один `server_audit` без алертов — это «чёрный ящик»: полезен после инцидента, но не предотвращает его.

## Предварительные требования

- **Плагин `server_audit`** загружен (`plugin_load_add = server_audit` в `my.cnf`); детали настройки — в [Аудите](audit.md).
- **Привилегии:** `SUPER` — для `SET GLOBAL server_audit_*`; `PROCESS` — для просмотра чужих сессий в `information_schema.PROCESSLIST`; `SELECT` на `mysql.user` — для снимков привилегий.
- **Инструменты:** `rsyslog`/`syslog-ng` (пересылка в SIEM), `openssl` (проверка сертификатов), `mysqld_exporter` + `node_exporter` (Prometheus-метрики).
- **NTP:** корреляция событий между узлами и SIEM требует синхронизированных часов (см. раздел «Синхронизация времени» в [Аудите](audit.md)).

## Практические сценарии

### Сценарий 1: Алерт на всплеск ошибок аутентификации

```bash
# Подсчёт ошибок Access denied за последние 10 минут.
# Час в error log MariaDB дополняется пробелом (формат «%2d»: «2026-10-08  9:46:17»),
# поэтому временную метку собираем заново с нулевым дополнением часа
START=$(date -d '10 minutes ago' '+%Y%m%d%H%M%S')
grep "Access denied" /var/log/mysql/error.log | awk -v d="$START" '{
  split($2, t, ":"); gsub(/-/,"",$1)
  ts = sprintf("%s%02d%02d%02d", $1, t[1], t[2], t[3])
  if (ts+0 > d+0) n++
} END { print n+0 }'
# → при значении > 50 — алерт (порог настраивается)

# Альтернатива при логировании в journald
journalctl -u mariadb --since '10 minutes ago' | grep -c "Access denied"
```

```sql
-- Альтернатива: счётчик через статус (требует подсчёта в приложении/SIEM)
SHOW GLOBAL STATUS LIKE 'Aborted_connects';
-- → резкий рост Aborted_connects — индикатор атаки или ошибки конфигурации клиентов

-- Дифференциальная диагностика: почему растут отказы
SHOW GLOBAL STATUS LIKE 'Connection_errors_%';
-- → Connection_errors_max_connections — исчерпана квота max_connections (DoS или перебор)
-- → Aborted_connects растёт также при отсутствии привилегий у клиента,
--   некорректном connect-пакете или превышении connect_timeout — не только при атаке
```

### Сценарий 2: Контроль состояния аудита

```sql
-- Проверка, что аудит включён
SHOW GLOBAL VARIABLES LIKE 'server_audit_logging';
-- → server_audit_logging | ON

-- Проверка, что плагин активен
SHOW PLUGINS LIKE 'server_audit';
-- → server_audit | ACTIVE
```

Алерт: если `server_audit_logging` стал `OFF` или плагин не `ACTIVE` — немедленное уведомление (P1).

### Сценарий 3: Отслеживание изменений привилегий

```sql
-- Снимок привилегий для сравнения (храните в git)
mariadb -e "SELECT User, Host, Plugin FROM mysql.user ORDER BY User, Host;" > /var/backups/mysql.user.$(date +%F)
mariadb -e "SHOW GRANTS FOR 'app_svc'@'10.0.5.%';" >> /var/backups/grants.$(date +%F)

-- Сравнение с предыдущим снимком
diff /var/backups/mysql.user.$(date -d yesterday +%F) /var/backups/mysql.user.$(date +%F)
```

### Сценарий 4: Мониторинг TLS-сертификата

```bash
# Дней до истечения сертификата
echo | openssl s_client -connect 10.0.5.20:3306 -servername db01.example.com 2>/dev/null | \
  openssl x509 -noout -enddate
# → notAfter=Dec 31 23:59:59 2026 GMT

# Автоматический расчёт
END=$(echo | openssl s_client -connect 10.0.5.20:3306 2>/dev/null | \
  openssl x509 -noout -enddate | cut -d= -f2)
echo $(( ($(date -d "$END" +%s) - $(date +%s)) / 86400 ))" days left"
# → 89 days left (алерт при < 30)
```

### Сценарий 5: Обнаружение аномальных подключений

```sql
-- Откуда подключаются пользователи
SELECT User, Host, COUNT(*) AS connections
FROM information_schema.PROCESSLIST
GROUP BY User, Host
ORDER BY connections DESC;

-- Подключения с хостов вне ожидаемой подсети
-- (Host содержит «host:port»; без привилегии PROCESS видны только собственные сессии)
SELECT User, Host FROM information_schema.PROCESSLIST
WHERE Host NOT LIKE '10.0.5.%' AND Host NOT LIKE 'localhost%';
-- → пустой результат — хорошо
```

## Конфигурации и команды

### Интеграция с SIEM через syslog

```ini
[mariadb]
plugin_load_add        = server_audit
server_audit_events    = CONNECT, QUERY, TABLE
server_audit_logging   = ON
server_audit_output_type = SYSLOG
# ident по умолчанию — «mysql-server_auditing»; задаём явно для фильтрации в rsyslog
server_audit_syslog_ident = mariadb-audit
server_audit_syslog_priority = LOG_INFO
server_audit_syslog_facility = LOG_LOCAL6
```

> Значения `ident` и `facility` должны совпадать с правилом rsyslog ниже (тот же формат, что и в [Аудите](audit.md)).

Настройка rsyslog для пересылки в SIEM:

```bash
# /etc/rsyslog.d/30-mariadb-audit.conf
# один @ — UDP, @@ — TCP (надёжнее для security-событий, поддерживает TLS-канал)
if $programname == 'mariadb-audit' then @@siem.example.com:514
& stop
```

```bash
sudo systemctl restart rsyslog
```

### Prometheus-метрики (через mysqld_exporter)

Пользователь и права для экспортёра:

```sql
CREATE USER 'mysqld_exporter'@'localhost' IDENTIFIED BY '<пароль>' WITH MAX_USER_CONNECTIONS 3;
GRANT SELECT, PROCESS, REPLICATION CLIENT ON *.* TO 'mysqld_exporter'@'localhost';
```

```ini
# /etc/mysql/exporter.cnf (права 0600, владелец — пользователь экспортёра)
[client]
user = mysqld_exporter
password = <пароль>
```

Скрайп-конфигурация Prometheus (экспортёр слушает `:9104`):

```yaml
scrape_configs:
  - job_name: mariadb
    static_configs:
      - targets: ['db01.example.com:3306']
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: localhost:9104
```

Алерты (пример для Alertmanager):

```yaml
groups:
  - name: mariadb-security
    rules:
      - alert: MariaDBAuditDisabled
        expr: mysql_global_variables_server_audit_logging == 0
        for: 1m
        labels:
          severity: critical
      - alert: MariaDBAccessDeniedSpike
        expr: rate(mysql_global_status_aborted_connects[5m]) > 10
        for: 5m
        labels:
          severity: warning
      - alert: MariaDBMaxConnectionsExhausted
        expr: rate(mysql_global_status_connection_errors_max_connections[5m]) > 0
        for: 5m
        labels:
          severity: warning
```

**Срок TLS-сертификата — отдельная метрика.** `mysqld_exporter` НЕ собирает сроки сертификатов (такого собирателя нет). Вариант 1 — textfile collector `node_exporter` (cron каждые 10 минут):

```bash
END=$(echo | openssl s_client -connect 127.0.0.1:3306 -servername db01.example.com 2>/dev/null | \
  openssl x509 -noout -enddate | cut -d= -f2)
echo "mysql_tls_cert_not_after $(date -d "$END" +%s)" > \
  /var/lib/node_exporter/textfile_collector/mysql_tls_cert.prom
```

```yaml
# Алерт на срок сертификата (метрика в Unix epoch)
- alert: MariaDBTLSCertExpiring
  expr: mysql_tls_cert_not_after - time() < 30 * 86400
  labels:
    severity: warning
# Вариант 2: ssl_exporter (TCP-пробер) — метрика ssl_cert_not_after
# с метками cn/dnsnames: expr: ssl_cert_not_after{instance=~"db01.*"} - time() < 30 * 86400
```

## Проверка и валидация

### Проверка полноты мониторинга

```bash
# 1. Аудит-логи поступают в syslog
sudo journalctl -u rsyslog | grep mariadb-audit | tail -5
# → записи CONNECT/QUERY/TABLE
# Fallback: grep mariadb-audit /var/log/syslog (Debian) / /var/log/messages (RHEL)

# 2. SIEM получает события
# → проверка на стороне SIEM: последние события от хоста db01

# 3. Экспортёр отдаёт метрики
curl -s http://localhost:9104/metrics | grep -E 'server_audit_logging|aborted_connects'
# → mysql_global_variables_server_audit_logging 1
# → mysql_global_status_aborted_connects 0

# 4. Алерты срабатывают
# → имитация: SET GLOBAL server_audit_logging = OFF; → алерт MariaDBAuditDisabled
# → восстановление: SET GLOBAL server_audit_logging = ON;

# 5. Правила загружены в Prometheus
curl -s http://prometheus.example.com:9090/api/v1/rules | grep -o 'MariaDBAuditDisabled'
```

## Устранение неполадок

### Алерт «Access denied» — ложное срабатывание

**Причина:** приложение использует устаревший пароль или неверный хост.

**Диагностика:**
```bash
grep "Access denied" /var/log/mysql/error.log | tail -20
# → определите User и Host источника
```

**Решение:** исправьте учётные данные в приложении; если хост неизвестен — расследуйте как инцидент.

### server_audit отключился после перезапуска

**Причина:** `server_audit_logging = ON` не закреплён в `my.cnf` (переменная динамическая, но не персистентная).

**Решение:** добавьте `server_audit_logging = ON` в секцию `[mariadb]` файла конфигурации. Подробнее: [Аудит](audit.md).

### События не доходят до SIEM

**Причина:** несовпадение `server_audit_syslog_ident` или `server_audit_syslog_facility` с правилом rsyslog (ident по умолчанию — `mysql-server_auditing`), либо фаервол блокирует порт SIEM (514/6514).

**Диагностика:**
```bash
# События есть локально?
sudo grep mariadb-audit /var/log/syslog | tail -3      # Debian/Ubuntu
sudo grep mariadb-audit /var/log/messages | tail -3    # RHEL/CentOS
# Текущие syslog-параметры плагина
mariadb -e "SHOW GLOBAL VARIABLES LIKE 'server_audit_syslog%';"
```

**Решение:** приведите ident и facility к значениям из правила rsyslog; проверьте порт и протокол (UDP/TCP) канала до SIEM.

### Aborted_connects растёт без атаки

**Причина:** счётчик инкрементируется не только при ошибках аутентификации, но и при отсутствии привилегий у клиента, некорректном connect-пакете и превышении `connect_timeout`. Исчерпание `max_connections` фиксируется отдельно — в `Connection_errors_max_connections`.

**Диагностика:** `SHOW GLOBAL STATUS LIKE 'Connection_errors_%';` — рост `Connection_errors_max_connections` указывает на квоту соединений, а не на перебор паролей.

**Решение:** скорректируйте порог алерта или `connect_timeout`; при росте `Connection_errors_max_connections` — увеличьте `max_connections` или оптимизируйте пулы подключений приложений.

## Лучшие практики

1. **Алерты на отключение защиты — P1.** Отключение аудита, TDE, TLS — немедленное уведомление, не дежурная очередь.
2. **Снимки привилегий в git.** Ежедневный `SHOW GRANTS` в репозиторий — дешёвый способ обнаружить эскалацию.
3. **Коррелируйте с ОС.** Подключение с нового хоста + процесс `mysqld` с необычным родителем — сильный индикатор компрометации.
4. **Не храните логи только локально.** Логи на том же сервере уничтожаются вместе с ним; отправляйте в SIEM.
5. **Тестируйте алерты.** Периодически имитируйте события и проверяйте доставку уведомлений.

## Граничные случаи

- **Аудит можно отключить с `SUPER`.** `server_audit_logging` — динамическая переменная: любой пользователь с `SUPER` выполнит `SET GLOBAL server_audit_logging=OFF`, а при отсутствии блокировки — даже `UNINSTALL PLUGIN server_audit`. Мониторинг переменной (алерт `MariaDBAuditDisabled`) обнаруживает это; предотвращает — `server_audit = FORCE_PLUS_PERMANENT` в `my.cnf` (см. [Аудит](audit.md)).
- **Аудит фильтрует по имени пользователя, а не по `user@host`.** В CONNECT-записи фиксируется хост, но `server_audit_excl_users`/`incl_users` хосты не различают — учётная запись `app_svc` с двух разных хостов логируется одинаково. Для разделения используйте разные учётные записи.
- **Задержка событий в асинхронном режиме (MariaDB 12.1+).** При `server_audit_file_buffer_size > 0` записи буферизуются в памяти и могут быть недоступны в логе сразу после события — при расследовании «горячего» инцидента учитывайте задержку.
- **Аудит-лог по умолчанию создаётся в `datadir`** (если `server_audit_file_path` не задан явно): при компрометации СУБД лог доступен вместе с данными. Выносите его на отдельный раздел или отправляйте в syslog/SIEM.
- **`general_log` с `log_output = TABLE`** пишет в `mysql.general_log` — таблицу, доступную через SQL, что упрощает эксфильтрацию при компрометации. Для security-целей используйте FILE на отдельном разделе (см. [Аудит](audit.md)).
- **Ошибки аутентификации и ошибки квоты — разные счётчики.** Перебор паролей растит `Aborted_connects`; исчерпание `max_connections` — `Connection_errors_max_connections`. Алерт только на `Aborted_connects` пропустит DoS через исчерпание квоты.
- **Час в error log дополняется пробелом** (формат `%2d`: «2026-10-08  9:46:17») — парсеры логов (ELK, awk со строковым сравнением) должны нормализовать временную метку, иначе события с часом 0–9 выпадают из выборки.

## Дополнительная информация

### Ограничения

- `server_audit` добавляет нагрузку; при высокой нагрузке выбирайте события избирательно (`CONNECT, TABLE` вместо `QUERY`). Оверхед оцените по [Производительность security-фич](security-performance.md).
- Метрики `Aborted_connects` не различают атаку, ошибку конфигурации клиентов и превышение `connect_timeout` — требуется анализ контекста; исчерпание `max_connections` отслеживайте отдельно через `Connection_errors_max_connections`.

### Смежные темы

- **[Аудит](audit.md)** — настройка `server_audit`.
- **[Мониторинг MariaDB](../monitoring.md)** — производительный мониторинг.
- **[Управление логами](../log_management.md)** — ротация и хранение всех логов MariaDB.
- **[Тестирование безопасности](security-testing.md)** — имитация атак для проверки алертов.
- **[Устранение неполадок](troubleshooting.md)** — инциденты и postmortem.
- **[SSL/TLS](ssl-tls.md)** — мониторинг сертификатов.
- **[Комплаенс](compliance.md)** — требования к логированию (PCI DSS Req 10).
- **[CIS Benchmark](cis-benchmark.md)** — контролы мониторинга.
