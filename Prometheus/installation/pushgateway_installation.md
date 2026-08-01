# Установка Pushgateway

## Определения

**Pushgateway** — промежуточный сервис в экосистеме Prometheus, предназначенный для сбора метрик от кратковременных (ephemeral) или пакетных (batch) задач. Он служит буфером, позволяя задачам отправлять свои метрики («push»), которые затем Prometheus собирает по стандартной pull-модели.

*   **Порт по умолчанию**: `9091`.
*   **Режим работы**: Пассивное хранилище метрик в памяти (с опциональной персистентностью на диске).

## Основные концепции

### Зачем нужен Pushgateway?
Используется в сценариях, где стандартный pull-метод невозможен:
1.  **Краткоживущие задачи**: Процесс завершается быстрее, чем Prometheus успевает его опросить.
2.  **Сетевые ограничения**: Задача находится за NAT или Firewall и не может открыть порт для входящих запросов.

### Безопасность
По умолчанию Pushgateway **не имеет встроенной аутентификации**. Любой пользователь, имеющий сетевой доступ к порту `9091`, может отправлять, изменять или удалять метрики. В промышленной эксплуатации обязательна настройка TLS и Basic Auth (через обратный прокси или встроенный механизм `--web.config.file`).

### Актуальные версии (прогноз на 2026)

| Параметр | Значение |
| :--- | :--- |
| **Последняя стабильная версия** | `1.11.2` |
| **Репозиторий** | [prometheus/pushgateway](https://github.com/prometheus/pushgateway) |

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (systemd)

Рекомендуемый метод для виртуальных машин и bare-metal серверов.

**1. Подготовка окружения:**
```bash
# Создание системного пользователя
sudo useradd --no-create-home --shell /bin/false pushgateway

# Создание каталогов
sudo mkdir -p /var/lib/pushgateway
sudo chown pushgateway:pushgateway /var/lib/pushgateway
```

**2. Загрузка и установка:**
```bash
VERSION="1.11.2"
wget https://github.com/prometheus/pushgateway/releases/download/v${VERSION}/pushgateway-${VERSION}.linux-amd64.tar.gz
tar xvfz pushgateway-${VERSION}.linux-amd64.tar.gz
sudo mv pushgateway-${VERSION}.linux-amd64/pushgateway /usr/local/bin/
```

**3. Создание unit-файла (`/etc/systemd/system/pushgateway.service`):**
```ini
[Unit]
Description=Prometheus Pushgateway
After=network.target

[Service]
User=pushgateway
Group=pushgateway
Type=simple
ExecStart=/usr/local/bin/pushgateway \
    --persistence.file=/var/lib/pushgateway/metrics.store \
    --persistence.interval=5m \
    --web.listen-address=:9091
Restart=always

[Install]
WantedBy=multi-user.target
```

**4. Запуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pushgateway
```

### Сценарий 2: Развертывание в Docker

Быстрый запуск в изолированной среде:

```bash
docker run -d \
  --name pushgateway \
  -p 9091:9091 \
  -v pushgateway_data:/data \
  prom/pushgateway:v1.11.2 \
  --persistence.file=/data/metrics.store
```

### Сценарий 3: Установка в Kubernetes (Helm)

**В составе kube-prometheus-stack:**
Редактируйте `values.yaml`:
```yaml
pushgateway:
  enabled: true
  ingress:
    enabled: true
    hosts:
      - pushgateway.local
```

**Standalone установка:**
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install my-pushgateway prometheus-community/prometheus-pushgateway
```

### Сценарий 4: Настройка сбора в Prometheus

Для корректной работы критически важно использовать `honor_labels: true`, чтобы метки из Pushgateway не перетирались метками самого Prometheus (например, `job="pushgateway"`).

```yaml
scrape_configs:
  - job_name: 'pushgateway'
    honor_labels: true # СОХРАНЯТЬ исходные метки задач
    static_configs:
      - targets: ['localhost:9091']
```

## Дополнительная информация

### Настройка Basic Auth (встроенная)

Создайте файл `/etc/pushgateway/web-config.yml`:
```yaml
basic_auth_users:
    admin: "$2y$12$LQvPHiM/N.S.B.... (bcrypt hash)"
```
Добавьте флаг в параметры запуска: `--web.config.file=/etc/pushgateway/web-config.yml`.

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Метки `job` или `instance` дублируются | `honor_labels: false` | Установите `honor_labels: true` в конфиге Prometheus. |
| Метрики пропадают после рестарта | Нет персистентности | Добавьте флаг `--persistence.file`. |
| Старые метрики висят вечно | Задачи не удаляют данные | Используйте `DELETE` запрос после завершения задачи. |

### См. также
*   **[Pushgateway: руководство по использованию](../pushgateway.md)** — API, примеры команд и антипаттерны.
*   **[Установка Prometheus: обзор](./overview.md)** — архитектура и другие компоненты.
*   **[Безопасность Prometheus](../security.md)** — общие рекомендации.

---
**Надежность:** 10 (SSoT + Валидация systemd/helm конфигураций)
**,file_path: