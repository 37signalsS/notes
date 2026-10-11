# Consul: Enterprise против Open Source

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

## Определения

**Consul Community Edition (CE)** — бесплатная версия с базовым набором функций: service discovery, health checks, KV store, ACL, Service Mesh (Connect) в рамках одного дата-центра и кластерный консенсус Raft.

**Consul Enterprise** — коммерческая версия для крупных организаций, добавляющая multi-tenancy, расширенную изоляцию, governance-механизмы, дополнительные resilience-фичи и уровни поддержки. Существует два тарифа:
- **Standard** — включает service discovery, multi-tenancy, дополнительную отказоустойчивость и масштабируемость.
- **Premium** — включает все Standard-фичи плюс Service Mesh multi-cluster, API gateway, ingress/terminating gateway, locality-aware routing, fault injection.

**Лицензия Enterprise** — файл с расширением `.hclic`, содержащий идентификатор лицензии, customer ID, даты действия и список доступных функций. Начиная с Consul 1.10.0, лицензия должна присутствовать на агентах при старте; временные лицензии (temporary licensing) удалены.

**Модель лицензирования** — Consul Enterprise использует per-cluster модель: каждый кластер серверов требует отдельной лицензии. В Kubernetes среде лицензирование может базироваться на количестве узлов (per-node), где virtual agents не требуют отдельной лицензии.

**Приоритет загрузки лицензии (сервер):**
1. Переменная окружения `CONSUL_LICENSE`
2. Переменная окружения `CONSUL_LICENSE_PATH`
3. Параметр конфигурации `license_path`

**Client agent лицензирование:** клиентские агенты автоматически забирают лицензию с серверов через RPC при старте. Для этого требуется валидный не-anonymous ACL-токен (любые права). Если ACL отключены — лицензия должна быть предоставлена локально через окружение или конфиг. Snapshot agent работает аналогично: забирает лицензию у сервера или клиентского агента, при недоступности в течение 5 минут завершает работу.

**Virtual agent (Kubernetes):** логический узел Consul Dataplane в Kubernetes. Virtual agents не требуют отдельной лицензии; лицензирование базируется на cluster-level entitlement.

**Namespace** — логический изолятор внутри Admin Partition, разделяющий сервисы, политики ACL и KV-ключи между командами или окружениями.

**Admin Partition** — административная граница изоляции внутри дата-центра. Разделы используют общие серверы и Raft-кворум, но имеют полностью независимые каталоги сервисов и пространства имен.

**Sentinel** — Policy as Code механизм Enterprise, позволяющий внедрять контекстные политики на основе времени суток, геолокации, состояния кластера и MFA.

**Redundancy Zone** — механизм распределения серверов по зонам доступности (AZ) с автоматическим повышением non-voter при отказе voter внутри той же AZ.

**Network Areas** — механизм соединения дата-центров через предопределенные TCP-туннели вместо публичного gossip по WAN. Доступен в Enterprise.

**Network Segments** — изоляция LAN gossip на уровне сегментов, позволяющая разделить один дата-центр на несколько непересекающихся gossip-доменов.

**Sameness Groups** — группировка partitions и cluster peers в единую логическую группу с идентичным набором сервисов для упрощения cross-DC failover.

## Основные концепции

### Тарификация и лицензирование

Consul Enterprise поставляется в двух редакциях: **Standard** и **Premium**. Лицензия привязывается к кластеру (per-cluster) или к количеству узлов (per-node в Kubernetes). Начиная с 1.10.0, лицензия должна быть доступна на момент старта агента.

| Компонент | Способ получения лицензии |
| :--- | :--- |
| **Server agent** | `CONSUL_LICENSE`, `CONSUL_LICENSE_PATH` или `license_path` в конфигурации |
| **Client agent** | Автоматически с серверов (требует ACL-токен) или локально (если ACL отключены) |
| **Snapshot agent** | Автоматически с серверов или клиентских агентов (требует ACL-токен) |
| **Virtual agent (K8s)** | Не требует лицензии; entitlement определяется на уровне кластера |

```hcl
# /etc/consul.d/server.hcl — серверный агент
license_path = "/etc/consul.d/license.hclic"
```

```bash
# Переменные окружения (systemd unit)
Environment="CONSUL_LICENSE=$(cat /etc/consul.d/license.hclic)"
# или
Environment="CONSUL_LICENSE_PATH=/etc/consul.d/license.hclic"
```

### Сравнение функций: CE vs Enterprise

| Категория | CE | Enterprise Standard | Enterprise Premium |
| :--- | :--- | :--- | :--- |
| **Service Discovery** | DNS, HTTP API, catalog | + DNS Views, Sameness Groups | + DNS Views, Sameness Groups |
| **Service Mesh** | Single DC, mTLS, intentions | ❌ | Multi-cluster, locality-aware routing, fault injection |
| **KV Store** | CRUD, ACL | + Namespaces/Partitions | + Namespaces/Partitions |
| **API Gateway** | ✅ (single DC) | ❌ | ✅ (multi-DC, JWT verification) |
| **Ingress/Terminating Gateway** | ✅ (single DC) | ❌ | ✅ |
| **Multi-tenancy** | ❌ | Namespaces, Admin Partitions | Namespaces, Admin Partitions |
| **Isolation** | Базовые ACL | + Network Segments, Network Areas | + Network Segments, Network Areas |
| **Governance** | Ручное управление | + Sentinel, Audit Logging | + Sentinel, Audit Logging |
| **Resiliency & Scale** | Базовый Autopilot | + Redundancy Zones, Enhanced Read Replicas, Automated Upgrades | + Redundancy Zones, Enhanced Read Replicas, Automated Upgrades |
| **Support** | Community | Official HashiCorp/IBM support | Official HashiCorp/IBM support |
| **FIPS 140-3** | ❌ | ✅ | ✅ |
| **LTS releases** | ❌ | ✅ | ✅ |

### Архитектурные особенности Enterprise

#### 1. Namespaces и Admin Partitions

**Namespace** — логический изолятор внутри Admin Partition, разделяющий сервисы, политики ACL и KV-ключи между командами.

**Admin Partition** — административная граница, обеспечивающая полную изоляцию каталога сервисов и сетевых областей на уровне дата-центра. Разделы используют общие серверы Consul и Raft-кворум, но имеют независимые пространства имен.

```
┌─────────────────────────────────────────────────────────────┐
│              Consul Enterprise Datacenter                    │
│                                                             │
│  ┌─────────────────┐           ┌─────────────────┐         │
│  │ Admin Partition │           │ Admin Partition │         │
│  │    Platform     │           │     Billing     │         │
│  │  ┌───────────┐  │           │  ┌───────────┐  │         │
│  │  │ NS: prod  │  │           │  │ NS: dev   │  │         │
│  │  └───────────┘  │           │  └───────────┘  │         │
│  │  ┌───────────┐  │           │  ┌───────────┐  │         │
│  │  │ NS: staging│ │           │  │ NS: test  │  │         │
│  │  └───────────┘  │           │  └───────────┘  │         │
│  └─────────────────┘           └─────────────────┘         │
│            ↓ Shared Control Plane (Servers)                 │
│  ┌─────────────────────────────────────────────┐            │
│  │   Consul Servers (Raft, Catalog, KV, ACL)   │            │
│  └─────────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────┘
```

#### 2. Sentinel — Policy as Code

Sentinel позволяет создавать декларативные политики с контекстными данными:
- **Время суток:** Разрешить deploy только в окне 10:00–18:00
- **Геолокация:** Блокировать доступ из не-корпоративных IP
- **Состояние кластера:** Разрешить запись только при `consul_raft_autopilot_healthy = 1`
- **MFA:** Требовать второе подтверждение для чувствительных операций

```hcl
policy "deploy-window" {
  enforcement_level = "hard-mandatory"
  "maintenance_mode == false" {
    hour = ["10-18"]
    weekday = ["monday-friday"]
  }
}
```

#### 3. Redundancy Zones

Распределение серверов по AZ для защиты от сбоя целой зоны без раздувания Raft-кворума:
- В каждой AZ назначается один активный `voter`. Остальные — `non-voters`.
- При отказе `voter`, Autopilot автоматически повышает `non-voter` в той же AZ.
- Работает только внутри одной AZ; при отказе всей AZ требуется ручное вмешательство.

#### 4. Network Areas

Network Areas предоставляют предопределенные TCP-туннели между дата-центрами как альтернативу публичному WAN gossip:
- Низкоуровневая изоляция Federation traffic.
- Определены на уровне серверов через `operator area` команды.
- Доступны только в Enterprise.

#### 5. Automated Server Backups и Upgrades

Enterprise включает встроенный механизм автоматических снапшотов и плановых обновлений:
- **Automated Backups:** Планирование снапшотов через `snapshot agent` без внешних cron-скриптов.
- **Automated Upgrades:** Поэтапное обновление серверов с автоматическим transfer лидерства.

#### 6. Audit Logging

Enterprise-фича для compliance. Логирует все операции ACL и configuration changes в файловый sink. Для передачи в SIEM требуется внешний агент (например, Filebeat).

## Практические сценарии

### 1. Установка лицензии на серверы

```hcl
# /etc/consul.d/server.hcl
license_path = "/etc/consul.d/license.hclic"
```

```bash
# Применение: reload агента
consul reload

# Проверка лицензии
consul license inspect
# → Valid: true
# → Package: premium
# → Features: ["Admin Partitions", "Namespaces", "Sentinel", "Redundancy Zones", ...]
# → Expiration: 2026-12-31T23:59:59Z
```

> **Важно:** Начиная с Consul 1.10.0, лицензия должна быть доступна при старте агента. Серверы больше не автоматически распространяют лицензию между собой. Каждый сервер должен иметь локальную копию.

### 2. Автоматическое получение лицензии клиентскими агентами

```hcl
# /etc/consul.d/client.hcl
retry_join = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]

acl {
  enabled = true
  tokens {
    agent = "a7c9e8f2-..."
  }
}
```

```bash
# Клиентский агент автоматически забирает лицензию с серверов при старте.
# Для диагностики:
journalctl -u consul -f | grep -i license
# → "successfully retrieved license from server" или ошибка

# Если ACL отключены — лицензия должна быть задана локально:
export CONSUL_LICENSE="$(cat /etc/consul.d/license.hclic)"
```

### 3. Создание Admin Partition и Namespace

```bash
# Создание Admin Partition
consul partition create -name platform -description "Platform services"

# Создание Namespace внутри Partition
consul namespace create -name billing -partition platform -description "Billing team"

# Регистрация сервиса в Namespace
consul services register -partition platform -namespace billing web-app.hcl

# Просмотр сервисов
consul catalog services -partition platform -namespace billing
```

### 4. Настройка Sentinel политики

```bash
# Создание политики
consul sentinel policy create -name "deploy-restrictions" -policy @deploy.hcl

# Привязка к роли
consul sentinel policy add-role -name "deploy-restrictions" -role-name "deployer"

# Проверка списка политик
consul sentinel policy list
# → Name: deploy-restrictions, Enforcement: hard-mandatory
```

### 5. Настройка Redundancy Zones

```hcl
# /etc/consul.d/server.hcl — сервер в AZ "us-east-1a"
server = true
bootstrap_expect = 5
redundancy_zone = "us-east-1a"
```

```hcl
# /etc/consul.d/server.hcl — сервер в AZ "us-east-1b"
server = true
bootstrap_expect = 5
redundancy_zone = "us-east-1b"
```

```bash
# Проверка распределения
consul operator raft list-peers
# → voter, us-east-1a, ...
# → voter, us-east-1b, ...
# → non-voter, us-east-1a, ...
```

### 6. DNS Views (Split-horizon DNS)

```hcl
# /etc/consul.d/server.hcl
dns {
  views {
    internal {
      resolvers {
        service = "web"
        subnet  = "10.0.0.0/8"
        answer {
          address = "10.0.1.50"
        }
      }
    }
    external {
      resolvers {
        service = "web"
        subnet  = "0.0.0.0/0"
        answer {
          address = "203.0.113.10"
        }
      }
    }
  }
}
```

### 7. Snapshot Agent (Automated Backups)

```hcl
# /etc/consul.d/snapshot-agent.hcl
datacenter = "dc1"
consul {
  address = "127.0.0.1:8500"
}

snapshot {
  interval = "1h"
  retention = "720h"  # 30 дней
  storage {
    local {
      path = "/opt/consul/snapshots"
    }
  }
}
```

```bash
# Запуск snapshot agent (требует Enterprise-бинар)
consul snapshot agent -config-file /etc/consul.d/snapshot-agent.hcl
```

## Валидация и мониторинг

### Проверка лицензии

```bash
# Инспекция лицензии (работает с локальным файлом или окружением)
consul license inspect
# → Valid: true
# → Package: premium
# → Features: ["Admin Partitions", ...]
# → Expiration: 2026-12-31T23:59:59Z

# Получение активной лицензии кластера
consul license get
# → Valid: true, License: {...}
```

```bash
# Проверка доступных функций через CLI
consul namespace list
consul partition list
consul sentinel policy list

# Проверка Redundancy Zones
consul operator raft list-peers
# → voter/non-voter distribution across AZs
```

### Мониторинг лицензирования

```bash
# Проверка срока действия
consul license inspect | grep Expiration
# → Expiration: 2026-12-31T23:59:59Z

# Проверка warnings при старте
journalctl -u consul -f | grep -i "license"
# → ищите предупреждения об истечении срока или невалидности
```

### Мониторинг Enterprise-функций

| Функция | Метрика/Команда |
| :--- | :--- |
| **Sentinel** | `consul sentinel policy list`, логи Sentinel evaluations |
| **Redundancy Zones** | `consul operator raft list-peers`, `consul_raft_leader_lastContact` |
| **Audit Logging** | Размер файла audit log, `consul_audit` метрики |
| **Automated Backups** | Наличие снапшотов в целевом хранилище, `snapshot_agent` логи |
| **Network Areas** | `consul operator area list`, метрики `consul_network_*` |

## Устранение неполадок

### Лицензия не найдена при старте

- **Причина:** Файл лицензии отсутствует или путь указан неверно. Начиная с 1.10.0, временные лицензии удалены.
- **Диагностика:**
  ```bash
  consul license inspect
  # → Error: no license configured

  journalctl -u consul -f | grep -i license
  # → "no license found, shutting down"
  ```
- **Решение:** Укажите `license_path` в конфигурации сервера или переменную окружения `CONSUL_LICENSE_PATH`. Проверьте права на чтение файла.

### Client agent не может присоединиться к кластеру

- **Причина:** Клиентский агент не может автоматически получить лицензию с серверов. Причины: нет `retry_join`, нет ACL-токена, или ACL отключены.
- **Диагностика:**
  ```bash
  journalctl -u consul -f | grep -i "license"
  # → "unable to retrieve license: ACL token missing"

  # Или, если ACL отключены:
  # → "license required but ACLs disabled"
  ```
- **Решение:** Если ACL включены — задайте agent-токен с любыми правами. Если ACL отключены — задайте `CONSUL_LICENSE` или `CONSUL_LICENSE_PATH` на клиентских агентах.

### Snapshot agent завершает работу через 5 минут

- **Причина:** Snapshot agent не может получить лицензию (нет связи с серверами или нет ACL-токена).
- **Диагностика:**
  ```bash
  journalctl -u consul-snapshot -f | grep -i license
  # → "failed to retrieve license from agent"
  ```
- **Решение:** Проверьте доступность серверов и наличие ACL-токена в конфигурации snapshot agent.

### Sentinel политика игнорируется в OSS

- **Причина:** Sentinel доступен только в Enterprise. В OSS политики silently игнорируются.
- **Диагностика:**
  ```bash
  consul sentinel policy list
  # → пустой вывод, но операция разрешена
  ```
- **Решение:** Перейдите на Enterprise-лицензию или используйте ACL policies для ограничений.

### Истекшая лицензия

- **Причина:** Срок действия лицензии истек.
- **Диагностика:**
  ```bash
  consul license inspect
  # → Valid: false
  # → Expiration: 2025-01-01T00:00:00Z (прошлое)
  ```
- **Решение:** Получите новую лицензию у продавца и примените через `license_path` на всех серверах. Enterprise-функции отключаются после истечения срока.

### Namespace/Partition не создается

- **Причина:** Лицензия не Enterprise или функция недоступна для текущего тарифа.
- **Диагностика:**
  ```bash
  consul namespace create -name test
  # → "operation not permitted" или "namespace feature not available"

  consul license inspect | grep Package
  # → Package: oss  (или Standard без нужной фичи)
  ```
- **Решение:** Проверьте тариф лицензии (`Standard` vs `Premium`). Убедитесь, что лицензия действительна.

## Лучшие практики

- **Лицензия на серверах:** Всегда храните файл лицензии на каждом сервере. Не полагайтесь только на автоматическое распространение (удалено в 1.10.0).
- **ACL для client agents:** Включите ACL на всех агентах, чтобы клиенты могли автоматически забирать лицензию. Используйте agent-токен с минимально необходимыми правами.
- **Версионирование лицензии:** Храните `.hclic` файл в секрет-менеджере (Vault, SOPS). Версионируйте изменения.
- **Мониторинг срока:** Отслеживайте `Expiration` через `consul license inspect` и настраивайте алерты за 30/7/1 день до истечения.
- **Standard vs Premium:** Оцените потребности: Standard покрывает multi-tenancy, Redundancy Zones, Sentinel; Premium добавляет Service Mesh multi-cluster и API gateway.
- **Redundancy Zones:** Обязательны для geo-распределенных кластеров Enterprise. Используйте по одной AZ на voter.
- **Sentinel:** Тестируйте политики в staging перед production. Используйте `hard-mandatory` только для критичных ограничений.
- **Network Areas vs WAN Federation:** Для новых развертываний используйте Network Areas вместо WAN Federation — это более безопасный и контролируемый механизм.
- **Rollback:** При обновлении лицензии сохраняйте старый файл до подтверждения работы кластера. `consul license inspect` показывает только текущую активную лицензию.
- **Virtual agents (K8s):** В Kubernetes не назначайте лицензии на client agents'ы — они не нужны. Управляйте entitlement на уровне кластера.

## Граничные случаи

- **Использование `consul license list`:** Команда `consul license list` deprecated в 1.10.0 и всегда возвращает ошибку. Используйте `consul license get` и `consul license inspect`.
- **Только v2 лицензии:** `consul license inspect` осмысленно работает только с v2 лицензиями (Consul 1.6+). v1 лицензии не возвращают деталей.
- **OSS vs Enterprise behavior:** При истечении лицензии кластер не останавливается, но Enterprise-функции отключаются. Sentinel политики игнорируются, Namespaces/Partitions становятся недоступны.
- **Per-cluster vs per-node:** Классическая лицензия per-cluster требует отдельной лицензии на каждый кластер серверов. В Kubernetes с virtual agents возможно per-node лицензирование.
- **Enterprise → OSS миграция:** Требует ручного удаления Enterprise-only config entries (namespaces, admin partitions) и отката snapshot'ов (Enterprise снапшоты несовместимы с OSS).
- **Automated Upgrades в ECS:** Automated Upgrades не поддерживаются в ECS runtime. Доступны только для VM и Kubernetes.
- **FIPS:** FIPS 140-3 Compliance доступна только в Enterprise. Требует сборки Enterprise бинарника с FIPS-модом.
- **Redundancy Zones и AZ:** Redundancy Zones работают только внутри одной AZ. При отказе всей AZ требуется ручное вмешательство. Cross-AZ автоматическое повышение не поддерживается.
- **Network Segments в ECS:** Network Segments недоступны в ECS runtime. Доступны только для VM и Kubernetes клиентов.
- **Consul-Terraform-Sync:** CTS работает с CE и Enterprise, но CTS Enterprise-коннекторы требуют Enterprise-лицензии.

## Дополнительная информация

- **[Consul Enterprise Documentation](https://developer.hashicorp.com/consul/docs/enterprise)** — официальная документация по Enterprise-функциям.
- **[Consul Licensing](https://developer.hashicorp.com/consul/docs/enterprise/license)** — управление лицензиями, приоритет загрузки, client auto-discovery.
- **[Consul Editions](https://developer.hashicorp.com/consul/docs/fundamentals/editions)** — сравнение CE, Standard и Premium.
- **[Consul License API](https://developer.hashicorp.com/consul/api-docs/operator/license)** — HTTP API для работы с лицензиями.
- **[Sentinel Documentation](https://developer.hashicorp.com/consul/docs/deprecated/sentinel)** — синтаксис политик.
- **[Consul CLI License Commands](https://developer.hashicorp.com/consul/commands/license)** — справочник CLI.
- **[Consul Namespaces](./consul_kv_store.md#изоляция-enterprise)** — логическое разделение ресурсов.
- **[Consul Architecture — Enterprise Isolation](./consul_architecture.md#многопользовательская-изоляция-enterprise)** — архитектура multi-tenancy.
- **[Consul Consensus — Redundancy Zones](./consul_consensus.md#зоны-избыточности-enterprise)** — Raft-распределение по AZ.
- **[Consul Audit Logging](./consul_audit_logging.md)** — аудит операций (Enterprise).
- **[Consul ESM](./consul_esm.md)** — мониторинг внешних сервисов (Enterprise).
- **[Consul Config Entries Lifecycle](./consul_config_entries_lifecycle.md)** — Enterprise-only config entries.
