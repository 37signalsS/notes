# Мониторинг Angie — пользовательские метрики

## Определения

**Модуль metric** — встроенный компонент Angie для создания произвольных метрик на основе переменных сервера. Позволяет собирать данные, недоступные в стандартных зонах мониторинга, включая бизнес-показатели и расширенную статистику производительности.

**Зона метрик (metric_zone)** — именованная область в разделяемой памяти для агрегации метрик одного типа: счетчик (count), среднее значение (average) или гистограмма (histogram).

### Параметры зоны метрик
- **expire** — время жизни записи в зоне. Позволяет автоматически удалять устаревшие данные при переполнении памяти.
- **average** — определяет способ расчета среднего (например, `mean`).
    - **window** — временное окно для расчета среднего (например, 15 секунд).
    - **count** — количество последних значений для расчета среднего (например, последние 20 запросов).

**Комплексная зона метрик (metric_complex_zone)** — область памяти для одновременного сбора нескольких типов метрик (например, количество и средний размер) по одному ключу.

## Базовые концепции

### Типы агрегации

1. **count** — подсчет количества событий (например, число запросов).
2. **average** — расчет среднего арифметического или экспоненциального среднего.
3. **histogram** — распределение значений по заданным интервалам (бакетам).

### Моменты срабатывания

Директива `metric` поддерживает параметр `on`, определяющий фазу обработки запроса:

- **on=request** — срабатывает при получении заголовков. Подходит для метрик на основе URI (Uniform Resource Identifier), User-Agent или других данных запроса.
- **on=end** — срабатывает после завершения обработки. Используется для метрик времени ответа, статусов и размеров переданных данных.

### Влияние на производительность

Сбор метрик через модуль `metric` оптимизирован и оказывает минимальное влияние на CPU (Central Processing Unit). Основные задержки могут возникнуть при использовании сложных скриптов Lua для предварительной обработки данных перед записью в метрику.

### Версионность

Функционал модулей `metric` и `metric_complex_zone` доступен в Angie начиная с версии 1.6.0.

## Практические сценарии

### Сценарий 1: Подсчет запросов по типам браузеров

Для анализа аудитории можно использовать заголовок User-Agent.

```nginx
http {
    # Резервируем 1МБ под счетчики браузеров
    metric_zone browsers:1m count;

    server {
        # Увеличиваем счетчик для каждого уникального User-Agent
        metric browsers $http_user_agent on=request;
    }
}
```

Данные доступны через HTTP (HyperText Transfer Protocol) API (Application Programming Interface) в формате JSON (JavaScript Object Notation).

### Сценарий 2: Расчет среднего времени ответа по регионам

Использование переменной из модуля GeoIP2 для анализа задержек в разных странах.

```nginx
http {
    metric_zone geo_latency:1m average mean;

    server {
        location / {
            # Записываем время ответа по ISO (International Organization for Standardization) коду страны
            metric geo_latency $geoip2_country_iso_code=$request_time on=end;
        }
    }
}
```

### Сценарий 3: Расчет индекса удовлетворенности APDEX

APDEX (Application Performance Index) позволяет оценить качество работы сервиса на основе времени ответа.

```nginx
http {
    # Гистограмма с бакетами 2с (целевое время) и 8с (допустимое)
    metric_zone satisfaction:1m histogram 2 8 inf;

    server {
        location /api/ {
            metric satisfaction satisfaction=$request_time;
        }
    }
}
```

Для визуализации данных рекомендуется использовать [интеграцию с Prometheus](./angie_monitoring_prometheus.md).

### Сценарий 4: Сбор бизнес-метрик с помощью Lua

Парсинг тела POST-запроса для подсчета количества заказанных товаров.

```nginx
http {
    metric_complex_zone shop_stats:1m {
        total_items  sum gauge;
        orders_count count;
    }
}

server {
    location /order {
        set $qty '';
        access_by_lua_block {
            ngx.req.read_body()
            local body = ngx.req.get_body_data()
            if body then
                -- Пример извлечения количества из JSON
                local quantity = body:match('"quantity":(%d+)')
                ngx.var.qty = quantity
            end
        }
        metric shop_stats "total"=$qty on=request;
        proxy_pass http://backend;
    }
}
```

### Сценарий 5: Комплексный мониторинг времени ответа (End-to-End)

Этот сценарий описывает создание метрик для отслеживания среднего времени ответа (Response Time) в разрезе доменов и апстримов.

#### 1. Определение зон в http-блоке
```nginx
http {
    # Среднее время по доменам (окно 15с)
    metric_zone Hist:1m average mean window=15s expire=30s;
    
    # Среднее время по апстримам (окно 15с или последние 20 запросов)
    metric_zone upstream_time:1m average mean window=15s count=20;

    # Сбор метрики по апстримам на уровне http
    metric upstream_time $upstream_addr=$upstream_response_time on=end;
}
```

#### 2. Сбор метрики для конкретного сайта
```nginx
server {
    server_name example.com;
    location / {
        proxy_pass http://backend;
        # Сбор метрики по имени сервера
        metric Hist $server_name=$request_time on=end;
    }
}
```

#### 3. Настройка шаблона Prometheus
Для экспорта кастомных метрик необходимо отредактировать файл конфигурации шаблонов (например, `prometheus_all.conf`). В блок `prometheus_template all` добавляются правила сопоставления путей API и метрик Prometheus.

```nginx
# Пример добавления в prometheus_template
# Метрика времени ответа сервера
angie_http_response_time_stats{server_name="$1"} $2 /http/metrics/zones/Hist/metrics/(.*) average_mean;

# Метрика времени ответа апстрима
angie_http_upstreams_response_time_stats{upstream_addr="$1"} $2 /http/metrics/zones/upstream_time/metrics/(.*) average_mean;
```

#### 4. Визуализация в Grafana
1. Создайте копию существующего графика (например, "Upstream Requests").
2. В поле запроса (Query) укажите название новой метрики: `angie_http_response_time_stats`.
3. В настройках легенды (Legend) используйте метки: `{{server_name}}` или `{{upstream_addr}}`.
4. Настройте формат отображения (Unit) как "Seconds (s)" или "Milliseconds (ms)".

## Дополнительная информация

### См. также

- [Основные концепции мониторинга](./angie_monitoring_concepts.md)
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md)
- [Возможности Angie Pro](./angie_monitoring_pro.md)
