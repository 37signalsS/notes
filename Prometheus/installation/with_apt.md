# Установка Prometheus через APT

## Definitions

- **Prometheus Server** — основной компонент, выполняющий сбор (scrape), хранение и обработку метрик в TSDB.
- **Node Exporter** — агент для сбора метрик ОС (CPU, RAM, диск, сеть), предоставляет метрики по HTTP на порту `9100`.

> См. также: [Prometheus overview](./overview.md), [Node Exporter](../Exporters/overview.md), [TSDB](../concepts/tsdb.md).

## Basic Concepts

### Архитектура мониторинга

1. **Сбор**: Node Exporter собирает метрики с хоста и отдаёт их через HTTP-эндпоинт `/metrics`.
2. **Хранение**: Prometheus Server периодически опрашивает (scrape) цели и сохраняет данные в TSDB.
3. **Визуализация**: Grafana подключается к Prometheus как datasource для построения дашбордов. Подробнее: [Grafana overview](../../Grafana/grafana_overview.md), [Grafana dashboards](../../Grafana/grafana-dashboards.md).

### Преимущества установки через APT

Пакетный менеджер `apt` (Debian/Ubuntu) упрощает развёртывание и обновление — пакеты предустановлены для работы с `systemd` ([service_management](../../Linux/Core/systemd/service_management.md)). Установка одной командой включает автозапуск и стандартную конфигурацию в `/etc/prometheus/`.

> См. также: [linux_package_management_overview](../../Linux/PackageManagement/linux_package_management_overview.md).

## Practical Scenarios

### Установка Prometheus Server и Node Exporter

1. Обновление списка пакетов:

    ```bash
    sudo apt update
    ```

2. Установка Prometheus Server и Node Exporter:

    ```bash
    sudo apt install prometheus prometheus-node-exporter
    ```

    Сервисы `prometheus.service` и `prometheus-node-exporter.service` запускаются автоматически.

3. Проверка доступности:

    ```bash
    ss -tnlp
    ```

    Ожидаемые порты:
    - `*:9090` — Prometheus Server (веб-интерфейс и API)
    - `*:9100` — Node Exporter (метрики хоста)

    Веб-интерфейс Prometheus: `http://<ip_сервера>:9090`. На **Status → Targets** должен быть виден `localhost:9100` со статусом `UP`.

    > Подробнее об утилите `ss`: [ss](../../Linux/Diagnostics/Networking/ss.md).

### Добавление нового хоста для мониторинга

1. **На целевом хосте** — установка Node Exporter:

    ```bash
    sudo apt update
    sudo apt install prometheus-node-exporter
    ```

    Проверка с сервера мониторинга:

    ```bash
    curl http://<ip_целевого_хоста>:9100/metrics
    ```

    Подробнее: [node_exporter_installation](./node_exporter_installation.md).

2. **На сервере мониторинга** — редактирование `/etc/prometheus/prometheus.yml`:

    ```yaml
    scrape_configs:
      - job_name: "prometheus"
        static_configs:
          - targets: ["localhost:9090"]

      - job_name: "node"
        static_configs:
          - targets: ["localhost:9100", "192.168.1.100:9100"]  # IP нового хоста
    ```

    Перезагрузка конфигурации:

    ```bash
    sudo systemctl reload prometheus.service
    ```

    Проверка: **Status → Targets** в веб-интерфейсе Prometheus. Новый хост должен иметь статус `UP`.

    > Подробнее о конфигурации: [Prometheus configuration](../configuration.md).

### Интеграция с Grafana

После установки Prometheus подключите Grafana как источник данных:

1. Установка Grafana: [Grafana installation](../../Grafana/Installation/).
2. Добавление datasource: **Configuration → Data Sources → Prometheus** → URL: `http://localhost:9090`.
3. Импорт дашборда Node Exporter Full (ID `1860`): **Dashboards → Import**.

> См. также: [Grafana dashboards](../../Grafana/grafana-dashboards.md), [Docker Compose setup](./docker_stack/overview.md) для автоматизированного развёртывания.

### Настройка Nginx как обратного прокси

Для доступа к Grafana по порту `80` вместо `3000` настройте reverse proxy ([nginx_as_reverse_proxy_for_grafana](../../WebServers/Nginx/Scenarios/nginx_as_reverse_proxy_for_grafana.md)).

## Additional Information

Файл охватывает установку Prometheus Server и Node Exporter через APT на Debian/Ubuntu. Связанные темы: конфигурация Prometheus ([configuration](../configuration.md)), экспортёры ([exporters](../Exporters/overview.md)), Grafana ([grafana_overview](../../Grafana/grafana_overview.md), [installation](../../Grafana/Installation/)), Nginx reverse proxy ([nginx_as_reverse_proxy_for_grafana](../../WebServers/Nginx/Scenarios/nginx_as_reverse_proxy_for_grafana.md)).
