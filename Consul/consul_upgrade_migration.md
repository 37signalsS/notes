# Consul Upgrade и Migration

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x (LTS) / 1.18.x (LTS)

## Определения

**Consul Upgrade** — процесс обновления версии Consul на кластере без потери данных и простоя. Включает обновление бинарных файлов, миграцию формата данных при необходимости, координацию версий Envoy-прокси и валидацию работоспособности после обновления.

**Consul Migration** — процесс переноса данных между кластерами или между форматами хранения (например, с BoltDB на WAL LogStore), а также переход между режимами federation (WAN federation → cluster peering).

**Protocol Compatibility** — гарантия HashiCorp, что каждая версия Consul совместима как минимум с одной предыдущей версией по gossip-протоколу. Это позволяет выполнять rolling upgrade без остановки кластера.

**Backward Incompatible Upgrade** — редкий сценарий, при котором новая версия Consul использует протокол, несовместимый с текущей. Требует 2-фазного обновления с флагом `-protocol=PREVIOUS`.

**Autopilot Upgrade Migration** — функция Consul Enterprise, которая автоматически переводит новые серверы в voters и исключает старые из кворума. При ручном rolling upgrade должна быть отключена (`disable-upgrade-migration=true`), чтобы предотвратить преждевременную выборку нового лидера.

**Snapshot Version** — версия формата снапшота, сохраняемая в поле `Version` внутри файла `.snap`. Восстановление на версию Consul, отличную от версии создания снапшота, не поддерживается.

## Основные концепции

### Принципы обновления

Consul спроектирован как долгоживущий агент, поэтому безопасное обновление является ключевым требованием. Основные гарантии:

- **Backwards compatibility:** По умолчанию Consul автоматически использует совместимый протокол при общении с агентами более старых версий.
- **Rolling upgrade:** Агенты обновляются по одному без остановки кластера.
- **Raft quorum preservation:** Во время обновления серверов кворум Raft должен оставаться доступным (не менее 2 из 3 серверов для 3-серверного кластера).

Для Consul Community Edition рекомендуется не пропускать более 2 major versions за одну операцию. Consul Enterprise LTS-релизы поддерживают прыжок до 3 major versions при обновлении с одного LTS на следующий.

### Совместимость протоколов

| Consul Version | Gossip Protocol | Raft Protocol | Примечание |
| :--- | :--- | :--- | :--- |
| 0.1 - 0.3 | 1 | 1 | Legacy |
| 0.4 | 1, 2 | 1, 2 | |
| 0.5 | 1, 2 | 2 | Серверы 0.5.x нельзя смешивать со старыми |
| 0.6 | 1, 2, 3 | 2, 3 | |
| >= 0.7 | 2, 3 | 3+ | Автоматический upshift при общении с совместимыми агентами |

Проверить поддерживаемые версии протокола:
```bash
consul -v
# → Consul v2.0.3 ... Protocol: 2, 3
```

### Форматы хранения Raft

| Формат | Версия внедрения | Статус | Рекомендация |
| :--- | :--- | :--- | :--- |
| **BoltDB** | До 1.15.0 | Legacy | Миграция на WAL |
| **WAL LogStore** | С 1.15.0 (по умолчанию) | Актуальный | Использовать для новых кластеров |
| **WAL + BoltDB fallback** | 1.15.0+ | Совместимость | Для обратной совместимости при обновлении |

### Enterprise automation

Consul Enterprise предоставляет **Automated Upgrades** через Autopilot. Новые серверы с более высокой версией присоединяются как `non-voters`; Autopilot автоматически повышает их до `voters` и исключает старые узлы.

При **ручном** rolling upgrade в Enterprise необходимо отключить `upgrade_migration`:
```bash
consul operator autopilot set-config -disable-upgrade-migration=true
```

### Миграция лицензии HashiCorp → IBM

Начиная с Consul v1.21, лицензирование перешло от HashiCorp к IBM. Существует два типа лицензий:
- **Standard** — service discovery
- **Premium** — service mesh

Если кластер использует старую лицензию HashiCorp, требуется промежуточный upgrade до Consul Enterprise v1.21.7+ перед применением IBM-лицензии. См. [Consul Enterprise Licensing](./consul_enterprise_licensing.md).

## Практические сценарии

### 1. Подготовка к обновлению

```bash
# 1. Проверка текущей версии
consul version
# → Consul v2.0.3

# 2. Проверка состояния кластера
consul operator raft list-peers
# → все серверы healthy, один leader

# 3. Проверка версии протокола
consul -v
# → Protocol: 2, 3

# 4. Создание снапшота ПЕРЕД обновлением
consul snapshot save /tmp/pre-upgrade-backup-$(date +%Y%m%d).snap
# → Snapshot saved successfully

# 5. Проверка снапшота
consul snapshot inspect /tmp/pre-upgrade-backup-*.snap
# → Size, Index, Version, Timestamp

# 6. Проверка snapshot index
consul operator raft list-peers
# → зафиксируйте last_log_index для последующей валидации
```

### 2. Rolling upgrade серверов (single-DC)

```bash
# На каждом follower-сервере:
# 1. Graceful leave
consul leave

# 2. Замена бинарного файла
cp consul /usr/bin/consul
chmod +x /usr/bin/consul

# 3. Запуск
consul agent -config-dir=/etc/consul.d &

# 4. Валидация rejoining
consul operator raft list-peers
# → узел healthy, leader не изменился
consul info | grep "raft\.last_log_index"
# → должен приближаться к лидеру

# 5. Повторить для всех follower-серверов

# 6. Обновление лидера (последним)
# Лидер автоматически перейдет на уже обновленный follower
consul leave
# ... замена бинарника ...
consul agent -config-dir=/etc/consul.d &
```

### 3. Rolling upgrade клиентов и прокси

```bash
# 1. Graceful leave клиента
consul leave

# 2. Замена бинарника
cp consul /usr/bin/consul

# 3. Запуск
consul agent -config-dir=/etc/consul.d &

# 4. Если используются Envoy sidecars/gateways:
# - Остановить старые Envoy ПЕРЕД остановкой consul client
systemctl stop consul-envoy
# - Запустить consul client с новой версией
systemctl start consul
# - Запустить Envoy совместимой версии (проверить compatibility matrix)
systemctl start consul-envoy

# 5. Валидация
consul members
# → узел alive, версия обновлена
```

### 4. Upgrade в Kubernetes (Helm)

```bash
# 1. Проверка текущей версии
helm get values consul -n consul | grep image

# 2. Обновление values.yaml с новой версией образа
# values.yaml
server:
  image: "hashicorp/consul:2.0.3"
  updatePartition: 3  # количество серверных реплик

# 3. Поэтапное обновление через updatePartition
helm upgrade --install consul hashicorp/consul -f values.yaml \
  --set server.updatePartition=3

# 4. Дождаться готовности
kubectl rollout status statefulset/consul-server -n consul

# 5. Снизить partition на 1
helm upgrade --install consul hashicorp/consul -f values.yaml \
  --set server.updatePartition=2

# 6. Повторить до 0
helm upgrade --install consul hashicorp/consul -f values.yaml \
  --set server.updatePartition=0
```

### 5. Multi-DC WAN federation upgrade

Порядок обновления критичен для WAN-federated environments:

1. **Secondary DC clients** → **Secondary DC servers** → **Primary DC clients** → **Primary DC servers**

```bash
# На primary DC:
# 1. Обновить всех клиентов
# 2. Обновить серверы (followers → leader)

# На secondary DC:
# 1. Обновить всех клиентов
# 2. Обновить серверы (followers → leader)

# Верификация federation после обновления
consul members -wan
# → все узлы в WAN pool alive

# Проверка ACL replication на secondary
curl http://secondary-server:8500/v1/acl/replication
# → {"Enabled": true, "SyncTime": "..."}
```

### 6. Миграция BoltDB → WAL LogStore

```bash
# 1. Проверка текущего бэкенда
consul info | grep raft_logstore
# → raft_logstore.backend: boltdb

# 2. Настройка WAL в server.hcl
raft {
  logstore {
    backend = "wal"
  }
}

# 3. Перезапуск сервера
systemctl restart consul

# 4. Проверка
consul info | grep raft_logstore
# → raft_logstore.backend: wal
```

### 7. Backward incompatible upgrade (2-phase)

Применяется, когда release notes явно указывают на breaking changes в протоколе:

```bash
# Фаза 1: Все агенты на новой версии со старым протоколом
# На каждом узле:
consul leave
consul agent -protocol=PREVIOUS -config-dir=/etc/consul.d &
# где PREVIOUS — версия протокола старой версии Consul (consul -v)

# Фаза 2: Перезапуск без флага -protocol
consul leave
consul agent -config-dir=/etc/consul.d &
# → автоматически поднимется на новый протокол

# Верификация
consul members
# → все узлы с одинаковой, новой версией протокола
```

### 8. Миграция лицензии HashiCorp → IBM (Enterprise)

Если кластер переходит с HashiCorp лицензии на IBM:

```bash
# 1. Upgrade всех серверов до Consul Enterprise v1.21.7+
# 2. Обновить лицензию
consul license set -license-file ibm-license.hcl

# 3. Перезапустить серверы по одному
consul leave
consul agent -config-dir=/etc/consul.d &

# 4. После стабилизации серверов — обновить клиенты
```

## Операции и команды

### Валидация после обновления

```bash
# 1. Версия на всех узлах
consul version
# → Consul v2.0.3

# 2. Raft кворум
consul operator raft list-peers
# → все серверы healthy, один leader

# 3. Стабилизация Raft
watch -n 5 'consul operator raft list-peers'
# → стабильное состояние 1-2 минуты

# 4. Сервисы каталога
consul catalog services
# → полный список сервисов присутствует

# 5. KV-хранилище
consul kv get config/app/db_url
# → значение присутствует

# 6. ACL токены
consul acl token read -self
# → токен валиден

# 7. WAN federation (если применимо)
consul members -wan
# → все ДЦ в Federation

# 8. ACL replication (secondary DC)
curl http://secondary:8500/v1/acl/replication
# → {"Enabled": true}
```

### Откат (Rollback)

```bash
# 1. Остановка обновленного узла
consul leave

# 2. Возврат предыдущего бинарного файла
cp /opt/consul-backup/consul-1.22.3 /usr/bin/consul

# 3. Запуск
consul agent -config-dir=/etc/consul.d &

# 4. Валидация
consul version
# → Consul v1.22.3
consul operator raft list-peers
# → узел healthy

# Внимание: восстановление из снапшота на другую версию не поддерживается.
# Для полного отката используйте снапшот, созданный ДО обновления.
```

## Устранение неполадок

### Обновление не применяется

- **Причина:** Старый бинарный файл в PATH или кэш systemd.
- **Решение:**
  ```bash
  which consul
  # → /usr/bin/consul
  consul version
  # → убедитесь, что версия новая
  hash -r  # сброс кэша bash
  ```

### Leader flapping после обновления

- **Причина:** Autopilot upgrade migration включен в Enterprise; дисковая подсистема не соответствует требованиям.
- **Решение:**
  ```bash
  # Отключить upgrade migration
  consul operator autopilot set-config -disable-upgrade-migration=true

  # Проверить диск
  iostat -x 1 5
  # → await < 10ms
  ```

### Фолловер не rejoins после рестарта

- **Причина:** `commit_index` и `last_log_index` расходятся; узел не успел синхронизировать логи.
- **Решение:**
  ```bash
  # Проверить индексы
  consul info | grep "raft\.\(commit_index\|last_log_index\)"
  # → значения должны совпадать или быть близкими

  # Если расхождение велико — дождаться завершения синхронизации
  watch -n 5 'consul info | grep raft'
  ```

### Данные потеряны после обновления

- **Причина:** Восстановление из снапшота, созданного на другой версии Consul.
- **Решение:** Создавайте снапшот ДО обновления. Восстанавливайтесь только на той же версии, что и при создании снапшота.

### Envoy proxy incompatible после обновления Consul

- **Причина:** Версия Envoy несовместима с новой версией Consul (например, xDS API changes).
- **Решение:** Обновлять Consul и Envoy одновременно. Проверить compatibility matrix перед upgrade.

### Enterprise лицензия не загружается после обновления

- **Причина:** В Consul 1.10+ лицензия должна присутствовать в конфигурации или окружении до старта агента; автоматическое получение от серверов требует ACL и `start_join`/`retry_join`.
- **Решение:**
  ```bash
  # Указать лицензию в конфиге
  license_path = "/etc/consul.d/license.hcl"

  # Или через окружение
  export CONSUL_LICENSE="$(cat license.hcl)"
  ```

## Лучшие практики

- **Снапшот перед обновлением:** Всегда создавайте бэкап перед обновлением. Храните снапшоты версионированно: `consul-<version>-<dc>-<date>.snap`.
- **Тестирование в staging:** Обновляйте staging-кластер, mirroring production, перед production rollout.
- **Последовательность:** Обновляйте по одному узлу за раз; серверы перед клиентами; followers перед leader.
- **Enterprise Autopilot:** При ручном upgrade отключите `upgrade_migration`; при automated upgrades — наоборот, используйте Autopilot.
- **Версия CLI:** Используйте CLI той же версии, что и целевая версия Consul. См. [Consul CLI Reference](./consul_cli_reference.md).
- **Согласованность Envoy:** При использовании Service Mesh обновляйте Consul и Envoy одновременно. См. [Consul Service Mesh](./consul_service_mesh.md).
- **Мониторинг:** Наблюдайте за метриками Raft (`consul.raft.*`) и состоянием peers после обновления.
- **Rollback plan:** Будьте готовы откатиться на предыдущую версию при проблемах. Для полного отката используйте снапшот, созданный ДО обновления.
- **Версионное соответствие:** В Kubernetes используйте `consul-k8s` версии, совместимой с целевой версией Consul. См. compatibility matrix.

## Граничные случаи

- **Enterprise → OSS:** Миграция требует ручного удаления Enterprise-only config entries (namespaces, admin partitions, network areas). Enterprise снапшоты несовместимы с OSS. См. [Consul Enterprise Licensing](./consul_enterprise_licensing.md).
- **Major version jump >2:** При переходе с 1.x на 2.x проверьте release notes на deprecated параметры и breaking changes. Используйте промежуточные версии при необходимости.
- **WAN Federation → Cluster Peering:** Для новых развертываний рекомендуется Cluster Peering. Для миграции существующих WAN-federated environments см. [Migrating from WAN to Peering](https://developer.hashicorp.com/consul/docs/upgrade-specific/migrate-wan-federation-to-peering).
- **LTS upgrade path:** Consul Enterprise LTS поддерживает прыжок до 3 major versions. Например, 1.15.x LTS → 1.18.x LTS → 1.21.x LTS.
- **IBM license migration:** При переходе с HashiCorp на IBM лицензии требуется промежуточный upgrade до v1.21.7+. См. [Consul Enterprise Licensing](./consul_enterprise_licensing.md).
- **Catalog v2:** В Consul 1.22+ каталог перешел на Catalog v2. При обновлении убедитесь, что все клиенты поддерживают новую схему. См. [Consul Service Catalog](./consul_service_catalog.md).
- **Large clusters (>5000 узлов):** Обновляйте клиентов группами (batch) для избежания шторма регистрации. Увеличьте `reconnect_timeout` на время upgrade.
- **Service Mesh с Nomad:** Consul 1.14 изменил дефолты `connect.enabled` и `peering.enabled`. При использовании Nomad 1.4.3 и ранее отложите upgrade до исправлений в Nomad.
- **Snapshot compatibility:** Снапшоты можно восстановить только на той же версии Consul. Для кросс-версионной миграции используйте export/import через HTTP API или `consul migrate` для отдельных data formats.

## Дополнительная информация

- **[General Upgrade Process](https://developer.hashicorp.com/consul/docs/upgrade/instructions/general)** — базовый процесс обновления, подготовка, Autopilot.
- **[Upgrade Consul](https://developer.hashicorp.com/consul/docs/upgrade)** — общий гайд, backward incompatible upgrades, protocol versions.
- **[Upgrade Instructions](https://developer.hashicorp.com/consul/docs/upgrade/instructions)** — версионные зависимости, максимальный прыжок версий.
- **[Protocol Compatibility](https://developer.hashicorp.com/consul/docs/upgrade/compatibility)** — таблица совместимости gossip и Raft протоколов.
- **[Upgrade WAN-federated datacenters](https://developer.hashicorp.com/consul/docs/upgrade/federated)** — upgrade для multi-DC WAN federation.
- **[Long Term Support (LTS)](https://developer.hashicorp.com/consul/docs/upgrade/lts)** — жизненный цикл LTS релизов, окно совместимости.
- **[Migrating from WAN to Peering](https://developer.hashicorp.com/consul/docs/upgrade-specific/migrate-wan-federation-to-peering)** — миграция с WAN federation на cluster peering.
- **[Consul Disaster Recovery](./consul-disaster-recovery.md)** — снапшоты, восстановление, бэкапы.
- **[Consul Deployment](./consul_deployment.md)** — базовое развертывание, rolling update в деталях.
- **[Consul Enterprise Licensing](./consul_enterprise_licensing.md)** — лицензии, IBM migration, Enterprise → OSS.
- **[Consul Service Mesh](./consul_service_mesh.md)** — координация версий Envoy при upgrade.
- **[Consul WAN vs Peering](./consul_wan_vs_peering.md)** — сравнение federation моделей.
- **[Consul CLI Reference](./consul_cli_reference.md)** — справочник CLI команд для валидации.
- **[Consul Consensus](./consul_consensus.md)** — Raft протокол, кворум, выборы.
