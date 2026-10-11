# Consul Network Segments

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x / 1.18.x

## Определения

**Consul Network Segments** — механизм разбиения одного дата-центра на несколько независимых LAN gossip-пулов (сегментов). Network segments позволяют создавать изолированные группы узлов, что снижает нагрузку на сеть и CPU при больших кластерах и позволяет работать в средах с частичной сетевой изоляцией (segmented networks).

**Segmented network** — среда, в которой политики безопасности или firewall-правила предотвращают полную mesh-связность между всеми агентами в дата-центре. Network segments решают эту проблему, ограничивая требования к связности только внутри одного сегмента.

**Сегмент (segment)** — логическая группа узлов с общим именем сегмента. Внутри сегмента работает стандартный LAN gossip (Serf/SWIM). Клиенты разных сегментов не видят друг друга через gossip.

**<default> сегмент** — сегмент по умолчанию (имя — пустая строка). Все агенты, не настроенные на конкретный сегмент, автоматически joining в `<default>`. Для full-mesh кластеров без сегментации используется только `<default>`.

**Server membership** — серверы Consul автоматически являются участниками ВСЕХ сегментов в дата-центре, включая `<default>`. Это позволяет им маршрутизировать RPC между сегментами.

**Client membership** — клиентский агент может быть участником ТОЛЬКО одного сегмента за раз. По умолчанию клиент joining в `<default>`, если явно не указан `segment`.

**Segment listener** — отдельный gossip-порт (по умолчанию 8301 UDP) для каждого не-`<default>` сегмента на сервере. Клиенты joining к конкретному сегменту через адрес `server:segment_port`.

**rpc_listener** — опциональный параметр в конфигурации сегмента на сервере. Если `true`, для сегмента запускается отдельный RPC-слушатель на порту 8300. Используется только когда `bind` сегмента отличается от основного `-bind` сервера.

**Segment isolation** — изоляция на уровне LAN gossip. Клиенты в разных сегментах не обнаруживают друг друга через gossip, но могут обращаться к серверам Consul через RPC и использовать HTTP/DNS API для service discovery.

## Основные концепции

### Архитектура

```
Без segments (<default> только):

  ┌─────────────────────────────────────────────┐
  │         <default> LAN Gossip Pool           │
  │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │
  │  │ S1   │ │ S2   │ │ C1   │ │ C2   │       │
  │  ├──────┤ ├──────┤ ├──────┤ ├──────┤       │
  │  │8301  │ │8301  │ │8301  │ │8301  │       │
  │  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘       │
  │     └────────┴────────┴────────┘            │
  │         Full mesh required                   │
  └─────────────────────────────────────────────┘

С segments (alpha + beta + <default>):

  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
  │   Segment alpha  │  │   Segment beta   │  │   <default>      │
  │  ┌──────┐  ┌───┐│  │  ┌──────┐  ┌───┐│  │  ┌──────┐  ┌───┐ │
  │  │ C1   │  │ S1││  │  │ C4   │  │ S1││  │  │ C6   │  │ S1│ │
  │  ├──────┤  ├─┬─┤│  │  ├──────┤  ├─┬─┤│  │  ├──────┤  ├─┬─┤ │
  │  │8303  │  │ │ ││  │  │8304  │  │ │ ││  │  │8301  │  │ │ │ │
  │  └──┬───┘  │ │ ││  │  └──┬───┘  │ │ ││  │  └──┬───┘  │ │ │ │
  │     └──────┼─┼─┘│  │     └──────┼─┼─┘│  │     └──────┼─┼─┘ │
  │            │ │  │  │            │ │  │  │            │ │   │
  └────────────┼─┼──┘  └────────────┼─┼──┘  └────────────┼─┼───┘
               │ │                   │ │                   │ │
               ▼ ▼                   ▼ ▼                   ▼ ▼
          ┌─────────────┐       ┌─────────────┐       ┌─────────────┐
          │  Server S1  │       │  Server S1  │       │  Server S1  │
          │  (все       │       │  (все       │       │  (все       │
          │   сегменты) │       │   сегменты) │       │   сегменты) │
          └─────────────┘       └─────────────┘       └─────────────┘
```

### Принцип работы

1. **Определение сегментов на серверах:** Оператор добавляет блок `segments` в конфигурацию серверных агентов. Каждый сегмент имеет уникальное имя, адрес `bind`, адрес `advertise` и номер порта для gossip. Сервер запускает отдельный Serf-инстанс для каждого сегмента.

2. **Участие серверов:** Сервер автоматически joining во ВСЕ сегменты дата-центра. При запуске сервер логируется как `alive` во всех сегментах. В выводе `consul members` для сервера отображается `<all>` в колонке Segment (для `<default>`) или конкретный сегмент.

3. **Joining клиентов:** Клиентский агент может принадлежать только одному сегменту. При старте клиент указывает `segment = "alpha"` в конфигурации и `retry_join` адрес сервера в формате `server:segment_port` (например, `10.0.0.1:8303`). Клиент подключается только к агентам того же сегмента.

4. **Изоляция gossip:** Внутри сегмента работает стандартный SWIM-протокол (Serf). Сообщения gossip не распространяются между сегментами. Это снижает объем трафика с O(N^2) до O(N) на сегмент.

5. **Межсегментное взаимодействие:** Клиенты изолированы на уровне gossip, но могут обращаться к серверам Consul через RPC (порт 8300 TCP) для выполнения HTTP/DNS запросов, регистрации сервисов и discovery. Серверы маршрутизируют запросы между сегментами.

6. **Шифрование gossip:** Если включен `encrypt`, один и тот же gossip-ключ применяется ко ВСЕМ сегментам на всех узлах. Segments не создают отдельных ключей. Ротация ключа через `consul keyring` затрагивает все сегменты одновременно.

7. **Service Discovery через сегменты:** Запросы DNS/HTTP API к серверам возвращают сервисы из ВСЕХ сегментов. Клиент может фильтровать результаты по сегменту через метаданные узла или API-параметры. Сервисы в разных сегментах видимы друг для друга через Catalog API.

### Конфигурация сегментов на серверах

Сервер определяет сегменты через блок `segments` в HCL/JSON конфигурации:

| Поле | Тип | Обязательно | Описание |
| :--- | :--- | :--- | :--- |
| `name` | string | Да | Имя сегмента, 1–64 символа |
| `bind` | string | Нет | Адрес для приема gossip-трафика. По умолчанию — `bind_addr` агента |
| `advertise` | string | Нет | Адрес для анонса другим узлам. По умолчанию — `advertise_addr` |
| `port` | integer | Да | Порт UDP для gossip сегмента. Должен отличаться от портов других сегментов |
| `rpc_listener` | boolean | Нет | Запускать отдельный RPC-слушатель для сегмента. Только если `bind` отличается от `-bind`. По умолчанию `false` |

### Ограничения и совместимость

- **Только Enterprise:** Network segments доступны только в Consul Enterprise начиная с версии 0.9.3.
- **Несовместимо с Admin Partitions:** Параметр `segment` не может использоваться одновременно с `partition`. Выберите один механизм изоляции.
- **WAN Federation:** Segments влияют только на LAN gossip (порт 8301). WAN gossip между дата-центрами (порт 8302) остается единым.
- **Cluster Peering:** Peering работает через серверы Consul. Segments не влияют на peered трафик.
- **Network Areas (Enterprise):** Для изоляции WAN gossip между дата-центрами используйте Network Areas. Segments и Network Areas дополняют друг друга для сложных топологий.

## Практические сценарии

### 1. Определение сегментов на серверах

```hcl
# /etc/consul.d/server.hcl
datacenter = "dc1"
data_dir   = "/opt/consul"
log_level  = "INFO"

server = true
bootstrap_expect = 3

# Шифрование gossip (общий ключ для всех сегментов)
encrypt = "YwgWlBvicJN17UOYcutXLpJSZsw5aWpLEEWqgK635zA="

# Определение сегментов
segments = [
  {
    name      = "alpha"
    bind      = "10.0.1.10"
    advertise = "10.0.1.10"
    port      = 8303
  },
  {
    name      = "beta"
    bind      = "10.0.2.10"
    advertise = "10.0.2.10"
    port      = 8304
    # Отдельный RPC-слушатель (если bind отличается от основного)
    rpc_listener = true
  }
]

# Retry join в <default> сегменте
retry_join = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
```

```json
{
  "datacenter": "dc1",
  "data_dir": "/opt/consul",
  "server": true,
  "bootstrap_expect": 3,
  "encrypt": "YwgWlBvicJN17UOYcutXLpJSZsw5aWpLEEWqgK635zA=",
  "segments": [
    {
      "name": "alpha",
      "bind": "10.0.1.10",
      "advertise": "10.0.1.10",
      "port": 8303
    },
    {
      "name": "beta",
      "bind": "10.0.2.10",
      "advertise": "10.0.2.10",
      "port": 8304,
      "rpc_listener": true
    }
  ],
  "retry_join": ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
}
```

```bash
# Запуск сервера
consul agent -config-file=/etc/consul.d/server.hcl

# Ожидаемый вывод:
# → consul: Started listener for LAN segment "alpha" on 10.0.1.10:8303
# → consul: Started listener for LAN segment "beta" on 10.0.2.10:8304
# → serf: EventMemberJoin: server1.dc1 10.0.0.1
```

### 2. Настройка клиентов для joining в сегменты

```hcl
# /etc/consul.d/client-alpha.hcl
datacenter = "dc1"
data_dir   = "/opt/consul"
log_level  = "INFO"

# Клиент joining в сегмент alpha
segment = "alpha"

# Join к segment listener на сервере (обязательно указать порт сегмента)
retry_join = ["10.0.1.10:8303"]

# Адрес для HTTP/DNS
client_addr = "0.0.0.0"
```

```bash
# Запуск клиента через CLI
consul agent -client \
  -datacenter=dc1 \
  -segment=alpha \
  -bind=10.0.1.20 \
  -join=10.0.1.10:8303 \
  -data-dir=/tmp/consul-client
```

```hcl
# /etc/consul.d/client-beta.hcl
datacenter = "dc1"
data_dir   = "/opt/consul"
log_level  = "INFO"

segment = "beta"
retry_join = ["10.0.2.10:8304"]
client_addr = "0.0.0.0"
```

> **Важно:** Порт в `retry_join` должен соответствовать порту сегмента на сервере (8303 для alpha, 8304 для beta). Использование порта 8301 приведет к joining в `<default>` сегмент.

### 3. Верификация сегментов

```bash
# Просмотр всех узлов с указанием сегмента
consul members
# → Node          Address           Status  Type    Build      Protocol  DC   Segment
# → server1       10.0.0.1:8301     alive   server  1.22.3    2         dc1  <all>
# → client-alpha  10.0.1.20:8303    alive   client  1.22.3    2         dc1  alpha
# → client-beta   10.0.2.20:8304    alive   client  1.22.3    2         dc1  beta

# Просмотр конкретного сегмента
consul members -segment alpha
# → Node          Address           Status  Type    Build      Protocol  DC   Segment
# → server1       10.0.0.1:8301     alive   server  1.22.3    2         dc1  alpha
# → client-alpha  10.0.1.20:8303    alive   client  1.22.3    2         dc1  alpha

# Все сегменты
consul members -segment "*"

# Через API
curl http://127.0.0.1:8500/v1/agent/members?segment=alpha
# → [{"Name":"server1","Addr":"10.0.0.1","Port":8301,"Tags":{"segment":"alpha",...}}, ...]

# Проверка через info
consul info | grep -E "serf_lan|segment"
# → serf_lan.encrypted = true
# → segment.current = alpha
```

### 4. Service Discovery через сегменты

```bash
# DNS: сервисы из всех сегментов возвращаются
dig @127.0.0.1 -p 8600 web.service.consul A
# → 10.0.1.30 (alpha)
# → 10.0.2.30 (beta)

# HTTP API: запрос к серверу возвращает все сегменты
curl "http://10.0.0.1:8500/v1/catalog/service/web?dc=dc1"
# → [{"Node":"client-alpha","Address":"10.0.1.30",...},{"Node":"client-beta","Address":"10.0.2.30",...}]

# Фильтрация по сегменту через node_meta (Consul 1.15+)
curl "http://10.0.0.1:8500/v1/catalog/service/web?dc=dc1&node-meta=segment:alpha"
# → [{"Node":"client-alpha",...}]
```

### 5. Настройка firewall для сегментов

```bash
# Сервер: открываем порты gossip для каждого сегмента
firewall-cmd --add-port=8301/udp --permanent   # <default> segment
firewall-cmd --add-port=8303/udp --permanent   # alpha segment
firewall-cmd --add-port=8304/udp --permanent   # beta segment
firewall-cmd --add-port=8300/tcp --permanent   # RPC (общий для всех сегментов)
firewall-cmd --reload

# Или iptables
iptables -A INPUT -p udp --dport 8301 -j ACCEPT   # <default>
iptables -A INPUT -p udp --dport 8303 -j ACCEPT   # alpha
iptables -A INPUT -p udp --dport 8304 -j ACCEPT   # beta
iptables -A INPUT -p tcp --dport 8300 -j ACCEPT   # RPC
```

### 6. Ротация gossip-ключа с сегментами

```bash
# Генерация нового ключа
consul keyring -new-key="aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789+/=" -use

# Применение на всех узлах ВСЕХ сегментов
# Ключ один для всего кластера, включая все сегменты
consul reload

# Проверка
consul info | grep serf_lan.encrypted
# → true (на всех сегментах)
```

## Валидация

### Проверка конфигурации сегментов

```bash
# Проверка что сервер слушает все сегменты
ss -u -lpn | grep consul
# → UNCONN  0  0  10.0.1.10:8303  0.0.0.0:*  users:(("consul",...))
# → UNCONN  0 0  10.0.2.10:8304  0.0.0.0:*  users:(("consul",...))

# Проверка что клиент в правильном сегменте
consul info | grep segment.current
# → segment.current = alpha

# Проверка firewall
nc -zv 10.0.1.10 8303 -u
# → Connection to 10.0.1.10 8303 udp port [udp/*] succeeded!
```

### Проверка изоляции gossip

```bash
# На клиенте alpha: попытка соединения с портом beta
nc -zv 10.0.2.10 8304 -u
# → Connection refused (ожидаемо)

# На клиенте alpha: запрос к серверу работает
curl http://10.0.0.1:8500/v1/status/leader
# → 10.0.0.1:8300 (работает через RPC, не через gossip)
```

### Проверка серверного bridging

```bash
# Клиент alpha не видит клиент beta через gossip
# но сервер видит оба через RPC:
consul catalog nodes -segment=alpha
# → server1, client-alpha

consul catalog nodes -segment=beta
# → server1, client-beta

consul catalog nodes
# → server1, client-alpha, client-beta (через сервер)
```

## Устранение неполадок

### Клиент не joining в сегмент, а falling back в <default>

```bash
# Симптомы:
consul members
# → client-alpha 10.0.1.20:8301  alive  ...  <default>
# (ожидалось: alpha)

# Причины:
# 1. retry_join указывает на порт 8301 сервера, а не на порт сегмента
# 2. segment не указан в конфигурации клиента

# Диагностика:
consul info | grep segment
# → segment.current = <default>

# Решение:
# Исправьте retry_join на адрес segment listener:
# retry_join = ["10.0.1.10:8303"]  # alpha segment port
```

### Клиент не может join к серверу

```bash
# Симптомы:
# → [ERR] agent: failed to join 10.0.1.10:8303: dial tcp 10.0.1.10:8303: connect: connection refused

# Причины:
# 1. Сервер не слушает порт сегмента
# 2. Firewall блокирует UDP 8303
# 3. Bind адрес сегмента неверен

# Диагностика:
ss -u -lpn | grep 8303
# → (пусто) — сервер не слушает порт

# Проверка конфигурации сервера:
grep -A5 "segments" /etc/consul.d/server.hcl
# → segments = [{name="alpha", port=8303, ...}]

# Решение:
# Перезапустите сервер после изменения конфигурации segments
consul reload
```

### Сервер отображается только в <default> сегменте

```bash
# Симптомы:
consul members -segment alpha
# → (пусто)

# Причины:
# 1. Сервер не стартовал с сегментами
# 2. Логи: "Failed to start listener for LAN segment"

# Диагностика:
journalctl -u consul -f | grep segment
# → [ERR] Failed to start listener for LAN segment "alpha": bind: address already in use

# Решение:
# Проверьте что порт сегмента свободен
ss -u -lpn | grep 8303
# Устраните конфликт или измените порт в конфигурации
```

### Высокая нагрузка на сеть в сегменте сохраняется

```bash
# Симптомы:
# Высокий traffic на порту сегмента

# Диагностика:
iftop -p -u -f "port 8303"
# → большой объем UDP-трафика

# Решение:
# Увеличьте gossip интервалы для конкретного сегмента:
consul info | grep serf_lan
# → serf_lan.gossip_interval = 200ms (по умолчанию)

# В конфигурации сервера:
gossip_lan {
  gossip_interval = "500ms"
  probe_interval = "2s"
}
# Примечание: gossip_lan настройки общие для всех сегментов на данном сервере
```

### Кросс-сегментный service discovery возвращает не все сервисы

```bash
# Симптом:
curl "http://server:8500/v1/catalog/services" | jq .
# → отсутствуют сервисы из другого сегмента

# Причина:
# Запрос идет к клиентскому агенту в сегменте, у которого нет полного каталога
# Либо используется stale=only на сервере без replication

# Решение:
# Обращайтесь к серверу напрямую:
curl "http://server:8500/v1/catalog/services"
# Серверы видят все сегменты
```

### Segment name conflicts

```bash
# Симптом:
# → [ERR] agent: segment 'alpha' already defined

# Причина:
# Два серверных процесса пытаются слушать один сегмент на одном порту

# Решение:
# Убедитесь что каждый сегмент имеет уникальный порт на каждом сервере
# segments = [{name="alpha", port=8303}, {name="beta", port=8304}]
```

## Лучшие практики

- **Начинайте без segments:** Используйте `<default>` сегмент для кластеров <5000 узлов. Segments добавляют сложность администрирования.
- **Enterprise requirement:** Network segments доступны только в Consul Enterprise 0.9.3+. Убедитесь что у вас действующая лицензия.
- **Server placement:** Размещайте серверы на машинах с доступом ко всем сегментам (route-able из всех subnet). Серверы автоматически joining во все сегменты.
- **Segment sizing:** Рекомендуется 500–1000 узлов на сегмент. При превышении — создавайте новый сегмент, а не увеличивайте существующий.
- **Port planning:** Выделяйте непересекающиеся диапазоны портов для сегментов. Стандартный LAN gossip — 8301 UDP. Segments используют 8302+ UDP.
- **Segment naming:** Используйте осмысленные имена, отражающие топологию: `segment-frontend`, `segment-backend`, `segment-db`.
- **Join addresses:** Клиенты должны joining к segment listener сервера (порт сегмента), а не к стандартному LAN порту 8301.
- **Firewall rules:** Открывайте только порт конкретного сегмента для соответствующих подсетей. Запрещайте межузловой gossip между сегментами на L3.
- **Gossip encryption:** Используйте единый `encrypt` ключ для всех сегментов. Ротация ключа затрагивает все сегменты одновременно.
- **Monitoring:** Отслеживайте метрики `consul.serf.member.failed`, `consul.serf.member.join`, `consul.serf.member.leave` с тегом `segment`.
- **Admin Partitions vs Segments:** Для логической изоляции сервисов/ACL используйте Admin Partitions. Для сетевой изоляции gossip — segments. Не смешивайте в одном конфиге.
- **rpc_listener:** Используйте только при необходимости отдельного RPC-порта для сегмента (например, при bind сегмента на отдельном интерфейсе).
- **Rolling restart:** При добавлении нового сегмента перезапускайте серверы по одному. Существующие клиенты продолжают работать в своих сегментах.

## Граничные случаи

- **WAN Federation:** Segments влияют только на LAN gossip внутри дата-центра. WAN gossip (порт 8302 UDP) между дата-центрами остается единым. Серверы всех сегментов участвуют в WAN Federation.
- **Cluster Peering:** Peering устанавливается между серверами. Segments не влияют на peered трафик и replication каталога.
- **Admin Partitions incompatibility:** Параметр `segment` несовместим с `partition`. Нельзя назначить агенту одновременно segment и admin partition.
- **Catalog v2:** Multi-port сервисы корректно работают внутри сегментов. Service Catalog через серверы видит все сегменты.
- **Migration from single segment:** При добавлении сегментов в существующий кластер перезапустите серверы с новым конфигом. Существующие клиенты продолжают работу в `<default>`. Новые клиенты могут joining в созданные сегменты.
- **Network Areas (Enterprise):** Для федерации дата-центров без full-mesh WAN используйте Network Areas. Segments решают задачу внутри одного ДЦ, Network Areas — между ДЦ.
- **Multi-homed servers:** Если сервер имеет несколько интерфейсов, используйте `bind` и `advertise` в определении сегмента для явного указания адреса. По умолчанию используется `bind_addr`.
- **Segment with Consul Dataplane:** В Kubernetes Consul Dataplane управляет Envoy без gossip. Network segments в основном применимы к VM-средам. Для Kubernetes используйте Network Policies и Admin Partitions.
- **Gossip keyring rotation:** При ротации gossip ключа через `consul keyring` новый ключ должен быть установлен на ВСЕХ узлах ВСЕХ сегментов до удаления старого. Частичная установка приведет к partition в gossip.
- **Default segment cannot be defined:** Сегмент `<default>` создается автоматически. Не добавляйте его в блок `segments` на сервере — это вызовет ошибку.
- **Segment name constraints:** Имя сегмента должно быть строкой от 1 до 64 символов. Использование пробелов или спецсимволов приведет к ошибке валидации.
- **RPC between segments:** Клиенты из разных сегментов не могут напрямую обмениваться gossip, но оба могут обращаться к серверам по RPC (8300 TCP). Это единственный канал для координации между сегментами.

## Дополнительная информация

- **[Consul Network Segments Overview](https://developer.hashicorp.com/consul/docs/multi-tenant/network-segment)** — обзор концепций, segmented networks, cluster membership.
- **[Create Network Segments on VMs](https://developer.hashicorp.com/consul/docs/multi-tenant/network-segment/vm)** — пошаговое руководство по созданию сегментов на виртуальных машинах.
- **[Consul Agent Configuration — segments](https://developer.hashicorp.com/consul/docs/reference/agent/configuration-file/general#segments)** — справочник параметров `segment` и `segments`.
- **[Consul Network Segments API](https://developer.hashicorp.com/consul/api-docs/operator/segment)** — управление сегментами через HTTP API.
- **[Consul Multi-Tenancy Overview](https://developer.hashicorp.com/consul/docs/multi-tenant)** — Admin Partitions, Namespaces, Network Segments, Sameness Groups.
- **[Consul Architecture](./consul_architecture.md)** — Control Plane, Data Plane, Serf/SWIM, gossip.
- **[Consul Enterprise Licensing](./consul_enterprise_licensing.md)** — сравнение Enterprise и Community функций.
- **[Consul WAN Federation vs Cluster Peering](./consul_wan_vs_peering.md)** — мульти-DC топологии.
- **[Consul Disaster Recovery](./consul-disaster-recovery.md)** — восстановление кластера, gossip keyring.
- **[Consul Telemetry](./consul_telemetry.md)** — метрики Serf для мониторинга сегментов.
- **[Consul at Scale](https://developer.hashicorp.com/consul/docs/manage/scale)** — рекомендации по масштабированию.
