# Rancher: Обзор платформы

## Определения

**Rancher** — открытая платформа мультикластерного управления Kubernetes (MCM), обеспечивающая единый интерфейс (Control Plane) для эксплуатации кластеров в гибридных и мультиоблачных средах. На 2026 год является центральным узлом экосистемы SUSE для управления контейнеризированными нагрузками.

**Rancher Manager (Rancher Server)** — управляющий компонент (Management Plane), работающий как набор контейнеров в выделенном Kubernetes-кластере (Local). Обеспечивает Web UI, REST API `/v3` (и новое публичное API на базе `ext.cattle.io`), аутентификацию, авторизацию и проксирование запросов к downstream-кластерам.

**MCM (Multi-Cluster Management)** — концепция централизованного управления жизненным циклом (провижининг, обновление, масштабирование) неограниченного количества кластеров из одной точки.

**Cluster API (CAPI)** — базовый механизм Rancher (начиная с v2.6+), используемый для декларативного управления кластерами как ресурсами Kubernetes. Позволяет абстрагироваться от специфики облачных провайдеров.

**Fleet** — масштабируемое GitOps-решение, интегрированное в Rancher, предназначенное для доставки манифестов и Helm-чартов на тысячи кластеров одновременно. Работает по Pull-модели: агент на каждом downstream-кластере сам забирает изменения из репозитория.

**NeuVector** — основной компонент безопасности (Full Lifecycle Container Security), обеспечивающий сканирование уязвимостей, аудит соответствия (Compliance) и защиту сетевого трафика в реальном времени (L7 Firewall).

**Project (Проект)** — уникальная абстракция Rancher: логическая группировка нескольких Namespace внутри кластера для агрегации прав доступа (RBAC), квот ресурсов (Resource Quotas) и политик безопасности. Подробности — в `rancher_rbac.md`.

**Downstream Cluster (Управляемый кластер)** — кластер, созданный (provisioned) или импортированный (imported) в Rancher. Бывает трёх видов: Rancher-launched (RKE2/K3s через Node Driver), Custom Nodes и Imported (существующие kubeadm/EKS/AKS/GKE).

**cattle-system** — системный namespace, где живут поды Rancher Manager (все поды `rancher-*`, `cattle-cluster-agent`, webhook и т.п.) в Management-кластере.

## Базовые концепции

### Ключевые возможности платформы

1.  **Унифицированная аутентификация:** интеграция с корпоративными IDP (Active Directory, Okta, Keycloak, Authentik) с использованием OIDC и SAML.
2.  **Глобальный RBAC:** сквозное управление правами доступа через все кластеры с поддержкой проектов (Projects). GlobalRoles задают права глобально, ClusterRoleTemplate/ProjectRoleTemplate — на уровне кластеров и проектов; механизм работает через двухплоскостную трансляцию в нативный Kubernetes RBAC.
3.  **Инфраструктурная конвергенция:** тесная интеграция с **Harvester** (Hyperconverged Infrastructure) для запуска виртуальных машин и контейнеров на едином bare-metal оборудовании.
4.  **Безопасность "из коробки":** предустановленные стеки NeuVector и CIS Benchmark для обеспечения безопасности на всех этапах жизненного цикла.

**Дополнительные ключевые возможности:**
*   **Apps & Marketplace:** встроенный каталог Helm-чартов (в т.ч. официальные `rancher-monitoring`, `rancher-logging`, `rancher-backup`, `rancher-provisioning-capi`, `neuvector`), с версионированием по схеме `100.x.y+up<upstream.version>`.
*   **Мультикластерная наблюдаемость:** агрегация мониторинга и логов из всех кластеров в единые хранилища (Prometheus Remote Write / Logging Operator).
*   **Continuous Delivery (GitOps):** встроенный Fleet для доставки приложений и базовых сервисов (Ingress, cert-manager) во все новые кластеры.

### Архитектурная модель

Rancher использует иерархическую структуру управления:

*   **Management Cluster (Local):** кластер, где запущен Rancher Server. Здесь хранятся пользовательские данные, RoleTemplates и конфигурации Fleet. 
    *   *Важно:* Не рекомендуется размещать бизнес-нагрузки в Local-кластере для обеспечения стабильности панели управления. Для Production следует использовать HA-установку на отдельном кластере (рекомендуется RKE2/K3s), а одиночная Docker-установка допустима только для тестирования.
*   **Downstream Clusters (Управляемые):** кластеры, созданные или импортированные в Rancher. Связь поддерживается через `cattle-cluster-agent`.
*   **Cluster API Providers:** модули, специфичные для облаков (AWS, Azure, vSphere), через которые Rancher заказывает инфраструктуру.

#### Компоненты Rancher Manager и агентов

Понимание компонентов критично для диагностики:

| Компонент | Где работает | Назначение |
| :--- | :--- | :--- |
| **`rancher` Deployment** | Management-кластер `cattle-system` | Основной API-сервер (Rancher API), Web UI, контроллеры management-плоскости. Масштабируется репликами (рекомендуется 3). |
| **`cattle-cluster-agent`** | Каждый downstream-кластер | Устанавливает исходящий TLS/WebSocket-туннель к Rancher Server (порт 443). Через него Rancher проксирует запросы к API downstream-кластера даже за NAT/Firewall. |
| **`cattle-node-agent`** | Каждый узел Node Driver кластера | Управляет жизненным циклом узла: подготовка ОС, установка RKE2, выполнение команд провижининга. |
| **`cattle-webhook`** | Management-кластер | Валидирующий/мутирующий admission webhook для ресурсов Rancher (CRD) и кастомных CRD (`crd.project.cattle.io`). |
| **`rancher-operator` / `rancher-provisioning-capi`** | Management-кластер | Реализация провижининга через Cluster CAPI (RKE2/K3s) и долгосрочной CRD-модели кластеров. |
| **Fleet controller** | Management-кластер | Управление GitRepo, применением манифестов и статусом синхронизации на downstream-кластерах. |
| **`neuvector`** | Downstream (опционально) | Контроллеры безопасности: сканер, контроллер процессов, сетевые политики. |

#### Клиентские инструменты доступа

Взаимодействие с Rancher и managed-кластерами возможно несколькими способами:

1.  **Web UI** — основной графический интерфейс.
2.  **kubeconfig из UI (Rancher Proxy)** — генерируемый файл, где контексты проксируют запросы через Rancher (аутентификация через Rancher, impersonation). `kubectl` идёт через туннель `cattle-cluster-agent`.
3.  **Authorized Cluster Endpoint (ACE)** — прямой доступ к API-серверу downstream-кластера, минуя Rancher. Доступен для кластеров RKE2/K3s (не для hosted EKS/AKS/GKE). В kubeconfig появляются отдельные контексты (`<cluster>-fqdn` при заданном FQDN, иначе `<cluster>-<node>`).
4.  **Rancher CLI (`rancher`)** — официальная утилита: `rancher login`, `rancher context switch`, `rancher kubectl ...` (проксирует kubectl через Rancher). Полезен для скриптов и операций с Rancher API.
5.  **REST API `/v3`** — программный доступ (Terraform/OpenTofu, Ansible, скрипты) с API-токенами.

#### Туннелирование и автономность

Механизм «обратного подключения» (reverse tunnel):
*   **Туннелирование:** `cattle-cluster-agent` сам инициирует исходящее WebSocket-соединение к Rancher Server. Rancher не требует прямой сетевой достижимости API-сервера managed-кластера (кроме импортированных кластеров, где связь также через контакты).
*   **Автономность:** при потере связи с Rancher нагрузки в downstream-кластере продолжают работать; недоступны только UI и централизованная аутентификация.
*   **Сетевые требования:** узлы должны иметь исходящий доступ к Rancher по порту 443 (HTTPS).

> Детали провижининга, агентов и архитектуры связи — в `rancher_rke.md`.

### Технологический стек (актуально на 2026 г.)

| Категория | Технология | Примечание |
| :--- | :--- | :--- |
| **Оркестрация** | Kubernetes | Поддержка актуальных версий (v1.33+ для Rancher 2.13, v1.35 для 2.14) |
| **Дистрибутивы** | RKE2, K3s | RKE1 признан Legacy (EOL 2025) |
| **Безопасность** | NeuVector | Заменяет/дополняет стандартные Network Policies |
| **GitOps** | Fleet | Основной инструмент доставки |
| **Наблюдаемость** | Prometheus, Grafana, Vector | Пакеты `rancher-monitoring` и `rancher-logging` |
| **HCI** | Harvester | Интеграция через виртуализацию |

### Способы создания (провижининга) кластеров

Различают три основных пути:

1.  **Node Drivers (Cloud Provisioning):** Rancher сам заказывает ВМ через API облака/инфраструктуры (AWS, Azure, GCP, vSphere, OpenStack) и устанавливает RKE2/K3s. Управление полным жизненным циклом (создание, масштабирование, обновление, удаление узлов).
2.  **Custom Nodes:** администратор сам готовит узлы ОС, затем запускает сгенерированную команду регистрации. Rancher устанавливает только RKE2 и агенты. Рекомендуется для bare-metal и сред с жёсткими требованиями к сетевым границам.
3.  **Imported Clusters:** подключение существующих кластеров (kubeadm, EKS, AKS, GKE, self-managed). Rancher управляет только Workloads и политиками, но не жизненным циклом самого Kubernetes.

Детали и команды — в `rancher_rke.md`.

## Практические сценарии

### Жизненный цикл эксплуатации кластера

1.  **Провижининг:** Выбор провайдера (Node Driver или Custom) и развертывание RKE2 через Cluster API.
2.  **Настройка доступа:** Подключение внешней группы из AD/Okta и назначение роли `Cluster Owner` или `Project Member`.
3.  **Доставка приложений:** Настройка Git-репозитория во **Fleet** для автоматического деплоя базовых сервисов (Ingress, Cert-manager) во все новые кластеры.
4.  **Сканирование и защита:** Активация NeuVector для анализа образов в CI/CD и блокировки подозрительной сетевой активности в Runtime.
5.  **Обновление:** Выполнение Rolling Update версии Kubernetes без прерывания работы сервисов через интерфейс Rancher.

### Установка (кратко)

Подробное руководство — в `rancher_installation.md`. Ключевые решения:

*   **Инфраструктура:** для Production — HA-кластер (RKE2/K3s, 3 сервера + LB), отдельный от downstream.
*   **Helm:** установка чарта `rancher` в namespace `cattle-system` с указанием `hostname`, `bootstrapPassword`, `ingress.tls.source`.
*   **Требования:** cert-manager (поддержка Gateway API), PSA-профили, включённый Kubernetes API Aggregation Layer.
*   **Ресурсы:** минимум 4 CPU / 8 GB RAM на узел Management-кластера (рекомендуется 16 GB).

### Подключение kubectl через Rancher

**Способ A — kubeconfig через UI (прокси):**

```bash
# 1. Из UI: Cluster Management → кластер → Kubeconfig File → скопировать YAML
# 2. Сохранить в ~/.kube/config (или объединить)
kubectl config get-contexts        # проверить контексты
kubectl cluster-info               # если ОК — kubeconfig работает через Rancher
```

> Если в Rancher отключено автоматическое создание токенов в kubeconfig, при `kubectl` потребуется `rancher` CLI в PATH (иначе ошибка `exec: "rancher": executable file not found in $PATH`).

**Способ B — Authorized Cluster Endpoint (прямой доступ):**

```bash
# Для RKE2/K3s с включённым ACE. В скачанном kubeconfig будут доп. контексты:
kubectl config get-contexts
#   my-cluster              <- через Rancher (прокси)
#   my-cluster-fqdn         <- напрямую, если задан FQDN
#   my-cluster-node1        <- напрямую, если FQDN нет (по узлам control plane)

# Прямое подключение (минуя Rancher, полезно при его недоступности):
kubectl --context my-cluster-fqdn get nodes
```

ACE полagается для RKE2/K3s, включается в настройках кластера. Прямой доступ снижает нагрузку на Rancher-прокси и сохраняет управление при остановке Rancher (break-glass).

### Rancher CLI

Официальный CLI `rancher` применяется для автоматизации и операций с Rancher API:

```bash
# Вход (используя API-токен или интерактивно)
rancher login https://rancher.example.com --token ${RANCHER_TOKEN}

# Контекст (сервер → кластер → проект): обязателен перед операциями
rancher context switch            # выбрать проект из списка

# Проксирование kubectl через Rancher
rancher kubectl get nodes
rancher kubectl get pods -A

# Прочие полезные команды
rancher cluster ls                # список кластеров
rancher inspect <resource>        # детали ресурса (проект, workload, кластер)
rancher token                     # генерация kubeconfig-токена
rancher namespaces ls
```

> `rancher kubectl` — это прокси: некоторые продвинутые возможности/плагины kubectl могут работать не полностью; для полной функциональности используйте kubeconfig с контекстами.

### API-токены для автоматизации (Terraform/Ansible/CI)

*   API-токены создаются в `Users & Authentication → API & Keys` или через `POST /v3/tokens`.
*   **TTL по умолчанию (2026):** auth-токены — 90 дней, kubeconfig-токены — 30 дней; настраиваются через setting `kubeconfig-default-token-ttl-minutes`.
*   Для CI используйте отдельный сервисный токен с минимальными правами и его ротацию, а не личный admin-токен.
*   Для декларативного управления ресурсами Rancher используйте Terraform/OpenTofu с провайдером `rancher2` или Fleet (дальше — в `rancher_rbac.md`).

### Непрерывная доставка через Fleet (GitOps)

Подробности методологии — в `GitOps/GitOps_overview.md`. Ключевые шаги:

1.  Создайте Git-репозиторий с манифестами/чартами.
2.  В UI: **Continuous Delivery → Git Repos → Create**.
3.  Укажите репозиторий и селектор целевых кластеров (по меткам фаз: `fleet.cattle.io/managed: true`, `env=prod` и т.п.).
4.  Fleet автоматически соберёт **Bundle** и применит его в выбранные кластеры, синхронизируя дифф.

**Практика:** разнесите инфраструктурные сервисы (cert-manager, ingress-nginx) и приложения по разным GitRepo, чтобы управлять порядком и зонами ответственности. Используйте `fleet.cattle.io/name` и labels для тонкой таргетизации.

### Аудит соответствия (CIS Benchmark + NeuVector)

Rancher включает встроенную оценку CIS-бенчмарков для RKE2/K3s:

1.  Перейдите в **Cluster Management → кластер → CIS Scan → Create Scan** (версия бенчмарка для вашей версии K8s).
2.  Выполните скан после первичной установки и после обновления кластера.
3.  NeuVector дополняет этот скан сканированием образов (CVE), compliance-профилями (PCI-DSS, HIPAA, NIST) и runtime-защитой сети.
4.  Не вносите исправления «вслепую»: под каждую критичную находку проверьте, не игнорируете ли вы системный компонент (например, `kube-controller-manager` с кастомным конфигом).

> Общие принципы сканирования образов — в `Security/` и `Docker/Docker_security/` (Trivy, Grype и др.). NeuVector — SSoT-источник Rancher-специфического файрвола/сканера.

### Переход с устаревших решений

*   **Rancher Pipelines:** Полностью заменены на Fleet (для CD) и внешние CI-системы (GitHub Actions, GitLab CI). Подробности миграции — в `rancher_pipelines.md`.
*   **RKE1:** Требует миграции на RKE2. Прямого апгрейда не существует; рекомендуется развертывание нового кластера и перенос нагрузок. RKE1 находится на EOL (июль 2025), и Rancher 2.12+ не поддерживает провижининг/управление RKE1. Детали — в `rancher_rke.md` и `../Installation/RKE/index.md`.

## Диагностика и отладка

### Проблемы с агентом и туннелем

*   **Кластер в состоянии `Unavailable`, поды `cattle-cluster-agent` в `CrashLoopBackOff`:**
    ```bash
    kubectl get pods -n cattle-system       # статус агента
    kubectl logs -n cattle-system <cattle-cluster-agent-pod> -c cluster-register
    # Типичная причина: неверный/истёкший CA-сертификат, Discord с Rancher по 443,
    # или слишком большой размер agent-пода (проверьте resources/limit).
    ```
    Проверьте исходящую связность узла с Rancher: `curl -v https://<rancher-fqdn>/v3`.
*   **`cattle-webhook` не готов:** проявляется как ошибки admission при apply. Проверьте `kubectl get pods -n cattle-system` и логи целла.
*   **Недоступность UI, но кластеры работают:** вероятно, проблема в Rancher Server, а не в кластерах — нагрузки автономны.

### Проблемы провижининга

*   **Узел Node Driver завис в `Provisioning`:** смотрите логи `cattle-node-agent` и состояние cloud-ресурса (ВМ). Обычно — ошибка cloud-init, ключа SSH или деталей сети/статических IP.
*   **Ошибка `firewalld`:** firewalld несовместим с CNI-плагинами; отключите его на узлах (требование Rancher).
*   **K8s-версия вне поддержки:** Rancher 2.13 не поддерживает версии младше v1.32; при попытке провижининга — обновите выбор версии в UI.

### Проблемы доступа/RBAC

*   Пользователь не видит кластер/проект — не хватает membership-binding на нужном уровне (см. `rancher_rbac.md`).
*   `kubectl` возвращает `Forbidden` — проверьте `kubectl auth can-i ... --as <user>` и корректность правил RoleTemplate.
*   Прямое подключение к ACE недоступно — проверьте, что в контексте используется `-fqdn`/`-node`, а кластер — RKE2/K3s (не hosted).

## Дополнительная информация

### Статус компонентов и рекомендации (2026)

| Компонент | Версия | Статус | Рекомендация |
| :--- | :--- | :--- | :--- |
| **Rancher (Community)** | v2.14.x | Актуально | Базовая версия без поддержки; для prod — Prime. |
| **Rancher Prime** | v2.13.x / v2.14.x (LTS) | LTS | Для корпоративных сред с поддержкой 24/7. |
| **NeuVector** | v5.5.x | Актуально | Обязательно для сред с требованиями PCI-DSS/HIPAA. В 5.5.0 прекращена нативная Docker-поддержка. |
| **Cluster API** | v1.x+ | Стабильно | Основной движок провижининга; нативные CAPI-провайдеры (CAPA/CAPV) — tech preview в v2.14. |
| **Helm client** | 3.18+ | Требование | Необходим для управления Rancher 2.12+. |

**Поддерживаемые версии K8s (SUSE Support Matrix, 2026):**
*   Rancher 2.13: RKE2/K3s **v1.32 – v1.34**.
*   Rancher 2.14: RKE2/K3s **v1.33 – v1.35** (Кubernetes v1.31 и старше — вне поддержки; v1.32 удалён в v2.14).
*   RKE1 полностью EOL (июль 2025).

### Рекомендации и лучшие практики (2026)

*   **Отдельный HA-кластер под Rancher:** никогда не смешивайте бизнес-нагрузки с Management-кластером; для Production используйте 3-узловой RKE2/K3s с Load Balancer.
*   **Policy-as-Code:** определяйте проекты, роли, кластеры и Fleet-репозитории через Terraform/OpenTofu или Fleet, а не вручную в UI (для воспроизводимости и аудита).
*   **Группы вместо пользователей:** назначайте роли группам из IDP, а не отдельным аккаунтам.
*   **Центральная доставка:** внедрите Fleet для раздачи базовых сервисов (cert-manager, ingress, policies) во все новые кластеры — это снижает протухание конфигурации на растущем парке кластеров.
*   **ACE для CI:** для доставки в downstream используйте прямые ACE-контексты, чтобы не перегружать Rancher-прокси и сохранить доступ при остановке Rancher.
*   **Регулярные бэкапы:** используйте `rancher-backup` (на базе Velero) для Management-кластера и проверяйте восстановление (см. `rancher_installation.md`).
*   **Ротация и аудит токенов:** периодически ревизуйте API-токены, отзывайте неиспользуемые, ротируйте CI-токены до истечения TTL.
*   **Поддержка версий:** следите за жизненным циклом Rancher и K8s (EOL), планируйте апгрейды в пределах поддержки KDM.
*   **Обновление charts:** закрепляйте версии Helm-чартов и применяйте политику ретенции версий Rancher (для v2.15+ — окно из 7 релизов).

---

**См. также:**

*   [Установка Rancher Server](./rancher_installation.md) — выбор инфраструктуры и Helm-настройка.
*   [RKE в Rancher](./rancher_rke.md) — детали работы RKE2 и агентов, провижининг.
*   [Управление пользователями и RBAC](./rancher_rbac.md) — настройка проектов и SSO.
*   [Логирование в Rancher](./rancher_logging.md) — сбор логов через Logging Operator и Vector.
*   [Мониторинг в Rancher](./rancher_monitoring.md) — стек наблюдаемости (Prometheus/Grafana).
*   [Fleet: непрерывная доставка](./rancher_fleet.md) — GitOps и доставка приложений.
*   [Day-2 операции](./rancher_day2_operations.md) — обновления, масштабирование, обслуживание.
*   [Disaster Recovery](./rancher_disaster_recovery.md) — backup и восстановление.
*   [Troubleshooting](./rancher_troubleshooting.md) — диагностика и устранение неполадок.
*   [Безопасность](./rancher_security.md) — PSA, CIS Benchmark, NeuVector.
*   [Сетевые настройки](./rancher_networking.md) — CNI, DNS, Ingress.
*   [Capacity Planning](./rancher_capacity_planning.md) — планирование ресурсов.

**Внешние ресурсы:**

*   [Rancher Architecture Guide](https://ranchermanager.docs.rancher.com/reference-guides/rancher-manager-architecture)
*   [Rancher CLI Reference](https://ranchermanager.docs.rancher.com/reference-guides/cli-with-rancher/rancher-cli)
*   [SUSE NeuVector Documentation](https://open-docs.neuvector.com/)
*   [Harvester HCI Project](https://harvesterhci.io/)
