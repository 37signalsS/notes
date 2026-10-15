# Zabbix — плагины Zabbix Agent 2

**Актуально для:** Zabbix 7.0 LTS / 7.4

Документ описывает архитектуру плагинов Zabbix Agent 2, встроенные (built-in) и загружаемые (loadable) плагины, их конфигурирование и разработку собственных. Базовые ключи агента (system.*, vfs.*, net.*) и общие принципы работы агента описаны в **[Zabbix — проверки агентом](./zabbix_agent_checks.md)**; мониторинг СУБД через плагины — в **[Zabbix — мониторинг баз данных](./zabbix_database_monitoring.md)**.

---

## Определения

* **Zabbix Agent 2** — агент нового поколения, написанный на Go; единый бинарник, поддерживает плагины.
* **Built-in plugin** — плагин, скомпилированный прямо в бинарник агента; доступен из коробки.
* **Loadable plugin** — отдельный исполняемый файл, с которым агент взаимодействует по протоколу плагинов; сборка самого агента не требуется.
* **Plugin name** — уникальное имя плагина, задаваемое при регистрации; используется в конфиге (`Plugins.<Name>.System.Path`) и не должно конфликтовать с другими.
* **Item key / metric** — ключ элемента данных, который регистрирует плагин (например, `mysql.ping`, `docker.info`).
* **Named session** — именованный набор параметров подключения плагина (например, `Plugins.Mysql.Sessions.<name>.*`), выбираемый по имени в ключе элемента.

---

## Основные концепции

### Зачем Agent 2

Zabbix Agent 2 написан на Go и поддерживает **плагины** — как встроенные, так и загружаемые. Это позволяет мониторить СУБД, брокеры, контейнеры и другие сервисы без внешних UserParameter-скриптов и без установки дополнительных утилит (например, `mysqladmin`, `redis-cli`) на хост. Agent 2 при этом поддерживает **все ключи элементов классического Zabbix agent** (Unix и Windows) и добавляет к ним плагинные ключи.

### Два типа плагинов (с Zabbix 6.0)

| | Built-in | Loadable |
|---|---|---|
| Компиляция | Внутри бинарника агента | Отдельно, как самостоятельный исполняемый файл |
| Требует пересборки агента | Да | Нет |
| Обновление агента | Требует обновления плагина вместе с агентом | Плагин обновляется независимо |
| Поддержка с версии | 6.0 | 6.0.0 |
| Конфигурация | `zabbix_agent2.d/plugins.d/*.conf` (общая схема) | `Plugins.<Name>.System.Path` |

**Преимущество loadable-плагинов** — независимое обновление: при апгрейде агента плагин пересобирать не нужно. Внешние (community/loadable) плагины живут в отдельном репозитории Zabbix и используют общий с агентом Go-пакет.

**Ограничение интерфейсов loadable-плагинов:** поддерживаются `Exporter` (кроме параметра `ContextProvider`), `Runner`, `Configurator`. Интерфейсы `Watcher` и `Collector` для loadable-плагинов **не поддерживаются**.

### Встроенные плагины

Доступны из коробки с Zabbix Agent 2:

| Плагин | Назначение | Примеры ключей |
|---|---|---|
| Docker | Мониторинг контейнеров Docker | `docker.info`, `docker.ping`, `docker.containers`, `docker.container_info`, `docker.container_stats`, `docker.data_usage`, `docker.images`, `docker.containers.discovery`, `docker.images.discovery` |
| MySQL | MySQL и форки | `mysql.ping`, `mysql.version`, `mysql.get_status_variables`, `mysql.db.discovery`, `mysql.db.size`, `mysql.replication.*`, `mysql.custom.query` |
| PostgreSQL | PostgreSQL | `pgsql.ping`, `pgsql.db.discovery`, `pgsql.autovacuum.count`, `pgsql.custom.query` и др. |
| MSSQL | Microsoft SQL Server | `mssql.ping`, `mssql.availability.group.get`, `mssql.custom.query` и др. |
| Oracle | Oracle Database (требует Oracle Instant Client) | `oracle.ping`, `oracle.instance.info`, `oracle.sessions.stats`, `oracle.sys.metrics`, `oracle.custom.query` и др. |
| Redis | Redis | `redis.ping`, `redis.info`, `redis.config`, `redis.slowlog.count` |
| MongoDB | MongoDB | `mongodb.*` |
| Memcached | Memcached | `memcached.*` |
| Modbus | Чтение данных Modbus | `modbus.get` |
| MQTT | Подписка на топики MQTT | `mqtt.get` |
| Ceph | Ceph | `ceph.*` |
| Ember+ | Ember+ | `ember.*` |
| Web certificate | Проверка сроков TLS-сертификатов | `web.certificate.get` |
| NET.TCP / VFS / Systemd и др. | Системные проверки | `net.tcp.*`, `vfs.*`, `systemd.*` |

Ключи конкретной версии всегда можно вывести командой `zabbix_agent2 -p` (см. ниже).

### Расположение конфигурации

* Основной конфиг агента: `/etc/zabbix/zabbix_agent2.conf`.
* Директория include: `/etc/zabbix/zabbix_agent2.d/`.
* Конфиги плагинов: `/etc/zabbix/zabbix_agent2.d/plugins.d/*.conf`.
* Для loadable-плагина путь к его исполняемому файлу задаётся параметром `Plugins.<Name>.System.Path` в этом каталоге.

Имя в параметре (`<Name>`) обязано совпадать с именем, указанным при регистрации метрик в коде плагина (`plugin.RegisterMetrics`).

### Регистрация метрик (для разработчиков)

В Go-коде плагина метрики регистрируются в функции `init()`:

```go
import "git.zabbix.com/ap/plugin-support/plugin"

func init() {
    // Register the metric, specifying the plugin and metric details.
    // 1 - a pointer to plugin implementation
    // 2 - plugin name
    // 3 - metric name (item key)
    // 4 - metric description
    plugin.RegisterMetrics(&impl, "Myip", "myip", "Return the external IP address of the host where agent is running.")
}
```

Критично: **описание метрики должно заканчиваться точкой** — иначе agent 2 не запустится. Имя плагина (`Myip`) должно быть уникальным и не конфликтовать с существующими плагинами.

---

## Практические сценарии

### Предварительные требования

* Установлен Zabbix Agent 2 (пакет `zabbix-agent2`), а не классический `zabbix-agent`.
* Для Docker-плагина у пользователя `zabbix` есть доступ к `/var/run/docker.sock` (обычно через группу `docker`).
* Для Oracle — установлен Oracle Instant Client.

### Просмотр доступных ключей

```bash
# Список известных (зарегистрированных) ключей элементов
zabbix_agent2 -p
# → таблица ключей и их описаний
```

### Сценарий 1. Включение встроенного плагина Docker

1. Убедиться, что агент видит Docker-сокет:

   ```
   docker ps
   # → список контейнеров
   ```

2. При необходимости задать нестандартный endpoint в `/etc/zabbix/zabbix_agent2.d/plugins.d/docker.conf`:

   ```ini
   Plugins.Docker.Endpoint=unix:///var/run/docker.sock
   Plugins.Docker.Timeout=5
   ```

   `Plugins.Docker.Endpoint` по умолчанию `unix:///var/run/docker.sock`; поддерживается **только схема `unix://`**. `Plugins.Docker.Timeout` — 1–30 секунд.

3. Перезапустить агент:

   ```bash
   sudo systemctl restart zabbix-agent2
   ```

4. На хосте в Zabbix привязать шаблон **`Docker by Zabbix agent 2`** и дать LLD отработать.

### Сценарий 2. Настройка плагина СУБД через named session

Пример MySQL с двумя экземплярами — в `/etc/zabbix/zabbix_agent2.d/plugins.d/mysql.conf` (фрагмент):

```ini
Plugins.Mysql.Sessions.prod.Uri=tcp://127.0.0.1:3306
Plugins.Mysql.Sessions.prod.User=zbx_monitor
Plugins.Mysql.Sessions.prod.Password=<PASSWORD>

Plugins.Mysql.Sessions.replica.Uri=tcp://127.0.0.1:3307
Plugins.Mysql.Sessions.replica.User=zbx_monitor
Plugins.Mysql.Sessions.replica.Password=<PASSWORD>
```

В ключе элемента имя сессии передаётся в connString: `mysql.ping[tcp://127.0.0.1:3306,,,,prod]` или через `Plugins.Mysql.Sessions.<name>`. Подробности — в **[Zabbix — мониторинг баз данных](./zabbix_database_monitoring.md)**.

### Сценарий 3. Сборка и подключение собственного loadable-плагина

1. Собрать плагин (Go) в исполняемый файл, например `/usr/local/zabbix/go/plugins/myip/myip`.
2. Прописать путь к нему в конфиг:

   ```ini
   # /etc/zabbix/zabbix_agent2.d/plugins.d/myip.conf
   Plugins.Myip.System.Path=/usr/local/zabbix/go/plugins/myip/myip
   ```

3. Перезапустить агент и проверить:

   ```bash
   sudo systemctl restart zabbix-agent2
   zabbix_agent2 -t "myip"
   # → myip [<value>]
   ```

Если в логе агента ошибка про описание метрики — проверить, что описание в `plugin.RegisterMetrics` заканчивается точкой.

### Валидация

```bash
# Проверка конкретного ключа плагина на локальном агенте
zabbix_agent2 -t "docker.info"
# → docker.info [<JSON>]

# Проверка из Zabbix (сервер/прокси → агент)
zabbix_get -s <AGENT_HOST> -k "mysql.ping[tcp://127.0.0.1:3306]"
# → 1

# Проверка, что плагин загрузился (в логе агента)
grep -i "plugin" /var/log/zabbix/zabbix_agent2.log
```

---

## Операции и команды

```bash
# Вывести все зарегистрированные ключи (built-in + loadable)
zabbix_agent2 -p

# Протестировать один ключ на месте
zabbix_agent2 -t "redis.ping[tcp://127.0.0.1:6379]"

# Подробный вывод при тесте/печати ключей
zabbix_agent2 -p -v

# Проверить конфигурацию без запуска агента
zabbix_agent2 -T -c /etc/zabbix/zabbix_agent2.conf

# Runtime control
zabbix_agent2 -R userparameter_reload -c /etc/zabbix/zabbix_agent2.conf
```

| Опция | Действие |
|---|---|
| `-c, --config` | Путь к конфигурационному файлу |
| `-p, --print` | Вывести известные ключи элементов |
| `-t, --test <key>` | Протестировать один ключ и выйти |
| `-v, --verbose` | Подробный вывод для `--test`/`--print` |
| `-T, --test-config` | Проверить конфигурацию |
| `-R, --runtime-control` | Runtime control (например, перечитать userparameters) |
| `-h, --help` | Справка |
| `-V, --version` | Версия |

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| Агент не запускается после добавления плагина | Описание метрики в `RegisterMetrics` не заканчивается точкой | Добавить точку в описание и пересобрать |
| Ключ плагина не найден (`Unsupported`) | Плагин не загружен / неверный `Plugins.<Name>.System.Path` | Проверить путь, имя плагина и лог агента |
| Docker-ключи возвращают ошибку | Нет доступа к `/var/run/docker.sock` | Добавить `zabbix` в группу `docker`, перезапустить агент |
| Плагин не стартует | Конфликт имени плагина с существующим | Переименовать плагин (имена уникальны) |
| Ошибка подключения к СУБД | Неверный connString / права / TLS | Проверить `Plugins.<Plugin>.Sessions.*`, пользователя, параметры TLS |
| Плагин не обновился после апгрейда агента | Для built-in требуется пересборка | Использовать loadable-версию или пересобрать |
| Значения пустые на удалённом хосте | Обращается к localhost, а БД на другом сервере | Указать корректный URI в connString/сессии |

---

## Лучшие практики

* **Предпочитать loadable-плагины built-in** там, где есть выбор: их обновление не требует пересборки и апгрейда агента вместе с плагином.
* **Проверять ключи через `zabbix_agent2 -t`** до добавления элемента данных — быстрее, чем через UI.
* **Использовать named sessions** для нескольких экземпляров СУБД/сервисов — конфигурация отделяется от ключей.
* **Не давать агенту избыточных прав**: для Docker достаточно членства в группе `docker`; не запускать агент от root без необходимости.
* **Хранить пароли к БД в защищённом виде** (ограниченные права на `plugins.d/*.conf`), а в идеале — использовать vault-макросы.
* **Следить за уникальностью имён плагинов** при написании своих — конфликт ломает загрузку.
* **Тестировать собственный плагин на той же ОС**, что и целевой агент (Go-сборка зависит от платформы).

---

## Дополнительная информация

### См. также

* [Zabbix — проверки агентом](./zabbix_agent_checks.md) — базовые ключи агента.
* [Zabbix — мониторинг баз данных](./zabbix_database_monitoring.md) — плагины MySQL/PostgreSQL/MSSQL/Oracle.
* [Zabbix — элементы данных (items)](./zabbix_items.md) — создание элементов и параметры ключей.
* [Zabbix — прокси](./zabbix_proxy.md) — агент за прокси.
* [Zabbix — внутреннее устройство и архитектура процессов](./additional_info.md) — место агента в архитектуре.

### Источники и ссылки

* Zabbix documentation: [Zabbix agent 2](https://www.zabbix.com/documentation/7.0/en/manual/concepts/agent2)
* Zabbix documentation: [Built-in plugins](https://www.zabbix.com/documentation/7.0/en/manual/concepts/agent2/builtin_plugins)
* Zabbix documentation: [Agent 2 item keys](https://www.zabbix.com/documentation/7.0/en/manual/config/items/itemtypes/zabbix_agent/zabbix_agent2)
* Zabbix documentation: [Zabbix agent 2 plugins configuration](https://www.zabbix.com/documentation/7.0/en/manual/appendix/config/zabbix_agent2_plugins)
* Zabbix guidelines: [Loadable plugins](https://www.zabbix.com/documentation/guidelines/en/plugins/loadable_plugins)
* Zabbix documentation: [zabbix_agent2 man page](https://www.zabbix.com/documentation/7.0/en/manpages/zabbix_agent2)
