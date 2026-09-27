# Многосервисный деплой (Multi-Service Deployment)

> **Актуально для:** Kubernetes 1.37.x, GitLab CI 17.x, on-prem/self-hosted инфраструктура

## Определения

**Multi-Service Deployment** — паттерн одновременного или скоординированного развёртывания нескольких interdependent сервисов (микросервисов, воркеров, инфраструктурных компонентов) с гарантией консистентности состояния кластера.

**All-or-Nothing Deployment** — стратегия, при которой либо все сервисы успешно обновляются, либо ни один — система остаётся в предыдущем стабильном состоянии. Противоположность независимому rollout'у каждого сервиса.

**Deployment Ordering** — упорядочивание сервисов по графу зависимостей (например, миграция БД → backend → frontend → ingress) для предотвращения каскадных сбоев.

**Saga Pattern (Deployment Saga)** — распределённая транзакция деплоя, где каждый сервис имеет компенсирующее действие отката, если последующий сервис не смог обновиться.

## Основные концепции

### Типы многосервисных деплоев

| Тип | Описание | Риск | Rollback |
| :--- | :--- | :--- | :--- |
| **Sequential** | Сервисы деплоятся один за другим в заданном порядке | Средний: сбой на сервисе N останавливает последующие | Откат только продеплоенных |
| **Parallel (Independent)** | Независимые сервисы деплоятся параллельно | Низкий: нет блокировок | Независимый откат каждого |
| **All-or-Nothing** | Всё или ничего; атомарный переключатель | Высокий при сбое: всё останавливается | Единый откат всех сервисов |
| **Blue-Green ( coordinated)** | Все сервисы обновляются в Green, затем единый cutover | Низкий для пользователя, высокий по ресурсам | Мгновенный возврат на Blue |

### Граф зависимостей сервисов

Пример типичного графа:
```
db-migration → backend-api → frontend → ingress-config
                    ↓
               worker-service
                    ↓
               queue-processor
```

### Стратегии отката при многосервисном деплое

1. **Sequential Rollback:** Откатывать сервисы в обратном порядке deployment'а (frontend → backend → migration).
2. **Parallel Rollback:** Все сервисы откатываются параллельно (быстрее, но рискованнее).
3. **Blue-Green Cutover:** Возврат на Blue-среду, где все сервисы на старой версии.
4. **Feature Flags + Kill Switch:** Отключение новой логики без отката артефактов.

## Практические сценарии

### 1. Последовательный деплой через GitLab DAG (`needs`)

```yaml
stages:
  - migrate
  - deploy_workers
  - deploy_api
  - deploy_frontend
  - smoke_test

db_migrate:
  stage: migrate
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/job-db-migration.yaml
    - kubectl wait --for=condition=complete job/db-migration --timeout=600s
  environment:
    name: production

deploy_workers:
  stage: deploy_workers
  image: bitnami/kubectl:1.37
  needs:
    - db_migrate
  script:
    - kubectl apply -f k8s/deployment-workers.yaml
    - kubectl rollout status deployment/workers --timeout=300s
  environment:
    name: production

deploy_api:
  stage: deploy_api
  image: bitnami/kubectl:1.37
  needs:
    - deploy_workers
  script:
    - kubectl apply -f k8s/deployment-api.yaml
    - kubectl rollout status deployment/api --timeout=300s
  environment:
    name: production

deploy_frontend:
  stage: deploy_frontend
  image: bitnami/kubectl:1.37
  needs:
    - deploy_api
  script:
    - kubectl apply -f k8s/deployment-frontend.yaml
    - kubectl rollout status deployment/frontend --timeout=300s
  environment:
    name: production

smoke_test:
  stage: smoke_test
  image: curlimages/curl:8.22.0
  needs:
    - deploy_frontend
  script:
    - curl -sf https://app.example.com/healthz || exit 1
    - curl -sf https://api.example.com/healthz || exit 1
```

### 2. All-or-Nothing деплой через GitLab DAG

```yaml
stages:
  - deploy
  - verify
  - promote
  - rollback

deploy_service_a:
  stage: deploy
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/service-a.yaml
    - kubectl rollout status deployment/service-a --timeout=300s
  environment:
    name: production

deploy_service_b:
  stage: deploy
  image: bitnami/kubectl:1.37
  needs:
    - deploy_service_a
  script:
    - kubectl apply -f k8s/service-b.yaml
    - kubectl rollout status deployment/service-b --timeout=300s
  environment:
    name: production

verify_all:
  stage: verify
  image: curlimages/curl:8.22.0
  needs:
    - job: deploy_service_a
      artifacts: true
    - job: deploy_service_b
      artifacts: true
  script:
    - curl -sf https://app.example.com/healthz || exit 1
    - curl -sf https://api.example.com/healthz || exit 1

promote_all:
  stage: promote
  image: bitnami/kubectl:1.37
  needs:
    - verify_all
  script:
    - echo "All services verified. Deployment complete."
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

rollback_all:
  stage: rollback
  image: bitnami/kubectl:1.37
  needs:
    - deploy_service_a
    - deploy_service_b
  script:
    - kubectl rollout undo deployment/service-a
    - kubectl rollout undo deployment/service-b
  environment:
    name: production
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### 3. Параллельный деплой независимых сервисов

```yaml
stages:
  - deploy_independent
  - verify

deploy_service_a:
  stage: deploy_independent
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/service-a.yaml
    - kubectl rollout status deployment/service-a --timeout=300s
  environment:
    name: production

deploy_service_b:
  stage: deploy_independent
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/service-b.yaml
    - kubectl rollout status deployment/service-b --timeout=300s
  environment:
    name: production

deploy_service_c:
  stage: deploy_independent
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/service-c.yaml
    - kubectl rollout status deployment/service-c --timeout=300s
  environment:
    name: production
```

### 4. Rollback через Blue-Green (все сервисы одновременно)

```yaml
stages:
  - deploy_green
  - verify_green
  - cutover
  - rollback

deploy_green_all:
  stage: deploy_green
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/green/service-a.yaml
    - kubectl apply -f k8s/green/service-b.yaml
    - kubectl apply -f k8s/green/service-c.yaml
    - kubectl rollout status deployment/service-a-green --timeout=300s
    - kubectl rollout status deployment/service-b-green --timeout=300s
    - kubectl rollout status deployment/service-c-green --timeout=300s
  environment:
    name: production-green

verify_green:
  stage: verify_green
  image: curlimages/curl:8.22.0
  needs:
    - deploy_green_all
  script:
    - curl -sf https://app.example.com/healthz || exit 1
    - curl -sf https://api.example.com/healthz || exit 1

cutover:
  stage: cutover
  image: bitnami/kubectl:1.37
  needs:
    - verify_green
  script:
    - kubectl patch service/myapp -p '{"spec":{"selector":{"version":"green"}}}'
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

rollback_blue:
  stage: rollback
  image: bitnami/kubectl:1.37
  needs:
    - cutover
  script:
    - kubectl patch service/myapp -p '{"spec":{"selector":{"version":"blue"}}}'
  environment:
    name: production
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
```

### 5. Parent-Child пайплайны для многосервисного деплоя

**Parent `.gitlab-ci.yml`:**
```yaml
stages:
  - deploy_services

trigger_service_a:
  stage: deploy_services
  trigger:
    project: group/service-a
    branch: main
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

trigger_service_b:
  stage: deploy_services
  trigger:
    project: group/service-b
    branch: main
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
```

**Child `.gitlab-ci.yml` (в group/service-a):**
```yaml
deploy:
  stage: deploy
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/
    - kubectl rollout status deployment/service-a --timeout=300s
  environment:
    name: production
```

### 6. Deployment через ArgoCD ApplicationSet (multi-cluster)

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: myapp
spec:
  generators:
    - git:
        repoURL: https://gitlab.example.com/group/myapp.git
        revision: main
        directories:
          - path: k8s/*
  template:
    metadata:
      name: "{{path.basename}}"
    spec:
      project: default
      source:
        repoURL: https://gitlab.example.com/group/myapp.git
        targetRevision: main
        path: "{{path}}"
      destination:
        server: https://kubernetes.default.svc
        namespace: "{{path.basename}}"
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

## Операции и команды

### GitLab CI — DAG и контроль порядка

| Действие | Команда / Конфигурация | Результат |
| :--- | :--- | :--- |
| **Задать порядок деплоя** | `needs:` в заданиях GitLab CI | DAG-зависимости; задания не стартуют, пока их зависимости не завершены |
| **Запустить smoke-тест после всех сервисов** | `needs: [deploy_a, deploy_b, deploy_c]` | Задание стартует только после успешного деплоя всех указанных сервисов |
| **Ручной approval на прод** | `when: manual` + `rules:` | Деплой в production останавливается до явного нажатия |
| **Автоматический откат по провалу smoke-test** | `allow_failure: false` на verification stage | Весь пайплайн падает, активируется rollback-этап |
| **Trigger downstream-пайплайна** | `trigger:` с `project:` и `branch:` | Запускает пайплайн в соседнем проекте/сервисе |
| **Artifact promotion между сервисами** | `dependencies:` + `artifacts:true` | Потребляет артефакт (манифест, digest) из upstream-задания |

### Kubernetes — проверка состояния после деплоя

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Проверить статус rollout** | `kubectl rollout status deployment/<name> --timeout=300s` | Ожидает завершения rollout или таймаут |
| **Проверить статус Job** | `kubectl wait --for=condition=complete job/<name> --timeout=600s` | Ожидает успешного завершения Job |
| **Проверить readiness всех подов** | `kubectl get pods -l app=<name> -o wide` | Показывает готовность (READY) и распределение по узлам |
| **Смотреть события Namespace** | `kubectl get events -n <env> --sort-by='.lastTimestamp'` | Хронология событий: ошибки, предупреждения, успешные деплои |
| **Проверить статус rollout history** | `kubectl rollout history deployment/<name>` | Список ревизий Deployment с изменениями |
| **Откатить конкретный сервис** | `kubectl rollout undo deployment/<name> --to-revision=N` | Возврат к указанной ревизии без пересборки |

### Helm — координированный деплой нескольких релизов

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Lint всех chart'ов** | `helm lint ./chart-a ./chart-b ./chart-c` | Проверка шаблонов на валидность перед деплоем |
| **Установить релизы в зависимости** | `helm upgrade --install <rel> ./chart --atomic --timeout 5m` | Установка с автоматическим откатом при ошибке |
| **Список релизов в namespace** | `helm list -n <env> --all-namespaces` | Показывает все релизы, их статус и revision |
| **Проверить зависимости chart'ов** | `helm dependency update ./chart && helm dependency list ./chart` | Обновление и проверка subchart'ов |
| **Тестовый запуск без применения** | `helm upgrade --install <rel> ./chart --dry-run` | Покажет, что будет применено, без реальных изменений |
| **Rollback конкретного релиза** | `helm rollback <rel> 1 -n <env>` | Возврат к ревизии 1 конкретного релиза |

### ArgoCD — multi-cluster ApplicationSet

| Действие | Команда / Конфигурация | Результат |
| :--- | :--- | :--- |
| **Создать ApplicationSet** | YAML-манифест с generators | Автоматическое создание Application для каждого пути/кластера |
| **Принудительная синхронизация** | `argocd app sync <app-name>` | Запуск syncPolicy для конкретного Application |
| **Проверить статус всех App** | `argocd app list -o wide` | Список всех приложений с состоянием sync и health |
| **Откатить конкретное Application** | `argocd app rollback <app-name>` | Возврат к предыдущей ревизии Git |
| **Разрешить самоисцеление** | `spec.syncPolicy.selfHeal: true` | Автоматический откат при отклонении от желаемого состояния |
| **Приостановить авто-sync** | `argocd app set <app-name> --sync-policy none` | Отключение automated sync для ручного контроля |

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Каскадный провал smoke-теста** | Один из сервисов не готов, но предыдущие уже деплоены | Восстановите провалившийся сервис вручную или откатите весь деплой по dependency graph |
| **DAG deadlock в GitLab CI** | Циклическая зависимость `needs:` между заданиями | Визуализируйте DAG; удалите цикл; используйте асинхронные health check вместо tight coupling |
| **Helm release в `pending-rollback`** | Откат не завершился (timeout, parted CRD) | `helm history <rel>` → `helm rollback <rel> <rev>`; проверьте `kubectl get events` |
| **Stuck Job (Pending/Evicted)** | Недостаточно ресурсов в namespace или PDB запрещает выселение | `kubectl describe pod <pod>` → проверьте events, requests/limits, PDB |
| **Multi-cluster partial failure** | Один кластер недоступен или manifests несовместимы | Используйте последовательное применение с проверкой статуса каждого кластера; откатывайте при первом провале |
| **ArgoCD OutOfSync после деплоя** | `kubectl apply` из CI конфликтует с Git-источником ArgoCD | Выберите один источник истины: либо GitOps через ArgoCD, либо прямой `kubectl apply` из CI, не смешивайте |
| **Registry недоступен при деплое** | DNS/сеть между CI-runner и registry разорвана | Проверьте `nslookup registry`, `curl -I https://registry/health`; используем registry-mirror или fallback |
| **Некорректный order деплоя** | Зависимость service B от service A не выражена в DAG | Добавьте `needs:` явно; документируйте граф зависимостей в `README` или Architecture Decision Record (ADR) |
| **Approvals истекли на середине деплоя** | Service A approved в понедельник, service B — в среду | Используйте единый approval gate для всего пайплайна; ограничьте TTL approval'ов 24 часами |
| **ConfigMap/Secret не обновился** | Поды используют старую версию ConfigMap (in-memory кэш) | Проверьте `kubectl rollout restart deployment/<name>` или `kubectl delete pod` для принудительного обновления |
| **Helm values drift между сервисами** | Вручную изменены values в production, не попавшие в Git | Централизуйте values через Git (monorepo); используйте `helm get values <rel> -n <env>` для аудита |
| **Database migration зависла** | Длинная миграция блокирует деплой последующих сервисов | Выделите отдельный stage с увеличенным timeout; добавьте `kubectl wait` для Job |
| **Promotion артефакта не найден** | Digest не был pushed в registry или permissions некорректны | Проверьте `docker push` в логах; убедитесь, что CI-сервисный аккаунт имеет права push |
| **SBOM/Signature отсутствует** | Syft или cosign не сработали в пайплайне | Проверьте, что эти шаги идут перед `kubectl apply`; артефакты сохраняются в `artifacts:paths` |

## Лучшие практики

1. **Граф зависимостей явно:** Определите deployment order в документации и в пайплайне (`needs:`). Никаких «магических» задержек (`sleep 30`). Храните граф в виде ADR (Architecture Decision Record) или в `README` сервиса.
2. **Health Checks после каждого сервиса:** После деплоя каждого сервиса проверяйте его `/healthz` перед переходом к следующему. Используйте `startupProbe` для медленных сервисов (Java/JVM), `readinessProbe` для проверки зависимостей (БД, кэш), `livenessProbe` для самоисцеления.
3. **Артефакт promotion для всех сервисов:** Все сервисы должны использовать артефакты из одного пайплайна (одинаковый коммит, одинаковые digest'ы). Храните SBOM и подпись в артефактах с `expire_in: 30d`.
4. **Feature Flags для декoupling:** Используйте флаги для управления видимостью новых функций, чтобы сервисы можно было деплоить независимо. Включайте флаг только после успешного smoke-теста.
5. **Раздельные approval'ы для критичных сервисов:** База данных и core-backend требуют отдельного approval от DBA/SRE. Используйте `when: manual` с `rules:` для каждого критичного сервиса.
6. **Каждый сервис — отдельный Job в пайплайне:** Избегайте «монолитного» deploy-скрипта, который деплоит всё сразу. Это упрощает откат и аудит.
7. **Rollback order:** Документируйте и автоматизируйте обратный порядок отката (frontend → api → workers → migration). Используйте `kubectl rollout undo` или `helm rollback` с явным указанием ревизии.
8. **Monitoring каждого сервиса:** После деплоя проверяйте метрики (error rate, latency, saturation) каждого сервиса отдельно, а не только агрегированные. Настройте алерты на деградацию каждого сервиса.
9. **Audit Trail для каждого сервиса:** Логируйте, кто, когда, какой артефакт деплоил в какой сервис. Используйте `CI_PIPELINE_ID`, коммит и approval-юзера в метках.
10. **Раздельные реестры для сред:** Dev/staging/prod должны иметь разные registry с разными правами доступа. CI-сервисный аккаунт имеет права push только в staging, а promotion в prod — через отдельный approval gate.
11. **Immutable артефакты:** Запретите тег `:latest` и перезапись артефактов. Используйте digest + immutable tags. В Kubernetes привязывайтесь к digest'у в imagePullPolicy.
12. **Database migration в отдельном stage:** Выделите миграции БД в отдельный stage с увеличенным timeout (например, 600s) и `kubectl wait` для завершения Job. Никогда не смешивайте миграции с деплоем приложения в одном stage.
13. **Pre-flight проверки перед деплоем:** Запускайте lint, scan и unit-тесты перед любым деплоем. Используйте `allow_failure: false` для критичных проверок.
14. **Retention политики:** Настройте автоматическое удаление старых артефактов, Helm-релизов и CI-артефактов. В Helm используйте `--history-max`, в GitLab — `expire_in: 30d`.
15. **Network partitions и DNS:** Убедитесь, что CI-runner имеет статический IP и сетевое подключение до Kubernetes API и registry. При VPN/файрволе используйте proxy или статические IP-раннеры.
16. **Конфигурация через Git:** Все манифесты, Helm values и скрипты должны храниться в Git. Никаких ручных `kubectl edit` в production. Используйте PR/MR для изменений конфигурации.
17. **Ограничение параллельных promotions:** Используйте mutex-скрипт или очередь в GitLab для предотвращения гонок при одновременном продвижении нескольких артефактов.
18. **Знакомство с blast radius:** Перед деплоем оцените, сколько сервисов затронет сбой. Используйте canary или blue-green для сервисов с высоким blast radius.

## Граничные случаи и ограничения

- **Каскадный сбой:** При Blue-Green все сервисы деплоятся в Green; если один не встаёт — ресурсы wasted. Решение — canary для каждого сервиса отдельно.
- **Разные TTL approval'ов:** Если approval на service A истёк, а service B ещё не деплоился — пайплайн в неконсистентном состоянии. Используйте единый approval gate для всего деплоя.
- **Совместимость API:** При одновременном деплое service A (v2) и service B (v2) убедитесь, что они совместимы по контракту. Используйте contract testing (Pact, Spring Cloud Contract) для проверки совместимости до деплоя.
- **Database backfill:** При добавлении нового сервиса может потребоваться backfill данных. Решение — отдельный migration Job с `backoffLimit` и `activeDeadlineSeconds`.
- **Multi-cluster:** Деплой в несколько кластеров требует последовательной проверки статуса каждого; параллельный деплой riskован. Используйте ApplicationSet с `prune: false` для safety.
- **Service Mesh:** При использовании Istio/Linkerd можно управлять трафиком на уровне сервисов, что упрощает многосервисный cutover. Но mesh добавляет сложность: нужно отслеживать VirtualService и DestinationRule.
- **Registry mirror недоступен:** Если registry-mirror недоступен, деплой блокируется. Настройте fallback на primary registry или отложенный promotion.
- **CI-runner исчерпал ресурсы:** При параллельном деплое нескольких сервисов runner может исчерпать CPU/RAM. Ограничьте параллельные jobs через `resource_group` или очередь.
- **Helm chart завис в `pending-install`:** Helm 3.x может оставить релиз в `pending-install` при сбое. Используйте `helm uninstall <rel>` и повторный `helm install` с `--atomic`.
- **ConfigMap hash collision:** При использовании ConfigMap с одинаковым именем в разных сервисах возможна коллизия. Используйте уникальные имена или namespace-изоляцию.
- **Rolling Update конфликтует с HPA:** HPA может перезаписать `spec.replicas` во время Rolling Update. Настройте HPA на управление Deployment напрямую, а не ReplicaSet.
- **Database schema drift:** При деплое нескольких сервисов, меняющих схему БД, возможен drift. Используйте Expand-Contract паттерн для миграций.
- **Network latency между сервисами:** При деплое в разные availability zones проверяйте latency между сервисами. Используйте topology spread constraints для размещения подов.
- **Rollback требует отката БД:** Если деплой включал миграцию БД, откат приложения без отката миграции может привести к data corruption. Документируйте compatibility миграций.
- **ArgoCD Conflict при прямом apply:** Если CI использует `kubectl apply`, а ArgoCD отслеживает Git, возникает рассинхронизация. Выберите один источник истины.
- **Stale image pull:** Registry кэширует образы; новый digest может не примениться сразу. Используйте `imagePullPolicy: Always` или `imagePullSecrets` для force-pull.
- **Node affinity и topology:** При деплое нескольких сервисов учитывайте node affinity, taints/tolerations и topology spread constraints для отказоустойчивости.
- **Resource Quota exhaustion:** Параллельный деплой нескольких сервисов может превысить Resource Quota namespace. Проверяйте квоты перед деплоем через `kubectl describe quota -n <env>`.
- **Helm release accumulation:** Удаленные релизы остаются в истории. Настройте `--history-max` или периодический `helm uninstall` для очистки.
- **Log shipping gaps:** При каскадном деплое логи каждого сервиса должны уходить в центральный SIEM с корреляцией по deployment ID. Без этого невозможно расследовать инцидент.

## Дополнительная информация

### Рекомендованные ссылки

- **[Blue-Green Deployment](./blue_green_deployment.md)** — атомарный cutover для всех сервисов.
- **[Rolling Update](./rolling_update.md)** — поочередный деплой сервисов.
- **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)** — архитектура отката.
- **[Родительско-дочерние пайплайны](../GitLab_CI/Advanced/Downstream_Pipelines/parent_child_pipelines.md)** — оркестрация через GitLab trigger.
- **[DAG и needs в GitLab CI](../GitLab_CI/Advanced/workflow_rules/dag_with_needs.md)** — управление порядком выполнения задач.
