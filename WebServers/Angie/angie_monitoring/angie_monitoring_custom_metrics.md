# Мониторинг Angie — пользовательские метрики

## Определения

**Модуль metric** (`ngx_http_metric_module`) — встроенный компонент веб-сервера Angie (начиная с версии 1.6.0), предназначенный для создания произвольных метрик на основе внутренних переменных сервера. Модуль позволяет собирать и агрегировать данные, недоступные в стандартных зонах мониторинга, включая бизнес-показатели, детальную статистику производительности и распределения (гистограммы).

**Зона метрик (metric_zone)** — именованная область в разделяемой памяти (Shared Memory) для агрегации метрик одного типа (счетчик, гистограмма, среднее и т.д.) по заданному ключу.

**Комплексная зона метрик (metric_complex_zone)** — расширенный тип зоны (появился в версии 1.11.0), позволяющий в рамках одного ключа собирать несколько различных показателей одновременно (например, количество запросов и суммарное время их обработки), что существенно оптимизирует потребление памяти и снижает накладные расходы.

**prometheus_template** — директива Angie, определяющая соответствие внутренних путей API `/status/http/metric_zones/<zone>/metrics/<key>/<metric_name>` именам метрик Prometheus и их типам. Позволяет без промежуточных экспортеров отдавать кастомные бизнес-метрики в текстовом формате Prometheus.

**$p8s_value** — внутренняя переменная шаблона `prometheus_template`, подставляющая актуальное числовое значение метрики, возвращаемое API для конкретного ключа и имени метрики.

**discard_key** — параметр директивы `metric_zone`, задающий имя ключа, в котором агрегируются значения удаляемых (expired) записей при переполнении памяти. Это позволяет сохранять общую сумму при очистке, вместо полной потери данных.

## Базовые концепции

### Архитектура сбора данных

Кастомные метрики в Angie организованы по иерархическому принципу:

```
[ Воркер Angie ] → (запись в Shared Memory) → [ metric_zone / metric_complex_zone ]
                                                      ↓
                                              [ API /status/http/metric_zones/ ]
                                                      ↓
                                         [ prometheus_template ] → [ Prometheus ]
```

1. **Объявление зоны:** В контексте `http` директива `metric_zone` или `metric_complex_zone` резервирует именованную область в разделяемой памяти с заданным размером и типом агрегации.
2. **Сбор:** Воркеры Angie вызывают директиву `metric` при обработке запроса или события и атомарно обновляют счетчики в разделяемой памяти.
3. **Чтение через API:** Любой клиент (curl, скрипт, Prometheus) может получить JSON с текущими значениями через `/status/http/metric_zones/<zone>/metrics/<key>/<metric_name>`.
4. **Экспорт в Prometheus:** Директива `prometheus_template` сопоставляет пути API с именами метрик Prometheus. При HTTP GET к указанному `location` Angie формирует ответ в текстовом формате Prometheus.

### Lifecycle метрики

1. **Создание:** При старте Angie модуль `ngx_http_metric_module` создает дескрипторы зон на основе конфигурации. Размер зоны задается в конфигурации (например, `metric_zone browsers:2m` — 2 МБ).
2. **Сбор:** Воркеры инкрементируют/обновляют значения при каждом событии (запрос, соединение, таймер). Операции выполняются атомарно (lock-free).
3. **Хранение:** Значения удерживаются в разделяемой памяти. При переполнении, если `expire=on`, удаляются самые старые записи (LRU), а их значения агрегируются в `discard_key`.
4. **Экспорт:** При запросе API или Prometheus-скрапинга модуль считывает текущие значения и форматирует их.
5. **Удаление:** При `stop/start` разделяемая память освобождается, все метрики сбрасываются. При `reload` метрики сохраняются.

### Параметры зон и управление памятью

При объявлении зон доступны параметры, управляющие их жизненным циклом и точностью вычислений:

- **expire=on | off**: определяет поведение при переполнении памяти. 
  - `on`: автоматически удаляет самые старые записи (LRU).
  - `off` (по умолчанию): прекращает запись новых ключей до освобождения места.
- **discard_key=имя**: специальный ключ, в котором будут агрегироваться значения удаляемых (expired) записей, что позволяет сохранять общую сумму при очистке памяти.
- **average=mean | exp**: алгоритм расчета среднего.
  - `mean`: среднее арифметическое.
  - `exp`: экспоненциальное скользящее среднее (EMA).
  - **window**: временное окно (например, `15s`) для расчета.
  - **count**: количество последних значений для учета.

**Технические характеристики (Memory Overhead):**
- Накладные расходы на каждую уникальную запись (ключ): ~128 байт.
- Каждая простая метрика в зоне: +8 байт.
- Гистограмма: +8 байт на каждый бакет (+1 технический бакет).
- В зоне объемом 1 МБ при среднем размере ключа в 40 байт может храниться от 6 000 до 8 000 уникальных записей.

### Типы агрегации

1. **count** — инкрементальный счетчик событий.
2. **sum** — накопление суммы значений.
3. **gauge** — текущее значение (поддерживает увеличение и уменьшение).
4. **histogram** — распределение значений по интервалам (бакетам).
5. **average** — расчет среднего значения (`mean` или `exp`).
6. **min / max** — фиксация минимального или максимального значения за период.
7. **last** — сохранение только последнего полученного значения.

### Моменты срабатывания (Phase control)

Директива `metric` поддерживает параметр `on`:
- **on=request** — срабатывает сразу после получения заголовков. Подходит для метрик на основе входных данных (URI, User-Agent).
- **on=end** (по умолчанию) — срабатывает в фазе логирования. Используется для метрик времени ответа, статусов и объема трафика.

### Регистрация метрик в Prometheus

Для экспорта кастомных метрик в Prometheus используется директива `prometheus_template`, которая связывает пути API с именами метрик:

```nginx
prometheus_template advanced_metrics {
    'angie_shop_revenue_total{shop_id="$1"}' $p8s_value 
        path=~^/http/metric_zones/shop_stats/metrics/([^/]+)/total_revenue$ 
        type=counter;

    'angie_http_vhost_latency_avg{host="$1"}' $p8s_value 
        path=~^/http/metric_zones/geo_latency/metrics/([^/]+)$ 
        type=gauge;
}
```

**Правила именования:**
- Префикс `angie_` используется для всех стандартных метрик.
- Для кастомных метрик рекомендуется использовать осмысленные префиксы (например, `angie_shop_`, `angie_api_`).
- Метка `key` автоматически добавляется к метрикам из `metric_zone` со значением ключа агрегации.
- В `prometheus_template` регулярное выражение `path` позволяет извлекать части пути как метки (например, `$1` для `shop_id`).

## Практические сценарии

### Сценарий 1: Анализ аудитории по типам браузеров

```nginx
http {
    # Резервируем 2МБ под счетчики браузеров с автоматической очисткой
    metric_zone browsers:2m count expire=on;

    server {
        # Группировка по User-Agent на фазе запроса
        metric browsers $http_user_agent on=request;
    }
}
```

**Валидация:**
```bash
curl -s http://localhost:8888/status/http/metric_zones/browsers/metrics/ | jq keys | head -n 10
# → ["Chrome/120.0", "Firefox/121.0", "Safari/605.1.15", ...]

curl -s http://localhost:8888/status/http/metric_zones/browsers/metrics/Chrome/ | jq .
# → {"count": 5432}
```

### Сценарий 2: Расчет среднего времени ответа по странам (GeoIP2)

```nginx
http {
    # Скользящее среднее по странам
    metric_zone geo_latency:1m average mean window=30s;

    server {
        location / {
            metric geo_latency $geoip2_country_iso_code=$request_time on=end;
        }
    }
}
```

**Валидация:**
```bash
curl -s http://localhost:8888/status/http/metric_zones/geo_latency/metrics/RU/ | jq .
# → {"average": 0.142}
```

### Сценарий 3: Расчет индекса удовлетворенности APDEX

APDEX оценивает качество сервиса на основе бакетов времени.

```nginx
http {
    # Целевое время 1.5с, допустимое 4с
    metric_zone satisfaction:2m histogram 1.5 4.0;

    server {
        location /api/ {
            metric satisfaction $server_name=$request_time;
        }
    }
}
```

**Валидация:**
```bash
curl -s http://localhost:8888/status/http/metric_zones/satisfaction/metrics/prod.example.com/ | jq .
# → {"histogram": {"1.5": 1200, "4.0": 300, "Inf": 50}}
```

### Сценарий 4: Сбор бизнес-метрик с использованием Комплексных зон и Lua

Использование `metric_complex_zone` для минимизации обращений к памяти при записи нескольких метрик.

```nginx
http {
    metric_complex_zone shop_stats:10m {
        total_revenue sum;
        items_sold    sum;
        orders_count  count;
    }
}

server {
    location /order {
        set $revenue 0;
        set $items 0;
        
        access_by_lua_block {
            ngx.req.read_body()
            local body = ngx.req.get_body_data()
            if body then
                local data = require("cjson").decode(body)
                ngx.var.revenue = data.price or 0
                ngx.var.items = data.quantity or 0
            end
        }
        
        # Обновление нескольких метрик для одного ключа за один вызов
        metric shop_stats "global"=total_revenue:$revenue;
        metric shop_stats "global"=items_sold:$items;
        metric shop_stats "global"=orders_count:1;
        
        proxy_pass http://backend;
    }
}
```

**Валидация:**
```bash
curl -s http://localhost:8888/status/http/metric_zones/shop_stats/metrics/global/ | jq .
# → {
# →   "total_revenue": 152340.50,
# →   "items_sold": 1240,
# →   "orders_count": 87
# → }
```

### Сценарий 5: Экспорт в Prometheus через кастомные шаблоны

Для вывода данных в Prometheus необходимо связать пути API Angie с именами метрик.

```nginx
# Определение структуры экспорта
prometheus_template advanced_metrics {
    # $p8s_value — переменная, подставляющая значение из API
    # $1 — захват из регулярного выражения пути (название ключа)
    
    'angie_shop_revenue_total{shop_id="$1"}' $p8s_value 
        path=~^/http/metric_zones/shop_stats/metrics/([^/]+)/total_revenue$ 
        type=counter;

    'angie_http_vhost_latency_avg{host="$1"}' $p8s_value 
        path=~^/http/metric_zones/geo_latency/metrics/([^/]+)$ 
        type=gauge;
}

http {
    server {
        location /p8s {
            prometheus advanced_metrics;
            allow 127.0.0.1;
            deny all;
        }
    }
}
```

**Валидация через Prometheus:**
```bash
curl -s http://localhost/p8s | grep 'angie_shop_revenue_total'
# → angie_shop_revenue_total{shop_id="global"} 152340.50

# Проверка через promtool
curl -s http://localhost/p8s | promtool check metrics /dev/stdin
# → SUCCESS
```

### Сценарий 6: Валидация метрик перед подключением к Prometheus

Перед добавлением в Prometheus проверьте корректность данных через API:

```bash
# 1. Проверка наличия зоны
curl -s http://localhost:8888/status/http/metric_zones/ | jq keys
# → ["browsers", "geo_latency", "satisfaction", "shop_stats"]

# 2. Проверка конкретного ключа
curl -s http://localhost:8888/status/http/metric_zones/shop_stats/metrics/global/ | jq .

# 3. Проверка вывода Prometheus
curl -s http://localhost/p8s | grep '^angie_' | wc -l
# → 12

# 4. Проверка типов метрик
curl -s http://localhost/p8s | grep -E '^# TYPE'
# → # TYPE angie_shop_revenue_total counter
# → # TYPE angie_http_vhost_latency_avg gauge
```

### Сценарий 7: Мониторинг эффективности кэша через кастомную гистограмму

Использование `metric_zone` для отслеживания размера кэшируемых объектов.

```nginx
http {
    # Гистограмма размеров объектов: 1KB, 10KB, 100KB, 1MB
    metric_zone object_size:5m histogram 1024 10240 102400 1048576;

    server {
        location / {
            set $size $content_length;
            metric object_size $size;
            proxy_pass http://backend;
        }
    }
}
```

**Валидация:**
```bash
curl -s http://localhost:8888/status/http/metric_zones/object_size/metrics/ | jq 'keys_unsorted[0:5]'
# → ["1024", "10240", "102400", "1048576", "Inf"]
```

### Сценарий 8: Отладка метрик через JSON API при расследовании инцидентов

```bash
#!/bin/bash
# /usr/local/bin/check_metric_zones.sh

ZONES_API="http://localhost:8888/status/http/metric_zones/"

# Получение списка всех зон
zones=$(curl -sf "$ZONES_API" | jq -r 'keys[]')

for zone in $zones; do
    count=$(curl -sf "$ZONES_API$zone/metrics/" | jq 'length')
    echo "Zone: $zone, keys: $count"
    
    if [ "$count" -eq 0 ]; then
        echo "WARNING: Zone $zone is empty"
    fi
done
```

**Использование:**
```bash
chmod +x /usr/local/bin/check_metric_zones.sh
./check_metric_zones.sh
# → Zone: browsers, keys: 145
# → Zone: geo_latency, keys: 42
# → Zone: satisfaction, keys: 0
# → WARNING: Zone satisfaction is empty
```

## Операции и команды

### Проверка метрик через API

```bash
# Список всех зон метрик
curl -s http://localhost:8888/status/http/metric_zones/ | jq keys
# → ["browsers", "geo_latency", "shop_stats"]

# Статистика конкретной зоны (список ключей и количество записей)
curl -s http://localhost:8888/status/http/metric_zones/browsers/metrics/ | jq '{
    total_keys: length,
    sample_keys: (keys_unsorted[0:5])
}'
# → {
# →   "total_keys": 145,
# →   "sample_keys": ["Chrome/120.0", "Firefox/121.0", "Safari/605.1.15"]
# → }

# Значения метрик для конкретного ключа
curl -s http://localhost:8888/status/http/metric_zones/shop_stats/metrics/global/ | jq .
# → {"total_revenue": 152340.50, "items_sold": 1240, "orders_count": 87}

# Проверка состояния разделяемой памяти для зоны
curl -s http://localhost:8888/status/slabs/shop_stats/ | jq .
```

### Проверка вывода Prometheus

```bash
# Подсчет количества уникальных метрик
curl -s http://localhost/p8s | grep -E '^[a-z_]+{' | wc -l
# → 12

# Проверка конкретной метрики
curl -s http://localhost/p8s | grep '^angie_shop_revenue_total'
# → angie_shop_revenue_total{shop_id="global"} 152340.50

# Проверка типа метрики
curl -s http://localhost/p8s | grep -E '^# TYPE angie_shop_revenue_total'
# → # TYPE angie_shop_revenue_total counter

# Проверка гистограммы (наличие бакетов)
curl -s http://localhost/p8s | grep 'angie_metric_rt_hist_bucket'
# → angie_metric_rt_hist_bucket{le="0.05"} 120
# → angie_metric_rt_hist_bucket{le="0.1"} 350
# → angie_metric_rt_hist_bucket{le="+Inf"} 500

# Проверка фильтрации по статусу
curl -s 'http://localhost/p8s?status=5xx' | head -n 5
# → HELP angie_http_responses_total ...
# → TYPE angie_http_responses_total counter
# → angie_http_responses_total{status="500"} 3
```

### Проверка конфигурации Angie

```bash
# Проверка включен ли модуль metric
angie -V 2>&1 | grep -o 'http_metric_module'
# → --with-http_metric_module=dynamic

# Проверка наличия директив metric_zone и prometheus_template
angie -T | grep -E 'metric_zone|metric_complex_zone|prometheus_template'
# → metric_zone browsers:2m count expire=on;
# → metric_complex_zone shop_stats:10m { ... };
# → prometheus_template advanced_metrics { ... };
```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
|:---|:---|:---|
| **Ошибка: `unknown directive "metric_zone"`** | Модуль `ngx_http_metric_module` не загружен или не включен в сборку. | Проверьте вывод `angie -V` на наличие `--with-http_metric_module`. В официальных пакетах модуль включен по умолчанию. |
| **Зона метрик пустая (0 ключей)** | Директива `metric` не срабатывает или переменная пустая. | Проверьте `on=request`/`on=end` и что переменная (`$http_user_agent`, `$request_time`) содержит значение. |
| **Метрики отсутствуют в Prometheus** | `prometheus_template` не настроен или путь не совпадает. | Убедитесь, что `path=~` в шаблоне соответствует реальному пути API, и что метрика включена в `location /p8s`. |
| **Высокое потребление памяти** | Создано слишком много уникальных ключей (высокая кардинальность). | Ограничьте длину ключа (например, обрежьте User-Agent), используйте агрегацию или увеличьте размер зоны. |
| **Ключи обрезаются** | Длина ключа превышает 255 символов. | Используйте `map` для сокращения переменной перед записью в метрику. |
| **Метрики сбрасываются при restart** | Разделяемая память resides в RAM. | Это ожидаемое поведение. Для персистентности используйте внешние системы сбора (Prometheus). |
| **Тип метрики в Prometheus неверный** | В `prometheus_template` указан неверный `type` (например, `gauge` вместо `counter`). | Убедитесь, что `type` соответствует семантике: `counter` для монотонно растущих значений, `gauge` для текущих. |
| **Expired записи не удаляются** | `expire` не включен или размер зоны слишком велик для LRU. | Установите `expire=on` и следите за использованием памяти через `/status/slabs/`. |
| **discard_key не работает** | Ключ `discard_key` не объявлен как метрика или имеет неверное имя. | Добавьте `metric discard_key <zone> <metric_name>;` для агрегации удаленных значений. |

## Лучшие практики

### Безопасность

1. **Ограничивайте доступ к эндпоинтам метрик** по IP или через внутреннюю сеть. Минимальная конфигурация:
    ```nginx
    location = /p8s {
        prometheus all;
        allow 10.0.10.5;
        deny all;
    }
    ```
2. **Используйте TLS** при доступе к метрикам через ненадежные каналы.
3. **Не экспортируйте метрики на публичные интерфейсы.** Даже без аутентификации метрики раскрывают топологию и нагрузки.

### Производительность

1. **Размер зон:** выделяйте память с запасом. Для гистограмм с большим количеством ключей рекомендуется от 1 МБ до 10 МБ на зону.
2. **expire=on:** используйте для зон с высокой оборачиваемостью ключей (например, по User-Agent), чтобы избежать зависания записи при переполнении.
3. **discard_key:** применяйте, когда важно сохранять общую сумму даже при потере детализации (например, общий revenue при удалении старых записей).
4. **Cardinality:** избегайте высококардинальных ключей. Максимальная длина ключа — 255 символов; слишком длинные ключи обрезаются без предупреждения.
5. **metric_complex_zone:** используйте вместо нескольких `metric_zone` для одного логического объекта (например, заказа), чтобы сократить обращения к памяти.

### Эксплуатация

1. **Именование ключей:** используйте осмысленные ключи (`api_v1`, `static_files`) вместо необработанных URI или полных User-Agent.
2. **Верификация после изменений:** после добавления новых `metric_zone` проверяйте появление ключей через API: `curl -s http://localhost:8888/status/http/metric_zones/<zone>/metrics/ | jq keys`.
3. **Валидация Prometheus:** после настройки `prometheus_template` проверяйте вывод через `promtool check metrics`.
4. **Мониторинг памяти:** регулярно проверяйте `/status/slabs/<zone>/` для контроля использования разделяемой памяти.

### Отладка

1. **Сравнение API и Prometheus:** при расхождениях проверяйте, что `path` в `prometheus_template` точно соответствует пути API.
2. **Проверка переменных:** используйте `metric on=request` для отладки входных переменных (User-Agent, URI), проверяя их через API.
3. **Логи Angie:** при проблемах с модулем проверяйте `error.log` на наличие `metric`:
    ```bash
    grep -i metric /var/log/angie/error.log | tail -20
    ```

## Дополнительная информация

### Визуализация

Для кастомных метрик в Grafana можно использовать готовые панели или создавать собственные дашборды на основе PromQL-запросов к `angie_*` метрикам.

### Производительность

Нативный модуль `ngx_http_metric_module` работает в процессе воркеров и использует атомарные операции (lock-free) для обновления счетчиков. Это обеспечивает минимальный overhead даже при высокой частоте событий. Внешние агенты (sidecar-экспортеры) потребляют дополнительные ресурсы CPU и памяти, так как требуют парсинга access-логов или JSON API.

### Сравнение инструментов

| Характеристика | metric_zone + API | metric_zone + Prometheus | Console Light |
|:---|:---|:---|:---|
| **Гранулярность** | Реал-тайм (~1 сек через API) | Зависит от scrape_interval (от 15s) | Реал-тайм (~1 сек) |
| **История** | Нет | Месяцы/годы (TSDB) | Нет |
| **Масштаб** | Один узел | Весь кластер | Один узел |
| **Алертинг** | Через внешние системы | Нативный (Alertmanager) | Отсутствует |
| **Типы метрик** | Любые (count, sum, gauge, histogram, average) | counter, gauge, histogram, summary | Стандартные зоны API |
| **Overhead** | Минимальный | Зависит от частоты скрапинга | Минимальный (браузер опрашивает API) |
| **Назначение** | Оперативная отладка, бизнес-метрики | Тренды, Capacity Planning, SLA | Оперативная отладка |

### Ограничения

1. **Pull-модель для Prometheus:** метрики доступны только при активном скрапинге. При недоступности Angie данные не собираются.
2. **Cardinality:** каждая уникальная комбинация ключей создает отдельную временную серию. При высокой кардинальности TSDB быстро растет.
3. **Один источник:** стандартный модуль metric покрывает только пользовательские зоны Angie. Для метрик ОС (CPU, RAM, disk I/O) требуется отдельный `node_exporter`.
4. **Отсутствие истории при restart:** метрики в разделяемой памяти сбрасываются при `stop/start`. Это не влияет на Prometheus TSDB, но может создавать "провалы" на графиках.
5. **Максимальная длина ключа:** 255 символов. При превышении ключи обрезаются без предупреждения.
6. **Типы метрик:** модуль metric поддерживает richer типы (average, min/max, last), которые не имеют прямого соответствия в Prometheus. При экспорте через `prometheus_template` используйте `gauge` для средних и экстремумов.

### Связанные технологии

- **[Основные концепции мониторинга](./angie_monitoring_concepts.md)** — определения `status_zone`, `metric_zone`, расчет памяти
- **[Интеграция с Prometheus](./angie_monitoring_prometheus.md)** — `prometheus_template`, `prometheus_all.conf`, нативный экспорт
- **[Возможности Angie Pro](./angie_monitoring_pro.md)** — динамическое управление весами, `upstream_probe`, `keyval_zone`
- **[Работа с конфигурацией через API](./angie_monitoring_api.md)** — полная таблица эндпоинтов, JSON-схемы
- **[Настройка Console Light и API](./angie_monitoring_console.md)** — веб-интерфейс для оперативного контроля

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md)
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md)
- [Возможности Angie Pro](./angie_monitoring_pro.md)
- [Работа с конфигурацией через API](./angie_monitoring_api.md)
- [Настройка Console Light и API](./angie_monitoring_console.md)
