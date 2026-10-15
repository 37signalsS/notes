# Zabbix — интеграция с Grafana

**Актуально для:** Zabbix 7.0 LTS / 7.4, Grafana 11.6+

Документ описывает визуализацию данных Zabbix в Grafana через плагин-источник данных: установку и включение плагина, настройку источника, Direct DB Connection, панель Problems и провижининг. Общие сведения об источниках Grafana — в разделе **[Grafana](../Grafana/grafana_plugins.md)**.

---

## Определения

* **Zabbix data source plugin** — плагин Grafana `alexanderzobnin-zabbix-app`, позволяющий запрашивать метрики, проблемы и SLA из Zabbix.
* **App plugin** — тип плагина Grafana: его нужно не только установить, но и **включить** отдельным шагом, прежде чем источник данных станет доступен.
* **Direct DB Connection** — режим, при котором плагин читает историю и тренды напрямую из БД Zabbix через существующий SQL/InfluxDB источник Grafana, минуя API.
* **Problems panel** — панель Grafana для отображения активных проблем (триггеров) Zabbix.
* **Annotations** — пометки на графиках, построенные из событий Zabbix.
* **Provisioning** — декларативное описание источника данных в YAML-файлах Grafana.

---

## Основные концепции

### Что даёт плагин

Возможности источника Zabbix в Grafana:

* **Metrics** — запрос значений элементов (в том числе массово по regex).
* **Alerting** — правила алертинга Grafana на данных Zabbix.
* **Annotations** — события Zabbix как пометки на графиках (фильтрация по важности и подтверждению).
* **Template variables** — переменные дашборда (хосты, группы).
* **Problems panel** — таблица активных проблем.
* **Direct DB Connection** — быстрый доступ к истории/трендам на широких диапазонах.
* **Функции обработки** — `groupBy`, `scale`, `delta`, `rate`, `movingAverage`, `percentile` и др.

### Установка и включение

Плагин — **app plugin**. Установка и включение — два разных шага:

1. Установить (Administration → Plugins and data → Plugins → Install, либо `grafana cli`).
2. **Включить** (Enable) на странице плагина — до этого источник нельзя добавить.
3. Перезапустить Grafana после установки.

```bash
# Установка плагина из CLI (новый синтаксис)
grafana cli plugins install alexanderzobnin-zabbix-app
# → Installing plugin: alexanderzobnin-zabbix-app

# В старых версиях с отдельным бинарём
grafana-cli plugins install alexanderzobnin-zabbix-app
```

Для неподписанных сборок может потребоваться в `grafana.ini`:

```ini
allow_loading_unsigned_plugins = alexanderzobnin-zabbix-datasource
```

### Настройка источника данных

Ключевой параметр — **URL**: полный адрес API Zabbix, **включая** путь `api_jsonrpc.php`:

```default
http://zabbix.example.com/zabbix/api_jsonrpc.php
```

Аутентификация: `authType` = `userLogin` (логин/пароль) или `token` (API-токен). Пользователь Zabbix должен иметь права чтения на запрашиваемые группы и хосты.

Параметры трендов:

* `trends` (по умолчанию `true`) — включать тренды;
* `trendsFrom` (по умолчанию `7d`) — с какого возраста использовать тренды вместо истории;
* `trendsRange` (по умолчанию `4d`) — ширина диапазона для переключения на тренды.

### Direct DB Connection

Позволяет плагину читать history/trends **напрямую из БД Zabbix** через существующий SQL/InfluxDB источник Grafana, минуя Zabbix API. Быстрее на широких диапазонах и снижает объём передаваемых данных.

Требования:

* В Grafana должен быть создан источник MySQL, PostgreSQL или InfluxDB, указывающий на БД `zabbix`.
* В настройках источника Zabbix (Additional settings → Direct DB Connection) включить `Enable Direct DB Connection` и выбрать этот источник.
* Для InfluxDB дополнительно задаётся retention policy (оставлять пустым при стандартной политике).

---

## Практические сценарии

### Предварительные требования

* Grafana 11.6+ (для актуальной версии плагина), права Organization administrator.
* Работающий Zabbix Server с доступным API и пользователь с правами чтения.
* Для Direct DB Connection — доступ Grafana к БД Zabbix.

### Сценарий 1. Установка и включение плагина

```bash
grafana cli plugins install alexanderzobnin-zabbix-app
sudo systemctl restart grafana-server
# → плагин установлен в /var/lib/grafana/plugins
```

Далее в UI: Administration → Plugins → найти `Zabbix` → Install (если ещё не установлен) → **Enable**.

### Сценарий 2. Добавление источника данных

Connections → Add new connection → `Zabbix` → Add new data source:

* **Name**: `Zabbix`.
* **URL**: `http://zabbix.example.com/zabbix/api_jsonrpc.php`.
* **Auth**: userLogin (username/password) или token (API token).
* Save & test → сообщение: `Zabbix API version: 7.4.0`.

### Сценарий 3. Direct DB Connection

1. Создать источник Grafana MySQL/PostgreSQL, указывающий на БД `zabbix` (Save & test).
2. В источнике Zabbix → Additional settings → Direct DB Connection → включить и выбрать созданный источник.
3. Save & test → сообщение дополнительно содержит тип подключения к БД.

### Сценарий 4. Панель Problems и аннотации

1. Создать дашборд → добавить панель → тип **Problems** → выбрать источник Zabbix, фильтры по группам/важности.
2. В настройках дашборда → Annotations → добавить источник Zabbix, задать фильтр по событиям.
3. Проверить, что активные проблемы отображаются, а события появляются как пометки на графиках.

### Сценарий 5. Провижининг источника (YAML)

```yaml
apiVersion: 1

datasources:
  - name: Zabbix
    type: alexanderzobnin-zabbix-datasource
    url: http://zabbix.example.com/zabbix/api_jsonrpc.php
    jsonData:
      authType: userLogin
      username: grafana_ro
      trends: true
      trendsFrom: '7d'
      trendsRange: '4d'
      cacheTTL: '1h'
      dbConnectionEnable: true
      dbConnectionDatasourceName: ZabbixDB
    secureJsonData:
      password: <ZABBIX_PASSWORD>
    version: 1
    editable: false

  - name: ZabbixDB
    type: mysql
    url: <MYSQL_HOST>:3306
    user: <MYSQL_USER>
    jsonData:
      database: zabbix
    secureJsonData:
      password: <MYSQL_PASSWORD>
```

### Валидация

* В настройках источника кнопка **Save & test** должна показать версию Zabbix API (и тип БД при Direct DB Connection).
* На дашборде с панелью по элементу данных должны строиться графики.
* В панели Problems — список активных проблем, совпадающий с Zabbix.

---

## Операции и команды

```bash
# Список установленных плагинов
grafana cli plugins list
# → alexanderzobnin-zabbix-app @ ...

# Обновление плагина
grafana cli plugins install alexanderzobnin-zabbix-app
# (для локальных инсталляций плагины не обновляются автоматически)
```

| Поле provisioning | Назначение | По умолчанию |
|---|---|---|
| `authType` | `userLogin` или `token` | `userLogin` |
| `trends` | Использовать тренды | `true` |
| `trendsFrom` | Порог перехода на тренды | `7d` |
| `trendsRange` | Ширина диапазона для трендов | `4d` |
| `cacheTTL` | Кэш имён метрик | `1h` |
| `dbConnectionEnable` | Включить Direct DB Connection | `false` |

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| Источник Zabbix недоступен для добавления | Плагин установлен, но не **включён** | Enable на странице плагина |
| `Invalid JSON` / ошибка API | URL без `api_jsonrpc.php` | Указать полный путь до `api_jsonrpc.php` |
| Нет данных по части хостов | У пользователя нет прав чтения на эти группы/хосты | Выдать права в Zabbix |
| Медленные графики на широких диапазонах | Данные идут через API | Включить Direct DB Connection |
| Direct DB Connection не работает | Нет SQL-источника к БД или неверные креды | Создать/проверить источник MySQL/PostgreSQL |
| Пустые графики, хотя данные есть в Zabbix | Неверный `trendsFrom`/`trendsRange`, кэш | Проверить параметры трендов; очистить кэш |
| Плагин не загружается в старых Grafana | Неподписанный плагин | `allow_loading_unsigned_plugins = alexanderzobnin-zabbix-datasource` |
| Аннотации не отображаются на диапазоне «день/неделя» | Известное ограничение | Сузить диапазон или обновить плагин |

---

## Лучшие практики

* **Выделенный пользователь Zabbix** для Grafana с правами только на чтение нужных групп.
* **API-токен вместо пароля** (`authType: token`) — устойчивее и отзывается независимо (см. **[Аутентификация и RBAC](./zabbix_authentication_and_rbac.md)**).
* **Direct DB Connection** для тяжёлых дашбордов с широкими диапазонами.
* **Провижининг источник в YAML** — воспроизводимость и управление конфигурацией.
* **Не публиковать API Zabbix в интернет;** доступ граничить сетевой политикой.
* **Разделять роли:** Zabbix — сбор и алертинг, Grafana — визуализация и аналитика (не дублировать алертинг в двух системах без необходимости).
* **Следить за версией плагина** — поддержка новых версий Zabbix/Grafana приходит с обновлениями плагина.

---

## Дополнительная информация

### См. также

* [Grafana — плагины](../Grafana/grafana_plugins.md) — установка и управление плагинами Grafana.
* [Zabbix — API и автоматизация](./zabbix_api_automation.md) — API, к которому обращается плагин.
* [Zabbix — аутентификация и RBAC](./zabbix_authentication_and_rbac.md) — пользователь для интеграции.
* [Zabbix — экспорт и стриминг данных](./zabbix_data_streaming.md) — альтернативные каналы выгрузки.

### Источники и ссылки

* Grafana docs: [Zabbix data source](https://grafana.com/docs/plugins/alexanderzobnin-zabbix-app/latest/)
* Grafana docs: [Configure the Zabbix data source](https://grafana.com/docs/plugins/alexanderzobnin-zabbix-app/latest/configure/)
* Grafana docs: [Provisioning the Zabbix data source](https://grafana.com/docs/plugins/alexanderzobnin-zabbix-app/latest/configuration/provisioning/)
