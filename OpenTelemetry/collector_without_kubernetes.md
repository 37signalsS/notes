# OpenTelemetry: Collector в не-Kubernetes средах

## Определения

**OpenTelemetry Collector в не-Kubernetes средах** — это развёртывание и управление Collector на bare-metal серверах, виртуальных машинах или Docker Compose без использования Kubernetes. Включает установку, конфигурацию, мониторинг и обновление.

В 2026 году OTel Collector поддерживает различные среды, включая legacy-инфраструктуру.

## Теоретический блок

### Варианты развёртывания

| Среда | Инструмент | Преимущества |
| :--- | :--- | :--- |
| **Bare-metal** | Systemd, Docker | Полный контроль, минимальный оверхед |
| **Виртуальные машины** | Cloud-init, Ansible | Стандартная инфраструктура |
| **Docker Compose** | docker-compose.yml | Простота, воспроизводимость |

### Архитектура

```text
Приложение → OTel SDK → Collector (локальный) → Backend (удалённый)
                         ↓
                    Systemd/Docker
```

## Практические сценарии

### Сценарий 1: Установка на bare-metal (Systemd)

**Установка Collector:**

```bash
# Скачивание Collector
wget https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v0.96.0/otelcol_0.96.0_linux_amd64.tar.gz

# Распаковка
tar -xzf otelcol_0.96.0_linux_amd64.tar.gz
mv otelcol /usr/local/bin/otelcol

# Создание пользователя
useradd -r -s /bin/false otelcol

# Создание директорий
mkdir -p /etc/otelcol /var/lib/otelcol
chown otelcol:otelcol /etc/otelcol /var/lib/otelcol
```

**Systemd unit:**

```ini
# /etc/systemd/system/otelcol.service
[Unit]
Description=OpenTelemetry Collector
After=network.target

[Service]
User=otelcol
Group=otelcol
Type=simple
ExecStart=/usr/local/bin/otelcol --config=/etc/otelcol/config.yaml
Restart=always
RestartSec=5
LimitNOFILE=65536
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
```

**Конфигурация Collector:**

```yaml
# /etc/otelcol/config.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512
  batch:
    timeout: 10s

exporters:
  otlp/backend:
    endpoint: "backend:4317"
    tls:
      insecure: false
      cert_file: /etc/otelcol/certs/client.crt
      key_file: /etc/otelcol/certs/client.key

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/backend]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/backend]
```

**Запуск:**

```bash
systemctl daemon-reload
systemctl enable otelcol
systemctl start otelcol
systemctl status otelcol
```

### Сценарий 2: Docker Compose

**docker-compose.yml:**

```yaml
version: '3.8'
services:
  otel-collector:
    image: otel/opentelemetry-collector-contrib:0.96.0
    container_name: otel-collector
    volumes:
      - ./config.yaml:/etc/otelcol/config.yaml
      - ./certs:/etc/otelcol/certs
    ports:
      - "4317:4317"
      - "4318:4318"
      - "8888:8888"
    environment:
      - OTEL_SERVICE_NAME=otel-collector
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8888/"]
      interval: 30s
      timeout: 10s
      retries: 3
```

**Запуск:**

```bash
docker compose up -d
docker compose logs -f otel-collector
```

### Сценарий 3: Автоматизация через Ansible

**Playbook для установки Collector:**

```yaml
# install_otelcol.yml
---
- hosts: monitoring
  become: yes
  vars:
    otelcol_version: "0.96.0"
    otelcol_config_dir: /etc/otelcol
    otelcol_service_name: otelcol

  tasks:
    - name: Скачать Collector
      get_url:
        url: "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v{{ otelcol_version }}/otelcol_{{ otelcol_version }}_linux_amd64.tar.gz"
        dest: "/tmp/otelcol_{{ otelcol_version }}_linux_amd64.tar.gz"

    - name: Распаковать Collector
      unarchive:
        src: "/tmp/otelcol_{{ otelcol_version }}_linux_amd64.tar.gz"
        dest: /usr/local/bin/
        remote_src: yes

    - name: Создать пользователя
      user:
        name: otelcol
        system: yes
        shell: /bin/false

    - name: Создать конфигурацию
      template:
        src: templates/config.yaml.j2
        dest: "{{ otelcol_config_dir }}/config.yaml"
      notify: restart otelcol

    - name: Создать systemd unit
      template:
        src: templates/otelcol.service.j2
        dest: "/etc/systemd/system/{{ otelcol_service_name }}.service"
      notify: restart otelcol

  handlers:
    - name: restart otelcol
      systemd:
        name: "{{ otelcol_service_name }}"
        state: restarted
        daemon_reload: yes
```

## Дополнительная информация

### Типичные проблемы и решение

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Collector не стартует** | Ошибка в конфигурации | Проверить `otelcol validate --config=config.yaml` |
| **Нет данных в backend** | Неверный endpoint или TLS | Проверить логи, сертификаты |
| **Высокое потребление памяти** | Отсутствует memory_limiter | Настроить memory_limiter processor |
| **Порт занят** | Конфликт с другим сервисом | Изменить порт в конфигурации |

### Best Practices

1. **Используйте Systemd** — для автоматического перезапуска и управления.
2. **Настраивайте healthcheck** — для мониторинга состояния Collector.
3. **Резервируйте конфигурацию** — храните в Git.
4. **Мониторьте ресурсы** — отслеживайте CPU, память, диск.
5. **Регулярно обновляйте** — обновляйте Collector до последней версии.

### Ссылки

- [OTel Collector Releases](https://github.com/open-telemetry/opentelemetry-collector-releases)
- [OTel Collector Documentation](https://opentelemetry.io/docs/collector/)
- [Systemd Documentation](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
