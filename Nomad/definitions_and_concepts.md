# HashiCorp Nomad: Определения и базовые концепции

## Definitions

**Nomad** — легковесный оркестратор от HashiCorp для планирования (scheduling) и запуска приложений (workloads). В отличие от Kubernetes — комплексной платформы «всё в одном» — Nomad придерживается философии UNIX: одна задача, но выполненная хорошо.

**Ключевая особенность:** единый бинарный файл без внешних зависимостей; поддерживает контейнеры, бинарные приложения, Java, QEMU/VM и иные типы workload'ов.

**Актуальная версия:** v1.11.3 (март 2026) — [официальная документация](https://developer.hashicorp.com/nomad/docs)

---

## Basic Concepts

### Архитектура

Два типа агентов в одном бинарном файле:

| Компонент | Назначение |
| :--- | :--- |
| **Server** | Управление кластером, хранение состояния, планирование |
| **Client** | Запуск задач, отчёт о ресурсах, взаимодействие с runtime |

**Режимы развёртывания:**

- **Standalone** — один сервер (dev/test)
- **High Availability** — 3–5 серверов (production, консенсус Raft)

### Ключевые характеристики

| Характеристика | Описание |
| :--- | :--- |
| **Простота** | Один бинарный файл, тривиальная установка |
| **Гибкость workload'ов** | Docker, Podman, exec, Java, QEMU/VM, raw_exec |
| **Масштабируемость** | До 10 000+ узлов в production |
| **Мульти-регион** | Нативная федерация кластеров |
| **Гибридность** | Единый workflow для on-prem, cloud, edge |
| **Лицензия** | Open source (BSL → MPL) |

### Интеграция с экосистемой HashiCorp

- **[Consul](../Consul/consul_overview.md):** service discovery, health checking, service mesh
- **[Vault](../Vault/overview.md):** управление секретами, динамические credentials
- **[Terraform](https://developer.hashicorp.com/terraform):** provisioning инфраструктуры
- **Boundary:** безопасный доступ к workload'ам (через Consul)

### Сравнение с другими оркестраторами

| Критерий | **Nomad** | **[Kubernetes](../Kubernetes/kubernetes_overview.md)** | **[Docker Swarm](../Docker_swarm/docker_swarm_overview.md)** |
| :--- | :--- | :--- | :--- |
| **Архитектура** | Единый бинарник, нет внешних зависимостей | 12+ компонентов, требует etcd | Встроен в Docker Engine |
| **Workload'ы** | Контейнеры + legacy (Windows, Java, VM) | Только Linux-контейнеры | Только Docker-контейнеры |
| **Масштабируемость** | До 10 000+ узлов | До 5 000 узлов | До ~1 000 узлов |
| **Сложность** | Минимальная | Высокая операционная сложность | Низкая |
| **Мульти-регион** | Нативная федерация | Ограниченная, высокая сложность | Отсутствует |
| **Service Discovery** | Через Consul | Встроенный (CoreDNS, Services) | Встроенный (Routing Mesh) |
| **Secrets Management** | Через Vault | Встроенный + External | Встроенный (Secrets) |
| **GPU / AI / ML** | Встроенная поддержка | Через Device Plugins | Ограниченная |
| **Сообщество** | Нишевое, растущее | Доминирующее, enterprise-стандарт | Угасающее |

### Преимущества

- Простота установки и эксплуатации
- Фокус на оркестрации — эффективное планирование и запуск нагрузок
- Гибридные workload'ы: микс контейнеров и legacy-приложений в одном кластере
- Малые команды: меньше ресурсов на поддержку vs Kubernetes
- Edge computing: легковесность для периферийных устройств

### Недостатки

- Требует Consul (service discovery) и Vault (secrets) для полноценной работы
- Меньшая экосистема и community tools vs Kubernetes
- Нишевое решение: сложнее найти специалистов
- Не оптимален для cloud-native greenfield (предпочтителен Kubernetes)

---

## Practical Scenarios

Практические сценарии развёртывания: [practical_scenarios.md](./practical_scenarios.md) — микросервисы, batch jobs, QEMU/VM, GPU/AI, edge computing, мульти-регион федерация.

---

## Additional Information

Версии, production adoption, выбор между Nomad и Kubernetes: [advanced_topics.md](./advanced_topics.md).
