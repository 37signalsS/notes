# rsyslog: Фильтрация и пересылка логов

## Определения

**`rsyslog`** (Rocket-fast System for Log Processing) — высокопроизводительная служба для сбора, обработки и пересылки системных журналов. В современных дистрибутивах Linux (RHEL/CentOS 7+, Debian 8+, Ubuntu 14.04+) является стандартным демоном логирования. Основная роль — получение логов от `systemd-journald`, их фильтрация, модификация и перенаправление в различные места назначения (файлы, базы данных, удаленные серверы, брокеры сообщений).

**Ключевое применение:** построение систем [централизованного логирования](../../../Concepts/Observability_and_Monitoring/observability_definitions.md). Взаимодействие с [journald](./journald.md) и [journalctl](../../Diagnostics/journalctl/journalctl_overview.md) описано в соответствующих файлах. Общий обзор — в [обзоре логирования](./logging_overview.md).

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
| **Output** | `om` | Отправка логов | `omfile` (в файл), `omfwd` (по сети), `omelasticsearch`, `omkafka`, `ommysql` |
| **Filter** | `fm` | Фильтрация и модификация | `fmhash`, `fmlookup` |
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

#### Современная фильтрация (Property-based)

Позволяет фильтровать по любому свойству сообщения (текст, имя программы, хост).

**Синтаксис:** `:свойство, [оператор], "значение" действие`

- `:msg, contains, "error" /var/log/errors.log` — поиск текста в сообщении.
- `:programname, isequal, "nginx" /var/log/nginx-system.log` — фильтрация по имени приложения.
- `if $programname == 'app' then /var/log/app.log` — формат RainierScript.

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

2.  **Перезапуск и открытие порта:**
    ```bash
    sudo systemctl restart rsyslog
    sudo firewall-cmd --add-port=514/tcp --permanent && sudo firewall-cmd --reload
    # → success
    ```

#### Клиент (отправитель логов) с очередью (`Action Queue`)

Очереди позволяют накапливать логи на диске, если сервер логов временно недоступен.

`/etc/rsyslog.d/99-forward.conf`:
```conf
action(type="omfwd"
       target="remote-log-server"
       port="514"
       protocol="tcp"
       # Настройка очереди
       queue.type="LinkedList"       # Тип очереди в памяти
       queue.filename="fwd_queue"    # Имя файла для сброса на диск
       queue.maxdiskspace="1g"       # Макс. место на диске
       queue.saveonshutdown="on"     # Сохранять при выключении
       action.resumeRetryCount="-1"  # Бесконечные попытки переподключения
)
```

### Безопасная передача через TLS

Для шифрования трафика между клиентом и сервером.

1.  **Установить пакет:** `sudo apt install rsyslog-gnutls` (или `rsyslog-openssl`).
2.  **Настройка сервера:**
    ```conf
    module(load="imtcp" StreamDriver.Name="gtls" StreamDriver.Mode="1")
    $DefaultNetstreamDriverCAFile /etc/ssl/certs/ca.pem
    $DefaultNetstreamDriverCertFile /etc/ssl/certs/server-cert.pem
    $DefaultNetstreamDriverKeyFile /etc/ssl/private/server-key.pem
    input(type="imtcp" port="6514")
    ```
3.  **Настройка клиента:**
    ```conf
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

### Интеграция с systemd-journald

По умолчанию `rsyslog` забирает сообщения из сокета `journald`.

1.  **Загрузить модуль `imjournal`** (`/etc/rsyslog.conf`):
    ```conf
    module(load="imjournal" 
           PersistStateInterval="100" 
           StateFile="/var/lib/rsyslog/imjournal.state")
    ```
2.  **Отключить дублирование** (необязательно): Если `rsyslog` пишет в `/var/log/syslog`, можно отключить аналогичный вывод в `journald.conf` (`ForwardToSyslog=no`), чтобы снизить нагрузку.

### Тестирование и диагностика

```bash
# Проверка синтаксиса конфигурации (критично перед перезапуском)
sudo rsyslogd -N1
# → rsyslogd: version 8.x, config validation run (N1)
# → rsyslogd: End of config validation run.

# Отправить тестовое сообщение с тегом
logger -t test_script "Тестовое сообщение"

# Проверить попадание в лог в реальном времени
tail -f /var/log/syslog | grep test_script

# Проверка очереди (если настроена)
ls -lh /var/lib/rsyslog/fwd_queue*
```

### Отладка проблем

```bash
# Включить отладочный режим (временная остановка службы)
sudo systemctl stop rsyslog
sudo rsyslogd -dn > /tmp/rsyslog_debug.log 2>&1

# Проверить открытые порты (TCP/UDP)
ss -tulpn | grep rsyslog

# Просмотр ошибок самой службы rsyslog
journalctl -u rsyslog -f
```

## Дополнительная информация

### Оптимизация производительности

Для систем с высокой нагрузкой (High Load):
- **Batch Size:** Увеличение количества сообщений, обрабатываемых за один раз.
  `action(type="omfile" ... action.reportsstats="on" queue.checkpointinterval="100")`
- **Threads:** Использование нескольких потоков для записи или пересылки.
  `action(type="omfwd" ... queue.workerthreads="4")`
- **Асинхронная запись:** Использование `-` перед путем к файлу (legacy) или `ioBufferSize` в RainierScript.

### Типичные проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Логи не записываются** | Неправильные права или владелец | `chown syslog:adm /var/log/*.log` (Debian) или `root:root` (RHEL) |
| **Порт 514 закрыт** | SELinux или AppArmor блокируют порт | `semanage port -a -t syslogd_port_t -p tcp 514` |
| **Дублирование логов** | `journald` и `rsyslog` пишут одно и то же | Установить `ForwardToSyslog=no` в `/etc/systemd/journald.conf` |
| **Потеря логов по UDP** | Переполнение буфера сокета UDP | Увеличить `net.core.rmem_max` через `sysctl` или перейти на TCP |
| **Файлы не ротируются** | Конфликт с `logrotate` | Убедиться, что `logrotate` посылает `SIGHUP` в `rsyslog` после ротации |

### Связанные темы

- [Обзор логирования в Linux](./logging_overview.md)
- [systemd-journald: Сбор и хранение](./journald.md)
- [journalctl: Диагностика и чтение](../../Diagnostics/journalctl/journalctl_overview.md)
- [Централизованное логирование Docker](../../../Docker/Docker_logs/docker_centralized_logging.md)
