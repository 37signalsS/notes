# Consul External Service Monitor (ESM)

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

## Определения

**Consul External Service Monitor (ESM)** — отдельный демон Enterprise-редакции Consul для мониторинга состояния внешних ресурсов, на которых невозможно установить Consul агент (SaaS-сервисы, облачные базы данных, API сторонних провайдеров, сервисы в недоверенных сетях). ESM периодически выполняет проверки (HTTP, TCP, gRPC) и обновляет статусы в каталоге Consul, регистрируя результаты как виртуальные сервисы.

**Внешний узел (external node)** — узел без локального Consul агента, зарегистрированный в каталоге Consul напрямую через API. Отличается наличием метаданных `"external-node": "true"` в `NodeMeta`.

**Direct Mode** — режим работы ESM (начиная с Consul 1.21), при котором ESM подключается напрямую к серверам Consul без локального клиентского агента и gossip-связи.

**Agent Mode** — классический режим работы ESM, при котором он регистрируется в каталоге как клиентский агент и использует gossip для коммуникации.

**Leader election** — механизм выбора активного ESM-инстанса через захват блокировки (lock) в Consul. Только leader выполняет проверки; остальные инстансы находятся в standby и готовы к takeover.

**Batch flushing** — режим буферизации обновлений статусов проверок (`enable_agentless = true`), при котором ESM отправляет изменения пачками через транзакции Consul, снижая количество HTTP-запросов.

**Enterprise requirement** — ESM доступен только в Consul Enterprise. В Community Edition регистрация внешних сервисов через API работает, но автоматический мониторинг через ESM невозможен.

## Основные концепции

### Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                    Consul Cluster                            │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ External      │    │ External      │    │ External      │  │
│  │ Node: RDS     │    │ Node: SaaS    │    │ Node: API     │  │
│  │ (no agent)    │    │ (no agent)    │    │ (no agent)    │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                    │          │
│         ▼                   ▼                    ▼          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Consul ESM (Leader)                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │   │
│  │  │ HTTP Check  │  │ TCP Check   │  │ gRPC Check  │  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  │   │
│  │         │               │                │           │   │
│  │         └───────────────┼────────────────┘           │   │
│  │                         ▼                            │   │
│  │              ┌─────────────────────┐                 │   │
│  │              │  Catalog Update      │                 │   │
│  │              │  (via API / Agent)   │                 │   │
│  │              └─────────────────────┘                 │   │
│  └──────────────────────────────────────────────────────┘   │
│                         │                                   │
│                         ▼                                   │
│              ┌─────────────────────┐                       │
│              │  Consul Servers     │                       │
│              │  (Catalog, KV, ACL) │                       │
│              └─────────────────────┘                       │
└─────────────────────────────────────────────────────────────┘

Standby ESM instances watch for leader failure and automatically acquire lock.
```

### Принцип работы

1. **Регистрация внешнего узла:** Внешний сервис и узел регистрируются в каталоге Consul через HTTP API (`/v1/catalog/register`) или CLI (`consul services register`). В `NodeMeta` обязательно указывается `"external-node": "true"`. Если ESM должен выполнять ICMP-ping узла, добавляется `"external-probe": "true"`.

2. **Запуск ESM:** ESM подключается к Consul, получает лидерство через блокировку и начинает сканировать каталог на внешние узлы. Для каждого обнаруженного внешнего узла ESM выполняет проверки, определенные в `Checks`.

3. **Выполнение проверок:** ESM периодически запускает проверки согласно `Interval` и `Timeout`. Результат (`passing`, `critical`, `warning`) обновляется в каталоге Consul. При `enable_agentless = true` обновления буферизуются и отправляются пачками.

4. **Самодерегистрация:** ESM регистрирует собственную проверку здоровья с `DeregisterCriticalServiceAfter = "30m"`. Если ESM переходит в `critical` (например, потерял связь с Consul), через 30 минут агент попытается автоматически deregister сервис `consul-esm`.

5. **Отказоустойчивость:** При падении leader ESM, standby-инстанс получает блокировку и продолжает выполнение проверок. Переключение происходит автоматически.

### Режимы работы

| Режим | Описание | Требования |
| :--- | :--- | :--- |
| **Agent Mode** | ESM регистрируется как клиентский агент, использует gossip | Consul agent на том же хосте |
| **Direct Mode** | Подключение напрямую к серверам Consul без gossip | Consul 1.21+, сетевой доступ к серверам |

### ACL-требования

ESM требует токен со следующими правами:

| Право | Назначение |
| :--- | :--- |
| `agent:read` | Проверка совместимости версий, расчет network coordinates |
| `key:write` | Запись состояния в KV store (путь настраивается в конфиге) |
| `node:read` | Обнаружение внешних узлов для мониторинга |
| `node:write` | Обновление статусов узлов |
| `service:write` | Регистрация сервиса `consul-esm` в каталоге |
| `session:write` | Получение блокировки лидерства |
| `acl:read` | *(Enterprise-only)* Сканирование namespaces для поиска узлов |

> **Важно:** ESM поддерживает только `default` admin partition.

## Практические сценарии

### 1. Установка ESM

```bash
# Скачивание бинарника (отдельный проект, не входит в consul-enterprise)
curl -o /usr/local/bin/consul-esm https://releases.hashicorp.com/consul-esm/<VERSION>/consul-esm_<VERSION>_linux_amd64.zip
chmod +x /usr/local/bin/consul-esm

# Проверка версии
consul-esm -version
# → consul-esm: version 0.3.2 (or higher)

# Минимальная версия Consul: 1.4.1+
```

### 2. Создание ACL-токена для ESM

```hcl
# esm-policy.hcl — CE
agent "agent1" {
  policy = "read"
}
key_prefix "consul-esm/" {
  policy = "write"
}
node_prefix "" {
  policy = "read"
}
service "consul-esm" {
  policy = "write"
}
session "agent1" {
  policy = "write"
}
node "node1" {
  policy = "write"
}
node "node2" {
  policy = "write"
}
```

```hcl
# esm-policy.hcl — Enterprise
partition "default" {
  agent "agent1" {
    policy = "read"
  }
  key_prefix "consul-esm/" {
    policy = "write"
  }
  node_prefix "" {
    policy = "read"
  }
  service "consul-esm" {
    policy = "write"
  }
  session "agent1" {
    policy = "write"
  }
  node "node1" {
    policy = "write"
  }
  namespace "default" {
    acl = "read"
  }
}
```

```bash
# Создание политики
consul acl policy create \
  -name "esm-policy" \
  -rules @esm-policy.hcl \
  -description "Policy for Consul ESM"

# Создание токена
consul acl token create \
  -description "Token for Consul ESM" \
  -policy-name "esm-policy"
# → SecretID: a7c9e8f2-...
```

### 3. Регистрация внешнего сервиса

```json
{
  "Datacenter": "dc1",
  "Node": "hashicups-db-0-ext",
  "ID": "11111111-2222-3333-4444-555555555555",
  "Address": "10.0.1.50",
  "NodeMeta": {
    "external-node": "true",
    "external-probe": "true"
  },
  "Service": {
    "ID": "hashicups-db-0",
    "Service": "hashicups-db",
    "Tags": ["external", "inst_0"],
    "Address": "10.0.1.50",
    "Port": 5432
  },
  "Checks": [{
    "CheckID": "hashicups-db-0-check",
    "Name": "hashicups-db check",
    "Status": "critical",
    "ServiceID": "hashicups-db-0",
    "Definition": {
      "TCP": "10.0.1.50:5432",
      "Interval": "5s",
      "Timeout": "1s",
      "DeregisterCriticalServiceAfter": "60m"
    }
  }]
}
```

```bash
# Регистрация через CLI
consul services register external-db.hcl

# Или через API
curl --request PUT http://127.0.0.1:8500/v1/catalog/register \
  -H "X-Consul-Token: $CONSUL_HTTP_TOKEN" \
  -d @external-db.json
```

> **Важно:** Устанавливайте `"Status": "critical"` при регистрации. Сервис останется в `critical` до первого успешного прохождения проверки ESM. В production это предотвращает маршрутизацию трафика на нездоровые внешние сервисы.

### 4. Конфигурация ESM

```hcl
# /etc/consul.d/esm.hcl
datacenter = "dc1"

consul {
  address = "127.0.0.1:8500"
  token   = "a7c9e8f2-..."  # ACL-токен ESM
}

# Включение batch flushing для agentless-сред
enable_agentless = true

# Порог обновления статуса (по умолчанию: 1 изменение)
check_update_threshold = 1

# Интервал сброса буфера (по умолчанию: 2s)
check_flush_interval = "2s"

# Определение внешних сервисов
services {
  datacenter = "dc1"

  node {
    id      = "11111111-2222-3333-4444-555555555555"
    node    = "hashicups-db-0-ext"
    address = "10.0.1.50"

    # Обязательные метаданные для обнаружения ESM
    meta {
      "external-node"  = "true"
      "external-probe" = "true"
    }
  }

  service {
    id      = "hashicups-db-0"
    service = "hashicups-db"
    tags    = ["external", "inst_0"]
    address = "10.0.1.50"
    port    = 5432
  }

  checks {
    check_id  = "hashicups-db-0-check"
    name      = "hashicups-db check"
    status    = "critical"
    service_id = "hashicups-db-0"
    definition {
      tcp      = "10.0.1.50:5432"
      interval = "5s"
      timeout  = "1s"
      deregister_critical_service_after = "60m"
    }
  }
}

# Дополнительный сервис: SaaS API
services {
  datacenter = "dc1"

  node {
    id      = "22222222-3333-4444-5555-666666666666"
    node    = "stripe-api-ext"
    address = "api.stripe.com"

    meta {
      "external-node"  = "true"
      "external-probe" = "false"
    }
  }

  service {
    id      = "stripe-api"
    service = "stripe-api"
    tags    = ["saas"]
    address = "api.stripe.com"
    port    = 443
  }

  checks {
    check_id   = "stripe-api-check"
    name       = "Stripe API health"
    status     = "critical"
    service_id = "stripe-api"
    definition {
      http            = "https://api.stripe.com/v1/charges"
      interval        = "30s"
      timeout         = "5s"
      expect_status   = [401]  # Stripe возвращает 401 без auth
      deregister_critical_service_after = "60m"
    }
  }
}
```

```hcl
# /etc/consul.d/esm-direct.hcl — Direct Mode (Consul 1.21+)
# Не требуется локальный Consul agent
datacenter = "dc1"

consul {
  address = "10.0.0.1:8500"  # Прямое подключение к серверам
  token   = "a7c9e8f2-..."
}

enable_agentless = true
```

### 5. Запуск ESM

```bash
# Foreground (для отладки)
consul-esm -config-file=/etc/consul.d/esm.hcl

# Ожидаемый вывод:
# → consul-esm: Connecting to Consul: address=127.0.0.1:8500
# → Consul ESM running!
# → consul-esm: Trying to obtain leadership...
# → consul-esm: Obtained leadership
# → consul-esm: Updating external node list: items=2
```

```bash
# Systemd unit
# /etc/systemd/system/consul-esm.service
[Unit]
Description=Consul External Service Monitor
After=network.target consul.service
Wants=consul.service

[Service]
Type=simple
ExecStart=/usr/local/bin/consul-esm -config-file=/etc/consul.d/esm.hcl
Restart=on-failure
RestartSec=5
LimitNOFILE=65536

# Ограничение на время запуска — ESM должен получить лидерство быстро
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
# Применение
systemctl daemon-reload
systemctl enable --now consul-esm
systemctl status consul-esm
```

### 6. Мониторинг состояния ESM

```bash
# Проверка регистрации внешних сервисов
consul catalog services
# → hashicups-db, stripe-api, ...

# Проверка узлов
consul catalog nodes
# → hashicups-db-0-ext, stripe-api-ext, ...

# Проверка health checks
consul health checks hashicups-db
# → CheckID: hashicups-db-0-check, Status: passing

# Проверка через DNS
dig @127.0.0.1 -p 8600 hashicups-db.service.consul A
# → 10.0.1.50 (если passing)

# Проверка статуса ESM как сервиса
consul health checks consul-esm
# → CheckID: consul-esm, Status: passing
```

## Валидация

### Проверка лидерства ESM

```bash
# Логи ESM
journalctl -u consul-esm -f
# → consul-esm: Obtained leadership
# → consul-esm: Updating external node list: items=2

# Проверка блокировки в KV
consul kv get consul-esm/leader-lock
# → (пусто или ID лидера)

# Проверка сессии
consul kv get consul-esm/leader
# → ID сессии лидера
```

### Проверка ACL-токена

```bash
# Проверка валидности токена
curl -H "X-Consul-Token: a7c9e8f2-..." http://localhost:8500/v1/agent/self
# → {"Config": {...}, "Member": {...}, ...}

# Проверка недостающих прав (должно возвращать 403)
curl -H "X-Consul-Token: a7c9e8f2-..." http://localhost:8500/v1/catalog/nodes
```

### Проверка внешних сервисов

```bash
# Статус сервиса
consul health service hashicups-db
# → Node: hashicups-db-0-ext, Service: hashicups-db, Status: passing

# Проверка узла
consul catalog node hashicups-db-0-ext
# → Node: hashicups-db-0-ext, Address: 10.0.1.50, NodeMeta: {"external-node": "true", ...}

# Проверка метрик (если настроен telemetry)
curl http://localhost:8500/v1/metrics | grep consul_esm
# → consul_esm_leader{} 1
# → consul_esm_checks_passing{} 2
```

## Устранение неполадок

### Внешний сервис остается в состоянии `critical`

- **Причина 1:** ESM не запущен или не получил лидерство.
  ```bash
  journalctl -u consul-esm -f
  # → consul-esm: Unable to obtain leadership (другой инстанс держит lock)
  ```
- **Решение:** Проверьте, что только один ESM является leader. Остановите дублирующиеся инстансы.

- **Причина 2:** Некорректный `NodeMeta` — отсутствует `"external-node": "true"`.
  ```bash
  consul catalog node hashicups-db-0-ext
  # → NodeMeta: {} (пусто)
  ```
- **Решение:** Перерегистрируйте узел с корректными метаданными.

- **Причина 3:** Проверка не проходит (неверный порт, таймаут, сетевой доступ).
  ```bash
  nc -zv 10.0.1.50 5432
  # → Connection refused
  ```
- **Решение:** Исправьте сетевую связность или настройки проверки.

### ESM не может подключиться к Consul

```bash
journalctl -u consul-esm -f
# → [ERROR] check failed: Get "http://10.0.0.1:8500/v1/kv/...": dial tcp: connection refused
```
- **Решение:** Проверьте доступность серверов Consul, корректность адреса в `consul.address`, и валидность ACL-токена.

### ESM теряет лидерство каждые несколько секунд

- **Причина:** Сетевые разрывы или сессия прерывается.
- **Диагностика:**
  ```bash
  consul kv get consul-esm/leader-lock
  # →频繁 изменения
  ```
- **Решение:** Увеличьте `ttl` сессии в конфигурации Consul или стабилизируйте сеть между ESM и серверами.

### Самодерегистрация ESM через 30 минут

- **Причина:** ESM перешел в `critical` (потерял связь с Consul) и истек таймаут `DeregisterCriticalServiceAfter = "30m"`.
- **Диагностика:**
  ```bash
  consul health checks consul-esm
  # → Status: critical
  ```
- **Решение:** Восстановите работу ESM. После перезапуска он автоматически перерегистрируется. Все внешние проверки временно переходят к standby-инстансу или сбрасываются в `critical`.

### Rate limiting внешних API

- **Причина:** Слишком частые проверки внешних HTTP-сервисов.
- **Решение:** Увеличьте `Interval` до минимально допустимого для API. Добавьте exponential backoff в ESM-конфиг или используйте отдельный ESM-инстанс для rate-limited сервисов.

## Лучшие практики

- **Отдельный инстанс ESM:** Запускайте минимум два ESM-инстанса для HA. Второй инстанс автоматически получит лидерство при падении первого.
- **ACL с минимальными правами:** Используйте узкоперечисленные права (`node "node1" { policy = "write" }`) вместо `node_prefix "" { policy = "write" }` в production.
- **Статус `critical` при регистрации:** Всегда регистрируйте внешние сервисы с `"Status": "critical"`. Это предотвращает маршрутизацию трафика до первого успешного health check.
- **Batch flushing:** Включайте `enable_agentless = true` в Direct Mode для снижения нагрузки на API Consul при большом количестве проверок.
- **Мониторинг ESM:** Настройте алерты на статус `consul-esm` сервиса и количество external nodes в `critical`.
- **Direct Mode:** Используйте Direct Mode (Consul 1.21+) для упрощения развертывания — eliminates need for local agent and gossip.
- **Таймауты:** Устанавливайте `timeout = 1/3 * interval` для предотвращения зависаний проверок.
- **DeregisterCriticalServiceAfter:** Устанавливайте на внешних сервисах (`60m` — разумный минимум), чтобы `critical` сервисы автоматически удалялись из каталога при длительных сбоях.
- **Segregation:** Для large-scale развертываний разделяйте ESM-инстансы по группам внешних сервисов (например, один ESM для SaaS, другой для баз данных).

## Граничные случаи

- **Direct Mode (1.21+):** Доступен только в Consul 1.21 и выше. Убедитесь, что все серверы Consul обновлены перед переходом. Требует сетевой доступ к серверам (порты 8300, 8500, 8600).
- **ICMP ping и `external-probe`:** Установка `"external-probe": "true"` заставляет ESM выполнять ping узла для поддержания проверки `externalNodeHealth`. Если провайдер блокирует ICMP, установите `ping_type = "socket"` в конфигурации ESM.
- **macOS:** ESM требует `sudo` для ICMP ping. Используйте `ping_type = "socket"` или запускайте с привилегиями.
- **Self-deregistration:** ESM deregisters сам себя после 30 минут в `critical`. Это поведение неконфигурируемо. При восстановлении ESM необходимо перезапустить его для повторной регистрации.
- **Batch flushing threshold:** `check_update_threshold` определяет минимальное количество изменений для сброса буфера. При `1` каждое изменение flush'ится немедленно. Увеличение threshold снижает API-нагрузку, но добавляет задержку обновления статуса.
- **Enterprise-only `acl:read`:** В Community Edition ESM работает только с `default` namespace. Multi-namespace мониторинг требует Enterprise.
- **Consul ESM и Service Mesh:** ESM регистрирует внешние сервисы в каталоге, но не создает Service Mesh intentions. Для mesh-доступа к внешним сервисам требуется дополнительная конфигурация terminating gateway.
- **Compatibility matrix:**

| ESM версия | Минимальный Consul |
| :--- | :--- |
| 0.3.2+ | 1.4.1+ |
| 0.3.1 и ниже | 1.0.1–1.4.0 |

- **Kubernetes:** Для внешних сервисов в Kubernetes используйте `Registration` CRD вместо прямого API. CRD автоматически вызывает `/catalog/register` при применении.
- **Multi-DC:** ESM может мониторить ресурсы в нескольких дата-центрах, если указан соответствующий `datacenter` в конфигурации каждого сервиса. Каждый DC требует отдельного ESM-инстанса или конфигурационного блока.

## Дополнительная информация

- **[Consul ESM Documentation](https://developer.hashicorp.com/consul/docs/register/external/esm)** — официальная документация.
- **[Consul ESM Tutorial](https://developer.hashicorp.com/consul/tutorials/connect-services/service-registration-external-services)** — пошаговое руководство.
- **[Consul ESM on Kubernetes](https://developer.hashicorp.com/consul/docs/register/external/esm/k8s)** — регистрация внешних сервисов в Kubernetes.
- **[Consul ESM ACL Token](https://developer.hashicorp.com/consul/docs/secure/acl/token/esm)** — создание токена с необходимыми правами.
- **[Consul ESM GitHub](https://github.com/hashicorp/consul-esm)** — исходный код и issue tracker.
- **[Consul Catalog Register API](https://developer.hashicorp.com/consul/api-docs/catalog)** — HTTP API для регистрации сервисов.
- **[Consul ACL Reference](./consul_acl.md)** — ACL policies, токены, permissions.
- **[Consul Health Checks](./consul_health_checks.md)** — типы проверок, thresholds, anti-entropy.
- **[Consul Service Catalog](./consul_service_catalog.md)** — Catalog v2, multi-port, service discovery.
- **[Consul Enterprise Licensing](./consul_enterprise_licensing.md)** — сравнение OSS и Enterprise функций.
- **[Consul Service Mesh](./consul_service_mesh.md)** — intentions, terminating gateway, mesh-доступ к внешним сервисам.
