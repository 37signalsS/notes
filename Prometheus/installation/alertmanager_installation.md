# Установка Alertmanager

Данное руководство описывает процесс развёртывания Alertmanager на Linux-системах и в Docker.

> **Важно:** Перед установкой ознакомьтесь с архитектурой и принципами работы в основном разделе **[Alertmanager — управление оповещениями](../alertmanager.md)**.

## Актуальная версия

| Параметр | Значение |
|---|---|
| **Последняя стабильная версия** | `0.32.0` (апрель 2026) |
| **Репозиторий** | [prometheus/alertmanager](https://github.com/prometheus/alertmanager) |

> Полный список ключей запуска и их описание доступны в разделе **[Ключи запуска](../alertmanager.md#веб-интерфейс-и-ключи-запуска)**.

## Практические сценарии

### Установка из бинарных файлов (Linux)

**1. Создание пользователя:**

```bash
useradd --no-create-home --shell /bin/false alertmanager --comment "User to run Alertmanager"
```

**2. Загрузка и установка:**

```bash
ALERTMANAGER_VERSION="0.32.0"
cd /tmp
wget https://github.com/prometheus/alertmanager/releases/download/v${ALERTMANAGER_VERSION}/alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
tar xvfz alertmanager-${ALERTMANAGER_VERSION}.linux-amd64.tar.gz
cd alertmanager-${ALERTMANAGER_VERSION}.linux-amd64
mv alertmanager amtool /usr/local/bin/
```

**3. Настройка каталогов и конфигурации:**

```bash
mkdir -p /etc/alertmanager
cp alertmanager.yml /etc/alertmanager/alertmanager.yml
chown -R alertmanager:alertmanager /etc/alertmanager

mkdir -p /var/lib/alertmanager
chown alertmanager:alertmanager /var/lib/alertmanager
```

**4. Создание файла с опциями запуска** (`/etc/sysconfig/alertmanager`):

```bash
cat <<EOF > /etc/sysconfig/alertmanager
OPTIONS="--config.file=/etc/alertmanager/alertmanager.yml \
--storage.path=/var/lib/alertmanager/ \
--web.listen-address=:9093 \
--cluster.listen-address="
EOF
```

> **Примечание:** Пустой `--cluster.listen-address=` отключает кластеризацию для одиночного инстанса. Подробнее о кластеризации: **[Высокая доступность — HA](../alertmanager.md#высокая-доступность-ha)**.

**5. Создание systemd-сервиса** (`/etc/systemd/system/alertmanager.service`):

```bash
cat <<EOF > /etc/systemd/system/alertmanager.service
[Unit]
Description=Prometheus Alertmanager
Documentation=https://prometheus.io/docs/alerting/latest/alertmanager/
After=network-online.target

[Service]
User=alertmanager
Group=alertmanager
Restart=always
EnvironmentFile=/etc/sysconfig/alertmanager
ExecStart=/usr/local/bin/alertmanager \$OPTIONS
ExecReload=/bin/kill -HUP \$MAINPID
TimeoutStopSec=20s

[Install]
WantedBy=multi-user.target
EOF
```

**6. Запуск и проверка:**

```bash
systemctl daemon-reload
systemctl start alertmanager
systemctl enable alertmanager

# Проверка доступности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9093
```

### Проверка конфигурации

Для проверки синтаксиса используйте утилиту `amtool`:

```bash
amtool check-config /etc/alertmanager/alertmanager.yml
```

### Установка через Docker

```bash
docker run -d \
  --name alertmanager \
  -p 9093:9093 \
  -v /etc/alertmanager/alertmanager.yml:/etc/alertmanager/alertmanager.yml \
  -v alertmanager-data:/alertmanager \
  prom/alertmanager:v0.32.0 \
  --config.file=/etc/alertmanager/alertmanager.yml \
  --storage.path=/alertmanager
```

## Дополнительная информация

*   **Настройка уведомлений:** подробные примеры `alertmanager.yml` и логика маршрутизации описаны в **[Конфигурация Alertmanager](../alertmanager.md#конфигурация-alertmanageryml)**.
*   **Безопасность:** рекомендации по защите инстанса доступны в разделе **[Безопасность и лучшие практики](../alertmanager.md#безопасность-и-лучшие-практики)**.
*   **Интеграция с Prometheus:** см. [Обзор Prometheus](../overview.md).
