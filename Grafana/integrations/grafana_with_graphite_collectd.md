# Интеграция Grafana с Graphite и Collectd

## Определения

-   **Grafana:** Платформа для аналитики и интерактивной визуализации данных, позволяющая создавать дашборды, графики и алерты.
-   **Graphite:** Система для хранения и обработки временных рядов. Состоит из трех компонентов:
    -   **Carbon:** Демон, принимающий метрики по сети (например, от Collectd) и записывающий их в базу данных.
    -   **Whisper:** Файловая база данных для хранения временных рядов с фиксированным размером.
    -   **Graphite-web:** Веб-интерфейс для визуализации данных и API для их получения, с которым взаимодействует Grafana.
-   **Collectd:** Демон, который собирает системные метрики (CPU, память, сеть, диск) и отправляет их в Graphite или другие системы.

## Основные концепции

Архитектура и процесс сбора и визуализации метрик выглядят следующим образом:

1.  `Collectd`, запущенный на хост-машине, собирает системные метрики.
2.  `Collectd` отправляет метрики на `Carbon` (компонент Graphite), который слушает порт `2003`.
3.  `Carbon` записывает полученные метрики в базу данных `Whisper`.
4.  `Grafana` подключается к `Graphite-web` как к источнику данных (Data Source).
5.  `Grafana` запрашивает данные у `Graphite-web` API, который читает их из `Whisper`, и строит на их основе графики.

## Практические сценарии

### Развертывание с помощью Docker Compose

#### Создание файла `docker-compose.yml`

Создайте директорию для проекта (например, `~/monitoring`) и в ней файл `docker-compose.yml` со следующим содержимым:

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
      - GF_SECURITY_ADMIN_PASSWORD=admin # В реальной среде используйте более надежный пароль
      - GF_USERS_ALLOW_SIGN_UP=false
    depends_on:
      - graphite

volumes:
  graphite_data:
  graphite_conf:
  grafana_data:
```

#### Запуск стека

В директории с файлом `docker-compose.yml` выполните команду:

```bash
docker-compose up -d
```

### Настройка Collectd на хосте

Установите и настройте `collectd` на машине, метрики которой требуется собирать, чтобы он отправлял данные в Graphite.

#### Установка Collectd

```bash
sudo apt update
sudo apt install collectd -y
```

#### Настройка плагина `write_graphite`

Откройте конфигурационный файл `/etc/collectd/collectd.conf` и приведите секцию `<Plugin write_graphite>` к следующему виду для отправки метрик на порт `2003` Docker-хоста.

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

После сохранения изменений перезапустите `collectd`:

```bash
sudo systemctl restart collectd
```

### Настройка Grafana

#### Вход в Grafana

Откройте в браузере `http://localhost:3000`. Используйте логин `admin` и пароль `admin`.

#### Добавление Graphite как источника данных

1.  Перейдите в **Connections -> Data sources**.
2.  Нажмите **Add new data source** и выберите **Graphite**.
3.  В поле **URL** укажите адрес `http://graphite:80`, используя имя сервиса из `docker-compose.yml`.
4.  Нажмите **Save & test** для проверки подключения.

#### Создание дашборда

После подключения можно создавать дашборды, используя `Graphite` как источник данных. В режиме запроса будет доступна иерархия метрик от `collectd` (например, `collectd.имя_хоста.cpu-0.cpu-idle`).
