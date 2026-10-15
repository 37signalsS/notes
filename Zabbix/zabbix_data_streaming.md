# Zabbix — экспорт и стриминг данных

**Актуально для:** Zabbix 7.0 LTS / 7.4

Документ описывает выгрузку данных из Zabbix во внешние системы: real-time export в файлы (NDJSON) и стриминг на внешние системы через коннекторы (HTTP, Kafka). Смежные темы — **[API и автоматизация](./zabbix_api_automation.md)**, **[Дополнительная информация](./additional_info.md)**.

---

## Определения

* **Real-time export** — непрерывная запись триггерных событий, значений элементов и трендов в файлы в формате newline-delimited JSON.
* **NDJSON (newline-delimited JSON)** — формат, где каждая строка файла — отдельный JSON-объект; все экспортные файлы имеют расширение `.ndjson`.
* **`ExportDir`** — каталог, в который Zabbix пишет экспортные файлы; задание этого параметра включает real-time export.
* **`ExportType`** — какие сущности экспортировать: `events`, `history`, `trends`.
* **`ExportFileSize`** — максимальный размер одного экспортного файла; при превышении файл переименовывается добавлением `.old`, создаётся новый.
* **Connector (коннектор, с 7.0)** — механизм стриминга значений элементов и событий во внешние системы по HTTP.
* **Connector manager / connector worker** — процессы сервера, отвечающие за стриминг.
* **Kafka connector** — легковесный сервер на Go, пересылающий значения и события из Zabbix в Kafka-брокер.

---

## Основные концепции

Существует два независимых механизма выгрузки данных:

| Свойство | Export в файлы | Стриминг через коннекторы |
|---|---|---|
| Назначение | Локальные `.ndjson`-файлы для последующей обработки | Отправка во внешние системы по HTTP |
| Транспорт | Файловая система | HTTP (`Content-Type: application/x-ndjson`) |
| Экспортируемые данные | events, history, **trends** | events, item values (тренды — только в файлы) |
| Настройка | `ExportDir`, `ExportType`, `ExportFileSize` | Коннекторы в веб-интерфейсе |
| Введён | Давно | 7.0 |

Общее: экспортируются **триггерные события**, **значения элементов** и **тренды**; **value mappings не применяются**; формат — NDJSON, по одному JSON-объекту на строку.

### Экспорт в файлы

* Включение: задать каталог в `ExportDir` в `zabbix_server.conf`.
* `ExportType` позволяет ограничить набор: `events`, `history`, `trends` (можно комбинировать).
* `ExportFileSize` управляет ротацией: перед записью сервер проверяет размер файла и, если лимит превышен, переименовывает его с суффиксом `.old`, создавая файл с исходным именем.
* Файлы `.ndjson` пригодны для последующей загрузки в аналитические системы (ClickHouse, Elasticsearch) через внешние агенты.

### Стриминг через коннекторы (7.0+)

* Настройка коннектора включает:

  * **Name** — имя коннектора;
  * **Data type** — `Item values` (значения элементов) или `Events` (события);
  * **URL** — адрес приёмника (поддерживаются пользовательские макросы);
  * **Tag filter** — фильтр по тегам (операторы `Exists`, `Equals`, `Contains`, `Does not exist`, `Does not equal`, `Does not contain`; логика `And/Or` или `Or`; сопоставление имён тегов всегда регистрозависимо).

* Обмен идёт по HTTP методом POST на URL приёмника; тело — NDJSON. Успешными считаются коды ответа **200, 201, 202, 203, 204**, иначе запрос считается неуспешным.

Пример тела запроса стриминга событий:

```http
POST /v1/events HTTP/1.1
Host: localhost:8080
Content-Type: application/x-ndjson

{"clock":1673454303,"ns":800155804,"value":1,"eventid":5,"name":"trigger for foo being 0","severity":0,"hosts":[{"host":"Zabbix server","name":"Zabbix server"}],"groups":["Zabbix servers"],"tags":[{"tag":"foo_trig","value":"test"}]}
```

* Очередь коннектора контролируется внутренним элементом `zabbix[connector_queue]` — число значений в очереди на отправку.
* **Kafka connector** (Go, тоже «Kafka connector for Zabbix server») — типовой приёмник для стриминга в Kafka: принимает данные от сервера и публикует их в топики (`Kafka.Items`, `Kafka.Events`). Адреса брокеров задаются списком в `kafka_connector.conf` (например, `Kafka.URL=kafka1.example.com:9093,kafka2.example.com:9093`; порт при отсутствии берётся из `Kafka.Port`, по умолчанию `9093`); клиент подключается к первым ответившим брокерам и использует их метаданные кластера. Приёмник слушает пути `api/v1/items` и `api/v1/events`, поэтому URL коннектора в веб-интерфейсе задаётся как `http://<host>:<port>/api/v1/items` и `.../api/v1/events`.

---

## Практические сценарии

### Предварительные требования

* Работающий Zabbix Server 7.0+.
* Для файлового экспорта — права на запись в каталог `ExportDir` и место на диске.
* Для стриминга — доступный HTTP-приёмник (собственный сервис, Kafka connector) и сетевой доступ к нему.

### Сценарий 1. Экспорт в NDJSON-файлы

```ini
# /etc/zabbix/zabbix_server.conf
ExportDir=/var/lib/zabbix/export
ExportType=events,history,trends
ExportFileSize=1G
```

```bash
sudo mkdir -p /var/lib/zabbix/export
sudo chown zabbix:zabbix /var/lib/zabbix/export
sudo systemctl restart zabbix-server
ls -l /var/lib/zabbix/export
# → events.ndjson, history.ndjson, trends.ndjson
tail -n 1 /var/lib/zabbix/export/events.ndjson
# → одна строка JSON с последним событием
```

### Сценарий 2. Ограничение экспорта по типу

Экспортировать только события и историю (тренды не нужны):

```ini
ExportDir=/var/lib/zabbix/export
ExportType=events,history
```

### Сценарий 3. Стриминг событий в собственный приёмник

1. Развернуть HTTP-приёмник, принимающий POST с `application/x-ndjson`.
2. В веб-интерфейсе создать коннектор: Data type `Events`, URL приёмника, при необходимости Tag filter.
3. Проверить, что события доходят до приёмника, и что ответ — 2xx.

### Сценарий 4. Стриминг в Kafka

1. Собрать и развернуть Kafka connector (Go): `make build` создаёт исполняемый файл `kafka-connector`, конфигурация — `kafka_connector.conf`. Указать адреса брокеров и топики.
2. Создать коннектор в Zabbix, Data type `Item values` (и/или `Events`), URL = адрес Kafka connector.
3. Убедиться, что сообщения появляются в топике.
4. Мониторить `zabbix[connector_queue]` — рост очереди означает проблемы с приёмником.

### Валидация

```bash
# Файловый экспорт пишется
ls -lh /var/lib/zabbix/export
# → .ndjson-файлы увеличиваются, при ротации появляются .old

# Проверить NDJSON-формат (каждая строка — валидный JSON)
head -n 3 /var/lib/zabbix/export/history.ndjson
# → {"host":{...},"itemid":...,...}

# Очередь коннектора (внутренний элемент)
# zabbix[connector_queue] — число значений, ожидающих отправки
```

---

## Операции и команды

```bash
# Проверить, что сервер видит параметры экспорта
zabbix_server -T -c /etc/zabbix/zabbix_server.conf 2>&1 | grep -i export
# → при корректной конфигурации ошибок нет
```

| Параметр | Где | Назначение |
|---|---|---|
| `ExportDir` | `zabbix_server.conf` | Каталог экспортных файлов (включает экспорт) |
| `ExportType` | `zabbix_server.conf` | Типы: `events`, `history`, `trends` |
| `ExportFileSize` | `zabbix_server.conf` | Максимальный размер файла до ротации |
| `zabbix[connector_queue]` | внутренний элемент | Длина очереди коннектора |

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| Файлы экспорта не появляются | `ExportDir` не задан или каталог недоступен | Проверить параметр и права на запись |
| Экспортируются не все типы | `ExportType` ограничивает набор | Указать нужные типы через запятую |
| Диск переполняется | Нет ротации/очистки старых `.old`-файлов | Задать `ExportFileSize`; настроить внешнюю очистку/архивацию |
| События не доходят до приёмника | URL недоступен / приёмник не отвечает 2xx | Проверить доступность, коды ответа, логи приёмника |
| Растёт `zabbix[connector_queue]` | Медленный/недоступный приёмник | Устранить приёмник; проверить сеть и пропускную способность |
| Kafka connector предупреждает о недоступных адресах | В списке смешаны адреса разных кластеров | Использовать брокеры одного кластера |
| Тренды не стримятся в коннектор | Тренды доступны только при экспорте в файлы | Использовать `ExportType=trends` и файловый экспорт |

---

## Лучшие практики

* **Разделять механизмы:** файловый экспорт — для последующей пакетной загрузки (BI/озеро данных); коннекторы — для онлайн-потока в Kafka/HTTP.
* **Фильтровать по тегам** (`Tag filter`) — не экспортировать всё подряд, снижая объём и стоимость.
* **Ограничивать `ExportFileSize`** и организовать внешнюю ротацию/удаление — иначе диск переполнится.
* **Мониторить `zabbix[connector_queue]`** триггером: устойчивый рост означает сбой приёмника (см. **[Триггеры](./zabbix_triggers.md)**).
* **Защищать канал стриминга** (TLS, внутренняя сеть) — данные содержат чувствительную информацию.
* **Не использовать файловый экспорт как бэкап** — это транспорт, а не резервная копия (см. **[Обновление и резервное копирование](./zabbix_upgrade_and_backup.md)**).
* **Проверять совместимость схемы NDJSON** при обновлениях Zabbix — формат может меняться между версиями.

---

## Дополнительная информация

### См. также

* [Zabbix — API и автоматизация](./zabbix_api_automation.md) — `history.push`, экспорт/импорт конфигурации.
* [Zabbix — внутреннее устройство и архитектура процессов](./additional_info.md) — процессы connector manager/worker.
* [Zabbix — обновление и резервное копирование](./zabbix_upgrade_and_backup.md) — отличие транспорта от бэкапа.
* [Zabbix — алертинг и эскалация](./zabbix_alerting_and_escalation.md) — уведомления как альтернативный канал внешних интеграций.

### Источники и ссылки

* Zabbix documentation: [Export to files](https://www.zabbix.com/documentation/7.0/en/manual/config/export/files)
* Zabbix documentation: [Streaming to external systems](https://www.zabbix.com/documentation/7.0/en/manual/config/export/streaming)
* Zabbix documentation: [Newline-delimited JSON export protocol](https://www.zabbix.com/documentation/7.0/en/manual/appendix/protocols/real_time_export)
* Zabbix Git: [Kafka connector for Zabbix server](https://git.zabbix.com/projects/ZT/repos/kafka-connector/browse)
