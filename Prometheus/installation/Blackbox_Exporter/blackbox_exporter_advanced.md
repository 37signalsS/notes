# Blackbox Exporter: Дополнительные темы

## 1. Рекомендации по безопасности

### 1.1. Ограничение доступа

```bash
# Разрешите доступ только с доверенных IP
ufw allow from 10.0.0.0/8 to any port 9115
```

### 1.2. TLS через reverse proxy

```nginx
server {
    listen 443 ssl;
    server_name blackbox.example.com;

    ssl_certificate /etc/ssl/certs/blackbox.crt;
    ssl_certificate_key /etc/ssl/private/blackbox.key;

    location / {
        proxy_pass http://localhost:9115;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 2. Установка через Docker

```bash
docker run -d \
  --name blackbox-exporter \
  -p 9115:9115 \
  -v /etc/blackbox_exporter/blackbox.yml:/etc/blackbox_exporter/blackbox.yml \
  prom/blackbox-exporter:v0.28.0 \
  --config.file=/etc/blackbox_exporter/blackbox.yml
```

## 3. Параметры запуска

| Параметр | По умолчанию | Описание |
| :--- | :--- | :--- |
| `--config.file` | `blackbox.yml` | Путь к конфигурации |
| `--web.listen-address` | `:9115` | Адрес для веб-интерфейса |
| `--log.level` | `info` | Уровень логирования |

## 4. Устранение неполадок

### 4.1. Blackbox Exporter не запускается

```bash
# Проверка логов
journalctl -u blackbox_exporter -f

# Проверка портов
ss -tnlp | grep 9115

# Проверка конфигурации
blackbox_exporter --config.file=/etc/blackbox_exporter/blackbox.yml --dry-run
```

### 4.2. Проверка не выполняется

- Проверьте доступность цели из сети
- Убедитесь, что таймаут достаточен
- Проверьте логи на ошибки

## Связанные документы

- **[Основные концепции](./blackbox_exporter_concepts.md)** — определения и возможности
- **[Установка и настройка](./blackbox_exporter_installation.md)** — установка, конфигурация, интеграция
- **[Blackbox Exporter](../../Exporters/blackbox_exporter.md)** — полное руководство
- **[Prometheus Server](../prometheus_server_installation.md)** — интеграция
- **[Configuration](../configuration.md)** — настройка Prometheus
- **[Docker Stack](../docker_stack/remote_hosts_monitoring.md)** — мониторинг удалённых хостов
