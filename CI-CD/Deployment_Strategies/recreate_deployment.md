# Recreate Deployment — последовательная замена

**Актуально для:** Kubernetes 1.37.x

> Стратегия развертывания, при которой старая версия приложения полностью останавливается перед запуском новой. Это единственная стратегия, которая гарантирует отсутствие одновременной работы двух версий, но при этом приводит к периоду времени недоступности сервиса (downtime). Детали по другим стратегиям — в **[Сравнение стратегий развертывания](./comparison.md)**; интеграцию с проверками здоровья и CI/CD — в **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)**.

## Определения

**Recreate Deployment** — стратегия развертывания, при которой все экземпляры старой версии (v1) последовательно останавливаются, и только после полной остановки запускаются экземпляры новой версии (v2). В любой момент времени работает только одна версия приложения.

- **Downtime (Простой)** — период времени, в течение которого сервис недоступен для пользователей. При Recreate downtime неизбежен и определяется временем остановки v1 + временем запуска v2.
- **Maintenance Window (Окно обслуживания)** — заранее запланированный период времени, в течение которого выполняются технические работы, связанные с остановом сервиса. Recreate требует наличия такого окна.
- **Атомарный откат (Atomic Rollback)** — при использовании symlink-деплоя или immutable образов откат сводится к переключению на предыдущую версию, что минимизирует время восстановления.
- **Graceful Shutdown (Бережное завершение)** — корректное завершение работы приложения с перехватом `SIGTERM`, завершением активных соединений и освобождением ресурсов. Критично для минимизации downtime.
- **Cold Start (Холодный старт)** — период прогрева нового экземпляра (JIT-компиляция, прогрев кэшей, подключение к БД). Определяет длительность downtime.
- **Schema Migration (Миграция схемы)** — при Recreate допустимы разрушительные (destructive) изменения схемы БД, так как старая версия уже остановлена. Это ключевое преимущество перед другими стратегиями.

## Основные концепции

### Ключевые идеи

- **Единственная версия в production** — в любой момент времени работает только одна версия приложения. Это исключает проблемы совместимости версий, но создает окно недоступности.
- **Destructive migrations допустимы** — поскольку старая версия уже остановлена, можно выполнять любые изменения схемы БД, включая удаление колонок, изменение типов с блокировкой, переименование таблиц.
- **Простота реализации** — не требует сложной инфраструктуры (L7-балансировщик, Service Mesh, Gateway API). Достаточно механизма остановки старой версии и запуска новой.
- **Предсказуемость** — процесс линейный: stop → deploy → start → verify. Нет промежуточных состояний, когда работают обе версии одновременно.

### Жизненный цикл Recreate

1.  **Подготовка (Pre-deploy)** — проверка ресурсов, бэкап БД, оповещение пользователей о maintenance window.
2.  **Остановка (Drain)** — graceful shutdown старой версии, вывод из балансировщика (если есть), завершение активных соединений.
3.  **Деплой (Deploy)** — установка новой версии (артефакт, образ, конфигурация).
4.  **Прогрев (Warm-up)** — запуск новой версии, прогрев кэшей, проверка health-эндпоинтов.
5.  **Верификация (Verify)** — smoke-тесты, проверка зависимостей (БД, кэш, внешние API).
6.  **Возврат трафика (Cutover)** — включение сервиса в балансировщике или возврат VIP.
7.  **Мониторинг (Observe)** — отслеживание Golden Signals после восстановления работы.

### Взаимодействие с PodDisruptionBudget

`PodDisruptionBudget` (PDB) защищает от добровольных прерываний (`kubectl drain`, плановое обслуживание узла), но **не защищает от rollout-прерываний**. Recreate Deployment контроллер скалирует старый ReplicaSet до 0 реплик в рамках rollout — PDB это не блокирует. Это означает:

- **CI/CD pipeline**, запускающий Recreate rollout, остановит все поды даже при наличии PDB с `minAvailable: 1`.
- PDB защищает только от действий оператора (`drain`, `evict`), но не от логики Deployment controller.
- Для защиты от случайного Recreate rollout на продакшене используйте ** admission-контроллер** (OPA/Gatekeeper/Kyverno), который отклоняет манифесты с `strategy.type: Recreate` и `replicas > 1` без обоснования.

### Взаимодействие с HorizontalPodAutoscaler (HPA)

HPA не влияет на стратегию Deployment напрямую, но при Recreate следует учитывать:

- **Scale-to-zero → scale-up:** если HPA скейлил Deployment до 0 из-за низкой нагрузки, Recreate rollout начнется с 0 реплик. Новые поды появятся только после того, как HPA решит скейлить вверх (на основе метрик).
- **Рекомендация:** фиксируйте `replicas` в Deployment (не используйте HPA с `minReplicas: 0`) или отключайте HPA на время Recreate rollout, чтобы Deployment controller управлял репликами напрямую.

### Когда использовать Recreate

| Сценарий | Причина |
| :--- | :--- |
| **Тяжелые миграции БД** | Изменение типа колонки под блокировку, удаление не-NULL колонок без default |
| **Legacy-монолиты** | Невозможность работы двух версий с одной БД одновременно |
| **Низкая частота релизов** | Раз в месяц/квартал — downtime приемлем при планировании |
| **Dev/Staging среды** | Риск downtime минимален, важна простота |
| **Stateful-сервисы с single-replica** | Невозможность одновременной работы двух инстансов с одним хранилищем |
| **Изменение порта/формата протокола** | Несовместимый API v2 требует полной остановки v1 |

### Сравнение с другими стратегиями

| Критерий | Recreate | Rolling Update | Blue-Green | Canary |
| :--- | :--- | :--- | :--- | :--- |
| **Downtime** | Есть | Минимальный | Zero | Zero |
| **Blast Radius** | 100% | Средний | 100% | Минимальный |
| **Сложность** | Низкая | Средняя | Средняя | Высокая |
| **Стоимость** | 1x | 1x + surge | 2x | 1x + canary |
| **Destructive migrations** | Да | Нет | Нет | Нет |
| **Скорость отката** | Медленная | Средняя | Мгновенная | Быстрая |

## Практические сценарии

### 1. Recreate в Kubernetes

Самый простой вариант — использование стратегии `Recreate` в Deployment. Подходит для фоновых сервисов, batch-воркеров или когда downtime планируемый.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: batch-processor
spec:
  replicas: 1
  minReadySeconds: 10
  progressDeadlineSeconds: 300
  revisionHistoryLimit: 5
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: batch-processor
  template:
    metadata:
      labels:
        app: batch-processor
    spec:
      terminationGracePeriodSeconds: 60
      containers:
      - name: processor
        image: registry.internal/batch-processor:v2.4.0
        ports:
        - containerPort: 8080
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 10
          periodSeconds: 5
        startupProbe:
          httpGet:
            path: /startup
            port: 8080
          failureThreshold: 30
          periodSeconds: 10
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
```

**Валидация:**
```bash
kubectl apply -f deployment-recreate.yaml
kubectl rollout status deployment/batch-processor --timeout=300s
# → deployment "batch-processor" successfully rolled out
```

### 2. Recreate в GitLab CI с approval gate

Пайплайн для planned downtime: деплой блокируется до ручного подтверждения, что окно обслуживания началось.

```yaml
stages:
  - notify
  - deploy
  - verify

notify_team:
  stage: notify
  script:
    - echo "Maintenance window started. Proceed with deployment."
  when: manual
  allow_failure: false

deploy_recreate:
  stage: deploy
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/deployment-recreate.yaml
    - kubectl rollout status deployment/batch-processor --timeout=300s
  environment:
    name: production
    url: https://batch.example.com
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
      allow_failure: false

verify_recreate:
  stage: verify
  image: curlimages/curl:8.22.0
  script:
    - curl -sf https://batch.example.com/healthz || exit 1
    - curl -sf https://batch.example.com/readyz || exit 1
  environment:
    name: production
  needs:
    - deploy_recreate
```

### 3. Recreate через systemd + symlink (традиционная инфраструктура)

Для монолитов и приложений без оркестратора — атомарный откат через симлинк.

```bash
# Остановка старой версии
systemctl stop myapp

# Атомарная смена версии
ln -sfn /opt/apps/myapp/v2.4.0 /opt/apps/myapp/current

# Запуск новой версии
systemctl start myapp

# Верификация
systemctl is-active myapp   # → active
curl -sf http://localhost:8080/healthz   # → OK
readlink /opt/apps/myapp/current   # → /opt/apps/myapp/v2.4.0
```

**В GitLab CI:**
```yaml
recreate_deploy:
  stage: deploy
  image: alpine:3.24
  before_script:
    - apk add --no-cache curl openssh-client
  script:
    - ssh deploy@prod01 "systemctl stop myapp"
    - ssh deploy@prod01 "ln -sfn /opt/apps/myapp/${CI_COMMIT_TAG} /opt/apps/myapp/current"
    - ssh deploy@prod01 "systemctl start myapp"
    - ssh deploy@prod01 "curl -sf http://localhost:8080/healthz"
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### 4. Recreate для батчевых Job (Kubernetes)

Для задач с разрушительными миграциями БД, которые не могут работать параллельно со старой версией.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migration-v2
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migrate
        image: registry.internal/db-migrate:v2.4.0
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-secrets
              key: url
```

**Запуск из GitLab CI:**
```yaml
db_migration:
  stage: deploy
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/job-db-migration.yaml
    - kubectl wait --for=condition=complete job/db-migration-v2 --timeout=600s
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

### 5. Recreate с pre-flight проверками

Пайплайн с обязательными проверками перед деплоем и автоматическим откатом при провале.

```yaml
stages:
  - preflight
  - deploy
  - postflight

preflight_checks:
  stage: preflight
  image: curlimages/curl:8.22.0
  script:
    # Проверка доступности БД
    - curl -sf http://prod-db:5432/health || exit 1
    # Проверка места на диске
    - ssh deploy@prod01 "df -h /opt/apps | awk 'NR==2 {print \$5}' | grep -qv 9[0-9]%"
    # Проверка, что нет других активных деплоев
    - curl -s --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
        "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/deployments" \
        | jq -e '.[] | select(.status == "running")' == null
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_recreate:
  stage: deploy
  image: bitnami/kubectl:1.37
  script:
    - kubectl scale deployment/myapp --replicas=0
    - kubectl wait --for=delete pod -l app=myapp --timeout=120s
    - kubectl apply -f k8s/deployment-recreate.yaml
    - kubectl rollout status deployment/myapp --timeout=300s
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual

postflight_checks:
  stage: postflight
  image: curlimages/curl:8.22.0
  script:
    - curl -sf https://app.example.com/healthz || exit 1
    - curl -sf https://app.example.com/readyz || exit 1
  environment:
    name: production
  needs:
    - deploy_recreate
```

### 6. Recreate через Ansible (традиционная инфраструктура)

Для сред Bare Metal / VM с фиксированным пулом серверов — плейбук с последовательной остановкой старой версии и запуском новой.

```yaml
- name: Recreate deploy myapp
  hosts: app_servers
  serial: 1
  gather_facts: yes
  vars:
    app_version: "2.4.0"
    artifact_url: "https://artifactory.local/myapp-{{ app_version }}.tar.gz"
    install_dir: "/opt/apps/myapp"
    service_name: "myapp"
  tasks:
    - name: Pre-flight — проверка доступности БД
      uri:
        url: "http://{{ db_host }}:5432/health"
        status_code: 200
      delegate_to: localhost

    - name: Pre-flight — проверка места на диске
      command: df -h {{ install_dir }}
      register: disk_usage

    - name: Остановка сервиса
      systemd:
        name: "{{ service_name }}"
        state: stopped

    - name: Ожидание завершения процесса (graceful shutdown)
      wait_for:
        timeout: 60
        sleep: 5

    - name: Развертывание артефакта (immutable)
      unarchive:
        src: "{{ artifact_url }}"
        dest: "{{ install_dir }}/{{ app_version }}"
        remote_src: yes

    - name: Атомарный переключатель symlink
      file:
        src: "{{ install_dir }}/{{ app_version }}"
        dest: "{{ install_dir }}/current"
        state: link
        force: yes

    - name: Запуск сервиса
      systemd:
        name: "{{ service_name }}"
        state: started

    - name: Прогрев — ожидание health-эндпоинта
      uri:
        url: "http://localhost:8080/healthz"
        status_code: 200
      register: health
      until: health.status == 200
      retries: 30
      delay: 10

    - name: Post-flight — smoke-тест
      uri:
        url: "http://{{ inventory_hostname }}:8080/readyz"
        status_code: 200
```

**Запуск с откатом при ошибке:**
```bash
ansible-playbook playbooks/recreate_deploy.yml \
  --limit "tag_env_production:&tag_role_app" \
  --forks 1 \
  --extra-vars "app_version=2.4.0"
# → При ошибке на любом узле playbook останавливается; остальные узлы не затрагиваются.
```

### 7. Recreate с Packer и immutable artifacts (Bare Metal / VM)

Для сред, где требуется полная иммутабельность хоста — Packer собирает Golden Image с новой версией, а Recreate — это замена всей ВМ/физического сервера.

```bash
# 1. Собрать новый образ через Packer
packer build -var "app_version=2.4.0" packer/myapp.json

# 2. Развернуть новый хост (libvirt / VMware / bare metal)
# На практике: Terraform создает новую ВМ из образа, старую останавливает.

# 3. Валидация нового хоста
curl -sf http://new-host.internal:8080/healthz

# 4. Переключение трафика (VIP/VRRP или изменение LB)
echo "set server app_servers/old-host state maint" | socat /var/run/haproxy.sock stdio
echo "set server app_servers/new-host state ready" | socat /var/run/haproxy.sock stdio
```

**SRE-аспект:** Error Budget при Recreate полностью «сжигается» на время downtime. Если SLO = 99.9% (допустимый простой ~43 мин/месяц), а Recreate занимает 5 минут, это ~12% месячного бюджета за один деплой. Планируйте такие деплои на начало месяца, чтобы оставить запас на инциденты.

### 8. Recreate с разрушительными миграциями БД

Классический сценарий для Recreate: изменение схемы БД, несовместимое с работающей версией.

**Паттерн Expand-Contract с Recreate:**

```sql
-- Expand: добавить новую колонку (v1 игнорирует, v2 использует)
ALTER TABLE orders ADD COLUMN total_net NUMERIC(12,2) NULL;

-- Migrate: фоновый батч-перенос (по 1000 строк)
UPDATE orders SET total_net = total WHERE total_net IS NULL AND id BETWEEN :batch_start AND :batch_end;

-- После Recreate деплоя v2 и проверки стабильности:
-- Contract: удалить старую колонку (только после остановки v1)
ALTER TABLE orders DROP COLUMN total;
```

**GitLab CI pipeline с миграцией:**
```yaml
stages:
  - migrate
  - deploy
  - verify

db_migrate_recreate:
  stage: migrate
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/job-db-migration.yaml
    - kubectl wait --for=condition=complete job/db-migration-v2 --timeout=600s
  environment:
    name: production

deploy_recreate:
  stage: deploy
  image: bitnami/kubectl:1.37
  script:
    - kubectl apply -f k8s/deployment-recreate.yaml
    - kubectl rollout status deployment/myapp --timeout=300s
  environment:
    name: production
  rules:
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH
      when: manual
```

**Важно:** destructive DDL (DROP COLUMN, ALTER TYPE) допустим только ПОСЛЕ полной остановки v1. При Recreate это гарантировано. При Rolling Update/CANARY такие изменения приведут к ошибкам в работающих инстансах v1.

## Операции и команды

### Kubernetes — Recreate стратегия

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Применить Recreate Deployment** | `kubectl apply -f deployment-recreate.yaml` | Создает/обновляет Deployment с стратегией Recreate |
| **Откатить Recreate** | `kubectl rollout undo deployment/myapp` | Возвращает к предыдущей ревизии |
| **Проверить статус rollout** | `kubectl rollout status deployment/myapp --timeout=300s` | Ждет завершения rollout |
| **Масштабировать в 0** | `kubectl scale deployment/myapp --replicas=0` | Останавливает все поды |
| **Удалить поды** | `kubectl delete pod -l app=myapp` | Принудительно удаляет поды |
| **Установить deadline rollout** | `kubectl patch deployment/myapp -p '{"spec":{"progressDeadlineSeconds":300}}'` | Откат deployment, если rollout не завершится за 5 минут |
| **Ограничить историю ревизий** | `kubectl patch deployment/myapp -p '{"spec":{"revisionHistoryLimit":5}}'` | Хранит только 5 последних ReplicaSet |
| **Проверить PDB** | `kubectl get poddisruptionbudget` | PDB не блокирует Recreate rollout (см. раздел «Основные концепции») |

### GitLab CI — управление Recreate деплоем

| Действие | Команда / фрагмент | Результат |
| :--- | :--- | :--- |
| **Запуск manual deploy** | `when: manual` в задаче | Блокирует деплой до нажатия кнопки в UI GitLab |
| **Approval перед деплоем** | `environment: production` + Protected Environment | Только authorized users могут запустить деплой |
| **Откат через GitLab UI** | Environments → Rollback | Возвращает к предыдущему успешному deployment job |
| **API отмены пайплайна** | `curl -X POST "https://gitlab.example.com/api/v4/projects/$CI_PROJECT_ID/pipelines/$CI_PIPELINE_ID/cancel"` | Отменяет активный пайплайн |

### systemd — управление Recreate

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Остановка сервиса** | `systemctl stop myapp` | Корректная остановка с graceful shutdown |
| **Атомарный откат** | `ln -sfn /opt/apps/myapp/v2.3.0 /opt/apps/myapp/current && systemctl restart myapp` | Переключение на предыдущую версию |
| **Проверка статуса** | `systemctl is-active myapp` | `active` или `inactive` |
| **Логи сервиса** | `journalctl -u myapp -n 50 --no-pager` | Последние 50 строк логов |

### Docker Compose — Recreate

| Действие | Команда | Результат |
| :--- | :--- | :--- |
| **Полный Recreate** | `docker compose down && docker compose up -d app` | Полная остановка и перезапуск |
| **С перезапуском только одного сервиса** | `docker compose up -d --force-recreate app` | Пересоздает только указанный сервис |
| **Проверка статуса** | `docker compose ps app` | Статус контейнера (running, exited, etc.) |

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Downtime превышает SLA** | Слишком долгий холодный старт (JIT, прогрев кэшей) | Добавить warm-up скрипт перед cutover; увеличить `initialDelaySeconds` в readiness probe; использовать `startupProbe` с `failureThreshold` |
| **Старый процесс не останавливается** | Приложение не перехватывает `SIGTERM` или зависает | Увеличить `TimeoutStopSec` в systemd; добавить обработчик сигнала в код; использовать `ExecStopPost` с проверкой |
| **Address already in use** | Новый процесс пытается занять порт, который еще не освободил старый | Увеличить `TimeoutStopSec`; использовать `Type=notify` для точного контроля; добавить `preStop` hook с `sleep` |
| **Новая версия не проходит readiness** | Проблемы с БД, кэшем или конфигурацией | Проверить логи `kubectl logs`; проверить connectivity к зависимостям; откатить через `rollout undo` |
| **Rollback занимает слишком много времени** | Отсутствие атомарного механизма переключения | Использовать symlink-деплой или immutable образы; тестировать процедуру отката заранее |
| **Конфиг дрейфует между деплоями** | Ручные правки на production-хостах | Переход на immutable образы + Configuration as Code (Ansible/Terraform); ежедневный `ansible-playbook --check --diff` |
| **Пользователи получают 502/504** | Балансировщик слает трафик на остановленный инстанс | Настроить `drain` перед остановкой; увеличить `terminationGracePeriodSeconds`; добавить preStop hook |
| **Миграция БД упала посреди** | Длинная миграция прервана, схема в несогласованном состоянии | Использовать транзакционные миграции; иметь бэкап; предусмотреть `down`-миграции |
| **CI/CD пайплайн зависает** | Деплой ждет завершения rollout, но новый под в `CrashLoopBackOff` | Увеличить `timeout` в задаче; настроить `progressDeadlineSeconds`; добавить `rescue` блок в пайплайн |
| **PDB не блокирует Recreate rollout** | Ожидание, что PDB защитит от одновременной остановки всех подов | PDB защищает только от добровольных прерываний (drain/evict), но не от rollout. Используйте admission-контроллер для запрета Recreate на multi-replica Deployment. |
| **HPA скейлит Deployment в 0 перед Recreate** | Низкая нагрузка → HPA уменьшил реплики до 0 | Отключите HPA на время rollout или установите `minReplicas` фиксированным значением в Deployment. |
| **Rollout зависает в Pending** | Нет места для новых подов (старые еще не завершены, новые не могут запланироваться) | Убедитесь, что `progressDeadlineSeconds` не слишком велик; проверьте квоты namespace; при необходимости добавьте узлы. |
| **Образ на новом хосте (Packer) не стартует** | Packer образ устарел или содержит неправильный артефакт | Проверяйте checksum артефакта в Packer-проверках; используйте `build_manifest` для аудита слоев. |
| **Error Budget сгорает на планируемый downtime** | Recreate деплой запланирован без учета SLO | Вычислите допустимый downtime из SLO (например, 99.9% → ~43 мин/мес). Планируйте Recreate деплой на начало месяца, сохраняя Budget для инцидентов. |

## Лучшие практики

1. **Планируйте maintenance window заранее** — оповестите stakeholders, обновите статус-страницу, выберите время с минимальной нагрузкой.
2. **Автоматизируйте откат** — процедура возврата должна быть одной командой или скриптом, протестированным в staging.
3. **Используйте immutable артефакты** — каждый релиз имеет уникальный тег/хеш; откат = переключение на предыдущий артефакт, а не `latest`.
4. **Graceful shutdown обязателен** — приложение должно перехватывать `SIGTERM`, завершать активные запросы и выходить gracefully.
5. **Pre-flight проверки** — перед деплоем проверяйте доступность зависимостей (БД, кэш, внешние API), место на диске, целостность артефакта.
6. **Post-flight верификация** — после деплоя обязательно smoke-тест и проверка health-эндпоинтов.
7. **Бэкап перед деплоем** — для миграций БД создавайте бэкап перед применением изменений.
8. **Иммутабельность конфигурации** — все изменения через IaC (Ansible/Terraform); никаких ручных правок на production.
9. **Тестируйте откат** — регулярно выполняйте процедуру отката в staging, чтобы убедиться в ее работоспособности.
10. **Мониторинг после деплоя** — первые 15–30 минут после cutover — критический период; держите дежурного на связи.
11. **Учитывайте Error Budget** — планируйте Recreate деплои так, чтобы downtime не «сжег» допустимый бюджет ошибок (SLO). Для SLO 99.9% допустимый простой ~43 минуты в месяц.
12. **Используйте Packer для иммутабельных хостов** — в среде Bare Metal/VM соберите Golden Image с новым артефактом заранее; замена хоста быстрее и предсказуемее, чем in-place обновление.
13. **Ограничивайте Recreate на multi-replica Deployment** — добавьте admission-контроллер (OPA/Gatekeeper/Kyverno), который отклоняет манифесты с `strategy.type: Recreate` и `replicas > 1` без явного обоснования.
14. **Отключайте HPA во время Recreate rollout** — фиксируйте `replicas` или отключайте HPA, чтобы Deployment controller управлял репликами напрямую, а не HPA на основе метрик.

## Граничные случаи и ограничения

- **Stateful-сервисы с единым хранилищем** — при Recreate данные сохраняются (PV/PVC), но если приложение пишет в общую БД без backward compatibility — откат невозможен без восстановления из бэкапа.
- **Долгие транзакции** — при остановке приложения активные транзакции могут быть прерваны; увеличьте `terminationGracePeriodSeconds` или используйте `preStop` hook с паузой.
- **Кластеры с ограниченными ресурсами** — Recreate требует, чтобы новая версия получила все ресурсы сразу; при нехватке CPU/RAM деплой зависнет в `Pending`.
- **WebSocket / gRPC соединения** — при остановке сервиса все активные долгоживущие соединения обрываются; используйте connection draining на балансировщике.
- **Database lock во время миграции** — destructive DDL может блокировать таблицы на минуты; планируйте окно обслуживания с учетом этого.
- **DNS кэширование** — даже после возврата VIP/clients могут держать старый IP; снижайте TTL заранее или используйте L7-балансировщик.
- **Время прогревов** — Java/JVM-приложения с JIT могут требовать 30–60 секунд прогрева; без `startupProbe` readiness probe будет FAIL, а балансировщик пошлет трафик на холодный под.
- **HPA скейлит в 0 перед Recreate** — если HorizontalPodAutoscaler уменьшил реплики до 0, Recreate rollout начнется с 0. Отключайте HPA или фиксируйте `minReplicas` на время деплоя.
- **PodDisruptionBudget не защищает от rollout** — PDB блокирует `kubectl drain` и `evict`, но не блокирует Deployment controller при scale-to-zero в рамках Recreate. Используйте admission-контроллер для запрета опасных манифестов.
- **Ручные миграции БД без транзакций** — при падении midway схема остается в несогласованном состоянии. Используйте инструменты с идempотентностью (Flyway, Liquibase, Alembic) и храните миграции в VCS.
- **Одновременный деплой нескольких зависимых сервисов** — при Recreate сервис A останавливается, затем стартует. Если сервис B зависит от A, планируйте оркестрацию через `serial: true` в GitLab CI или `serial: 1` в Ansible.

## Дополнительная информация

### Связь с другими стратегиями

Recreate часто является частью гибридных подходов:
- **Recreate + Blue-Green** — Blue остается активной, пока Green прогревается; только после проверки происходит cutover (при этом Blue останавливается, но остается в резерве для мгновенного отката).
- **Recreate для batch-воркеров** — CronJob по сути использует Recreate для каждого запуска: старый Job завершается, новый создается после истечения schedule.
- **Recreate как fallback** — если Rolling Update застрял или не удается обеспечить N-1 совместимость, Recreate с maintenance window — единственный вариант.

### Когда НЕ использовать Recreate

- **Критичные продакшен-сервисы с SLA > 99.9%** — downtime неприемлем.
- **Высоконагруженные системы** — остановка всех инстансов сразу создает скачок нагрузки при перезапуске.
- **Системы без возможности maintenance window** — 24/7 сервисы, где downtime даже на 1 минуту = инцидент.
- **Микросервисы с shared state** — если версии несовместимы по протоколу или схеме данных, лучше использовать Blue-Green или Canary.

### См. также

- **[Сравнение стратегий развертывания](./comparison.md)** — матрица выбора стратегий, включая Recreate.
- **[Проверки здоровья и откат](./deployment_health_checks_and_rollback.md)** — архитектура автоматизированного отката, триада проб.
- **[Развертывание в традиционной инфраструктуре](./traditional_infrastructure.md)** — Bare Metal/VM паттерны, symlink-деплой, systemd.
- **[Rolling Update](./rolling_update.md)** — стратегия с минимальным downtime, альтернатива Recreate.
- **[Blue-Green Deployment](./blue_green_deployment.md)** — стратегия с нулевым downtime и мгновенным откатом.
