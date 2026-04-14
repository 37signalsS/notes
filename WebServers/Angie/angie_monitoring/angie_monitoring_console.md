# Мониторинг Angie — Console Lite и API

## Определения

**Angie Console Lite** — бесплатный веб-интерфейс для интерактивного мониторинга метрик Angie в реальном времени. Предоставляет визуализацию данных из HTTP API без необходимости настройки внешних систем (Prometheus, Grafana).

**HTTP API мониторинга** — встроенный интерфейс Angie, отдающий метрики в формате JSON. Доступен через директиву `api` и предоставляет данные о запросах, соединениях, upstream-серверах, кэше, зонах статуса и пользовательских метриках.

## Базовые концепции

### Архитектура взаимодействия

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   Browser   │─────>│ Console Lite │─────>│  Angie API  │
│  (UI)       │      │  (HTML/JS)   │      │  (/status/) │
└─────────────┘      └──────────────┘      └─────────────┘
```

- **Console Lite** — статические HTML/JS файлы, обращающиеся к API каждую секунду
- **API эндпоинт** — директива `api`, указывающая путь к данным (обычно `/status/`)
- **Прямой доступ** — можно обращаться к API напрямую через `curl` без Console Lite

### Отличие от Prometheus

| Характеристика | Console Lite / API | Prometheus |
|:---------------|:-------------------|:-----------|
| **Актуальность** | Реальное время (обновление ~1 сек) | С интервалом scrape (15–30 сек) |
| **Хранение** | Только текущие значения | Исторические данные |
| **Назначение** | Оперативная диагностика | Тренды, алерты, дашборды |
| **Зависимости** | Только Angie | Prometheus, Grafana |

### Безопасность

API отдаёт внутренние метрики сервера, поэтому **обязательна** защита от публичного доступа:

- Ограничение по IP (`allow` / `deny`)
- Использование SSL/TLS
- Закрытие порта файрволом

## Практические сценарии

### Сценарий 1: Установка Console Lite

Установите пакет `angie-console-lite` через пакетный менеджер после [базовой установки Angie](../angie_installation.md).

```bash
# Ubuntu/Debian
sudo apt-get install angie-console-lite

# RHEL/AlmaLinux
sudo dnf install angie-console-lite
```

Файлы консоли устанавливаются в `/usr/share/angie-console-lite/html`.

### Сценарий 2: Настройка эндпоинтов

Создайте отдельный `server` блок для мониторинга, защитив его от публичного доступа.

```nginx
server {
    listen 8888;
    server_name monitor.example.com;

    # Рекомендуется использовать SSL и ограничение по IP
    # ssl_certificate /etc/ssl/certs/monitor.pem;
    # ssl_certificate_key /etc/ssl/private/monitor.key;
    # allow 192.168.1.0/24;
    # allow 10.0.0.0/8;
    # deny all;

    # Обслуживание файлов Angie Console Lite
    location /console {
        alias /usr/share/angie-console-lite/html;
        index index.html;

        # Вложенный location для проксирования запросов от консоли к API
        location /console/api/ {
            # /status/ — это эндпоинт API из другого location блока
            api /status/;
        }
    }

    # Основной эндпоинт Angie API
    location /status/ {
        api;
        # allow 127.0.0.1;
        # deny all;
    }
}
```

**Важно:** Вложенный `location /console/api/` необходим, чтобы Console Lite мог обращаться к API без CORS-ограничений.

### Сценарий 3: Анализ данных

**Веб-интерфейс Console Lite:**

Откройте `http://monitor.example.com:8888/console` для просмотра статистики.

- Демо-версия: [console.angie.software](https://console.angie.software/)
- Обновление данных: ~1 секунда
- Доступные метрики: запросы, соединения, upstream-серверы, кэш, зоны статуса

**Прямой доступ к API:**

```bash
# Получение всех метрик
curl -s http://monitor.example.com:8888/status/ | jq

# Метрики по конкретному upstream
curl -s http://monitor.example.com:8888/status/upstreams/backend/ | jq

# Активные соединения
curl -s http://monitor.example.com:8888/status/connections/ | jq
# → {
#   "active": 42,
#   "idle": 15,
#   "accepted": 15234,
#   "dropped": 3
# }
```

## Дополнительная информация

### Версионность

- Console Lite доступен начиная с Angie 1.5.0
- Пакет `angie-console-lite` устанавливается отдельно от основного пакета

### Ограничения Console Lite

- Не хранит исторические данные (только текущее состояние)
- Не поддерживает настройку алертов
- Для долгосрочного хранения и визуализации используйте [интеграцию с Prometheus](./angie_monitoring_prometheus.md)

### Динамическая конфигурация (Angie Pro)

В коммерческой версии Angie Pro API поддерживает запись (`write=on` в директиве `api`), что позволяет через Console Lite или `curl` управлять состоянием серверов в upstream-группах (помечать как down, изменять вес).

Подробнее: [Функции Angie Pro](./angie_monitoring_pro.md).

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md)
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md)
- [Работа с конфигурацией через API](./angie_monitoring_api.md)
