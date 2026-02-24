# Мониторинг Angie

## Определения

**Мониторинг Angie** — это процесс сбора, анализа и визуализации метрик производительности и состояния веб-сервера. В отличие от устаревшего модуля `stub_status` в NGINX, Angie предоставляет мощный встроенный **JSON API**, открывающий доступ к сотням метрик в реальном времени.

Дополнительно, Angie предлагает **модуль `metric`**, который позволяет создавать произвольные пользовательские метрики на основе любых переменных запроса, что стирает грань между инфраструктурным и бизнес-мониторингом.

## Основные концепции

### API-мониторинг реального времени vs. анализ логов

Традиционный подход к мониторингу веб-сервера через анализ логов имеет фундаментальные недостатки, которые решает нативный API в Angie:

1. **Ретроспективность логов**: Логи записываются *после* завершения обработки запроса. Это не позволяет отслеживать долгоживущие соединения, медленных клиентов или видеть начало DoS-атаки, когда запросы только начинают накапливаться. API, в свою очередь, показывает метрику `processing` (активные запросы) в реальном времени.
2. **Неполнота данных**: Логи не содержат информации о состоянии внутренних механизмов, таких как **зоны разделяемой памяти** (`slab`) или **зоны кэширования**. Их переполнение может привести к сбоям и недоступности сервиса. API предоставляет полный доступ к этим метрикам.
3. **Неточность и задержки**: Сторонние модули, такие как `vts`, также часто работают в лог-фазе, то есть считают метрики по окончании запроса, что делает их подверженными тем же недостаткам, что и анализ логов. Встроенный API в Angie предоставляет более точные значения непосредственно из рантайма.

### Подходы к мониторингу

1. **Интерактивный мониторинг**: Использование встроенного веб-интерфейса **Angie Console Light** и прямого доступа к **HTTP API** для быстрого обзора состояния сервера в реальном времени.
2. **Долгосрочная аналитика**: Сбор, хранение и визуализация метрик с помощью [**Prometheus**](../../Prometheus/overview.md) и [**Grafana**](../../Grafana/grafana_overview.md) для анализа тенденций и настройки оповещений.

**Баланс между реальным временем и хранением:**

- **Console Light** обращается к API каждую секунду, предоставляя максимально актуальные данные, что идеально для оперативной диагностики.
- **Prometheus** собирает метрики с определенным интервалом (например, 15-30 секунд). Это может приводить к небольшой задержке в отображении данных на дашбордах Grafana, что является компромиссом в пользу эффективности долгосрочного хранения данных.

### Зоны мониторинга (`status_zone` и `metric_zone`)

Чтобы API начал отдавать подробные метрики, необходимо в конфигурации определить **зоны** — именованные области для сбора статистики.

- **`status_zone`**: Используется для сбора стандартной статистики по `server`, `location`, `upstream` и `cache`.
  - Для `server` блока: `status_zone server_example;`
  - Для `location` блока: `status_zone api_v2;`
- **`zone` в `upstream`**: `zone upstream_backend 64k;`
- **`keys_zone` в `proxy_cache_path`**: `proxy_cache_path ... keys_zone=my_cache:10m;`
- **`metric_zone` / `metric_complex_zone`**: Используются для агрегации произвольных метрик.
  - `metric_zone`: Для простых метрик (счетчик, среднее, гистограмма).
  - `metric_complex_zone`: Для сбора нескольких метрик по одному ключу (например, и счетчик, и среднее).

## Практические сценарии

### Сценарий 1: Настройка Console Lite и API

#### Шаг 1: Установка Console Lite

Установите пакет `angie-console-lite` через пакетный менеджер после [базовой установки Angie](./angie_installation.md).

```bash
sudo apt-get install angie-console-light
```

#### Шаг 2: Настройка эндпоинтов

Создайте отдельный `server` блок для мониторинга, защитив его от публичного доступа.

```nginx
server {
    listen 8888;
    server_name monitor.example.com;

    # Рекомендуется использовать SSL и ограничение по IP
    # ssl_certificate ...;
    # ssl_certificate_key ...;
    # allow 127.0.0.1;
    # deny all;

    # Обслуживание файлов Angie Console Lite
    location /console {
        alias /usr/share/angie-console-lite/html;
        index index.html;

        # Вложенный location для проксирования запросов от консоли к API
        location /console/api/ {
            # /status/ - это эндпоинт API из другого server блока
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

#### Шаг 3: Анализ данных

- **Веб-интерфейс:** Откройте `http://monitor.example.com:8888/console` для просмотра статистики в Console Lite. (Демо: [console.angie.software](https://console.angie.software/))
- **Прямой доступ к API:**

    ```bash
    # Получение всех метрик
    curl -s http://monitor.example.com:8888/status/ | jq
    ```

### Сценарий 2: Интеграция с Prometheus

#### Шаг 1: Настройка эндпоинта в Angie

Создайте защищенный `location`, который будет экспортировать метрики в формате Prometheus. Это решение **является нативным** и, в отличие от аналогов для NGINX, **не требует использования njs** или других скриптовых языков.

```nginx
server {
    listen 80;
    # ...
    location = /metrics {
        prometheus all; # Экспорт всех метрик из шаблона "all"
        allow 127.0.0.1; # IP-адрес сервера Prometheus
        deny all;
    }
}
```

*Убедитесь, что в `angie.conf` подключен шаблон `prometheus.conf`.*

#### Шаг 2: Настройка Prometheus

Добавьте в `prometheus.yml` новую задачу для сбора метрик.

```yaml
scrape_configs:
  - job_name: 'angie'
    metrics_path: /metrics
    static_configs:
      - targets: ['localhost:80'] # Адрес сервера Angie
```

#### Шаг 3: Визуализация в Grafana

1. Подключите Prometheus как источник данных в Grafana.
2. Импортируйте официальный дашборд Angie, используя ID `2719`.

### Сценарий 3: Работа с конфигурацией через API

API позволяет не только просматривать метрики, но и работать с конфигурацией.

#### Получение текущей конфигурации

В отличие от `angie -T`, которая парсит файлы с диска, API позволяет получить **конфигурацию, на которой работает Angie в данный момент**. Это полезно для диагностики и восстановления.

```bash
# Получить содержимое angie.conf
curl http://monitor.example.com:8888/status/config_files/angie.conf

# Вся конфигурация в виде JSON
curl http://monitor.example.com:8888/status/config_files/ | jq
```

#### Отслеживание поколений конфигурации

Angie отслеживает "поколение" конфигурации каждого процесса. При `reload` номер поколения увеличивается. Это позволяет отследить, применились ли изменения, и есть ли "старые" рабочие процессы, которые не завершились.

```bash
# Вывод ps покажет процессы разных поколений
ps aux | grep angie

# Вывод API покажет только номер текущего, нового поколения
curl http://monitor.example.com:8888/status/angie/ | jq .generation
```

### Сценарий 4: Создание пользовательских метрик с помощью модуля `metric`

Модуль `metric` позволяет создавать произвольные метрики, используя любую переменную Angie в качестве ключа и/или значения.

#### Подсчет запросов по браузерам

**Задача:** Узнать, какими браузерами пользуются клиенты.

**Решение:** Считаем запросы по заголовку `User-Agent`.

```nginx
http {
    # Зона для простого подсчета
    metric_zone browsers:1m count;

    server {
        # ...
        # Для каждого запроса увеличиваем счетчик для ключа $http_user_agent
        metric browsers $http_user_agent on=request;
    }
}
```

Результат в API (`/api/http/metric_zones/browsers/`) будет выглядеть так:

```json
{ "metrics": { "Firefox": 1, "Chrome": 5 } }
```

#### Расчет среднего времени ответа по странам

**Задача:** Выяснить, есть ли проблемы со скоростью доступа из разных стран.

**Решение:** Считаем среднее значение `$request_time` для каждой страны, определенной по GeoIP.

```nginx
http {
    # ...
    geoip2 /var/lib/GeoIP/GeoLite2-Country.mmdb {
        auto_reload 1h;
        $geoip2_country_iso_code country iso_code;
    }

    # Зона для расчета среднего значения
    metric_zone geo:1m average mean;

    server {
        # ...
        location / {
            # ...
            # В конце обработки запроса добавляем значение $request_time
            metric geo $geoip2_country_iso_code=$request_time on=end;
        }
    }
}
```

#### Расчет индекса APDEX

**Задача:** Оценить удовлетворенность пользователей скоростью работы сайта.

**Решение:** Используем гистограмму для разделения запросов на "хорошие" (`<2s`), "удовлетворительные" (`<8s`) и "плохие" (`>8s`).

1. **Настройка зоны и метрики:**

    ```nginx
    http {
        # ...
        # Зона-гистограмма с бакетами 2с, 8с, +бесконечность
        metric_zone curapdex:1m histogram 2 8 inf;

        server {
            # ...
            location / {
                metric curapdex curapdex=$request_time;
            }
        }
    }
    ```

2. **Шаблон для Prometheus:** Создаем шаблон для преобразования данных в формат гистограммы Prometheus.

    ```nginx
    http {
        # ...
        prometheus_template apdex {
            'angie_apdex_curapdex_stats{le="$1"}' $p8s_value
                path=~^/http/metric_zones/curapdex/metrics/curapdex/(.+)$
                type=histogram;
        }

        server {
            # ...
            location /prometheus/apdex {
                prometheus apdex;
                access_log off;
            }
        }
    }
    ```

3. **Запрос в Prometheus:** APDEX вычисляется по формуле:
    `(sum(angie_apdex_curapdex_stats{le="2"}) + sum(angie_apdex_curapdex_stats{le="8"})) / 2 / sum(angie_apdex_curapdex_stats{le="inf"})`

#### Сбор бизнес-метрик с помощью Lua

**Задача:** Считать, сколько единиц каждого товара добавляют в корзину.

**Решение:** Используем Lua для парсинга тела POST-запроса, извлечения ID и количества товара, и записываем это в комплексную метрику.

> **Производительность:** Сам по себе модуль `metric` не создает нагрузки. Однако использование сложных вычислений, например, с помощью Lua для парсинга тела запроса на ранней стадии (`on=request`), может влиять на утилизацию CPU.

1. **Настройка комплексной зоны:**

    ```nginx
    http {
        # ...
        metric_complex_zone awesome_customs:1m discard_key="other" {
            stats    histogram 64 256 1024 4096 16384 +Inf; # Гистограмма размеров заказа
            sum      gauge;    # Общее кол-во штук
            count    count;    # Кол-во заказов
            avg_size average exp; # Средний размер заказа
        }
    }
    ```

2. **Парсинг запроса с Lua:**

    ```nginx
    server {
        # ...
        set $product_name '';
        set $product_quantity '';

        location /addToCart {
            lua_need_request_body on;

            access_by_lua '
                ngx.req.read_body()
                local body = ngx.req.get_body_data()
                if body then
                    local id = tonumber(string.match(body, \'"id":(%d+)\'))
                    local qty = tonumber(string.match(body, \'"quantity":(%d+)\'))

                    if id == 516970094 then ngx.var.product_name = "awesome_product"
                    elseif id == 516970095 then ngx.var.product_name = "other_product"
                    end

                    if qty then ngx.var.product_quantity = tostring(qty) end
                end
            ';

            metric awesome_customs $product_name=$product_quantity on=request;
            proxy_pass http://backend;
        }
    }
    ```

    Соответствующий `prometheus_template` позволит экспортировать все эти метрики в Prometheus для дальнейшего анализа.

## Дополнительная информация

### Возможности Angie Pro

- **Динамическое управление `upstream`**: Коммерческая версия Angie Pro позволяет через API и Console Lite динамически изменять состояние серверов в `upstream` группах. Для этого в директиве `api` используется параметр `write=on`.
- **Расширенные метрики**: Некоторые ключевые метрики, например, **время ответа от апстрима (`upstream response time`)**, доступны только в Angie Pro и не экспортируются в Open Source версии. Однако, как показано выше, схожую функциональность можно реализовать вручную с помощью модуля `metric`.
