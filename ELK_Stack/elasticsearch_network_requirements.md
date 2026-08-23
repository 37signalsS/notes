# Network и Firewall Requirements

> Справочник по сетевым требованиям Elastic Stack. Порты, протоколы и конфигурация firewall.
>
> Связанные темы: безопасность — [Security Advanced](./Elasticsearch/elasticsearch_security_advanced.md); установка кластера — [Cluster Setup](./Tutorials/cluster_setup.md).

## Порты Elastic Stack

### Elasticsearch

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 9200 | HTTP/REST | API и клиентский трафик | Inbound |
| 9300 | Transport | Межузловое взаимодействие | Bidirectional |

### Kibana

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 5601 | HTTP/REST | Web UI и API | Inbound |

### Logstash

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 5044 | Beats | Прием данных от Filebeat | Inbound |
| 514 | Syslog | Прием syslog данных | Inbound |
| 5514 | Syslog (TLS) | Прием syslog данных (TLS) | Inbound |
| 9600 | HTTP/REST | Monitoring API | Inbound |
| 5000 | TCP | TCP input plugin | Inbound |
| 6379 | Redis | Redis input/output | Bidirectional |

### Beats

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 5044 | Beats | Отправка на Logstash | Outbound |
| 9200 | HTTP/REST | Отправка напрямую в ES | Outbound |

### Fleet Server

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 8220 | HTTPS | Агенты → Fleet Server | Inbound |

### APM Server

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 8200 | HTTP/REST | APM Agents → APM Server | Inbound |

### Enterprise Search

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 3002 | HTTP/REST | Web UI и API | Inbound |

## Типовая архитектура сети

```
┌─────────────────────────────────────────────────────────────┐
│                         INTERNET                            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                      LOAD BALANCER                          │
│                      (Port 443)                             │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│   Kibana 1   │      │   Kibana 2   │      │   Kibana N   │
│   (:5601)    │      │   (:5601)    │      │   (:5601)    │
└──────────────┘      └──────────────┘      └──────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              │ 9200
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  ELASTICSEARCH CLUSTER                      │
│                                                             │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐         │
│  │ Node 1  │─│ Node 2  │─│ Node 3  │─│ Node N  │         │
│  │(:9300)  │ │(:9300)  │ │(:9300)  │ │(:9300)  │         │
│  │(:9200)  │ │(:9200)  │ │(:9200)  │ │(:9200)  │         │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘         │
│         Master          Data            Ingest             │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Fleet       │      │  Logstash    │      │  Beats       │
│  Server      │      │              │      │  (sources)   │
│  (:8220)     │      │  (:5044)     │      │              │
└──────────────┘      └──────────────┘      └──────────────┘
                              │
                              ▼
                      ┌──────────────┐
                      │  Kafka       │
                      │  (optional)  │
                      └──────────────┘
```

## Firewall Rules

### Elasticsearch Node

```bash
# Входящие соединения
-A INPUT -p tcp --dport 9200 -s 10.0.0.0/8 -j ACCEPT    # Kibana, Beats, Apps
-A INPUT -p tcp --dport 9300 -s 10.0.0.0/8 -j ACCEPT    # ES nodes

# Исходящие соединения
-A OUTPUT -p tcp --dport 9300 -d 10.0.0.0/8 -j ACCEPT   # ES cluster
-A OUTPUT -p tcp --dport 9200 -d 10.0.0.0/8 -j ACCEPT   # ES API
-A OUTPUT -p tcp --dport 443 -d monitor.es.io -j ACCEPT # Elastic Cloud
```

### Kibana Server

```bash
# Входящие соединения
-A INPUT -p tcp --dport 5601 -s 10.0.0.0/8 -j ACCEPT    # Admin network
-A INPUT -p tcp --dport 5601 -s VPN_SUBNET -j ACCEPT     # VPN users

# Исходящие соединения
-A OUTPUT -p tcp --dport 9200 -d ES_SUBNET -j ACCEPT    # Elasticsearch
-A OUTPUT -p tcp --dport 443 -d kibana.es.io -j ACCEPT  # Elastic Cloud
```

### Logstash Server

```bash
# Входящие соединения
-A INPUT -p tcp --dport 5044 -s BEATS_SUBNET -j ACCEPT   # Beats
-A INPUT -p tcp --dport 514 -s SYSLOG_SUBNET -j ACCEPT   # Syslog
-A INPUT -p tcp --dport 9600 -s MONITORING_SUBNET -j ACCEPT # Monitoring

# Исходящие соединения
-A OUTPUT -p tcp --dport 9200 -d ES_SUBNET -j ACCEPT    # Elasticsearch
-A OUTPUT -p tcp --dport 6379 -d REDIS_SUBNET -j ACCEPT  # Redis
-A OUTPUT -p tcp --dport 9092 -d KAFKA_SUBNET -j ACCEPT  # Kafka
```

### Beats Agents

```bash
# Входящие соединения (обычно не требуются)
# Beats только отправляют данные

# Исходящие соединения
-A OUTPUT -p tcp --dport 9200 -d ES_SUBNET -j ACCEPT    # Elasticsearch
-A OUTPUT -p tcp --dport 5044 -d LOGSTASH_SUBNET -j ACCEPT # Logstash
-A OUTPUT -p tcp --dport 8220 -d FLEET_SUBNET -j ACCEPT  # Fleet Server
```

## Сетевые зоны (DMZ)

### Зона 1: External (Internet-facing)

```
Services: Kibana (behind reverse proxy)
Ports: 443 (HTTPS) → 5601 (internal)
Access: Authenticated users
```

### Зона 2: Internal (Application)

```
Services: Elasticsearch (no direct external access)
Ports: 9200, 9300
Access: Kibana, Beats, Apps
```

### Зона 3: Data Collection

```
Services: Logstash, Beats
Ports: 5044, 514, 6379, 9092
Access: Internal services
```

### Зона 4: Management

```
Services: Monitoring, Fleet Server
Ports: 9200 (monitoring), 8220 (fleet), 9600 (logstash)
Access: Operations team
```

## Kubernetes Network Policies

### Elasticsearch

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: elasticsearch-network-policy
spec:
  podSelector:
    matchLabels:
      app: elasticsearch
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: kibana
        - podSelector:
            matchLabels:
              app: beats
      ports:
        - port: 9200
    - from:
        - podSelector:
            matchLabels:
              app: elasticsearch
      ports:
        - port: 9300
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: elasticsearch
      ports:
        - port: 9300
```

### Kibana

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: kibana-network-policy
spec:
  podSelector:
    matchLabels:
      app: kibana
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
      ports:
        - port: 5601
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: elasticsearch
      ports:
        - port: 9200
```

## Протоколы и шифрование

### Transport Protocol (9300)

- **Протокол:** Binary TCP (custom protocol)
- **Шифрование:** TLS (обязательно в production)
- **Authentication:** Certificate-based (PKI)
- **Использование:**
  - Master ↔ Data node communication
  - Data node ↔ Data node communication
  - Cluster state updates

### HTTP Protocol (9200)

- **Протокол:** HTTP/HTTPS REST API
- **Шифрование:** TLS (обязательно в production)
- **Authentication:** Basic, SAML, OIDC, API Key, PKI
- **Использование:**
  - Client API requests
  - Kibana ↔ Elasticsearch
  - Beats/Logstash → Elasticsearch

### Beats Protocol (5044)

- **Протокол:** Custom binary protocol
- **Шифрование:** TLS (опционально, рекомендуется)
- **Использование:**
  - Filebeat → Logstash
  - Packetbeat → Logstash

## TLS Configuration

### Elasticsearch TLS

```yaml
# elasticsearch.yml
xpack.security.transport.ssl.enabled: true
xpack.security.transport.ssl.verification_mode: certificate
xpack.security.transport.ssl.keystore.path: certs/elastic-certificates.p12
xpack.security.transport.ssl.truststore.path: certs/elastic-certificates.p12

xpack.security.http.ssl.enabled: true
xpack.security.http.ssl.keystore.path: certs/elastic-certificates.p12
```

### Kibana TLS

```yaml
# kibana.yml
server.ssl.enabled: true
server.ssl.certificate: /path/to/kibana.crt
server.ssl.key: /path/to/kibana.key
elasticsearch.ssl.certificateAuthorities: /path/to/ca.crt
```

### Beats TLS

```yaml
# filebeat.yml
output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  ssl.certificate_authorities: ["/path/to/ca.crt"]
  ssl.certificate: "/path/to/client.crt"
  ssl.key: "/path/to/client.key"
```

## Производительность сети

### Рекомендации

| Component | Рекомендация |
|-----------|--------------|
| ES Nodes (9300) | 10Gbps+, <1ms latency |
| ES ↔ Kibana (9200) | 1Gbps+, <5ms latency |
| Beats → ES | 100Mbps+, <50ms latency |
| CCR (cross-DC) | 1Gbps+, <100ms latency |

### Latency Impact

```
Latency <1ms:    Optimal for cluster communication
Latency 1-5ms:   Good for search queries
Latency 5-50ms:  Acceptable for indexing
Latency >100ms:  May impact CCR and search performance
Latency >200ms:  Not recommended for CCR
```

### Bandwidth Estimation

```
Indexing:
  Bandwidth = indexing_rate × average_doc_size × replication_factor

Example:
  10,000 docs/sec × 5KB × 2 (replicas) = 100 MB/s = 800 Mbps

Search:
  Bandwidth = query_rate × average_result_size

Example:
  1,000 queries/sec × 50KB = 50 MB/s = 400 Mbps
```

## Troubleshooting Network Issues

### Не удается подключиться к Elasticsearch

```bash
# Проверка DNS
nslookup elasticsearch.company.com

# Проверка порта
telnet elasticsearch 9200
nc -zv elasticsearch 9200

# Проверка firewall
iptables -L -n | grep 9200

# Проверка TLS
openssl s_client -connect elasticsearch:9200 -servername elasticsearch
```

### High Network Latency

```bash
# Измерение latency
ping elasticsearch
traceroute elasticsearch

# Проверка bandwidth
iperf3 -c elasticsearch

# Мониторинг network stats
netstat -s
ss -ti
```

### Connection Refused

1. Проверить, слушает ли процесс порт: `netstat -tlnp | grep 9200`
2. Проверить firewall rules
3. Проверить `network.host` в elasticsearch.yml
4. Проверить bind address (0.0.0.0 vs specific IP)

## Security Checklist

### Network Security

- [ ] Elasticsearch не доступен из Internet (9200)
- [ ] Все соединения зашифрованы (TLS)
- [ ] Firewall rules настроены (whitelist по IP/subnet)
- [ ] Отдельные security groups для каждого компонента
- [ ] Monitoring traffic изолирован от production
- [ ] CCR traffic идет через dedicated network/VPN

### Access Control

- [ ] Kibana доступна только через VPN или internal network
- [ ] API keys вместо паролей для сервисных аккаунтов
- [ ] Rate limiting на API endpoints
- [ ] Audit logging включен
- [ ] Failed login attempts мониторятся

## См. также

* **[Elasticsearch: Обзор](../Elasticsearch/elasticsearch_overview.md)** — архитектура и безопасность.
* **[Security Advanced](../Elasticsearch/elasticsearch_security_advanced.md)** — TLS, RBAC, Audit Logging.
* **[Elastic Agent и Fleet](../Elasticsearch/elastic_agent_and_fleet.md)** — порты для агентов.
* **[Beats Family](../Elasticsearch/beats_family.md)** — порты для Beats.
* **[Logstash: Обзор](../Logstash/logstash_overview.md)** — порты для Logstash.
* **[Kibana: Обзор](../Kibana/kibana_overview.md)** — порты для Kibana.
* **[Настройка кластера](../Tutorials/cluster_setup.md)** — сетевая конфигурация.
