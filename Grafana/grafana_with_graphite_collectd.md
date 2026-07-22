# Интеграция Grafana с Graphite и Collectd

> **Надежность: 8** (Технология считается устаревшей, документация проверена для целей поддержки legacy-систем на июль 2026)
> **Статус:** Устаревший стек (Legacy)

> **ВНИМАНИЕ:** Graphite и Collectd считаются устаревшими компонентами. Для новых проектов настоятельно рекомендуется использовать современный стек на базе OpenTelemetry и Prometheus.
>
> - **Метрики:** [Prometheus](../Prometheus/overview.md) + [Grafana Alloy](./grafana_alloy_overview.md)
> - **Логи:** [Loki](../Loki/loki_overview.md) + Alloy
> - **Трассировки:** [Tempo](../Tempo/index.md)
>
> Данная документация сохранена исключительно для поддержки и миграции существующих систем.

## Определения

**Grafana** — универсальная платформа для визуализации данных и построения аналитических панелей (дашбордов).

**Graphite** — система для сбора, хранения и визуализации временных рядов (time-series data). Архитектура включает три компонента:

- **Carbon** — высокопроизводительный сервис (демон), принимающий метрики по протоколам Line, Pickle или через StatsD и записывающий их в Whisper.
- **Whisper** — специализированная файловая база данных фиксированного размера (fixed-size), обеспечивающая предсказуемое потребление дискового пространства за счет понижения точности старых данных.
- **Graphite-web** — веб-приложение и API для извлечения данных, обеспечивающее функции отрисовки и математической обработки графиков.

**Collectd** — легковесный системный агент для периодического сбора метрик производительности (CPU, RAM, дисковые операции, сетевой трафик) и их передачи в системы хранения.

## Базовые концепции

Процесс мониторинга в данном стеке строится по следующей схеме:

1. **Сбор:** Служба `Collectd` на целевом хосте собирает показатели системы с помощью плагинов.
2. **Передача:** `Collectd` отправляет данные на входной порт `Carbon` (обычно TCP/UDP `2003`).
3. **Хранение:** `Carbon` сохраняет данные в файлы `.wsp` (Whisper).
4. **Запрос:** `Grafana` через свой источник данных (Data Source) обращается к API `Graphite-web`.
5. **Визуализация:** `Graphite-web` считывает данные из `Whisper`, применяет функции (если указаны) и передает их `Grafana` для отрисовки.

## Практические сценарии

### Развертывание стека через Docker Compose

Для быстрого развертывания или тестирования используется официальный образ, объединяющий компоненты Graphite.

**Файл `docker-compose.yml`:**

```yaml
services:
  graphite:
    image: graphiteapp/graphite-statsd:1.1.10-1
    container_name: graphite
    restart: always
    ports:
      - "8080:80"       # Graphite Web UI / API
      - "2003:2003"     # Carbon Line Receiver (TCP)
      - "2003:2003/udp" # Carbon Line Receiver (UDP)
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
      - "3000:3000"
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

**Запуск стека:**
```bash
docker compose up -d
# → Создание сетей и контейнеров
```

### Настройка Collectd на целевом хосте

#### Установка

В большинстве Linux-дистрибутивов пакет доступен в стандартных репозиториях:

```bash
sudo apt update && sudo apt install collectd -y
```

#### Настройка плагина отправки данных

Отредактируйте `/etc/collectd/collectd.conf`, включив плагин `write_graphite`.

```conf
LoadPlugin write_graphite

<Plugin write_graphite>
  <Node "graphite_server">
    Host "192.168.1.100" # IP-адрес сервера Graphite
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

Перезапустите службу для применения изменений:
```bash
sudo systemctl restart collectd
```

### Настройка источника данных в Grafana

1. Войдите в Grafana (`http://localhost:3000`).
2. Перейдите в **Connections → Data sources**.
3. Нажмите **Add new data source** и выберите **Graphite**.
4. Укажите URL: `http://graphite:80` (внутри сети Docker).
5. В поле **Version** выберите версию вашего Graphite (например, `1.1.x`).
6. Нажмите **Save & test**.

## Дополнительная информация

### Управление хранением (Whisper)

База Whisper требует предварительной настройки политик хранения (retention) в файле `storage-schemas.conf`. Если настройки меняются после создания файла метрики, существующие `.wsp` файлы необходимо изменять вручную утилитой `whisper-resize.py`.

**Пример `storage-schemas.conf`:**
```ini
[collectd]
pattern = ^collectd\.
retentions = 10s:1d,1m:7d,10m:1y
# 10 сек точность на 1 день, 1 мин на 7 дней, 10 мин на 1 год
```

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Нет данных в Grafana** | `Collectd` не может подключиться | Проверьте `journalctl -u collectd`. Убедитесь, что порт 2003 открыт на сервере. |
| **Пустые списки метрик** | Ошибка Carbon или права доступа | Проверьте логи Carbon в контейнере: `docker logs graphite`. Проверьте `/opt/graphite/storage/whisper`. |
| **"Broken" графики** | Несовпадение интервалов | Убедитесь, что интервал `collectd` (по умолчанию 10с) совпадает с первым уровнем retention в `storage-schemas.conf`. |

### Миграция на современный стек

План перехода с Graphite/Collectd на Prometheus/Alloy:

1. **Параллельный запуск:** Установите [Grafana Alloy](./grafana_alloy_overview.md) на те же хосты.
2. **Сбор метрик:** Настройте в Alloy компонент `prometheus.exporter.unix` для сбора системных показателей.
3. **Хранение:** Направьте Alloy в [Mimir](../Mimir/mimir_overview.md) или Prometheus.
4. **Конвертация:** Перепишите запросы в дашбордах с Graphite-функций на PromQL.
5. **Вывод из эксплуатации:** Отключите `Collectd` и Graphite после подтверждения идентичности данных.

### Безопасность

- **Отсутствие аутентификации:** Протокол Carbon не поддерживает встроенную проверку подлинности. Любой, кто имеет доступ к порту `2003`, может записать любые данные. Используйте IP Whitelisting (Firewall).
- **Безопасность API:** Ограничьте доступ к API Graphite-web, разрешив запросы только со стороны Grafana.

**См. также:**
- [Обзор Grafana](./grafana_overview.md)
- [Источники данных Grafana](./grafana_datasources.md)
- [Развертывание Grafana в Docker](./Installation/docker_compose_setup.md)
- [Mimir: Хранение метрик](../Mimir/mimir_overview.md)
