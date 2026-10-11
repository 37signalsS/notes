# Harbor: Обзор реестра

**Актуально для:** Harbor 2.15.x

## Определения

* **Harbor**: Open-source реестр артефактов корпоративного уровня. Проект CNCF: принят 31.07.2018, переведён в Incubating 14.11.2018, Graduated — с 15.06.2020.
* **Проект (Project)**: Основная единица организации в Harbor. Группирует репозитории, пользователей и политики. Может быть публичным или приватным.
* **OCI-реестр (Open Container Initiative Registry)**: Реестр, поддерживающий спецификации OCI для хранения не только образов контейнеров, но и Helm-чартов, SBOM, сигнатур и других артефактов.
* **Proxy Cache**: Режим работы проекта, при котором Harbor выступает прозрачным прокси-сервером для внешних реестров (Docker Hub, Quay), кэшируя артефакты локально для обхода лимитов и ускорения загрузки.
* **P2P Preheat**: Интеграция с P2P-сетями распределения (Dragonfly, Kraken): Harbor заранее прогревает образы в P2P-движке по политике — критично для крупных инсталляций с тысячами узлов.
* **Referrers API (OCI 1.1)**: Механизм связи между артефактами, позволяющий «прикреплять» SBOM или подписи к образу как связанные объекты, а не дополнительные слои.
* **Deployment Security**: Политика проекта, блокирующая `pull` артефактов с уязвимостями выше заданного порога критичности CVE.
* **Security Hub**: Централизованная панель администратора: общее число уязвимостей по severity, топ-5 опасных артефактов и CVE, поиск по CVE ID, severity, CVSS3, проекту, digest, репозиторию, пакету и тегу.
* **Квота (Quota)**: Ограничение на объём хранилища и количество артефактов на уровне проекта.

## Основные концепции

Harbor расширяет возможности стандартного Docker Registry, предоставляя инструменты для управления безопасностью, жизненным циклом и производительностью доставки артефактов.

### Архитектурные компоненты

Harbor состоит из взаимодействующих сервисов (состав подтверждается метрикой `harbor_up` с лейблами компонентов):

| Компонент | Назначение |
| :--- | :--- |
| **Proxy (Nginx)** | Точка входа, маршрутизация запросов к UI, API и Registry. |
| **Portal** | Веб-интерфейс Harbor (UI). |
| **Core** | Основная логика: управление проектами, RBAC, аутентификация, квоты и Webhooks. |
| **Job Service** | Фоновые задачи: репликация, сканирование уязвимостей, Garbage Collection, P2P preheat. |
| **Registry** | Модифицированный Docker Distribution для физического хранения слоёв и манифестов. |
| **Registryctl** | Управление конфигурацией Registry (хранилище и драйверы хранения). |
| **Database (PostgreSQL)** | Метаданные: конфигурация проектов, пользователи, логи и результаты сканирования. |
| **Redis** | Кэширование данных и управление очередями заданий для Job Service. |
| **Scanner (Trivy)** | Анализ артефактов на наличие известных уязвимостей (CVE); поддерживаются подключаемые сканеры (pluggable scanners). |

### Ключевые возможности

| Возможность | Описание |
| :--- | :--- |
| **Управление доступом (RBAC)** | Аутентификация через LDAP/AD, OIDC (документированные примеры провайдеров: Okta, KeyCloak, dex) или локальную БД; роли на уровне системы и проекта. |
| **Сканирование уязвимостей** | Автоматический (по расписанию или событию) или ручной запуск Trivy. Поддержка блокировки `pull` при превышении порога критичности CVE (Deployment Security). |
| **Управление SBOM** | Генерация SBOM (Harbor 2.11+, встроенный Trivy) при push или вручную; визуализация состава пакетов (SBOM Details), экспорт в формате SPDX; SBOM хранится как OCI-артефакт (Referrers) и реплицируется с артефактом. |
| **Репликация (Push/Pull)** | Синхронизация данных между инстансами Harbor по расписанию или событию (например, push в Dev-реестр инициирует репликацию в Prod). |
| **Управление жизненным циклом** | Гибкие политики очистки (Retention) по времени или количеству тегов, а также неизменяемые (Immutable) теги. |
| **Квоты и лимиты** | Ограничение дискового пространства и количества артефактов на уровне проекта для предотвращения переполнения хранилища. |
| **P2P Preheat** | Прогрев образов в P2P-сетях Dragonfly (v1.0.5+) и Uber Kraken (v0.1.3+); политики по расписанию, событию или вручную, с учётом content trust и ситуации с уязвимостями. |
| **Метрики (Prometheus)** | Метрики в модели данных Prometheus (с v2.2) от компонентов exporter, core, jobservice и registry. |
| **Аудит и трассировка** | Audit Log операций и распределённая трассировка (Distributed Tracing). |
| **Резервное копирование** | Backup и restore Harbor в Kubernetes через Velero. |

### Требования к ресурсам и ПО

Официальные минимальные и рекомендуемые требования Harbor 2.15:

| Ресурс | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| CPU | 2 CPU | 4 CPU |
| Память | 4 GB | 8 GB |
| Диск | 40 GB | 160 GB |

ПО для развёртывания через Docker Compose:

| ПО | Версия | Назначение |
| :--- | :--- | :--- |
| Docker Engine | > 20.10 | Среда выполнения контейнеров |
| Docker Compose | > 2.3 | Входит в состав Docker Engine |
| OpenSSL | Latest (опционально) | Генерация сертификатов и ключей для Harbor |

Сетевые порты: **443** (HTTPS) и **80** (HTTP) — портал и Core API принимают запросы на этих портах; оба меняются в конфигурационном файле. Для Kubernetes используется Helm-чарт `goharbor/harbor-helm`.

> Для offline-контура Kubespray применяются расширенные требования (2+ CPU, 4+ ГБ RAM, 100+ ГБ SSD) — см. [шаг 3 offline-установки](../../../Kubernetes/Installation/Kubespray/offline_installation/step3_offline_env.md).

### Поддержка OCI 1.1 и Referrers

Harbor (v2.11+) поддерживает спецификацию OCI 1.1. Это позволяет:
* **Прикреплять аттестации**: SBOM и данные о сборке (provenance) хранятся как связанные артефакты.
* **Интеграция с Cosign и Notation**: подписи образов отображаются в интерфейсе как связанные Referrers, что упрощает аудит.
* **Пользовательские OCI-артефакты (User-defined OCI Artifacts)**: хранение Helm-чартов, OPA-политик и произвольных артефактов в едином формате.

### Безопасность и доверие

Harbor реализует многоуровневую модель безопасности:
1. **Робот-аккаунты**: изолированные учётные данные для CI/CD с ограниченным временем жизни и правами только на конкретный проект (см. [сценарий 2](./usage.md#сценарий-2-использование-робот-аккаунтов-в-cicd)).
2. **Deployment Security**: блокировка `pull` артефактов с уязвимостями выше порога. Для OCI image index проверяются вложенные артефакты (например, образ Redis для ARM проверяется отдельно от amd64), а не сам index целиком.
3. **CVE Allowlists**: системные (system-wide) и на уровне проекта — временное или постоянное разрешение образов с известными уязвимостями, признанными безопасными для инфраструктуры.
4. **Security Hub**: сводный обзор безопасности всего реестра — общее число уязвимостей по severity, топ-5 опасных артефактов и CVE, поиск уязвимостей.
5. **Аудит**: полное логирование операций (кто, когда и какой артефакт скачал или изменил).

## Практические сценарии

### Развертывание в различных окружениях

Harbor является гибким инструментом и может быть развернут как на одном сервере через Docker Compose (для малых сред), так и в кластере Kubernetes через Helm (для высокодоступных систем).
Подробности см. в [установке Harbor](./installation.md).

### Интеграция в CI/CD пайплайны

Типовое использование включает автоматическую сборку образов, их сканирование в Harbor и последующую доставку в K8s. Harbor выступает в роли «врат безопасности», не позволяя образам с критическими уязвимостями попасть в Production.
Примеры команд и настройки доступа см. в [работе с Harbor](./usage.md).

### Проверка состояния инстанса (SRE)

Для оперативной диагностики используй health-check endpoint (не требует аутентификации):

```bash
# Статус каждого компонента
curl -s https://harbor.example.com/api/v2.0/health

# Проверка pull-путь: registry доступен
curl -s https://harbor.example.com/v2/ -o /dev/null -w "%{http_code}\n"
# → 200 (без логина; 401 ожидается при авторизованном запросе)

# Проверка через Prometheus
curl -s http://harbor.example.com:9090/metrics | grep -E '^harbor_up\{|^harbor_health'
```

**Критерии:** registry и database — mandatory; jobservice, portal, redis, registryctl, trivy — влияют на конкретные сценарии (без jobservice не работают репликация/GC/preheat, без trivy — сканирование). См. [operations.md](./operations.md) по алертам и SLO.

### Работа в изолированных сетях (Air-gapped)

В закрытых контурах Harbor становится центральным узлом для хранения всех доверенных образов. Для поддержания актуальности баз уязвимостей используется механизм оффлайн-обновления.
Инструкции см. в [обновлении Trivy](./offline_trivy_update.md).

### Конфигурация harbor.yml (SRE)

Ключевые секции `harbor.yml` (шаблон `make/harbor.yml.tmpl`, v2.15.0), которые влияют на эксплуатацию:

| Секция | Ключевые параметры | Значение по умолчанию / замечание |
| :--- | :--- | :--- |
| `hostname` / `external_url` | `hostname`, `external_url` | `external_url` отключает `hostname` (используется при reverse proxy). |
| `https` | `port`, `certificate`, `private_key` | 443; HTTP (80) редиректит на HTTPS. |
| `database` | `password`, `max_idle_conns`, `max_open_conns`, `conn_max_lifetime` | `max_open_conns: 900` — лимит PostgreSQL; уменьшите при внешней БД с малым `max_connections`. |
| `external_database` / `external_redis` | `host`, `port`, `ssl_mode`, `registry_db_index`, `jobservice_db_index` | db_index 0 — core (неизменяем), 1 — registry, 2 — jobservice. Redis TLS не поддерживается. |
| `trivy` | `ignore_unfixed`, `skip_update`, `offline_scan`, `security_check`, `timeout` (до 30m), `github_token` | `security_check: vuln` — только уязвимости; `config`/`secret` добавляются отдельно. |
| `jobservice` | `max_job_workers`, `max_job_duration_hours`, `job_loggers` | `jobLogger: database` — обязательно при object storage. |
| `notification` | `webhook_job_max_retry`, `webhook_job_http_client_timeout` | 3 retry / 3s. |
| `log` | `level`, `local.rotate_count`, `local.rotate_size`, `local.location` | `/var/log/harbor`; ротация 50 файлов по 200M. |
| `proxy` | `http_proxy`, `https_proxy`, `no_proxy`, `components` | Репликация требует proxy для core и jobservice. |
| `metric` | `enabled`, `port`, `path` | `port: 9090`, `path: /metrics`. |
| `trace` | `enabled`, `sample_rate`, `jaeger` / `otel` | Один провайдер за раз (см. [tracing.md](./tracing.md)). |
| `upload_purging` | `enabled`, `age`, `interval`, `dryrun` | Очистка `_upload` папок по расписанию. |
| `cache` | `enabled`, `expire_hours` | Отключено по умолчанию; в HA — одинаковое значение на всех инстансах. |
| `core` | `quota_update_provider` | `db` (по умолчанию) или `redis` при высокой конкурентности push. |

> **Файл содержит пароли в открытом виде** — `chmod 600 harbor.yml`; в Kubernetes пароли хранятся в Secrets.

### Мониторинг и наблюдаемость (SRE)

Harbor экспортирует метрики в модели данных Prometheus. Включается в `harbor.yml` (параметры `metrics.port` и `metrics.path`, доступны с v2.2); адрес: `<harbor_instance>:<metrics_port>/<metrics_path>`.

**Health-check endpoint:** `GET /api/v2.0/health` (без аутентификации) возвращает статус каждого компонента (core, database, jobservice, portal, redis, registry, registryctl, trivy) в формате `OverallHealthStatus`. HTTP 200 — всё здорово, 500 — есть нездоровые компоненты. Используется в healthcheck-библиотеках и как простая замена `harbor_up`:

```bash
curl -s https://harbor.example.com/api/v2.0/health | python3 -m json.tool
# → {"status":"healthy","components":[{"name":"registry","status":"healthy"},...]}
```

Компоненты, от которых зависит работоспособность: registry (pull/push), database (метаданные, аудит), jobservice (фоновые задачи), portal (UI), redis (очереди), registryctl (конфиг registry), trivy (сканирование).

Ключевые метрики: `harbor_up` (статус компонентов: core, database, jobservice, portal, redis, registry, registryctl, trivy), `harbor_health`, `harbor_artifact_pulled` (число pull в проекте), `harbor_project_quota_usage_byte` (использование квоты), `harbor_task_queue_size` (очередь задач Job Service).

Пример scrape-конфигурации Prometheus (из документации Harbor):

```yaml
scrape_configs:
  - job_name: 'harbor-exporter'
    scrape_interval: 20s
    static_configs:
      - targets: ['<harbor_instance>:<metrics_port>']
  - job_name: 'harbor-core'
    scrape_interval: 20s
    params:
      comp: ['core']
    static_configs:
      - targets: ['<harbor_instance>:<metrics_port>']
  - job_name: 'harbor-registry'
    scrape_interval: 20s
    params:
      comp: ['registry']
    static_configs:
      - targets: ['<harbor_instance>:<metrics_port>']
  - job_name: 'harbor-jobservice'
    scrape_interval: 20s
    params:
      comp: ['jobservice']
    static_configs:
      - targets: ['<harbor_instance>:<metrics_port>']
```

В Kubernetes достаточно создать [ServiceMonitor](../../../Prometheus/kubernetes/operator/crd/servicemonitor.md) с `port: metrics` и включить `metrics.enabled: true` в values harbor-helm. Пример Grafana-дэшборда доступен в репозитории Harbor. Основы Prometheus см. в [обзоре Prometheus](../../../Prometheus/overview.md).

Резервное копирование инстанса в Kubernetes — через [Velero](../../../Kubernetes/ToolsUtilities/velero-overview.md) (документированный Harbor способ backup/restore).

## Дополнительная информация

### Сравнение с аналогами

Официальная сравнительная таблица Harbor ([Registry Landscape](https://goharbor.io/docs/2.15.0/build-customize-contribute/registry-landscape/), поддерживается сообществом Harbor; «?» — данные сообщества не подтверждены):

| Функция | Harbor | Docker Trusted Registry | Quay | Distribution | Artifactory | GitLab |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Определение версий бинарий в контейнерах | ✓ | ✓ | ✓ | ✗ | ? | ? |
| Артефакт-репозиторий (rpm, git, jar) | ✗ | ✗ | ✗ | ✗ | ✓ | partial |
| Аудит-логи | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Content Trust и валидация | ✓ | ✓ | ✓ | partial | partial | ✗ |
| Кастомные TLS-сертификаты | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Helm Chart Repository Manager | ✓ | ✗ | partial | ✗ | ✓ | ✗ |
| LDAP-аутентификация | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Локальная аутентификация | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Метрики | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Multi-tenancy (проекты, команды, namespaces) | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| Open Source | ✓ | partial | ✓ | ✗ | partial | partial |
| Project Quotas (по хранилищу) | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ |
| Репликация между инстансами | ✓ | ✓ | ✓ | n/a | ✗ | ✓ |
| Репликация между не-инстансами | ✓ | ✗ | ✓ | n/a | ✗ | ✗ |
| Robot-аккаунты для Helm-чартов | ✓ | ✗ | ✗ | ? | ✗ | ✗ |
| Robot-аккаунты для образов | ✓ | ? | ✓ | ? | ✗ | ? |
| RBAC | ✓ | ✓ | ✓ | ✗ | ✓ | ✗ |
| SSO (OIDC) | ✓ | ✓ | ✓ | ✗ | partial | ✗ |
| Tag Retention Policy | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ |
| Upstream Registry Proxy Cache | ✓ | ✓ | ✗ | ✓ | ✓ | ✗ |
| Сканирование уязвимостей и мониторинг | ✓ | ✓ | ✓ | ✗ | ✓ | partial |
| Фреймворк подключаемых сканеров | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ |
| Vulnerability Allowlisting | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Webhooks | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

> Сравнение Harbor с минимальным Docker Registry (проекты, RBAC, веб-интерфейс) в контексте Kubespray offline — в [шаге 3 offline-установки](../../../Kubernetes/Installation/Kubespray/offline_installation/step3_offline_env.md).

### Граничные случаи и ограничения

* **Смена auth mode**: переключение с локальной БД на OIDC невозможно, если в БД Harbor есть хотя бы один локальный пользователь (кроме admin).
* **Сканирование по MIME-типам**: сканер решает, поддерживается ли артефакт, по метаданным `consumes_mime_types` — например, Trivy не сканирует Helm-чарты. OCI image index сканируется как агрегация результатов вложенных артефактов.
* **OIDC и CLI**: Docker/Helm CLI не обрабатывают OIDC-редирект — для них используется CLI secret из профиля пользователя; если провайдер не выдаёт refresh token, секрет инвалидируется после истечения ID token (нужно перелогиниться через провайдера).
* **P2P совместимость**: Dragonfly v1 архивирован и не поддерживается; Harbor >= v2.12.0 требует Dragonfly >= v2.1.59; для Kraken нужны дополнительные настройки (ограничения его preheat API).
* **Ресурсы**: официальные минимумы (2 CPU / 4 GB) — для нагруженных offline-контуров Kubespray требуется больше (см. ссылку в разделе требований).

### Связанные документы

* **[Установка Harbor](./installation.md)** — методы развёртывания (Docker Compose, Helm, за reverse proxy).
* **[Работа с Harbor](./usage.md)** — аутентификация, тегирование и управление артефактами.
* **[Аутентификация и управление доступом](./authentication.md)** — LDAP/AD, OIDC, пользователи, imagePullSecrets.
* **[Обновление, бэкап и восстановление](./upgrade_backup.md)** — апгрейд, миграция, RPO/RTO, DR drill.
* **[Репликация артефактов](./replication.md)** — синхронизация между реестрами.
* **[Эксплуатация](./operations.md)** — производительность, алерты, аудит-логи, хранилище, runbook инцидентов.
* **[Политики безопасности](./security_policies.md)** — CVE allowlist, Deployment Security.
* **[Harbor REST API](./api.md)** — Swagger UI, пагинация, автоматизация.
* **[Создание сертификатов](./certificates.md)** — настройка TLS для безопасного доступа.
* **[Оффлайн-обновление Trivy](./offline_trivy_update.md)** — поддержка актуальности сканера в закрытых контурах.
* **[Лейблы](./labels.md)** — организация и фильтрация артефактов.
* **[SBOM](./sbom.md)** — генерация, экспорт и жизненный цикл SBOM.
* **[Multi-arch артефакты](./multi_arch.md)** — OCI image index и per-platform сканирование.
* **[P2P Preheat](./p2p_preheat.md)** — прогрев образов в Dragonfly/Kraken.
* **[Распределённая трассировка](./tracing.md)** — Jaeger/OTel-экспорт трейсов.
* **[Hardening](./hardening.md)** — защита инстанса Harbor.
* **[Хранилище: бэкенды, кэш, ёмкость](./storage.md)** — S3/Azure/GCS-бэкенды, cache layer, S3-гигиена.
* **[Миграция в Harbor](./migration.md)** — перенос образов из Docker Hub и других реестров в Harbor.
* **[Velero: Обзор](../../../Kubernetes/ToolsUtilities/velero-overview.md)** — бэкап и восстановление Harbor в Kubernetes.
* **[Offline-установка Kubespray, шаг 3](../../../Kubernetes/Installation/Kubespray/offline_installation/step3_offline_env.md)** — Harbor как единственный реестр в закрытом контуре.
