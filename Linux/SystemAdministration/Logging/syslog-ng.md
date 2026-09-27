# syslog-ng: Альтернативный syslog-демон

## Определения

**syslog-ng** — высокопроизводительный демон для сбора, обработки и пересылки системных логов. В отличие от rsyslog, использует чисто декларативную модель конфигурации и более стабилен при глубоком парсинге логов. Разрабатывается компанией One Identity (ранее Balabit), доступен как open-source (OFE) и коммерческая версия (PE).

**Ключевое отличие от rsyslog:** syslog-ng не имеет гибридного формата (legacy + современный). Вся конфигурация строится на блочной структуре с ясной семантикой, что упрощает поддержку сложных правил фильтрации и маршрутизации.

## Базовые концепции

### Архитектура

```
Источники (sources) → Парсеры (parsers) → Фильтры (filters) → Маршруты (destinations) → Логи (logs)
```

**Основные компоненты:**

| Компонент | Описание | Пример |
|:---|:---|:---|
| **Source** | Откуда поступают логи | `system()`, `network()`, `file()`, `pipe()` |
| **Parser** | Разбор и трансформация сообщений | `csv-parser()`, `json-parser()`, `patterndb` |
| **Filter** | Условия маршрутизации | `program()`, `level()`, `host()`, `match()` |
| **Destination** | Куда отправляются логи | `file()`, `network()`, `syslog()`, `elasticsearch()`, `kafka()` |
| **Log** | Связывает source → filter → destination | `log { source(s); filter(f); destination(d); };` |

### Иерархия конфигурации

- **Глобальный:** `/etc/syslog-ng/syslog-ng.conf`
- **Локальные переопределения:** `/etc/syslog-ng/conf.d/*.conf`
- **Встроенные пути:** `/etc/syslog-ng/scl.d/` (System Configuration Library — готовые блоки)

### Источники (Sources)

```conf
# Системный syslog (аналог imuxsock/imklog в rsyslog)
source s_local {
    system();
    internal();
};

# Сетевой прием (TCP с TLS)
source s_network {
    network(
        ip("0.0.0.0")
        port(6514)
        transport("tls")
        tls(
            cert-file("/etc/syslog-ng/tls/server.crt")
            key-file("/etc/syslog-ng/tls/server.key")
            peer-verify(optional-untrusted)
        )
    );
};

# Чтение файлов (аналог imfile в rsyslog)
source s_nginx {
    file("/var/log/nginx/access.log"
        follow-freq(1)
        flags(no-parse)
    );
};

# Journald (через pipe или socket)
source s_journald {
    systemd-journal(
        prefix(".journald.")
        default-facility(syslog)
    );
};
```

**Основные типы sources:**

| Тип | Описание | Ключевые параметры |
|:---|:---|:---|
| `system()` | Системный syslog + ядро | `default-facility()`, `flags(keep-hostname)` |
| `network()` | Прием по сети (TCP/UDP/TLS) | `ip()`, `port()`, `transport()`, `tls()` |
| `file()` | Чтение текстовых файлов | `follow-freq()`, `flags(no-parse)`, `multi-line()` |
| `pipe()` | Чтение из именованного pipe | `pipe()`, `flags(no-parse)` |
| `program()` | Вывод внешней программы | `program()`, `flags(no-parse)` |

### Назначения (Destinations)

```conf
# Локальный файл с ротацией по дате
destination d_local {
    file("/var/log/remote/${HOST}/${PROGRAM}.log"
        owner("root")
        group("adm")
        perm(0640)
        create_dirs(yes)
    );
};

# Центральный сервер по TCP
destination d_central {
    network("logserver.example.com"
        port(514)
        transport("tcp")
        template("json-template")
        flush_lines(100)
        flush_timeout(1000)
        so_keepalive(yes)
        keep-alive(yes)
    );
};

# Elasticsearch (через HTTP)
destination d_elasticsearch {
    elasticsearch(
        index("syslog-${YEAR}.${MONTH}.${DAY}")
        type("")
        cluster("es-cluster")
        host("localhost:9200")
        template("$(format-json --key * --rekey @timestamp --shift @timestamp)")
    );
};

# Kafka
destination d_kafka {
    kafka(
        bootstrap-servers("kafka1:9092,kafka2:9092")
        topic("syslog-${PROGRAM}")
        template("$(format-json --key *)")
    );
};
```

### Фильтры (Filters)

```conf
# По программе
filter f_nginx { program("nginx"); };
filter f_auth { facility(auth, authpriv); };

# По уровню
filter f_err { level(err, crit, emerg); };
filter f_not_debug { not level(debug); };

# По хосту
filter f_web { host("web0[1-3]"); };

# Комбинированные
filter f_critical_nginx {
    program("nginx") and level(err, crit);
};

# По содержимому (regex)
filter f_sql_errors { match("SQL.*error" value("MESSAGE")); };

# По пользовательским полям
filter f_production { tags("production"); };
```

### Шаблоны (Templates)

```conf
# Текстовый шаблон
template t_text {
    template("${ISODATE} ${HOST} ${PROGRAM}[${PID}]: ${MESSAGE}\n");
    template-escape(no);
};

# JSON шаблон (рекомендуется для modern stacks)
template t_json {
    template('{"@timestamp":"${ISODATE}","host":"${HOST}","program":"${PROGRAM}","severity":"${LEVEL}","facility":"${FACILITY}","message":"${MESSAGE}"}\n');
    template-escape(yes);
};

# Динамический путь
template t_dynamic_path {
    template("/var/log/remote/${HOST}/${YEAR}-${MONTH}-${DAY}/${PROGRAM}.log");
};
```

### Связи (Log)

Связь определяет поток данных: source → filter → destination.

```conf
# Базовая связь
log {
    source(s_local);
    destination(d_local);
};

# С фильтрацией
log {
    source(s_local);
    filter(f_auth);
    destination(d_auth_log);
};

# Цепочка: прочитал → отфильтровал → отправил + записал локально
log {
    source(s_local);
    filter(f_err);
    destination(d_central);
    destination(d_local_err);
    flags(final);  # Прекратить обработку после этого
};
```

**Флаги связей:**

| Флаг | Описание |
|:---|:---|
| `final` | Прекратить обработку после этой связи |
| `fallback` | Использовать только если предыдущие связи не сработали |
| `catch-all` | Перехватить все сообщения, не обработанные ранее |
| `flow-control` | Включить контроль обратного давления (backpressure) |

## Практические сценарии

### Сценарий 1: Центральный syslog-сервер

```conf
# /etc/syslog-ng/syslog-ng.conf

@version: 4.6
@include "scl.conf"

# Источники
source s_local { system(); internal(); };

source s_remote_tcp {
    network(
        ip("0.0.0.0")
        port(514)
        transport("tcp")
        flags(no-parse)
    );
};

source s_remote_tls {
    network(
        ip("0.0.0.0")
        port(6514)
        transport("tls")
        tls(
            cert-file("/etc/syslog-ng/tls/server.crt")
            key-file("/etc/syslog-ng/tls/server.key")
            peer-verify(optional-untrusted)
        )
        flags(no-parse)
    );
};

# Парсинг
parser p_json {
    json-parser(
        prefix("json.")
        template("${MESSAGE}")
    );
};

# Шаблоны
template t_per_host {
    template("/var/log/remote/${HOST}/${YEAR}-${MONTH}-${DAY}/${PROGRAM}.log");
    template-escape(no);
};

template t_json {
    template('{"@timestamp":"${ISODATE}","host":"${HOST}","program":"${PROGRAM}","severity":"${LEVEL}","facility":"${FACILITY}","message":"${MESSAGE}"}\n');
    template-escape(yes);
};

# Назначения
destination d_per_host {
    file("$(template t_per_host)"
        owner("root")
        group("adm")
        perm(0640)
        create_dirs(yes)
    );
};

destination d_json_file {
    file("/var/log/syslog/json/syslog.json"
        template("t_json")
        create_dirs(yes)
    );
};

# Связи
log {
    source(s_remote_tcp);
    source(s_remote_tls);
    destination(d_per_host);
    destination(d_json_file);
    flags(final);
};

log {
    source(s_local);
    destination(d_local);
};
```

### Сценарий 2: Фильтрация и маршрутизация

```conf
# Разделение логов по типам
log {
    source(s_local);
    filter(f_auth);
    destination(d_auth_log);
    flags(final);
};

log {
    source(s_local);
    filter(f_nginx);
    destination(d_nginx_log);
    flags(final);
};

log {
    source(s_local);
    filter(f_err);
    destination(d_error_log);
    destination(d_central);
    flags(final);
};

# Остальное в общий файл
log {
    source(s_local);
    destination(d_general_log);
};
```

### Сценарий 3: Синтаксическая проверка и отладка

```bash
# Проверка конфигурации (аналог rsyslogd -N1)
sudo syslog-ng --syntax-only

# Запуск в foreground с debug-логированием
sudo syslog-ng -Fevd

# Проверка активных правил
sudo syslog-ng-ctl stats

# Принудительная перезагрузка конфигурации
sudo syslog-ng-ctl reload

# Просмотр статистики по source/destination
sudo syslog-ng-ctl query get "*.*"
```

### Сценарий 4: TLS-шифрование (клиент)

```conf
# /etc/syslog-ng/conf.d/99-tls-forward.conf

destination d_tls_central {
    network("logserver.example.com"
        port(6514)
        transport("tls")
        tls(
            cert-file("/etc/syslog-ng/tls/client.crt")
            key-file("/etc/syslog-ng/tls/client.key")
            ca-file("/etc/syslog-ng/tls/ca.crt")
            peer-verify(yes)
            peer-name("logserver.example.com")
        )
        template("t_json")
        flush_lines(100)
        flush_timeout(1000)
        so_keepalive(yes)
    );
};

log {
    source(s_local);
    destination(d_tls_central);
    flags(flow-control);
};
```

### Сценарий 5: Интеграция с journald

```conf
# Сбор логов из systemd-journald
source s_journald {
    systemd-journal(
        prefix(".journald.")
        default-facility(syslog)
    );
};

# Извлечение метаданных
parser p_journald {
    extract-patterns(
        prefix(".journald.")
        pattern-*()
    );
};

log {
    source(s_journald);
    parser(p_journald);
    destination(d_central);
};
```

### Сценарий 6: Disk-buffer для отказоустойчивости

```conf
# Disk-assisted queue для гарантированной доставки
destination d_central_reliable {
    network("logserver.example.com"
        port(514)
        transport("tcp")
        template("t_json")
    );
    disk-buffer(
        mem-buf-size(16m)
        disk-buf-size(2g)
        reliable(yes)
        dir("/var/lib/syslog-ng/buffer")
    );
    flags(flow-control);
    keep-alive(yes);
    retries(5);
    retry-over(max(5));
};

log {
    source(s_local);
    destination(d_central_reliable);
};
```

## Диагностика и устранение неполадок

### Типичные проблемы

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Синтаксическая ошибка** | Неверный формат блока | `syslog-ng --syntax-only -f /etc/syslog-ng/syslog-ng.conf` |
| **Логи не доставляются** | DNS, firewall, TLS | `nc -zv logserver 514`, `openssl s_client -connect logserver:6514` |
| **Disk-buffer переполнен** | Долго недоступен destination | Проверить `/var/lib/syslog-ng/buffer/`, увеличить `disk-buf-size` |
| **Дублирование логов** | Несколько связей без `flags(final)` | Добавить `flags(final)` или `flags(catch-all)` |
| **Высокое потребление RAM** | Большие mem-buf-size | Уменьшить `mem-buf-size`, включить `reliable(no)` |
| **TLS handshake failed** | Неверный cert/key | `openssl x509 -in server.crt -noout -subject -issuer -dates` |

### Мониторинг

```bash
# Статистика по всем компонентам
sudo syslog-ng-ctl stats

# Статистика по конкретному source
sudo syslog-ng-ctl query get "source.s_local.*"

# Проверка очередей
sudo ls -lah /var/lib/syslog-ng/buffer/

# Мониторинг в реальном времени
journalctl -u syslog-ng -f
```

## Сравнение с rsyslog

| Параметр | **syslog-ng** | **rsyslog** |
|:---|:---|:---|
| **Философия** | Чисто декларативная | Гибридная (legacy + RainierScript) |
| **Производительность** | Стабильнее при глубоком парсинге | Лидер в простых сценариях |
| **Многопоточность** | Нативная | Ограниченная |
| **Disk-buffer** | Встроенный с reliable mode | Disk-assisted queue |
| **Дефолт в дистрибутивах** | RHEL (как syslog-ng), SUSE | Debian, Ubuntu |
| **Patterndb** | Мощная система паттернов | mmnormalize (liblognorm) |
| **TLS** | Нативная поддержка | Через gtls (GnuTLS) |
| **Correlation** | Встроенная (correlate()) | Нет нативной |

## Дополнительная информация

### Лучшие практики

1. **Используйте `flags(flow-control)`** для контроля обратного давления при пересылке по сети.
2. **Включайте disk-buffer** для критичных логов — `reliable(yes)` + `disk-buf-size()`.
3. **Шаблонизируйте в JSON** — упрощает интеграцию с ELK/Loki/Vector.
4. **Разделяйте логи по facility** — auth, daemon, local0-7 в отдельные файлы.
5. **Тестируйте конфигурацию** перед перезапуском: `syslog-ng --syntax-only`.
6. **Используйте SCL** (System Configuration Library) — готовые блоки для типовых сценариев.
7. **Настройте `flush_lines` и `flush_timeout`** для оптимизации отправки по сети.
8. **Используйте `create_dirs(yes)`** для автоматического создания подкаталогов.
9. **Включайте `keep-alive(yes)`** для поддержания TCP-соединений.
10. **Мониторьте `syslog-ng-ctl stats`** — количество обработанных/потерянных сообщений.

### См. также

- [Обзор системы логирования](./logging_overview.md)
- [rsyslog: Фильтрация и пересылка](./rsyslog.md)
- [systemd-journald: Сбор и хранение](./journald.md)
