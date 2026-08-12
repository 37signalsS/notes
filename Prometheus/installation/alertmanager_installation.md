# Установка Alertmanager

## Определения

**Alertmanager** — центральный компонент экосистемы Prometheus, отвечающий за обработку, агрегацию и доставку оповещений. Основные функции: дедупликация (удаление дублей от HA-пар Prometheus), группировка алертов и маршрутизация уведомлений (Slack, Telegram, Email, Webhooks).

*   **amtool** — официальная CLI-утилита для взаимодействия с API Alertmanager, проверки конфигурации и управления «тишиной» (silences).
*   **Gossip-протокол** — механизм обмена состоянием между узлами кластера для синхронизации данных о доставленных уведомлениях и созданных паузах.

## Основные концепции

### Модели развертывания

1.  **Standalone (Одиночный узел)**: Подходит для сред разработки и небольших инсталляций. Не обеспечивает отказоустойчивость.
2.  **High Availability (HA Cluster)**: Кластер из 3 и более узлов. Рекомендуется для Production. Гарантирует доставку уведомлений при выходе из строя части узлов. В Kubernetes реализуется через `replicas: 3` в операторе.

### Сетевая архитектура и порты

| Порт | Протокол | Назначение |
| :--- | :--- | :--- |
| **9093** | TCP | Web UI и API (для Prometheus и amtool) |
| **9094** | TCP / UDP | Кластерный обмен (Gossip) |

### Безопасность (Hardening)

По умолчанию Alertmanager открыт для всех входящих запросов. Для защиты в промышленной эксплуатации необходимо:
*   **Встроенный TLS/Auth**: Использование `--web.config.file` для активации HTTPS и Basic Auth.
*   **Изоляция процесса**: Настройка параметров `systemd` для ограничения привилегий (ReadOnly, NoNewPrivileges).
*   **mTLS для Gossip**: Шифрование межузлового трафика в кластере.

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (systemd)

Метод обеспечивает максимальный контроль и рекомендуется для bare-metal/VM серверов.

**1. Подготовка системного пользователя и директорий:**
```bash
# Создание пользователя без прав входа
sudo useradd --no-create-home --shell /bin/false alertmanager

# Создание каталогов для конфигурации и БД
sudo mkdir -p /etc/alertmanager /var/lib/alertmanager
sudo chown alertmanager:alertmanager /etc/alertmanager /var/lib/alertmanager
# → Directories created with correct ownership
```

**2. Установка бинарных файлов (v0.33.1):**
```bash
VERSION="0.33.1"
wget https://github.com/prometheus/alertmanager/releases/download/v${VERSION}/alertmanager-${VERSION}.linux-amd64.tar.gz
tar xvfz alertmanager-${VERSION}.linux-amd64.tar.gz
sudo mv alertmanager-${VERSION}.linux-amd64/alertmanager /usr/local/bin/
sudo mv alertmanager-${VERSION}.linux-amd64/amtool /usr/local/bin/
# → Alertmanager and amtool installed to /usr/local/bin/
```

**3. Настройка unit-файла (`/etc/systemd/system/alertmanager.service`):**
```ini
[Unit]
Description=Prometheus Alertmanager
Documentation=https://prometheus.io/docs/alerting/latest/alertmanager/
After=network.target

[Service]
User=alertmanager
Group=alertmanager
Type=simple
ExecStart=/usr/local/bin/alertmanager \
    --config.file=/etc/alertmanager/alertmanager.yml \
    --storage.path=/var/lib/alertmanager/ \
    --web.listen-address=:9093
Restart=always
# Hardening
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

**4. Запуск и проверка:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now alertmanager
# Проверка доступности
curl -s http://localhost:9093/-/healthy
# → OK
```

### Сценарий 2: Развертывание HA-кластера (3 узла)

Для корректной работы Gossip необходимо указать адрес для прослушивания кластерного трафика и адреса соседей.

```bash
# Пример флагов запуска для Node-1 (IP: 10.0.0.1)
alertmanager \
  --cluster.listen-address=10.0.0.1:9094 \
  --cluster.peer=10.0.0.2:9094 \
  --cluster.peer=10.0.0.3:9094 \
  --config.file=/etc/alertmanager/alertmanager.yml
# → [INFO] Marshaling gossip message...
```

### Сценарий 3: Настройка и использование amtool

`amtool` позволяет управлять алертами без использования браузера.

**1. Создание конфигурации (`~/.config/amtool/config.yml`):**
```yaml
alertmanager.url: "http://localhost:9093"
output: extended
```

**2. Практические команды:**
```bash
# Проверка синтаксиса конфигурации
amtool check-config /etc/alertmanager/alertmanager.yml
# → SUCCESS

# Просмотр активных оповещений
amtool alert
# → [Alertname] [Severity] [Starts At] ...

# Создание тишины (Silence) для подавления алертов
amtool silence add alertname=DiskFull --duration=2h --comment="Planned maintenance"
# → Silence ID: 12345-abcde...
```

## Дополнительная информация

### Защита Web-интерфейса (Native Auth)

Создайте файл `/etc/alertmanager/web-config.yml`:
```yaml
tls_server_config:
  cert_file: /etc/alertmanager/certs/server.crt
  key_file: /etc/alertmanager/certs/server.key

basic_auth_users:
  admin: "$2y$12$..." # bcrypt hash
```
Добавьте флаг `--web.config.file=/etc/alertmanager/web-config.yml` в параметры запуска.

### См. также
*   **[Конфигурация Alertmanager](../alertmanager.md)** — подробное описание логики маршрутизации.
*   **[Установка Prometheus: обзор](./overview.md)** — сравнение методов развертывания всего стека.
*   **[Безопасность и лучшие практики](../alertmanager.md#безопасность-и-лучшие-практики)**.
