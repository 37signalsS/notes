# Harbor: Вопросы на собеседованиях

**Актуально для:** Harbor 2.15.x; ответы верифицированы по документации Harbor (goharbor.io/docs/2.15.0) и спецификации API v2.0 (swagger.yaml)

## Определения

**Задачи этого файла** — краткие, точные ответы на типичные вопросы DevOps/SRE-собеседований по Harbor. Каждый ответ содержит ключевой факт и, где нужно, команду для проверки. Теория и практика — в смежных файлах (ссылки в конце).

## Базовые концепции

**Q: Чем Harbor отличается от Docker Registry?**
A: Harbor — enterprise-реестр поверх Docker Distribution: проекты (multi-tenancy), RBAC (Guest/Developer/Project Admin), аутентификация через LDAP/AD и OIDC, сканирование уязвимостей (Trivy), репликация между реестрами, retention/GC, квоты проектов, аудит-лог, метрики Prometheus, веб-UI. Docker Registry — только хранение образов без UI, RBAC и сканирования. Проверка компонентов: `curl -sk https://harbor.local/api/v2.0/health` → `{"status":"healthy"}`.

**Q: Из каких компонентов состоит Harbor?**
A: Proxy (Nginx — точка входа), Portal (UI), Core (проекты, RBAC, аутентификация, квоты, webhooks), Job Service (фоновые задачи: репликация, сканирование, GC, P2P preheat), Registry (модифицированный Docker Distribution), Registryctl (конфигурация Registry), PostgreSQL (метаданные), Redis (кэш и очереди), Scanner (Trivy-адаптер). Статус компонентов — метрика `harbor_up{component=...}`: core, database, jobservice, portal, redis, registry, registryctl, trivy.

**Q: Что такое проект в Harbor?**
A: Основная единица организации: группирует репозитории, пользователей и политики. Публичный (анонимный pull) или приватный (требуется роль Guest+). На проект накладываются квоты, retention, immutable-теги, Deployment Security. Системный проект `library` — публичный, принадлежит администратору.

**Q: Чем digest отличается от тега и почему важно?**
A: Digest (`sha256:...`) — хеш манифеста, неизменяемый идентификатор содержимого. Тег перезаписываем (если не включён Immutable Tag): `app:v1` может указывать на разный контент после ретега. Для гарантии неизменности — ссылайтесь на образ по digest (`docker pull harbor.local/prod/app@sha256:...`), подписывайте по digest, в манифестах деплоя используйте digest.

**Q: Что такое OCI image index (multi-arch) в Harbor?**
A: Манифест верхнего уровня, ссылающийся на дочерние манифесты для разных платформ (linux/amd64, linux/arm64). Harbor 2.0+ управляет index как артефактом: в списке артефактов — папка-иконка рядом с digest; OCI-артефакт кликабелен и показывает дочерние элементы. Deployment Security проверяет вложенные артефакты per-platform, а не index целиком. Подробнее — [multi_arch.md](./multi_arch.md).

## Аутентификация и доступ

**Q: Какие режимы аутентификации поддерживает Harbor? А SAML?**
A: Три режима: Database (локальная PostgreSQL), LDAP/AD, OIDC. **SAML не поддерживается** — для SAML-окружений нужен IdP-брокер (например, Dex, предъявляемый Harbor как OIDC-провайдер). Смена auth mode с Database на LDAP/OIDC заблокирована, если в БД есть локальные пользователи (кроме `admin`). Проверка: `curl -sk https://harbor.local/api/v2.0/systeminfo | jq .auth_mode`.

**Q: Что такое робот-аккаунт и зачем он в CI/CD?**
A: Сервисный аккаунт, привязанный к проекту: формат логина `robot$<project>+<name>`, права только на конкретный проект (Pull/Push; Push требует Pull), не может входить в UI — только API и CLI. Секрет показывается **один раз** при создании и нигде не хранится; утерянный восстанавливается через Refresh Secret (старый немедленно отменяется). Принцип least privilege для автоматизации.

**Q: Почему `docker login` не работает для OIDC/LDAP-пользователя?**
A: Docker/Helm CLI не обрабатывают OIDC-редирект — для них используется **CLI Secret** из профиля пользователя в Harbor Portal. Если провайдер не выдаёт refresh token (scope `offline_access`), CLI Secret инвалидируется после истечения ID token — нужно перелогиниться через провайдера.

**Q: Как kubelet загружает образы из приватного проекта Harbor?**
A: Через `imagePullSecret` (Secret типа `docker-registry`) или инъекцию в ServiceAccount: `kubectl patch serviceaccount default -n prod -p '{"imagePullSecrets":[{"name":"harbor-pull"}]}'`. Ротация секрета требует перезапуска подов — kubelet кэширует учётные данные до пересоздания Pod.

## Безопасность

**Q: Что такое Deployment Security?**
A: Политика проекта, блокирующая `pull` артефактов с CVE выше заданного порога severity (Critical/High/Medium/Low/None/Unknown). Включается флажком **Prevent vulnerable images from running**. Влияет **только на pull**, не на push — «врата безопасности» работают на этапе развёртывания. Для OCI image index проверяются вложенные артефакты per-platform.

**Q: Что такое CVE allowlist и как он взаимодействует с отчётом сканирования?**
A: Список CVE, игнорируемых при проверке Deployment Security. Два уровня: системный (Administration → Configuration → Security) и проектный; проектный переопределяет системный. Запись может быть постоянной или с датой expiry. **Ключевой нюанс:** allowlist не удаляет CVE из отчёта сканирования — отчёт и Security Hub по-прежнему показывают все уязвимости; allowlist только разрешает pull.

**Q: Почему включённая self-registration — риск?**
A: Исторический пример: CVE-2019-16097 (Harbor 1.7.0–1.8.2) — не-admin мог создать учётку с admin-правами через `POST /api/users` с полем `has_admin_role: true` при включённой self-registration. Исправлено в 1.7.6/1.8.3. Self-registration по умолчанию **выключена**; включать только в Database-режиме и только при необходимости. Урок: Harbor не защищён «из коробки» — оператор должен явно настраивать RBAC (SECURITY.md проекта). Чек-лист — [hardening.md](./hardening.md).

**Q: Как подписываются образы в Harbor?**
A: Cosign или Notation; Harbor 2.11+ хранит подписи как OCI 1.1 Referrers (без дополнительных тегов). Подписывать нужно **по digest** (тег перезаписываем). Принудительная верификация включается в конфигурации проекта (Cosign/Notation) — тогда pull доступен только для образов с валидной подписью. Практика — [usage.md, сценарий 4](./usage.md#сценарий-4-подпись-образа-с-помощью-cosign).

## Жизненный цикл артефактов

**Q: Чем Retention Policy отличается от Garbage Collection?**
A: Retention **помечает** артефакты как неиспользуемые по правилам (число тегов, возраст, фильтры); GC **физически удаляет** помеченное из хранилища. Место на диске освобождается только после GC. Особенности GC: работает без остановки Harbor; не удаляет артефакты, загруженные за последние 2 часа; остановка GC **не восстанавливает** уже удалённое; опция `delete_untagged` разрешает удаление артефактов без тегов.

**Q: Что такое Immutable Tag?**
A: Настройка проекта, запрещающая перезапись существующего тега по паттерну (например, `v*`, `release-*`). Гарантирует, что тег всегда указывает на один и тот же артефакт. Дополняет Deployment Security: без immutable тег уязвимую версию можно перезаписать «исправленной», но история развёртываний теряется.

**Q: Как работает репликация артефактов?**
A: Синхронизация между реестрами (Harbor↔Harbor или Harbor↔внешний). Два направления: push-based (из Harbor в целевой) и pull-based (из исходного в Harbor). Правило: endpoint (URL + учётные данные, лучше робот-аккаунт), фильтры (проект, тег, лейбл, тип ресурса — комбинируются AND), триггер (manual / event-based / scheduled cron), политика override. Артефакт передаётся **по digest**. Параллелизм ограничен `jobservice.max_job_workers` (дефолт 10). Подробнее — [replication.md](./replication.md).

**Q: Чем Proxy Cache отличается от Replication?**
A: Proxy Cache — pull-only кэш upstream-реестра (Docker Hub, Quay, ECR): обходит rate limits, кэширует слои локально; push в проект-кэш отклоняется. Replication — полноценная синхронизация с фильтрами, триггерами и перезаписью, в обоих направлениях.

## Эксплуатация (SRE)

**Q: Какие метрики экспортирует Harbor и как их включить?**
A: Включаются в `harbor.yml` (`metric.enabled: true`, порт 9090, путь `/metrics` — с Harbor 2.2) или `metrics.enabled: true` в Helm. Ключевые: `harbor_up{component}`, `harbor_health`, `harbor_artifact_pulled{project_name}`, `harbor_project_quota_usage_byte{project_name}`, `harbor_task_queue_size{instance,job,type}`, `harbor_task_queue_latency`, `harbor_core_http_request_total`, `registry_http_requests_total`, `harbor_jobservice_task_total`. Полный справочник — [operations.md, сценарий 2](./operations.md#сценарий-2-мониторинг-и-алерты-prometheus).

**Q: Как включить debug-логирование Harbor?**
A: `log.level: debug` в `harbor.yml` (уровни: debug, info, warning, error, fatal; дефолт info), затем `./prepare` и перезапуск контейнеров. Логи — `/var/log/harbor/` (параметр `log.location`). Возвращайте `info` после диагностики — debug сильно увеличивает объём логов.

**Q: Как обновить базы Trivy в air-gapped-контуре?**
A: `trivy.skip_update: true` + `skip_java_db_update: true` в `harbor.yml`; на хосте с интернетом скачать базы (`oras pull ghcr.io/aquasecurity/trivy-db:2` и `trivy-java-db:1`), распаковать `trivy.db` + `metadata.json` в `/data/trivy-adapter/trivy/db` и `.../java-db`, `chown -R 10000:10000` (пользователь `scanner`), `./prepare && docker compose up -d`. Пошагово — [offline_trivy_update.md](./offline_trivy_update.md).

**Q: Как бэкапить Harbor и почему откат после апгрейда возможен только из бэкапа?**
A: Docker Compose: при остановленном инстансе — `harbor.yml`, директория установщика и `data_volume` (дефолт `/data`: БД, registry, Redis, кэш Trivy). Kubernetes — Velero. Внешняя PostgreSQL — `pg_dump`. Миграция схемы БД при апгрейде **необратима** — старая версия не прочитает мигрированную БД, поэтому откат = восстановление бэкапа, сделанного до апгрейда. Сценарии — [upgrade_backup.md](./upgrade_backup.md).

**Q: Что такое DR drill для реестра?**
A: Плановая тренировка восстановления из бэкапа в изолированной среда — единственный способ проверить, что бэкап рабочий. Для Harbor: развернуть чистый инстанс той же версии, восстановить `harbor.yml` + `data_volume` + БД, выполнить smoke-тест (login, push, pull, сканирование). Сценарий — [upgrade_backup.md, сценарий 7](./upgrade_backup.md#сценарий-7-dr-drill-тренировка-восстановления).

## API и автоматизация

**Q: Как работает пагинация в Harbor API?**
A: Все списковые эндпоинты принимают `page` и `page_size`; ответ содержит заголовки `X-Total-Count` (общее число записей) и `Link` (URL prev/next). Скрипты должны итерировать страницы, пока `jq 'length'` < `page_size`. Фильтры — параметр `q` (синтаксис различается по эндпоинтам, смотрите в Swagger UI).

**Q: Как запустить Garbage Collection через API?**
A: `POST /api/v2.0/system/gc` с телом `{"delete_untagged":false}` → `201 Created`; история задач — `GET /api/v2.0/system/gc`. Перед реальным GC — DRY RUN в UI (Administration → Clean Up → Garbage Collection). Удаление артефакта через API (`DELETE .../artifacts/<digest>`) возвращает `200`, но место освобождается только после GC.

**Q: Как автоматизировать retention через API?**
A: `GET /api/v2.0/retentions/metadatas` — доступные шаблоны правил и селекторы; `POST /api/v2.0/retentions` — создание политики (только когда к проекту не привязана другая); `POST /api/v2.0/retentions/{id}/executions` — запуск выполнения (с `dry_run: true` для превью); `GET /api/v2.0/retentions/{id}/executions/{eid}/tasks` — задачи выполнения. Примеры — [usage.md, сценарий 8](./usage.md#сценарий-8-управление-жизненным-циклом-retention--immutable).

## Интеграция и supply chain

**Q: Как Harbor интегрируется в CI/CD пайплайн?**
A: Типовая цепочка: сборка → push в Harbor (робот-аккаунт) → scan on push → webhook `PUSH_ARTIFACT` (payload Default или CloudEvents) уведомляет CI/Jenkins/ArgoCD → репликация Dev→Prod (event-based) → Deployment Security блокирует pull образов с Critical CVE в Production. Webhook payload: `{"type":"PUSH_ARTIFACT","occur_at":...,"operator":"...","event_data":{"resources":[{"digest","tag","resource_url"}],"repository":{...}}}`.

**Q: Что такое SBOM в Harbor?**
A: С Harbor 2.11 — автоматическая генерация SBOM встроенным Trivy при push (включается в конфигурации проекта) или вручную (кнопка GENERATE SBOM). SBOM хранится как OCI-артефакт, привязанный к образу; в UI — таблица «пакет / версия / лицензия» и скачивание в формате SPDX. Физически удаляется при GC; реплицируется вместе с артефактом. Подробнее — [sbom.md](./sbom.md).

**Q: Что такое P2P preheat и когда он нужен?**
A: Прогрев образов в P2P-сетях Dragonfly или Kraken по политике — критично для крупных инсталляций с тысячами узлов: слои раздаются peer-to-peer, минуя центральный registry. Триггеры: manual, scheduled (cron), event-based (OnPush, OnScanComplete, OnLabel). Совместимость: Harbor ≥2.12.0 требует Dragonfly ≥2.1.59. Настройка — [p2p_preheat.md](./p2p_preheat.md).

**Q: Как Harbor вписывается в GitOps (ArgoCD Image Updater / Flux)?**
A: Image Updater и Flux image-automation-controller опрашивают Harbor API на новые теги (учётные данные — робот-аккаунт в Secret) и обновляют манифесты в Git. Harbor-сторона: webhook `PUSH_ARTIFACT` может дёргать webhook-receiver Image Updater для немедленной реакции. Инструменты описаны в [ArgoCD Image Updater](../../../GitOps/ArgoCD/argocd_image_updater.md) и [Flux](../../../GitOps/flux.md); Harbor-специфичная связка — [replication.md](./replication.md#harbor-и-автоматизация-обновления-образов-argocd-image-updater--flux).

## Дополнительная информация

### Ссылки на смежные темы

* **[Обзор Harbor](./overview.md)** — архитектура, компоненты, сравнение с аналогами.
* **[Установка](./installation.md)** — Docker Compose, Helm, HA.
* **[Аутентификация](./authentication.md)** — LDAP/AD, OIDC, RBAC, imagePullSecrets.
* **[Работа с реестром](./usage.md)** — robot-аккаунты, push/pull, Cosign, webhooks, retention, GC.
* **[Лейблы артефактов](./labels.md)** — управление лейблами и их роль в фильтрах.
* **[SBOM](./sbom.md)** — генерация и управление SBOM.
* **[Multi-arch артефакты](./multi_arch.md)** — OCI image index в Harbor.
* **[P2P Preheat](./p2p_preheat.md)** — Dragonfly/Kraken.
* **[Распределённая трассировка](./tracing.md)** — Jaeger/OpenTelemetry.
* **[Hardening](./hardening.md)** — чек-лист защиты инстанса.
* **[Эксплуатация](./operations.md)** — метрики, аудит, тюнинг, runbook инцидентов.
* **[Репликация](./replication.md)** — синхронизация между реестрами.
* **[Политики безопасности](./security_policies.md)** — Deployment Security, CVE allowlists.
* **[Обновление, бэкап и восстановление](./upgrade_backup.md)** — апгрейд, DR drill, Velero.
* **[Harbor REST API](./api.md)** — Swagger, пагинация, автоматизация.
