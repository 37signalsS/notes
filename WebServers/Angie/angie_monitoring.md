# Мониторинг Angie

## Определения

**Мониторинг Angie** — это процесс сбора, анализа и визуализации метрик производительности и состояния веб-сервера. В отличие от устаревшего модуля `stub_status` в NGINX, Angie предоставляет мощный встроенный JSON API, открывающий доступ к сотням метрик.

## Основные концепции

### Подходы к мониторингу

1.  **Интерактивный мониторинг**: Использование встроенного веб-интерфейса **Angie Console Lite** и прямого доступа к **HTTP API** для быстрого обзора состояния сервера в реальном времени.
2.  **Долгосрочная аналитика**: Сбор, хранение и визуализация метрик с помощью [**Prometheus**](../../Prometheus/overview.md) и [**Grafana**](../../Grafana/grafana_overview.md) для анализа тенденций и настройки оповещений.

### Зоны мониторинга (`status_zone`)

Чтобы API начал отдавать подробные метрики, необходимо в конфигурации определить **зоны** — именованные области для сбора статистики. Это ключевой механизм, позволяющий Angie агрегировать данные по различным компонентам.

-   **Для `server` блока:** `status_zone server_example;`
-   **Для `location` блока:** `status_zone api_v2;`
-   **Для `upstream` группы:** `zone upstream_backend 64k;`
-   **Для кэша:** `proxy_cache_path ... keys_zone=my_cache:10m;`

## Практические сценарии

### Сценарий 1: Настройка Console Lite и API

#### Шаг 1: Установка Console Lite
Установите пакет `angie-console-lite` через пакетный менеджер после [базовой установки Angie](./angie_installation.md).

#### Шаг 2: Настройка эндпоинтов
Создайте отдельный `server` блок для мониторинга, защитив его от публичного доступа.
```nginx
server {
    listen 8888 ssl;
    server_name monitor.example.com;

    allow 127.0.0.1;
    deny all;

    # Обслуживание файлов Angie Console Lite
    location / {
        root /usr/share/angie-console-lite/html;
    }

    # Эндпоинт Angie API
    location /api/ {
        api;
    }
}
```

#### Шаг 3: Анализ данных
-   **Веб-интерфейс:** Откройте `https://monitor.example.com:8888` для просмотра статистики в Console Lite.
-   **Прямой доступ к API:**
    ```bash
    # Получение всех метрик
    curl -s https://monitor.example.com:8888/api/ | jq
    ```

### Сценарий 2: Интеграция с Prometheus и Grafana

#### Шаг 1: Настройка эндпоинта в Angie
Создайте защищенный `location`, который будет экспортировать метрики в формате Prometheus.
```nginx
server {
    # ...
    location = /p8s {
        prometheus all; # Экспорт всех метрик
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
    metrics_path: /p8s
    static_configs:
      - targets: ['localhost:80'] # Адрес сервера Angie
```

#### Шаг 3: Визуализация в Grafana
1.  Подключите Prometheus как источник данных в Grafana.
2.  Импортируйте официальный дашборд Angie, используя ID `2719`.

## Дополнительная информация

### Возможности Angie Pro

-   **Динамическое управление `upstream`**: Коммерческая версия Angie Pro позволяет через API и Console Lite динамически изменять состояние серверов в `upstream` группах. Для этого в директиве `api` используется параметр `write=on`.
-   **Расширенные метрики**: Некоторые ключевые метрики, например, **время ответа от апстрима (`upstream response time`)**, доступны только в Angie Pro и не экспортируются в Open Source версии.