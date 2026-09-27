# Docker-развертывание Wazuh: Docker Compose стек

## Определения

**Docker Compose** — инструмент для оркестрации multi-container Docker-приложений. Позволяет развернуть полный стек Wazuh (Manager, Indexer, Dashboard) в одном `docker-compose.yml`.

**Containerized Deployment** — развёртывание Wazuh в контейнерах. Альтернатива bare-metal/VM установке. Подходит для development, testing, POC и небольших production-сред.

**Volume** — Docker volume для персистентного хранения данных (Indexer data, конфигурации, логи).

## Основные концепции

### Архитектура Docker Compose стека

```
┌─────────────────────────────────────────────┐
│              Docker Network                  │
│                                              │
│  ┌──────────────┐  ┌──────────────────────┐ │
│  │ wazuh-manager│  │ wazuh-indexer        │ │
│  │ (Container)  │←→│ (Container)          │ │
│  │  Port: 1514  │  │  Port: 9200          │ │
│  │  Port: 55000 │  │  Volume: indexer-data│ │
│  └──────┬───────┘  └──────────────────────┘ │
│         │                                    │
│  ┌──────┴───────┐  ┌──────────────────────┐ │
│  │ wazuh-dashboard│  │ wazuh-agent         │ │
│  │ (Container)  │  │ (Optional sidecar)   │ │
│  │  Port: 443   │  │                      │ │
│  └──────────────┘  └──────────────────────┘ │
└─────────────────────────────────────────────┘
```

## Практические сценарии

### 1. docker-compose.yml: полный стек

```yaml
version: '3.8'

services:
  wazuh-indexer:
    image: wazuh/wazuh-indexer:5.0
    hostname: wazuh-indexer
    container_name: wazuh-indexer
    ports:
      - "9200:9200"
    environment:
      - "discovery.type=single-node"
      - "DISABLE_SECURITY_PLUGIN=true"
      - "OPENSEARCH_JAVA_OPTS=-Xms2g -Xmx2g"
      - "cluster.name=wazuh-indexer-cluster"
      - "node.name=wazuh-indexer"
    volumes:
      - indexer_data:/usr/share/opensearch/data
      - ./config/wazuh-indexer/opensearch.yml:/usr/share/opensearch/config/opensearch.yml
    networks:
      - wazuh-net
    healthcheck:
      test: ["CMD", "curl", "-k", "https://localhost:9200/_cluster/health"]
      interval: 30s
      timeout: 10s
      retries: 5

  wazuh-manager:
    image: wazuh/wazuh-manager:5.0
    hostname: wazuh-manager
    container_name: wazuh-manager
    ports:
      - "1514:1514"
      - "1515:1515"
      - "55000:55000"
    environment:
      - "INDEXER_URL=https://wazuh-indexer:9200"
      - "INDEXER_USER=admin"
      - "INDEXER_PASS=admin"
    volumes:
      - manager_etc:/var/ossec/etc
      - manager_logs:/var/ossec/logs
      - manager_queue:/var/ossec/queue
      - manager_integrations:/var/ossec/integrations
      - ./config/wazuh-manager/ossec.conf:/var/ossec/etc/ossec.conf
    depends_on:
      wazuh-indexer:
        condition: service_healthy
    networks:
      - wazuh-net

  wazuh-dashboard:
    image: wazuh/wazuh-dashboard:5.0
    hostname: wazuh-dashboard
    container_name: wazuh-dashboard
    ports:
      - "443:443"
    environment:
      - "INDEXER_URL=https://wazuh-indexer:9200"
      - "DASHBOARD_URL=https://wazuh-dashboard:443"
      - "INDEXER_USERNAME=admin"
      - "INDEXER_PASSWORD=admin"
    volumes:
      - ./config/wazuh-dashboard/opensearch_dashboards.yml:/usr/share/wazuh-dashboard/config/opensearch_dashboards.yml
    depends_on:
      wazuh-indexer:
        condition: service_healthy
      wazuh-manager:
        condition: service_started
    networks:
      - wazuh-net

volumes:
  indexer_data:
    driver: local
  manager_etc:
    driver: local
  manager_logs:
    driver: local
  manager_queue:
    driver: local
  manager_integrations:
    driver: local

networks:
  wazuh-net:
    driver: bridge
```

### 2. Конфигурация Indexer

```yaml
# config/wazuh-indexer/opensearch.yml
cluster.name: wazuh-indexer-cluster
node.name: wazuh-indexer
network.host: 0.0.0.0
discovery.type: single-node
plugins.security.ssl.transport.pemcert_filepath: esnode.pem
plugins.security.ssl.transport.pemkey_filepath: esnode-key.pem
plugins.security.ssl.transport.pemtrustedcas_filepath: root-ca.pem
plugins.security.ssl.transport.enforce_hostname_verification: false
plugins.security.ssl.http.enabled: true
plugins.security.ssl.http.pemcert_filepath: esnode.pem
plugins.security.ssl.http.pemkey_filepath: esnode-key.pem
plugins.security.ssl.http.pemtrustedcas_filepath: root-ca.pem
plugins.security.allow_unsafe_dangerous_http_enabled: true
```

### 3. Конфигурация Manager

```xml
<!-- config/wazuh-manager/ossec.conf -->
<ossec_config>
  <global>
    <email_notification>no</email_notification>
  </global>

  <remote>
    <connection>syslog</connection>
    <port>514</port>
    <protocol>udp</protocol>
  </remote>

  <alerts>
    <log_alert_level>1</log_alert_level>
    <email_alert_level>7</email_alert_level>
  </alerts>

  <command>
    <name>firewall-drop</name>
    <executable>firewall-drop.sh</executable>
    <expect>srcip</expect>
    <timeout_allowed>yes</timeout_allowed>
  </command>

  <active-response>
    <command>firewall-drop</command>
    <location>local</location>
    <rules_id>5720</rules_id>
    <timeout>600</timeout>
  </active-response>
</ossec_config>
```

### 4. Конфигурация Dashboard

```yaml
# config/wazuh-dashboard/opensearch_dashboards.yml
server.host: "0.0.0.0"
server.port: 5601
opensearch.hosts: ["https://wazuh-indexer:9200"]
opensearch.ssl.verificationMode: none
opensearch.username: "admin"
opensearch.password: "admin"
opensearch.requestHeadersAllowlist: ["securitytenant", "Authorization"]
opensearch_security.multitenancy.enabled: false
opensearch_security.readonly_mode.roles: ["kibana_read_only"]
```

### 5. Запуск

```bash
# Запуск стека
docker-compose up -d

# Проверка статуса
docker-compose ps

# Логи
docker-compose logs -f wazuh-manager
docker-compose logs -f wazuh-indexer

# Остановка
docker-compose down

# Остановка с удалением данных
docker-compose down -v
```

### 6. Установка агента в контейнере

```yaml
# Добавление агента в docker-compose
  wazuh-agent:
    image: wazuh/wazuh-agent:5.0
    hostname: wazuh-agent
    container_name: wazuh-agent
    environment:
      - "WAZUH_MANAGER=wazuh-manager"
      - "WAZUH_MANAGER_PORT=1515"
      - "WAZUH_AGENT_GROUP=linux-servers"
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - wazuh-net
```

### 7. Backup/Restore

```bash
# Бэкап Indexer данных
docker-compose exec wazuh-indexer tar czf /tmp/indexer-backup.tar.gz -C /usr/share/opensearch/data .
docker cp wazuh-indexer:/tmp/indexer-backup.tar.gz ./backups/

# Бэкап Manager конфигурации
docker cp wazuh-manager:/var/ossec/etc ./backups/manager-etc/

# Восстановление
docker-compose down
docker-compose up -d wazuh-indexer
docker cp ./backups/indexer-backup.tar.gz wazuh-indexer:/tmp/
docker-compose exec wazuh-indexer tar xzf /tmp/indexer-backup.tar.gz -C /usr/share/opensearch/data
docker-compose up -d
```

## Дополнительная информация

### Когда использовать Docker-развертывание

| Сценарий | Рекомендация |
|:---|:---|
| Development / Testing | Docker Compose |
| POC / Demo | Docker Compose |
| Production (< 100 агентов) | Docker Compose |
| Production (> 100 агентов) | Bare-metal / K8s |
| High Availability | Bare-metal / K8s |
| Air-gapped | Bare-metal |

### Best Practices

1. **Volumes**: всегда используйте named volumes для данных.
2. **Healthcheck**: проверяйте здоровье контейнеров через healthcheck.
3. **Resource Limits**: задавайте `mem_limit`, `cpus` для каждого контейнера.
4. **Networks**: используйте отдельную сеть для Wazuh.
5. **Secrets**: не храните пароли в `docker-compose.yml`, используйте `.env`.
6. **Logging**: настройте log driver для централизованного сбора логов.

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **Indexer не стартует** | Недостаточно памяти | Увеличьте `mem_limit` до 4GB |
| **Manager не подключается к Indexer** | Indexer не healthy | Проверьте healthcheck |
| **Dashboard 502** | Indexer недоступен | Проверьте `docker-compose logs wazuh-indexer` |
| **Agent не регистрируется** | DNS не резолвит | Используйте service name (`wazuh-manager`) |

### См. также
- [Развертывание Wazuh](./deployment.md) — bare-metal установка.
- [Kubernetes](./wazuh-kubernetes.md) — K8s вариант.
- [Container Monitoring](./container_monitoring.md) — мониторинг контейнеров.
