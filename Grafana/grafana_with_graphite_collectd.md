# Интеграция Grafana с Graphite и Collectd

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

### Поток данных

Процесс мониторинга строится по следующей схеме:

1. **Сбор:** Служба `Collectd` на целевом хосте собирает показатели системы с помощью плагинов.
2. **Передача:** `Collectd` отправляет данные на входной порт `Carbon` (обычно TCP/UDP `2003`).
3. **Хранение:** `Carbon` сохраняет данные в файлы `.wsp` (Whisper).
4. **Запрос:** `Grafana` через свой источник данных (Data Source) обращается к API `Graphite-web`.
5. **Визуализация:** `Graphite-web` считывает данные из `Whisper`, применяет функции и передает их `Grafana` для отрисовки.

### Иерархия метрик и теги

Традиционно Graphite использует иерархическую структуру имен, разделенных точками:
`servers.web-01.cpu.usage.user`

Начиная с версии **1.1.0**, Graphite поддерживает **теги** (tags), что приближает его к многомерной модели Prometheus:
`seriesByTag('name=cpu.usage', 'server=web-01', 'type=user')`

### Функции обработки

Graphite-web предоставляет сотни встроенных функций для манипуляции данными на лету:
- `aliasByNode(series, node)` — переименование серии по части пути.
- `summarize(series, interval, function)` — агрегация данных за период.
- `movingAverage(series, window)` — сглаживание графиков.
- `asPercent(series1, series2)` — расчет процентного соотношения.

## Практические сценарии

### Развертывание стека через Docker Compose

Для быстрого развертывания используется официальный образ, объединяющий компоненты Graphite.

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
    image: grafana/grafana:13.x
    container_name: grafana
    restart: always
    ports:
      - "3000:3000"
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

### Настройка Collectd на целевом хосте

#### Установка

```bash
sudo apt update && sudo apt install collectd -y
```

#### Настройка плагина write_graphite

Отредактируйте `/etc/collectd/collectd.conf`:

```conf
LoadPlugin write_graphite

<Plugin write_graphite>
  <Node "graphite_server">
    Host "192.168.1.100"
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

Перезапустите службу:
```bash
sudo systemctl restart collectd
```

### Настройка источника данных в Grafana

1. Войдите в Grafana (`http://localhost:3000`).
2. Перейдите в **Connections → Data sources**.
3. Нажмите **Add new data source** и выберите **Graphite**.
4. Укажите URL: `http://graphite:80`.
5. В поле **Version** выберите версию (например, `1.1.x`).
6. Нажмите **Save & test**.

## Дополнительная информация

### Управление хранением (Whisper)

#### Политики хранения (storage-schemas.conf)
Определяют точность и длительность хранения данных.
```ini
[collectd]
pattern = ^collectd\.
retentions = 10s:1d,1m:7d,10m:1y
# 10 сек точность на 1 день, 1 мин на 7 дней, 10 мин на 1 год
```

#### Агрегация данных (storage-aggregation.conf)
Определяет способ вычисления значений при переходе на менее точный уровень (downsampling).
```ini
[min]
pattern = \.min$
xFilesFactor = 0.1
aggregationMethod = min

[default_average]
pattern = .*
xFilesFactor = 0.5
aggregationMethod = average
```
- `xFilesFactor`: минимальная доля заполненных данных для записи агрегата (0.5 = 50%).
- `aggregationMethod`: среднее (`average`), сумма (`sum`), минимум, максимум.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Нет данных в Grafana** | `Collectd` не может подключиться | Проверьте `journalctl -u collectd`. Убедитесь, что порт 2003 открыт. |
| **Пустые списки метрик** | Ошибка Carbon или права доступа | Проверьте логи: `docker logs graphite`. Проверьте директорию `/opt/graphite/storage/whisper`. |
| **"Broken" графики** | Несовпадение интервалов | Интервал `collectd` (Interval в конфиге) должен совпадать с первым уровнем retention. |

### Миграция на современный стек

План перехода:
1. **Параллельный запуск:** Установите [Grafana Alloy](./grafana_alloy_overview.md).
2. **Сбор метрик:** Используйте в Alloy компонент `prometheus.exporter.unix`.
3. **Хранение:** Направьте Alloy в [Mimir](../Mimir/mimir_overview.md) или Prometheus.
4. **Конвертация:** Перепишите Graphite-запросы на PromQL.
5. **Вывод из эксплуатации:** Отключите Graphite после проверки данных.

### Безопасность

- **Отсутствие аутентификации:** Протокол Carbon (порт 2003) не имеет встроенной проверки подлинности. Используйте сетевые экраны (firewall) для ограничения доступа.
- **Безопасность API:** Ограничьте доступ к порту 80 (Graphite-web), разрешив запросы только от IP-адреса Grafana.

**См. также:**
- [Обзор Grafana](./grafana_overview.md)
- [Источники данных Grafana](./grafana_datasources.md)
- [Развертывание Grafana в Docker](./Installation/docker_compose_setup.md)
- [Mimir: Хранение метрик](../Mimir/mimir_overview.md)
