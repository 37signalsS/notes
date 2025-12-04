# Интеграция Grafana с другими системами

Grafana является центральным элементом современного стека наблюдаемости и легко интегрируется с десятками систем для сбора и визуализации данных. В этой заметке собраны практические примеры настройки таких интеграций.

---

## Интеграция с Graphite и Collectd

Этот пример демонстрирует классическую связку для сбора и отображения системных метрик.

### 1. Компоненты системы

-   **Grafana:** Платформа для аналитики и визуализации данных.
-   **Graphite:** Система для хранения и обработки временных рядов, состоящая из:
    -   **Carbon:** Демон, принимающий метрики по сети.
    -   **Whisper:** Файловая база данных для временных рядов.
    -   **Graphite-web:** Веб-интерфейс и API для доступа к данным.
-   **Collectd:** Демон для сбора системных метрик (CPU, память, сеть, диск) и их отправки в Graphite.

### 2. Архитектура

1.  `Collectd` на хосте собирает метрики.
2.  `Collectd` отправляет метрики на порт `2003` демона `Carbon`.
3.  `Carbon` записывает данные в `Whisper`.
4.  `Grafana` подключается к `Graphite-web` как к источнику данных.
5.  `Grafana` запрашивает данные через API `Graphite-web` и строит графики.

### 3. Развертывание с помощью Docker Compose

Файл `docker-compose.yml` для запуска Grafana и Graphite:

```yaml
version: '3.8'

services:
  graphite:
    image: graphiteapp/graphite-statsd:1.1.10-1
    container_name: graphite
    restart: always
    ports:
      - "8080:80"       # Graphite Web UI
      - "2003:2003"       # Carbon Line Receiver (для Collectd)
      - "2004:2004"       # Carbon Pickle Receiver
      - "8125:8125/udp"   # StatsD UDP
    volumes:
      - graphite_data:/opt/graphite/storage
      - graphite_conf:/opt/graphite/conf

  grafana:
    image: grafana/grafana:10.4.2
    container_name: grafana
    restart: always
    ports:
      - "3000:3000" # Grafana Web UI
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_USERS_ALLOW_SIGN_UP=false
    depends_on:
      - graphite

volumes:
  graphite_data:
  graphite_conf:
  grafana_data:
```

Запуск стека: `docker-compose up -d`.

### 4. Настройка Collectd на хосте

1.  **Установка:**
    ```bash
    sudo apt update
    sudo apt install collectd -y
    ```

2.  **Настройка:**
    Отредактируйте `/etc/collectd/collectd.conf`, чтобы включить и настроить плагин `write_graphite`:

    ```conf
    <Plugin write_graphite>
      <Node "graphite">
        Host "localhost"
        Port "2003"
        Protocol "tcp"
        LogSendErrors true
        Prefix "collectd."
        StoreRates true
        AlwaysAppendDS false
        EscapeCharacter "_"
      </Node>
    </Plugin>
    ```

3.  **Перезапуск сервиса:**
    ```bash
    sudo systemctl restart collectd
    ```

### 5. Настройка Grafana

1.  **Войдите в Grafana:** `http://localhost:3000` (admin/admin).
2.  **Добавьте источник данных:**
    -   Перейдите в **Connections -> Data sources -> Add new data source**.
    -   Выберите **Graphite**.
    -   В поле **URL** укажите `http://graphite:80` (используя имя сервиса из Docker Compose).
    -   Нажмите **Save & test**.
3.  **Создайте дашборд:**
    -   При создании панели выберите `Graphite` как источник данных.
    -   В конструкторе запросов вы увидите иерархию метрик от `collectd`, например: `collectd.имя_хоста.cpu-0.cpu-idle`.

---
**Связанные темы:**
*   [[grafana_datasources_setup.md]]
*   [[grafana_dashboards.md]]
