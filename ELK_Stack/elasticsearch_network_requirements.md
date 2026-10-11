# Network и Firewall Requirements

**Актуально для:** Elastic Stack 9.5.x / 8.19 LTS

> Справочник по сетевым требованиям Elastic Stack: порты, протоколы, TLS, firewall и сетевая архитектура.
>
> Связанные темы: безопасность (RBAC, audit) — [Security Advanced](./Elasticsearch/elasticsearch_security_advanced.md); установка кластера, `network.host`, bootstrap checks — [Cluster Setup](./Tutorials/cluster_setup.md); cross-cluster сеть (CCR/CCS) — [CCR и CCS](./Elasticsearch/elasticsearch_ccr_ccs.md).

## Определения

| Термин | Определение |
|---|---|
| HTTP layer | REST API Elasticsearch на порту 9200: клиентские запросы, Kibana, Beats, Logstash, мониторинг |
| Transport layer | Бинарный протокол межузлового взаимодействия на порту 9300: cluster state, выборы cluster manager, аллокация шардов |
| Cluster manager | Узел, участвующий в кворуме и управляющий состоянием кластера (терминология 8.x+; ранее — master node) |
| Coordinating node | Узел без ролей (`node.roles: []`), маршрутизирующий клиентские запросы; не хранит данные |
| Seed node | Узел из `discovery.seed_hosts`, с которого новый узел начинает обнаружение кластера |
| Remote cluster interface | Выделенный порт 9443 для cross-cluster-трафика в модели API key (8.14+); в сертификатной модели используется transport 9300 |
| Fleet Server | Прокси-сервис, через который Elastic Agent получает политики и отправляет данные в Elasticsearch |
| DMZ | Demilitarized zone — сетевая зона между внешним и внутренним периметрами |
| CCR / CCS | Cross-Cluster Replication / Cross-Cluster Search — репликация и поиск между кластерами |
| TLS / PKI | Transport Layer Security / Public Key Infrastructure — шифрование и аутентификация по сертификатам |

## Архитектура и принцип работы

### Двухпортовая модель Elasticsearch

Elasticsearch слушает два TCP-порта, и они не взаимозаменяемы:

- **9200 — HTTP/REST.** Все клиентские запросы: search, indexing, cat API, monitoring. Все официальные клиентские библиотеки, Kibana, Beats и Logstash работают через этот порт.
- **9300 — transport.** Кастомный бинарный протокол только для межузлового взаимодействия: обновления cluster state, выборы cluster manager, присоединение/выход узлов, аллокация шардов. Клиентские библиотеки его не используют (поддержка transport-клиентов в официальных библиотеках давно deprecated).
- **9443 — remote cluster interface.** Выделенный порт для cross-cluster-трафика при аутентификации API key (8.14+); в сертификатной модели remote-кластеры общаются через transport 9300.

Почему это важно для firewall: правила для 9200 и 9300 различаются по источникам. 9200 открыт клиентам, Kibana и Beat-источникам; 9300 — только узлам кластера и обязательно bidirectional (каждый узел одновременно принимает и инициирует соединения на 9300).

### Роли узлов и сетевые следствия

| Роль (`node.roles`) | Сетевое следствие |
|---|---|
| `cluster_manager` | 9300 bidirectional со всеми узлами; для HA — минимум 3 master-eligible узла (кворум) |
| `data` | 9300 со всеми узлами; 9200 — если узел принимает клиентские запросы |
| `ingest` | 9200 от источников с pipeline; 9300 со всеми узлами |
| `coordinating_only` (`node.roles: []`) | 9200 для клиентов; 9300 для связи с кластером |
| `remote_cluster_client` | исходящие соединения к remote-кластерам (9443 или 9300); исключите роль из `node.roles`, чтобы запретить узлу подключаться к remote-кластерам |

### Матрица соединений

| Источник | Назначение | Порт | Протокол | Шифрование |
|---|---|---|---|---|
| Kibana | Elasticsearch | 9200 | HTTPS | TLS (обязательно) |
| Elasticsearch node | Elasticsearch node | 9300 | TCP (binary) | TLS (обязательно) |
| Elasticsearch node | Remote cluster (API key) | 9443 | TCP | TLS |
| Elasticsearch node | Remote cluster (cert model) | 9300 | TCP | TLS |
| Beats / Elastic Agent | Logstash | 5044 | TCP | TLS (рекомендуется) |
| Beats | Elasticsearch | 9200 | HTTPS | TLS |
| Elastic Agent | Fleet Server | 8220 | HTTPS | TLS |
| Fleet Server | Elasticsearch | 9200 | HTTPS | TLS |
| Fleet Server | Kibana | 5601 | HTTPS | TLS |
| APM Agent | APM Server | 8200 | HTTP/HTTPS | TLS (рекомендуется) |
| APM Server | Elasticsearch | 9200 | HTTPS | TLS |
| Logstash | Elasticsearch | 9200 | HTTPS | TLS |
| Logstash | Kafka | 9092 | TCP | TLS (опционально) |
| Logstash | Redis | 6379 | TCP | TLS (опционально) |
| Syslog-источники | Logstash | 514 / 5514 | UDP+TCP / TCP | — / TLS |

### Типовая схема сети

```
                       ┌──────────────┐
                       │   Internet   │
                       └──────┬───────┘
                              │ 443
                       ┌──────┴───────┐
                       │  LB / Proxy  │
                       └──────┬───────┘
                              │ 5601
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
  ┌─────┴──────┐       ┌────┴──────┐        ┌─────┴──────┐
  │  Kibana 1  │       │  Kibana 2 │        │  Kibana N  │
  │   :5601    │       │   :5601   │        │   :5601    │
  └─────┬──────┘       └────┬──────┘        └─────┬──────┘
        └─────────────────────┼─────────────────────┘
                              │ 9200 (HTTPS)
  ┌───────────────────────────┼───────────────────────────┐
  │                     Elasticsearch Cluster                │
  │                                                         │
  │   ┌────────┐ ── 9300 (TLS, bidirectional) ── ┌──────┐ │
  │   │ Node 1 │                                 │Node 2│ │
  │   │ :9200  │                                 │ :9200│ │
  │   │ :9300  │                                 │ :9300│ │
  │   └────────┘                                 └──────┘ │
  │                        ... Node N                     │
  └───────────────────────────┬───────────────────────────┘
                              │ 9200 (HTTPS)
   ┌──────────┬───────────────┼───────────────┬──────────┐
   │          │               │               │          │
┌──┴───────┐ ┌┴─────────┐ ┌───┴───────┐ ┌─────┴─────┐ ┌┴──────────┐
│Logstash  │ │  Beats   │ │  Fleet    │ │    APM    │ │ Apps /    │
│  :5044   │ │  agents  │ │  Server   │ │  Server   │ │ Syslog    │
└──────────┘ └──────────┘ │  :8220    │ │  :8200    │ │ sources   │
                          └─────┬─────┘ └───────────┘ └───────────┘
                                │ 8220 (HTTPS)
                          ┌─────┴──────┐
                          │Elastic Agent│
                          └────────────┘
```

Опционально: Kafka (9092) или Redis (6379) между источниками и Logstash как буфер при пиковых нагрузках или разрывах связи с Elasticsearch.

## Порты Elastic Stack

### Elasticsearch

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 9200 | HTTP/REST | API и клиентский трафик | Inbound |
| 9300 | Transport (binary TCP) | Межузловое взаимодействие | Bidirectional |
| 9443 | TCP | Remote cluster interface (модель API key, 8.14+) | Inbound (от remote-кластеров) |

Примечания:

- Дефолтные диапазоны биндинга: `http.port` — 9200-9300, `transport.port` — 9300-9400. Если порт занят, узел поднимается на следующем свободном (9201, 9301) — в production задавайте порты явно.
- На master-eligible узлах `transport.port` должен быть одиночным значением, не диапазоном.
- С 8.0 security включен по умолчанию: TLS и аутентификация активны сразу после установки.

### Kibana

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 5601 | HTTP/REST | Web UI и API | Inbound |

Исходящий трафик: 9200 (HTTPS) к Elasticsearch.

### Logstash

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 5044 | TCP | Beats input (порт обязателен; 5044 — конвенция) | Inbound |
| 514 | TCP+UDP | syslog input (дефолтный порт плагина; плагин не поддерживает TLS) | Inbound |
| 5514 | TCP | syslog over TLS — через `tcp` input с `ssl_enabled` (конвенция, не дефолт) | Inbound |
| 9600 | HTTP | Logstash API (мониторинг, управление pipeline) | Inbound |
| 8080 | HTTP | http input (дефолт плагина) | Inbound |
| 5000 | TCP | пример tcp input (не дефолт) | Inbound |
| 6379 | TCP | Redis input/output | Bidirectional |
| 9092 | TCP | Kafka input/output | Bidirectional |

Другие input-плагины имеют свои дефолтные порты (например, gelf — 12201). Порты 514 и <1024 требуют root или `CAP_NET_BIND_SERVICE`.

### Beats

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 5044 | TCP | Отправка на Logstash | Outbound |
| 9200 | HTTPS | Отправка напрямую в ES | Outbound |
| 8220 | HTTPS | Отправка через Fleet Server | Outbound |

Packetbeat и Heartbeat дополнительно генерируют исходящие проверочные соединения (ICMP/TCP/UDP) к мониторируемым хостам; детали — в [Beats Family](./Elasticsearch/beats_family.md).

### Fleet Server

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 8220 | HTTPS | Elastic Agent → Fleet Server (дефолт self-managed) | Inbound |

Исходящий трафик: 5601 (Kibana — управление политиками), 9200 (Elasticsearch — запись данных).

### APM Server

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 8200 | HTTP/REST | APM Agents → APM Server | Inbound |

Исходящий трафик: 9200 (HTTPS) к Elasticsearch. Альтернатива с 9.2: нативный OTLP/HTTP-эндпоинт прямо в Elasticsearch на порту 9200 (metrics — GA, logs/traces — preview в 9.5, только OTLP/HTTP, не gRPC).

### Enterprise Search (legacy)

| Порт | Протокол | Назначение | Direction |
|------|----------|------------|-----------|
| 3002 | HTTP/REST | Web UI и API | Inbound |

> **Статус:** Enterprise Search удалён в Elastic 9.0. Порт 3002 актуален только для существующих развёртываний 8.x. Для новых — нативные возможности Elasticsearch (connectors, search APIs).

## Сетевые настройки

Ключевые параметры `elasticsearch.yml` (полная механика `network.host`, discovery и bootstrap checks — в [Cluster Setup](./Tutorials/cluster_setup.md)):

```yaml
network.host: 10.0.1.10        # IP узла, доступный другим узлам и клиентам
http.port: 9200                # явно — чтобы не попасть в диапазон 9200-9300
transport.port: 9300           # явно; на master-eligible — одно значение, не диапазон
discovery.seed_hosts: ["es-1:9300", "es-2:9300", "es-3:9300"]
```

- `network.host` привязывает и HTTP, и transport слои. Любое значение, кроме loopback, активирует bootstrap checks (память, file descriptors, потоки).
- Автоконфигурация single-node записывает `http.host: 0.0.0.0` — узел сразу доступен по всем интерфейсам; закрывайте 9200 firewall-правилами.
- `http.max_content_length` — лимит тела HTTP-запроса, дефолт `100mb`. Документы больше — разбивайте на части до отправки.
- `transport.tcp.compress: true` — сжатие transport-трафика (дефолт `false`); полезно на WAN-линках между DC за счёт небольшой нагрузки на CPU.
- Transport profiles (`transport.profiles.<name>.port` / `.bind_host`) — биндинг transport-слоя на разные интерфейсы и порты, например отдельный профиль для DMZ:

```yaml
transport.profiles.dmz.port: 9700-9800
transport.profiles.dmz.bind_host: 172.16.1.2
```

## Firewall Rules

Принцип: default-deny + whitelist по подсетям. Порт 9300 — bidirectional между ВСЕМИ узлами кластера. Замените `10.0.0.0/8`, `ES_SUBNET`, `BEATS_SUBNET` и другие плейсхолдеры на реальные подсети.

### Elasticsearch Node

iptables:

```bash
# Установленные соединения
-A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Входящие
-A INPUT -p tcp --dport 9200 -s 10.0.0.0/8 -j ACCEPT    # Kibana, Beats, приложения
-A INPUT -p tcp --dport 9300 -s 10.0.1.0/24 -j ACCEPT   # узлы кластера (только ES-подсеть)
-A INPUT -p tcp --dport 9443 -s 10.0.2.0/24 -j ACCEPT   # remote-кластер (API key модель)

# Исходящие
-A OUTPUT -p tcp --dport 9300 -d 10.0.1.0/24 -j ACCEPT  # cluster traffic
-A OUTPUT -p tcp --dport 9443 -d 10.0.2.0/24 -j ACCEPT  # remote cluster client
```

firewalld (RHEL/Rocky/AlmaLinux):

```bash
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.1.0/24" port port="9300" protocol="tcp" accept'
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/8" port port="9200" protocol="tcp" accept'
sudo firewall-cmd --reload
```

ufw (Ubuntu/Debian):

```bash
sudo ufw allow from 10.0.1.0/24 to any port 9300 proto tcp
sudo ufw allow from 10.0.0.0/8 to any port 9200 proto tcp
```

### Kibana Server

```bash
# Входящие
-A INPUT -p tcp --dport 5601 -s 10.0.0.0/8 -j ACCEPT    # Admin network
-A INPUT -p tcp --dport 5601 -s VPN_SUBNET -j ACCEPT    # VPN users

# Исходящие
-A OUTPUT -p tcp --dport 9200 -d ES_SUBNET -j ACCEPT    # Elasticsearch
```

### Logstash Server

```bash
# Входящие
-A INPUT -p tcp --dport 5044 -s BEATS_SUBNET -j ACCEPT   # Beats
-A INPUT -p tcp --dport 514 -s SYSLOG_SUBNET -j ACCEPT   # Syslog (TCP+UDP)
-A INPUT -p tcp --dport 9600 -s MONITORING_SUBNET -j ACCEPT # Monitoring API

# Исходящие
-A OUTPUT -p tcp --dport 9200 -d ES_SUBNET -j ACCEPT     # Elasticsearch
-A OUTPUT -p tcp --dport 6379 -d REDIS_SUBNET -j ACCEPT  # Redis
-A OUTPUT -p tcp --dport 9092 -d KAFKA_SUBNET -j ACCEPT  # Kafka
```

### Fleet Server

```bash
# Входящие
-A INPUT -p tcp --dport 8220 -s AGENT_SUBNET -j ACCEPT   # Elastic Agent

# Исходящие
-A OUTPUT -p tcp --dport 9200 -d ES_SUBNET -j ACCEPT     # Elasticsearch
-A OUTPUT -p tcp --dport 5601 -d KIBANA_SUBNET -j ACCEPT # Kibana (политики)
```

### Beats Agents

```bash
# Входящие соединения обычно не требуются — Beats только отправляют данные

# Исходящие
-A OUTPUT -p tcp --dport 9200 -d ES_SUBNET -j ACCEPT     # Elasticsearch
-A OUTPUT -p tcp --dport 5044 -d LOGSTASH_SUBNET -j ACCEPT # Logstash
-A OUTPUT -p tcp --dport 8220 -d FLEET_SUBNET -j ACCEPT  # Fleet Server
```

## Сетевые зоны (DMZ)

### Зона 1: External (Internet-facing)

```
Services: Kibana (behind reverse proxy / LB)
Ports: 443 (HTTPS) → 5601 (internal)
Access: Authenticated users
Firewall: 5601 открыт только от LB/proxy, не от клиентов напрямую
```

### Зона 2: Internal (Application)

```
Services: Elasticsearch (no direct external access)
Ports: 9200, 9300, 9443
Access: Kibana, Beats, Logstash, приложения
Firewall: 9300 — только между узлами кластера, bidirectional
```

### Зона 3: Data Collection

```
Services: Logstash, Beats, syslog-источники
Ports: 5044, 514/5514, 6379, 9092
Access: Internal services
```

### Зона 4: Management

```
Services: Fleet Server, monitoring
Ports: 8220 (fleet), 9600 (logstash API), 9200 (monitoring)
Access: Operations team
```

## Kubernetes Network Policies

> Требуется CNI с поддержкой NetworkPolicy (Calico, Cilium, Weave Net). Политики применяются per-namespace; `podSelector` без `namespaceSelector` матчит поды в том же namespace.

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

- **Протокол:** binary TCP (кастомный протокол Elasticsearch)
- **Шифрование:** TLS (обязательно в production; включено по умолчанию с 8.0)
- **Authentication:** certificate-based (PKI)
- **Использование:** cluster manager ↔ data node, data ↔ data, cluster state updates, shard allocation

### HTTP Protocol (9200)

- **Протокол:** HTTP/HTTPS REST API
- **Шифрование:** TLS (обязательно в production; включено по умолчанию с 8.0)
- **Authentication:** Basic, API Key, PKI, SAML, OIDC
- **Использование:** клиентские API-запросы, Kibana ↔ Elasticsearch, Beats/Logstash → Elasticsearch, OTLP/HTTP (9.2+)

### Beats Protocol (5044)

- **Протокол:** кастомный бинарный протокол Beats
- **Шифрование:** TLS (опционально, рекомендуется; в Logstash — `ssl => true`)
- **Использование:** Filebeat → Logstash, Packetbeat → Logstash

### Remote Cluster (9443 / 9300)

- **API key модель (8.14+):** выделенный remote cluster interface, порт 9443 (`remote_cluster.port`); TLS обязателен, аутентификация — cross-cluster API key
- **Сертиатная модель:** transport-порт 9300, аутентификация — сертификаты узлов
- Механика настройки remote-кластеров — в [CCR и CCS](./Elasticsearch/elasticsearch_ccr_ccs.md)

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

Примечания:

- С 8.0 эти настройки включены по умолчанию (security auto-configuration); пример выше — для явного задания.
- Генерация сертификатов: `elasticsearch-certutil` (форматы p12 и PEM).
- `verification_mode`: `none` (без проверки), `certificate` (проверка подписи CA, без проверки имени хоста), `full` (подпись + имя хоста — рекомендуется).

### Kibana TLS

```yaml
# kibana.yml
server.ssl.enabled: true
server.ssl.certificate: /path/to/kibana.crt
server.ssl.key: /path/to/kibana.key
elasticsearch.ssl.certificateAuthorities: /path/to/ca.crt
elasticsearch.ssl.verificationMode: full
```

### Beats TLS

```yaml
# filebeat.yml
output.elasticsearch:
  hosts: ["https://elasticsearch:9200"]
  ssl.certificate_authorities: ["/path/to/ca.crt"]
  ssl.certificate: "/path/to/client.crt"
  ssl.key: "/path/to/client.key"
  ssl.verification_mode: full
```

### Logstash: Beats input с TLS

```ruby
input {
  beats {
    port => 5044
    ssl => true
    ssl_certificate => "/etc/pki/logstash/logstash.crt"
    ssl_key => "/etc/pki/logstash/logstash.pk8"   # формат PKCS8
    ssl_certificate_authorities => ["/etc/pki/ca/ca.crt"]
    ssl_verify_mode => "force_peer"
  }
}
```

### Logstash: syslog over TLS (tcp input)

```ruby
input {
  tcp {
    port => 5514
    ssl_enabled => true
    ssl_certificate => "/etc/pki/logstash/logstash.crt"
    ssl_key => "/etc/pki/logstash/logstash.pk8"
  }
}
```

> Плагин `syslog` (порт 514) не поддерживает TLS — для шифрованного syslog используйте `tcp` input с `ssl_enabled => true` (конвенциональный порт 5514).

Полные конфигурации этих входов и сценарии приема — в [Logstash: Входы, выходы и маршрутизация](./Logstash/logstash_inputs_outputs.md).

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

### MTU и сжатие

- Jumbo frames (MTU 9000) для CCR/CCS между DC; несовпадение MTU на пути вызывает тихую потерю пакетов и деградацию репликации.
- `transport.tcp.compress: true` — сжатие transport-трафика на WAN-линках (дефолт `false`).
- TCP keep-alives на remote-cluster-соединениях включены по умолчанию.

## Проверка и валидация

```bash
# Порты слушаются
ss -tlnp | grep -E ':(9200|9300)\b'
# → LISTEN 0 128 0.0.0.0:9200 0.0.0.0:* users:(("java",pid=1234,fd=...))
# → LISTEN 0 128 0.0.0.0:9300 0.0.0.0:* users:(("java",pid=1234,fd=...))

# Health check кластера
curl -k -u elastic:$PASS https://localhost:9200/_cluster/health?pretty
# → "status" : "green", "number_of_nodes" : 3

# TLS-сертификат и срок действия
openssl s_client -connect es-node:9200 -servername es-node 2>/dev/null | openssl x509 -noout -dates
# → notAfter=Dec 31 23:59:59 2027 GMT

# Сканирование портов узла
nmap -p 9200,9300,9443 es-node
# → 9200/tcp open  http
# → 9300/tcp open  unknown
# → 9443/tcp open  unknown

# Firewall: firewalld
sudo firewall-cmd --list-all
# → ports: 9200/tcp 9300/tcp

# Firewall: iptables
sudo iptables -L INPUT -n --line-numbers | grep -E '9200|9300'
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

### master not discovered / кластер не формируется

Симптомы: в логах `master not discovered or elected yet`, `failed to join cluster`, кластер `red`/`yellow` с неприсвоенными шардами.

Причина: закрыт порт 9300 между узлами или неверный `discovery.seed_hosts`.

Диагностика:

```bash
# С каждого узла — на каждый (9300 должен быть bidirectional)
nc -zv es-1 9300
nc -zv es-2 9300

# Убедиться, что узел слушает не-loopback интерфейс
ss -tlnp | grep 9300
```

Решение: открыть 9300 bidirectional между всеми узлами кластера; проверить `network.host` и `discovery.seed_hosts`.

### TLS handshake failure

- `ssl handshake exception`, `certificate unknown`, `unable to find valid certification path` — несовпадение CA или имени хоста. Проверьте `verification_mode`/`verificationMode` и SAN сертификата.
- Logstash: `ssl_key` должен быть в формате PKCS8. Конвертация: `openssl pkcs8 -topk8 -inform PEM -outform PEM -nocrypt -in key.pem -out key.pk8`.
- Remote cluster: проверьте, что подключаетесь к правильному порту — 9443 в модели API key, 9300 в сертификатной модели.

### Неожиданный порт (9201 / 9301)

Если дефолтный порт занят, Elasticsearch поднимается на следующем свободном в диапазоне (`http.port` — 9200-9300, `transport.port` — 9300-9400). Проверка: `ss -tlnp | grep java`. Решение: задать `http.port` и `transport.port` явно в `elasticsearch.yml`.

### Syslog TLS не работает

Плагин `syslog` не поддерживает SSL. Для шифрованного syslog используйте `tcp` input с `ssl_enabled => true` (обычно порт 5514).

### High Network Latency

```bash
# Измерение latency
ping elasticsearch
traceroute elasticsearch

# Проверка bandwidth
iperf3 -c elasticsearch

# Мониторинг network stats и TCP-соединений
netstat -s
ss -ti
```

`ss -ti` показывает RTT, retransmits и cwnd на каждом соединении — рост retransmits при нормальном ping указывает на потерю пакетов или несовпадение MTU.

### Connection Refused

1. Проверить, слушает ли процесс порт: `ss -tlnp | grep 9200`
2. Проверить firewall rules
3. Проверить `network.host` в `elasticsearch.yml`
4. Проверить bind address (`0.0.0.0` vs конкретный IP)

## Best Practices и Security Checklist

### Network Security

- [ ] Elasticsearch (9200) не доступен из Internet
- [ ] 9300 открыт только между узлами кластера, bidirectional
- [ ] Все соединения зашифрованы (TLS)
- [ ] Firewall: whitelist по IP/подсетям, default-deny
- [ ] Отдельные firewall-зоны для каждого компонента
- [ ] Monitoring traffic изолирован от production
- [ ] CCR/CCS traffic идет через dedicated network/VPN

### Access Control

- [ ] Kibana доступна только через VPN или internal network
- [ ] API keys вместо паролей для сервисных аккаунтов
- [ ] Rate limiting на API endpoints
- [ ] Audit logging включен
- [ ] Failed login attempts мониторятся

## Edge Cases и ограничения

- **Диапазоны портов по умолчанию.** `http.port` биндится к диапазону 9200-9300, `transport.port` — 9300-9400; при занятом порте узел поднимается на следующем свободном. В production задавайте порты явно.
- **IPv6.** Seed-адреса записываются в квадратных скобках: `[2001:db8::1]:9300`. IPv6 в seed-адресах remote-кластеров поддерживается начиная с Kibana 9.2.
- **`0.0.0.0`.** Автоконфигурация single-node записывает `http.host: 0.0.0.0` — узел доступен по всем интерфейсам сразу после старта; TLS и аутентификация включены по умолчанию, но порт 9200 всё равно нужно закрыть firewall-правилами.
- **Bootstrap checks.** Установка `network.host` в не-loopback значение активирует проверки ОС (память, file descriptors, потоки) — детали в [Cluster Setup](./Tutorials/cluster_setup.md).
- **File descriptors.** Лимит `ulimit -n` (рекомендуется 65535+) ограничивает число одновременных сетевых соединений узла.
- **MTU.** Несовпадение MTU на пути между DC — тихая потеря пакетов; симптомы проявляются только под нагрузкой CCR.
- **Enterprise Search.** Удалён в 9.0; порт 3002 актуален только для 8.x.

## См. также

* **[Elasticsearch: Обзор](Elasticsearch/elasticsearch_overview.md)** — архитектура и безопасность.
* **[Security Advanced](Elasticsearch/elasticsearch_security_advanced.md)** — TLS, RBAC, Audit Logging.
* **[CCR и CCS](Elasticsearch/elasticsearch_ccr_ccs.md)** — remote cluster interface 9443, cross-cluster сеть.
* **[Elastic Agent и Fleet](Elasticsearch/elastic_agent_and_fleet.md)** — порты для агентов (8220).
* **[Beats Family](Elasticsearch/beats_family.md)** — порты для Beats.
* **[Logstash: Обзор](Logstash/logstash_overview.md)** — порты для Logstash.
* **[Kibana: Обзор](Kibana/kibana_overview.md)** — порты для Kibana.
* **[Настройка кластера](Tutorials/cluster_setup.md)** — `network.host`, discovery, bootstrap checks.
