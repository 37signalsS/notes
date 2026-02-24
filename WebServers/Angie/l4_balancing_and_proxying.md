# Балансировка и проксирование L4-трафика (TCP/UDP) в Angie

## Определения

**Проксирование L4-трафика** в Angie — это процесс перенаправления сетевых потоков на транспортном уровне (TCP/UDP) с помощью модуля `stream`.

## Основные концепции

Поскольку [Angie](./angie_overview.md) является форком Nginx, его функциональность проксирования на уровне L4 полностью унаследована от Nginx и работает идентично.

**Основная документация, примеры и детальные сценарии использования находятся в главной заметке (SSoT):**
> **[Балансировка и проксирование L4-трафика (TCP/UDP) в Nginx](../Nginx/Proxy/nginx_l4_proxying.md)**

## Практические сценарии

### Сценарий: Адаптация конфигурации Nginx для Angie

Единственным существенным отличием при настройке L4-проксирования являются стандартные пути к файлам конфигурации и логам.

**Таблица соответствия путей:**

| Компонент | Nginx | Angie |
| :--- | :--- | :--- |
| **Главный конфигурационный файл** | `/etc/nginx/nginx.conf` | `/etc/angie/angie.conf` |
| **Директория для `stream` конфигов**| `/etc/nginx/stream.d/` | `/etc/angie/stream.d/` |
| **Лог доступа `stream`** | `/var/log/nginx/stream-access.log` | `/var/log/angie/stream-access.log`|
| **Лог ошибок `stream`** | `/var/log/nginx/stream-error.log` | `/var/log/angie/stream-error.log` |

**Пример структуры в `angie.conf`:**

```nginx
# /etc/angie/angie.conf
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time "$upstream_addr"';

    access_log /var/log/angie/stream-access.log basic;

    # Включение конфигураций из stream.d
    include /etc/angie/stream.d/*.conf;
}
```

## Дополнительная информация

Все директивы (`server`, `upstream`, `proxy_pass`, `ssl_preread` и т.д.) и переменные в модуле `stream` полностью совпадают с Nginx.
