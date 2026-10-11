# Harbor: Политики безопасности проекта

**Актуально для:** Harbor 2.15.x

## Определения

* **Deployment Security**: Политика проекта, блокирующая `pull` артефактов с уязвимостями выше заданного порога критичности CVE. Включается флажком **Prevent vulnerable images from running** в конфигурации проекта.
* **CVE Allowlist**: Список CVE, которые игнорируются при проверке Deployment Security. Двух уровней: **системный** (Administration → Configuration → Security) и **проектный** (проект → Configuration → CVE allowlist). Проектный переопределяет системный.
* **Scan on Push**: Автоматическое сканирование артефакта встроенным Trivy сразу после push. Включается в конфигурации проекта.
* **Severity**: Порог критичности CVE для блокировки: `Critical`, `High`, `Medium`, `Low`, `None`, `Unknown`.
* **CVE Allowlist Expiry**: Срок действия записи в allowlist — постоянная (`Never expires`) или с датой истечения.

## Основные концепции

### Как слои политик взаимодействуют

```text
push артефакта
   │
   ├─ Scan on Push → отчёт сканирования (Trivy)
   │
   ├─ CVE Allowlist (системный → проектный)
   │     CVE из allowlist исключаются из проверки Deployment Security
   │
   └─ Deployment Security (порог severity)
         при pull: если есть CVE выше порога (за вычетом allowlist) → DENIED
```

**Критический нюанс (частая ошибка):** CVE allowlist **не удаляет уязвимости из отчёта сканирования** — он только разрешает `pull` артефакта, попадающего под Deployment Security. Отчёт в UI и Security Hub по-прежнему показывает все CVE.

Для OCI image index (multi-arch) Deployment Security проверяет **вложенные артефакты** (например, образ Redis для ARM проверяется отдельно от amd64), а не index целиком.

## Практические сценарии

### Сценарий 1: Сканирование при push и порог severity

1. Откройте проект: **Projects → myproject → Configuration**.
2. Включите **Automatically scan images on push**.
3. Включите **Prevent vulnerable images from running** (Deployment Security).
4. Установите порог severity — например, **Critical**: блокируются только образы с Critical CVE.

```bash
# Проверка отчёта сканирования через API
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject/repositories/my-app/artifacts?with_tag=true&with_scan_overview=true" | \
  jq '.[] | {tag: .tags[0].name, severity: .scan_overview."application/vnd.security.vulnerability.report; version=1.0".severity}'
# → {"tag":"v1.3.0","severity":"Critical"}
```

### Сценарий 2: Системный CVE allowlist

Для уязвимостей, признанных безопасными для всей инфраструктуры (например, CVE в пакете, который не используется в рантайме):

1. **Administration → Configuration → Security → Deployment security → Add**.
2. Введите CVE ID — списком через запятую или построчно.
3. Снимите **Never expires** и задайте дату истечения, если запрет временный.
4. **Save**.

> Системный allowlist применяется ко всем проектам по умолчанию.

### Сценарий 3: Проектный CVE allowlist с expiry

Для временного разрешения конкретного образа в конкретном проекте (типичный кейс: исправление запланировано через спринт):

1. **Projects → myproject → Configuration → CVE allowlist → Project allowlist**.
2. Опционально **Copy From System** — скопировать текущий системный список.
3. **Add** — введите CVE ID (через запятую или построчно).
4. Снимите **Never expires**, задайте дату истечения (например, дату следующего патч-окна).
5. **Save**.

```bash
# Проектный allowlist (поле cve_allowlist в деталях проекта)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject" | jq '.cve_allowlist'
# → {"items":[{"cve":"CVE-2024-XXXX","expire_at":"2026-11-01T00:00:00Z"}]}

# Переиспользование системного allowlist (metadata проекта)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject/metadatas/reuse_sys_cve_allowlist" | jq .
```

### Сценарий 4: Тестирование блокировки pull

```bash
# 1. Образ с Critical CVE (не в allowlist)
docker pull harbor.corp.local/myproject/vulnerable-app:v1.0
# → Error response from daemon: ... is blocked by deployment security policy

# 2. Добавление CVE в проектный allowlist (см. сценарий 3)

# 3. Повторный pull — разрешён
docker pull harbor.corp.local/myproject/vulnerable-app:v1.0
# → Status: Downloaded newer image for ...

# 4. После истечения срока allowlist pull снова блокируется
```

## Валидация

```bash
# Конфигурация проекта (scan on push, deployment security)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/projects/myproject" | \
  jq '.metadata | {auto_scan: .auto_scan, severity: .severity, prevent_vul: .prevent_vul}'
# → {"auto_scan":true,"severity":"Critical","prevent_vul":true}

# Системный allowlist (эндпоинт /system/CVEAllowlist)
curl -sk -u "admin:$PASS" \
  "https://harbor.corp.local/api/v2.0/system/CVEAllowlist" | jq .

# Pull заблокирован политикой (код ошибки в отчёте)
docker pull harbor.corp.local/myproject/vulnerable-app:v1.0 2>&1 | grep -i "deployment security"
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Pull блокируется, хотя CVE в allowlist | CVE добавлен в системный, а проект переопределяет список | Добавьте CVE в проектный allowlist или используйте Copy From System |
| Allowlist не работает | CVE ID введён с опечаткой | Проверьте формат `CVE-YYYY-NNNN`; валидация ID на этапе добавления |
| CVE «пропал» из отчёта после allowlist | Так не должно быть | Allowlist не скрывает CVE из отчётов — проверьте отчёт сканирования |
| Блокируется multi-arch образ | Уязвимость в одной из платформ | Deployment Security проверяет вложенные артефакты index; проверьте отчёт по каждой платформе |
| Scan on push не запускается | Сканер не установлен | Установите Harbor с `--with-trivy` или `trivy.enabled: true` в Helm |
| Severity в отчёте `Unknown` | Нет данных о CVE | Обновите базы Trivy (см. [оффлайн-обновление](./offline_trivy_update.md)) |

## Best Practices

### Проектирование политик и гигиена allowlist

* **Severity-порог по умолчанию — Critical** в production; по мере зрелости процесса можно снизить до High. Блокировка Medium/Low без автоматизации remediation создаёт backlog уязвимостей, который игнорируется.
* **Задавайте allowlist на уровне проекта**, а не системном, когда причина уязвимости специфична для контекста проекта. Системный allowlist — для истинно инфраструктурных исключений.
* **Документируйте каждую запись allowlist** с тикетом, владельцем и плановой датой исправления. `Never expires` в production — антипаттерн, за исключением well-known статических бинарных зависимостей (например, CVE в busybox, которые не вызывают код проекта).
* **Immutable tags** ([usage.md](./usage.md#сценарий-8-управление-жизненным-циклом-retention--immutable)) и **content trust** (Cosign/Notation) — отдельные слои защиты, дополняющие Deployment Security. Content trust гарантирует происхождение артефакта; Deployment Security — его безопасность. Включайте оба в production.

### Интеграция с CI/CD и автоматизация gate

* **Webhook `SCANNING_COMPLETED`** — настраивайте на проект или системный webhook, чтобы блокировать deployment-pipeline при появлении Critical CVE после push. Payload содержит `severity` и `cve_ids`; CI-система (Jenkins, GitLab CI, ArgoCD) может отклонить деплой.
* **API-проверка перед деплоем** — в pipeline запрашивайте отчёт сканирования через [Harbor REST API](./api.md) и отклоните артефакт, если он содержит CVE выше порога. Альтернатива: CLI [harbor-cli](https://github.com/goharbor/harbor-cli) — команды `harbor cve-allowlist list/add/remove` для управления allowlist из пайплайна.
* **Content trust как prerequisite**: если в проекте включён `Only signed images`, то Deployment Security применяется только к подписанным артефактам. Неподписанные артефакты отклоняются до сканирования.

### Мониторинг и оповещения

* **Алерт на застрявшее сканирование** — метрика `harbor_task_queue_size` (операции `scan` и `scan_all`) в сочетании с `harbor_up{component="trivy-adapter"}`. Если очередь растёт, а адаптер down — сканирование не работает, и Deployment Security не имеет данных для принятия решений.
* **Security Hub как источник истины для новых CVE** — регулярно проверяйте Dashboard (Administration → Security → Vulnerability) или экспортируйте данные через API для SIEM. Рост числа Critical CVE в production-проектах за неделю — инцидент SRE.
* **Аудит-лог изменений политик** — каждый `POST/PUT /api/v2.0/projects/<name>/metadatas` или `PUT /api/v2.0/system/CVEAllowlist` записывается в аудит-лог (`GET /api/v2.0/auditlog-exts`). Ротируйте логи в SIEM и алертите на изменения allowlist неавторизованными аккаунтами.

### Свежесть баз Trivy

* **Air-gapped: синхронизируйте базы не реже раза в неделю** — интервал обновления Trivy DB в `metadata.json` по умолчанию 24 часа; устаревшая база даёт false negatives (пропуск CVE) и `schema mismatch` при несовпадении версий. Процедура — в [offline_trivy_update.md](./offline_trivy_update.md).
* **При апгрейде Harbor проверяйте совместимость версий Trivy и адаптера** — несоответствие приводит к `database error: schema mismatch` и пустым отчётам. Актуальную матрицу версий — в репозитории [harbor-scanner-trivy](https://github.com/goharbor/harbor-scanner-trivy).
* **Не пропускайте сканирование из-за нагрузки** — `scan_all_policy` (Administration → Configuration → Scanning) запускает фоновое полное сканирование проектов. Если jobservice перегружен, приоритизируйте production-проекты.

### Управление изменениями и инциденты

* **Никогда не отключайте Deployment Security в production** на постоянной основе — даже при инциденте используйте проектный allowlist с коротким expiry вместо глобального отклюжения.
* **Ротация allowlist-записей**: еженедельный обзор проектных allowlist на предмет просроченных записей. Просроченная запись автоматически восстанавливает блокировку — это safety mechanism, а не баг.
* **Runbook на блокировку pull** — если Deployment Security блокирует критичный deploy, стандартный ответ: (1) проверить, не stale ли DB Trivy; (2) если CVE подтверждён и исправление готово — перетегнуть образ; (3) если CVE ложноположительный — добавить в allowlist с expiry на 24–48 часов; (4) ни в коем случае не снижать severity-порог глобально.

## Граничные случаи

* **Allowlist с expiry** — после истечения даты CVE снова блокирует pull; мониторьте даты в Security Hub.
* **Copy From System** односторонний: удаление CVE из системного allowlist **не** удаляет его из проектного — удаляйте вручную.
* **Deployment Security не влияет на push** — блокируется только pull; «врата безопасности» работают на этапе развёртывания, а не сборки.
* **Trivy не сканирует Helm-чарты** — сканер выбирает артефакты по `consumes_mime_types` (см. [обзор](./overview.md)). Для контроля качества Helm-чартов, хранящихся в Harbor, используйте внешние инструменты в CI-пайплайне (Harbor сам не выполняет их):
  * **`helm lint`** — валидация структуры чарта и значений (входит в Helm).
  * **`trivy config`** — анализ манифестов/Kustomize/Helm-шаблонов на ошибки конфигурации (misconfiguration).
  * **`kube-linter`** — статический анализ чартов на best practices Kubernetes.
  
  Сравнение инструментов SCA и статического анализа — в [sca_tools_comparison.md](../../../Security/Supply_Chain_Security/sca_tools_comparison.md); best practices подов, которые проверяет kube-linter, — в [pod_best_practices.md](../../../Kubernetes/Base/Pod/pod_best_practices.md).
* **Immutable теги** (см. [работу с Harbor](./usage.md#сценарий-8-управление-жизненным-циклом-retention--immutable)) дополняют политику: гарантируют, что тег не перезапишут уязвимой версией.
* **Content trust + Deployment Security — комплементарные слои**: включение `Only signed images` (Cosign/Notation) не отменяет необходимость Deployment Security — подписанный артефакт может содержать Critical CVE. Оба слоя работают независимо; для атомарного gate используйте webhook `SCANNING_COMPLETED` в CI.
* **Устаревшая DB Trivy в air-gapped**: при `skip_update: true` устаревшая база даёт false negatives (пропуск CVE) или `schema mismatch` при несовпадении версий. Deployment Security работает без данных — блокировка не срабатывает. Синхронизируйте базы через [offline_trivy_update.md](./offline_trivy_update.md).
* **Self-registration и CVE-2019-16097**: исторический прецедент — в Harbor 1.7.0–1.8.2 с включённой self-registration не-admin мог создать учётку с admin-правами. Никогда не включайте self-registration в production без контроля RBAC (см. [hardening.md](./hardening.md)).
* **Proxy cache и сканирование**: pull-through кэш не запускает scan-on-push для закэшированных артефактов. Уязвимости кэшируются «как есть» из upstream. При включённом Deployment Security целевой реестр проверяет артефакт при pull из кэша.
* **Harbor CLI для allowlist**: автоматизируйте управление через [harbor-cli](https://github.com/goharbor/harbor-cli): `harbor cve-allowlist list`, `harbor cve-allowlist add <cve>`, `harbor cve-allowlist remove <cve>`. Подробнее — [Harbor REST API](./api.md).
* **Security Hub в SIEM**: экспортируйте данные уязвимостей через API для корреляции с данными хостовых сканеров (Wazuh, Nessus). Разница между Harbor-отчётом и данными сканера — индикатор пропущенных образов.
* **PostgreSQL 18 и reindexdb (начиная с Harbor 2.15.2)**: при автоматическом обновлении embedded PostgreSQL с 15 на 18 в не-ASCII средах возможна коррупция B-Tree индексов, что проявляется как пустые списки в UI (включая Security Hub) или `robot account permission failures`. Исправление — `reindexdb --all-databases -U postgres` в окне обслуживания (см. [установку](./installation.md)).

## Дополнительная информация

* Официальная документация: [Deployment Security](https://goharbor.io/docs/2.15.2/administration/vulnerability-scanning/deployment-security/), [System-Wide CVE Allowlists](https://goharbor.io/docs/2.15.2/administration/vulnerability-scanning/configure-system-allowlist/), [Per-Project CVE Allowlist](https://goharbor.io/docs/2.15.2/working-with-projects/project-configuration/configure-project-allowlist/).
* **Методология анализа CVE и Trivy** — [Сканирование уязвимостей](../../Docker_security/vulnerability_scanning.md).
* **Security Hub** — сводный обзор уязвимостей инстанса (см. [обзор](./overview.md)).
* **Hardening инстанса** — [hardening.md](./hardening.md) (политики безопасности как слой защиты Harbor).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — модель безопасности.
* **[Работа с Harbor](./usage.md)** — immutable теги, retention.
* **[Оффлайн-обновление Trivy](./offline_trivy_update.md)** — актуальность баз CVE.
* **[Подписи образов](../../Docker_security/image_signature_and_verification.md)** — Cosign/Notation как второй слой политики.
* **[SBOM](./sbom.md)** — инвентаризация компонентов артефакта.
* **[Hardening](./hardening.md)** — защита самого инстанса Harbor.
