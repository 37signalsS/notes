# HashiCorp Nomad: Дополнительная информация

## Версии и поддержка

| Версия | Дата выпуска | Статус |
| :--- | :--- | :--- |
| **v1.11.2** | Февраль 2026 | **Latest** |
| v1.10.8 | Февраль 2026 | Поддерживаемая |
| v1.8.20 | Февраль 2026 | LTS |
| v1.7.x и ранее | — | Устаревшие |

**Ключевые нововведения v1.11.x:**

- **Client Identity:** Автоматическая генерация и ротация идентичностей клиентов
- **Deployments для system jobs:** Поддержка развёртываний для системных задач
- **Secrets Block:** Новый блок `secret` для получения секретов из Vault
- **GPU Fingerprinting:** Улучшенное обнаружение GPU, FPGA, TPU
- **Sentinel:** Новый `nomad_var` built-in для переменных

**Enterprise-версии:** С апреля 2026 HashiCorp меняет модель выпуска enterprise-версий — [подробности](https://support.hashicorp.com/hc/en-us/articles/48015293517203)

---

## Production Adoption

**Компании в production:** PagerDuty, Target, Citadel, Trivago, SAP, Pandora, Roblox, eBay, Deluxe Entertainment

---

## Когда выбирать Nomad

| Критерий | Nomad | Kubernetes |
| :--- | :--- | :--- |
| **Workload'ы** | Микс контейнеров и legacy (Windows, Java, VM) | Только контейнеры |
| **Команда** | Малые/средние, ограниченные ресурсы на поддержку | Крупные, выделенная SRE-команда |
| **Среда** | On-premises или гибридная | Преимущественно cloud |
| **Приложения** | Существующие core-приложения + новые | Cloud-native greenfield |
| **Приоритет** | Простота и скорость внедрения | Полнота функциональности |
| **Бюджет** | Ограниченный | Значительный |

**Тренд 2025–2026:** Сосуществование обоих оркестраторов в крупных предприятиях (Intel, Autodesk, GitHub).

---

## Полезные ресурсы

- [Официальная документация](https://developer.hashicorp.com/nomad/docs)
- [Сравнение Nomad и Kubernetes](https://developer.hashicorp.com/nomad/docs/nomad-vs-kubernetes)
- [A Kubernetes User's Guide to HashiCorp Nomad](https://developer.hashicorp.com/nomad/tutorials/enterprise/kubernetes-to-nomad)
- [The Kubernetes to Nomad Cheat Sheet](https://developer.hashicorp.com/nomad/tutorials/enterprise/kubernetes-to-nomad-cheat-sheet)
- [GitHub Releases](https://github.com/hashicorp/nomad/releases)

---

## Связанные концепты

- **Оркестрация контейнеров** — общие принципы (см. [`kubernetes_overview.md`](../Kubernetes/kubernetes_overview.md), [`docker_swarm_overview.md`](../Docker_swarm/docker_swarm_overview.md))
- **[Edge computing](../Concepts/edge_computing_overview.md)** — периферийные вычисления
- **[Service Mesh](../Service_Mesh/service_mesh_concepts.md)** — Consul Connect
- **[High Availability](../Concepts/High_Availability/ha_overview.md)** — отказоустойчивость кластеров

---

## Ссылки на связанные файлы

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Практические сценарии](./practical_scenarios.md) — развёртывание приложений
