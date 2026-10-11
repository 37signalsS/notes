# Harbor: P2P Preheat (Dragonfly, Kraken)

**Актуально для:** Harbor 2.15.x; Dragonfly ≥ v2.1.59 (для Harbor ≥ v2.12.0)

## Определения

* **P2P Preheat**: Механизм предварительного прогрева образов в P2P-сети распределения (Dragonfly или Uber Kraken) по политике в Harbor. Образы кэшируются в P2P-движке до того, как узлы кластера начнут их запрашивать.
* **Preheat Provider Instance**: Учётная запись P2P-движка в Harbor: endpoint preheat API, режим аутентификации, учётные данные. Создаётся системным администратором; одна instance может использоваться политиками всех проектов.
* **Preheat Policy**: Правило прогрева в проекте: фильтры ресурсов, критерии отбора, provider instance и триггер. Создаётся администратором проекта.
* **Event-based Preheat**: Триггер по событию: `OnPush` (push артефакта), `OnScanComplete` (успешное сканирование), `OnLabel` (присвоение лейбла). При событии запускается evaluation-процесс, который обходит политики проекта и выполняет подходящие.
* **Evaluation Process**: Процесс, который при событии обходит event-based политики проекта и выполняет совпавшие политики для конкретного артефакта (прогрев начинается не мгновенно, а после оценки).

## Основные концепции

### Зачем preheat в продакшене

| Сценарий | Без preheat | С preheat |
| :--- | :--- | :--- |
| Массовый запуск (1000+ реплик) | Все узлы тянут слои с registry — пиковая нагрузка на registry и сеть | Слои уже в P2P-сети; узлы получают их peer-to-peer |
| Rollout нового образа | Холодный старт, таймауты pull | Образ прогрет по событию OnPush до начала деплоя |
| Периодическая раздача базовых образов | Каждый узел тянет из registry | Scheduled-прогрев по cron |

P2P-движок раздаёт слои между узлами, минуя центральный registry — критично для крупных инсталляций (теория P2P-дистрибуции — в [artifact_management.md](../../../CI-CD/artifact_management.md)).

### Критерии отбора артефактов

Критерии **наследуются из конфигурации проекта** и не могут быть изменены в самой политике (единственный способ изменить — конфигурация проекта):

* **Only signed images** — доступен, если в проекте включён content trust (принудительная верификация подписей); прогреваются только подписанные артефакты.
* **No vulnerability severity of [severity] and above** — доступен, если в проекте включён Deployment Security (Prevent vulnerable images from pulling); прогреваются только артефакты, удовлетворяющие порогу severity.

Если настройки проекта не заданы — критерии скрыты в политике и не влияют на отбор.

### Совместимость версий

| Harbor | Dragonfly |
| :--- | :--- |
| ≥ v2.12.0 | ≥ v2.1.59 |
| < v2.12.0 | ≥ v1.0.5, < v2.1.59 |

* Dragonfly v1 архивирован и не поддерживается; v2 не совместим с v1.
* Kraken (v0.1.3+): из-за ограничений его preheat API требуются дополнительные шаги конфигурации (см. руководство Kraken).

## Практические сценарии

### Сценарий 1: Установка P2P-движка (Dragonfly)

P2P-движок устанавливается отдельно от Harbor — следуйте официальному руководству Dragonfly ([d7y.io/docs](https://d7y.io/docs/next/)) или Kraken. Harbor интегрируется с уже развёрнутым движком через его preheat API.

Для Dragonfly с самоподписанными сертификатами Harbor: в конфигурации Dragonfly Manager (`/etc/dragonfly/manager.yaml`) добавьте CA-сертификат Harbor (`yourdomain.crt` — это `ca.crt` Harbor).

### Сценарий 2: Создание provider instance (системный админ)

1. **Administration → Distributions → +NEW INSTANCE**.
2. Параметры:

| Параметр | Пример | Назначение |
| :--- | :--- | :--- |
| **Provider** | `Dragonfly` / `Kraken` | Тип P2P-движка |
| **Name** | `dragonfly-prod` | Идентификатор instance |
| **Preheat API Endpoint** | `http://dragonfly-manager:8080` | Endpoint preheat API движка |
| **Auth Mode** | `NONE` / `Basic` / `OAuth` | Аутентификация в preheat API |
| **Credentials** | username/password или bearer token | Учётные данные (для Dragonfly OAuth — personal access token Dragonfly Manager) |
| **Enable** | включено | Instance активна |
| **Skip certificate verification** | выключено | Только для самоподписанных сертификатов |

3. **TEST CONNECTION** — проверка связности.
4. **OK** — сохранение. Статус instance отображается как **Healthy** (зелёный).

### Сценарий 3: Создание политики прогрева (администратор проекта)

1. **Projects → myproject → P2P Preheat → +NEW POLICY**.
2. Параметры:

| Параметр | Пример | Назначение |
| :--- | :--- | :--- |
| **Provider** | `dragonfly-prod` | Provider instance из сценария 2 |
| **Filters** | проект/репозиторий, теги (`v*`), лейблы | Какие артефакты прогревать |
| **Criteria** | (унаследованы из конфигурации проекта) | Only signed images / No vulnerability severity |
| **Trigger** | `Manual` / `Scheduled` / `Event-based` | Когда запускается |

3. Триггеры:
   * **Manual** — запуск администратором.
   * **Scheduled** — cron (например, `*/15 0 * * *` — каждые 15 минут в полночь).
   * **Event-based** — `OnPush`, `OnScanComplete`, `OnLabel`.
4. **ADD** — сохранение политики.

### Сценарий 4: Мониторинг выполнений

* **Projects → myproject → P2P Preheat** — список политик и деталей выполнений с логами.
* Каждое выполнение политики записывается Harbor — можно ревьювать историю прогрева.
* Статус provider instance: **Administration → Distributions** — колонка статуса (Healthy / недоступен).

## Валидация

```bash
# 1. Provider instance Healthy: Administration → Distributions (UI)

# 2. Тест подключения пройден (TEST CONNECTION при создании)

# 3. Политика выполнилась: Projects → myproject → P2P Preheat → executions
#    (статус выполнения и логи)

# 4. Образ в P2P-сети: первый pull узла кластера не грузит registry
#    (проверяется в метриках Dragonfly Manager / логах seed peer)
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Provider instance не Healthy | Неверный endpoint, сеть, учётные данные, сертификат | Проверьте endpoint preheat API, доступность порта, Auth Mode; при самоподписанном TLS — Skip certificate verification или добавьте CA в Dragonfly Manager |
| Политика не выполняется по событию | Артефакт не проходит критерии (подпись/severity) или фильтры | Критерии наследуются из конфигурации проекта — проверьте content trust и Deployment Security проекта; проверьте фильтры политики |
| Прогрев не запускается при push | Триггер не event-based или событие не OnPush | Проверьте тип триггера в политике |
| Kraken не прогревает | Ограничения preheat API Kraken | Дополнительные шаги конфигурации Kraken (см. руководство Kraken) |
| Нельзя удалить provider instance | На instance ссылаются политики | Удалите все политики, использующие instance, затем удалите instance |
| Ошибка совместимости Dragonfly | Harbor ≥2.12 с Dragonfly <2.1.59 | Обновите Dragonfly до ≥2.1.59 |

## Граничные случаи

* **Критерии нельзя переопределить в политике** — только через конфигурацию проекта (content trust, Deployment Security).
* **Событие OnLabel** срабатывает при присвоении лейбла артефакту (см. [labels.md](./labels.md)); снятие лейбла событием не является.
* **Evaluation-процесс** при event-based триггере: прогрев начинается не мгновенно, а после оценки политик — задержка в секунды.
* **Dragonfly v1 архивирован** — для новых инсталляций только Dragonfly v2 (≥2.1.59 для Harbor ≥2.12).
* **Preheat ≠ Proxy Cache**: preheat прогревает P2P-сеть по политике; proxy cache — pull-only кэш upstream-реестра (см. [usage.md, сценарий 6](./usage.md#сценарий-6-настройка-proxy-cache-pull-through-cache)).

## Операции и команды

### CLI (harbor-cli)

```bash
# Управление provider instance (системный админ)
harbor instance preheat provider list
harbor instance preheat provider create --name dragonfly-prod --provider dragonfly --endpoint http://dragonfly-manager:8080 --auth-mode basic --username admin --password "***"
harbor instance preheat provider get dragonfly-prod
harbor instance preheat provider update dragonfly-prod --endpoint http://new-dragonfly-manager:8080
harbor instance preheat provider delete dragonfly-prod

# Управление политиками (администратор проекта)
harbor project preheat policy list --project myproject
harbor project preheat policy create --project myproject --name preheat-v1 --provider dragonfly-prod --filter '{"repository": "myproject/app", "tag": "v*"}' --trigger manual
harbor project preheat policy create --project myproject --name preheat-scheduled --provider dragonfly-prod --trigger scheduled --cron "*/15 0 * * *"
harbor project preheat policy create --project myproject --name preheat-onpush --provider dragonfly-prod --trigger event-based --event onpush
harbor project preheat policy get --project myproject preheat-onpush
harbor project preheat policy delete --project myproject preheat-onpush

# Запуск и мониторинг выполнений
harbor project preheat execution list --project myproject --policy preheat-onpush
harbor project preheat execution run --project myproject --policy preheat-onpush --artifact sha256:abc123...
harbor project preheat execution get --project myproject <execution-id>
```

### API (прямые вызовы для автоматизации)

```bash
# Список provider instances
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/preheat/providers"

# Создание provider instance (Dragonfly OAuth)
curl -sk -u "admin:$PASS" -X POST "https://harbor.corp.local/api/v2.0/preheat/providers" \
  -H "Content-Type: application/json" -d '{
    "name": "dragonfly-prod",
    "vendor_type": "dragonfly",
    "endpoint": "http://dragonfly-manager:8080",
    "auth_mode": "oauth",
    "credential": {"access_token": "dragonfly-personal-access-token"},
    "enabled": true,
    "insecure": false
  }'

# Список политик проекта
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/projects/myproject/preheat/policies"

# Создание event-based политики (OnPush)
curl -sk -u "admin:$PASS" -X POST "https://harbor.corp.local/api/v2.0/projects/myproject/preheat/policies" \
  -H "Content-Type: application/json" -d '{
    "name": "preheat-onpush",
    "provider_name": "dragonfly-prod",
    "trigger": {"type": "event_based", "event_type": "onpush"},
    "filters": [{"type": "repository", "value": "myproject/*"}, {"type": "tag", "value": "v*"}],
    "enabled": true
  }'

# Запуск политики вручную для конкретного артефакта
curl -sk -u "admin:$PASS" -X POST "https://harbor.corp.local/api/v2.0/projects/myproject/preheat/policies/preheat-onpush/executions" \
  -H "Content-Type: application/json" -d '{"artifact_digest": "sha256:abc123..."}'

# История выполнений
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/projects/myproject/preheat/policies/preheat-onpush/executions"
```

### Ключевые параметры конфигурации Dragonfly (для интеграции с Harbor)

```yaml
# /etc/dragonfly/manager.yaml — для самоподписанных сертификатов Harbor
caCert: "/etc/dragonfly/certs/harbor-ca.crt"   # CA сертификат Harbor (ca.crt)

# /etc/dragonfly/dfdaemon.yaml — настройки seed peer / p2p
p2p:
  enable: true
  port: 65001
  network: "tcp"
  storageDriver: "disk"  # или memory для эфимерных нод
  disk:
    dir: "/var/lib/dragonfly/p2p"
```

## Лучшие практики

### Архитектура и развёртывание

* **Отдельный кластер Dragonfly**: Развёртывайте Dragonfly Manager + seed peers + dfdaemon на выделенных нодах, раздельно от Harbor. Общая топология: Harbor (core/registry) ↔ Dragonfly Manager (preheat API) ↔ dfdaemon на каждой worker-ноде Kubernetes/VM.
* **Seed peers**: Настройте 2–3 seed peer ноды в разных зонах доступности для отказоустойчивости P2P-сети. Seed peers хранят полные копии образов и служат точками входа для новых узлов.
* **Сетевые политики**: Обеспечьте связность между dfdaemon (порт 65001 P2P, порт 65000 download) и Dragonfly Manager (порт 8080 preheat API, порт 65003 gRPC). В Kubernetes — NetworkPolicy или Security Groups.
* **TLS**: Используйте мTLS между Dragonfly компонентами. Для самоподписанных сертификатов Harbor — добавьте `ca.crt` Harbor в `manager.yaml` (см. сценарий 1) и настройте `insecure: false` в provider instance.

### Политики прогрева (Preheat Policies)

* **Event-based OnPush как дефолт**: Для production-образа используйте `OnPush` — прогрев запускается сразу после успешного push, до начала деплоя. Это устраняет холодный старт при rollout.
* **Scheduled для базовых образов**: Ежедневный/недельный прогрев базовых образов (OS base, runtime, common libs) по cron (`0 3 * * *`) — снижает нагрузку на registry в рабочие часы.
* **Фильтры по тегам и репозиториям**: Ограничивайте прогрев только нужными репозиториями и тегами (`v*`, `release-*`, `prod-*`). Избегайте прогрева `latest` и feature-веток — забивают P2P-кэш нерелевантными слоями.
* **Критерии безопасности**: Включайте `Only signed images` (при content trust) и `No vulnerability severity Critical/High` (при Deployment Security) — прогреваются только артефакты, прошедшие проверки. Настройка — в конфигурации проекта, не в политике.
* **Один provider instance на среду**: Создавайте отдельные provider instances для dev/staging/prod (разные Dragonfly кластеры или разные namespaces) — изоляция сред и blast radius.

### Мониторинг и наблюдаемость

* **Метрики Dragonfly**: Скрейпьте `dragonfly_manager_preheat_total`, `dragonfly_manager_preheat_duration_seconds`, `dragonfly_p2p_download_total`, `dragonfly_peer_task_total` — видимость прогрева и P2P-трафика.
* **Метрики Harbor**: `harbor_task_queue_size` (preheat задачи идут через Job Service), `harbor_jobservice_task_total{type="preheat"}` — отслеживайте задержки запуска.
* **Алерты**:
  - `dragonfly_manager_preheat_failed_total > 0` — ошибки прогрева
  - `dragonfly_p2p_peer_count < expected` — потери peer-ов
  - Provider instance status ≠ Healthy (Harbor API `/preheat/providers`)
* **Логи**: Dragonfly Manager логи (`/var/log/dragonfly/manager.log`) — детали preheat API; dfdaemon логи — P2P-качевание и ошибки скачивания.

### Производительность и масштабирование

* **max_job_workers**: Preheat задачи потребляют слот в Job Service. При массовом preheat (сотни политик) увеличьте `jobservice.max_job_workers` (см. [operations.md](./operations.md#сценарий-1-тюнинг-производительности)) и мониторьте `harbor_task_queue_size`.
* **Dragonfly кэш**: Настройте `dfdaemon.cache.disk.dir` и квоту (`disk.quota`) — избегайте переполнения диска seed peer-ов.
* **Параллелизм preheat**: Dragonfly Manager конфигурирует `preheat.concurrency` (дефолт 10) — число одновременных задач прогрева. Подбирайте под пропускную способность сети и диск seed peers.
* **Мульти-архитектура**: При preheat multi-arch образов (image index) — Dragonfly прогревает каждый манифест-платформу отдельно. Учитывайте в планировании емкости.

### Безопасность

* **OAuth для Dragonfly**: Предпочитайте OAuth (personal access token) вместо Basic auth для provider instance — токены можно отзывать, ротация без пересоздания instance.
* **Skip certificate verification — только для тестов**: В production всегда `insecure: false` с валидным CA. Self-signed — через добавление CA в Dragonfly Manager.
* **RBAC**: Provider instance создаёт системный админ; политики — администратор проекта. Не давайте права на создание provider instance проектным командам.
* **Аудит**: Все действия preheat (создание provider, политик, запуски) пишутся в Audit Log Harbor — включайте форвардинг в SIEM (см. [operations.md](./operations.md#сценарий-3-аудит-логи)).

### Эксплуатация и DR

* **DR Drill**: Проводите проверку восстановления Dragonfly кластера (seed peers + Manager) вместе с Harbor DR drill (см. [operations.md](./operations.md#эксплуатация)).
* **Бэкап конфигурации**: Бэкапьте `manager.yaml`, `dfdaemon.yaml`, provider instance конфигурацию (через API экспорт) — восстановление быстрее, чем пересоздание вручную.
* **Очистка P2P-кэша**: Dragonfly не имеет встроенного retention для P2P-кэша. Настройте cron-очистку старых blobs в `/var/lib/dragonfly/p2p` или используйте `dfdaemon` с `cache.disk.gc` (если доступно в версии).
* **Версионирование**: Блокируйте мажорные апгрейды Dragonfly (v2 → v3) без тестирования совместимости с Harbor preheat API. Следите за changelog Dragonfly и Harbor release notes.

## Дополнительная информация

* Официальная документация: [P2P Preheat](https://goharbor.io/docs/2.15.0/administration/p2p-preheat/), [Manage Preheat Provider Instances](https://goharbor.io/docs/2.15.0/administration/p2p-preheat/manage-preheat-providers/), [Preheat Images](https://goharbor.io/docs/2.15.0/working-with-projects/working-with-images/preheat-images/).
* **Dragonfly**: [документация](https://d7y.io/docs/next/), [интеграция с Harbor](https://d7y.io/docs/operations/integrations/harbor).
* **P2P-дистрибуция в CI/CD** — [artifact_management.md](../../../CI-CD/artifact_management.md).
* **Лейблы и событие OnLabel** — [labels.md](./labels.md).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — компоненты (Job Service).
* **[Работа с Harbor](./usage.md)** — proxy cache, лейблы.
* **[Репликация](./replication.md)** — event-based триггеры.
* **[Политики безопасности](./security_policies.md)** — критерии severity.
* **[Вопросы на собеседованиях](./harbor_interview_qa.md)** — Q&A по Harbor.
