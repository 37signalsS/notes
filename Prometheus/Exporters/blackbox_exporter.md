# Blackbox Exporter

В отличие от экспортеров, которые собирают *внутренние* метрики системы (whitebox), `blackbox_exporter` предназначен для мониторинга систем *снаружи*, с точки зрения пользователя (blackbox). Он позволяет проверять доступность и работоспособность эндпоинтов по сети и должен запускаться отдельно от наблюдаемого сервиса.

*   **Назначение:** Проверка эндпоинтов с использованием различных протоколов: HTTP(S), TCP, ICMP, DNS. Например, можно проверить, что веб-сайт возвращает код `200 OK`, что SSL-сертификат действителен или что TCP-порт открыт.

*   **Принцип работы:** `blackbox_exporter` работает по особому принципу. Prometheus опрашивает не целевую систему (например, `google.com`), а сам `blackbox_exporter` (на его эндпоинте `/probe`), передавая ему целевой адрес в качестве параметра (`?target=...`). Остальная логика проверок настраивается в конфигурации самого экспортера.
    1.  Prometheus делает запрос к `http://blackbox-exporter:9115/probe?target=google.com&module=http_2xx`.
    2.  `blackbox_exporter` получает этот запрос, выполняет проверку цели `google.com` согласно правилам модуля `http_2xx`.
    3.  Он возвращает Prometheus'у метрики о результатах проверки: `probe_success` (1 или 0), `probe_duration_seconds` (длительность проверки) и другие.

> **Замечания из лекции:**
> *   При проверке URL в браузере стоит помнить, что по пути `/metrics` `blackbox_exporter` отдает метрики о своей работе, а не результаты проверок. Результаты проверок доступны по пути `/probe`.
> *   Ошибка `network is unreachable` при проверке IPv6-адреса (`[2606:4700:...]`) указывает на то, что на хосте не настроена маршрутизация для IPv6.

### Настройка Prometheus для Blackbox Exporter

```yaml
scrape_configs:
  - job_name: 'blackbox'
    metrics_path: /probe # Указываем путь /probe
    params:
      module: [http_2xx] # Передаем имя модуля как параметр
    static_configs:
      - targets:
        - "http://prometheus.io" # В targets указываем НЕ blackbox-exporter, а ЦЕЛЬ для проверки
        - "https://google.com"
    relabel_configs:
      # 1. Копируем адрес цели (из targets) в параметр __param_target
      - source_labels: [__address__]
        target_label: __param_target
      # 2. Копируем __param_target в лейбл instance для красивого отображения
      - source_labels: [__param_target]
        target_label: instance
      # 3. Подменяем адрес для скрайпинга на адрес самого blackbox_exporter
      - target_label: __address__
        replacement: 127.0.0.1:9115
```
Подробнее о relabeling см. в [service_discovery_and_relabeling](./service_discovery_and_relabeling.md).

### Настройка модулей `blackbox_exporter`

Конфигурационный файл `blackbox.yml` содержит `modules`. Каждый модуль описывает, как выполнять проверку (`prober`) и ее параметры.

**Общая структура:**
```yaml
modules:
  http_2xx: # Имя модуля
    prober: http # Тип проверки: http, tcp, icmp, dns
    timeout: 5s
    http:
      valid_status_codes: [200]
      preferred_ip_protocol: "ip4"
```

*   **ICMP (ping):**
    ```yaml
    icmp_default:
      prober: icmp
      timeout: 5s
      icmp:
        preferred_ip_protocol: "ip4"
    ```
    Проверка: `curl "localhost:9115/probe?module=icmp_default&target=google.com"`

*   **DNS:**
    ```yaml
    dns_default:
      prober: dns
      timeout: 5s
      dns:
        query_name: "prometheus.io"
        preferred_ip_protocol: "ip4"
    ```
    Проверка: `curl "localhost:9115/probe?module=dns_default&target=8.8.8.8"`

*   **TCP:**
    ```yaml
    tcp_ssh_banner:
      prober: tcp
      timeout: 5s
      tcp:
        query_response:
          - expect: "^SSH-2.0-"
        preferred_ip_protocol: "ip4"
    ```
    Проверка: `curl "localhost:9115/probe?module=tcp_ssh_banner&target=127.0.0.1:22"`

*   **HTTP:**
    ```yaml
    http_2xx:
      prober: http
      timeout: 5s
      http:
        valid_http_versions: ["HTTP/1.1", "HTTP/2.0"]
        valid_status_codes: [200] # Проверка на 200 OK
        method: GET
        fail_if_body_not_matches_regexp:
          - "Prometheus" # Проверка наличия слова в теле ответа
    ```
    Проверка: `curl "localhost:9115/probe?module=http_2xx&target=http://prometheus.io"`
