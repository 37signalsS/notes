# Blackbox Exporter — Обзор и основные концепции

## Определения

**Blackbox Exporter** — официальный инструмент Prometheus для реализации **blackbox-мониторинга** (внешнего наблюдения). В отличие от классических экспортеров, он не собирает внутренние метрики приложения, а имитирует поведение клиента, проверяя доступность и корректность работы сервисов по сети.

- **Multi-Target Exporter:** один экземпляр экспортера может опрашивать неограниченное количество целей.
- **Поддерживаемые протоколы:** HTTP(S), TCP, ICMP (Ping), DNS, gRPC.
- **Порт по умолчанию:** `9115`
- **Репозиторий:** [prometheus/blackbox_exporter](https://github.com/prometheus/blackbox_exporter)
- **Связанные документы:**
    - [Установка и настройка](./blackbox_exporter_installation_and_setup.md)
    - [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
    - [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)

## Основные концепции

### Сравнение подходов: Whitebox vs Blackbox

| Характеристика | Whitebox (Внутренний) | Blackbox (Внешний) |
| :--- | :--- | :--- |
| **Объект наблюдения** | Внутреннее состояние (CPU, RAM, очереди) | Внешнее поведение (доступность, SSL, время ответа) |
| **Метод сбора** | Прямой опрос `/metrics` приложения | Имитация запроса пользователя через прокси-экспортер |
| **Точка зрения** | "Как чувствует себя система?" | "Видит ли пользователь сервис?" |
| **Пример** | `node_exporter`, `mysqld_exporter` | `blackbox_exporter` |
| **Применение** | Отладка, профилирование, внутренние алерты | Контроль SLA/SLO, проверка сетевой связности |

### Принцип работы (Multi-Target Scrape)

`blackbox_exporter` использует специфический паттерн опроса. Prometheus отправляет запрос не на целевой сервис, а на эндпоинт `/probe` самого экспортера, передавая параметры цели в URL.

1. **Запрос:** Prometheus обращается к `http://blackbox:9115/probe?target=example.com&module=http_2xx`.
2. **Выполнение:** Экспортер инициирует проверку (например, GET-запрос к `example.com`).
3. **Результат:** Экспортер собирает метрики проверки и возвращает их Prometheus в текстовом формате.

**Важно:**
- Путь `/metrics` — содержит метрики здоровья самого экспортера (запросы, ошибки, аптайм).
- Путь `/probe` — содержит результаты проверок целевых систем.

## Практические сценарии

### Сценарии использования модулей

| Сценарий | Модуль | Ожидаемый результат |
| :--- | :--- | :--- |
| **Веб-сайт** | `http_2xx` | Статус 200, валидный SSL, ответ < 2с |
| **API Endpoint** | `http_post_2xx` | Корректный ответ на POST-запрос с body |
| **База данных** | `tcp_connect` | TCP-порт (например, 5432) открыт и принимает соединения |
| **Сетевая связность** | `icmp` | Хост отвечает на Ping (требуются права root/cap_net_raw) |
| **DNS-резолвинг** | `dns_udp` | Запись `A` возвращает ожидаемый IP-адрес |
| **gRPC Service** | `grpc` | Сервис поддерживает Health Check Protocol |
| **SSL-сертификаты** | `http_2xx` | Проверка даты истечения сертификата (`probe_ssl_earliest_cert_expiry`) |

### Стандартная конфигурация Relabeling

Поскольку адрес цели передается как параметр, стандартная конфигурация Prometheus требует использования `relabel_configs` для подмены `__address__`:

```yaml
scrape_configs:
  - job_name: 'blackbox'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
        - https://prometheus.io
        - https://github.com
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target    # Записываем адрес цели в параметр target
      - source_labels: [__param_target]
        target_label: instance          # Сохраняем адрес цели в лейбле instance
      - target_label: __address__
        replacement: 127.0.0.1:9115     # Указываем адрес самого Blackbox Exporter
```

## Дополнительная информация

### Нововведения в версии v0.28.0

- **HTTP/3 (QUIC):** возможность проверки сайтов по новейшему протоколу.
- **Unix Domain Sockets:** поддержка пробинга сервисов, работающих через локальные сокеты.
- **Auto-Reload:** флаг `--config.enable-auto-reload` позволяет обновлять настройки без перезапуска процесса.
- **Prober Logging:** расширенное логирование конкретных проверок для упрощения отладки.

### Официальные ресурсы

- [GitHub Repository](https://github.com/prometheus/blackbox_exporter)
- [Official Documentation](https://prometheus.io/docs/guides/blackbox-exporter/)
- [Configuration Reference](https://github.com/prometheus/blackbox_exporter/blob/master/CONFIGURATION.md)

**См. также:**

- [Установка и настройка](./blackbox_exporter_installation_and_setup.md)
- [Конфигурация модулей](./blackbox_exporter_modules_configuration.md)
- [Метрики и алертинг](./blackbox_exporter_metrics_and_alerting.md)
