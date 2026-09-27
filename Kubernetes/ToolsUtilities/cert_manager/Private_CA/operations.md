# Операции приватного CA

## Определения

**Операции приватного CA** — комплекс административных и технических процедур по обеспечению жизненного цикла внутренних удостоверяющих центров. Включает в себя управление иерархией доверия, ротацию ключей, дистрибуцию бандлов и мониторинг состояния сертификатов.

**Цепочка доверия (Chain of Trust)** — последовательность сертификатов, где каждый последующий подписан предыдущим, начиная от доверенного корня (Root CA). Операционная задача — обеспечить корректную передачу всей цепочки (`tls.crt` + `ca.crt`) приложениям.

**Ротация (Rotation)** — процесс замены сертификата или закрытого ключа до истечения срока их действия. Для Private CA ротация может быть плановой (истечение срока) или экстренной (компрометация).

**Экстренная ротация (Emergency Rotation)** — принудительная замена ключа и сертификата при подозрении на компрометацию. В отличие от плановой ротации, выполняется немедленно без ожидания окна `renewBefore` и требует немедленного распространения нового CA через trust-manager.

**Отзыв (Revocation)** — аннулирование сертификата до истечения срока действия. В cert-manager отзыв реализуется через удаление ресурса `Certificate`, но это не гарантирует отклонение подключений с использованием уже выпущенного сертификата. Для надёжного отзыва необходим CRL/OCSP или короткие TTL.

**Резервное копирование (Backup)** — сохранение критических данных PKI-инфраструктуры: CA-секретов (приватные ключи), ресурсов Issuer/Certificate и ключей ACME-аккаунтов. Для Private CA бэкап CA-секретов является приоритетной задачей, так как потеря приватного ключа Intermediate CA делает невозможным выпуск новых сертификатов.

---

## Основные концепции

### Иерархическое управление (2-Tier Ops)

В архитектуре 2026 года операции разделены на два уровня:

1.  **Уровень Root CA:** Редкие операции (раз в 2–5 лет). Корневой ключ должен быть максимально изолирован. Его основная задача — выпуск Intermediate CA.
2.  **Уровень Intermediate CA:** Регулярные операции. Эти CA выпускают сертификаты для сервисов. Именно здесь настраиваются политики (например, разрешенные DNS-имена или типы ключей).

### Жизненный цикл и сроки (Стандарты 2026)

Для минимизации ущерба при компрометации рекомендуется использовать агрессивные сроки ротации:

| Тип ресурса | Рекомендуемый TTL | Окно продления (`renewBefore`) | Политика ключа |
| :--- | :--- | :--- | :--- |
| **Root CA** | 5–10 лет | 1 год | RSA 4096 / ECDSA 384 |
| **Intermediate CA** | 1 год | 30–60 дней | Ed25519 / ECDSA 256 |
| **Service (mTLS)** | 7–30 дней | 2–5 дней | Ed25519 (Always rotate) |

### Механизм ARI (ACME Renewal Information)

cert-manager 1.15+ поддерживает ARI не только для Let's Encrypt, но и для внутренних иерархий. Это позволяет контроллеру более гибко определять момент продления, избегая пиковых нагрузок на API-сервер при массовой ротации.

### Цикл жизни сертификата в cert-manager

Понимание внутреннего конвейера критично для диагностики:

```
Certificate → CertificateRequest → Order/Challenge (ACME) → Secret (tls.crt + tls.key)
     │                                                              │
     │                     ┌────────────────────────────────────────┘
     │                     ▼
     │              Secret монтируется в Pod
     │
     └── При renewBefore: cert-manager создаёт новый CertificateRequest
```

| Этап | Что происходит | Типичная задержка |
| :--- | :--- | :--- |
| `Certificate` создан | cert-manager видит ресурс и создаёт `CertificateRequest` | 1–5 сек |
| `CertificateRequest` обработан | Webhook валидирует, CA Issuer подписывает | 5–30 сек |
| `Secret` обновлён | Новый сертификат записывается в Secret | 1–2 сек |
| Pod видит обновление | Обновление через Volume Mount (auto) или restart | 1–60 мин (取决于 fsVolumeRepollInterval) |

### Резервное копирование Private CA

Для восстановления PKI-инфраструктуры необходимо бэкапировать три уровня данных:

| Уровень | Что бэкапить | Критичность | Частота |
| :--- | :--- | :--- | :--- |
| **CA Secrets** | `root-ca-secret`, `intermediate-ca-secret` | Критическая | При каждом изменении |
| **Ресурсы cert-manager** | Issuer, Certificate, Bundle | Высокая | При изменении + еженедельно |
| **trust-manager ConfigMap** | Целевые ConfigMap с CA-бандлами | Средняя | Ежедневно (автоматически) |

> **Важно:** CA-секреты содержат приватные ключи. Храните бэкапы в зашифрованном виде (GPG, SOPS, Vault) и проверяйте возможность восстановления ежеквартально.

### Мониторинг и алертинг для Private CA

Для обеспечения надежности Private CA необходимо отслеживать метрики cert-manager в Prometheus:

**Ключевые метрики:**

| Метрика | Описание | Критический порог |
| :--- | :--- | :--- |
| `certmanager_certificate_expiration_timestamp_seconds` | Время истечения сертификата | `< 7 дней` для сервисов, `< 90 дней` для CA |
| `certmanager_certificate_ready_status` | Статус готовности (condition=True: 1, False: 0) | `< 1` |
| `certmanager_http_acme_client_request_count` | Количество запросов к ACME API | Аномальный рост |
| `controller_runtime_reconcile_errors_total` | Ошибки реконсиляции контроллера | `> 0` в течение 5 минут |
| `certmanager_webhook_request_duration_seconds` | Задержка webhook | `> 1 сек` |

**Пример PrometheusRule для Private CA:**

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: private-ca-alerts
  namespace: cert-manager
spec:
  groups:
  - name: private-ca.rules
    rules:
    - alert: PrivateCACertificateExpiringSoon
      expr: |
        certmanager_certificate_expiration_timestamp_seconds - time() < 30 * 24 * 3600
        and on(name, namespace)
        certmanager_certificate_is_ca == 1
      for: 1h
      labels:
        severity: warning
      annotations:
        summary: "Intermediate CA {{ $labels.name }} в {{ $labels.namespace }} истекает менее чем через 30 дней"

    - alert: PrivateCACertificateExpired
      expr: certmanager_certificate_expiration_timestamp_seconds < time()
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "Сертификат {{ $labels.name }} в {{ $labels.namespace }} просрочен"

    - alert: PrivateCADistributionFailure
      expr: certmanager_bundle_synced_total{result="error"} > 0
      for: 15m
      labels:
        severity: warning
      annotations:
        summary: "trust-manager не может синхронизировать Bundle {{ $labels.name }}"
```

---

## Практические сценарии

### Глубокая диагностика через cmctl

Утилита `cmctl` предоставляет наиболее полную информацию о состоянии объектов cert-manager.

```bash
# 1. Проверка полной цепочки выпуска
cmctl status certificate my-app-tls -n production
# → Ready: True, Reason: Issued, Expiration: 2026-10-01

# 2. Инспекция состава сертификата (SAN, алгоритм, сроки) без base64
cmctl inspect secret my-app-tls -n production
# → Subject: CN=my-app, SANs: my-app.production.svc.cluster.local, Algorithm: Ed25519

# 3. Принудительный перевыпуск (например, при изменении политики Issuer)
cmctl renew my-app-tls -n production
# → CertificateRequest created

# 4. Проверка готовности управляющих компонентов
cmctl check api
# → cert-manager API is ready

# 5. Диагностика всех ошибок в namespace
cmctl status certificate -n production
# → Выводит статус всех сертификатов в namespace

# 6. Просмотр логов контроллера (для глубокой диагностики)
kubectl logs -n cert-manager -l app=cert-manager --tail=100
```

### Верификация цепочек через openssl

Необходима для подтверждения того, что Intermediate CA корректно подписан корнем, а сервис — промежуточным CA.

```bash
# Проверка соответствия сертификата промежуточному CA (2-tier)
openssl verify -CAfile <(kubectl get secret root-ca-secret -n cert-manager -o jsonpath='{.data.ca\.crt}' | base64 -d) \
  -untrusted <(kubectl get secret intermediate-ca-secret -n cert-manager -o jsonpath='{.data.tls\.crt}' | base64 -d) \
  <(kubectl get secret service-tls-secret -n production -o jsonpath='{.data.tls\.crt}' | base64 -d)
# → OK

# Проверка формата закрытого ключа (Ed25519)
kubectl get secret service-tls-secret -n production -o jsonpath='{.data.tls\.key}' | base64 -d | openssl pkey -noout -text
# → (253 bit) (Ed25519)

# Проверка SAN в сертификате
kubectl get secret service-tls-secret -n production -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -ext subjectAltName
# → DNS:my-app, DNS:my-app.production.svc.cluster.local

# Проверка полной цепочки (Root → Intermediate → Leaf)
kubectl get secret service-tls-secret -n production -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl crl2pkcs7 -nocrl | openssl pkcs7 -print_certs -noout
# → subject=CN = my-app
# → issuer=CN = team-alpha-intermediate-ca
```

### Ротация корневого CA с нулевым простоем (Zero Downtime)

Процедура требует наличия `trust-manager` для поддержки двух корней одновременно в переходный период.

1.  **Добавление нового корня:** Создайте новый Root CA Certificate (v2).
2.  **Обновление Bundle:** Добавьте публичный ключ нового корня в `trust-manager` Bundle. Теперь приложения доверяют и старому, и новому CA.
    ```yaml
    spec:
      sources:
      - secret: { name: root-ca-v1-secret, key: ca.crt }
      - secret: { name: root-ca-v2-secret, key: ca.crt }
    ```
3.  **Переключение Issuer:** Обновите `ClusterIssuer`, чтобы он использовал Secret нового корня (v2).
4.  **Перевыпуск цепочки:** Выполните `cmctl renew --all`. Новые сертификаты будут подписаны новым корнем.
5.  **Очистка:** Когда все приложения обновятся, удалите v1 из Bundle и кластера.

### Экстренная ротация при компрометации

Если подозревается компрометация приватного ключа Intermediate CA, выполняется немедленная ротация:

```bash
# 1. Немедленно удалите скомпрометированный Issuer
kubectl delete clusterissuer intermediate-ca-issuer

# 2. Создайте новый Intermediate CA, подписанный тем же Root CA
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: intermediate-ca-v2
  namespace: cert-manager
spec:
  isCA: true
  commonName: "team-alpha-intermediate-ca-v2"
  secretName: intermediate-ca-v2-secret
  duration: 8760h
  renewBefore: 720h
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  issuerRef:
    name: root-ca-issuer
    kind: ClusterIssuer
EOF

# 3. Обновите ClusterIssuer на новый Secret
kubectl patch clusterissuer intermediate-ca-issuer --type=merge \
  -p '{"spec":{"ca":{"secretName":"intermediate-ca-v2-secret"}}}'

# 4. Принудительно перевыпустите все сертификаты
cmctl renew --all

# 5. Обновите trust-manager Bundle (если используется)
kubectl patch bundle internal-trust-bundle --type=merge \
  -p '{"spec":{"sources":[{"secret":{"name":"intermediate-ca-v2-secret","key":"ca.crt"}}]}}'
```

### Проверка целостности цепочки

Периодическая верификация корректности всей цепочки доверия:

```bash
#!/bin/bash
# check-chain.sh — проверка цепочки для всех Certificate в namespace

NAMESPACE=${1:-production}

echo "=== Проверка цепочки сертификатов в namespace: $NAMESPACE ==="

ROOT_CA=$(kubectl get secret root-ca-secret -n cert-manager -o jsonpath='{.data.ca\.crt}' | base64 -d)

kubectl get certificate -n $NAMESPACE -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.secretName}{"\n"}{end}' | \
while read CERT_NAME SECRET_NAME; do
    echo "--- $CERT_NAME ---"
    
    # Извлекаем сертификат из Secret
    CERT=$(kubectl get secret $SECRET_NAME -n $NAMESPACE -o jsonpath='{.data.tls\.crt}' | base64 -d)
    
    # Извлекаем Intermediate CA (если есть в tls.crt)
    INTERMEDIATE=$(echo "$CERT" | sed -n '/BEGIN CERTIFICATE/,/END CERTIFICATE/p' | tail -n +2)
    
    if [ -n "$INTERMEDIATE" ]; then
        echo "$INTERMEDIATE" > /tmp/intermediate.pem
        echo "$CERT" > /tmp/leaf.pem
        
        RESULT=$(openssl verify -CAfile <(echo "$ROOT_CA") -untrusted /tmp/intermediate.pem /tmp/leaf.pem 2>&1)
    else
        echo "$CERT" > /tmp/leaf.pem
        RESULT=$(openssl verify -CAfile <(echo "$ROOT_CA") /tmp/leaf.pem 2>&1)
    fi
    
    if echo "$RESULT" | grep -q "OK"; then
        echo "  Статус: OK"
    else
        echo "  ОШИБКА: $RESULT"
    fi
    
    # Проверка срока действия
    EXPIRY=$(echo "$CERT" | openssl x509 -noout -enddate | cut -d= -f2)
    echo "  Истекает: $EXPIRY"
    echo ""
done

rm -f /tmp/intermediate.pem /tmp/leaf.pem
```

### Управление отзывом (Revocation)

Для Private CA в cert-manager отзыв сертификатов реализуется через механизм **CertificateRequests**.

-   **Отзыв через удаление:** Удаление ресурса `Certificate` не аннулирует уже выпущенный сертификат в Secret.
-   **CRL/OCSP:** По умолчанию cert-manager не управляет CRL-файлами. Если вашему приложению (например, Nginx/Angie) требуется проверка отзыва, необходимо:
    1.  Использовать внешний PKI-бэкенд (например, HashiCorp Vault через cert-manager Issuer).
    2.  Либо использовать очень короткие TTL (1–2 дня), где отзыв заменяется простым непродлением.

### Резервное копирование и восстановление Private CA

#### Процедура бэкапа

```bash
# 1. Бэкап CA-секретов (критически важный шаг)
# ВАЖНО: Храните эти файлы в зашифрованном виде!
kubectl get secret root-ca-secret -n cert-manager -o yaml > root-ca-backup.yaml
kubectl get secret intermediate-ca-secret -n cert-manager -o yaml > intermediate-ca-backup.yaml

# 2. Бэкап всех ресурсов cert-manager
kubectl get issuers,clusterissuers,certificates,certificaterequests -A -o yaml > cert-manager-resources-backup.yaml

# 3. Бэкап trust-manager Bundles
kubectl get bundles -A -o yaml > trust-manager-bundles-backup.yaml

# 4. Бэкап RBAC-конфигурации (если используется делегирование)
kubectl get roles,rolebindings,clusterroles,clusterrolebindings -l cert-manager.io/issuer=allowed -A -o yaml > cert-manager-rbac-backup.yaml
```

#### Процедура восстановления

```bash
# 1. Восстановление CA-секретов (ПРИОРИТЕТ)
kubectl apply -f root-ca-backup.yaml
kubectl apply -f intermediate-ca-backup.yaml

# 2. Восстановление ресурсов cert-manager
kubectl apply -f cert-manager-resources-backup.yaml

# 3. Восстановление trust-manager Bundles
kubectl apply -f trust-manager-bundles-backup.yaml

# 4. Верификация
cmctl check api
kubectl get certificate -A
# Все сертификаты должны быть в статусе Ready: True
```

#### Проверка целостности бэкапа

Рекомендуется ежеквартально проверять возможность восстановления в изолированном namespace или тестовом кластере:

```bash
# 1. Создайте тестовый namespace
kubectl create namespace ca-restore-test

# 2. Восстановите CA-секрет
kubectl apply -f root-ca-backup.yaml -n ca-restore-test
kubectl apply -f intermediate-ca-backup.yaml -n ca-restore-test

# 3. Создайте тестовый Issuer
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: test-issuer
  namespace: ca-restore-test
spec:
  ca:
    secretName: intermediate-ca-secret
EOF

# 4. Выпустите тестовый сертификат
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: test-cert
  namespace: ca-restore-test
spec:
  secretName: test-cert-secret
  issuerRef:
    name: test-issuer
    kind: Issuer
  dnsNames:
    - test.example.com
EOF

# 5. Проверьте статус
cmctl status certificate test-cert -n ca-restore-test
# → Ready: True

# 6. Очистка
kubectl delete namespace ca-restore-test
```

### Миграция Private CA между кластерами

Алгоритм переноса активных сертификатов без перевыпуска (избегание повторной генерации ключей):

1.  **Кластер-источник:** Экспортируйте CA-секреты и ресурсы.
    ```bash
    kubectl get secret root-ca-secret intermediate-ca-secret -n cert-manager -o yaml > ca-secrets.yaml
    kubectl get issuers,clusterissuers,certificates -A -o yaml > cert-manager-resources.yaml
    kubectl get bundles -A -o yaml > trust-manager-bundles.yaml
    ```
2.  **Новый кластер:** Установите cert-manager и trust-manager той же или более новой версии.
3.  **Импорт секретов:** Сначала примените файлы с секретами (порядок важен — корень первым).
    ```bash
    kubectl apply -f ca-secrets.yaml
    ```
4.  **Импорт ресурсов:** Примените манифесты `Issuers`, `Certificates` и `Bundles`.
    ```bash
    kubectl apply -f cert-manager-resources.yaml
    kubectl apply -f trust-manager-bundles.yaml
    ```
5.  **Верификация:** Проверьте статус через `cmctl status certificate -A`. Контроллер должен подхватить существующие секреты без запроса новых в CA.

> **Важно:** При миграции убедитесь, что kubeconfig нового кластера имеет доступ к API-серверу cert-manager webhook. Если webhook не доступен, создание ресурсов cert-manager будет заблокировано.

---

## OCSP/CRL для приватных CA

### Проблема отзыва сертификатов в Private CA

cert-manager не предоставляет встроенный OCSP-Responder или генерацию CRL для приватных CA. Удаление ресурса `Certificate` не аннулирует уже выпущенный сертификат в Secret. Существует три подхода к решению:

| Подход | Механизм | Когда использовать |
| :--- | :--- | :--- |
| **Короткие TTL** | Сертификат живёт 1-7 дней, отзыв заменяется непродлением | Рекомендуется для绝大多数 случаев |
| **OCSP через Vault** | Vault PKI предоставляет встроенный OCSP-Responder | Enterprise, compliance |
| **CRL через Step-CA** | Step-CA генерирует CRL автоматически | Air-gapped среды |

### Рекомендация: короткие TTL вместо OCSP/CRL

В контейнерных средах короткоживущие сертификаты (1-24 часа) являются предпочтительным подходом, так как:

- Нет необходимости в инфраструктуре OCSP/CRL
- Компрометированный сертификат автоматически становится бесполезным через TTL
- Ротация ключей происходит часто, что снижает risk window
- Проще в эксплуатации и масштабировании

```yaml
# Пример: сертификат с TTL 24 часа
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: short-lived-service
spec:
  duration: 24h
  renewBefore: 1h
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
```

### Настройка CRL через Step-CA (если.required)

```bash
# Step-CA автоматически поддерживает CRL
# Включение CRL в конфигурации Step-CA:
step ca provisioner update acme --enable-SSH=false --crldp http://step-ca.step-ca.svc.cluster.local:9000/1.0/crl

# Получение CRL
curl http://step-ca.step-ca.svc.cluster.local:9000/1.0/crl -o crl.pem

# Просмотр CRL
openssl crl -inform PEM -in crl.pem -text -noout
```

---

## Capacity planning для cert-manager

### Ключевые метрики для планирования

| Метрика | Описание | Порог для масштабирования |
| :--- | :--- | :--- |
| `certmanager_workqueue_depth` | Глубина очереди reconciler'ов | > 100 стабильно |
| `certmanager_reconcile_errors_total` | Ошибки реконсиляции | > 0 в течение 5 минут |
| `certmanager_certificate_ready_status` | Доля готовых сертификатов | < 95% |
| `certmanager_webhook_request_duration_seconds` | Задержка webhook | P99 > 1 секунды |
| `container_memory_working_set_bytes` | Потребление памяти контроллером | > 80% от limits |

### Формулы расчета ресурсов

```
# Контроллер: 1 CPU core на ~500 активных сертификатов
# Memory: ~1MB на каждый отслеживаемый Certificate ресурс
# Webhook: 1 CPU core на ~100 запросов/сек

# Пример для кластера с 2000 сертификатов:
# controller.resources.limits.cpu = 4 cores
# controller.resources.limits.memory = 4Gi
# webhook.replicaCount = 3
```

### Рекомендуемая конфигурация по нагрузке

| Количество сертификатов | Controller replicas | Memory limits | Webhook replicas |
| :--- | :--- | :--- | :--- |
| < 100 | 1 | 256Mi | 1 |
| 100-500 | 2 | 512Mi | 2 |
| 500-2000 | 3 | 1Gi | 3 |
| > 2000 | 3+ (HPA) | 2Gi+ | 3+ |

### Пример HPA для контроллера

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: cert-manager-hpa
  namespace: cert-manager
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: cert-manager
  minReplicas: 2
  maxReplicas: 5
  metrics:
  - type: Pods
    pods:
      metric:
        name: workqueue_depth
      target:
        type: AverageValue
        averageValue: "50"
```

---

## Чеклист миграции версий cert-manager

### Перед обновлением

- [ ] Проверить текущую версию: `helm list -n cert-manager`
- [ ] Проверить версию CRD: `kubectl get crd certificates.cert-manager.io -o jsonpath='{.spec.versions[*].name}'`
- [ ] Проверить совместимость API (v1beta1 → v1): `kubectl get issuers,clusterissuers,certificates -A -o yaml | grep apiVersion`
- [ ] Сделать бэкап CA-секретов: `kubectl get secrets -n cert-manager -o yaml > backup.yaml`
- [ ] Сделать бэкап всех ресурсов: `kubectl get issuers,clusterissuers,certificates -A -o yaml > resources.yaml`
- [ ] Проверить статус всех сертификатов: `cmctl status certificate -A`
- [ ] Убедиться, что webhook доступен: `cmctl check api`

### Во время обновления

```bash
# 1. Обновление CRD (если требуется)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v<NEW_VERSION>/cert-manager.crds.yaml

# 2. Обновление Helm-чарта
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v<NEW_VERSION> \
  --reuse-values \
  --wait \
  --timeout 5m

# 3. Проверка подов
kubectl get pods -n cert-manager
# → Все поды должны быть Running и Ready

# 4. Проверка webhook
cmctl check api
```

### После обновления

- [ ] Проверить статус всех сертификатов: `cmctl status certificate -A`
- [ ] Проверить логи контроллера на ошибки: `kubectl logs -n cert-manager -l app=cert-manager --tail=50`
- [ ] Проверить, что webhook работает: `cmctl check api`
- [ ] Проверить trust-manager: `kubectl get bundles -A`
- [ ] Протестировать выпуск нового сертификата (self-signed)
- [ ] Проверить метрики в Prometheus: `certmanager_certificate_ready_status == 0`

### Rollback при проблемах

```bash
# 1. Просмотр истории релизов
helm history cert-manager -n cert-manager

# 2. Откат на предыдущую версию
helm rollback cert-manager <REVISION> -n cert-manager --wait --timeout 5m

# 3. Если CRD были обновлены — откат CRD вручную
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v<OLD_VERSION>/cert-manager.crds.yaml

# 4. Проверка после отката
cmctl check api
kubectl get certificate -A | grep False
```

### Известные проблемы при обновлении

| Версия | Проблема | Решение |
| :--- | :--- | :--- |
| 1.19 → 1.20 | Удалены некоторые beta API | Мигрировать все ресурсы на `v1` |
| 1.20 → 1.21 | Удалены права на создание ServiceAccount токенов | Добавить `serviceaccounts/token: create` в ClusterRole |
| 1.21+ | Webhook timeout при большом количестве ресурсов | Увеличить `webhook.timeoutSeconds` до 30 |

---

## Дополнительная информация

### Частые ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `X509: certificate signed by unknown authority` | Пропущена дистрибуция CA | Проверить Bundle в trust-manager и монтирование в поде |
| `Invalid Intermediate Chain` | Intermediate CA не имеет `isCA: true` | Проверить спецификацию Certificate для Intermediate |
| `Algorithm mismatch` | Попытка подписать Ed25519 через RSA Issuer | Привести алгоритмы в иерархии к единому стандарту |
| `Secret not updated` | Зависший `CertificateRequest` | Очистить старые запросы: `kubectl delete certificaterequest -l ...` |
| `CertificateRequest pending` | Webhook недоступен или отклонил запрос | Проверить логи webhook: `kubectl logs -n cert-manager -l app=cert-manager-webhook` |
| `Bundle not syncing` | trust-manager не может достичь API-сервера | Проверить RBAC для trust-manager ServiceAccount |
| `Too many retries` | Проблемы с сетью или CA-сервером | Проверить логи контроллера и увеличить `backoff` в Issuer |
| `Rate limit exceeded` | Слишком частые запросы к CA (ACME) | Увеличить интервал между запросами, использовать ARI |
| `Secret already exists` | Конфликт с существующим Secret | Удалить конфликтующий Secret или использовать `secretName` |

### Лучшие практики эксплуатации

-   **Staging для тестов:** Всегда используйте Let's Encrypt Staging для проверки миграций и обновлений инфраструктуры.
-   **Разделение Issuer:** Используйте разные Issuer для публичных (Let's Encrypt) и внутренних (Vault/Self-signed) нужд для упрощения аудита.
-   **Мониторинг Webhook:** Настройте алерты на `certmanager_webhook_request_duration_seconds`. Рост задержки может замедлить работу всего кластера.
-   **Ежеквартальная проверка бэкапов:** Восстанавливайте CA в тестовом namespace для подтверждения целостности данных.
-   **Автоматизация:** Используйте `cmctl renew --all` в CronJob для массовой ротации при изменении политики ключей.

### Смотрите также

-   **[Приватный CA: Обзор](./index.md)** — архитектура и выбор типа иерархии.
-   **[Приватный CA: Сценарии](./scenarios.md)** — готовые YAML-манифесты для развертывания.
-   **[Обновление и миграция cert-manager](../Administration/upgrades_and_migration.md)** — пошаговый апгрейд версий.
-   **[Масштабирование и производительность](../Administration/scaling_and_performance.md)** — capacity planning для Private CA.
-   **[Cert-manager: Troubleshooting](../Administration/troubleshooting.md)** — общая диагностика контроллера.
