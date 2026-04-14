# Red Hat OpenShift

## Definitions

**Red Hat OpenShift** — коммерческий дистрибутив Kubernetes от Red Hat (подразделение IBM). Представляет собой платформу класса PaaS с расширенными инструментами разработки, усиленной безопасностью и коммерческой поддержкой. Является надстройкой над «ванильным» Kubernetes, добавляя готовые компоненты и ужесточая политики безопасности.

**OKD (Origin Kubernetes Distribution)** — community-версия OpenShift с открытым исходным кодом. Содержит те же компоненты, но без коммерческой поддержки и брендинга Red Hat. Основа для всех редакций OpenShift.

## Basic Concepts

### Ключевые отличия от «ванильного» Kubernetes

| Параметр | OpenShift | Kubernetes (vanilla) |
| :--- | :--- | :--- |
| **Безопасность** | SCC (Security Context Constraints) по умолчанию запрещают запуск от `root`; усиленные политики | PSS/PSP (Pod Security Standards); запуск от `root` разрешён по умолчанию |
| **CLI** | `oc` — расширенный клиент с командами `oc new-app`, `oc start-build` и др. | `kubectl` — базовый клиент |
| **Web UI** | Встроенная консоль «из коробки» с мониторингом, каталогом разработчика, топологией | Требует отдельной установки; Kubernetes Dashboard архивирован, рекомендуется [Headlamp](https://headlamp.dev/) |
| **CI/CD** | Встроенные OpenShift Pipelines (Tekton), интеграция с Jenkins | Сторонние инструменты (ArgoCD, Jenkins, Tekton, GitLab CI) |
| **Сборка образов** | Source-to-Image (S2I) — автоматическая сборка из исходного кода | Сторонние решения (Kaniko, Buildpacks, Dockerfile) |
| **Реестр образов** | Встроенный Image Registry | Внешние реестры (Docker Hub, Harbor, GHCR) |
| **CNI** | OVN-Kubernetes (дефолт с 4.12); OpenShiftSDN удалён в 4.15 | Любой CNI-совместимый плагин (Calico, Cilium, Flannel) |
| **Операторы** | OLM (Operator Lifecycle Manager) — каталог и управление операторами «из коробки» | OLM устанавливается отдельно |
| **ОС нод** | RHEL, RHCOS (Red Hat CoreOS) — управляемые обновления | Любой Linux |
| **Поддержка** | Коммерческая от Red Hat с SLA | Сторонние вендоры или community |

### Архитектура и дополнительные компоненты

OpenShift добавляет поверх Kubernetes:

- **RHCOS (Red Hat CoreOS)** — неизменяемая ОС для worker-нод с автоматическими атомарными обновлениями через Machine Config Operator.
- **OLM (Operator Lifecycle Manager)** — каталог, установка и управление жизненным циклом операторов.
- **Routes** — аналог Ingress, но с собственной абстракцией маршрутизации (на базе HAProxy).
- **Builds / S2I** — встроенный механизм сборки образов из исходного кода.
- **Image Streams** — абстракция над контейнерными образами, позволяющая отслеживать теги и триггерить обновления.
- **Projects** — расширенные Namespace с RBAC, квотами и сетевыми политиками.

### Редакции OpenShift

| Редакция | Назначение |
| :--- | :--- |
| **OpenShift Container Platform (OCP)** | On-premise / private cloud — полная платформа для развёртывания в ЦОД |
| **Azure Red Hat OpenShift (ARO)** | Управляемый сервис на Azure — Red Hat и Microsoft совместно управляют Control Plane |
| **Red Hat OpenShift Service on AWS (ROSA)** | Управляемый сервис на AWS — аналогичная модель с AWS |
| **IBM Cloud OpenShift** | Развёртывание на инфраструкме IBM Cloud |
| **OKD** | Community-версия — бесплатна, без коммерческой поддержки |

### Требования к ресурсам

Минимальные требования для OCP 4.x существенно выше, чем у vanilla Kubernetes:

- **Control Plane:** минимум 3 узла по 4 vCPU / 16 GB RAM
- **Worker Nodes:** минимум 2 узла по 4 vCPU / 8 GB RAM
- **Итого:** кластер из 5+ нод, ~50 GB+ дискового пространства на узел

## Practical Scenarios

### Когда выбирать OpenShift

| Сценарий | Обоснование |
| :--- | :--- |
| Enterprise с требованиями compliance и безопасности | SCC по умолчанию, встроенный аудит, сертифицированная платформа |
| Команды, нуждающиеся в PaaS «под ключ» | Разработчики работают с UI/CLI, эксплуатация — через операторы |
| Регулярные CI/CD без настройки инфраструктуры | S2I, Tekton, встроенный реестр — минимум конфигурации |
| Гибридные / мультиоблачные развёртывания | Единая платформа на AWS, Azure, on-premise с одинаковым API |
| Необходимость коммерческой поддержки с SLA | Поддержка Red Hat с гарантированным временем реакции |

### Когда OpenShift может быть избыточен

| Сценарий | Альтернатива |
| :--- | :--- |
| Стартап / небольшая команда | Vanilla K8s (kubeadm, k3s) + сторонние инструменты |
| Ограниченный бюджет на лицензии | OKD (community-версия) или vanilla Kubernetes |
| Потребность в максимальной гибкости CNI, runtime | Vanilla K8s —自由选择 любой компонент |
| Простые Stateless-приложения | Managed K8s (GKE, EKS, AKS) — меньше оверхед |

### Миграция с Kubernetes на OpenShift

- **Совместимость:** OpenShift полностью совместим с API Kubernetes — манифесты YAML/ Helm работают без изменений (за исключением SCC и специфичных ресурсов).
- **Ограничения:** Некоторые манифесты требуют адаптации под SCC (например, запуск от `root` требует `anyuid` SCC).
- **Ingress → Route:** Стандартные Ingress-объекты работают, но для расширенной маршрутизации используются Routes.

## Additional Information

### Связанные темы

- Обзор Kubernetes: [kubernetes_overview.md](./kubernetes_overview.md)
- Установка HA-кластера: [k8s_ha_cluster_overview.md](./Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- Альтернативные container runtime: [alternative_runtimes](../Docker/alternative_runtimes_and_tools.md)

### Полезные ресурсы

- [Официальная документация OpenShift](https://docs.openshift.com/)
- [OKD — community-версия](https://www.okd.io/)
- [Что нового в OpenShift 4.21](https://developers.redhat.com/articles/2026/02/03/whats-new-developers-openshift-4-21)
