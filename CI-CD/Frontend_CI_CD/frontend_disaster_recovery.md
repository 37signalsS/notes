**Актуально для:** Argo CD v3.x, Flux v2.9.x, Kubernetes 1.29–1.36

# Disaster Recovery для фронтенда

## Определения

- **RTO (Recovery Time Objective)** — максимальное допустимое время восстановления сервиса после сбоя.
- **RPO (Recovery Point Objective)** — максимально допустимая потеря данных (время с последнего резервного снимка).
- **Failover** — автоматическое или ручное переключение трафика с отказавшего компонента на резервный.
- **Multi-region** — развёртывание в нескольких географических точках для отказоустойчивости.
- **Backup Strategy** — план резервного копирования артефактов, конфигураций и секретов.
- **Cold/Warm/Hot standby** — уровни готовности резервной инфраструктуры.
- **Graceful degradation** — режим работы, при котором сервис сохраняет частичную функциональность при недоступности компонентов.
- **Static asset fingerprinting** — добавление хэша содержимого в имя файла (`app.a1b2c3.js`) для бесконечного кэширования и безопасного деплоя.
- **Origin fallback** — резервный источник статики/трафика, на который CDN переключается при падении primary origin.
- **CDN cold standby** — резервный CDN-слой, не принимающий трафик в штатном режиме, но готовый к активации.
- **Registry mirror** — реплика реестра образов в локальной сети для обхода outage внешнего реестра.
- **Git as artifact store** — хранение сборок фронтенда (`dist/`) в Git LFS или как CI-артефакты, привязанные к коммиту.
- **Drift detection** — обнаружение расхождений между состоянием в Git и реальным состоянием кластера.

---

## Предварительные требования

- **Kubernetes:** кластер v1.29+ с включёнными стабильными API-группами (`apps/v1`, `networking.k8s.io/v1`, `autoscaling/v2`).
- **Ingress/Gateway:** настроенный контроллер (NGINX Ingress Controller 1.9+ или Gateway API controller) с TLS-терминацией.
- **CDN:** edge-сервис с поддержкой origin pools, health checks и автоматического failover.
- **Registry:** внутренний OCI-реестр (Harbor, GitLab Container Registry, Nexus) с retention policy и поддержкой репликации.
- **Vault:** HashiCorp Vault 1.15+ или аналогичный хранилище секретов с поддержкой snapshot.
- **CI/CD:** пайплайн (GitLab CI 16+), сохраняющий артефакты сборки и умеющий публиковать в зеркальный registry.
- **Мониторинг:** Prometheus + Alertmanager с дашбордами RUM/JS Error Rate и алертами на доступность origin/CDN/registry.
- **RBAC:** минимальные права для on-call: доступ к CDN API, Vault, registry mirror и кластеру для принудительного отката.

---

## Основные концепции

### Архитектура DR для фронтенда

```
Пользователь
   │
   ▼
CDN (edge) ── health checks ──► Origin pool (primary / secondary / DR)
   │                                    │
   │                                    ▼
   │                              Kubernetes
   │                              ├── Deployment (frontend)
   │                              ├── Service
   │                              ├── Ingress / Gateway
   │                              └── HPA
   │
   ├──► Static assets (fingerprinted, immutable)
   │         │
   │         ├── CDN cache (TTL=max-age, stale-while-revalidate)
   │         └── Registry mirror (fallback при outage)
   │
   └──► Secrets (Vault)
             │
             ├── CDN токены
             ├── FFaaS токены
             └── Registry credentials
```

### Угрозы для фронтенда

Фронтенд-сервис может пострадать от:
1. **Origin недоступен:** hardware failure, network partition, человеческий фактор.
2. **CDN/edge сбой:** региональный outage, ошибка конфигурации, DDoS-блокировка.
3. **Реестр недоступен:** outage внешнего/внутреннего registry, потеря доступа к образам.
4. **Потеря данных:** потеря статики, артефактов или конфигурации.
5. **Секреты:** потеря доступа к Vault/CDN/FFaaS токенам.

### Уровни отказоустойчивости

| Уровень | Описание | RTO | RPO | Компоненты |
| :--- | :--- | :--- | :--- | :--- |
| **Basic** | Один origin, один CDN, нет зеркала registry | Часы | Часы | Nginx, CDN, Git |
| **HA** | Origin pool + CDN с multi-region + registry mirror | Минуты | Минуты | Load Balancer, CDN Failover, Harbor replication |
| **DR** | Multi-region origin + CDN cold standby + automated failover + Vault snapshot | Секунды | 0 | Global Load Balancer, Active-Active, Vault Raft |

### Стратегия резервного копирования

Что нужно бэкапить:
- **Артефакты:** `dist/` с fingerprinting или Docker-образы в registry с retention policy 30–90 дней.
- **Конфигурация:** Ingress, Gateway, ConfigMap, Deployment — всё в Git.
- **Секреты:** Vault snapshots (RPO < 1 час), CDN/FFaaS токены в Vault.
- **Данные:** RUM-метрики, логи (Loki/ELK retention), audit logs.
- **Registry:** зеркало в локальной сети; при outage промоушен из mirror.

### Специфика фронтенда

- **Статика иммутабельна:** fingerprinting делает файлы бесконечно кэшируемыми; CDN-отказ не ломает уже загруженные ассеты.
- **SSR/SSG кэш:** при восстановлении origin нужно прогреть кэш (revalidation, ISR `revalidate`), иначе пользователи получат 502/ stale-контент.
- **Service Worker:** при failover SW может закэшировать 502; нужна стратегия отката на network-first или обновление SW.
- **Preview-окружения:** для MR/PR создаются временные окружения; их DR — это TTL + быстрая пересборка из Git, а не долгосрочный backup.
- **GitOps-контроллер:** состояние Argo CD / Flux не хранит frontend-артефакты; бэкап ConfigMap/Applications/Secrets контроллера — отдельная задача (см. [Argo CD: Disaster Recovery](../../GitOps/ArgoCD/argocd_disaster_recovery.md)).

---

## Практические сценарии

### Сценарий 1: Планирование RTO/RPO по слоям фронтенда

```markdown
## План восстановления фронтенда

### Слой A: Статические ассеты (fingerprinted)
- **RTO:** 2 минуты (CDN fallback origin или cache-only режим).
- **RPO:** 0 (файлы иммутабельны, CDN хранит копию).
- **Действия:**
  1. Переключение CDN origin pool на secondary.
  2. Если CDN недоступен — обновление DNS TTL на 60 секунд и переключение на origin напрямую.
  3. Проверка fingerprint integrity: `sha256sum` последнего задеплоенного бандла.

### Слой B: SSR/SSG контент
- **RTO:** 5 минут.
- **RPO:** 5 минут (ISR `revalidate` интервал).
- **Действия:**
  1. Переключение трафика на secondary SSR-инстанс.
  2. Принудительный прогон ISR-ревалидации для критических путей.
  3. Если SSR недоступен — fallback на статический HTML из CDN.

### Слой C: Конфигурация и секреты
- **RTO:** 1 минута.
- **RPO:** < 1 час (Vault snapshot).
- **Действия:**
  1. Восстановление Vault из snapshot.
  2. Проверка CDN токенов, FFaaS флагов.
  3. Перезапуск pods для подхвата новых секретов.

### Слой D: Registry/образы
- **RTO:** 15 минут.
- **RPO:** 0 (образы кэшируются на узлах; mirror готов).
- **Действия:**
  1. Переключение CI/CD на зеркальный registry.
  2. Промоушен образа из mirror в production namespace.
  3. Проверка digest: `crane digest registry-mirror.example.com/frontend:sha-abc123`.
```

**Валидация:**
- **RTO:** замеряется от detection до полного восстановления; фиксируется в incident timeline.
- **RPO:** проверяется, что последний backup/artifact старше RPO не более допустимого.
- **Failover:** secondary origin/region принимает трафик за время < RTO; smoke-тест проходит.
- **Backup restore:** ежемесячный drill восстановления Vault/registry из snapshot.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Secondary origin отдаёт stale-контент | Не проведена инвалидация CDN после failback | Принудительная инвалидация `/assets`, `/index.html`; проверка `Cache-Control` |
| SSR возвращает 502 | Secondary инстанс не прогрет, startup probe не прошёл | Увеличить `failureThreshold` startup probe; добавить readiness gate |
| Vault snapshot повреждён | Запись snapshot прервана | Проверять `vault operator raft snapshot` exit code; хранить snapshot в отдельном PVC/NFS |
| Registry mirror не синхронизирован | Replication lag > RPO | Настроить webhook/replication trigger; мониторить `Last Sync` в Harbor |
| DNS не переключается | TTL записи > 60 секунд | Уменьшить TTL в штатном режиме до 60–300 секунд |

---

### Сценарий 2: Multi-region CDN failover и origin fallback

```bash
# 1. Настройка origin pool в CDN (generic CDN syntax)
# Primary origin: dc1.origin.example.com
# Secondary origin: dc2.origin.example.com
# Health check: GET /healthz, interval=10s, timeout=5s, healthy threshold=2

# 2. Проверка текущего активного origin
curl -sI https://cdn.example.com/assets/app.a1b2c3.js | grep -i "x-cache\|age\|cf-cache-status"
# → X-Cache: Hit from dc1 (primary)

# 3. Имитация отказа primary: отключаем dc1 в CDN origin pool
curl -X POST "$CDN_API/origin-groups/primary/disable" \
  -H "Authorization: $TOKEN"

# 4. Проверяем переключение на dc2
sleep 15
curl -sI https://cdn.example.com/assets/app.a1b2c3.js | grep -i "x-cache\|x-cdn"
# → X-Cache: Hit from dc2 (secondary datacenter)

# 5. Восстанавливаем primary
curl -X POST "$CDN_API/origin-groups/primary/enable" \
  -H "Authorization: $TOKEN"

# 6. Валидация: traffic вернулся на primary
sleep 60
curl -sI https://cdn.example.com/assets/app.a1b2c3.js | grep -i "x-cache"
# → X-Cache: Hit from dc1
```

**Валидация:**
- Health check переводит primary в unhealthy за 20–30 секунд (2× interval).
- Failover завершается за < 60 секунд; smoke-тест на `/healthz` проходит.
- После восстановления primary traffic пропорционально распределяется; drift = 0.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Failover не происходит | Health check путь `/healthz` возвращает 503 | Проверить readiness probe в Deployment; убедиться, что CDN может достичь origin |
| Оба origin отдают разный контент | Нет graceful degradation на CDN | Настроить origin fallback: при 5xx от primary — retry на secondary |
| CDN кэширует 502 | Нет stale-if-error / stale-while-revalidate | Добавить `Cache-Control: stale-if-error=60` для HTML; для ассетов — не требуется |
| Долгий DNS failover | TTL записи > 60 секунд | В штатном режиме TTL = 60–300 секунд; при DR — снизить до 10 через API провайдера DNS |

---

### Сценарий 3: Резервное копирование секретов (Vault snapshot)

```bash
# Резервное копирование Vault (RPO < 1 час)
vault operator raft snapshot save /vault/backups/vault-$(date +%Y%m%d-%H%M).snap

# Проверка целостности snapshot
vault operator raft snapshot inspect /vault/backups/vault-20260927-1400.snap
# → snapshot valid, index 12345, term 7

# Восстановление из snapshot (на DR-кластере)
vault operator raft snapshot restore /vault/backups/vault-20260927-1400.snap

# Автоматизация через CronJob в Kubernetes
kubectl create job --from=cronjob/vault-snapshot vault-snapshot-manual -n vault
```

**Валидация:**
- Snapshot создаётся без ошибок (`vault operator raft snapshot inspect` = valid).
- Восстановление на тестовом кластере проходит; секреты читаемы.
- Retention: snapshots хранятся 30 дней; ежемесячный drill restore.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Snapshot не создаётся | Vault в sealed/standby режиме | Проверить `vault status`; активный узел должен быть leader |
| Snapshot повреждён | Прерывание записи на NFS/object storage | Использовать локальный SSD + async upload; проверять checksum |
| Восстановление занимает часы | Большой кластер Vault (TB) | Использовать `vault operator raft snapshot restore` с `-force` на пустом кластере; перенос metadata отдельно |

---

### Сценарий 4: Резерв артефактов и восстановление registry mirror

```bash
# GitLab CI: retention policies
# .gitlab-ci.yml
deploy_production:
  stage: deploy
  artifacts:
    paths:
      - dist/
    expire_in: 90 days
  rules:
    - if: $CI_COMMIT_BRANCH == "main"

# Harbor: retention rules
# Project → Retention → "Keep last 20 semver tags, 90 days for sha-*"

# Ручной экспорт артефакта из mirror (при outage primary registry)
 crane copy \
  registry-mirror.example.com/frontend:sha-abc123 \
  registry.internal.corp/frontend:sha-abc123

# Проверка digest
crane digest registry.internal.corp/frontend:sha-abc123
# → sha256:1a2b3c...

# Принудительный обновление Deployment на mirror
kubectl set image deployment/frontend \
  frontend=registry.internal.corp/frontend:sha-abc123 \
  -n production
```

**Валидация:**
- Артефакты доступны в mirror с тем же digest, что и в primary.
- Retention policy отдаёт последний рабочий артефакт за < RTO.
- Harbor replication status = OK; lag < 5 минут.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Artifact 404 в CI | `expire_in: 1 day` | Увеличить до 30–90 дней; для production — бессрочно + object storage versioning |
| Mirror устарел на неделю | Replication прерван | Включить webhook trigger; добавить мониторинг `Last Sync` |
| Digest mismatch | Рaces condition при push | Использовать digest pinning в Deployment; теги только для dev/staging |

---

### Сценарий 5: Chaos Engineering / DR drill для фронтенда

```bash
# Сценарий: отказ origin DC1 + проверка failover
# 1. Отключаем DC1 origin в CDN
curl -X POST "$CDN_API/origin-groups/primary/disable" \
  -H "Authorization: $TOKEN"

# 2. Проверяем переключение на DC2
curl -sI https://cdn.example.com/assets/app.a1b2c3.js | grep -i "x-cache\|x-cdn"
# → X-Cache: Hit from dc2

# 3. Проверяем SSR fallback (если SSR недоступен)
curl -fsS https://example.com/ssr-path || echo "fallback to static"

# 4. Восстанавливаем DC1
curl -X POST "$CDN_API/origin-groups/primary/enable" \
  -H "Authorization: $TOKEN"

# 5. Инвалидация CDN после восстановления
curl -X POST "$CDN_API/purge" -H "Auth: $TOKEN" -d '{"prefix":"/assets","tags":["drill"]}'

# 6. Валидация: traffic вернулся на primary
sleep 60
curl -sI https://cdn.example.com/assets/app.a1b2c3.js | grep -i "x-cache"
# → X-Cache: Hit from dc1
```

**Валидация:**
- Failover завершён за время < RTO.
- Secondary origin/registry/SSR прошёл smoke-тест.
- После восстановления primary traffic пропорционально распределяется; drift = 0.
- Записан incident timeline; участники drill получили фидбэк.

**Troubleshooting:**
| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Secondary SSR не готов | Нет warm standby для SSR | Настроить minimum replicas=1 в secondary namespace; использовать HPA |
| CDN кэширует 502 после drill | Нет stale-if-error | Добавить заголовок; принудительная инвалидация после drill |
| Preview env не очистился | Нет TTL для preview namespaces | Добавить `argocd app delete --cascade` или Flux Kustomization TTL |

---

## Операционные команды

| Действие | Команда / Конфигурация | Ожидаемый результат |
| :--- | :--- | :--- |
| Snapshot Vault | `vault operator raft snapshot save /backups/vault-$(date +%Y%m%d).snap` | Файл snapshot создан, `inspect` = valid |
| Проверка origin health | `curl -sI https://cdn.example.com/assets/app.js \| grep -i "x-cache"` | `X-Cache: Hit from dc1/dc2` |
| Отключение origin в CDN | `curl -X POST "$CDN_API/origin-groups/primary/disable" -H "Authorization: $TOKEN"` | HTTP 200/204, origin переходит в disabled |
| Инвалидация CDN | `curl -X POST "$CDN_API/purge" -H "Auth: $TOKEN" -d '{"prefix":"/assets"}'` | CDN удаляет кэш для указанных путей |
| Digest образа | `crane digest registry.example.com/frontend:sha-abc123` | `sha256:1a2b3c...` |
| Копирование в mirror | `crane copy registry-mirror/frontend:sha-abc123 registry.internal.corp/frontend:sha-abc123` | Образ доступен в mirror с тем же digest |
| Проверка Vault | `vault status` | `sealed: false`, `cluster address: ...`, `ha enabled: true/false` |
| Проверка HAProxy/Ingress | `kubectl get pods -n production -l app=frontend` | Все поды `Running`, `READY` = 1/1 |
| Проверка registry replication | Harbor UI → Project → Replication → Last Sync | `Success`, lag < 5 минут |
| Проверка retention | GitLab CI: `curl --header "PRIVATE-TOKEN: $TOKEN" "https://gitlab.example.com/api/v4/projects/123/jobs/artifacts/main/download?job=deploy_production"` | HTTP 200, архив скачан |
| Проверка preview TTL | `kubectl get app -n preview -l app.kubernetes.io/managed-by=argocd` | Только актуальные PR/MR; старые удалены |
| Проверка SW adoption | `navigator.serviceWorker.controller && serviceWorker.state === 'activated'` в DevTools | Доля пользователей на новом SW > 95% |

---

## Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Долгий failover | Нет health check в CDN | Настроить CDN Health Check с interval=10s, healthy threshold=2 |
| Потеря артефактов | `expire_in: 1 day` в CI artifacts | Увеличить retention до 30–90 дней; production — бессрочно + object storage versioning |
| Vault недоступен | Нет snapshot, кластер потерян | Ежедневные raft snapshot, test restore ежемесячно |
| CDN кэширует 502 | Нет graceful degradation | Настроить `stale-if-error=60` для HTML; origin fallback в CDN |
| Дрейф конфигурации | Ручные изменения в кластере | GitOps + drift detection alerts (OutOfSync > 5 минут) |
| Registry outage | Нет fallback registry | Настроить Harbor replication/mirror; CI/CD aware mirror |
| Устаревший SW у пользователей | Нет skipWaiting/forced update | `skipWaiting: true` в deploy; serviceWorker.update() при критическом DR |
| Preview env забил кластер | Нет TTL для preview namespaces | ApplicationSet TTL + Prune; ResourceQuota + LimitRange |
| Secondary SSR не прогрет | Нет minimum replicas | HPA minReplicas=1 в secondary namespace; startup probe |
| DNS не переключается | TTL записи > 60 секунд | В штатном режиме TTL = 60–300 секунд |

---

## Особые случаи

- **Preview-окружения:** DR для preview = быстрая пересборка из Git; не нужен долгосрочный backup. Настройте TTL (24–72 часа) и Prune.
- **SSR/SSG при восстановлении:** при поднятии secondary SSR-инстанса прогрейте кэш (ISR `revalidate`, `generateStaticParams`), иначе пользователи получат 502.
- **Service Worker при failover:** SW может закэшировать 502 от fallback origin; используйте network-first для HTML и cache-first для ассетов, или принудительное `skipWaiting`.
- **CDN инвалидация после DR:** автоматическая инвалидация `/assets`, `/index.html`, `/sw.js` после восстановления primary origin; иначе пользователи останутся на fallback.
- **Registry mirror:** настроить репликацию с webhook trigger; при outage CI/CD автоматически публикует в mirror. RPO для registry = интервал репликации (5–15 минут).
- **Git LFS / большие артефакты:** для `dist/` > 1 GB используйте Git LFS или внешнее хранилище (MinIO/NFS/object storage); Git сам по себе не предназначен для больших бинарных артефактов.
- **Fallback origin с stale-контентом:** если primary origin потерян, а secondary хранит недельную статику — CDN будет отдавать устаревшие fingerprint-файлы; настройте `stale-while-revalidate` и мониторинг age кэша.
- **CDN cold standby:** резервный CDN-провайдер не получает трафик в штатном режиме; активация вручную или через DNS failover. Проверяйте активацию раз в квартал.
- **DNS TTL и failover timing:** TTL в штатном режиме = 60–300 секунд; при DR снижайте до 10 через API DNS-провайдера. Без этого failover займёт часы.
- **HPA и replicas при DR:** во время failover HPA может скалировать secondary инстанс; убедитесь, что `minReplicas` достаточен для приёма traffic, а `maxReplicas` не превышает лимиты кластера.

---

## Лучшие практики

1. Документируйте RTO/RPO для каждого слоя: статика, SSR, конфигурация, секреты, registry.
2. Храните артефакты минимум 30 дней; для production — 90+ дней с versioning в object storage.
3. Тестируйте восстановление Vault из snapshot ежемесячно; проверяйте целостность через `vault operator raft snapshot inspect`.
4. Используйте multi-region CDN с origin pools и health checks; interval = 10 секунд, healthy threshold = 2.
5. Настройте alert на недоступность origin/CDN/registry с эскалацией < RTO.
6. Проводите quarterly chaos engineering: отключайте origin/CDN/registry, проверяйте failover.
7. Ведите incident timeline для каждого сбоя; после DR проверяйте, что RTO/RPO соблюдены.
8. Для секретов используйте Vault с raft snapshot backup; RPO для секретов < 1 час.
9. Используйте digest pinning для production образов; теги — только для dev/staging.
10. Настройте registry mirror с репликацией и webhook trigger; CI/CD должен уметь автоматически переключаться на mirror.
11. Для статики используйте fingerprinting (`contenthash`) + CDN с `stale-while-revalidate` и `stale-if-error`.
12. SSR/SSG: настройте ISR `revalidate` и graceful degradation на статический HTML при недоступности SSR.
13. Service Worker: используйте network-first для HTML и cache-first для ассетов; при DR — принудительное обновление SW.
14. Для preview-окружений используйте TTL + Prune (ApplicationSet / Flux Kustomization); не храните preview данные долгосрочно.
15. Настройте admission controller (OPA/Gatekeeper/Kyverno) для проверки манифестов перед применением; дрейф — симптом проблемы, а не решение.
16. Храните конфигурацию CDN, Ingress, Deployment в Git; для DR переключения используйте GitOps (см. [Argo CD: Disaster Recovery](../../GitOps/ArgoCD/argocd_disaster_recovery.md)).

---

## Дополнительная информация

### См. также

- **[Argo CD: Disaster Recovery](../../GitOps/ArgoCD/argocd_disaster_recovery.md)** — бэкап, восстановление, etcd snapshot, HA, geo-recovery GitOps-контроллера.
- **[Vault: стратегии бэкапов](../../Vault/guides/backup_restore_strategies.md)** — RPO/RTO, snapshot, recovery для секретов фронтенда.
