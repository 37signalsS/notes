# Consul как бэкенд для Vault

## Определения

**Consul бэкенд для Vault** — конфигурация, при которой HashiCorp Vault использует внешний распределенный кластер **[Consul](../../Consul/consul_overview.md)** в качестве персистентного хранилища данных и механизма координации высокой доступности (HA).

**Статус:** Данный метод считается **устаревшим (Legacy)** для новых инсталляций, хотя официально поддерживается HashiCorp. Рекомендуемым стандартом (основной вариант) является использование встроенного хранилища **[Raft (Integrated Storage)](./vault_installation.md)**. Использование Consul оправдано только в сложных распределенных топологиях или при наличии зрелой инфраструктуры Consul, требующей глубокой интеграции (например, когда Consul уже эксплуатируется как корпоративное KP хранилище и сервисная сетка).

## Основные концепции

### Роль Consul в архитектуре Vault

При использовании данного бэкенда Consul выполняет две функции:
1.  **K/V Storage:** Хранение зашифрованных данных Vault. Vault шифрует все данные перед записью, поэтому Consul не имеет доступа к открытому тексту секретов.
2.  **High Availability (HA):** Consul предоставляет механизм распределенных блокировок (Sessions) для выбора активного узла (Active Node) и перенаправления запросов с резервных узлов (Standby Nodes).

### Интеграция и Service Discovery

Vault автоматически регистрирует себя в каталоге сервисов Consul с default health check (HTTP-проверка на `/v1/sys/health`). В зависимости от состояния узла используются разные DNS-имена каталога `consul`:

*   `active.vault.service.consul` — активный (Active) узел, обслуживающий запросы;
*   `standby.vault.service.consul` — резервные (Standby) узлы, не выполняющие `vault.status` ответов;
*   `vault.service.consul` — все unsealed-узлы (и active, и standby);

Запечатанные (Sealed) узлы помечают себя как unhealthy и автоматически исключаются из результата Service Discovery, что позволяет строить балансировку через DNS или API Consul без лишних простоев.

> **Примечание:** Если у Vault настроено несколько `listener`, необходимо явно указать, какой адрес Consul должен публиковать как адрес активного узла, через параметры `api_addr` / `cluster_addr`.

> **Ограничение (актуально для Consul 1.14+):** Vault не поддерживает **Consul Dataplane**. Для кластеров, развернутых в Kubernetes, использование Consul 1.14+ с режимом Dataplane по умолчанию потребует выключения Dataplane и перехода обратно на классические client-agent (см. [upgrade guide Consul](https://developer.hashicorp.com/consul/docs/k8s/upgrade)). При использовании обычных client agents (VM, bare-metal) ограничение не распространяется.

Consul-бэкенд использует механизм **Consul Sessions** для выбора активного лидера. Активный узел создаёт сессию, привязывает её к K/V-ключу и удерживает через TTL (`session_ttl`, по умолчанию `15s`), периодически обновляя (renew). Остальные узлы находятся в режиме Standby и возвращают клиенту адрес активного узла (redirect).

В случае отказа активного узла сессия истекает (не возобновляется), блокировка освобождается, и один из Standby-узлов захватывает её через `lock_wait_time` (время ожидания перед очередной попыткой захвата). Выбор лидера координируется на стороне Consul, поэтому Vault не требует собственного алгоритма консенсуса, в отличие от Raft (Integrated Storage).

### Требования к безопасности (ACL)

Если в Consul включена система управления доступом (ACL), Vault требует токен с правами на:
*   Чтение/запись/удаление в префиксе K/V (по умолчанию `vault/`).
*   Создание и управление сессиями (`session`) для работы механизмов HA.
*   Чтение информации агента (`agent`) для корректной работы health check и Service Discovery.
*   Регистрацию сервиса (если включен параметр `service_registration` или `service` в `storage`).

**Пример политики ACL (синтаксис Consul 1.4+, который рекомендуется использовать с современными версиями Vault):**
```hcl
key_prefix "vault/" {
  policy = "write"
}
session_prefix "" {
  policy = "write"
}
service "vault" {
  policy = "write"
}
agent_prefix "" {
  policy = "read"
}
```

## Практические сценарии

### Конфигурация хранилища (vault.hcl)

Пример настройки в файле `/etc/vault.d/vault.hcl`:

```hcl
storage "consul" {
  # Рекомендуется обращаться к локальному Consul Agent (127.0.0.1:8500),
  # а не напрямую к серверу — это упрощает ACL и Health Check.
  address = "127.0.0.1:8500"
  path    = "vault/"
  
  # Использование токена ACL (не Vault токен!)
  token   = "YOUR_CONSUL_ACL_TOKEN"
  
  # Настройка TLS для подключения к Consul. Даже во внутренней сети
  # не рекомендуется использовать "http" для связи по сети.
  scheme  = "https"
  tls_ca_file   = "/etc/vault.d/consul-ca.crt"
  tls_cert_file = "/etc/vault.d/vault-consul-client.crt"
  tls_key_file  = "/etc/vault.d/vault-consul-client.key"

  # HA: TTL сессии, используемой для захвата лидерства (не меньше 10s на стороне Consul)
  session_ttl = "15s"
  # Максимальный параллелизм запросов к Consul (согласуется с http_max_conns_per_client в Consul)
  max_parallel = "128"

  # Регистрация сервиса в Consul
  service = "vault"
  service_tags = "production,security"
}

# Адреса для координации кластера
api_addr     = "https://vault-node-1.example.com:8200"
cluster_addr = "https://10.0.0.1:8201"
```

### Настройка Service Registration отдельно от Storage

Начиная с версии 1.4, регистрация сервиса может быть вынесена в отдельный блок, что позволяет использовать Raft для хранения, но продолжать использовать Consul для обнаружения сервиса:

```hcl
service_registration "consul" {
  address = "127.0.0.1:8500"
  service = "vault"
}
```

## Дополнительная информация

### Сравнение Consul и Raft

| Параметр | Consul (Legacy) | Raft (Standard) |
| :--- | :--- | :--- |
| **Зависимости** | Требует отдельный кластер Consul | Без внешних зависимостей |
| **Сложность** | Высокая (два кластера для поддержки) | Низкая (один бинарный файл) |
| **Производительность** | Ограничена сетевыми задержками до Consul | Максимальная (локальный диск + сеть Raft) |
| **Диагностика** | Разделена между логами Vault и Consul | Единый лог Vault |

### Миграция с Consul на Raft

Миграция позволяет перевести уже эксплуатируемый кластер с Consul-бэкенда на встроенное хранилище Raft (Integrated Storage) без потери данных. Команда используется: `vault operator migrate`. Миграция выполняется на одном из узлов, который станет лидером Raft-кластера, и требует временной остановки кластера (Vault должен быть офлайн).

> Перед миграцией обязательно создайте снапшот Consul: `consul snapshot save backup.snap` — это резервная копия на случай сбоя процесса.

**Конфигурация миграции (`migrate.hcl`):**
```hcl
storage_source "consul" {
  address = "127.0.0.1:8500"
  path    = "vault/"
}

storage_destination "raft" {
  path    = "/vault/raft/"
  node_id = "node_1"
}

cluster_addr = "https://10.0.0.1:8201"
```

> `storage_source` — текущий бэкенд (Consul), `storage_destination` — целевой (Raft). Значения `path` и `node_id` должны совпадать с конфигурацией серверного файла. Директория `/vault/raft/` должна существовать на хосте — команда не создает её автоматически.

**Команда миграции:**
```bash
vault operator migrate -config=migrate.hcl
# → перекопирует зашифрованные данные из Consul в Raft, не затрагивая секреты (зашифрованная структура сохраняется)
```

После миграции:

1. Запустите новый сервер Vault с конфигурацией на `storage "raft"` и выполните распечатывание (`vault operator unseal`, при необходимости `-migrate` для конверсии seal-структуры).
2. Один узел в Raft-кластере станет лидером — проверьте: `vault operator raft list-peers`.
3. Остальные узлы добавляются через `vault operator raft join <api_addr>`, либо автоматически при использовании `retry_join` в конфигурации Raft.

> В Vault Enterprise с multi-datacenter репликацией (Performance Replication / DR Secondary) рекомендован развёрнутый workflow: создать новый кластер на Raft, подключить его как DR Secondary к существующему основному (Consul), дождаться синхронизации, а затем перевести трафик и остановить старый кластер.

**См. также:**
*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и SLM.
*   **[Обзор Consul](../../Consul/consul_overview.md)** — возможности сервисной сетки, K/V и ACL.
*   **[Руководство по установке](./vault_installation.md)** — настройка Raft (Integrated Storage) и миграция.
