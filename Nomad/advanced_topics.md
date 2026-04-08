# HashiCorp Nomad: Дополнительная информация

## Definitions

**LTS (Long-Term Support)** — версия с расширенным периодом поддержки (обычно 12+ месяцев), рекомендуется для production.

**Enterprise-версия** — коммерческая версия HashiCorp с дополнительными функциями (Sentinel, SSO, приоритизация workload'ов) и изменённой моделью лицензирования.

---

## Basic Concepts

### Версии и поддержка

| Версия | Дата выпуска | Статус |
| :--- | :--- | :--- |
| **v1.11.3** | Март 2026 | **Latest** |
| v1.10.9 | Март 2026 | Поддерживаемая |
| v1.8.21 | Март 2026 | LTS |
| v1.7.x и ранее | — | Устаревшие |

**Ключевые нововведения v1.11.x:**

- **Client Identity** — автоматическая генерация и ротация идентичностей клиентов
- **Deployments for system jobs** — поддержка развёртываний для системных задач
- **Secrets Block** — новый блок `secret` для получения секретов из Vault
- **GPU Fingerprinting** — улучшенное обнаружение GPU, FPGA, TPU
- **Sentinel** — новый `nomad_var` built-in для переменных

**Лицензирование:** с апреля 2026 HashiCorp изменила модель выпуска enterprise-версий — [подробности](https://support.hashicorp.com/hc/en-us/articles/48015293517203).

### Production Adoption

**Компании в production:** PagerDuty, Target, Citadel, Trivago, SAP, Pandora, Roblox, eBay, Deluxe Entertainment.

---

## Practical Scenarios

### Выбор между Nomad и Kubernetes

Дополнение к [сравнительной таблице](./definitions_and_concepts.md) — критерии выбора:

| Критерий | Nomad | Kubernetes |
| :--- | :--- | :--- |
| **Workload'ы** | Микс контейнеров и legacy (Windows, Java, VM) | Только контейнеры |
| **Команда** | Малые/средние, ограниченные ресурсы | Крупные, выделенная SRE-команда |
| **Среда** | On-premises или гибридная | Преимущественно cloud |
| **Приложения** | Существующие core + новые | Cloud-native greenfield |
| **Приоритет** | Простота и скорость внедрения | Полнота функциональности |
| **Бюджет** | Ограниченный | Значительный |

**Тренд 2025–2026:** сосуществование обоих оркестраторов в крупных предприятиях (Intel, Autodesk, GitHub).

---

## Additional Information

Полезные ресурсы: [официальная документация](https://developer.hashicorp.com/nomad/docs), [сравнение Nomad/Kubernetes](https://developer.hashicorp.com/nomad/docs/nomad-vs-kubernetes), [руководство для K8s-пользователей](https://developer.hashicorp.com/nomad/tutorials/enterprise/kubernetes-to-nomad), [cheat sheet](https://developer.hashicorp.com/nomad/tutorials/enterprise/kubernetes-to-nomad-cheat-sheet), [GitHub Releases](https://github.com/hashicorp/nomad/releases).

Базовые определения: [definitions_and_concepts.md](./definitions_and_concepts.md).
Практические сценарии: [practical_scenarios.md](./practical_scenarios.md).
