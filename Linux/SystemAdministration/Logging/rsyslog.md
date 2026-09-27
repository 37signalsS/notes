# rsyslog: Фильтрация и пересылка логов

## Определения

**`rsyslog`** (Rocket-fast System for Log Processing) — высокопроизводительная служба для сбора, обработки и пересылки системных журналов. В современных дистрибутивах Linux (RHEL/CentOS 7+, Debian 8+, Ubuntu 14.04+) является стандартным демоном логирования. Основная роль — получение логов от `systemd-journald` ([journald](./journald.md)), их фильтрация, модификация и перенаправление в различные места назначения (файлы, базы данных, удаленные серверы, брокеры сообщений). Протокол syslog описан в [Syslog — протокол системного журналирования](../../../Networking/Protocols/syslog.md).

**Ключевое применение:** построение систем [централизованного логирования](../../../Concepts/Observability_and_Monitoring/observability_definitions.md). Взаимодействие с [journald](./journald.md) и [journalctl](../../Diagnostics/journalctl/journalctl_overview.md) обеспечивает полную видимость состояния системы.

## Основные концепции

### Форматы конфигурации

Rsyslog поддерживает три формата конфигурации, которые могут сосуществовать в одном файле:

1.  **RainierScript (Modern):** Рекомендуемый формат для Rsyslog 7+. Использует блочную структуру, похожую на языки программирования. Обеспечивает лучшую читаемость и расширяемость.
2.  **Advanced (Legacy):** Начинается с символа `$`. Используется для глобальных настроек (например, `$MaxMessageSize`).
3.  **Basic/Traditional (Legacy):** Классический формат `facility.priority action`. Ограничен в возможностях, но прост для базовых правил.

### Архитектура и модули

Rsyslog имеет модульную архитектуру. Модули загружаются директивой `module(load="name")`.

| Тип модуля | Префикс | Назначение | Примеры |
| :--- | :--- | :--- | :--- |
| **Input** | `im` | Сбор логов из источников | `imjournal` (systemd), `imudp`, `imtcp`, `imfile` (чтение текстовых файлов), `imklog` (ядро) |
| **Output** | `om` | Отправка логов | `omfile` (в файл), `omfwd` (по сети), `omelasticsearch`, `omkafka`, `ommysql`, `ommongodb` |
| **Modification** | `mm` | Фильтрация и модификация | `mmjsonparse` (парсинг JSON), `mmnormalize` (структурирование), `mmutf8fix` |
| **Parser** | `pm` | Разбор специфичных форматов | `pmrfc5424`, `pmrfc3164`, `pmlastmsg` |

#### Детализация модулей

**Input:**
| Модуль | Назначение | Ключевые параметры |
| :--- | :--- | :--- |
| `imjournal` | Сбор логов из systemd-journald | `StateFile`, `PersistStateInterval`, `IgnorePreviousMessages` |
| `imfile` | Чтение текстовых файлов (логи приложений) | `File`, `Tag`, `Facility`, `Severity`, `StateFile`, `FreshStartTail`, `readMode` |
| `imklog` | Чтение кольцевого буфера ядра (`/proc/kmsg`) | `ChainKmsg`, `PermitNonKernel`, `KeepKmsgChars` |
| `imudp` | Прием по UDP | `bindAddress`, `port` |
| `imtcp` | Прием по TCP | `bindAddress`, `port` |

**Output:**
| Модуль | Назначение | Ключевые параметры |
| :--- | :--- | :--- |
| `omelasticsearch` | Отправка в Elasticsearch | `server`, `port`, `bulkmode`, `maxRetries`, `retryWaitInterval` |
| `omkafka` | Отправка в Kafka | `broker`, `topic`, `partitionKey`, `partitionAlgo` |
| `ommysql` / `ompgsql` | Запись в базу данных | `server`, `db`, `user`, `pass` |
| `omrelp` | Надежная пересылка по RELP | `target`, `port` |
| `omfile` | Запись в файл | `file`, `dynaFile`, `template`, `ioBufferSize`, `flushOnTXEnd`, `asyncWriting` |
| `omfwd` | Пересылка по сети (UDP/TCP/TLS) | `target`, `port`, `protocol`, `queue.*` |

**Modification:**
| Модуль | Назначение | Ключевые параметры |
| :--- | :--- | :--- |
| `mmjsonparse` | Парсинг JSON-логов | `keepMemory`, `invalidInput`, `escapeControlCharacters` |
| `mmnormalize` | Нормализация через liblognorm | `ruleBase`, `processProps`, `escapeControlCharacters` |
| `mmutf8fix` | Исправление невалидного UTF-8 | `replacementChar` |

**Parser:**
| Модуль | Назначение |
| :--- | :--- |
| `pmrfc5424` | Разбор RFC 5424 |
| `pmrfc3164` | Разбор устаревшего RFC 3164 |
| `pmlastmsg` | Хранение последнего сообщения |

### Действия (Actions)

Действие определяет, что rsyslog делает с сообщением после обработки:

| Действие | Синтаксис | Описание |
| :--- | :--- | :--- |
| **Запись в файл** | `/var/log/file.log` | Стандартное текстовое файловое действие |
| **Динамический файл** | `action(type="omfile" dynaFile="TemplateName")` | Использование шаблона для пути |
| **Пересылка по сети** | `@@host:514` (TCP), `@host:514` (UDP) | TCP двойной `@@`, UDP одинарный `@` |
| **omfwd (современный)** | `action(type="omfwd" target="..." protocol="tcp")` | Расширенная пересылка с очередями |
| **Stop** | `stop` | Прекратить дальнейшую обработку сообщения |
| **Continue** | `continue` | Продолжить к следующим правилам (по умолчанию) |
| **Exec/Shell** | `action(type="ompipe" ...)` или `shell` | Выполнение внешней команды (редко, требует осторожности) |
| **Mail** | `:omusrmsg:user` или `action(type="ommail" ...)` | Отправка уведомлений (требует postfix/sendmail) |

### Шаблоны (Templates)

Шаблоны определяют формат вывода сообщений.

**Встроенные шаблоны:**
- `RSYSLOG_FileFormat` — традиционный текстовый формат
- `RSYSLOG_TraditionalFileFormat` — совместимый с legacy
- `RSYSLOG_SyslogProtocol23Format` — RFC 5424 (рекомендуется для JSON/structured)

**Пользовательские шаблоны:**

**String-шаблон:**
```conf
template(name="MyTemplate" type="string"
         string="%TIMESTAMP% %HOSTNAME% %syslogtag% %msg%\n")
```

**List-шаблон (билдер):**
```conf
template(name="json-template" type="list") {
    constant(value="{")
    constant(value="\"@timestamp\":\"")     property(name="timereported" dateFormat="rfc3339")
    constant(value="\",\"host\":\"")        property(name="hostname")
    constant(value="\",\"severity\":\"")    property(name="syslogseverity-text")
    constant(value="\",\"program\":\"")     property(name="programname")
    constant(value="\",\"message\":\"")     property(name="msg" format="json")
    constant(value="\"}\n")
}
```

**Динамический шаблон:**
```conf
template(name="PerHost" type="string"
         string="/var/log/remote/%HOSTNAME%/%PROGRAMNAME%.log")
```

### Глобальные директивы

Глобальные настройки начинаются с `$` (Legacy) или задаются через `global()` блок (RainierScript).

```conf
# Legacy-формат
$MaxMessageSize 64k
$SystemLogSocketName /dev/log
$SystemLogCatchallLogs on
$CreateMode 0640
$DirMode 0755
$Umask 0022
$PrivDropToUser syslog
$PrivDropToGroup adm

# RainierScript-формат
global(
    maxMessageSize="64k"
    preserveFQDN="on"
    defaultNetstreamDriverCAFile="/etc/ssl/certs/ca-certificates.crt"
)
```

**Ключевые директивы:**
- `$MaxMessageSize` — максимальный размер сообщения (по умолчанию 8k). Увеличьте для JSON или длинных стектрейсов.
- `$SystemLogSocketName` — путь к сокету syslog.
- `$PrivDropToUser` / `$PrivDropToGroup` — пользователь/группа, от имени которых работает rsyslog после старта.
- `$CreateMode` / `$DirMode` / `$Umask` — права на создаваемые файлы и директории.

### Очереди (Queues)

Очереди обеспечивают асинхронную обработку и отказоустойчивость. Обязательны для remote logging в production.

```conf
# Глобальная очередь (все действия)
main_msg_queue(
    queue.workerthreads="4"
    queue.dequeueBatchSize="2048"
    queue.maxDiskSpace="2g"
    queue.saveOnShutdown="on"
)

# Очередь для конкретного действия
action(
    type="omfwd"
    target="logserver.example.com"
    port="514"
    protocol="tcp"
    queue.type="LinkedList"
    queue.size="50000"
    queue.filename="fwdRule"
    queue.maxDiskSpace="2g"
    queue.saveOnShutdown="on"
    action.resumeRetryCount="-1"
)
```

**Типы очередей:**
| Тип | Описание | Использование |
| :--- | :--- | :--- |
| `LinkedList` | В памяти, динамическая | Высокая скорость, риск потери при падении |
| `FixedArray` | В памяти, фиксированный размер | Предсказуемое потребление RAM |
| `Disk Queue` | На диске (persistent) | Критично для compliance, гарантированная доставка |

**Основные параметры:**
- `queue.size` — максимальное количество сообщений в очереди
- `queue.filename` — префикс файлов для disk-assisted режима
- `queue.maxDiskSpace` — лимит места на диске для очереди
- `queue.workerthreads` — количество потоков обработки
- `queue.dequeueBatchSize` — размер пачки для обработки
- `queue.saveOnShutdown` — сохранять очередь при остановке rsyslog
- `action.resumeRetryCount` — количество попыток переподключения (`-1` = бесконечно)

### Потоки (Streams) и TLS

Rsyslog использует модули `streamdriver` для управления TLS-соединениями.

**Поддерживаемые драйверы:**
- `gtls` (GnuTLS) — рекоммендуемый, стабильный
- `nss` (Network Security Services) — устаревший
- `openssl` — экспериментальный

**Пример полной конфигурации TLS:**

```conf
# Загрузка драйвера (RainierScript)
module(load="imtcp" streamDriver.Name="gtls")

# Глобальный доверенный CA
global(
    defaultNetstreamDriverCAFile="/etc/ssl/certs/ca-certificates.crt"
)

# Прием по TLS (сервер)
input(type="imtcp" port="6514" streamDriver.Mode="1" streamDriver.Authmode="x509/name")

# Отправка по TLS (клиент)
action(
    type="omfwd"
    target="remote-log-server"
    port="6514"
    protocol="tcp"
    stream.driver="gtls"
    stream.driver.caFile="/etc/ssl/certs/ca-certificates.crt"
    stream.driver.certFile="/etc/rsyslog/tls/client-cert.pem"
    stream.driver.keyFile="/etc/rsyslog/tls/client-key.pem"
    stream.driver.permittedPeers="remote-log-server"
)
```

**Режимы аутентификации (`streamDriverAuthMode`):**
- `anon` — без аутентификации (только шифрование)
- `x509/name` — проверка CN/SAN сертификата
- `x509/fingerprint` — проверка отпечатка сертификата

### RELP (Reliable Event Logging Protocol)

RELP (RFC 5842) обеспечивает гарантированную доставку каждого сообщения с подтверждением. Решает проблему потерь при разрыве TCP-соединения.

```conf
# Сервер
module(load="imrelp")
input(type="imrelp" port="2514")

# Клиент
module(load="omrelp")
action(type="omrelp" target="logserver.example.com" port="2514")
```

**Применение:** compliance-среды (PCI DSS), где потеря логов недопустима.

### Файлы состояния (StateFile)

Модули, поддерживающие `StateFile`, сохраняют позицию чтения между перезапусками rsyslog. Критично для `imjournal` и `imfile`.

```conf
# imjournal
module(load="imjournal"
       StateFile="/var/lib/rsyslog/imjournal.state"
       PersistStateInterval="1000")

# imfile
input(type="imfile"
      File="/var/log/app/app.log"
      Tag="myapp"
      Facility="local0"
      Severity="info"
      StateFile="myapp-app"
      FreshStartTail="on")
```

**Параметры:**
- `StateFile` — путь к файлу состояния (должен быть уникальным для каждого input)
- `PersistStateInterval` — интервал записи состояния в секунды
- `FreshStartTail` — при первом запуске читать с конца файла (а не с начала)
- `readMode` — `0` (polling), `1` (inotify)

### Конфигурация и фильтрация

**Файлы конфигурации:**
- Главный: `/etc/rsyslog.conf`
- Дополнительные: `/etc/rsyslog.d/*.conf` (загружаются через `include(file="/etc/rsyslog.d/*.conf")`)

#### Традиционная фильтрация
**Структура правила:** `источник.приоритет   действие`

| Компонент | Описание | Примеры |
| :--- | :--- | :--- |
| **Facility (источник)** | Категория (подсистема) | `auth`, `authpriv` (безопасность), `cron`, `kern` (ядро), `mail`, `daemon`, `user`, `local0-7` |
| **Priority (уровень)** | Важность сообщения | `info`, `warning`, `err`, `crit`, `*` (любой), `none` (исключить) |
| **Action (действие)** | Куда отправить | `/var/log/file`, `@host` (UDP), `@@host` (TCP), `:omusrmsg:user` |

**Примеры:**
```conf
# Все сообщения безопасности в отдельный файл
auth,authpriv.*                 /var/log/auth.log

# Логи демонов и почты (уровня info и выше), кроме cron
daemon,mail.info;cron.none      -/var/log/syslog
```

#### Современная фильтрация (Property-based и RainierScript)

Позволяет фильтровать по любому свойству сообщения (текст, имя программы, хост).

**Синтаксис (Property-based):** `:свойство, [оператор], "значение" действие`
- `:msg, contains, "error" /var/log/errors.log` — поиск текста в сообщении.
- `:programname, isequal, "nginx" /var/log/nginx-system.log` — фильтрация по имени приложения.

**Синтаксис (RainierScript):**
```conf
if $programname == 'app' or $msg contains 'critical' then {
    action(type="omfile" file="/var/log/app_critical.log")
}
```

### Уровни приоритета (RFC 5424)

Уровни серьезности (severity) и facility определены в протоколе syslog. Подробное описание с расчетом PRI и примерами см. в [Syslog — протокол системного журналирования](../../../Networking/Protocols/syslog.md#severity-важность-сообщения).

## Практические сценарии

### Настройка удаленного логирования (RainierScript)

#### Сервер (получатель логов)
1.  **Настроить прием логов** (`/etc/rsyslog.d/50-remote.conf`):
    ```conf
    # Загрузка модуля для TCP
    module(load="imtcp")
    input(type="imtcp" port="514")

    # Шаблон для динамических путей: /var/log/remote/HOSTNAME/PROGRAM.log
    template(name="RemoteHostLog" type="string"
             string="/var/log/remote/%HOSTNAME%/%PROGRAMNAME%.log")

    # Сохранение всех удаленных логов по шаблону
    if $fromhost-ip != '127.0.0.1' then {
        action(type="omfile" dynaFile="RemoteHostLog")
        stop # Прекратить обработку, чтобы не писать в локальный syslog
    }
    ```

#### Клиент (отправитель логов) с отказоустойчивой очередью
Для обеспечения надежности в нагруженных средах необходимо использовать очереди (`Action Queue`).

`/etc/rsyslog.d/99-forward.conf`:
```conf
*.* action(type="omfwd"
    target="logserver.example.com"
    port="514"
    protocol="tcp"
    queue.type="LinkedList"       # Динамическая очередь в памяти
    queue.size="50000"            # Максимальное количество сообщений
    queue.dequeueBatchSize="1024" # Размер пачки для обработки
    queue.filename="fwdRule"      # Включает "disk-assisted" режим (сброс на диск при переполнении RAM)
    queue.maxDiskSpace="2g"       # Лимит места на диске
    queue.saveOnShutdown="on"     # Сохранять очередь при перезагрузке rsyslog
    action.resumeRetryCount="-1"  # Бесконечные попытки переподключения
)
```

**UDP против TCP для пересылки логов:**
- **UDP (один `@`):** Низкие задержки, риск потери данных при нагрузке.
- **TCP (двойной `@@`):** Гарантированная доставка. Обязательно для аудита и комплаенса.

### Форматирование в JSON (для ELK/Loki)
Современные системы анализа предпочитают структурированный формат.

```conf
template(name="json-template" type="list") {
    constant(value="{")
    constant(value="\"@timestamp\":\"")     property(name="timereported" dateFormat="rfc3339")
    constant(value="\",\"host\":\"")        property(name="hostname")
    constant(value="\",\"severity\":\"")    property(name="syslogseverity-text")
    constant(value="\",\"facility\":\"")    property(name="syslogfacility-text")
    constant(value="\",\"program\":\"")     property(name="programname")
    constant(value="\",\"message\":\"")     property(name="msg" format="json")
    constant(value="\"}\n")
}

# Отправка в файл или по сети в формате JSON
*.* action(type="omfile" file="/var/log/syslog.json" template="json-template")
```

### Нормализация данных (mmnormalize)
Используется для преобразования неструктурированного текста в JSON-объекты на лету (на базе `liblognorm`).

1.  **Создать файл правил** (`/etc/rsyslog.d/app.rulebase`):
    ```text
    rule=:%date:date-rfc3164% %host:word% %tag:word%[%pid:number%]: %message:rest%
    ```
2.  **Применение в конфигурации:**
    ```conf
    module(load="mmnormalize")
    if $programname == 'my_app' then {
        action(type="mmnormalize" ruleBase="/etc/rsyslog.d/app.rulebase")
    }
    ```

### Безопасная передача через TLS
Шифрование и аутентификация клиента и сервера. Требуется пакет `rsyslog-gnutls`.

```conf
# Пример конфигурации клиента
action(type="omfwd"
       target="remote-log-server"
       port="6514"
       protocol="tcp"
       StreamDriver="gtls"
       StreamDriverMode="1"
       StreamDriverAuthMode="x509/name"
       StreamDriverPermittedPeers="remote-log-server"
)
```

### Мониторинг логов приложений через imfile

Модуль `imfile` позволяет rsyslog читать текстовые логи приложений, не требующих syslog-интеграции (nginx, Apache, кастомные приложения).

```conf
# /etc/rsyslog.d/30-imfile.conf
module(load="imfile")

# Nginx access log
input(type="imfile"
      File="/var/log/nginx/access.log"
      Tag="nginx:access"
      Facility="local0"
      Severity="info"
      StateFile="nginx-access"
      FreshStartTail="on"
      readMode="1")

# Nginx error log
input(type="imfile"
      File="/var/log/nginx/error.log"
      Tag="nginx:error"
      Facility="local0"
      Severity="err"
      StateFile="nginx-error"
      FreshStartTail="on")

# Кастомное приложение
input(type="imfile"
      File="/opt/myapp/logs/app.log"
      Tag="myapp"
      Facility="local1"
      Severity="info"
      StateFile="myapp"
      readMode="0"
      maxLinesAtOnce="5000")

# Маршрутизация
if $programname == 'nginx:access' then {
    action(type="omfile" file="/var/log/rsyslog/nginx-access.log")
    stop
}
if $programname == 'nginx:error' then {
    action(type="omfile" file="/var/log/rsyslog/nginx-error.log")
    stop
}
if $programname == 'myapp' then {
    action(type="mmnormalize" ruleBase="/etc/rsyslog.d/app.rulebase")
    action(type="omfile" file="/var/log/rsyslog/myapp-structured.log")
    stop
}
```

**Валидация:**
```bash
sudo rsyslogd -N1
# → rsyslogd: End of config validation run.

# Проверка чтения файла
sudo tail -f /var/log/rsyslog/nginx-access.log
```

### Централизованный syslog-сервер

Прием логов от 100+ хостов с маршрутизацией по хостам и программам.

```conf
# /etc/rsyslog.d/50-remote.conf

# Загрузка модулей
module(load="imtcp")
module(load="imudp")

# Прием по TCP (рекомендуется)
input(type="imtcp" port="514")

# Прием по UDP (для легковесных устройств)
input(type="imudp" port="514")

# Шаблон для динамических путей
template(name="PerHost" type="string"
         string="/var/log/remote/%HOSTNAME%/%PROGRAMNAME%.log")

# Маршрутизация удаленных сообщений
if $fromhost-ip != '127.0.0.1' then {
    action(type="omfile" dynaFile="PerHost")
    stop
}
```

**Настройка клиента:**
```conf
# /etc/rsyslog.d/99-forward.conf
# Отправка всех локальных логов на центральный сервер
*.* @@logcentral.example.com:514

# Или только security-логи
auth,authpriv.* @@logcentral.example.com:514
```

### Логирование событий безопасности

Отдельная ротация и retention для auth/security событий.

```conf
# /etc/rsyslog.d/10-auth-security.conf

# Auth и authpriv в отдельный файл
auth,authpriv.*                 /var/log/auth.log

# Sudo-события
:programname, isequal, "sudo"   /var/log/sudo/sudo.log

# SSH-события
:programname, isequal, "sshd"   /var/log/ssh/sshd.log

# Ограничение доступа
$FileOwner root
$FileGroup adm
$FileCreateMode 0640
$DirCreateMode 0750
$Umask 0027

# Ротация через logrotate (см. ниже)
```

### Ротация логов через logrotate

Rsyslog работает с текстовыми файлами в `/var/log/`. Ротация обеспечивается `logrotate`.

```conf
# /etc/logrotate.d/rsyslog-custom
/var/log/rsyslog/*.log {
    daily
    missingok
    rotate 90
    compress
    delaycompress
    notifempty
    create 0640 root adm
    sharedscripts
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate 2>/dev/null || systemctl restart rsyslog >/dev/null 2>&1 || true
    endscript
}

/var/log/auth.log /var/log/sudo/sudo.log {
    daily
    missingok
    rotate 365
    compress
    delaycompress
    notifempty
    create 0640 root adm
    sharedscripts
    postrotate
        /usr/lib/rsyslog/rsyslog-rotate 2>/dev/null || systemctl restart rsyslog >/dev/null 2>&1 || true
    endscript
}
```

**Валидация:**
```bash
sudo logrotate -d /etc/logrotate.d/rsyslog-custom
# → Dry run, проверка без применения
```

### Интеграция с локальным SIEM

#### Wazuh (локальный агент)
Wazuh может собирать логи напрямую из файлов или через syslog-агент.

```xml
<!-- /var/ossec/etc/ossec.conf -->
<ossec_config>
  <localfile>
    <location>/var/log/rsyslog/nginx-access.log</location>
    <log_format>syslog</log_format>
  </localfile>
  <localfile>
    <location>/var/log/auth.log</location>
    <log_format>syslog</log_format>
  </localfile>
</ossec_config>
```

#### ELK Stack (локальный)
Filebeat для сбора rsyslog-логов:

```yaml
# /etc/filebeat/filebeat.yml
filebeat.inputs:
  - type: log
    enabled: true
    paths:
      - /var/log/rsyslog/*.log
      - /var/log/remote/*/*.log
    fields:
      service: syslog
      environment: production
    fields_under_root: true

output.elasticsearch:
  hosts: ["http://localhost:9200"]
  index: "rsyslog-%{+yyyy.MM.dd}"
```

**Валидация:**
```bash
sudo filebeat test output
# → 1  GET elasticsearch/_cluster/health ... [status: 200 OK]
```

### Безопасность и защита логов

```conf
# /etc/rsyslog.d/99-security.conf

# Права на создаваемые файлы
$FileOwner root
$FileGroup adm
$FileCreateMode 0640
$DirCreateMode 0750
$Umask 0027

# Drop root privileges после старта
$PrivDropToUser syslog
$PrivDropToGroup adm

# Ограничение доступа к конфигурации
$IncludeConfig /etc/rsyslog.conf
$IncludeConfig /etc/rsyslog.d/*.conf

# Защита от подделки (в связке с auditd)
# Необходимо включить immutable-бит на критические логи
```

**Immutable-бит (дополнительная защита):**
```bash
# Требует auditd или hand-настройка
sudo chattr +i /var/log/auth.log /var/log/secure /var/log/sudo/sudo.log
# → Файл становится нередактируемым даже для root
```

### Соответствие стандартам (Compliance)

**PCI DSS v4.0.1:**
- Требование 10: Логи всех событий безопасности (auth, sudo, ssh) должны собираться и храниться не менее 1 года (3 месяца доступны немедленно).
- Требование 10.3.1: Ведение логов всех событий безопасности.

**CIS Benchmarks:**
- Проверка: rsyslog установлен и запущен
- Проверка: настроены базовые правила для `/etc/rsyslog.conf` и `/etc/rsyslog.d/`
- Проверка: пересылка на центральный сервер настроена
- Проверка: логи auth и security хранятся отдельно

**Валидация:**
```bash
# Проверка: rsyslog активен
sudo systemctl is-active rsyslog
# → active

# Проверка: базовые правила присутствуют
sudo rsyslogd -N1 | grep -c "auth"
# → > 0

# Проверка: пересылка настроена
sudo rsyslogd -N1 | grep -c "@@"
# → > 0
```

### Disaster Recovery и восстановление после сбоя

```bash
# 1. Проверка статуса службы
sudo systemctl status rsyslog

# 2. Проверка конфигурации
sudo rsyslogd -N1

# 3. Проверка очередей (disk-assisted)
sudo ls -la /var/spool/rsyslog/
# → fwdRule*

# 4. Проверка прав доступа
sudo ls -la /var/log/
sudo ls -la /etc/rsyslog.d/

# 5. Восстановление из бэкапа конфигурации
sudo cp /etc/rsyslog.d/99-backup.conf /etc/rsyslog.d/
sudo systemctl restart rsyslog

# 6. Проверка логов
sudo tail -f /var/log/syslog | grep rsyslog
```

### Ansible: автоматизация развертывания

```yaml
# tasks/main.yml
- name: Ensure rsyslog is installed
  package:
    name: rsyslog
    state: present

- name: Deploy rsyslog configuration
  copy:
    src: rsyslog.conf
    dest: /etc/rsyslog.conf
    owner: root
    group: root
    mode: '0644'
  notify: restart rsyslog

- name: Deploy additional rules
  copy:
    src: "{{ item }}"
    dest: "/etc/rsyslog.d/{{ item }}"
    owner: root
    group: root
    mode: '0644'
  loop:
    - 10-auth.conf
    - 30-remote.conf
    - 99-security.conf
  notify: restart rsyslog

- name: Ensure rsyslog is started and enabled
  service:
    name: rsyslog
    state: started
    enabled: yes
```

```yaml
# handlers/main.yml
- name: restart rsyslog
  service:
    name: rsyslog
    state: restarted
```

## Настройка и оптимизация

### Тюнинг производительности (High Load)
На высоконагруженных системах стандартные настройки могут привести к потере логов или зависанию приложений.

- **Асинхронная запись:** Использование больших буферов для записи на диск.
  `action(type="omfile" ioBufferSize="128k" flushOnTXEnd="off" asyncWriting="on")`
- **Многопоточность:** Распараллеливание обработки очередей.
  `main_queue(queue.workerthreads="4" queue.dequeueBatchSize="2048")`
- **Размер сообщения:** Увеличение лимита для JSON-логов или длинных стектрейсов.
  `$MaxMessageSize 64k`

### Интеграция с systemd-journald
По умолчанию `rsyslog` забирает сообщения из сокета `journald`.
```conf
module(load="imjournal" 
       PersistStateInterval="1000" 
       StateFile="/var/lib/rsyslog/imjournal.state")
```
*Для снижения нагрузки можно установить `ForwardToSyslog=no` в `journald.conf`.*

### Тюнинг производительности rsyslog

```bash
# 1. Установка idle I/O priority для фоновой записи
sudo ionice -c 3 -p $(pgrep -f rsyslogd)

# 2. Systemd override для IOSchedulingClass
# /etc/systemd/system/rsyslog.service.d/override.conf
[Service]
IOSchedulingClass=idle
IOSchedulingPriority=7
LimitNOFILE=65536

# 3. Применение
sudo systemctl daemon-reload
sudo systemctl restart rsyslog

# 4. Валидация
sudo systemctl show rsyslog -p IOSchedulingClass,IOSchedulingPriority,LimitNOFILE
# → IOSchedulingClass=idle, IOSchedulingPriority=7, LimitNOFILE=65536
```

**Дополнительные параметры производительности:**
- Увеличение `$MaxMessageSize` до `64k` для JSON-логов
- Настройка `queue.workerthreads="4"` для многопоточности
- Использование `asyncWriting="on"` и `ioBufferSize="128k"` для omfile
- Мониторинг `iostat -xz 1 5` для контроля задержек записи

## Диагностика и устранение неполадок

> Для общей методологии диагностики логирования (journald, rsyslog, агенты) см. [Диагностика и устранение неполадок логирования](../../Diagnostics/Troubleshooting/logging_troubleshooting.md).

### Тестирование и проверка
```bash
# Проверка синтаксиса конфигурации (КРИТИЧНО перед перезапуском)
sudo rsyslogd -N1
# → rsyslogd: End of config validation run.

# Отправить тестовое сообщение
logger -t test_tag "Test message for rsyslog"

# Просмотр ошибок самой службы
journalctl -u rsyslog -f
```

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Логи не записываются** | Ошибки прав доступа | `chown syslog:adm /var/log/*.log` (на Debian/Ubuntu) |
| **Дублирование логов** | Активна пересылка из journald | Установить `ForwardToSyslog=no` в `/etc/systemd/journald.conf` |
| **Потеря логов по UDP** | Переполнение буфера ядра | Увеличить `net.core.rmem_max` через sysctl |
| **Файлы не ротируются** | Ошибка в `logrotate` | Убедиться, что `logrotate` посылает `SIGHUP` в `rsyslog` |
| **Высокая нагрузка на CPU** | Слишком сложная фильтрация | Оптимизировать правила, использовать `stop` для исключения лишних проверок |
| **Потеря логов при переполнении очереди** | `queue.size` слишком мал или диск заполнен | Увеличить `queue.size`, настроить `queue.maxDiskSpace`, мониторить `/var/spool/rsyslog/` |
| **TLS handshake failed** | Неверный сертификат или CA | Проверить `openssl s_client -connect host:6514`, права на ключи, `StreamDriverPermittedPeers` |
| **Lost events растет** | Буфер ядра или disk queue переполнен | Увеличить `net.core.rmem_max`, `queue.maxDiskSpace`, проверить скорость записи диска |
| **imfile не читает файл** | Неверный путь или права | Проверить `readMode`, права на файл, `StateFile` уникален, `FreshStartTail` |
| **imjournal пропускает сообщения** | `IgnorePreviousMessages=on` или поврежден StateFile | Проверить `PersistStateInterval`, удалить StateFile для перечитывания |
| **Дублирование через omfile** | Несколько правил с `stop` отсутствует | Добавить `stop` после действия или использовать `discard` для исключения |
| **Высокое потребление памяти** | Слишком большие очереди в RAM | Перейти на `queue.type="Disk Queue"` или уменьшить `queue.size` |
| **Логи не доставляются при перезагрузке** | `queue.saveOnShutdown="off"` | Включить `queue.saveOnShutdown="on"` для disk-assisted очередей |

### Диагностика очередей

```bash
# Проверка наличия disk-assisted очередей
sudo ls -lah /var/spool/rsyslog/
# → fwdRule* (файлы очереди)

# Мониторинг размера очереди
sudo du -sh /var/spool/rsyslog/

# Проверка потерь в логах rsyslog
sudo grep -i "lost" /var/log/syslog | tail -n 20
# → lost 0 (норма), lost 142 (проблема)

# Проверка статуса очереди через imjournal
sudo journalctl -u rsyslog | grep -i "queue"
```

### Диагностика TLS

```bash
# Проверка handshake
openssl s_client -connect logserver.example.com:6514 -CAfile /etc/ssl/certs/ca-certificates.crt
# → Verify return code: 0 (ok)

# Проверка сертификата сервера
echo | openssl s_client -connect logserver.example.com:6514 2>/dev/null | openssl x509 -noout -subject -issuer -dates

# Проверка слушающих портов
sudo ss -tnlp | grep -E "514|6514"
# → LISTEN 0 25 *:6514 *:* users:(("rsyslogd",pid=1234,fd=5))
```

### Диагностика imfile/imjournal

```bash
# Проверка imfile: какие файлы читаются
sudo rsyslogd -N1 | grep -i "imfile"
# → imfile: Loaded 3 file monitors

# Проверка imjournal: статус
sudo rsyslogd -N1 | grep -i "imjournal"
# → imjournal: StateFile /var/lib/rsyslog/imjournal.state

# Проверка прав на StateFile
sudo ls -la /var/lib/rsyslog/imjournal.state
# → -rw-r----- 1 root adm ...

# Проверка уникальности StateFile для imfile
sudo grep -r "StateFile" /etc/rsyslog.d/
# → Должен быть уникальным для каждого input
```

## Дополнительная информация

### Сравнение: rsyslog vs syslog-ng

| Параметр | **rsyslog** | **syslog-ng** |
| :--- | :--- | :--- |
| **Философия** | Гибридная (legacy + RainierScript) | Чисто декларативная |
| **Производительность** | Лидер в простых сценариях | Стабильнее при глубоком парсинге |
| **Стандарт** | Дефолт в RHEL, Ubuntu, Debian | Часто используется как центральный агрегатор |

### Лучшие практики

1.  **Очереди для remote logging:** Всегда используйте очереди (`queue.type`, `queue.filename`) при пересылке по сети. Без очереди потеря сообщений при разрыве соединения неизбежна.
2.  **Disk-assisted режим:** Для compliance-сред включайте `queue.filename` + `queue.saveOnShutdown="on"` для гарантированной доставки.
3.  **TLS для пересылки:** Используйте `protocol="tcp"` + `stream.driver="gtls"` для защиты данных в transit. Обязательно для PCI DSS и аналогичных стандартов.
4.  **Разделение логов безопасности:** Auth, sudo, ssh логи хранятся в отдельных файлах с обособленной ротацией (минимум 1 год) и правами `0640 root:adm`.
5.  **Валидация перед применением:** Всегда выполняйте `sudo rsyslogd -N1` перед перезапуском. Используйте `logrotate -d` для dry-run ротации.
6.  **Права и привилегии:** Настройте `$PrivDropToUser syslog` и `$PrivDropToGroup adm`. Файлы логов должны создаваться с `$FileCreateMode 0640`.
7.  **Мониторинг здоровья:** Настройте алертинг на ошибки `lost`, рост очередей в `/var/spool/rsyslog/`, падение `rsyslog.service`.
8.  **Ротация:** Используйте `logrotate` с `postrotate`, вызывающим `systemctl kill -s HUP rsyslog` или `/usr/lib/rsyslog/rsyslog-rotate`. Избегайте `copytruncate` для активных логов.
9.  **SELinux/AppArmor:** Убедитесь, что контексты SELinux не блокируют запись в новые пути (`ausearch -m avc -ts recent`).
10. **Файлы состояния:** Используйте уникальные `StateFile` для `imfile` и `imjournal` на отдельном разделе (например, `/var/lib/rsyslog/`).

### Безопасность и защита логов

```conf
# /etc/rsyslog.d/99-hardening.conf

# Отключение ненужных функций
$ModLoad all # не использовать в production

# Ограничение прав
$FileOwner root
$FileGroup adm
$FileCreateMode 0640
$DirCreateMode 0750
$Umask 0027

# Drop privileges
$PrivDropToUser syslog
$PrivDropToGroup adm

# Ограничение доступа к конфигурации
$IncludeConfig /etc/rsyslog.conf
$IncludeConfig /etc/rsyslog.d/*.conf
```

**Защита от модификации:**
```bash
# Установка immutable-бита на критические логи (дополнительная защита)
sudo chattr +i /var/log/auth.log /var/log/secure /var/log/sudo/sudo.log /var/log/audit/audit.log

# Проверка целостности через auditd (если установлен)
sudo ausearch -f /var/log/auth.log -i | grep "write"
```

**Проверка целостности логов:**
```bash
# Хэширование логов для проверки целостности
sudo sha256sum /var/log/auth.log > /var/log/auth.log.sha256

# Проверка
sudo sha256sum -c /var/log/auth.log.sha256
# → /var/log/auth.log: OK
```

**SELinux/AppArmor:**
```bash
# Проверка denial'ов
sudo ausearch -m avc -ts recent
sudo dmesg | grep -i "audit.*denied.*rsyslog"

# Временное разрешение (для тестирования)
sudo ausearch -m avc -ts recent | audit2allow -M my-rsyslog
sudo semodule -i my-rsyslog.pp
```

### Интеграция с loki (локально)

Для локальных сред без облака можно использовать Promtail или Vector для доставки rsyslog-логов в Loki.

```conf
# /etc/promtail/config.yml
server:
  http_listen_port: 9080
  grpc_listen_port: 0

positions:
  filename: /tmp/positions.yaml

clients:
  - url: http://localhost:3100/loki/api/v1/push

scrape_configs:
  - job_name: rsyslog
    static_configs:
      - targets:
          - localhost
        labels:
          job: rsyslog
          __path__: /var/log/rsyslog/*.log
          __path__: /var/log/remote/*/*.log
```

### См. также
- [Обзор логирования в Linux](./logging_overview.md)
- [Syslog — протокол системного журналирования](../../../Networking/Protocols/syslog.md)
- [systemd-journald: Сбор и хранение](./journald.md)
- [journalctl: Обзор и концепции](../../Diagnostics/journalctl/journalctl_overview.md)
- [Диагностика и устранение неполадок логирования](../../Diagnostics/Troubleshooting/logging_troubleshooting.md)
- [auditd: Аудит событий безопасности](../Logging/auditd.md)
- [logrotate: Ротация и сжатие](./logrotate.md)
- [Vector: современная альтернатива](../../../Vector/vector_overview.md)
