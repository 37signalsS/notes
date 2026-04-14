# Мониторинг Angie — Возможности Angie Pro

## Определения

**Angie Pro** — коммерческая версия веб-сервера Angie с расширенными возможностями мониторинга, управления конфигурацией и технической поддержкой. Включает все функции Open Source версии плюс дополнительные инструменты для enterprise-эксплуатации.

## Базовые концепции

### Отличия мониторинга в Angie Pro от Open Source

| Функция | Open Source | Angie Pro |
|:--------|:------------|:----------|
| Динамическое управление `upstream` | Нет | Да, через API с `write=on` |
| Время ответа от апстрима (`upstream response time`) | Нет | Да, встроенная метрика |
| Активные health checks (`health_check`) | Нет | Да |
| Модуль `metric` для пользовательских метрик | Да | Да |
| Console Lite | Да | Да |

### Динамическое управление upstream

В Angie Pro директива `api` поддерживает параметр `write=on`, который разрешает запись через API. Это позволяет:

- Помечать серверы в upstream-группе как `down` без перезагрузки конфигурации
- Изменять вес (`weight`) серверов для плавного перераспределения трафика
- Интегрировать с системами обнаружения сервисов (service discovery)

### Расширенные метрики производительности

Angie Pro экспортирует дополнительные метрики через API, включая **время ответа от апстрима (`upstream response time`)**. В Open Source версии эту метрику можно эмулировать вручную через модуль `metric` (см. [создание пользовательских метрик](./angie_monitoring_custom_metrics.md)), но в Pro она доступна «из коробки».

## Практические сценарии

### Сценарий 1: Включение записи в API для динамического управления upstream

```nginx
http {
    # Включение режима записи
    api write=on;

    upstream backend {
        server 192.168.1.10:8080;
        server 192.168.1.11:8080;
        server 192.168.1.12:8080;
    }
}
```

Пометить сервер как `down` через API:

```bash
curl -X POST http://monitor.example.com:8888/status/upstreams/backend/servers/192.168.1.12:8080/down
# → { "state": "down" }
```

Вернуть сервер в строй:

```bash
curl -X DELETE http://monitor.example.com:8888/status/upstreams/backend/servers/192.168.1.12:8080/down
# → { "state": "up" }
```

### Сценарий 2: Изменение веса сервера через API

Для плавного перераспределения нагрузки (например, перед обслуживанием сервера):

```bash
# Установить вес сервера в 2 раза меньше
curl -X PUT http://monitor.example.com:8888/status/upstreams/backend/servers/192.168.1.10:8080 \
  -H "Content-Type: application/json" \
  -d '{"weight": 5}'
# → { "weight": 5, "state": "up" }
```

### Сценарий 3: Использование метрик upstream response time

В Angie Pro метрика времени ответа от апстрима доступна через API без дополнительной настройки:

```bash
curl -s http://monitor.example.com:8888/status/upstreams/backend/ | jq '.response_time'
# → { "mean": 45, "msec": 1712934000.123 }
```

## Дополнительная информация

### Версионность

- Динамическое управление `upstream` через API — Angie Pro начиная с версии 1.5.0
- Расширенные метрики производительности — Angie Pro, версия 1.6.0+

### Ограничения Open Source версии

Пользователи Open Source версии могут получить схожую функциональность через модуль `metric`:

- Время ответа от апстрима: `metric response_time $upstream_response_time on=end;`
- Статус серверов в upstream — только через ручной анализ логов или внешние health checks

Подробнее: [Создание пользовательских метрик](./angie_monitoring_custom_metrics.md).

---

**См. также:**

- [Настройка Console Lite и API](./angie_monitoring_console.md)
- [Создание пользовательских метрик](./angie_monitoring_custom_metrics.md)
