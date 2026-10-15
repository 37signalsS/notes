# Zabbix — мониторинг Windows

**Актуально для:** Zabbix 7.0 LTS / 7.4

## Определения

* **Zabbix agent for Windows** — сборка классического агента под Windows (служба `Zabbix Agent`), работающая с теми же ключами, что и на Unix, плюс Windows-специфичные.
* **Zabbix Agent 2 for Windows** — сборка Agent 2 (Go), рекомендованный вариант для новых развёртываний; служба `Zabbix Agent 2`.
* **Perf Counter** — счётчик производительности Windows (Performance Monitor). В Zabbix читается ключом `perf_counter[...]`.
* **WMI (Windows Management Instrumentation)** — интерфейс управления Windows; в Zabbix доступен через ключ `wmi.get`.
* **Event Log** — журнал событий Windows (`Application`, `System`, `Security`, а также каналы приложений). Мониторится ключом `eventlog[...]` только активной проверкой.
* **Служба (service)** — Windows-сервис; управляется элементами `service.info[...]`, `service.discovery`, `service.state` и др.

## Основные концепции

### Агент и шаблоны

Как и в Linux, используется связка «агент на хосте + шаблон на сервере». Для Windows официальные шаблоны называются **Windows by Zabbix agent** (пассивный) и **Windows by Zabbix agent active** (активный). Выбор режима — те же принципы, что и для Linux (см. [Режимы работы агентов](./zabbix_agent_checks.md)).

### Специфика ключей

Windows-агент поддерживает:

* `perf_counter[...]` — счётчики производительности (CPU, память, диски, сеть);
* `service.info[<name>,<param>]`, `service.discovery` — состояние и обнаружение служб;
* `wmi.get[...]` — произвольный WMI-запрос (возвращает значение);
* `vfs.fs.discovery` с учётом Windows-томов;
* `eventlog[...]` — чтение журнала событий (активная проверка);
* `proc.num[...]` — число процессов;
* стандартные `system.cpu.load`, `vm.memory.size[...]`, `net.if.*`, `agent.ping`.

### Пассивный и активный режимы

Активный режим предпочтителен, если сервер инициировать соединение к клиенту не может (DMZ, филиал). Пассивный — если правила firewall позволяют входящий 10050. `eventlog` и, частично, плагинные ключи Agent 2 требуют активного режима.

## Практические сценарии

### Предварительные требования

* Права локального администратора на установку службы.
* Открытый порт 10050 (пассивный) и/или исходящий к серверу 10051 (активный).
* Имя хоста в конфиге совпадает с `Host name` в Zabbix.

### Шаг 1. Установка агента

MSI-пакет для Windows (x64) устанавливается графически либо из командной строки:

```powershell
# Установка с параметрами (директория установки и имя хоста)
msiexec /i zabbix_agent2-7.4.0-windows-amd64-openssl.msi /qn ^
  SERVER=192.168.1.100 ^
  SERVERACTIVE=192.168.1.100 ^
  HOSTNAME=win-fs01 ^
  LISTENPORT=10050

# Проверка службы
Get-Service "Zabbix Agent 2"
# → Status: Running
```

Конфигурация — `C:\Program Files\Zabbix Agent 2\zabbix_agent2.conf`.

```ini
Server=192.168.1.100
ServerActive=192.168.1.100
Hostname=win-fs01
LogFile=C:\Program Files\Zabbix Agent 2\zabbix_agent2.log
```

### Шаг 2. Счётчики производительности

Ключ `perf_counter` возвращает значение счётчика Performance Monitor:

```
perf_counter["\Processor(_Total)\% Processor Time"]
perf_counter["\Memory\Available MBytes"]
perf_counter["\LogicalDisk(C:)\% Free Space"]
```

> Счётчики с локализованными именами зависят от языка ОС: на русской Windows путь счётчика может отличаться. Для переносимости закладывайте это в макросы или проверяйте фактические имена счётчиков в `perfmon`.

### Шаг 3. WMI-запросы

`wmi.get` выполняет WMI-запрос в заданном пространстве имён:

```
wmi.get[root\cimv2,"SELECT TotalVisibleMemorySize FROM Win32_OperatingSystem"]
wmi.get[root\cimv2,"SELECT FreeSpace FROM Win32_LogicalDisk WHERE DeviceID='C:'"]
```

Для LLD по WMI удобно возвращать JSON через JavaScript-предобработку и `wmi.get` как master-элемент.

### Шаг 4. Мониторинг служб

```
service.info["MSSQLSERVER",state]      # 0 = running
service.discovery                       # LLD по всем службам
```

`service.discovery` создаёт прототипы, а `service.info["{#SERVICE.NAME}",state]` даёт состояние; триггер срабатывает при отклонении от `running`.

### Шаг 5. Журнал событий (active)

```
eventlog["System","error|critical",,,"^EventID",,skip]
```

Ключ `eventlog` — активная проверка: агент отправляет найденные события на сервер. Применяется для отлова BSOD, ошибок дисков, отказов служб.

### Проверка

```powershell
# Прослушивание порта (если пассивный режим)
netstat -ano | findstr :10050
# → TCP 0.0.0.0:10050 LISTENING

# Локальный тест ключа agent-утилитой
& "C:\Program Files\Zabbix Agent 2\zabbix_agent2.exe" -t "agent.ping"
# → agent.ping  [u|1]
```

## Операции и команды

| Задача | Команда PowerShell |
|---|---|
| Статус службы | `Get-Service "Zabbix Agent 2"` |
| Запуск/остановка | `Restart-Service "Zabbix Agent 2"` |
| Просмотр конфига | `Get-Content "C:\Program Files\Zabbix Agent 2\zabbix_agent2.conf"` |
| Тест ключа | `& "...\zabbix_agent2.exe" -t "perf_counter[\Processor(_Total)\% Processor Time]"` |
| Версия | `& "...\zabbix_agent2.exe" -V` |

```powershell
# Проверка конкретного счётчика до добавления в Zabbix
(Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue
# → 12.34
```

## Устранение неисправностей

### Агент не запускается

* Служба не установлена или остановлена — проверить `Get-Service`.
* Ошибка в конфиге — смотреть `zabbix_agent2.log`.
* Порт 10050 занят другим процессом.

### Элементы Unsupported

* Неверный путь счётчика `perf_counter` (локализация или опечатка).
* WMI-запрос возвращает нескалярное значение — `wmi.get` ожидает одно значение.
* Для `eventlog` использован пассивный режим — переключить на активный.

### Данные есть, но хост «Not available»

* Firewall блокирует порт со стороны сервера (пассивный режим).
* В активном режиме — `Hostname` не совпадает с именем хоста в Zabbix.
* На сервер не открыт 10051.

### Счётчики на другой локали ОС

* Имена счётчиков на русской Windows отличаются от английских. Определите фактические имена через `typeperf -qx` и используйте их в макросах.

## Лучшие практики

* **Agent 2 для новых развёртываний Windows**; классический агент — для существующих инсталляций.
* **Официальные шаблоны Windows by Zabbix agent (active)** — базовое покрытие CPU, памяти, дисков, сети, служб и event log.
* **Макросы для путей счётчиков** — облегчают работу с разными локалями и версиями ОС.
* **Активный режим** для серверов в DMZ/филиалах, где входящие подключения запрещены.
* **Не дублируйте сбор** со специализированными системами Windows (SCOM/Wazuh) — разделите роли: Zabbix отвечает за доступность и ресурсы.
* **Ограничьте права службы агента** минимально необходимыми; для WMI/eventlog требуются соответствующие разрешения.

## Дополнительная информация

### См. также

* [Режимы работы агентов](./zabbix_agent_checks.md) — активный/пассивный, авторегистрация.
* [Элементы данных](./zabbix_items.md) — типы элементов и предобработка.
* [Мониторинг логов](./zabbix_log_monitoring.md) — `log`/`logrt`/`eventlog`.
* [Установка и настройка](./installation.md) — развёртывание инфраструктуры Zabbix.

### Источники

* Zabbix documentation: [Windows agent](https://www.zabbix.com/documentation/current/en/manual/appendix/install/windows_agent), [Windows-specific item keys](https://www.zabbix.com/documentation/current/en/manual/config/items/itemtypes/zabbix_agent/win_keys).
