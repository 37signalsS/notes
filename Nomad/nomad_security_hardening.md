# Nomad — Security Hardening

## Определения

**Security Hardening** — процесс укрепления безопасности Nomad-кластера путём настройки ACL, шифрования, изоляции задач и ограничения привилегий.

**mTLS (Mutual TLS)** — двусторонняя аутентификация через TLS-сертификаты, обеспечивающая шифрование и проверку подлинности между всеми компонентами Nomad (сервер-сервер, сервер-клиент, клиент-задача).

**Audit Logging** — журнал аудита, фиксирующий все API-запросы к Nomad для compliance и forensic-анализа.

**Workload Identity** — механизм OIDC-аутентификации, позволяющий задачам получать JWT-токены для безопасного взаимодействия с Vault и Consul без статических секретов.

## Основные концепции

### Уровни безопасности Nomad

| Уровень | Меры | Минимальный набор |
| :--- | :--- | :--- |
| **Сеть** | Firewall, TLS, bind address | Да |
| **ACL** | Токены, политики, неймспейсы | Да |
| **Шифрование** | TLS для gossip и RPC | Да |
| **Изоляция задач** | Driver security, namespaces | Рекомендуется |
| **Аудит** | Audit logging | Рекомендуется |
| **Sentinel** | Policy as Code | Enterprise |

### Критические порты Nomad

| Порт | Протокол | Назначение | Доступ |
| :--- | :--- | :--- | :--- |
| **4646** | TCP | HTTP API | Клиенты, CI/CD |
| **4647** | TCP | RPC (сервер-клиент) | Только Nomad |
| **4648** | UDP | Gossip (Serf) | Только Nomad |

## Практические сценарии

### Сценарий 1: Настройка TLS

**Генерация сертификатов (consul):**
```bash
# Генерация CA
consul tls ca create

# Генерация серверного сертификата
consul tls cert create -server -dc=dc1

# Генерация клиентского сертификата
consul tls cert create -client -dc=dc1
```

**Конфигурация сервера (server.hcl):**
```hcl
server {
  enabled = true
  bootstrap_expect = 3
}

tls {
  http = true
  rpc  = true

  ca_file   = "/etc/nomad.d/tls/nomad-ca.pem"
  cert_file = "/etc/nomad.d/tls/server-consul-0.pem"
  key_file  = "/etc/nomad.d/tls/server-consul-0-key.pem"

  verify_server_hostname = true
  verify_https_client    = true
}
```

**Конфигурация клиента (client.hcl):**
```hcl
client {
  enabled = true
}

tls {
  http = true
  rpc  = true

  ca_file   = "/etc/nomad.d/tls/nomad-ca.pem"
  cert_file = "/etc/nomad.d/tls/client-consul-0.pem"
  key_file  = "/etc/nomad.d/tls/client-consul-0-key.pem"

  verify_server_hostname = true
}
```

### Сценарий 2: Настройка ACL

**Инициализация ACL (первый сервер):**
```bash
# Создание мастер-токена
nomad acl bootstrap

# Сохранение токена
export NOMAD_TOKEN="<master-token>"
```

**Политика для разработчиков (dev-policy.hcl):**
```hcl
namespace "development" {
  policy       = "write"
  capabilities = ["submit-job", "read-job", "list-jobs", "read-logs"]
}

namespace "staging" {
  policy       = "read"
  capabilities = ["read-job", "list-jobs"]
}
```

**Политика для CI/CD (ci-policy.hcl):**
```hcl
namespace "production" {
  policy       = "write"
  capabilities = ["submit-job", "read-job"]
}

namespace "staging" {
  policy       = "write"
  capabilities = ["submit-job", "read-job", "destroy-job"]
}
```

```bash
# Создание политики
nomad acl policy apply dev-policy dev-policy.hcl

# Создание токена
nomad acl token create -name="dev-token" -policy="dev-policy"
```

### Сценарий 3: Настройка Audit Logging

**Включение аудита (server.hcl):**
```hcl
audit {
  enabled = true

  sinks {
    file {
      enabled    = true
      file_path  = "/var/log/nomad/audit.log"
      max_bytes  = 104857600  # 100 MB
      max_rotations = 10
    }
  }

  # Фильтрация событий
  filter "Namespace" {
    events  = ["Namespace", "Job", "Allocation", "Evaluation"]
    actions = ["create", "update", "delete"]
  }
}
```

**Формат записи аудита:**
```json
{
  "type": "Audit",
  "timestamp": "2026-01-15T10:30:00Z",
  "version": "1.0",
  "node_id": "node1",
  "payload": {
    "type": "HTTP",
    "method": "PUT",
    "path": "/v1/jobs",
    "request": { "JobID": "webapp" }
  }
}
```

### Сценарий 4: Ограничение драйверов задач

**Конфигурация клиента (client.hcl):**
```hcl
client {
  # Разрешённые драйверы
  allowed_drivers = ["docker", "exec", "exec2"]

  # Запрещённые драйверы
  # raw_exec требует осторожного применения
}

# Для Exec2 — настройка sandbox
plugin "exec2" {
  config {
    allow_disk = false
    allow_network = false
  }
}
```

**Sentinel-политика (Enterprise):**
```sentinel
import "nomad"

main = rule {
    all_tasks_use_safe_drivers
}

all_tasks_use_safe_drivers = rule {
    all nomad.job.task_groups as tg {
        all tg.tasks as task {
            task.driver in ["docker", "exec", "exec2"]
        }
    }
}
```

### Сценарий 5: Workload Identity для Vault

**Конфигурация задачи:**
```hcl
task "server" {
  driver = "docker"

  identity {
    env  = true
    file = true
  }

  vault {
    policies = ["webapp-policy"]
  }

  template {
    data = <<EOH
{{ with secret "kv/data/webapp/config" }}
API_KEY="{{ .Data.data.api_key }}"
{{ end }}
EOH
    destination = "secrets/app.env"
    env         = true
  }
}
```

**Vault-политика (webapp-policy.hcl):**
```hcl
path "kv/data/webapp/config" {
  capabilities = ["read"]
}

path "kv/data/webapp/creds" {
  capabilities = ["read"]
}
```

### Сценарий 6: Network Isolation

**Ограничение сети через Nomad:**
```hcl
network {
  mode = "bridge"

  port "http" { to = 8080 }

  # Запрет исходящего трафика
  dns {
    servers = ["127.0.0.1"]
  }
}
```

**Дополнительная изоляция через iptables:**
```bash
# Блокировка трафика от Nomad задач к внешним IP (кроме DNS)
iptables -I FORWARD -s 172.26.64.0/20 -d 0.0.0.0/0 -j DROP
iptables -I FORWARD -s 172.26.64.0/20 -d 127.0.0.0/8 -j ACCEPT
```

## Чеклист безопасности для продакшена

| Проверка | Команда |
| :--- | :--- |
| TLS включён на всех серверах | `curl -sk https://nomad:4646/v1/status/leader` |
| ACL bootstrap выполнен | `nomad acl token list` |
| Gossip шифруется | `nomad agent -key=<key>` |
| Audit logging включён | `ls /var/log/nomad/audit.log` |
| raw_exec запрещён | Проверка Sentinel-политики |
| Workload Identity настроен | `nomad alloc status <id>` → identity |
| Файловые права на конфиги | `ls -la /etc/nomad.d/` → 640 |

## Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `permission denied` | ACL-токен не имеет прав | Обновите политику токена |
| `TLS handshake failure` | Неверные сертификаты | Проверьте CA, cert, key файлы |
| `gossip key mismatch` | Разные ключи шифрования | Убедитесь, что все агенты используют один ключ |
| `audit log not writing` | Неверный путь или права | Проверьте права на директорию |

## Дополнительная информация

- [Nomad — определения и базовые концепции](./definitions_and_concepts.md) — ACL и Workload Identity.
- [Nomad — Consul Connect](./nomad_consul_connect.md) — mTLS через Connect.
- [Security: Secrets Management](../Security/Concepts/secrets_management_overview.md) — управление секретами.
- [Linux: SSH](../Linux/Security/ssh/) — безопасный доступ к узлам.
