# Интеграция Grafana с Graphite и Collectd

> **LEGACY STACK (2026)**
>
> Graphite и Collectd — устаревшие компоненты. Для новых проектов рекомендуется:
>
> - **Метрики:** [Prometheus](../../Prometheus/overview.md) + [Grafana Alloy](../grafana_alloy_overview.md)
> - **Логи:** [Loki](../../Loki/loki_overview.md) + Alloy
> - **Трассировки:** [Tempo](../../Tempo/tempo_overview.md)
>
> Данная документация сохранена для поддержки legacy-систем.

> **Навигация:**
>
> - [Обзор Grafana](../grafana_overview.md)
> - [Источники данных](../grafana_datasources.md)
> - [Docker Compose установка](../Installation/docker_compose_setup.md)

## Определения

- **Grafana:** Платформа для аналитики, интерактивной визуализации данных, создания дашбордов, графиков и алертов.
- **Graphite:** Система хранения и обработки временных рядов, состоящая из:
  - **Carbon:** Демон, принимающий метрики по сети (например, от Collectd) и записывающий их в базу данных Whisper.
  - **Whisper:** Файловая база данных фиксированного размера для хранения временных рядов.
  - **Graphite-web:** Веб-интерфейс для визуализации данных и API, с которым взаимодействует Grafana.
- **Collectd:** Системный демон для сбора метрик (CPU, память, сеть, диск) и их отправки в Graphite или другие системы мониторинга.

## Основные концепции

1. **Сбор метрик:** `Collectd`, запущенный на хост-машине, собирает системные метрики.
2. **Передача метрик:** `Collectd` отправляет метрики на `Carbon` (компонент Graphite) по протоколу TCP на порт `2003`.
3. **Хранение метрик:** `Carbon` записывает полученные метрики в базу данных `Whisper`.
4. **Визуализация:** `Grafana` подключается к `Graphite-web` как к источнику данных.
5. **Отображение:** `Grafana` запрашивает данные у `Graphite-web` API, который извлекает их из `Whisper`, и строит на их основе графики.

## Практические сценарии

### Развертывание стека мониторинга с Docker Compose

Для быстрого развертывания Grafana и Graphite используется `docker-compose`. Создайте директорию проекта (например, `~/monitoring`) и файл `docker-compose.yml`:

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
      - GF_SECURITY_ADMIN_PASSWORD=admin # В производственной среде используйте надежный пароль
      - GF_USERS_ALLOW_SIGN_UP=false
    depends_on:
      - graphite

volumes:
  graphite_data:
  graphite_conf:
  grafana_data:
```

Запуск стека:

```bash
docker-compose up -d
```

### Настройка Collectd на хосте

Установите и настройте `collectd` на хост-машине для отправки метрик в Graphite-контейнер.

#### Установка Collectd

```bash
sudo apt update
sudo apt install collectd -y
```

#### Настройка плагина `write_graphite`

Отредактируйте конфигурационный файл `/etc/collectd/collectd.conf`, чтобы `collectd` отправлял метрики на порт `2003` Docker-хоста:

```conf
<Plugin write_graphite>
  <Node "graphite">
    Host "localhost" # 'localhost' относится к IP-адресу Docker-хоста, а не к контейнеру
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

После сохранения изменений перезапустите `collectd`:

```bash
sudo systemctl restart collectd
```

### Настройка Grafana

#### Вход в Grafana

Откройте в браузере `http://localhost:3000`. Используйте логин `admin` и пароль `admin` (измените их после первого входа).

#### Добавление Graphite как источника данных

1. Перейдите в **Connections -> Data sources**.
2. Нажмите **Add new data source** и выберите **Graphite**.
3. В поле **URL** укажите `http://graphite:80` (используя имя сервиса из `docker-compose.yml`).
4. Нажмите **Save & test** для проверки подключения.

#### Создание дашборда

После успешного подключения можно создавать дашборды, используя Graphite как источник данных. В режиме запроса будут доступны метрики от `collectd` (например, `collectd.имя_хоста.cpu-0.cpu-idle`).
