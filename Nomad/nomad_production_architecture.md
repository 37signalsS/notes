# Nomad — Production Reference Architecture

## Определения

**Reference Architecture** — рекомендуемая архитектура развертывания Nomad в production, включающая топологию серверов, требования к оборудованию, сетевую конфигурацию и компоненты экосистемы.

**High Availability (HA)** — конфигурация, при которой кластер продолжает работать при отказе отдельных компонентов (серверов, сетей).

**Kворум** — минимальное количество серверов, необходимое для работоспособности кластера: `(N/2) + 1`, где N — общее количество серверов.

## Основные концепции

### Рекомендуемая топология

```
                    ┌─────────────────────┐
                    │   Load Balancer     │
                    │   (HAProxy/Nginx)   │
                    └─────────┬───────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
       ┌──────┴──────┐ ┌─────┴──────┐ ┌─────┴──────┐
       │ Nomad Server│ │ Nomad Server│ │ Nomad Server│
       │   (Leader)  │ │  (Follower) │ │  (Follower) │
       └──────┬──────┘ └─────┬──────┘ └─────┬──────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
       ┌──────┴──────┐ ┌─────┴──────┐ ┌─────┴──────┐
       │ Nomad Client│ │ Nomad Client│ │ Nomad Client│
       │  (Docker)   │ │  (Docker)   │ │  (Docker)   │
       └─────────────┘ └────────────┘ └────────────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                    ┌─────────┴───────────┐
                    │    Consul Cluster   │
                    │    (Service Disc.)  │
                    └─────────────────────┘
```

### Hardware Requirements

| Компонент | Small (dev/staging) | Medium (production) | Large (high-load) |
| :--- | :--- | :--- | :--- |
| **CPU** | 2 cores | 4-8 cores | 16+ cores |
| **RAM** | 4 GB | 16-32 GB | 64+ GB |
| **Disk** | 50 GB | 100-200 GB SSD/NVMe | 500+ GB NVMe |
| **Network** | 1 Gbps | 10 Gbps | 25+ Gbps |
| **Количество серверов** | 1 | 3 | 5 |
| **Количество клиентов** | 1-3 | 10-100 | 100-10000+ |

### Порты Nomad

| Порт | Протокол | Назначение | Доступ |
| :--- | :--- | :--- | :--- |
| **4646** | TCP | HTTP API | Clients, CI/CD, UI |
| **4647** | TCP | RPC | Server ↔ Client |
| **4648** | UDP | Gossip (Serf) | Server ↔ Server, Server ↔ Client |

### Порты экосистемы

| Порт | Сервис | Назначение |
| :--- | :--- | :--- |
| **8500** | Consul | HTTP API |
| **8301** | Consul | Gossip (Serf) |
| **8600** | Consul | DNS |
| **8200** | Vault | HTTP API |
| **9090** | Prometheus | HTTP API |
| **3000** | Grafana | UI |

## Практические сценарии

### Сценарий 1: Конфигурация сервера (server.hcl)

```hcl
# /etc/nomad.d/server.hcl
datacenter = "dc1"
data_dir   = "/opt/nomad/data"
log_level  = "INFO"

server {
  enabled          = true
  bootstrap_expect = 3
  heartbeat_grace  = "30s"
  min_heartbeat    = "10s"
}

tls {
  http = true
  rpc  = true

  ca_file   = "/etc/nomad.d/tls/nomad-ca.pem"
  cert_file = "/etc/nomad.d/tls/server.pem"
  key_file  = "/etc/nomad.d/tls/server-key.pem"

  verify_server_hostname = true
  verify_https_client    = true
}

acl {
  enabled = true
}

audit {
  enabled = true
  sinks {
    file {
      enabled   = true
      file_path = "/var/log/nomad/audit.log"
    }
  }
}

consul {
  address = "127.0.0.1:8500"
}

vault {
  enabled = true
  address = "http://127.0.0.1:8200"
}

telemetry {
  publish_allocation_metrics = true
  publish_node_metrics       = true
  prometheus_metrics         = true
}
```

### Сценарий 2: Конфигурация клиента (client.hcl)

```hcl
# /etc/nomad.d/client.hcl
datacenter = "dc1"
data_dir   = "/opt/nomad/data"
log_level  = "INFO"

client {
  enabled = true

  reserved {
    cpu            = 500
    memory         = 256
    reserved_ports = "22,80,443"
  }

  host_volume "data" {
    path      = "/opt/nomad/data"
    read_only = false
  }
}

tls {
  http = true
  rpc  = true

  ca_file   = "/etc/nomad.d/tls/nomad-ca.pem"
  cert_file = "/etc/nomad.d/tls/client.pem"
  key_file  = "/etc/nomad.d/tls/client-key.pem"

  verify_server_hostname = true
}

consul {
  address = "127.0.0.1:8500"
}

plugin "docker" {
  config {
    allow_privileged = false
    volumes {
      enabled = true
    }
  }
}

plugin "exec2" {
  config {
    cgroup_root = "/sys/fs/cgroup/nomad"
  }
}
```

### Сценарий 3: HAProxy для API Load Balancing

```haproxy
frontend nomad_api
    bind *:4646 ssl crt /etc/haproxy/certs/nomad.pem
    mode tcp
    option tcplog
    default_backend nomad_servers

backend nomad_servers
    mode tcp
    option httpchk GET /v1/status/leader
    http-check expect string "node-id"

    server nomad1 10.0.1.10:4646 check inter 5s fall 3 rise 2
    server nomad2 10.0.1.11:4646 check inter 5s fall 3 rise 2
    server nomad3 10.0.1.12:4646 check inter 5s fall 3 rise 2
```

### Сценарий 4: Multi-Region Federation

```hcl
# server.hcl (Authoritative Region)
region           = "global"
datacenter       = "dc1"
server           = true
bootstrap_expect = 3

federation {
  enabled = true
}
```

```bash
# Присоединение второго региона
nomad server join -region=us nomad-eu.example.com:4648

# Проверка федерации
nomad federation list
```

### Сценарий 5: Network Security

```bash
# Firewall rules для Nomad сервера
iptables -A INPUT -p tcp --dport 4646 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 4647 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p udp --dport 4648 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 4646 -j DROP
iptables -A INPUT -p tcp --dport 4647 -j DROP
iptables -A INPUT -p udp --dport 4648 -j DROP
```

## Чеклист production-ready

| Компонент | Проверка | Статус |
| :--- | :--- | :--- |
| **TLS** | Включён на серверах и клиентах | |
| **ACL** | Bootstrap выполнен, политики настроены | |
| **Audit** | Логирование включено | |
| **Monitoring** | Prometheus собирает метрики | |
| **Alerting** | Алерты настроены | |
| **Backup** | Raft snapshots по расписанию | |
| **DR** | Процедура восстановления задокументирована | |
| **Серверы** | 3 или 5 серверов (кворум) | |
| **Диск** | SSD/NVMe для серверов | |
| **Сеть** | Firewall настроен | |

## Дополнительная информация

- [Nomad — определения и базовые концепции](./definitions_and_concepts.md) — архитектура.
- [Nomad — Linux OS Tuning](./nomad_linux_os_tuning.md) — настройка узлов.
- [Nomad — Security Hardening](./nomad_security_hardening.md) — настройка безопасности.
- [Nomad — мониторинг](./nomad_monitoring.md) — Prometheus + Grafana.
