# Blackbox Exporter — Обзор и основные концепции

## Определения

**Blackbox Exporter** — экспортер для мониторинга систем снаружи (blackbox-мониторинг), с точки зрения пользователя. Проверяет доступность и работоспособность эндпоинтов по сети с использованием протоколов: HTTP(S), TCP, ICMP, DNS, gRPC.

* **Порт по умолчанию:** `9115`
* **Репозиторий:** [prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter)
* **Установка:** [installation/blackbox_exporter_installation.md](../../installation/Blackbox_Exporter/blackbox_exporter_installation.md)

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

```
Prometheus → http://blackbox-exporter:9115/probe?target=google.com&module=http_2xx
                                                      ↓
blackbox_exporter выполняет проверку google.com
                                                      ↓
blackbox_exporter возвращает метрики: probe_success, probe_duration_seconds, ...
```

> **Важно:** По пути `/metrics` `blackbox_exporter` отдаёт метрики о своей работе, а не результаты проверок. Результаты проверок доступны только по пути `/probe`.

## Дополнительная информация

### Новые возможности v0.28.0

* **HTTP/3 (QUIC) prober** — поддержка нового протокола
* **gRPC metadata** — передача метаданных в gRPC-проверках
* **Byte matching в TCP** — проверка бинарных данных
* **Unix domain sockets** — проверка через локальные сокеты
* **Автоматическая перезагрузка конфига** — флаг `--config.enable-auto-reload`

### Связанные темы

* **[Установка и настройка](./blackbox_exporter_installation_and_setup.md)** — запуск и конфигурация Prometheus
* **[Конфигурация модулей](./blackbox_exporter_modules_configuration.md)** — HTTP, TCP, ICMP, DNS, gRPC модули
* **[Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)** — метрики и правила оповещений
* **[Service Discovery и Relabeling](../../service_discovery_and_relabeling.md)**
* **[Alertmanager](../alertmanager.md)**
* **[Правила оповещений](../../rules.md)**

### Официальные ресурсы

* [GitHub Repository](https://github.com/prometheus/blackbox_exporter)
* [Official Documentation](https://prometheus.io/docs/guides/blackbox-exporter/)
* [Default Port Allocations](https://github.com/prometheus/prometheus/wiki/Default-port-allocations)
