# Решение проблем при установке GitLab в Kubernetes

Руководство по диагностике и устранению типичных ошибок, возникающих при развертывании GitLab через официальный Helm-чарт.

---

## Определения

| Термин | Описание |
| :--- | :--- |
| **CrashLoopBackOff** | Статус пода, при котором контейнер запускается и сразу завершается с ошибкой, после чего Kubernetes пытается его перезапустить с экспоненциальной задержкой (10с, 20с, 40с... до 5 минут). |
| **PVC Pending** | Состояние запроса на хранилище, при котором том не может быть выделен из-за отсутствия StorageClass, свободных ресурсов или несовпадения `accessModes`. |
| **Shared Secrets** | Набор ключей и паролей (rails-secret, gitaly-token, otp_key_base, secrets_key_base, db_key_base), которые должны быть идентичны во всех компонентах GitLab для корректного взаимодействия. Генерируются автоматически при первой установке. |
| **Initial Root Password** | Временный пароль администратора (root), генерируемый Helm-чартом при первой установке и хранящийся в Secret `gitlab-initial-root-password`. Действителен 24 часа. |
| **Database Migrations** | Процесс обновления схемы базы данных, выполняемый отдельным Job (`gitlab-migrations`) перед запуском основных сервисов. Использует `db:migrate` и `db:seed`. |
| **Gitaly** | Git-сервис GitLab, отвечающий за хранение и обслуживание репозиториев. Работает как gRPC-сервис. Его недоступность блокирует все git-операции (clone, push, pull). |
| **Sidekiq** | Фоновый процессор задач Ruby, обрабатывающий асинхронные задачи (email-уведомления, импорт проектов, репликацию). Его падение приводит к накоплению очереди и задержкам. |
| **Puma** | HTTP-сервер Ruby, обрабатывающий веб-запросы к GitLab API и UI. Ключевой компонент — его недоступность = полная потеря веб-интерфейса. |
| **KAS (Kubernetes Agent Server)** | Сервер GitLab Kubernetes Agent, обеспечивающий обратное подключение к кластерам. Используется для GitLab Agent for Kubernetes (`agentk`). |
| **Kubelet** | Агент на каждом узле кластера, управляющий подами. Его логи ( `journalctl -u kubelet` ) содержат информацию о событиях планирования, OOM-убийствах и проблемах с контейнерами. |
| **Eviction** | Процесс принудительного завершения пода kubelet-ом при нехватке ресурсов (memory/disk pressure). Поды с классом QoS `BestEffort` убиваются первыми. |
| **Readiness Probe** | Проверка готовности контейнера принимать трафик. Если не проходит, под исключается из Endpoints сервиса, но не перезапускается. |
| **Liveness Probe** | Проверка жизнеспособности контейнера. Если не проходит, kubelet перезапускает контейнер. |
| **Job (Kubernetes)** | Ресурс для однократного выполнения контейнера. В GitLab используется для миграций БД,Inicial root password и backup. |

---

## Основные концепции

### Методология диагностики (Class-Based Troubleshooting)

Каждая проблема GitLab в Kubernetes попадает в один из классов. Определение класса сужает область поиска:

| Класс | Симптомы | Первичные компоненты | Инструменты диагностики |
| :--- | :--- | :--- | :--- |
| **Планирование** | Pod в `Pending`, `SchedulingFailed` | kube-scheduler, node resources | `kubectl describe pod`, `kubectl get events` |
| **Хранилище** | Pod в `Pending`, PVC в `Pending` | StorageClass, PV, provisioner | `kubectl describe pvc`, `kubectl get sc` |
| **Сеть** | Pod `Running`, но 502/504, тайм-ауты | Ingress, Service, NetworkPolicy, DNS | `kubectl exec nslookup`, `kubectl get ingress`, `curl` |
| **Конфигурация** | Pod `CrashLoopBackOff`, `CreateContainerConfigError` | ConfigMap, Secret, values.yaml | `kubectl logs --previous`, `kubectl describe pod` |
| **Ресурсы** | Pod `OOMKilled`, `CrashLoopBackOff`, `Evicted` | CPU/memory limits, node capacity | `kubectl top pod`, `kubectl describe pod` |
| **Зависимости** | Pod `Running`, но 500/401,Waiting for DB | PostgreSQL, Redis, Gitaly, MinIO | `kubectl logs`, `kubectl port-forward` |
| **Миграции** | Pod `Running`, но `Error` в Job,Webservice `Ready 0/1` | gitlab-migrations Job, БД | `kubectl logs -l app=migrations` |
| **Безопасность** | `403 Forbidden`, `Unauthorized`, Webhook fails | RBAC, ServiceAccount, ClusterRole | `kubectl auth can-i`, `kubectl describe sa` |

### Дерево решений (Decision Tree)

```
GitLab не работает
├── Веб-интерфейс недоступен (502/504)
│   ├── Webservice в CrashLoopBackOff → Логи: kubectl logs <pod> --previous
│   ├── Webservice в Pending → Проверить ресурсы и хранилище
│   ├── Webservice Running, Ready 0/1 → Зависимости не готовы
│   │   ├── gitlab-migrations Error → Логи миграций
│   │   ├── Gitaly не готов → Логи Gitaly
│   │   └── PostgreSQL не готов → Логи PostgreSQL
│   └── Webservice Running, Ready 1/1 → Ingress/Service/DNS
│       ├── Ingress не имеет IP → MetalLB/LoadBalancer
│       ├── TLS не работает → cert-manager, Let's Encrypt
│       └── DNS не резолвит → CoreDNS, /etc/resolv.conf
├── Git-операции не работают (clone/push/pull)
│   ├── Gitaly в CrashLoopBackOff → Логи Gitaly
│   ├── Gitaly в Pending → Хранилище (PVC)
│   ├── Gitaly Running, но ошибки → Тайм-ауты, диск
│   └── SSH не работает → Порт 22, gitlab-shell
├── CI/CD не работает
│   ├── Runner не подключается → gitlab-runner logs
│   ├── Job в queued → Runner неRegsitered
│   ├── Job в pending → Нет свободных слотов
│   └── Job failed → Логи Job, ресурсы
├── Registry не работает
│   ├── 401 Unauthorized → Personal Access Token
│   ├── 500 Internal Error → Логи registry
│   └── Disk full → PersistentVolume
└── Уведомления не отправляются
    ├── Sidekiq в CrashLoopBackOff → Логи Sidekiq
    ├── Sidekiq в Pending → Ресурсы
    └── SMTP недоступен → Сетевая доступность
```

### Типология ошибок GitLab

Сбои при установке GitLab в Kubernetes обычно делятся на три уровня:
1.  **Инфраструктурный уровень:** Ошибки планирования (Resources), хранилищ (PVC) и сети (LoadBalancer).
2.  **Уровень зависимостей:** Проблемы с запуском встроенных или внешних PostgreSQL, Redis, MinIO и Gitaly.
3.  **Прикладной уровень:** Ошибки миграций базы данных, невалидные конфигурации в `values.yaml`, конфликты секретов.

### Цепочка зависимостей при запуске

Для успешного старта веб-интерфейса компоненты должны запускаться в строго определенном порядке:
`Storage/PV → PostgreSQL/Redis → gitlab-migrations (Job) → Gitaly → Webservice (Puma) / Sidekiq`.
Если `gitlab-migrations` не завершится успешно, основные поды приложения не перейдут в состояние `Ready`.

### Роли компонентов и их.failure-модели

| Компонент | Роль | Класс QoS (рекомендуемый) | Типичные failure-модели |
| :--- | :--- | :--- | :--- |
| **Webservice (Puma)** | Веб-интерфейс и API | Burstable | OOMKilled при большом количестве запросов, тайм-ауты к БД |
| **Sidekiq** | Фоновые задачи | Burstable | OOMKilled при большом количестве задач, накопление очереди |
| **Gitaly** | Git-сервис | Guaranteed | Тайм-ауты при медленном диске, нехватка памяти при больших репозиториях |
| **KAS** | Kubernetes Agent Server | Burstable | Потеря соединения с агентами, нехватка ресурсов |
| **PostgreSQL** | База данных | Guaranteed | OOMKilled, disk full, replication lag |
| **Redis** | Кэш/очередь | Burstable | OOMKilled, потеря данных (без persistence) |
| **MinIO** | Объектное хранилище | Burstable | Disk full, тайм-ауты при больших объектах |
| **Registry** | Docker Registry | Burstable | Disk full, 401/403, тайм-ауты |
| **Prometheus** | Метрики | Burstable | OOMKilled при большом количестве targets, disk full |

---

## Практические сценарии

### 1. Ошибки миграции базы данных (Job Failed)

**Симптом:** Поды `webservice` и `sidekiq` находятся в `Running`, но `Ready 0/1`. При этом под `gitlab-migrations` имеет статус `Error`.

**Диагностика:**
```bash
# Поиск упавшего Job миграций
kubectl get pods -l app=migrations -n gitlab

# Просмотр логов миграций для выявления причины (например, тайм-аут или ошибка SQL)
kubectl logs -l app=migrations -n gitlab --tail=100

# Проверка.events Job
kubectl describe job gitlab-migrations -n gitlab
```

**Типичные причины:**
- Тайм-аут подключения к PostgreSQL (проверьте `global.psql.host`)
- Невалидные credentials (проверьте Secret `gitlab-db-password`)
- Конфликт миграций (БД была изменена вручную)
- Нехватка ресурсов (Job OOMKilled)

**Решение:**
```bash
# Перезапуск Job миграций
kubectl delete job gitlab-migrations -n gitlab
# Чарт автоматически пересоздаст Job

# Ручной запуск миграций (если Job не пересоздаётся)
kubectl exec -it $(kubectl get pod -n gitlab -l app=webservice -o jsonpath='{.items[0].metadata.name}') \
  -n gitlab -- bundle exec rake db:migrate
```

### 2. Конфликты секретов (Shared Secrets Mismatch)

**Симптом:** Ошибки "401 Unauthorized" между компонентами или "Invalid Token" в логах Sidekiq/Puma.

**Причина:** При переустановке GitLab без полной очистки или при ручном создании секретов возникло расхождение ключей.

**Диагностика:**
```bash
# Просмотр существующих секретов
kubectl get secrets -n gitlab -l release=gitlab

# Проверка ключей rails-secret
kubectl get secret gitlab-rails-secret -n gitlab -o jsonpath='{.data}' | jq

# Проверка ключей gitaly
kubectl get secret gitlab-gitaly-secret -n gitlab -o jsonpath='{.data}' | jq
```

**Решение:** Удалите повреждённые секреты и позвольте чарту пересоздать их:
```bash
# Удаление всех секретов GitLab (ДАННЫЕ НЕ УДАЛЯЮТСЯ — только secrets)
kubectl delete secrets -n gitlab -l release=gitlab

# Переустановка для пересоздания секретов
helm upgrade --install gitlab gitlab/gitlab \
  --namespace gitlab \
  -f values.yaml \
  --timeout 600s \
  --wait
```

### 3. Проблемы с хранилищем (PVC Pending)

**Симптом:** Поды в статусе `Pending`, PVC в статусе `Pending`.

**Диагностика:**
```bash
# Проверка причин ожидания PVC
kubectl describe pvc <pvc_name> -n gitlab

# Проверка доступных StorageClass
kubectl get sc

# Проверка容量 PV
kubectl get pv

# Проверка.events планировщика
kubectl get events -n gitlab --field-selector reason=FailedScheduling
```

**Типичные причины и решения:**

| Причина | Симптом в `describe pvc` | Решение |
| :--- | :--- | :--- |
| **Нет Default StorageClass** | `waiting for a volume to be created` | `kubectl patch sc standard -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'` |
| **Insufficient space** | `waiting for first consumer` (no nodes) | Освободите место на узлах или добавьте node |
| **Multi-AZ Conflict** | `no persistent volumes available` | Используйте `WaitForFirstConsumer` binding mode |
| **Wrong accessModes** | `volume mode "ReadWriteOnce" not found` | Проверьте StorageClass поддерживает RWO |

### 4. Нехватка ресурсов (OOMKilled / Insufficient CPU)

**Симптом:** Поды постоянно перезапускаются (`CrashLoopBackOff`) или не планируются.

**Диагностика:**
```bash
# Проверка OOM событий
kubectl get pods -n gitlab | grep -i oom

# Проверка лимитов и запросов
kubectl describe pod <pod_name> -n gitlab | grep -A 3 Limits

# Проверка фактического потребления
kubectl top pods -n gitlab

# Проверка исторических метрик
kubectl top pods -n gitlab --sort-by=memory
```

**Решение:** Для тестовых сред отключите ресурсоёмкие компоненты или уменьшите их лимиты и размеры томов (с осторожностью):

```yaml
# Оптимизация для dev-окружений
prometheus:
  install: false
gitlab-runner:
  install: false
postgresql:
  primary:
    persistence:
      size: 5Gi # Уменьшение с дефолтных 80ГБ
```

**Для production (увеличение лимитов):**
```yaml
gitlab:
  webservice:
    resources:
      requests:
        cpu: 500m
        memory: 3Gi
      limits:
        cpu: 4
        memory: 8Gi  # Увеличьте если OOMKilled
```

### 5. Ошибки Cert-Manager (SSL Issue)

**Симптом:** Браузер выдает ошибку сертификата, а секрет `gitlab-tls` не создается или пуст.

**Диагностика:**
```bash
# Проверка ресурсов cert-manager
kubectl get certificate -n gitlab
kubectl describe challenge -n gitlab

# Проверка status cert-manager
kubectl get certificaterequest -n gitlab

# Проверка логов cert-manager
kubectl logs -n cert-manager -l app=cert-manager --tail=50
```

**Типичные причины:**
- Ingress-контроллер не имеет внешнего IP
- Порт 80 закрыт (для HTTP-01 challenge)
- DNS не резолвит наружу
- Let's Encrypt rate limit

**Решение:**
```bash
# Проверка доступности порта 80
kubectl run test-curl --rm -it --image=curlimages/curl -- \
  curl -v http://<ingress-ip>/.well-known/acme-challenge/test

# Проверка DNS
kubectl run test-dns --rm -it --image=busybox -- \
  nslookup acme-v02.api.letsencrypt.org
```

### 6. ImagePullBackOff (Ошибка загрузки образа)

**Симптом:** Под в статусе `ImagePullBackOff` или `ErrImagePull`.

**Диагностика:**
```bash
# Проверка статуса пода
kubectl describe pod <pod_name> -n gitlab | grep -A 5 "Events"

# Проверка.image в Deployment
kubectl get deployment -n gitlab -o yaml | grep image
```

**Типичные причины:**
- Образ недоступен в registry (приватный репозиторий)
- Неверный тег образа
- Сетевые проблемы (нет доступа к registry)
- ImagePullSecret отсутствует

**Решение:**
```bash
# Создание секрета для приватного registry
kubectl create secret docker-registry gitlab-registry-secret \
  --docker-server=registry.gitlab.com \
  --docker-username=<user> \
  --docker-password=<token> \
  -n gitlab

# Добавление в values.yaml
global:
  imagePullSecrets:
    - name: gitlab-registry-secret
```

### 7. Gitaly: тайм-ауты и проблемы производительности

**Симптом:** Git-операции (clone, push, pull) завершаются с тайм-аутом. В логах Gitaly: `rpc error: code = DeadlineExceeded`.

**Диагностика:**
```bash
# Проверка логов Gitaly
kubectl logs -n gitlab -l app=gitaly --tail=100

# Проверка.liveness/readiness
kubectl describe pod -n gitlab -l app=gitaly

# Проверка хранилища
kubectl exec -it $(kubectl get pod -n gitlab -l app=gitaly -o jsonpath='{.items[0].metadata.name}') \
  -n gitlab -- df -h /home/git
```

**Типичные причины:**
- Медленный диск (HDD вместо SSD)
- Нехватка памяти (Gitaly OOMKilled)
- Файловая система (ext4 without journal)
- Большой репозиторий (larger than memory)

**Решение:**
```yaml
# Увеличение ресурсов Gitaly
gitlab:
  gitaly:
    resources:
      requests:
        cpu: 500m
        memory: 2Gi
      limits:
        cpu: 2
        memory: 4Gi
    persistence:
      size: 200Gi
      storageClass: fast-ssd  # NVMe/SSD StorageClass
```

### 8. Registry: 401/403 и проблемы доступа

**Симптом:** `docker pull` завершается с `unauthorized` или `forbidden`.

**Диагностика:**
```bash
# Проверка доступности registry
curl -v https://registry.example.com/v2/ -k

# Проверка.token
kubectl get secret -n gitlab gitlab-registry-auth -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq

# Проверка IAM (если используется)
kubectl get serviceaccount -n gitlab
```

**Типичные причины:**
- Personal Access Token истёк или не имеет scope `read_registry`/`write_registry`
- Registry authentication не настроен
- Квота на образы превышена

**Решение:**
```bash
# Ротация токена
# 1. Создайте новый PAT в GitLab (User Settings → Access Tokens)
# 2. Обновите секрет
kubectl create secret docker-registry gitlab-registry-secret \
  --docker-server=registry.example.com \
  --docker-username=deploy-token \
  --docker-password=<new-token> \
  --dry-run=client -o yaml | kubectl apply -f -
```

### 9. Ingress и сетевые проблемы

**Симптом:** Веб-интерфейс доступен по IP, но не по домену. Или 502 Bad Gateway.

**Диагностика:**
```bash
# Проверка Ingress
kubectl get ingress -n gitlab
kubectl describe ingress -n gitlab

# Проверка Service endpoints
kubectl get endpoints -n gitlab

# Проверка DNS
nslookup gitlab.example.com
dig gitlab.example.com

# Проверка TLS
openssl s_client -connect gitlab.example.com:443 -servername gitlab.example.com
```

**Типичные причины:**
- Ingress не имеет внешнего IP
- DNS не указывает на Ingress
- TLS-сертификат невалиден
- NetworkPolicy блокирует трафик

**Решение:**
```bash
# Проверка доступности Webservice (port-forward)
kubectl port-forward -n gitlab svc/gitlab-webservice-svc 8080:8080 &
curl http://localhost:8080

# Проверка NetworkPolicy (если есть)
kubectl get networkpolicy -n gitlab
kubectl describe networkpolicy -n gitlab
```

### 10. RBAC и ServiceAccount

**Симптом:** Ошибки `forbidden`, `cannot list resource`, `User "system:anonymous"`.

**Диагностика:**
```bash
# Проверка ServiceAccount
kubectl get serviceaccount -n gitlab

# Проверка ClusterRoleBinding
kubectl get clusterrolebinding | grep gitlab

# Проверка прав
kubectl auth can-i --list --as=system:serviceaccount:gitlab:default
```

**Типичные причины:**
- ServiceAccount не имеет необходимых прав
- RBAC-политики конфликтуют
- Pod использует `default` ServiceAccount вместо созданного

**Решение:**
```yaml
# Создание ServiceAccount с необходимыми правами
apiVersion: v1
kind: ServiceAccount
metadata:
  name: gitlab-sa
  namespace: gitlab
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: gitlab-role
  namespace: gitlab
rules:
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: gitlab-rolebinding
  namespace: gitlab
subjects:
  - kind: ServiceAccount
    name: gitlab-sa
    namespace: gitlab
roleRef:
  kind: Role
  name: gitlab-role
  apiGroup: rbac.authorization.k8s.io
```

### 11. Helm Release stuck in pending-upgrade

**Симптом:** `helm upgrade` завершается с ошибкой, релиз застрял в статусе `pending-upgrade`.

**Диагностика:**
```bash
# Проверка статуса релиза
helm history gitlab -n gitlab

# Проверка secret релиза
kubectl get secret -n gitlab -l owner=helm,name=gitlab
```

**Решение:**
```bash
# Откат на предыдущую ревизию
helm rollback gitlab <revision> -n gitlab

# Или удаление и переустановка (с сохранением PVC)
helm uninstall gitlab -n gitlab
helm install gitlab gitlab/gitlab \
  --namespace gitlab \
  -f values.yaml \
  --timeout 600s
```

### 12. Shell-доступ (SSH) не работает

**Симптом:** `git clone git@gitlab.example.com:group/project.git` завершается с `Connection refused` или `Permission denied`.

**Диагностика:**
```bash
# Проверка gitlab-shell
kubectl get pods -n gitlab -l app=gitlab-shell

# Проверка Service
kubectl get service -n gitlab -l app=gitlab-shell

# Проверка SSH-ключа
ssh -T git@gitlab.example.com -p 2222
```

**Типичные причины:**
- Порт 22 занят на узле (конфликт с системным SSH)
- gitlab-shell не запущен
- SSH-ключи не настроены

**Решение:**
```yaml
# Использование альтернативного порта
global:
  shell:
    port: 2222  # Вместо 22
```

### 13. Database connection issues

**Симптом:** Webservice/Sidekiq в `Running`, но 500 ошибки с `PG::ConnectionBad` или `FATAL: password authentication failed`.

**Диагностика:**
```bash
# Проверка доступности PostgreSQL
kubectl exec -it $(kubectl get pod -n gitlab -l app=webservice -o jsonpath='{.items[0].metadata.name}') \
  -n gitlab -- bundle exec rails runner "puts ActiveRecord::Base.connection.current_database"

# Проверка credentials
kubectl get secret -n gitlab gitlab-db-password -o jsonpath='{.data.password}' | base64 -d
```

**Решение:**
```yaml
# Проверка конфигурации подключения
global:
  psql:
    host: postgres.db.svc.cluster.local
    port: 5432
    database: gitlabhq_production
    username: gitlab
    password:
      secret: gitlab-db-password
      key: password
    sslmode: require  # Рекомендуется для production
```

---

## Дополнительная информация

### Полезные команды для отладки

| Команда | Описание |
| :--- | :--- |
| `helm status gitlab -n gitlab` | Общий статус релиза и выведенные заметки. |
| `kubectl get events -n gitlab --sort-by='.lastTimestamp'` | Хронология событий в пространстве имен. |
| `kubectl logs -f -l app=webservice -n gitlab -c webservice` | Логи Puma в реальном времени. |
| `kubectl top pods -n gitlab` | Фактическое потребление ресурсов (требует metrics-server). |
| `kubectl describe pod <pod> -n gitlab` | Детальная информация о поде (события, условия, лимиты). |
| `kubectl get pods -n gitlab --field-selector=status.phase!=Running` | Поды не в статусе Running. |
| `kubectl get pvc -n gitlab` | Статус PersistentVolumeClaim. |
| `kubectl get certificates -n gitlab` | Статус TLS-сертификатов. |
| `kubectl get ingress -n gitlab` | Ingress-правила и внешние IP. |
| `helm diff upgrade gitlab gitlab/gitlab -n gitlab -f values.yaml` | Сравнение текущего состояния с предстоящими изменениями (требует `helm-diff`). |

### Диагностический скрипт (one-shot)

```bash
#!/bin/bash
# gitlab-diagnose.sh — быстрая диагностика GitLab в Kubernetes
NAMESPACE=${1:-gitlab}

echo "=== Helm Release Status ==="
helm status gitlab -n $NAMESPACE 2>/dev/null || echo "Release not found"

echo ""
echo "=== Pods Status ==="
kubectl get pods -n $NAMESPACE -o wide

echo ""
echo "=== Pods Not Running ==="
kubectl get pods -n $NAMESPACE --field-selector=status.phase!=Running 2>/dev/null

echo ""
echo "=== PVC Status ==="
kubectl get pvc -n $NAMESPACE

echo ""
echo "=== Events (last 20) ==="
kubectl get events -n $NAMESPACE --sort-by='.lastTimestamp' | tail -20

echo ""
echo "=== Component Health ==="
for component in webservice sidekiq gitaly kas registry; do
  READY=$(kubectl get deploy -n $NAMESPACE -l app=$component -o jsonpath='{.items[0].status.readyReplicas}' 2>/dev/null || echo "0")
  DESIRED=$(kubectl get deploy -n $NAMESPACE -l app=$component -o jsonpath='{.items[0].status.replicas}' 2>/dev/null || echo "0")
  echo "$component: $READY/$DESIRED"
done

echo ""
echo "=== Recent CrashLoops ==="
kubectl get pods -n $NAMESPACE --field-selector=status.phase!=Running -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.reason}{"\n"}{end}' 2>/dev/null
```

### Runbook: инциденты по приоритетам

| Приоритет | Инцидент | Время отклика | Действия |
| :--- | :--- | :--- | :--- |
| **P1 (Critical)** | GitLab полностью недоступен | 15 мин | Проверить Webservice, Ingress, DNS, PostgreSQL. При необходимости — `helm rollback`. |
| **P1 (Critical)** | PostgreSQL недоступен | 15 мин | Проверить под PostgreSQL, PVC, логи. При необходимости — восстановление из бэкапа. |
| **P2 (High)** | Git-операции не работают | 30 мин | Проверить Gitaly, хранилище (IOPS), логи Gitaly. |
| **P2 (High)** | CI/CD пайплайны не запускаются | 30 мин | Проверить Runner, Sidekiq, Redis. |
| **P3 (Medium)** | 502/504 ошибки периодические | 2 часа | Проверить ресурсы Webservice, readiness probes, database latency. |
| **P3 (Medium)** | Registry: ошибки pull/push | 2 часа | Проверить доступность, токены, disk space. |
| **P4 (Low)** | Медленная загрузка страниц | 4 часа | Проверить ресурсы, кэш Redis, количество concurrent users. |

### Эскалация (Escalation Matrix)

| Уровень | Условие | Действие |
| :--- | :--- | :--- |
| **L1 (Junior SRE)** | Типичные проблемы: Pending, CrashLoopBackOff, cert-manager | Следовать данному runbook,搜集 логи |
| **L2 (Senior SRE)** | Не типичные проблемы, данные runbook не помогает | Глубокая диагностика, `kubectl debug`, проверка кластера |
| **L3 (Platform Team)** | Проблемы с Helm-чартом, баги, необходимость форка чарта | Обращение к GitLab Support, GitHub issue |
| **External (GitLab Support)** | Проблемы с лицензией, баги в GitLab, необходимость патчей | Тикет в GitLab Support (https://support.gitlab.com) |

### Метрики для мониторинга ( alerting rules)

```yaml
# gitlab-troubleshooting-alerts.yaml
groups:
  - name: gitlab-health
    rules:
      - alert: GitLabWebserviceDown
        expr: up{job="gitlab-webservice"} == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "GitLab Webservice is down"

      - alert: GitLabMigrationsFailed
        expr: kube_job_status_failed{job_name=~".*gitlab-migrations.*"} == 1
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "GitLab database migration failed"

      - alert: GitLabGitalyHighLatency
        expr: histogram_quantile(0.95, rate(gitaly_seconds_bucket[5m])) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Gitaly p95 latency > 1s"

      - alert: GitLabSidekiqQueueGrowing
        expr: sidekiq_queue_size{queue!=":*"} > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Sidekiq queue size > 1000"

      - alert: GitLabPVCUsageHigh
        expr: (kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes) > 0.85
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "PVC {{ $labels.persistentvolumeclaim }} is {{ $value | humanizePercentage }} full"
```

### Часто задаваемые вопросы

**Q: Как получить доступ к поду для отладки?**
```bash
# Интерактивный shell
kubectl exec -it <pod-name> -n gitlab -- /bin/bash

# Или через ephemeral debug container (Kubernetes 1.23+)
kubectl debug -it <pod-name> -n gitlab --image=busybox --target=<container-name>
```

**Q: Как посмотреть логи предыдущего запуска (если контейнер упал)?**
```bash
kubectl logs <pod-name> -n gitlab --previous
```

**Q: Как перезапустить конкретный под без удаления?**
```bash
kubectl rollout restart deployment <deployment-name> -n gitlab
```

**Q: Как проверить, доступен ли Webservice изнутри кластера?**
```bash
kubectl run test-curl --rm -it --image=curlimages/curl -- \
  curl -sk https://gitlab-webservice-svc:8080 -o /dev/null -w "%{http_code}\n"
```

**Q: Как проверить, подписан ли Let's Encrypt сертификат?**
```bash
kubectl get certificate -n gitlab gitlab-tls -o jsonpath='{.status.conditions[0].message}'
```

### См. также

- [Установка GitLab через Helm](./gitlab_kubernetes_helm_installation.md)
- [Методы доступа к GitLab](./gitlab_kubernetes_access.md)
- [Официальный Troubleshooting Guide GitLab](https://docs.gitlab.com/charts/troubleshooting/)
