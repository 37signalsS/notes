# Zabbix — инвентаризация и отчётность

**Актуально для:** Zabbix 7.0 LTS / 7.4

Документ описывает учёт активов (Host inventory), периодические отчёты (scheduled reports), отчётность по SLA и построение дашбордов и карт. Связанные темы — **[Триггеры](./zabbix_triggers.md)**, **[Внутреннее устройство](./additional_info.md)**.

---

## Определения

* **Host inventory** — набор атрибутов хоста (ОС, оборудование, ПО, серийный номер, ответственный и др.) для учёта активов.
* **Inventory mode** — режим наполнения инвентаря: `Disabled`, `Manual`, `Automatic`.
* **Scheduled report** — периодически формируемый PDF-снимок дашборда, рассылаемый получателям.
* **SLI (Service Level Indicator)** — измеряемый показатель уровня обслуживания (например, доступность).
* **SLO (Service Level Objective)** — целевое значение SLI (например, 99.9 %).
* **Service (IT-услуга)** — элемент дерева услуг, для которого рассчитывается SLI; может включать сервисы-потомки.
* **Dashboard** — страница с виджетами (графики, проблемы, SLA, карты); поддерживает сложность и совместное использование.
* **Network map** — карта топологии с элементами и связями, окрашиваемыми по состоянию триггеров.

---

## Основные концепции

### Host inventory

Инвентарь не заполняется сам по себе — данные вносятся вручную либо автоматически:

* **Disabled** — инвентарь не собирается.
* **Manual** — поля заполняются вручную в форме хоста (вкладка Inventory).
* **Automatic** — поля заполняются значениями элементов данных. В настройке элемента указывается, в какое поле инвентаря писать его значение (`Item will populate host inventory field`).

Наполнение инвентаря не может быть задачей только одного элемента: сопоставление значения поля выполняется в конфигурации элемента. Значения, полученные через элементы, попадают в инвентарь при поступлении данных.

Режим по умолчанию для новых хостов берётся из Administration → General → Other (`Default host inventory mode`). Для хостов, созданных через network discovery или autoregistration, режим можно задать операцией `Set host inventory mode` в действии — она перекрывает глобальную настройку.

### Scheduled reports

Периодический отчёт — это **PDF-версия дашборда**, отправляемая по расписанию. Для его генерации требуется отдельный сервис:

* Установить пакет `zabbix-web-service` и **Google Chrome** на той же машине, где работает web service (Chrome отдельно в пакет не входит).
* В `zabbix_server.conf` задать:

  * `WebServiceURL` — адрес web service в формате `http[s]://host:port/report` (порт по умолчанию `10053`, путь `/report` жёстко задан);
  * `StartReportWriters` — число процессов генерации отчётов (1–100); если не задан или `0` — генерация отчётов выключена.

* Во фронтенде (Administration → General → Other) задать `Frontend URL` — полный URL веб-интерфейса.

Настройка отчёта (Reports → Scheduled reports) включает: Owner, Name, Dashboard, Period (день/неделя/месяц/год), Cycle (ежедневно/еженедельно/ежемесячно/ежегодно), Start time, Repeat on (для weekly), Start/End date, Subject и Message (макросы `{TIME}`, `{TIMESTAMP}`), Subscriptions (получатели; по умолчанию владелец), Enabled, Description.

Права: нужна роль Admin или Super admin с доступом к отчетам и правом `Manage scheduled reports`.

### Отчёты по SLA

Отчёт по SLA строится на основе дерева услуг (Services) и их SLO:

* В отчёте (Services → SLA → SLA report) выбираются SLA и/или услуга, а также период.
* Каждая колонка (период) показывает SLI; значения, нарушающие SLO, выделяются красным.
* По умолчанию отображается 20 периодов; максимум 100, если заданы обе даты (From и To).
* Клик по имени услуги открывает детализированный отчёт.
* Отрицательная длительность проблемы не влияет на расчёт SLA.
* SLA-отчёт доступен и как виджет дашборда.

### Дашборды и карты

* **Dashboard** собирается из виджетов: Graph, Problems, SLA report, Top hosts, Map и др.; поддерживает параметризацию (динамические виджеты) и периоды.
* **Network maps** (Monitoring → Maps) визуализируют топологию: узлы (хосты, группы, триггеры) и связи; цвет отражает состояние. Карты удобны для NOC и дежурной смены.

---

## Практические сценарии

### Предварительные требования

* Для автоматического инвентаря — элементы данных, значения которых нужно класть в поля инвентаря.
* Для scheduled reports — установленный `zabbix-web-service` и Chrome, права Admin/Super admin.
* Для SLA — настроенное дерево услуг и SLO.

### Сценарий 1. Автоматическое наполнение инвентаря

1. Host → Inventory → `Inventory mode` = Automatic.
2. В элементе данных (Item) задать поле `Item will populate host inventory field` (например, `OS`).
3. После поступления значения поле инвентаря заполнится. Проверить: Inventory → Hosts, либо `host.get` с inventory.

### Сценарий 2. Настройка scheduled reports

```ini
# /etc/zabbix/zabbix_server.conf
WebServiceURL=http://localhost:10053/report
StartReportWriters=3
```

```bash
sudo systemctl start zabbix-web-service
sudo systemctl enable zabbix-web-service
# → сервис слушает порт 10053
```

Во фронтенде: Administration → General → Other → `Frontend URL` = полный URL UI.

Создание отчёта: Reports → Scheduled reports → Create report (выбрать дашборд, Period, Cycle, получателей). Проверить получение письма с PDF.

### Сценарий 3. Дерево услуг и SLA

1. Services → создать дерево услуг (родитель/потомки).
2. Задать SLO для услуги (целевое значение, период).
3. Сопоставить проблемы с услугами через теги (`service`), либо настройкой привязки.
4. Открыть Services → SLA → SLA report, выбрать SLA/услугу и период.

### Сценарий 4. Дашборд и карта

1. Dashboards → Create dashboard → добавить виджеты (Graph, Problems, SLA report).
2. Maps → Create map → добавить элементы (хосты/группы) и связи, привязать триггеры к индикации.

### Валидация

```bash
# Проверить, что web service доступен
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:10053/report
# → не 000 (сервис отвечает)

# Проверить, что генерация отчётов включена
zabbix_server -T -c /etc/zabbix/zabbix_server.conf 2>&1 | grep -i StartReportWriters
# → параметр присутствует, если настроен
```

API-проверки: `host.get` с `selectInventory`, `service.get`, `report.get` (scheduled reports).

---

## Операции и команды

```bash
# Список хостов с инвентарём
curl -s -X POST -H 'Content-Type: application/json-rpc' \
  -H 'Authorization: Bearer <TOKEN>' \
  -d '{"jsonrpc":"2.0","method":"host.get","params":{"output":["hostid","host"],"selectInventory":"extend"},"id":1}' \
  http://zabbix.example.com/zabbix/api_jsonrpc.php
# → массив хостов с полями inventory

# Список услуг
# method: service.get, params: {"output":"extend"}
```

| Сущность API | Назначение |
|---|---|
| `host.get` + `selectInventory` | Поля инвентаря хостов |
| `service.get` | Дерево услуг |
| `sla.get` | SLI/SLO |
| `report.get` | Периодические отчёты |

---

## Устранение неисправностей

| Симптом | Причина | Решение |
|---|---|---|
| Инвентарь пуст | Режим `Disabled`/`Manual`, либо нет сопоставления в элементе | Включить `Automatic`/`Manual`, настроить поле в элементе |
| Поле инвентаря не обновляется | Неверно выбрано поле в элементе | Проверить `Item will populate host inventory field` |
| Scheduled report не приходит | `zabbix-web-service` не запущен/не настроен | Запустить сервис, проверить `WebServiceURL`, Chrome |
| Отчёт не генерируется | `StartReportWriters` = 0 или не задан | Задать 1–100 и перезапустить сервер |
| Отчёт не приходит получателю | Нет email media / неверный `Frontend URL` | Заполнить media, задать Frontend URL |
| SLA показывает нарушение SLO при нормальной работе | Неверно заданы SLO/период, либо привязка проблем | Проверить SLO и сопоставление тегов |
| Виджет SLA пуст | Не выбраны SLA/услуга или нет данных за период | Проверить фильтр виджета |

---

## Лучшие практики

* **Инвентарь — через Automatic** с элементами, отдающими статичные данные (производитель, модель, серийник); ручной ввод оставить для исключений.
* **Scheduled reports — плановые отчёты для руководства/заказчика**, а не для дежурных; для дежурных лучше дашборды.
* **SLA строить на тегах услуг**, а не на хардкоде — так масштабируется и меняется без переписывания.
* **Разделять дашборды по аудиториям**: NOC (проблемы, карты), платформенная команда (ресурсы), бизнес (SLA).
* **Использовать `{TIME}`/`{TIMESTAMP}` в темах отчётов** для однозначной идентификации выпуска.
* **Проверять генерацию отчётов после обновления** — Chrome и web service версионно чувствительны.
* **Не дублировать алертинг и отчётность**: алерты — в Zabbix, аналитика — в дашбордах/BI.

---

## Дополнительная информация

### См. также

* [Zabbix — алертинг и эскалация](./zabbix_alerting_and_escalation.md) — условия и получатели уведомлений.
* [Zabbix — триггеры и выражения](./zabbix_triggers.md) — теги для SLA и корреляции.
* [Zabbix — внутреннее устройство и архитектура процессов](./additional_info.md) — процессы report writer.
* [Zabbix — API и автоматизация](./zabbix_api_automation.md) — работа с инвентарём и услугами через API.
* [Zabbix — интеграция с Grafana](./zabbix_grafana_integration.md) — альтернативная визуализация.

### Источники и ссылки

* Zabbix documentation: [Host inventory](https://www.zabbix.com/documentation/7.0/en/manual/config/hosts/inventory)
* Zabbix documentation: [Scheduled reports](https://www.zabbix.com/documentation/7.0/en/manual/config/reports)
* Zabbix documentation: [Setting up scheduled reports](https://www.zabbix.com/documentation/7.0/en/manual/appendix/install/web_service)
* Zabbix documentation: [SLA report](https://www.zabbix.com/documentation/7.0/en/manual/web_interface/frontend_sections/services/sla_report)
