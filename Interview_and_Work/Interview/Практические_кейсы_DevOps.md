# Практические кейсы из собеседований — DevOps/SRE

В данном файле собраны реальные кейсы из собеседований, структурированные по темам. Каждый кейс содержит описание проблемы, принятых решений и полученных результатов.

## Кейс 1: Телеком-провайдер с собственной инфраструктурой

### Контекст

Крупный телеком-провайдер с собственными дата-центрами (железо, «кубы»), собственными кластерами и базами данных. Стек: Go + PHP, GitLab CI, Ansible, Kubernetes (30+ нот/кластер, ~8 кластеров), PostgreSQL + MySQL. Compliance: PCI DSS.

### Архитектура инфраструктуры

- **Окружения:** Stage, Prod в отдельных VPC/подсетях.
- **Kubernetes:** ~30 нот на кластер, ~8 кластеров, ~2 CPU на ноту.
- **Изоляция:** Один сервис — один namespace. NetworkPolicy разрешает трафик только от инфраструктурных компонентов (Prometheus, Ingress Controller, engineering-сеть).
- **Базы данных:** PostgreSQL + MySQL, развернуты на bare metal в тех же дата-центрах.

### Решения

#### Секреты

- **External Secret Operator:** Синхронизация из Vault в Kubernetes `Secret`.
- **Время подготовки:** Секреты готовятся позже — в момент деплоя, а не во время сборки.
- **Без Vault Agent Injection:** Из-за проблем с фреймворками (Symfony, множественные источники конфигурации) предпочитают готовые секреты в `Secret`.

#### GitLab CI

- **Централизация:** Отдельный репозиторий `CI` со всеми пайплайнами. Проекты подключают шаблоны через `include:project`.
- **Доставка в Argo CD:** GitLab CI вызывает Argo CD API для синхронизации приложений (альтернатива классическому GitOps).
- **Downstream пайплайны:** Использование `trigger` для запуска дочерних пайплайнов (например, деплой после успешного тестирования).
- **Не используют традиционные GitOps:** Пайплайны отвечают за доставку, Argo CD — за синхронизацию.

#### Helm

- **Library charts:** Библиотечные чарты для стандартизации 150+ сервисов.
- **Технологическая специфичность:** Отдельные библиотеки для Java, PHP, Python. Общие шаблоны (метки, селекторы) вынесены в `common-lib`, stack-specific — в `java-lib`, `php-lib`.
- **Один сервис — один namespace:** Упрощает администрирование, Resource Quota и RBAC.

#### Секреты

- **External Secret Operator:** Синхронизация из Vault в Kubernetes `Secret`.
- **Время подготовки:** Секреты готовятся позже — в момент деплоя, а не во время сборки.
- **Без Vault Agent Injection:** Из-за проблем с фреймворками (Symfony, множественные источники конфигурации) предпочитают готовые секреты в `Secret`.

#### PCI DSS

- **Сетевая сегментация:** Удален прямой VPN-доступ к кубам и базам данных. Введен шлюз посередине с разными сетями.
- **Default Deny:** Каждый namespace имеет политику, запрещающую весь трафик по умолчанию.
- **Изоляция:** Инженерная сеть (bastion, CI/CD) отделена от production-сегмента.

### Инциденты

#### Авария в дата-центре Яндекса (Владимир)

- **Дата:** 28 марта.
- **Симптом:** Все сервисы были в зоне B дата-центра Яндекса во Владимире. Простой 6 часов на проде.
- **Последствия:** Летом переписана вся инфраструктура на высокодоступную Kubernetes с размазыванием по регионам (multi-AZ).
- **OutOfSync:** PostgreSQL master живет только в одной зоне, поэтому кубы не могут быть размазаны по географии без перехода на шардирование или изменения архитектуры БД.

### Выводы

1. **Модульность IaC** критична для инфраструктур 100+ сервисов. Один модуль — один сервис — один state.
2. **Atlantis** устраняет необходимость в shared credentials и обеспечивает аудит изменений инфраструктуры.
3. **Library charts** должны быть привязаны к технологическому стеку. Универсальный «божественный» чарт становится нечитаемым.
4. **PCI DSS** требует не только технических мер (NetworkPolicy), но и организационных (отдельные сети, шлюзы, аудит).
5. **Выбор паттерна секретов** зависит от экосистемы приложения: если фреймворк не умеет работать с динамическими секретами — используйте синхронизацию в нативный `Secret`.

## Кейс 2: Образовательная платформа в Яндекс.Облаке

### Контекст

Образовательная платформа (CNG) с инфраструктурой в Яндекс.Облаке. Стек: PHP + Symfony, React, GitLab CI, Kubernetes.

### Решения

- **Облако:** Яндекс.Облако, все сервисы в одной зоне.
- **Базы данных:** PostgreSQL + MySQL, управляемые сервисы (не self-hosted).
- **Сеть:** Один VPC, разделение по каталогам и подсетям.
- **Кластер:** Kubernetes, развернутый через IaC.

### Инцидент

Переезд на шлюз посередине и разные сети для PCI DSS. Аудиторы пока не требуют полной сегментации — только для хранения платежных данных (токенов).

### Выводы

- **Масштабирование:** При росте числа сервисов (>150) централизация CI/CD становится обязательной.
- **Стандартизация:** Жесткие стандарты именования переменных (U-Track) упрощают работу через library charts.
- **Сетевые ограничения:** VPN прямого доступа к базам данных — антипаттерн для compliance-сред.

## Кейс 3: Инструменты и технологии

### Ansible

- **Назначение:** Управление legacy-инфраструктурой, деплой Docker-контейнеров на bare metal.
- **Паттерны:** Итерация по словарям/массивам для массового создания конфигураций.

### Jenkins

- **Назначение:** Специфические задачи (бэкапы платформы тестирования Test IT), где требуется прямая интеграция с artifact repository.
- **GitLab CI vs Jenkins:** GitLab CI предпочтительнее из-за меньшего порога вхождения и встроенной интеграции с Kubernetes.

### Java

- **Проблема:** Высокое потребление памяти Jenkins при сборке Java-проектов.
- **Диагностика:** Flame graphs (async-profiler) для анализа hotspots в runtime.
- **Решение:** Включение профилирования на уровне Helm-чартов (sidecar с async-profiler).

## Кейс 4: Интервью DevOps Engineer (реальный диалог)

### Контекст

Запись реального интервью DevOps-инженера. Кандидат описывает инфраструктуру и отвечает на технические вопросы интервьюера. Сфокусировано на практических решениях и типичных вопросах, которые задаются на собеседованиях DevOps-позиций в 2026 году.

### Инфраструктура кандидата

**Приложение:** Java backend (N2O framework), PostgreSQL.

**CI/CD стек:**
- **Хранилище кода:** GitLab
- **CI/CD:** GitLab CI (через Helm) + Argo CD
- **Деплой:** в Kubernetes

**Реестры:**
- **Ниже prod:** GitLab Registry
- **Prod:** Harbor (встроенное сканирование Trivy, кэширование слоёв, репликация)

**Мониторинг и логирование:**
- **Метрики:** Prometheus (краткосрочное) + VictoriaMetrics (долгосрочное хранение)
- **Логи:** OpenSearch (вместо Elasticsearch) с ISM (Index State Management); есть проекты с Loki + Fluentd/Fluent Bit
- **Алёртинг:** AlertManager → корпоративный мессенджер через вебхуки

**Автоматизация:**
- **Ansible** — управление хостами (~5 ВМ), запуск через GitLab Runner
- **Salt (SaltStack)** — инжекция секретов через аннотации в поды Kubernetes
- **Kubespray** — развёртывание кластера Kubernetes (kubeadm + кастомизация сети)

**ОС:** Отечественные дистрибутивы (Альт, Астра, RedOS)

**Команда:** 15 DevOps-инженеров, ~100-150 разработчиков, ~100 тестировщиков

**Разворачиваемая инфраструктура:**
- ВМ в КОРЕ (VPS) для dev/staging
- Kubernetes в продакшене (через Kubespray, kubeadm)
- GitLab Runner как под в Kubernetes

### Вопросы интервьюера и ответы кандидата

#### CI/CD pipeline с нуля

**Вопрос:** При неограниченном бюджате и ресурсах, выбери любой язык и составь целевой CI/CD процесс. Из каких этапов? Какие инструменты?

**Ответ:**

1. **Линтинг кода** — проверка на синтаксис, code smell, стандарты команды. SonarQube.
2. **Сборка** — компиляция (Maven/Gradle для Java). Unit-тесты перед сборкой.
3. **Контейнеризация** — Docker/Kaniko, multi-stage, Alpine, минимизация слоёв.
4. **Реестр** — Harbor (prod, встроенный сканинг Trivy, кэш) vs GitLab Registry (dev).
5. **Сканирование** — Trivy на уязвимости, Gitleaks на секреты, SBOM.
6. **Тестирование** — integration и нагрузочное на тестовом стенде.
7. **Деплой** — Helm + Argo CD.

**Ключевые решения:** Harbor вместо GitLab Registry (встроенная проверка, кэширование); раннеры как поды в K8s; разные реестры для dev/prod.

Подробнее: **[CI/CD pipeline: этапы](../../CI-CD/Core_Concepts/pipeline_workflow.md)**, **[GitLab CI: примеры пайплайнов](../../CI-CD/GitLab_CI/Tutorials/gitlab_ci_pipeline_examples.md)**.

#### Безопасность контейнеров

**Вопрос:** Какие best practices при использовании Docker?

**Ответ:** Multi-stage builds, Alpine вместо Ubuntu, USER (не root), EXPOSE для документирования порта.

Подробнее: **[Docker best practices: безопасность](../../Docker/Dockerfile/Docker_best_practices/security.md)**, **[Docker best practices: оптимизация](../../Docker/Dockerfile/Docker_best_practices/build_optimization.md)**.

**Вопрос:** Приложение в Docker запущено, но веб не открывается. Как отлаживать?

**Ответ:**
1. `docker logs <container>` — ошибки старта/приложения.
2. `docker ps -a` — exit code и статус.
3. Проверить port mapping (`-p 8080:80`, `docker port`).
4. Проверить env vars (`docker inspect ... --format '{{json .Config.Env}}'`).
5. `docker exec -it <container> sh` — диагностика внутри.
6. `docker inspect` — конфигурация, слои, команды.

Подробнее: **[Docker troubleshooting](../../Docker/Docker_troubleshooting/)**, **[Docker logging drivers](../../Docker/Docker_logs/docker_logging_drivers_overview.md)**.

#### GitLab Runner и Kubernetes

**Вопрос:** Сколько контейнеров внутри пода GitLab Runner (Kubernetes executor)?

**Ответ:** 3 контейнера:
1. **Pause container** — держит сетевой стек (IP, порты).
2. **Init container** — подготовка (клонирование репо, загрузка артефактов/кэша).
3. **Main container** — выполнение задачи (`script`).

Подробнее: **[Обзор GitLab Runner](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_runners_executors.md)**, **[Установка GitLab Runner в K8s](../../Kubernetes/Installation/gitlab_runner_kubernetes_installation.md)**.

#### Kubernetes Architecture

**Вопрос:** Какие компоненты на control plane?

**Ответ:** kube-apiserver, etcd, controller-manager, scheduler, kube-proxy, kubelet.

Подробнее: **[Архитектура Control Plane](../../Kubernetes/Concepts/control_plane_architecture.md)**, **[Kubelet: агент на узле](../../Kubernetes/Concepts/kubelet.md)**.

**Вопрос:** Чем Deployment отличается от StatefulSet?

**Ответ:**
- **Deployment** — stateless, поды взаимозаменяемы, один PV на всех.
- **StatefulSet** — stateful (PostgreSQL, Kafka), **отдельный PVC для каждого пода** (через `volumeClaimTemplates`), порядок запуска/остановки (web-0, web-1, web-2).

Подробнее: **[Сравнение Deployment и StatefulSet](../../Kubernetes/Base/StatefulSet/statefulset_vs_deployment.md)**, **[StatefulSet: концепции](../../Kubernetes/Base/StatefulSet/statefulset_core_concepts.md)**.

**Вопрос:** Почему в Kubernetes есть Pod, а не контейнер?

**Ответ:** Pause container держит сетевой стек (общий IP); если main container упадёт — Pod жив. Можно подвязать VIP и балансировку через Service.

**Вопрос:** Какие ещё типы вспомогательных контейнеров?

**Ответ:** Init container'ы, sidecar'ы, job'ы.

Подробнее: **[Обзор Pod](../../Kubernetes/Base/Pod/pod_overview.md)**, **[Жизненный цикл Pod](../../Kubernetes/Base/Pod/pod_lifecycle_and_state.md)**.

#### Сетевая безопасность

**Вопрос:** Как ограничить сетевые связи между подами?

**Ответ:** NetworkPolicy по меткам. Бэкенд → только к БД (label: app=database), фронтенд → только к бэкенду (label: app=backend). Kubespray для настройки Calico CNI.

Подробнее: **[NetworkPolicy: сетевая безопасность](../../Kubernetes/Security/network_policies.md)**.

#### Безопасность образов и Supply Chain

**Вопрос:** Какие проверки на уязвимости можно проводить?

**Ответ:**
- **Trivy** — сканирование образа, Dockerfile, файловой системы, root filesystem (`trivy rootfs`), запущенного контейнера (`trivy container <id>`).
- **SBOM** — отчёт о компонентах, генерируется Trivy.
- Trivy — **SCA/compositional**, а не DAST. `trivy container` проверяет filesystem, а не тестирует runtime извне.

Подробнее: **[Сканирование уязвимостей](../../Docker/Docker_security/vulnerability_scanning.md)**, **[SBOM для Docker](../../Docker/Docker_security/docker_sbom.md)**.

#### Мониторинг и алертинг

**Ответ о стеке:**
- **Prometheus + VictoriaMetrics** — VM для LTS, Prometheus для быстрого доступа.
- **Метрики:** кластера, приложений, бизнес-, коды ответов, долгие запросы, node-exporter.
- **OpenSearch** (вместо ES) с ISM — аналог ILM. Свежие логи на SSD, старые на HDD.
- **Алёртинг:** AlertManager → вебхуки в корпоративный мессенджер. Маршрутизация по чатам команд.

Подробнее: **[VictoriaMetrics](../../VictoriaMetrics/overview.md)**, **[AlertManager](../../Prometheus/alertmanager.md)**, **[OpenSearch: ISM](../../ELK_Stack/OpenSearch/opensearch_ism_lifecycle.md)**.

#### Автоматизация и IaC

**Ответ об автоматизации:**
- **Ansible** — ~5 ВМ через GitLab Runner. extra_vars — наивысший приоритет. loop с items для массовых задач.
- **Salt** — инжекция секретов через аннотации в поды.
- **Kubespray** — kubeadm + кастомизация сети (pod subnet, service subnet), управление нодами.

**Вопрос:** Как запустить таску 10 раз с 10 параметрами?

**Ответ:** `loop` с `lookup('sequence')` или `items`.

**Вопрос:** Как запустить таску под другим пользователем?

**Ответ:** `become_user` (или `pikamz`).

Подробнее: **[Ansible: flow control](../../Ansible/PlaybookStructure/flow_control.md)**, **[Kubespray: обзор](../../Kubernetes/Installation/Kubespray/overview.md)**, **[SaltStack: безопасность](../../SaltStack/Security_Approaches.md)**.

#### Windows Server

**Вопрос:** С Windows серверами работал?

**Ответ:** Да. Active Directory, GPO. Предыдущий опыт на Legacy-проектах.

Подробнее: **[SSSD + Active Directory](../../Linux/SystemAdministration/Users/LDAP_SSSD/ad_integration.md)**, **[Ansible: Identity Management](../../Ansible/ansible-identity-management.md)**.

### Выводы

1. **CI/CD pipeline design** требует понимания полного цикла: линтинг → сборка → контейнеризация → реестр → сканирование → тестирование → деплой. Ключевые решения (Harbor vs GitLab Registry) должны быть обоснованы.
2. **Контейнеры и безопасность** — сканирование на всех этапах (образ, Dockerfile, fs, rootfs, container) через Trivy + SBOM.
3. **Kubernetes** — компоненты control plane, архитектура Pod (pause container), Deployment vs StatefulSet, NetworkPolicy — обязательны для senior-уровня.
4. **Инфраструктурные инструменты** — Ansible (loop, variables), Salt (secrets), Kubespray (cluster deployment).

## Дополнительная информация

### См. также

- [Обзор IaC](../../Concepts/iac_overview.md) — принципы Infrastructure as Code.
- [GitLab CI: продвинутые рабочие процессы](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_advanced_workflow.md) — DAG, Matrix, Pipeline Inputs.
- [Helm: зависимости и библиотечные чарты](../../Kubernetes/ToolsUtilities/Helm/helm_dependencies_and_library_charts.md) — library charts, технологическая специфичность.
- [NetworkPolicy: сетевая безопасность и изоляция подов](../../Kubernetes/Security/network_policies.md) — compliance, сегментация.
- [Внешние системы управления секретами](../../Kubernetes/Base/secrets/external_managers.md) — ESO, Vault, паттерн доставки секретов в Kubernetes.
