# Операции cert-manager: мониторинг, резервное копирование и обновление

## Определения

**Операции cert-manager (Day 2 Operations)** — комплекс регулярных задач по обеспечению непрерывности работы (High Availability), мониторингу состояния сертификатов, резервному копированию критических данных и плановому обновлению компонентов контроллера.

**ARI (ACME Renewal Information)** — механизм, позволяющий оператору отслеживать не только срок истечения, но и "окно продления", рекомендованное центром сертификации.

**cmctl** — специализированная CLI-утилита для операционного управления cert-manager (продление, проверка статуса, инспекция секретов).

**ServiceMonitor** — ресурс Custom Resource Definition (CRD) из набора Prometheus Operator, предназначенный для указания, какие endpoints необходимо скрапить для сбора метрик. В контексте cert-manager позволяет автоматически обнаруживать метрики контроллера и webhook без ручной конфигурации Prometheus.

**Workqueue (рабочая очередь)** — внутренняя очередь задач внутри reconciler'ов cert-manager. Задачи добавляются при изменении ресурсов (Certificate, Issuer и т.д.) и обрабатываются последовательно. Глубина очереди (`workqueue_depth`) является ключевым индикатором производительности контроллера.

**Leader Election (лидерство)** — механизм, при котором из нескольких реплик контроллера только одна активна (лидер), а остальные находятся в режиме ожидания. При падении лидера происходит перевыбор. Критично для работы Controller и CA Injector.

---

## Основные концепции

### Архитектура мониторинга

cert-manager предоставляет нативный эндпоинт для сбора метрик в формате Prometheus на порту `9402`. Для интеграции с `kube-prometheus-stack` или Prometheus Operator используется ресурс `ServiceMonitor`.

**Объекты мониторинга:**
1.  **Контроллер:** здоровье процесса, лидерство (Leader Election), нагрузка на очередь (Workqueue).
2.  **Сертификаты:** время до истечения, статус готовности, количество попыток продления.
3.  **Взаимодействие с CA:** частота запросов к ACME-серверу, ошибки API (Rate Limits).
4.  **Webhook:** задержка валидации и ошибки инъекции CA.

**Порты метрик:**
- `9402/tcp` — контроллер (controller-manager).
- `9402/tcp` — webhook.

### Стратегии обновления и риски

Обновление cert-manager требует тщательного тестирования из-за тесной интеграции с Kubernetes API через CRD.

*   **Минорные обновления:** (например, 1.20 -> 1.21) обычно проходят бесшовно.
*   **Мажорные обновления:** требуют проверки совместимости API-версий ресурсов (`v1beta1` vs `v1`).
*   **Риски:** При обновлении Webhook может возникнуть "окно недоступности", в течение которого создание любых ресурсов в кластере (не только cert-manager) может быть заблокировано. Рекомендуется использовать HA-конфигурацию (3 реплики webhook) и `failurePolicy: Fail`.

### PodDisruptionBudget (PDB)

PDB защищает cert-manager от одновременного выселения всех реплик при `kubectl drain` или обновлении узлов кластера.

*   **Особенность:** PDB блокирует только добровольные прерывания (eviction). При аварийном падении узла PDB не применяется.
*   **Конфликт с Cluster Autoscaler:** Если `minAvailable` слишком жесткий (100%), Cluster Autoscaler не сможет завершить масштабирование узла. Используйте `maxUnavailable: 1` для webhook в высоконагруженных кластерах.

### Конфигурация Webhook

Webhook cert-manager валидирует ресурсы при создании и обновлении. Неправильная конфигурация может привести к блокировке всего кластера.

*   **failurePolicy:** Рекомендуется значение `Fail` (по умолчанию в новых версиях). При `Ignore` невалидные сертификаты могут попасть в кластер.
*   **timeoutSeconds:** По умолчанию webhook ожидает ответ 10 секунд. При большой нагрузке увеличьте до `30`, но не более — иначе API-сервер будет держать соединения.
*   **Порт метрик:** Webhook экспортирует метрики на порту `9402` (Prometheus формат).

### Шифрование секретов и защита приватных ключей

Приватные ключи CA и сертификаты хранятся в Kubernetes Secrets. Без дополнительных мер они защищены только RBAC и etcd-шифрованием (при наличии EncryptionConfiguration).

*   **EncryptionConfiguration:** Обязательно включите шифрование `Secrets` на уровне etcd для Production-кластеров.
*   **CSI-драйвер cert-manager (v1.14+):** Генерирует ключи в памяти узла и хранит их в CSI-volume. Приватный ключ никогда не попадает в etcd. Это критично для высокосекретных сред.
*   **RBAC:** Ограничьте доступ к namespace `cert-manager` только администраторами PKI. Секреты с CA-ключами должны быть доступны минимуму сервисных аккаунтов.

### Мониторинг и аудит

Для proactive администрирования необходимо отслеживать не только метрики, но и события Kubernetes.

*   **События (Events):** cert-manager генерирует события `Reason: Readiness` и `Reason: Renewal` при изменении состояния сертификатов. Анализ событий позволяет выявлять проблемы до истечения срока.
*   **Аудит API-сервера:** Включите audit log для ресурсов `cert-manager.io/v1`. Это позволяет отследить, кто создал или изменил Issuer.
*   **Prometheus:** Метрики экспортируются на порту `9402`. Базовый PrometheusRule приведен ниже.

---

## Практические сценарии

### Мониторинг и алертинг

#### Ключевые метрики Prometheus

| Метрика | Описание | Критический порог |
| :--- | :--- | :--- |
| `certmanager_certificate_ready_status` | Статус готовности (condition=True: 1, False: 0) | `< 1` |
| `certmanager_certificate_expiration_timestamp_seconds` | Время истечения (Unix timestamp) | `< 7 days` |
| `certmanager_http_acme_client_request_count` | Количество запросов к ACME API | Аномальный рост |
| `controller_runtime_reconcile_errors_total` | Общее количество ошибок реконсиляции | `> 0` |
| `certmanager_webhook_request_duration_seconds` | Задержка валидации webhook | `> 1s` |
| `workqueue_depth` | Глубина очереди reconciler'ов | `> 100` |
| `leader_election_master_status` | Статус лидерства (1 = master, 0 = backup) | `0` для controller/cainjector |

#### Настройка ServiceMonitor (kube-prometheus-stack)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: cert-manager
  namespace: cert-manager
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: cert-manager
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

#### Настройка алертов (PrometheusRule)

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cert-manager-alerts
  namespace: cert-manager
spec:
  groups:
  - name: cert-manager.rules
    rules:
    - alert: CertManagerCertificateExpiration
      expr: |
        certmanager_certificate_expiration_timestamp_seconds - time() < 7 * 24 * 3600
      for: 1h
      labels:
        severity: warning
      annotations:
        description: "Сертификат {{ $labels.name }} в namespace {{ $labels.namespace }} истекает менее чем через 7 дней."
    
    - alert: CertManagerControllerDown
      expr: up{job="cert-manager"} == 0
      for: 5m
      labels:
        severity: critical
      annotations:
        description: "Контроллер cert-manager недоступен."

    - alert: CertManagerWebhookLatency
      expr: histogram_quantile(0.99, sum(rate(certmanager_webhook_request_duration_seconds_bucket[5m])) by (le)) > 1
      for: 5m
      labels:
        severity: warning
      annotations:
        description: "Webhook cert-manager имеет задержку >1s."

    - alert: CertManagerWorkqueueBacklog
      expr: certmanager_workqueue_depth > 100
      for: 10m
      labels:
        severity: warning
      annotations:
        description: "Очередь reconciler'ов cert-manager заполнена (>100 задач)."
```

### Резервное копирование и восстановление

#### Резервное копирование критических данных

Для восстановления PKI-инфраструктуры необходимо бэкапировать не только ресурсы, но и секреты, содержащие приватные ключи CA и аккаунтов.

```bash
# 1. Резервное копирование всех ресурсов cert-manager
kubectl get issuers,clusterissuers,certificates,certificaterequests -A -o yaml > cert-manager-backup.yaml

# 2. Резервное копирование CA-секретов (самое важное)
# ВАЖНО: Храните эти файлы в зашифрованном виде!
kubectl get secret -n cert-manager -l controller.cert-manager.io/fcl=true -o yaml > ca-secrets-backup.yaml

# 3. Резервное копирование ключей ACME-аккаунтов
kubectl get secret -n cert-manager letsencrypt-prod-account-key -o yaml > acme-account-backup.yaml

# 4. Резервное копирование RBAC (если использовалась кастомная RBAC)
kubectl get roles,rolebindings,clusterroles,clusterrolebindings -l cert-manager.io/issuer=allowed -A -o yaml > cert-manager-rbac-backup.yaml

# 5. Резервное копирование trust-manager Bundle ресурсов
kubectl get bundles -A -o yaml > trust-manager-bundles-backup.yaml
```

#### Восстановление из бэкапа (Disaster Recovery)

Алгоритм восстановления после полной потери данных cert-manager:

1.  **Установка cert-manager:** Установите ту же или более новую версию cert-manager.
2.  **Применение RBAC:** Восстановите кастомные `ClusterRole` и `ClusterRoleBinding`, если использовались.
3.  **Импорт CA-секретов:** Сначала примените файлы с секретами (`ca-secrets-backup.yaml`).
4.  **Импорт ACME-аккаунтов:** Примените `acme-account-backup.yaml`. Это позволяет избежать Rate Limits при повторном выпуске.
5.  **Импорт ресурсов:** Примените манифесты `Issuers` и `Certificates`.
6.  **Верификация:** Проверьте статус через `kubectl get certificate -A`. Контроллер должен подхватить существующие секреты без запроса новых в CA.

#### Проверка целостности бэкапа

Рекомендуется ежеквартально проверять возможность восстановления в изолированном namespace или тестовом кластере.

```bash
# 1. Создайте тестовый namespace
kubectl create namespace cert-manager-restore-test

# 2. Восстановите секреты в тестовом namespace
kubectl apply -f ca-secrets-backup.yaml -n cert-manager-restore-test

# 3. Установите cert-manager в тестовом режиме (если еще не установлен)
# helm install cert-manager-restore ... --namespace cert-manager-restore-test

# 4. Проверьте, что контроллер подхватил секреты без ошибок
kubectl get certificate -n cert-manager-restore-test
```

### Восстановление после сбоя Webhook

При падении webhook создание любых ресурсов в кластере блокируется.

1.  **Проверка статуса подов:**
    ```bash
    kubectl get pods -n cert-manager -l app=cert-manager,app.kubernetes.io/component=webhook
    ```
2.  **Проверка событий:**
    ```bash
    kubectl get events -n cert-manager --field-selector involvedObject.kind=Pod,involvedObject.name=<webhook-pod>
    ```
3.  **Перезагрузка deployment:**
    ```bash
    kubectl rollout restart deployment cert-manager-webhook -n cert-manager
    ```
4.  **Проверка health probes:**
    ```bash
    kubectl describe deployment cert-manager-webhook -n cert-manager | grep -A5 Liveness
    ```
5.  **Если перезагрузка не помогает:** Проверьте, не изменился ли `CABundle` в `ValidatingWebhookConfiguration` и `MutatingWebhookConfiguration`.

### Playbook: Истечение или компрометация CA-ключа

Если промежуточный CA-ключ скомпрометирован или истек:

1.  **Изоляция:** Создайте новый `ClusterIssuer` с новым CA-ключом.
2.  **Перевыпуск всех сертификатов:**
    ```bash
    cmctl renew --all -A
    ```
3.  **Распространение нового CA:** Обновите `ClusterBundle` в trust-manager.
4.  **Отзыв старого CA:** Удалите старый `ClusterIssuer` и связанные секреты только после успешного перевыпуска всех зависимых сертификатов.

### Миграция между кластерами

Алгоритм переноса активных сертификатов без перевыпуска (избегание Rate Limits):

1.  **Кластер-источник:** Экспортируйте ресурсы и секреты (см. выше).
2.  **Новый кластер:** Установите cert-manager той же или более новой версии.
3.  **Импорт секретов:** Сначала примените файлы с секретами (`ca-secrets-backup.yaml`).
4.  **Импорт ресурсов:** Примените манифесты `Issuers` и `Certificates`.
5.  **Верификация:** Проверьте статус через `kubectl get certificate -A`. Контроллер должен подхватить существующие секреты без запроса новых в CA.

### Каскадное обновление и откат (Helm)

Перед обновлением всегда проверяйте текущие версии и делайте бэкап.

```bash
# Просмотр текущей конфигурации
helm get values cert-manager -n cert-manager

# Просмотр доступных версий чарта
helm search repo jetstack/cert-manager --versions | head -20

# Обновление до целевой версии (например, v1.21.0)
# Пояснение: --version указывает версию чарта, --reuse-values сохраняет текущие настройки
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.21.0 \
  --reuse-values \
  --wait \
  --timeout 5m
```

**Rollback при проблемах:**

```bash
# Просмотр истории релизов
helm history cert-manager -n cert-manager

# Откат на предыдущую ревизию
helm rollback cert-manager <revision> -n cert-manager --wait --timeout 5m
```

**Проверка CRD перед обновлением:**

```bash
# Список CRD cert-manager и их версии API
kubectl get crd | grep cert-manager

# Проверка размера CRD (важно для больших кластеров)
kubectl get crd certificates.cert-manager.io -o jsonpath='{.spec.versions[*].name}'
```

### Мониторинг ACME Rate Limits

Публичные CA накладывают ограничения на количество запросов. cert-manager минимизирует количество запросов через ARI и кэширование.

**Диагностика Rate Limits:**

```bash
# Проверка заголовков в событиях Challenge
kubectl get challenge -A -o jsonpath='{range .items[*]}{.metadata.name}: {.status.presented}{"\n"}{end}'

# Поиск событий с Retry-After
kubectl get events -A --field-selector reason=RateLimit --sort-by='.lastTimestamp'
```

**Алерт на аномальный рост запросов:**

```yaml
- alert: CertManagerACMEHighRequestRate
  expr: rate(certmanager_http_acme_client_request_count[5m]) > 50
  for: 5m
  labels:
    severity: warning
  annotations:
    description: "Аномальный рост запросов к ACME API (>50 rps). Проверьте Rate Limits."
```

### Использование cmctl для операционных задач

Утилита `cmctl` (устанавливается отдельно) значительно упрощает Day 2 операции.

```bash
# Принудительное продление сертификата (внеплановая ротация)
cmctl renew <cert-name> -n <namespace>

# Массовое продление всех сертификатов в namespace
cmctl renew --all -n <namespace>

# Массовое продление во всех namespace
cmctl renew --all -A

# Инспекция сертификата в секрете (аналог openssl x509)
cmctl inspect secret <secret-name> -n <namespace>

# Проверка статуса выпуска
cmctl status certificate <cert-name> -n <namespace>

# Полная диагностика всех сертификатов в namespace
cmctl diagnose certificate --namespace <namespace> --all

# Проверка работоспособности API и вебхуков
cmctl check api --wait=2m
```

---

## Стратегии автоматизации продления

### Механизм продления cert-manager

cert-manager отслеживает срок действия сертификата и инициирует продление за `renewBefore` (или по рекомендации ARI). Процесс полностью автоматизирован:

1. **Мониторинг:** Фоновый процесс проверяет `status.notAfter` каждого Certificate.
2. **Инициация:** При достижении порога `renewBefore` (или ARI `suggestedWindow`) создается новый `CertificateRequest`.
3. **Выпуск:** Новый сертификат подписывается CA и сохраняется в Secret.
4. **Обновление:** Ingress-контроллер подхватывает новый Secret (при поддержке hot-reload).

### Стратегия 1: ARI-first (рекомендуется для 2026+)

При использовании cert-manager v1.21+ ARI включен по умолчанию. Контроллер сам определяет оптимальное время продления.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-app-tls
spec:
  secretName: my-app-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - my-app.example.com
  privateKey:
    rotationPolicy: Always
  # Не указывайте renewBefore — ARI определит оптимальное время
  duration: 2160h  # 90 дней
```

**Преимущества:**
- CA определяет оптимальное время (учитывая нагрузку, работы)
- Минимизация rate limits
- Автоматическая обработка массовых отзывов сертификатов

### Стратегия 2: Статическое окно (legacy)

Для совместимости со старыми версиями или конкретных требований:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-app-tls
spec:
  secretName: my-app-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - my-app.example.com
  privateKey:
    rotationPolicy: Always
  duration: 2160h     # 90 дней
  renewBefore: 360h   # 15 дней до истечения
```

**Рекомендации по renewBefore:**
- **Минимум 7 дней** — для покрытия проблем с DNS, rate limits
- **Рекомендуется 14-30 дней** — для production с высокими требованиями uptime
- **Не более 50% от duration** — чтобы избежать преждевременного продления

### Стратегия 3: Короткоживущие сертификаты (mTLS)

Для внутренних mTLS-соединений используются короткоживущие сертификаты:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-mtls
spec:
  secretName: internal-mtls
  issuerRef:
    name: vault-issuer
    kind: Issuer
  dnsNames:
  - my-service.production.svc.cluster.local
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  duration: 216h    # 9 дней
  renewBefore: 72h  # 3 дня
  usages:
  - server auth
  - client auth
```

### Обработка ошибок продления

#### Сценарий: Сертификат не продляется (stuck in Pending)

```bash
# 1. Проверка статуса
cmctl status certificate <name> -n <namespace>

# 2. Проверка CertificateRequest
kubectl get certificaterequest -n <namespace>
kubectl describe certificaterequest <name> -n <namespace>

# 3. Проверка Order (для ACME)
kubectl get order -n <namespace>
kubectl describe order <name> -n <namespace>

# 4. Проверка Challenge
kubectl get challenge -n <namespace>
kubectl describe challenge <name> -n <namespace>

# 5. Принудительное продление
cmctl renew <name> -n <namespace> --force
```

#### Сценарий: Rate Limit при продлении

```bash
# Проверка текущих лимитов
curl -s "https://acme-v02.api.letsencrypt.org/directory" | jq '.meta'

# Мониторинг rate limit через CT-логи
curl -s "https://crt.sh/?q=example.com&output=json" | \
  jq '.[] | .not_after' | sort | uniq -c

# Решение: использование Staging для массового перевыпуска
# 1. Создайте Staging ClusterIssuer
# 2. Переключите Certificate на Staging
# 3. После сброса лимитов верните на Production
```

#### Сценарий: Ошибка ARI (malformed request)

```bash
# Проверка ARI статуса
kubectl get certificate <name> -o jsonpath='{.status.acme.ari}'

# Отключение ARI (временно)
kubectl patch certificate <name> -p '{"spec":{"renewBefore":"360h"}}'

# Проверка логов cert-manager
kubectl logs -n cert-manager -l app=cert-manager | grep -i "ari\|renewal"
```

### Массовое продление (Drain)

При плановом обновлении Issuer или миграции CA:

```bash
# 1. Проверка всех сертификатов
cmctl status certificate --all -A

# 2. Последовательное продление (по 10 штук)
cmctl renew --all -A --concurrency=10

# 3. Мониторинг прогресса
watch -n 5 'cmctl status certificate --all -A | grep -v True'

# 4. Верификация после завершения
kubectl get certificate -A | grep False
```

### Проверка после продления

```bash
# 1. Проверка Secret
kubectl get secret <secret-name> -n <namespace> -o yaml

# 2. Проверка сертификата
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -text -noout | grep -A2 "Validity"

# 3. Проверка SAN
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl x509 -noout -ext subjectAltName

# 4. Проверка цепочки
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | \
  base64 -d | openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt
```

---

## Дополнительная информация

### Лучшие практики эксплуатации

*   **Staging для тестов:** Всегда используйте Let's Encrypt Staging для проверки миграций и обновлений инфраструктуры.
*   **Разделение Issuer:** Используйте разные Issuer для публичных (Let's Encrypt) и внутренних (Vault/Self-signed) нужд для упрощения аудита.
*   **Мониторинг Webhook:** Настройте алерты на `certmanager_webhook_request_duration_seconds`. Рост задержки может замедлить работу всего кластера.
*   **Бэкап CA-ключей:** Храните резервные копии Secrets с приватными ключами промежуточных CA в защищенном хранилище (Vault, AWS Secrets Manager) вне кластера.
*   **Аудит:** Включите audit log для API-сервера с фокусом на ресурсы `cert-manager.io/v1`.

### Ограничения и известные проблемы

*   **etcd-риски:** cert-manager не хранит историю Secret'ов. При случайном удалении Secret восстановление возможно только из внешнего бэкапа или повторным запросом в CA.
*   **ReferenceGrant (Gateway API):** Если `Secret` находится в другом namespace, требуется явный `ReferenceGrant`. Без него Gateway не увидит сертификат.
*   **Rate Limits Let's Encrypt:** При массовой регенерации сертификатов используйте Staging-окружение. Production Rate Limit — 50 дубликатов домена в неделю.
*   **Версия 1.21+:** Удалены права на создание ServiceAccount токенов из стандартного чарта. Для интеграции с AWS IRSA или GCP Workload Identity требуется ручная настройка RBAC.
*   **Совместимость с Ingress-контроллерами:** Некоторые контроллеры (устаревшие версии NGINX Ingress < 1.10) не поддерживают динамическое обновление TLS-секретов без перезапуска. Требуется проверка конфигурации Ingress-контроллера.

### Смотрите также

- **[Cert-manager: Администрирование](./index.md)** — HA, RBAC и Garbage Collection.
- **[Cert-manager: Диагностика](./troubleshooting.md)** — глубокий анализ ошибок и логирования.
- **[Обновление и миграция cert-manager](./upgrades_and_migration.md)** — пошаговый апгрейд версий, breaking changes, rollback.
- **[Масштабирование и производительность](./scaling_and_performance.md)** — tuning при 1000+ сертификатах, HPA, capacity planning.
- **[Cert-manager: GitOps интеграция](./gitops_integration.md)** — настройка ArgoCD/Flux с cert-manager.
- **[Cert-manager: Тестирование в CI/CD](./cicd_testing.md)** — валидация манифестов перед деплоем.
- **[Cert-manager: Production Playbooks](./production_playbooks.md)** — пошаговые инструкции по типичным инцидентам.
- **[Cert-manager: DNS-провайдеры](./dns_providers.md)** — настройка Cloudflare, Route53, Google Cloud DNS.
- **[Предотвращение истечения SSL-сертификатов](../../../Operations/ssl_expiration_prevention.md)** — общие стратегии мониторинга TLS.
