# Обзор Red Hat OpenShift

## Определение

**Red Hat OpenShift** — коммерческий дистрибутив Kubernetes корпоративного уровня от Red Hat (подразделение IBM). Представляет собой платформу класса PaaS (Platform as a Service) с интегрированными инструментами жизненного цикла разработки (DevSecOps), усиленной безопасностью и долгосрочной коммерческой поддержкой. Является глубокой надстройкой над «ванильным» Kubernetes, автоматизирующей эксплуатацию кластера через концепцию операторов.

**OKD (Origin Kubernetes Distribution)** — community-версия OpenShift с открытым исходным кодом. Служит upstream-проектом для всех коммерческих редакций OpenShift, содержит те же технологии, но без официальной поддержки и сертификации Red Hat.

## Основные концепции

### Ключевые отличия от ванильного Kubernetes

| Параметр | OpenShift | Kubernetes (vanilla) |
| :--- | :--- | :--- |
| **Безопасность** | SCC (Security Context Constraints) — строгие политики по умолчанию (запрет root) | PSS (Pod Security Standards) — требует ручной настройки |
| **Runtime** | CRI-O (единственный поддерживаемый) | containerd / CRI-O / Docker (через адаптеры) |
| **CLI** | `oc` — надмножество над `kubectl` с командами для сборки и деплоя | `kubectl` — базовое управление ресурсами |
| **Web UI** | Полнофункциональная консоль (Администрирование + Developer Topology) | Требует отдельной установки (Dashboard, Headlamp) |
| **CI / CD** | Встроенные OpenShift Pipelines (Tekton) и GitOps (ArgoCD) | Требует самостоятельной интеграции сторонних инструментов |
| **Виртуализация** | OpenShift Virtualization (на базе KubeVirt) — запуск VM рядом с контейнерами | Требует отдельной установки и настройки KubeVirt |
| **CNI** | OVN-Kubernetes (стандарт); поддержка User Defined Networks (UDN) с 4.18 | Любой совместимый плагин (Calico, Cilium, Flannel) |
| **Обновления** | Over-the-Air (OTA) — полностью автоматизированы через Machine Config Operator | Ручное или полуавтоматическое обновление компонентов |

### Архитектура и дополнительные компоненты

OpenShift расширяет возможности Kubernetes за счёт следующих компонентов:

- **RHCOS (Red Hat CoreOS)** — специализированная неизменяемая ОС на базе RHEL, управляемая кластером как ресурс.
- **OLM (Operator Lifecycle Manager)** — центральный механизм управления жизненным циклом операторов. В версии 4.18 представлен OLM v1 с декларативным API.
- **Routes** — встроенная альтернатива Ingress на базе HAProxy, поддерживающая Reencrypt и Edge терминацию из коробки.
- **Image Streams** — абстракция для управления образами, позволяющая автоматически запускать деплой при обновлении тега в реестре.
- **Hosted Control Planes (HCP)** — архитектура, позволяющая запускать Control Plane одного кластера как нагрузку (pod) в другом кластере для экономии ресурсов.
- **OpenShift Lightspeed** — виртуальный помощник на базе Generative AI для упрощения поиска неисправностей и администрирования.

### Редакции OpenShift

| Редакция | Среда развёртывания |
| :--- | :--- |
| **OpenShift Container Platform (OCP)** | On-premise (Bare Metal, vSphere) и частные облака |
| **Red Hat OpenShift Service on AWS (ROSA)** | Управляемый сервис в AWS, интегрированный в биллинг AWS |
| **Azure Red Hat OpenShift (ARO)** | Управляемый сервис, совместно поддерживаемый Microsoft и Red Hat |
| **OpenShift Dedicated** | Управляемый кластер в облаках AWS/GCP, администрируемый Red Hat |

### Требования к ресурсам

OpenShift потребляет значительно больше ресурсов, чем минимальный Kubernetes, из-за большого количества встроенных операторов (Monitoring, Logging, Registry):

- **Control Plane (3 узла):** минимум 4 vCPU / 16 GB RAM на каждый узел.
- **Worker Nodes:** минимум 2 узла по 2 vCPU / 8 GB RAM (рекомендуется 4 vCPU / 16 GB для промышленного использования).
- **Диск:** минимум 100 GB на узел с высокой производительностью IOPS (особенно для etcd).

## Практические сценарии

### Когда выбирать OpenShift

| Сценарий | Обоснование |
| :--- | :--- |
| Миграция с VMware | OpenShift Virtualization позволяет перенести VM в K8s без потери производительности |
| Строгие требования ИБ (PCI DSS, HIPAA) | SCC, шифрование etcd и FIPS-режим доступны из коробки |
| Enterprise-стандарт | Единая платформа для всех облаков и on-premise с гарантией поддержки |
| Команды без глубокой экспертизы в K8s | PaaS-инструменты (S2I, встроенный CI) ускоряют Time-to-Market |

### Когда OpenShift может быть избыточен

| Сценарий | Альтернатива |
| :--- | :--- |
| Малые проекты и стартапы | Managed K8s (GKE, EKS) или легкие дистрибутивы (k3s) |
| Экстремальная кастомизация компонентов | Vanilla Kubernetes (позволяет заменить любой компонент) |
| Ограниченные аппаратные ресурсы | Edge-дистрибутивы (MicroShift) или чистый K8s |

## Дополнительная информация

### Ссылки

- [Официальная документация Red Hat OpenShift](https://docs.openshift.com/)
- [OKD Project — upstream-версия](https://www.okd.io/)
- [Интерактивные лаборатории OpenShift](https://developers.redhat.com/courses/openshift)

### См. также

- [Kubernetes — обзор](./kubernetes_overview.md)
- [HA-кластер — обзор установки](./Installation/HA_Cluster_Bare_Metal/k8s_ha_cluster_overview.md)
- [Docker — альтернативные рантаймы](../Docker/alternative_runtimes_and_tools.md)
