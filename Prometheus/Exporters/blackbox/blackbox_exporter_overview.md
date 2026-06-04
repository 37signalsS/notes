# Blackbox Exporter — Обзор и основные концепции

## Определения

**Blackbox Exporter** — экспортер Prometheus для blackbox-мониторинга (проверка доступности эндпоинтов снаружи). Проверяет доступность и работоспособность сервисов по сети с использованием протоколов: HTTP(S), TCP, ICMP, DNS, gRPC.

- **Порт по умолчанию:** `9115`
- **Репозиторий:** [prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter)
- **Установка и настройка:** [blackbox_exporter_installation_and_setup.md](./blackbox_exporter_installation_and_setup.md)

## Основные концепции

### Whitebox vs Blackbox мониторинг

| Характеристика | Whitebox | Blackbox |
| :--- | :--- | :--- |
| **Доступ** | Внутренние метрики системы | Внешняя проверка |
| **Экспортер** | Устанавливается на целевой системе | Запускается отдельно |
| **Пример** | `node_exporter`, `mysqld_exporter` | `blackbox_exporter` |
| **Метрики** | CPU, память, запросы к БД | Доступность, SSL, время ответа |

### Принцип работы

`blackbox_exporter` работает по особому принципу:

1. Prometheus опрашивает не целевую систему (например, `google.com`), а сам `blackbox_exporter` на эндпоинте `/probe`
2. Целевой адрес передаётся как параметр `?target=...`
3. Имя модуля проверки передаётся как параметр `?module=...`
4. `blackbox_exporter` выполняет проверку и возвращает метрики о результате

**Схема работы:**

```text
Prometheus → http://blackbox-exporter:9115/probe?target=google.com&module=http_2xx
                                                      ↓
blackbox_exporter выполняет проверку google.com
                                                      ↓
blackbox_exporter возвращает метрики: probe_success, probe_duration_seconds, ...
```

**Важно:** По пути `/metrics` `blackbox_exporter` отдаёт метрики о своей работе, а не результаты проверок. Результаты проверок доступны только по пути `/probe`.

## Практические сценарии

### Когда использовать Blackbox Exporter

| Сценарий | Модуль | Что проверяем |
| :--- | :--- | :--- |
| Доступность веб-сайта | `http_2xx` | HTTP 200, SSL валиден, время ответа |
| Доступность API | `http_2xx` / `http_post_2xx` | Endpoint отвечает, корректный статус-код |
| Проверка порта БД | `tcp_connect` | Порт открыт, соединение устанавливается |
| Проверка сети (ping) | `icmp` | Хост доступен по сети |
| Валидность DNS | `dns_*` | Сервер разрешает имена, корректные записи |
| gRPC health check | `grpc` | Health endpoint отвечает |
| Проверка редиректа | `http_2xx` + `follow_redirects` | Корректный редирект (301/302) |
| Проверка HTTP/3 | `http_2xx` + `http3: true` | Поддержка QUIC |

### Relabeling — стандартная конфигурация

Blackbox Exporter требует relabeling для корректной работы. Целевой адрес передаётся как параметр, а `__address__` заменяется на адрес exporter:

```yaml
relabel_configs:
  - source_labels: [__address__]
    target_label: __param_target    # target → параметр ?target=
  - source_labels: [__param_target]
    target_label: instance          # target → лейбл instance
  - target_label: __address__
    replacement: blackbox:9115      # адрес exporter
```

## Дополнительная информация

### Новые возможности v0.28.0

- **HTTP/3 (QUIC) prober** — поддержка нового протокола
- **gRPC metadata** — передача метаданных в gRPC-проверках
- **Byte matching в TCP** — проверка бинарных данных
- **Unix domain sockets** — проверка через локальные сокеты
- **Автоматическая перезагрузка конфига** — флаг `--config.enable-auto-reload`

### Официальные ресурсы

- [GitHub Repository](https://github.com/prometheus/blackbox_exporter)
- [Official Documentation](https://prometheus.io/docs/guides/blackbox-exporter/)
- [Default Port Allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)

**См. также:**

- [Установка и настройка](./blackbox_exporter_installation_and_setup.md)
- [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
- [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
