# Сетевая безопасность Prometheus

## Определения

**Сетевая безопасность Prometheus** — совокупность мер по защите компонентов системы мониторинга (Prometheus Server, Alertmanager, Exporters, Pushgateway) на сетевом уровне: ограничение доступа по IP/подсети, сегментация трафика, настройка firewall и NetworkPolicy, контроль портов и протоколов.

В отличие от [безопасности приложения](./security.md) (TLS, Basic Auth, mTLS), сетевая безопасность фокусируется на **доступе к портам** и **маршрутизации трафика** между компонентами.

> **См. также:** [Безопасность Prometheus](./security.md) - TLS и аутентификация; [Установка через APT](./installation/with_apt.md) - пример UFW; [Kubernetes Network Policies](./kubernetes/operator/network_policies.md) - сетевые политики в K8s.

## Основные концепции

### Справочная таблица портов

| Компонент | Порт | Протокол | Назначение | Кому разрешать доступ |
| :--- | :--- | :--- | :--- | :--- |
| **Prometheus Server** | 9090 | TCP | Web UI, HTTP API, federation | Grafana, Alertmanager, вышестоящий Prometheus, администраторы |
| **Prometheus OTLP** | 4317 | TCP (gRPC) | Приём OTLP-данных | Приложения, OTel Collector, sidecar'ы |
| **Prometheus OTLP** | 4318 | TCP (HTTP) | Приём OTLP-данных (HTTP) | Приложения, OTel Collector |
| **Alertmanager** | 9093 | TCP | Web UI, API v2, кластеризация | Prometheus, ad-hoc алерты, администраторы |
| **Alertmanager Cluster** | 9094 | TCP | Gossip (gossip protocol) | Только другие инстансы Alertmanager |
| **Pushgateway** | 9091 | TCP | Push-эндпоинт для метрик | CronJobs, batch-задачи |
| **Node Exporter** | 9100 | TCP | Метрики хоста | Только Prometheus Server |
| **Blackbox Exporter** | 9115 | TCP | Метрики экспортера | Только Prometheus Server |
| **Redis Exporter** | 9121 | TCP | Метрики Redis | Только Prometheus Server |
| **PostgreSQL Exporter** | 9187 | TCP | Метрики PostgreSQL | Только Prometheus Server |
| **MySQL Exporter** | 9104 | TCP | Метрики MySQL | Только Prometheus Server |
| **Kafka Exporter** | 9308 | TCP | Метрики Kafka | Только Prometheus Server |
| **cAdvisor** | 8080 | TCP | Метрики контейнеров | Только Prometheus Server |
| **Grafana** | 3000 | TCP | Дашборды | Пользователи (через reverse proxy) |

### Принцип минимальных привилегий

Каждый компонент Prometheus должен быть доступен только тем системам, которые действительно его используют:

```
Prometheus Server <-- 9090 -- Grafana
Prometheus Server <-- 9090 -- Вышестоящий Prometheus (federation)
Prometheus Server --> 9100 -- Node Exporter (скрейпинг)
Prometheus Server --> 9187 -- PostgreSQL Exporter
Prometheus Server --> 9093 -- Alertmanager (отправка алертов)
Alertmanager <-- 9093 -- Prometheus Server
Alertmanager --> 9094 -- Alertmanager (gossip)
```

### Стратегии сетевой сегментации

| Стратегия | Уровень | Инструменты | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Firewall (host)** | ОС | iptables, nftables, ufw, firewalld | Bare-metal, VM |
| **Network Policy** | Kubernetes | Calico, Cilium, Weave | K8s кластеры |
| **Security Group** | Облако | AWS SG, GCP FW, Azure NSG | Облачные среды |
| **Reverse Proxy** | Приложение | NGINX, HAProxy, Traefik | Дополнительный слой аутентификации |
| **VPN/WireGuard** | Сеть | WireGuard, IPSec | Междатацентровая связность |

## Практические сценарии

### Сценарий 1: iptables/nftables для Bare-metal

**Рекомендуемая конфигурация для сервера Prometheus:**

```bash
# Prometheus Server: разрешить доступ только из доверенных подсетей
iptables -A INPUT -p tcp --dport 9090 -s 10.0.0.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 9090 -j DROP

# Alertmanager: разрешить только от Prometheus
iptables -A INPUT -p tcp --dport 9093 -s 10.0.0.100/32 -j ACCEPT
iptables -A INPUT -p tcp --dport 9093 -j DROP

# Alertmanager cluster: только между peers
iptables -A INPUT -p tcp --dport 9094 -s 10.0.0.100/32 -j ACCEPT
iptables -A INPUT -p tcp --dport 9094 -s 10.0.0.101/32 -j ACCEPT
iptables -A INPUT -p tcp --dport 9094 -j DROP

# Pushgateway: только из подсети cron-хостов
iptables -A INPUT -p tcp --dport 9091 -s 10.0.1.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 9091 -j DROP

# Node Exporter: только от Prometheus
iptables -A INPUT -p tcp --dport 9100 -s 10.0.0.100/32 -j ACCEPT
iptables -A INPUT -p tcp --dport 9100 -j DROP
```

**Сохранение правил:**

```bash
# Debian/Ubuntu
apt install iptables-persistent
netfilter-persistent save

# RHEL/CentOS
service iptables save
```

### Сценарий 2: nftables (современная замена iptables)

```nft
#!/usr/sbin/nft -f
flush ruleset

table inet prometheus {
    chain input {
        type filter hook input priority filter; policy drop;

        # Разрешить established/related
        ct state established,related accept

        # SSH (только из management подсети)
        ip saddr 10.0.0.0/24 tcp dport 22 accept

        # Prometheus UI/API (Grafana + вышестоящий Prometheus)
        ip saddr 10.0.0.0/24 tcp dport 9090 accept

        # OTLP receiver (приложения)
        ip saddr 10.0.0.0/8 tcp dport { 4317, 4318 } accept

        # Alertmanager (только Prometheus)
        ip saddr 10.0.0.100/32 tcp dport 9093 accept

        # Alertmanager cluster (только peers)
        ip saddr { 10.0.0.100/32, 10.0.0.101/32 } tcp dport 9094 accept

        # Pushgateway (cron-хосты)
        ip saddr 10.0.1.0/24 tcp dport 9091 accept

        # Логировать отброшенные
        log prefix "nft-prometheus-drop: " counter drop
    }
}
```

### Сценарий 3: ufw (Ubuntu/Debian - простой вариант)

```bash
# Сброс и начальная настройка
ufw default deny incoming
ufw default allow outgoing

# SSH
ufw allow from 10.0.0.0/24 to any port 22 proto tcp

# Prometheus UI (Grafana)
ufw allow from 10.0.0.0/24 to any port 9090 proto tcp

# OTLP receiver
ufw allow from 10.0.0.0/8 to any port 4317 proto tcp
ufw allow from 10.0.0.0/8 to any port 4318 proto tcp

# Alertmanager (от Prometheus)
ufw allow from 10.0.0.100/32 to any port 9093 proto tcp

# Alertmanager cluster
ufw allow from 10.0.0.100/32 to any port 9094 proto tcp
ufw allow from 10.0.0.101/32 to any port 9094 proto tcp

# Pushgateway
ufw allow from 10.0.1.0/24 to any port 9091 proto tcp

# Включить firewall
ufw enable
ufw status verbose
```

### Сценарий 4: Kubernetes NetworkPolicy

```yaml
# NetworkPolicy для Prometheus Server
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: prometheus-server-network-policy
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Grafana и другие клиенты
    - from:
        - namespaceSelector:
            matchLabels:
              name: monitoring
      ports:
        - port: 9090
          protocol: TCP
    # OTLP receiver от приложений
    - from:
        - namespaceSelector: {}
      ports:
        - port: 4317
          protocol: TCP
        - port: 4318
          protocol: TCP
  egress:
    # Скрейпинг Node Exporter и других экспортеров
    - to:
        - namespaceSelector: {}
      ports:
        - port: 9100
          protocol: TCP
        - port: 9187
          protocol: TCP
        - port: 9121
          protocol: TCP
    # Alertmanager
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - port: 9093
          protocol: TCP
    # DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
        - port: 53
          protocol: TCP
```

```yaml
# NetworkPolicy для Alertmanager
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: alertmanager-network-policy
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: alertmanager
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Только от Prometheus Server
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: prometheus
      ports:
        - port: 9093
          protocol: TCP
    # Gossip между peer'ами
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: alertmanager
      ports:
        - port: 9094
          protocol: TCP
  egress:
    # Вебхуки (Slack, PagerDuty, Email)
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - port: 443
          protocol: TCP
        - port: 587
          protocol: TCP
    # DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - port: 53
          protocol: UDP
```

### Сценарий 5: Reverse Proxy (NGINX) для дополнительной защиты

```nginx
# /etc/nginx/conf.d/prometheus.conf
upstream prometheus_backend {
    server 127.0.0.1:9090;
    keepalive 16;
}

server {
    listen 443 ssl http2;
    server_name prometheus.example.com;

    ssl_certificate /etc/nginx/ssl/prometheus.crt;
    ssl_certificate_key /etc/nginx/ssl/prometheus.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    # Basic Auth
    auth_basic "Prometheus";
    auth_basic_user_file /etc/nginx/.htpasswd;

    # Ограничение по IP (дополнительно к Basic Auth)
    allow 10.0.0.0/24;
    allow 10.0.1.0/24;
    deny all;

    # Ограничение методов
    limit_except GET POST {
        deny all;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=prometheus:10m rate=30r/s;

    location / {
        limit_req zone=prometheus burst=50 nodelay;
        proxy_pass http://prometheus_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Скрытие версии NGINX
        server_tokens off;
    }

    # Ограничение доступа к опасным эндпоинтам
    location ~ ^/-/(reload|shutdown) {
        allow 10.0.0.100/32;  # Только Prometheus master
        deny all;
        proxy_pass http://prometheus_backend;
    }

    location ~ ^/api/v1/admin/ {
        allow 10.0.0.100/32;  # Только admin
        deny all;
        proxy_pass http://prometheus_backend;
    }

    # Отключение /-/config (содержит конфигурацию)
    location = /-/config {
        deny all;
    }
}
```

### Сценарий 6: Сегментация для Federation

При использовании federation (вышестоящий Prometheus опрашивает нижестоящие), необходимо разрешить доступ к `/federate` только master-серверу:

```bash
# На Leaf-сервере: разрешить federation только от Master
iptables -A INPUT -p tcp --dport 9090 -s 10.0.0.200/32 -j ACCEPT
iptables -A INPUT -p tcp --dport 9090 -j DROP
```

```yaml
# В конфигурации Master-Prometheus
scrape_configs:
  - job_name: 'federation'
    honor_labels: true
    metrics_path: '/federate'
    params:
      'match[]':
        - '{job="node_exporter"}'
        - '{job="app"}'
    static_configs:
      - targets:
          - 'leaf-dc1:9090'
          - 'leaf-dc2:9090'
    # Federation использует свой scrape_interval
    scrape_interval: 60s
```

### Сценарий 7: WireGuard для междатацентровой связи

Для federation или remote_write между дата-центрами:

```ini
# /etc/wireguard/wg0.conf (на каждом конце)
[Interface]
PrivateKey = <private_key>
Address = 10.100.0.1/24
ListenPort = 51820

[Peer]
PublicKey = <remote_public_key>
AllowedIPs = 10.100.0.2/32
Endpoint = remote-dc.example.com:51820
PersistentKeepalive = 25
```

```bash
# Prometheus конфигурация для federation через WireGuard
# Leaf-сервер слушает на WireGuard-интерфейсе
prometheus \
  --web.listen-address=10.100.0.1:9090
```

### Сценарий 8: Мониторинг сетевой доступности

```yaml
# Blackbox Exporter для проверки доступности компонентов Prometheus
scrape_configs:
  - job_name: 'blackbox-http'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - http://prometheus:9090/-/healthy
          - http://alertmanager:9093/-/healthy
          - http://pushgateway:9091/-/healthy
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115

  - job_name: 'blackbox-tcp'
    metrics_path: /probe
    params:
      module: [tcp_connect]
    static_configs:
      - targets:
          - node-exporter:9100
          - postgres-exporter:9187
          - redis-exporter:9121
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115
```

```promql
# Алерт на недоступность компонентов
- alert: ComponentDown
  expr: probe_success{job="blackbox-http"} == 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "Компонент Prometheus недоступен: {{ $labels.instance }}"
```

## Дополнительная информация

### Чеклист сетевой безопасности

- [ ] Prometheus Server слушает только на 127.0.0.1:9090 (через `--web.listen-address`)
- [ ] Alertmanager слушает только на localhost (через `--web.listen-address`)
- [ ] Файлы конфигурации и TLS-сертификаты доступны только пользователю `prometheus`
- [ ] Firewall блокирует доступ к порту 9090 извне (разрешены только доверенные подсети)
- [ ] Exporters доступны только Prometheus Server (не напрямую извне)
- [ ] OTLP receiver защищен mTLS (в production)
- [ ] Gossip-порт Alertmanager (9094) доступен только между peers
- [ ] Reverse proxy добавляет Basic Auth + Rate Limiting
- [ ] Доступ к `/-/reload` и `/-/config` ограничен
- [ ] Регулярный аудит firewall-правил (квартально)

### Диагностика сетевых проблем

```bash
# Проверка доступности порта
ss -tlnp | grep 9090

# Проверка firewall-правил
iptables -L -n -v | grep 9090
nft list ruleset | grep 9090
ufw status | grep 9090

# Проверка TCP-соединения
nc -zv prometheus-server 9090
telnet prometheus-server 9090

# Проверка DNS
nslookup prometheus.example.com
dig prometheus.example.com

# Проверка маршрутизации
traceroute prometheus-server
mtr prometheus-server

# Проверка TLS-соединения
openssl s_client -connect prometheus:9090 -CAfile ca.crt

# Проверка HTTP-ответа
curl -v http://prometheus:9090/-/healthy

# Логи firewall (nflog для nftables)
nft monitor trace
```

### Типичные ошибки и решения

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Connection refused` | Firewall блокирует порт | Добавить правило: `iptables -A INPUT -p tcp --dport 9090 -s <ip> -j ACCEPT` |
| `No route to host` | Маршрутизация не настроена | Проверить `ip route`, добавить маршрут если нужно |
| `Connection timed out` | Порт открыт, но сервис не отвечает | Проверить, слушает ли Prometheus на `0.0.0.0:9090` |
| `SSL handshake failure` | TLS-сертификат не совпадает | Проверить CN/SAN в сертификате |
| `403 Forbidden` | Basic Auth или IP-ограничение | Проверить `.htpasswd` и firewall-правила |
| Federation не работает | `/federate` не разрешен | Добавить firewall-правило для master-сервера |
| Alertmanager не получает алерты | 9093 заблокирован | Проверить доступность порта 9093 |

### Лучшие практики

1. **Defense in Depth:** Используйте firewall + Basic Auth + TLS (не заменяйте одно другим)
2. **Сегментация:** Каждый компонент в отдельной подсети с минимальными правилами
3. **Логирование:** Включите логирование отброшенных пакетов для аудита
4. **Мониторинг:** Настройте Blackbox Exporter для проверки доступности всех компонентов
5. **Аудит:** Регулярно проверяйте firewall-правила на актуальность
6. **Документация:** Ведите реестр портов и правил доступа

### См. также

*   [Безопасность Prometheus](./security.md) - TLS, Basic Auth, mTLS
*   [Установка через APT](./installation/with_apt.md) - пример UFW для Prometheus
*   [Kubernetes Network Policies](./kubernetes/operator/network_policies.md) - сетевые политики в K8s
*   [Blackbox Exporter](./Exporters/blackbox/blackbox_exporter_overview.md) - мониторинг доступности
*   [Federation](./scaling/federation.md) - иерархическая агрегация
*   [Alertmanager](./alertmanager.md) - настройка кластеризации