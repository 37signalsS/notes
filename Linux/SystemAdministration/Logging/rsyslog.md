# rsyslog: Фильтрация и пересылка логов

## Определения

**`rsyslog`** (Rocket-fast System for Log Processing) — высокопроизводительная служба для сбора, обработки и пересылки системных журналов. В современных дистрибутивах Linux (RHEL/CentOS 7+, Debian 8+, Ubuntu 14.04+) является стандартным демоном логирования. Основная роль — получение логов от `systemd-journald`, их фильтрация, модификация и перенаправление в различные места назначения (файлы, базы данных, удаленные серверы, брокеры сообщений).

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

| Код | Уровень | Описание |
| :--- | :--- | :--- |
| 0 | `emerg` | Система неработоспособна |
| 1 | `alert` | Требуется немедленное действие |
| 2 | `crit` | Критические условия |
| 3 | `err` | Ошибки |
| 4 | `warning` | Предупреждения |
| 5 | `notice` | Нормальные, но значимые события |
| 6 | `info` | Информационные сообщения |
| 7 | `debug` | Отладочные сообщения |

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

## Диагностика и устранение неполадок

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

## Дополнительная информация

### Сравнение: rsyslog vs syslog-ng

| Параметр | **rsyslog** | **syslog-ng** |
| :--- | :--- | :--- |
| **Философия** | Гибридная (legacy + RainierScript) | Чисто декларативная |
| **Производительность** | Лидер в простых сценариях | Стабильнее при глубоком парсинге |
| **Стандарт** | Дефолт в RHEL, Ubuntu, Debian | Часто используется как центральный агрегатор |

### См. также
- [Обзор логирования в Linux](./logging_overview.md)
- [systemd-journald: Сбор и хранение](./journald.md)
- [journalctl: Диагностика и чтение](../../Diagnostics/journalctl/journalctl_overview.md)
- [Vector: современная альтернатива](../../../Vector/vector_overview.md)
