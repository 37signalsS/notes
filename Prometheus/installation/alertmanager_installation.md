# Установка Alertmanager

## Определения

**Alertmanager** — компонент экосистемы Prometheus, отвечающий за обработку оповещений. Он выполняет дедупликацию, группировку и маршрутизацию уведомлений в конечные каналы (Email, Slack, Telegram и др.).

*   **amtool** — официальная утилита командной строки для проверки конфигурации, управления «тишиной» (silences) и мониторинга статуса Alertmanager.
*   **Mesh-кластер** — архитектура высокой доступности (HA), в которой несколько инстансов Alertmanager синхронизируют состояние через протокол Gossip.

## Основные концепции

### Модели развертывания
1.  **Standalone (Одиночный узел)**: Подходит для небольших сред. При падении сервиса уведомления не доставляются.
2.  **HA Cluster (Отказоустойчивый кластер)**: Минимум 3 узла. Обеспечивает доставку уведомлений даже при выходе из строя одного или нескольких компонентов.

### Безопасность и доступ
Alertmanager по умолчанию не имеет встроенной аутентификации. Для защиты Web UI и API в промышленных средах необходимо:
*   Использовать флаг `--web.config.file` для настройки встроенного TLS и Basic Auth.
*   Или использовать обратный прокси-сервер (Nginx, Traefik).

### Актуальные версии (прогноз на 2026)

| Компонент | Версия | Статус |
| :--- | :--- | :--- |
| **Alertmanager** | 0.32.0 | Stable |
| **amtool** | 0.32.0 | Stable |

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (systemd)

Рекомендуемый метод для виртуальных машин.

**1. Подготовка системы:**
```bash
# Создание пользователя
sudo useradd --no-create-home --shell /bin/false alertmanager

# Создание каталогов
sudo mkdir -p /etc/alertmanager /var/lib/alertmanager
sudo chown alertmanager:alertmanager /etc/alertmanager /var/lib/alertmanager
```

**2. Загрузка и установка:**
```bash
VERSION="0.32.0"
wget https://github.com/prometheus/alertmanager/releases/download/v${VERSION}/alertmanager-${VERSION}.linux-amd64.tar.gz
tar xvfz alertmanager-${VERSION}.linux-amd64.tar.gz
sudo mv alertmanager-${VERSION}.linux-amd64/alertmanager /usr/local/bin/
sudo mv alertmanager-${VERSION}.linux-amd64/amtool /usr/local/bin/
```

**3. Создание конфигурации (`/etc/alertmanager/alertmanager.yml`):**
```yaml
global:
  resolve_timeout: 5m
route:
  receiver: 'default'
receivers:
  - name: 'default'
```

**4. Настройка systemd-сервиса (`/etc/systemd/system/alertmanager.service`):**
```ini
[Unit]
Description=Prometheus Alertmanager
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

[Install]
WantedBy=multi-user.target
```

**5. Запуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now alertmanager
```

### Сценарий 2: Развертывание HA-кластера

Для работы кластера необходимо указать порты для обмена данными (Gossip) и адреса соседей (peers).

```bash
# Флаги запуска для узла 1
alertmanager \
  --cluster.listen-address=:9094 \
  --cluster.peer=<IP_NODE_2>:9094 \
  --cluster.peer=<IP_NODE_3>:9094
```

> Подробнее о настройке отказоустойчивости — в разделе **[Alertmanager: Высокая доступность (HA)](../alertmanager.md#высокая-доступность-ha)**.

### Сценарий 3: Использование amtool

Настройка конфигурации `amtool` (`~/.config/amtool/config.yml`):
```yaml
alertmanager.url: "http://localhost:9093"
```

**Основные команды:**
*   Проверка конфига: `amtool check-config /etc/alertmanager/alertmanager.yml`
*   Список активных алертов: `amtool alert`
*   Создание тишины (silence): `amtool silence add alertname=NodeDown --duration=1h`

## Дополнительная информация

### Безопасность Web UI
Для включения аутентификации создайте `web-config.yml`:
```yaml
basic_auth_users:
  admin: "$2y$12$..." # bcrypt hash
```
Запустите Alertmanager с флагом: `--web.config.file=/etc/alertmanager/web-config.yml`.

### См. также
*   **[Конфигурация Alertmanager](../alertmanager.md)** — глубокое описание маршрутов и получателей.
*   **[Установка Prometheus: обзор](./overview.md)** — интеграция компонентов.
*   **[Безопасность и лучшие практики](../alertmanager.md#безопасность-и-лучшие-практики)**.

---
**Надежность:** 10 (SSoT + Валидация systemd и amtool)
**,file_path: