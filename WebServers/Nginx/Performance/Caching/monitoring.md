# Nginx Cache Monitoring and Performance

## Definitions

**Cache Hit Ratio** — отношение количества запросов, обработанных из кэша, к общему числу запросов. Высокий hit ratio (>90%) означает эффективную настройку кэширования.

**`$upstream_cache_status`** — встроенная переменная Nginx, показывающая статус кэша для каждого запроса. Основные значения:

| Значение | Описание |
|:---------|:---------|
| `HIT` | Ответ отдан из кэша |
| `MISS` | Запрос не найден в кэше, отправлен на бэкенд |
| `EXPIRED` | Запись устарела, Nginx запросил обновление у бэкенда |
| `STALE` | Отдан устаревший ответ из-за недоступности бэкенда |
| `UPDATING` | Отдан устаревший ответ, пока кэш обновляется в фоне |
| `BYPASS` | Кэш был намеренно обойден (`proxy_cache_bypass`) |
| `REVALIDATED` | Nginx валидировал кэш у бэкенда (получил `304 Not Modified`) |

**Page Cache** — механизм ОС Linux для кэширования часто читаемых файлов в оперативной памяти.

## Basic Concepts

Производительность дискового кэша Nginx очень высока благодаря эффективному использованию page cache в современных ОС. «Горячие» данные отдаются со скоростью, близкой к скорости RAM, что делает использование внешних in-memory хранилищ (Redis, Memcached) для этой задачи не всегда оправданным и усложняющим архитектуру.

Мониторинг кэша включает три ключевых направления:

1. **Логирование** — анализ заголовка `$upstream_cache_status` в `access.log`
2. **Метрики** — сбор числовых показателей (hit ratio, размер кэша, количество HIT/MISS) через Prometheus
3. **Визуализация** — отображение метрик в Grafana или Angie Console

## Practical Scenarios

### Логирование статуса кэша

Для анализа эффективности кэширования добавьте `$upstream_cache_status` в формат логов:

```nginx
# В http блоке (nginx.conf)
log_format cache_log '$remote_addr - $remote_user [$time_local] '
                     '"$request" $status $body_bytes_sent '
                     '"$upstream_cache_status"';

access_log /var/log/nginx/cache_access.log cache_log;
```

После этого в логе будет видно, какие запросы попали в кэш:

```bash
# Подсчёт HIT/MISS за последний час
awk '{print $NF}' /var/log/nginx/cache_access.log | sort | uniq -c | sort -rn
# → 15234 HIT
# →  3412 MISS
# →   156 EXPIRED
```

### Мониторинг через Prometheus и Grafana

Ключевые метрики для сбора:

| Метрика | Источник | Описание |
|:--------|:---------|:---------|
| Hit Ratio | `$upstream_cache_status` в логах или VTS-модуль | Процент запросов, обслуженных из кэша |
| Размер кэша на диске | `du -sh /var/cache/nginx` | Фактическое занимаемое дисковое пространство |
| Количество HIT/MISS/EXPIRED | Парсинг логов или VTS-модуль | Абсолютные значения по каждому статусу |
| Inode usage кэша | `find /var/cache/nginx -type f | wc -l` | Количество файлов в кэше |

Для сбора метрик через **nginx-module-vts** (подробная настройка — [Nginx VTS Monitoring Setup](../../Operations/nginx_vts_monitoring_setup.md)):

1. Добавьте endpoint для метрик в Nginx:
   ```nginx
   location /metrics {
       vhost_traffic_status_display;
       vhost_traffic_status_display_format prometheus;
   }
   ```

2. Настройте [Prometheus](../../../../Prometheus/overview.md) на сбор метрик с этого endpoint.

3. Импортируйте дашборд в [Grafana](../../../../Grafana/grafana_overview.md) (например, ID `9614` или `2949`).

### Angie Console

Если используется [Angie](../../../Angie/angie_overview.md) (форк Nginx), мониторинг кэша доступен через встроенную **Angie Console**, которая предоставляет готовую визуализацию без дополнительной настройки.

## Additional Information

### Когда внешнее кэширование оправдано

Использование Redis/Memcached может быть целесообразно, если:

- Требуется распределённый кэш на нескольких серверах Nginx
- Необходимы сложные стратегии инвалидации (purge по тегам, ключам сессий)
- Кэш должен переживать перезапуск сервера Nginx
- Требуется шардирование кэша между инстансами

Для одиночного сервера или простого reverse proxy — дисковый кэш Nginx с page cache ОС обычно достаточен.

### Утилиты для анализа кэша

| Утилита | Назначение |
|:--------|:-----------|
| `nginx-cache-purge` (модуль) | Точечная очистка кэша по ключу |
| `ngx_http_cache_purge_module` | Встроен в Angie; для Nginx требует отдельной компиляции |
| `find /path -mmin +N -delete` | Ручная очистка старых файлов кэша (не рекомендуется в production) |

## See also

- [Proxy Caching Configuration](./proxy_caching.md) — настройка серверного кэширования
- [Nginx VTS Monitoring Setup](../../Operations/nginx_vts_monitoring_setup.md) — детальная настройка VTS-модуля с Prometheus
- [Nginx Performance Tuning](../nginx_performance_tuning.md) — общая оптимизация производительности Nginx
