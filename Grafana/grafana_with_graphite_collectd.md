# Интеграция Grafana с Graphite и Collectd

> **УСТАРЕВШИЙ СТЕК (2026)**
>
> Graphite и Collectd считаются устаревшими компонентами. Для новых проектов рекомендуется использовать современный стек:
>
> - **Метрики:** [Prometheus](../Prometheus/overview.md) + [Grafana Alloy](./grafana_alloy_overview.md)
> - **Логи:** [Loki](../Loki/loki_overview.md) + Alloy
> - **Трассировки:** [Tempo](../Tempo/index.md)
>
> Данная документация сохранена для поддержки и миграции существующих систем.

## Определения

**Grafana** — универсальная платформа для визуализации данных и построения дашбордов.

**Graphite** — система для сбора и хранения временных рядов (time-series data). Состоит из трех основных компонентов:

- **Carbon** — сервис (демон), принимающий метрики по сети и записывающий их в базу данных.
- **Whisper** — специализированная файловая база данных фиксированного размера для хранения метрик.
- **Graphite-web** — веб-интерфейс и API для извлечения данных, с которым взаимодействует Grafana.

**Collectd** — системная служба для периодического сбора метрик производительности (процессор, память, диски, сеть) и их отправки в хранилища.

**Связанные темы:**

- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Источники данных](./grafana_datasources.md) — общие принципы настройки источников
- [Установка через Docker](./Installation/docker_compose_setup.md) — базовые принципы развёртывания

## Базовые концепции

Процесс мониторинга в данном стеке строится по следующей схеме:

1. **Сбор:** Служба `Collectd` на целевом хосте собирает показатели системы.
2. **Передача:** `Collectd` отправляет данные на входной порт `Carbon` (обычно TCP `2003`).
3. **Хранение:** `Carbon` сохраняет данные в файлы `Whisper`.
4. **Запрос:** `Grafana` через свой источник данных обращается к API `Graphite-web`.
5. **Визуализация:** `Graphite-web` считывает данные из `Whisper`, а `Grafana` отрисовывает их на графиках.

## Практические сценарии

### Развертывание стека через Docker Compose

Для локального тестирования или небольших инсталляций удобно использовать Docker. Создайте файл `docker-compose.yml`:

```yaml
services:
  graphite:
    image: graphiteapp/graphite-statsd:1.1.10-1
    container_name: graphite
    restart: always
    ports:
      - "8080:80"       # Graphite Web UI
      - "2003:2003"     # Carbon Line Receiver (вход для Collectd)
      - "2004:2004"     # Carbon Pickle Receiver
      - "8125:8125/udp" # StatsD UDP
    volumes:
      - graphite_data:/opt/graphite/storage
      - graphite_conf:/opt/graphite/conf

  grafana:
    image: grafana/grafana:12.x
    container_name: grafana
    restart: always
    ports:
      - "3000:3000" # Grafana Web UI
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin # Измените при первом входе
      - GF_USERS_ALLOW_SIGN_UP=false
    depends_on:
      - graphite

volumes:
  graphite_data:
  graphite_conf:
  grafana_data:
```

Запуск осуществляется командой:
`docker compose up -d`

### Настройка Collectd на целевом хосте

#### Установка

В большинстве Linux-дистрибутивов пакет доступен в стандартных репозиториях:

```bash
sudo apt update && sudo apt install collectd -y
```

#### Настройка отправки данных

Отредактируйте `/etc/collectd/collectd.conf`, включив плагин `write_graphite`:

```conf
<Plugin write_graphite>
  <Node "graphite_server">
    Host "127.0.0.1" # IP-адрес сервера с Graphite
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

После редактирования перезапустите службу:
`sudo systemctl restart collectd`

### Настройка источника данных в Grafana

1. Войдите в интерфейс Grafana (`http://localhost:3000`).
2. Перейдите в **Connections → Data sources**.
3. Нажмите **Add new data source** и выберите **Graphite**.
4. Укажите URL: `http://graphite:80` (внутри сети Docker).
5. Нажмите **Save & test**.

Теперь при создании панелей вы сможете выбирать метрики, начинающиеся с префикса `collectd.*`.

## Дополнительная информация

### Устранение неполадок

| Проблема | Решение |
| :--- | :--- |
| **Нет данных от Collectd** | Проверьте логи: `journalctl -u collectd`. Убедитесь, что плагин `write_graphite` раскомментирован в начале конфига. |
| **Порт 2003 недоступен** | Проверьте доступность порта на сервере: `ss -tlnp | grep 2003`. |
| **Пустые списки метрик** | Проверьте содержимое директории `/opt/graphite/storage/whisper` внутри контейнера graphite. |

### Миграция на современный стек

Для перехода на Prometheus/Alloy рекомендуется следующий план:

1. Установить [Grafana Alloy](./grafana_alloy_overview.md) на хосты параллельно с Collectd.
2. Настроить сбор метрик через `prometheus.exporter.unix` (аналог node_exporter) в Alloy.
3. Постепенно пересоздать дашборды, заменяя Graphite-запросы на PromQL.
4. После верификации данных отключить старый стек.

### Безопасность

- **Сетевой доступ:** Протокол Carbon не поддерживает аутентификацию по умолчанию. Ограничивайте доступ к порту `2003` на уровне файрвола.
- **Пароли:** Не используйте стандартные учетные данные `admin/admin` в продуктивной среде.
- **Хранение:** Учитывайте, что Whisper занимает фиксированное место на диске. Настройте политики ротации (retention) в `storage-schemas.conf` Graphite перед массовым добавлением метрик.
