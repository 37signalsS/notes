# Blackbox Exporter — Метрики и алертинг

## 1. Основные метрики

```
probe_success                              # 1 если проверка успешна, 0 если нет
probe_duration_seconds                     # Время выполнения проверки
probe_dns_lookup_time_seconds              # Время DNS-запроса
probe_connect_duration_seconds             # Время подключения
probe_ssl_earliest_cert_expiry             # Время истечения SSL-сертификата
probe_tls_version_info{version="TLSv1.3"}  # Версия TLS
probe_http_status_code                     # HTTP статус код
probe_http_duration_seconds                # Время HTTP-запроса
probe_ip_addr_protocol                     # Протокол IP (ipv4/ipv6)
probe_icmp_round_trip_seconds              # Время ICMP ping
```

---

## 2. Алертинг

### Эндпоинт недоступен

```yaml
- alert: BlackboxProbeFailed
  expr: probe_success == 0
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Проверка {{ $labels.instance }} не удалась"
    description: "Blackbox-проверка не удалась более 5 минут"
```

### Высокое время ответа

```yaml
- alert: BlackboxSlowResponse
  expr: probe_duration_seconds > 2
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Медленный ответ от {{ $labels.instance }}"
    description: "Время ответа превышает 2 секунды"
```

### SSL-сертификат истекает

```yaml
- alert: BlackboxSSLCertExpiring
  expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 30
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "SSL-сертификат истекает на {{ $labels.instance }}"
    description: "До истечения SSL-сертификата осталось менее 30 дней"
```

---

## 3. Связанные документы

- **[Обзор и концепции](./blackbox_exporter_overview.md)** — базовые определения
- **[Установка и настройка](./blackbox_exporter_installation_and_setup.md)** — запуск и конфигурация
- **[Конфигурация модулей](./blackbox_exporter_modules_configuration.md)** — HTTP, TCP, ICMP, DNS, gRPC модули
- **[Alertmanager](../alertmanager.md)**
- **[Правила оповещений](../rules.md)**
