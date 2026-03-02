# Мониторинг Angie — Пользовательские метрики

## Практический сценарий: Создание пользовательских метрик с помощью модуля `metric`

Модуль `metric` позволяет создавать произвольные метрики, используя любую переменную Angie в качестве ключа и/или значения.

### Подсчет запросов по браузерам

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

### Расчет среднего времени ответа по странам

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

### Расчет индекса APDEX

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

### Сбор бизнес-метрик с помощью Lua

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

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md)
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md)
