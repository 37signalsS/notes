# Обзор Consul

**Актуально для:** Consul 1.22.x / 1.20.x / 1.19.x

## Определения

**Consul** — платформа от HashiCorp для обнаружения сервисов, динамической конфигурации и управления доступом в распределённой инфраструктуре. В рамках **CAP-теоремы** Consul является **CP-системой**: он отдаёт приоритет строгой согласованности и устойчивости к разделению сети за счёт консенсуса **Raft** на серверных узлах.

В отличие от etcd или Zookeeper, Consul специализируется на **Service Networking**: предоставляет DNS-интерфейс, health checks, сервисную сетку, KV и ACL из единого стека. Начиная с Consul 1.14+, платформа эволюционировала к архитектуре **Dataplane-first**, где Consul Dataplane заменяет клиентских агентов в оркестраторах, а Envoy подключается к серверам по **gRPC (порт 8502)**.

## Основные концепции

### CAP и модель согласованности

Consul оптимизируется для сценариев, где важнее правильный ответ, чем быстрый:
- **Серверы** участвуют в Raft-кворуме и хранят авторитетное состояние.
- **Агенты/Dataplane** обеспечивают локальный кэш, anti-entropy и health checks.
- При потере кворума запись невозможна; только `stale` чтения продолжают работать.

### Архитектура и режимы работы

- **Modern (Dataplane):** Consul Dataplane — легковесный компонент, управляющий Envoy без клиентских агентов. Снижает потребление памяти и Gossip-трафик в Kubernetes, ECS и на выделенных серверах.
- **Legacy (Agent-based):** Классическая модель с серверами, клиентами и Gossip Protocol (Serf) для обнаружения сбоев.

### Субсистемы платформы

- **[Архитектура Consul](./consul_architecture.md):** Control Plane, Data Plane, порты, TLS, кэширование агента.
- **[Каталог служб (Service Catalog)](./consul_service_catalog.md):** Реестр экземпляров. Consul 1.22+ добавляет **Catalog v2** с абстракцией **Workload** и **Multi-port services** (HTTP/gRPC/metrics под одним сервисом).
- **[Consul API Gateway](./consul-api-gateway.md):** Управление внешним трафиком (North-South) на базе **Kubernetes Gateway API**. Заменяет Ingress Gateway.
- **[Проверки состояния (Health Checking)](./consul_health_checks.md):** Мониторинг HTTP, TCP, gRPC, TTL, Script, Docker, OSService. Стриминг anti-entropy с v1.20+ снижает нагрузку на серверы.
- **[KV-хранилище (Key/Value Store)](./consul_kv_store.md):** Иерархическое хранилище для конфигурации и координации лидеров.
- **[Сервисная сетка (Consul Service Mesh)](./consul_service_mesh.md):** mTLS, прозрачный прокси (Transparent Proxy), intentions, discovery chain.
- **[Система управления доступом (ACL)](./consul_acl.md):** Default Deny, токены, роли, внешние методы аутентификации.
- **[Raft-консенсус](./consul_consensus.md):** Жизненный цикл терминов, WAL, FSM, Autopilot, learners.

### Мультикластерность и отказоустойчивость

- **Cluster Peering (GA):** Соединение независимых кластеров без общей корневой CA. В отличие от WAN-федерации, не реплицирует глобальное состояние ACL и KV.
- **Sameness Groups:** Логическое объединение идентичных сервисов в разных partitions/peers для автоматического failover.
- **Mesh Gateways:** Шифрование и маршрутизация межкластерного трафика.

## Предварительные требования

- Рабочий кластер Consul: 3 или 5 серверов для HA, кворум `(N/2)+1`.
- Шифрование: Gossip ключ (`encrypt`), TLS для HTTP/HTTPS/gRPC.
- ACL включены с `default_policy = "deny"` и распределёнными токенами.
- Time synchronization (NTP/Chrony) на всех узлах; Raft зависит от согласованных часов.
- Достаточные ресурсы: CPU и диск для Raft/WAL, память для кэширования агента.
- Резервное копирование: снапшоты через `consul snapshot save` или snapshot agent (Enterprise).

## Практические сценарии

### Динамическое обнаружение и балансировка

1. **Регистрация:** Приложение передаёт агенту IP, порт, теги.
2. **Проверка:** Consul опрашивает `/health`.
3. **Обнаружение:** Другие сервисы запрашивают `api.service.consul` через DNS.
4. **Балансировка:** Возвращаются только `passing` экземпляры.

```bash
# Регистрация сервиса
curl -X PUT -d '{"ID":"web-1","Name":"web","Port":8080,"Tags":["prod"],"Check":{"HTTP":"http://localhost:8080/health","Interval":"10s"}}' http://127.0.0.1:8500/v1/agent/service/register

# DNS-обнаружение
dig @127.0.0.1 -p 8600 web.service.consul A +short
```

### Локальное окружение (Dev Mode)

```bash
consul agent -dev -ui
consul members
```

### Управление конфигурацией

Consul KV + `consul-template` или watches API:

```bash
consul kv put config/app/db_url postgres://app:pass@db:5432/app
consul-template -consul-addr 127.0.0.1:8500 -template "app.conf.ctmpl:app.conf" -once
```

### Мультикластерность

1. Обмен peering токеном между кластерами.
2. Создание Sameness Group для критичного сервиса.
3. Настройка exported services и intentions.

### NIaC

- **Consul-Terraform-Sync:** Автоматический запуск Terraform при изменении каталога.
- **Terraform Provider:** ACL, KV, intentions в виде кода.

## Лучшие практики

- **HA:** 3 или 5 серверов; больше замедляет Raft.
- **Шифрование:** Gossip + TLS для всех интерфейсов.
- **ACL:** Default Deny, короткоживущие токены, Vault для динамической выдачи.
- **Кэширование:** `use_cache: true` на агентах; `?cached` для приложений.
- **Наблюдаемость:** Telemetry в Prometheus, алерты на Raft/Gossip/Autopilot.
- **Бэкапы:** Регулярные снапшоты, DR план с восстановлением кворума.
- **Dataplane:** Используйте Dataplane в оркестраторах; для Vault нужны классические агенты.

## Граничные случаи

- **Dev Mode:** Нет шифрования, ACL, persistence. Только для разработки.
- **Cluster Peering:** Не реплицирует ACL/KV; используйте exported services и intentions.
- **Dataplane:** Vault требует классических агентов; Catalog v2 потребует обновления ACL и discovery цепочек.
- **Multi-DC:** Нет встроенной репликации KV; используйте Consul Replicate или экспорт/импорт.
- **Анонимный доступ:** При ACL без явной настройки анонимного токена все неаутентифицированные запросы отклоняются.

## Устранение неполадок

- **Потеря кворума:** Проверьте кворум `(N/2)+1`, learner/non-voter статус, Autopilot.
- **Сетевое разделение:** `stale` чтения работают; `consistent`/`default` возвращают ошибку.
- **Перевыборы Raft:** Проверьте `consul_raft_leader_lastContact > 200ms`, `MaxTrailingLogs`, CPU/дисковую подсистему.
- **CAS Conflict:** Retry с exponential backoff, актуальный `ModifyIndex`.
- **Истечение сессии:** Увеличьте TTL или добавьте renew.

## Дополнительная информация

- **[Архитектура Consul](./consul_architecture.md):** порты, роли, кэширование.
- **[Raft-консенсус](./consul_consensus.md):** репликация, WAL, FSM, Autopilot.
- **[Service Catalog](./consul_service_catalog.md):** Catalog v2, multi-port.
- **[Health Checks](./consul_health_checks.md):** типы, thresholds, anti-entropy.
- **[KV Store](./consul_kv_store.md):** CAS, транзакции, блокировки.
- **[Service Mesh](./consul_service_mesh.md):** intentions, discovery chain, прозрачный прокси.
- **[ACL](./consul_acl.md):** политики, токены, bootstrap.
- **[Consul Deployment](./consul-deployment.md):** продуктовый кластер, шифрование, systemd.
- **[Disaster Recovery](./consul-disaster-recovery.md):** снапшоты, восстановление.
- **[Enterprise лицензирование](./consul_enterprise_licensing.md):** сравнение OSS и Enterprise функций.
- **[WAN Federation vs Cluster Peering](./consul_wan_vs_peering.md):** детальное сравнение мульти-DC подходов.
- **[Consul Replicate](./consul-replicate.md):** репликация KV между дата-центрами в OSS.
- **[Consul ESM](./consul_esm.md):** мониторинг внешних сервисов (Enterprise).
- **[Consul Audit Logging](./consul_audit_logging.md):** аудит операций для compliance.
- **[Consul Telemetry](./consul_telemetry.md):** метрики, интеграция с Prometheus/StatsD.
- **[Consul Config Entries Lifecycle](./consul_config_entries_lifecycle.md):** управление конфигурацией как кодом.
- **[Consul CLI Reference](./consul_cli_reference.md):** продвинутое использование CLI.
- **[Consul Network Segments](./consul_network_segments.md):** разбиение gossip-пула для больших кластеров.
- **[Consul DNS Caching Strategies](./consul_dns_caching.md):** стратегии кэширования DNS.
- **[Consul Rate Limiting и Quotas](./consul_rate_limiting.md):** защита API и Service Mesh.
- **[Consul UI Administration](./consul_ui_administration.md):** администрирование через веб-интерфейс.
- **[Consul Backup Verification](./consul_backup_verification.md):** методика проверки бэкапов.
- **[Официальная документация](https://developer.hashicorp.com/consul/docs):** архитектура, релизы, гайды.
- **[Consul GitHub](https://github.com/hashicorp/consul):** исходный код и issues.
