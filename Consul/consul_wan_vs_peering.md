# WAN Federation против Cluster Peering

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

## Определения

**WAN Federation** — механизм объединения нескольких дата-центров (DC) Consul в единую федерацию через WAN-канал. Существует две разновидности: Traditional WAN Federation (прямое соединение серверов через gossip порт 8302/UDP) и WAN Federation Via Mesh Gateways (с Consul 1.8.0). Secondary ДЦ подключаются к primary ДЦ. Все серверы federated-кластера образуют единый Raft-лог, а данные ACL и KV реплицируются автоматически.

**Cluster Peering** — современный механизм связи независимых кластеров Consul без общей корневой CA и единого Raft-лога. Включен по умолчанию начиная с Consul 1.14. Кластеры остаются полностью независимыми, обмениваются трафиком через Mesh Gateways и явно экспортируют сервисы через `exported-services` config entries.

**Mesh Gateway** — специализированный Envoy-прокси, регистрируемый в каталоге Consul, который маршрутизирует и шифрует межкластерный трафик Service Mesh. Для WAN Federation via Mesh Gateways регистрируется с метаданными `{"consul-wan-federation":"1"}`; для Cluster Peering работает в режимах `local` или `remote`.

**Primary Datacenter** — authoritative дата-центр в WAN Federation, ответственный за создание корневого CA, репликацию ACL и глобальное состояние. Все secondary ДЦ ссылаются на `primary_datacenter` в конфигурации.

**Exported Services** — config entry типа `exported-services`, определяющая сервисы, которые кластер делает доступными для peer-кластеров. Consul использует эти записи для рекламы сервисов и поддержки Service Mesh соединений между кластерами.

**Sameness Groups** — Enterprise-механизм группировки partitions и cluster peers в единую логическую группу с идентичным набором сервисов для упрощения cross-DC/peer failover.

**Gossip Protocol** — протокол обнаружения и распространения членства в кластере. В WAN Federation серверы образуют единый WAN gossip pool (порт 8302/UDP с fallback на TCP); в Cluster Peering каждый кластер сохраняет собственный LAN gossip pool, а серверы не участвуют в cross-cluster gossip.

## Основные концепции

### Архитектурные различия

```
WAN Federation (Traditional):          WAN Federation via Mesh Gateways:     Cluster Peering:

┌──────────────┐ WAN    ┌──────────────┐    ┌──────────────┐ WAN    ┌──────────────┐    ┌──────────────┐ Peering    ┌──────────────┐
│  DC1 (Primary)│◄──────►│  DC2 (Secondary)│    │  DC1 (Primary)│◄──────►│  DC2 (Secondary)│    │  Cluster A   │◄──────────►│  Cluster B   │
│               │8302/UDP│               │    │               │ Mesh  │               │    │              │  Mesh GW   │              │
│ ┌───────────┐ │        │ ┌───────────┐ │    │ ┌──────────┐  │ GW    │ ┌──────────┐  │    │ ┌──────────┐ │            │ ┌──────────┐ │
│ │ Servers   │ │        │ │ Servers   │ │    │ │ Servers  │  │       │ │ Servers  │  │    │ │ Servers  │ │            │ │ Servers  │ │
│ │ Raft log  │ │        │ │ Raft log  │ │    │ │ Raft log │  │       │ │ Raft log │  │    │ │ Raft log │ │            │ │ Raft log │ │
│ │ (shared)  │ │        │ │ (shared)  │ │    │ │ (shared) │  │       │ │ (shared) │  │    │ │ (独立)    │ │            │ │ (独立)    │ │
│ └───────────┘ │        │ └───────────┘ │    │ └──────────┘  │       │ └──────────┘  │    │ └──────────┘ │            │ └──────────┘ │
└──────────────┘        └──────────────┘    └──────────────┘       └──────────────┘    └──────────────┘            └──────────────┘
        ↓                       ↓                        ↓                       ↓                        ↓                       ↓
    Единый Raft          Репликация через            Серверы не exposed,       Mesh GW шифрует          Полностью независимые     Обмен через
    лог для всех DC      WAN между primary/           traffic идет через         mTLS end-to-end           кластеры. Никакой         Mesh Gateways
                         secondary                    Mesh GW                   (WAN federation)          общей репликации          (peering)
                                                                                                               ↓                       ↓
                                                                                                          Репликация            mTLS terminated
                                                                                                          exported services      на GW, анализируется
                                                                                                          через Raft локально    HTTP для routing
```

### Сравнительная таблица

| Критерий | WAN Federation (Traditional) | WAN Federation via Mesh Gateways | Cluster Peering |
| :--- | :--- | :--- | :--- |
| **Архитектура** | Единый логический кластер с shared Raft | Единый логический кластер с shared Raft | Независимые кластеры |
| **Версия Consul** | Все версии | 1.8.0+ | 1.14.1+ |
| **Репликация данных** | Автоматическая (ACL, KV, intentions, config entries) | Автоматическая (ACL, KV, intentions, config entries) | Только exported services и intentions |
| **Primary DC** | Требуется | Требуется | Не требуется |
| **CA-инфраструктура** | Общая корневая CA для всех ДЦ | Общая корневая CA для всех ДЦ | Отдельная CA для каждого кластера |
| **Изоляция отказов** | Отказ secondary ДЦ влияет на primary | Отказ secondary ДЦ влияет на primary | Полная изоляция; отказ одного кластера не влияет на другой |
| **Безопасность** | Одна плоскость атаки | Одна плоскость атаки, но серверы не exposed | Минимальная плоскость атаки; кластеры изолированы |
| **Серверы в WAN** | Все Consul servers должны быть reachable по WAN | Только Mesh Gateways exposed; серверы остаются в private subnet | Серверы не участвуют в cross-cluster gossip |
| **Масштабирование** | Ограничено Raft-кворумом (~7 серверов на ДЦ) | Ограничено Raft-кворумом (~7 серверов на ДЦ) | Каждый кластер масштабируется независимо |
| **Операционная сложность** | Высокая (expose servers, firewall rules) | Средняя (expose только Mesh GW) | Средняя (несколько независимых кластеров, peering tokens) |
| **Совместимость версий** | Требует одинаковых версий Consul между ДЦ | Требует одинаковых версий Consul между ДЦ | Разные версии между кластерами допустимы |
| **Mesh Gateways** | Не требуются для Traditional; требуются для via Mesh GW variant | Требуются для federation | Требуются для межкластерного trafic |
| **Наблюдаемость** | Единый источник метрик | Единый источник метрик | Раздельные источники; требуется корреляция |
| **mTLS на Mesh GW** | mTLS сохраняется end-to-end | mTLS сохраняется end-to-end | mTLS terminated на GW для анализа HTTP routing |
| **Multi-tenancy** | Нет (все ДЦ управляются единой командой) | Нет | Да (разные operators могут управлять разными кластерами) |

### Детальный разбор механизмов

#### WAN Federation (Traditional)

1. **Primary/secondary модель:** Один ДЦ назначается authoritative через `primary_datacenter`. Secondary ДЦ подключаются к primary через gossip (порт 8302/UDP с fallback на TCP).
2. **Репликация:** Все критичные данные (KV, ACL, intentions, config entries) реплицируются через Raft между primary и secondary.
3. **Единый Raft-лог:** Все серверы всех ДЦ участвуют в одном логическом Raft-логе. Лидер может находиться в любом ДЦ.
4. **Сетевая топология:** Все Consul servers должны иметь routable адреса между ДЦ. Обычно требуется VPN или выделенный WAN-канал.
5. **Failover:** При отказе secondary ДЦ сервисы автоматически доступны через primary.

**Проблемы:**
- Единая точка отказа: compromise primary = compromise всех
- Ограничение на количество серверов: Raft не масштабируется бесконечно (~7 voters)
- Сложность с разными версиями Consul между ДЦ
- Сетевая сложность: требуется routable адрес для каждого сервера

#### WAN Federation Via Mesh Gateways (1.8.0+)

1. **Topology:** Только Mesh Gateways exposed на WAN. Consul servers остаются в private subnet.
2. **Initial join:** Secondary servers делают первоначальный вызов к primary Mesh Gateways.
3. **Ongoing traffic:** После первоначального join, вся WAN-коммуникация идет через Mesh Gateways. Все GW across DCs должны быть routable между собой.
4. **Federation secret:** В Kubernetes автоматически создается secret с CA сертификатом, replication токеном, gossip ключом и server config.
5. **mTLS:** Трафик между Mesh Gateways остается зашифрованным end-to-end.

**Преимущества над Traditional:**
- Серверы не exposed на WAN
- Единый Load Balancer в Kubernetes для Mesh GW pods
- Поддержка overlapping pod IP spaces между кластерами

#### Cluster Peering (1.14.1+)

1. **Peer-связь:** Два кластера обмениваются peering-токенами и устанавливают соединение. Peering tokens подписываются CA issuing сертификатом кластера.
2. **Exported services:** Кластер явно экспортирует сервисы через `exported-services` config entry. UI не поддерживает создание exported services — только CLI/HTTP API.
3. **Mesh Gateways:** Для production рекомендуются Mesh Gateways в режимах `local` или `remote` (по умолчанию `remote`). Режим `none` невалиден для peering.
4. **Изоляция:** Кластеры не реплицируют ACL, KV, intentions или глобальное состояние. Каждый кластер управляется independently.
5. **Versions:** Разные версии Consul между кластерами допустимы, но функциональность зависит от intersection возможностей.

**Ограничения:**
- Exported services ограничены 8MB на запись (approx 1000 service instances)
- Два admin partition в одном ДЦ не могут быть peered — используйте `exported-services` вместо этого
- UI не поддерживает peered services intentions — только локальные

### Производительность

| Метрика | WAN Federation (Traditional) | WAN Federation via Mesh GW | Cluster Peering |
| :--- | :--- | :--- | :--- |
| **Задержка меж-DC запросов** | Низкая (прямой gossip/RPC) | Средняя (через Mesh GW) | Средняя (через Mesh GW) |
| **Пропускная способность** | Высокая (прямая репликация Raft) | Средняя (Mesh GW bottleneck) | Зависит от Mesh Gateway capacity |
| **Нагрузка на Control Plane** | Высокая (все серверы участвуют в Raft) | Высокая (все серверы участвуют в Raft) | Низкая (каждый кластер автономен) |
| **Encryption overhead** | Минимальный (server-to-server mTLS) | mTLS end-to-end через Mesh GW | mTLS terminated/ re-encrypted на GW |

## Практические сценарии

### Сценарий 1: WAN Federation (Traditional) — VM/ Bare Metal

#### Настройка Primary DC

```hcl
# /etc/consul.d/server.hcl на серверах primary DC
datacenter = "dc1"
primary_datacenter = "dc1"
server = true
bootstrap_expect = 3

encrypt = "YOUR_GOSSIP_ENCRYPTION_KEY" # consul keygen

retry_join = ["10.0.1.10", "10.0.1.11", "10.0.1.12"]

# Если ACL включены
acl {
  enabled = true
  default_policy = "deny"
}

# Если TLS включены
ports {
  https = 8501
}
```

#### Настройка Secondary DC

```hcl
# /etc/consul.d/server.hcl на серверах secondary DC
datacenter = "dc2"
primary_datacenter = "dc1"
server = true
bootstrap_expect = 3

encrypt = "SAME_KEY_AS_PRIMARY"  # должен совпадать с primary DC

retry_join = ["10.0.2.10", "10.0.2.11", "10.0.2.12"]
retry_join_wan = ["10.0.1.10", "10.0.1.11", "10.0.1.12"]  # primary servers

# ACL replication token (если ACL включены)
acl {
  enabled = true
  default_policy = "deny"
}
```

#### Валидация

```bash
# Проверка WAN gossip pool
consul members -wan
# → Server members из всех ДЦ в статусе alive

# Проверка репликации KV из secondary
consul kv get config/app/db_url -datacenter=dc2
# → значение совпадает с dc1

# Проверка ACL replication на secondary
curl http://secondary-server:8500/v1/acl/replication
# → {"Enabled": true, "SyncTime": "..."}

# Проверка forwarding на primary
curl http://primary-server:8500/v1/catalog/services?dc=dc2
# → список сервисов из dc2
```

### Сценарий 2: WAN Federation Via Mesh Gateways

#### Настройка Primary DC

```hcl
# /etc/consul.d/server.hcl на primary DC
primary_datacenter = "dc1"
datacenter = "dc1"
server = true
bootstrap_expect = 3

connect {
  enabled = true
  enable_mesh_gateway_wan_federation = true
}

# Если TLS включены
tls {
  defaults {
    ca_file = "/etc/consul.d/certs/consul-agent-ca.pem"
    cert_file = "/etc/consul.d/certs/server.pem"
    key_file = "/etc/consul.d/certs/server-key.pem"
    verify_incoming = true
    verify_outgoing = true
  }
}
```

Mesh Gateway registration на primary:

```hcl
# /etc/consul.d/mesh-gateway.hcl
kind = "mesh-gateway"
name = "gateway"
# expose servers для WAN federation
# consul connect envoy -expose-servers добавляет consul-wan-federation=1
proxy {
  address = "10.0.1.50"
  port = 8443
}
```

#### Настройка Secondary DC

```hcl
# /etc/consul.d/server.hcl на secondary DC
primary_datacenter = "dc1"
datacenter = "dc2"
server = true
bootstrap_expect = 3

connect {
  enabled = true
  enable_mesh_gateway_wan_federation = true
}

# Адреса primary mesh gateways (fallback для reconnect)
primary_gateways = ["10.0.1.50:8443"]

# retry_join_wan НЕ требуется для mesh gateway federation
# retry_join_wan = []  # должно быть опущено
```

#### Валидация

```bash
# Проверка membership через WAN
consul members -wan
# → серверы всех ДЦ alive

# ПроверкаMesh Gateway registration
consul catalog services -datacenter=dc1
# → gateway присутствует

# Проверка server exposure через GW
curl http://10.0.1.50:8500/v1/catalog/services
# → сервисы primary DC

# Проверка service discovery cross-DC
consul catalog services -datacenter=dc2
# → сервисы primary DC видны
```

### Сценарий 3: Cluster Peering (VM)

#### Создание peering на Cluster A

```bash
# Генерация peering токена
consul peering generate-token -peer=cluster-b
# → eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Сохраните токен для передачи в Cluster B
```

#### Установка peering на Cluster B

```bash
# Использование токена для установления peering
consul peering establish -peering-token="eyJhbGci..." -peer=cluster-a
# → Peering established successfully
```

#### Настройка Mesh Gateways для Peering

```hcl
# /etc/consul.d/mesh.hcl на каждом кластере
kind = "mesh-gateway"
name = "gateway"
instances {
  proxy {
    address = "10.0.1.20"
    port = 8443
  }
}

# Включение peering через mesh gateways
# Mesh config entry:
kind = "mesh"
name = "global"
peeringThroughMeshGateways = true
```

#### Экспорт сервисов

```hcl
# /etc/consul.d/exported-services.hcl
kind = "exported-services"
name = "default"  # или namespace name

services = [
  {
    name = "billing-api"
    namespace = "default"
    consumers = [
      {
        peer = "cluster-b"
      }
    ]
  }
]
```

```bash
# Применение конфигурации
consul config write exported-services.hcl
```

#### Создание Intentions

```bash
# Разрешение трафика от cluster-b к billing-api
consul intention create -peer cluster-b web-service billing-api
# → Created intention: web-service => billing-api

# Проверка intentions
consul intention match -peer cluster-b web-service billing-api
# → Allowed
```

#### Валидация

```bash
# Статус peering
consul peering list
# → Peerings: [cluster-a (active), cluster-b (active)]

# Exported services через peer
consul catalog services -peer=cluster-b
# → billing-api, user-service, ...

# Проверка sync статуса
consul peering read -peer cluster-b
# → LastSyncTime, PeerThroughMeshGateways, Status

# Проверка health через peer
curl http://cluster-a-server:8500/v1/health/service/billing-api?peer=cluster-b
# → passing instances
```

### Сценарий 4: Cluster Peering (Kubernetes)

#### Helm values для Cluster A

```yaml
# values-cluster-a.yaml
global:
  name: consul
  datacenter: cluster-a
  tls:
    enabled: true
  acls:
    manageSystemACLs: true

meshGateway:
  enabled: true
  # Создаст LoadBalancer service для mesh gateway

peering:
  enabled: true
```

#### Helm values для Cluster B

```yaml
# values-cluster-b.yaml
global:
  name: consul
  datacenter: cluster-b
  tls:
    enabled: true
  acls:
    manageSystemACLs: true

meshGateway:
  enabled: true

peering:
  enabled: true
```

#### Установка

```bash
# Cluster A
helm upgrade --install consul hashicorp/consul -f values-cluster-a.yaml -n consul --create-namespace

# Получение peering токена
kubectl exec -n consul consul-server-0 -- consul peering generate-token -peer=cluster-b
# → TOKEN

# Cluster B
helm upgrade --install consul hashicorp/consul -f values-cluster-b.yaml -n consul --create-namespace

# Установка peering токена
kubectl exec -n consul consul-server-0 -- consul peering establish -peering-token="TOKEN" -peer=cluster-a
```

#### Настройка Mesh Gateway mode (Kubernetes)

```yaml
# ProxyDefaults CRD на Cluster A
apiVersion: consul.hashicorp.com/v1alpha1
kind: ProxyDefaults
metadata:
  name: global
  namespace: consul
spec:
  meshGateway:
    mode: local  # или remote (default)
```

#### Валидация

```bash
# Проверка peering статуса через K8s API
kubectl exec -n consul consul-server-0 -- consul peering list

# Проверка exported services через CRD
kubectl get exportedservices -n consul

# Проверка intentions
kubectl exec -n consul consul-server-0 -- consul intention list
```

### Сценарий 5: Миграция WAN Federation → Cluster Peering

#### Этап 1: Подготовка

```bash
# 1. Инвентаризация сервисов в WAN Federation
consul catalog services -datacenter=dc1 > dc1-services.txt
consul catalog services -datacenter=dc2 > dc2-services.txt

# 2. Проверка intentions
consul intention list -datacenter=dc1 > dc1-intentions.txt

# 3. Создание снапшота
consul snapshot save /tmp/pre-migration-$(date +%Y%m%d).snap
```

#### Этап 2: Развертывание Cluster Peering параллельно

```bash
# Не отключайте WAN Federation до завершения тестирования peering!

# 1. Включите Cluster Peering на обоих кластерах
# (включен по умолчанию в 1.14+, можно явно установить peering.enabled=true)

# 2. Создайте peering connection
# Cluster A:
consul peering generate-token -peer=cluster-b

# Cluster B:
consul peering establish -peering-token=<TOKEN> -peer=cluster-a

# 3. Настройте Mesh Gateways для peering traffic
# (отдельные от WAN Mesh Gateways, если используются)

# 4. Экспортируйте критические сервисы
```

#### Этап 3: Валидация и cutover

```bash
# 1. Проверка peered services доступности
curl http://cluster-b-service:8500/v1/health/service/billing-api?peer=cluster-a

# 2. Тестирование intentions
consul intention match -peer cluster-a web-service billing-api

# 3. Мониторинг в течение 24-48 часов
watch -n 10 'consul peering list'

# 4. После успешного тестирования — отключение WAN Federation
# На secondary DC:
consul leave
# Удалите retry_join_wan из конфигурации
# Запустите агент
```

#### Этап 4: Cleanup

```bash
# 1. Удалите WAN Federation конфигурацию
# 2. Обновите документацию и runbooks
# 3. Архивируйте снапшоты pre-migration
```

## Операции и команды

### Валидация состояния WAN Federation

```bash
# 1. WAN gossip pool
consul members -wan
# → все серверы из всех ДЦ alive

# 2. Рaft peers
consul operator raft list-peers
# → все серверы healthy, один leader

# 3. ACL replication (secondary DC)
curl http://secondary:8500/v1/acl/replication
# → {"Enabled": true, "SyncTime": "2024-01-15T10:30:00Z"}

# 4. KV cross-DC
consul kv get config/app/db_url -datacenter=dc2
# → значение присутствует

# 5. Service discovery cross-DC
consul catalog services -datacenter=dc2
# → полный список сервисов присутствует

# 6. Intentions cross-DC
consul intention list -datacenter=dc1
# → все intentions реплицированы

# 7. Логи на secondary
consul monitor -log-level=info
# → нет ошибок federation

# 8. Raft logs lag
consul info | grep "raft\.last_log_index"
# → приближается к leader на всех серверах
```

### Валидация состояния Cluster Peering

```bash
# 1. Peering status
consul peering list
# → Peerings: [cluster-a (active)]

# 2. Peering details
consul peering read -peer cluster-a
# → LastSyncTime, PeerThroughMeshGateways, Status: "active"

# 3. Exported services
consul catalog services -peer=cluster-a
# → список экспортированных сервисов

# 4. Service health через peer
curl http://localhost:8500/v1/health/service/billing-api?peer=cluster-a
# → passing instances

# 5. Intentions для peered services
consul intention list
# → intentions разрешающие трафик к exported services

# 6. Mesh Gateway status
consul catalog services | grep mesh-gateway
# → gateway сервисы присутствуют

# 7. Peering sync errors
consul monitor -log-level=warn | grep -i peering
# → нет ошибок

# 8. ACL для peered services
# Убедитесь, что sidecar proxies имеют токены с правами на чтение imported services
consul acl token read -token=<SIDECAR_TOKEN>
# → policies включают service:read для peered services
```

### Диагностика сети

```bash
# Проверка gossip портов
nc -zv <server-ip> 8302
# → connection succeeded (UDP)

# Проверка WAN connectivity между серверами
# На primary:
nc -zv secondary-server-ip 8302

# Проверка Mesh Gateway connectivity
curl -k https://mesh-gateway-ip:8443/v1/connect/ca/roots
# → корневой CA сертификат

# Проверка TLS handshake между Mesh GW
openssl s_client -connect mesh-gw-a:8443 -servername mesh-gw-a
# → сертификат валиден
```

## Устранение неполадок

### WAN Federation: servers не видят secondary ДЦ

- **Причина:** `encrypt` ключ различается между ДЦ.
  - **Решение:** Убедитесь, что `encrypt` идентичен на всех серверах всех ДЦ.
- **Причина:** Порт 8302/UDP заблокирован firewall.
  - **Решение:** Откройте 8302/UDP (и 8302/TCP fallback) между всеми серверами.
- **Причина:** `retry_join_wan` не настроен на secondary.
  - **Решение:** Добавьте адреса primary серверов в `retry_join_wan`.

### WAN Federation: ACL replication не работает на secondary

- **Причина:** `primary_datacenter` не установлен или неверен.
  - **Решение:** Убедитесь, что `primary_datacenter = "dc1"` на всех secondary серверах.
- **Причина:** Replication токен не настроен.
  - **Решение:** Создайте replication токен на primary и укажите на secondary.
- **Причина:** Secondary не может достичь primary API (Kubernetes federation).
  - **Решение:** Укажите `k8sAuthMethodHost` для secondary кластера.

### WAN Federation: серверы видят друг друга, но RPC forwarding не работает

- **Причина:** `bind_addr` настроен на private address, недоступный из других ДЦ.
  - **Решение:** Установите `bind_addr` на адрес, routable через WAN, или настройте `advertise_addr_wan`.
- **Причина:** `translate_wan_addrs` некорректно настроен.
  - **Решение:** Проверьте конфигурацию `translate_wan_addrs` для address rewriting.

### WAN Federation via Mesh GW: secondary не подключается после restart primary GW

- **Причина:** Primary Mesh GW был decommissioned до распространения новых адресов.
  - **Решение:** Не удаляйте старые primary GW IPs до подтверждения, что secondary получили новые адреса. Используйте `primary_gateways` как fallback.

### Cluster Peering: peer не активен (pending/failed)

- **Причина:** Mesh Gateways недоступны или TLS-сертификаты невалидны.
  - **Решение:** Проверьте connectivity до Mesh GW и срок действия сертификатов.
- **Причина:** Peering токен истек или поврежден.
  - **Решение:** Перегенерируйте токен на source кластере.

### Cluster Peering: exported services не видны

- **Причина:** `exported-services` config entry не применен.
  - **Решение:** Проверьте `consul config read -kind exported-services -name default`.
- **Причина:** Intentions не разрешают трафик.
  - **Решение:** Создайте intention: `consul intention create -peer cluster-b web-service billing-api`.
- **Причина:** Mesh Gateway не зарегистрирован в той же admin partition, что и exported services (Enterprise).
  - **Решение:** Зарегистрируйте Mesh GW в той же partition.

### Cluster Peering: service instance >8MB не экспортируется

- **Причина:** Ограничение размера exported service definition (approx 8MB / 1000 instances).
  - **Решение:** Разделите экспорт на несколько service entries или используйте wildcard `*` с фильтрацией на стороне consumer.

## Лучшие практики

- **Выбор топологии:** Для новых развертываний используйте Cluster Peering. WAN Federation считается legacy начиная с Consul 1.14. WAN Federation via Mesh Gateways предпочтительнее Traditional для новых развертываний, если требуется единый Raft-лог.
- **Изоляция:** Cluster Peering предпочтительнее для multi-operator сред, где кластеры принадлежат разным командам или даже организациям.
- **Mesh Gateways:** Размещайте Mesh Gateways в dedicated subnet / DMZ с контролируемым доступом. Для WAN Federation via Mesh GW убедитесь, что все Mesh GW across DCs routable между собой.
- **Версии:** При использовании WAN Federation все ДЦ должны быть на одинаковых версиях Consul. При Cluster Peering версии могут отличаться, но проверяйте compatibility matrix.
- **Migrating from WAN:** Планируйте поэтапную миграцию с WAN Federation на Cluster Peering для новых проектов. Не смешивайте WAN Federation и Cluster Peering между одними и теми же кластерами — это не поддерживается.
- **Primary Gateway upgrade:** При WAN Federation via Mesh GW не decommission old primary GW IPs до подтверждения распространения новых адресов на secondary.
- **ACL consistency:** При WAN Federation ACL должны быть включены на всех ДЦ или отключены на всех. При Cluster Peering ACL управляются independently в каждом кластере.
- **Sameness Groups (Enterprise):** Используйте для cross-cluster failover идентичных сервисов. Упрощают intentions и routing.
- **Версия CLI:** Используйте CLI той же версии, что и целевая версия Consul для peering операций.
- **Наблюдаемость:** Наблюдайте за метриками Mesh GW (задержка, TLS handshake failures, Raft lag). Для WAN Federation мониторьте Raft state всех серверов.

## Граничные случаи

- **WAN Federation и ACL:** Репликация ACL работает автоматически, но требует одинаковых версий Consul между ДЦ. Primary DC всегда показывает replication disabled в `/v1/acl/replication` — это нормально.
- **Cluster Peering и Catalog v2:** Exported services поддерживают Catalog v2 с multi-port services (Consul 1.22+).
- **Mesh Gateway лимиты:** В Consul 2.0 лимит в 8 инстансов шлюза снят; поддерживается горизонтальное масштабирование. Для Cluster Peering через Mesh GW регистрируйте GW в той же partition что и exported services.
- **Смешанные топологии:** Cluster Peering и WAN Federation могут сосуществовать в одном кластере (начиная с Consul 1.14), но не рекомендуется смешивать между одними и теми же парами кластеров.
- **Network segments:** Cluster Peering несовместим с WAN Federation внутри одного кластера для одних и тех же сервисов.
- **Enterprise → OSS при peering:** Enterprise-only features (namespaces, admin partitions, sameness groups) не мигрируют в OSS при переходе на Cluster Peering. Убедитесь, что exported services не зависят от Enterprise features.
- **Peering token expiration:** Peering токены имеют ограниченное время жизни. Если токен истек до использования — перегенерируйте.
- **Cross-DC Service Mesh:** При Consul 1.4.0+ CA federation происходит автоматически при detection что secondary не является primary. Обычно занимает секунды, но может быть короткое окно (секунды) где новые connection attempts в secondary fail при миграции с CE на Enterprise.
- **Large clusters (>5000 узлов) при WAN Federation:** Обновляйте серверы последовательно. Secondary ДЦ обновляются после Primary. Увеличьте `reconnect_timeout` на время upgrade.
- **Kubernetes private subnets при WAN via Mesh GW:** Mesh Gateways могут быть exposed через LoadBalancer в private subnet, если IP/DNS routable между кластерами. Public Load Balancer гарантирует routability.

## Дополнительная информация

- **[Cluster Peering Overview](https://developer.hashicorp.com/consul/docs/east-west/cluster-peering)** — официальная документация, сравнение с WAN Federation.
- **[WAN Federation Overview](https://developer.hashicorp.com/consul/docs/east-west/wan-federation)** — обзор механизмов федерации.
- **[WAN Federation via Mesh Gateways](https://developer.hashicorp.com/consul/docs/east-west/mesh-gateway/enable)** — включение WAN federation через Mesh GW.
- **[Establish Cluster Peering](https://developer.hashicorp.com/consul/docs/east-west/cluster-peering/establish/vm)** — создание peering между VM кластерами.
- **[Cluster Peering on Kubernetes](https://developer.hashicorp.com/consul/docs/east-west/cluster-peering/establish/k8s)** — peering между Kubernetes кластерами.
- **[Exported Services Config Entry](https://developer.hashicorp.com/consul/docs/reference/config-entry/exported-services)** — управление экспортом сервисов.
- **[Mesh Gateway Specifications](https://developer.hashicorp.com/consul/docs/east-west/cluster-peering/tech-specs)** — требования к Mesh Gateways для peering.
- **[Upgrade WAN-federated datacenters](https://developer.hashicorp.com/consul/docs/upgrade/federated)** — upgrade для multi-DC WAN Federation.
- **[Migrating from WAN to Peering](https://developer.hashicorp.com/consul/docs/upgrade-specific/migrate-wan-federation-to-peering)** — гайд по миграции.
- **[Consul Service Mesh](./consul_service_mesh.md)** — Mesh Gateways, intentions, Service Mesh в Consul.
- **[Consul Deployment](./consul-deployment.md)** — развертывание и rolling upgrade.
- **[Consul Upgrade и Migration](./consul_upgrade_migration.md)** — upgrade процедуры, WAN Federation upgrade order.
- **[Consul Enterprise Licensing](./consul_enterprise_licensing.md)** — Sameness Groups, admin partitions, Enterprise features.
- **[Consul Consensus](./consul_consensus.md)** — Raft протокол, кворум, выборы.
- **[Consul CLI Reference](./consul_cli_reference.md)** — справочник CLI команд для peering и federation.
