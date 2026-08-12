# Установка Pushgateway

## Определения

**Pushgateway** — промежуточный сервис-посредник в экосистеме Prometheus, предназначенный для сбора метрик от кратковременных (ephemeral) или пакетных (batch) задач. Он служит буфером, позволяя задачам отправлять свои метрики («push»), которые затем Prometheus собирает по стандартной pull-модели.

*   **Порт по умолчанию**: `9091`.
*   **Режим работы**: Пассивное хранилище метрик в оперативной памяти с опциональным сбросом на диск для обеспечения персистентности.

## Основные концепции

### Сценарии использования

1.  **Краткоживущие задачи**: Процесс завершается быстрее, чем стандартный интервал сбора Prometheus (scrape interval).
2.  **Сетевая изоляция**: Задача находится за NAT или Firewall и не может принимать входящие TCP-соединения от сервера мониторинга.
3.  **Скрипты автоматизации**: Сбор результатов выполнения cron-задач или CI/CD пайплайнов.

### Безопасность

По умолчанию Pushgateway **не имеет встроенных механизмов защиты**. Любой пользователь с сетевым доступом может изменять или удалять метрики. Для промышленной эксплуатации (Production) необходимо:
*   **Встроенная защита**: Использование флага `--web.config.file` для настройки TLS и Basic Auth.
*   **Внешний прокси**: Развертывание Nginx или Angie перед Pushgateway для обработки HTTPS и авторизации.
*   **Сетевые политики**: Ограничение доступа к порту `9091` только для доверенных IP (отправителей метрик и сервера Prometheus).

## Практические сценарии

### Сценарий 1: Установка из бинарных файлов (Linux/systemd)

Рекомендуемый метод для выделенных серверов или виртуальных машин.

**1. Подготовка системного окружения:**
```bash
# Создание изолированного пользователя без прав входа
sudo useradd --no-create-home --shell /bin/false pushgateway

# Создание директории для хранения данных (TSDB snapshot)
sudo mkdir -p /var/lib/pushgateway
sudo chown pushgateway:pushgateway /var/lib/pushgateway
# → Directory created and permissions set
```

**2. Загрузка и размещение исполняемых файлов:**
```bash
VERSION="1.11.3"
wget https://github.com/prometheus/pushgateway/releases/download/v${VERSION}/pushgateway-${VERSION}.linux-amd64.tar.gz
tar xvfz pushgateway-${VERSION}.linux-amd64.tar.gz
sudo mv pushgateway-${VERSION}.linux-amd64/pushgateway /usr/local/bin/
# → pushgateway binary moved to /usr/local/bin/
```

**3. Настройка unit-файла systemd (`/etc/systemd/system/pushgateway.service`):**
```ini
[Unit]
Description=Prometheus Pushgateway
Documentation=https://github.com/prometheus/pushgateway
After=network.target

[Service]
User=pushgateway
Group=pushgateway
Type=simple
ExecStart=/usr/local/bin/pushgateway \
    --persistence.file=/var/lib/pushgateway/metrics.store \
    --persistence.interval=5m \
    --push.enable-utf8-names \
    --web.listen-address=:9091
Restart=always
# Hardening (Безопасность процесса)
NoNewPrivileges=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
```

**4. Активация и запуск сервиса:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pushgateway
# Проверка статуса
systemctl is-active pushgateway
# → active
```

### Сценарий 2: Запуск в Docker или Podman

Подходит для сред контейнеризации.

```bash
docker run -d \
  --name pushgateway \
  -p 9091:9091 \
  -v pushgateway_data:/data \
  prom/pushgateway:v1.11.3 \
  --persistence.file=/data/metrics.store \
  --push.enable-utf8-names
# → Container started with ID ...
```

### Сценарий 3: Установка в Kubernetes через Helm

**В составе kube-prometheus-stack:**
Редактируйте `values.yaml`:
```yaml
pushgateway:
  enabled: true
  ingress:
    enabled: true
    hosts:
      - pushgateway.cluster.local
  persistentVolume:
    enabled: true
    size: 2Gi
```

**Standalone установка:**
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install pushgateway prometheus-community/prometheus-pushgateway
# → NAME: pushgateway deployed
```

### Сценарий 4: Настройка Native TLS и Basic Auth

Создайте файл конфигурации `/etc/pushgateway/web-config.yml`:
```yaml
tls_server_config:
  cert_file: /etc/pushgateway/certs/server.crt
  key_file: /etc/pushgateway/certs/server.key

basic_auth_users:
  admin: "$2y$12$LQvPHiM/N.S.B.bcrypt.hash.here"
```
Добавьте флаг `--web.config.file=/etc/pushgateway/web-config.yml` в параметры запуска.

## Дополнительная информация

### Важные параметры сбора (Scrape Config)

Для корректного сбора данных в `prometheus.yml` **обязательно** используйте параметр `honor_labels: true`. Без него Prometheus заменит исходные метки задач своими собственными (например, установит `job="pushgateway"` для всех метрик), что сделает невозможной их идентификацию.

```yaml
scrape_configs:
  - job_name: 'pushgateway'
    honor_labels: true
    static_configs:
      - targets: ['pushgateway-host:9091']
```

### Устранение неисправностей и диагностика

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Метки `job` затираются | `honor_labels: false` | Проверьте конфиг Prometheus. |
| Ошибка 400 при отправке | Недопустимые имена меток | Используйте флаг `--push.enable-utf8-names`. |
| Данные исчезают после рестарта | Нет флага `--persistence.file` | Укажите путь к файлу хранения в параметрах запуска. |
| Память переполнена | Накопление старых метрик | Реализуйте удаление метрик через `DELETE` запрос после завершения задачи. |

### См. также
*   **[Pushgateway: руководство по использованию](../pushgateway.md)** — методы работы с API и примеры.
*   **[Установка Prometheus: обзор](./overview.md)** — сравнение методов развертывания экосистемы.
*   **[Безопасность Prometheus](../security.md)** — общие принципы защиты инфраструктуры.
