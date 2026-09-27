# IPMI/BMC — Мониторинг аппаратного обеспечения серверов

## Определения

**IPMI (Intelligent Platform Management Interface)** — стандарт управления и мониторинга аппаратного обеспечения серверов на уровне BMC (Baseboard Management Controller). Работает независимо от ОС и процессора, обеспечивая доступ к данным о температуре, вентиляторах, питании и состоянии плат.

**BMC (Baseboard Management Controller)** — микроконтроллер на материнской плате сервера, реализующий интерфейс IPMI. Доступен даже при выключенном сервере (через отдельный канал питания).

**IPMI Exporter** (`prometheus-community/ipmi_exporter`) — внешний экспортер, опрашивающий BMC по протоколу IPMI и транслирующий метрики в формат Prometheus.

*   **Порт по умолчанию:** `9290`
*   **Репозиторий:** [prometheus-community/ipmi_exporter](https://github.com/prometheus-community/ipmi_exporter)

**См. также:** [Обзор экспортеров](./overview.md), [Каталог экспортеров](./other_exporters.md).

## Предварительные требования

*   **BMC:** Должен быть включен и иметь выделенный IP-адрес (обычно management network).
*   **Утилита `ipmitool`:** Требуется для локальных запросов (или удалённых через LAN).
*   **Доступ:** Учетная запись IPMI с правами на чтение датчиков (роль `Administrator` или `Operator`).
*   **Сеть:** Порты `623/udp` (RMCP) и `623/tcp` (RMCP+) должны быть доступны из сети мониторинга.
*   **Ресурсы:** ~20m CPU, 32Mi RAM на экземпляр.

## Основные концепции

### Архитектура сбора

```
┌─────────────────┐     IPMI/LAN      ┌──────────────┐
│  IPMI Exporter  │ ◄────────────────► │  BMC (B0)    │
│   :9290         │                    └──────────────┘
└────────┬────────┘
         │
         │   IPMI/LAN
         ▼
┌──────────────┐
│  BMC (B1)    │
└──────────────┘
         │
         │   (через проксирование)
         ▼
┌──────────────┐
│  BMC (B2)    │
└──────────────┘
```

### Три паттерна сбора

| Паттерн | Описание | Когда использовать |
|:---|:---|:---|
| **Remote (LAN)** | Экспортер опрашивает BMC напрямую по сети | Стандартный подход для большинства серверов |
| **Local (localhost)** | Экспортер запущен на хосте, опрашивает локальный BMC | Когда BMC не доступен по сети |
| **Проксирование** | Один экземпляр экспортера опрашивает несколько BMC | Малое количество серверов, нет отдельного management NIC |

### Ключевые метрики

| Метрика | Тип | Описание |
|:---|:---|:---|
| `ipmi_scrape_duration_seconds` | Gauge | Время опроса BMC |
| `ipmi_scrape_success` | Gauge | Успешность опроса (`1`/`0`) |
| `ipmi_dcmi_power_consumption_watts` | Gauge | Текущее потребление мощности (DCMI) |
| `ipmi_fan_speed_rpm` | Gauge | Скорость вращения вентилятора (RPM) |
| `ipmi_fan_speed_ratio` | Gauge | Относительная скорость вентилятора (0–1) |
| `ipmi_temperature_celsius` | Gauge | Температура датчика |
| `ipmi_voltage_volts` | Gauge | Напряжение на линии |
| `ipmi_current_amps` | Gauge | Ток на линии |
| `ipmi_inlet_temperature_celsius` | Gauge | Температура впускного воздуха |
| `ipmi_chassis_power_state` | Gauge | Состояние питания (`1` — вкл, `0` — выкл) |
| `ipmi_chassis_intrusion` | Gauge | Обнаружение вскрытия корпуса (`1` — вскрыт) |
| `ipmi_power_supply_status` | Gauge | Статус блока питания (`0` — OK, `1` — warning, `2` — critical) |

### Лейблы метрик

| Лейбл | Описание | Пример |
|:---|:---|:---|
| `name` | Имя сенсора | `CPU Temp`, `FAN1`, `DIMM0_VREF` |
| `chassis_name` | Имя сервера в BMC | `web-server-01` |
| `entity` | Категория (Power, Temperature, Fan, Voltage) | `Temperature` |

## Практические сценарии

### Конфигурация ipmi_exporter

```yaml
# /etc/ipmi_exporter/config.yml
modules:
  default:
    username: admin
    password: "ipmi_password"
    driver: auto
    collectors:
      - dcmi
      - ipmi
      - sel
      - sm_lan
  remote:
    username: admin
    password: "ipmi_password"
    driver: auto
    timeout: 10s
    collectors:
      - dcmi
      - ipmi
```

### Systemd (bare-metal)

```ini
[Unit]
Description=IPMI Exporter
After=network.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/ipmi_exporter \
  --config.file=/etc/ipmi_exporter/config.yml \
  --web.listen-address=0.0.0.0:9290
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

### Docker Compose

```yaml
services:
  ipmi-exporter:
    image: prometheuscommunity/ipmi_exporter:latest
    container_name: ipmi-exporter
    restart: unless-stopped
    ports:
      - "9290:9290"
    volumes:
      - ./config.yml:/etc/ipmi_exporter/config.yml:ro
    privileged: true
    devices:
      - /dev/ipmi0:/dev/ipmi0
    networks:
      - monitoring

networks:
  monitoring:
    driver: bridge
```

### Prometheus Configuration

```yaml
scrape_configs:
  - job_name: 'ipmi'
    static_configs:
      - targets: ['server1-bmc:9290', 'server2-bmc:9290']
    scrape_interval: 60s
    scrape_timeout: 30s
```

### Multi-target (через URL-параметр)

```yaml
scrape_configs:
  - job_name: 'ipmi-remote'
    metrics_path: /ipmi
    params:
      target: ['bmc-server1', 'bmc-server2']
    static_configs:
      - targets: ['ipmi-exporter:9290']
    relabel_configs:
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: ipmi-exporter:9290
```

## Алертинг

```yaml
groups:
  - name: ipmi_alerts
    rules:
      # Температура выше 80°C
      - alert: ServerTemperatureHigh
        expr: ipmi_temperature_celsius > 80
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Высокая температура {{ $labels.name }} на {{ $labels.chassis_name }}"
          description: "Температура {{ $value }}°C."

      # Вентилятор остановился
      - alert: ServerFanFailed
        expr: ipmi_fan_speed_rpm == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Вентилятор {{ $labels.name }} не вращается на {{ $labels.chassis_name }}"
          description: "Скорость 0 RPM."

      # Проблема с питанием
      - alert: ServerPowerSupplyFailed
        expr: ipmi_power_supply_status > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Проблема с БП {{ $labels.name }} на {{ $labels.chassis_name }}"
          description: "Статус: {{ $value }}."

      # Вскрытие корпуса
      - alert: ServerChassisIntrusion
        expr: ipmi_chassis_intrusion == 1
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Обнаружено вскрытие корпуса {{ $labels.chassis_name }}"

      # Выключенный сервер (неожиданно)
      - alert: ServerPowerOff
        expr: ipmi_chassis_power_state == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Сервер {{ $labels.chassis_name }} выключен"

      # Высокое потребление мощности
      - alert: ServerHighPowerConsumption
        expr: ipmi_dcmi_power_consumption_watts > 500
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Высокое потребление {{ $labels.chassis_name }}"
          description: "{{ $value }}W."
```

## Типичные ошибки и устранение неполадок

| Проблема | Причина | Решение |
|:---|:---|:---|
| `ipmi_scrape_success == 0` | Неверные креды или BMC недоступен | Проверьте `ipmitool -I lanplus -H bmc -U admin -P pass chassis status` |
| Метрики не обновляются | BMC блокирует запросы (rate limit) | Увеличьте `scrape_interval` до 120s |
| `connection refused` | Firewall блокирует порт 623 | Разрешите `623/udp` и `623/tcp` к BMC |
| `timeout` на удалённом BMC | Медленная сеть или BMC перегружен | Увеличьте `timeout` до 30s |
| `unknown sensor` | Датчик не поддерживается | Проверьте `ipmi-sensors` на сервере |

## Лучшие практики

1.  **Отдельная management сеть:** BMC всегда должны быть в изолированной сети мониторинга.
2.  **Более длинный scrape_interval:** 60–120s — IPMI-запросы медленные и нагружают BMC.
3.  **Валидация через `ipmitool`:** Перед настройкой экспортера протестируйте доступ: `ipmitool -I lanplus -H <bmc> -U <user> -P <pass> sensor list`.
4.  **Фильтрация датчиков:** Используйте `collectors` для ограничения набора опрашиваемых данных.
5.  **Физический мониторинг:** IPMI — единственный источник данных о температуре, вентиляторах и питании, когда сервер выключен или ОС зависла.

## См. также

*   [Node Exporter](./node_exporter.md) — мониторинг ОС (дополняет IPMI)
*   [Техническое обслуживание серверов](../../../Linux/SystemAdministration/server_maintenance.md) — апдейт прошивки BMC
*   [Обзор экспортеров](./overview.md) — принципы выбора экспортера
