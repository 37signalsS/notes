# Мониторинг Angie — Console Lite и API

## Практический сценарий: Настройка Console Lite и API

### Шаг 1: Установка Console Lite

Установите пакет `angie-console-lite` через пакетный менеджер после [базовой установки Angie](./angie_installation.md).

```bash
sudo apt-get install angie-console-light
```

### Шаг 2: Настройка эндпоинтов

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

### Шаг 3: Анализ данных

- **Веб-интерфейс:** Откройте `http://monitor.example.com:8888/console` для просмотра статистики в Console Lite. (Демо: [console.angie.software](https://console.angie.software/))
- **Прямой доступ к API:**

    ```bash
    # Получение всех метрик
    curl -s http://monitor.example.com:8888/status/ | jq
    ```

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md)
- [Интеграция с Prometheus](./angie_monitoring_prometheus.md)
