# Production Playbooks для cert-manager

## Определения

**Production Playbook** — пошаговая инструкция по реагированию на конкретный тип инцидента в production-среде. Содержит команды, критерии эскалации и критерии восстановления. Отличается от troubleshooting.md тем, что фокусируется на типичных production-инцидентах, а не на диагностике ошибок.

**MTTA (Mean Time To Acknowledge)** — среднее время от момента срабатывания алерта до начала действий по устранению.

**MTTR (Mean Time To Resolve)** — среднее время от обнаружения инцидента до полного восстановления.

**Blast Radius** — зона поражения при инциденте. Webhook недоступен → блокировка всех ресурсов в кластере.

---

## Основные концепции

### Классификация инцидентов

| Уровень | Инцидент | Влияние | MTTA | MTTR |
| :--- | :--- | :--- | :--- | :--- |
| **SEV-1** | Webhook заблокировал кластер | Блокировка любых API-запросов | 1 мин | 5 мин |
| **SEV-2** | Все сертификаты истекли | Полная потеря HTTPS | 5 мин | 15 мин |
| **SEV-3** | CA-ключ скомпрометирован | Риск MITM-атаки | 1 мин | 30 мин |
| **SEV-4** | cert-manager Controller недоступен | Сертификаты не продлеваются | 15 мин | 30 мин |
| **SEV-5** | Rate Limit Let's Encrypt | Невозможность выпуска новых сертификатов | 15 мин | 1–7 дней |
| **SEV-6** | Массовая ротация CA | Необходимость перевыпуска всех сертификатов | 30 мин | 2–4 часа |

---

## Практические сценарии

### Playbook 1: Webhook заблокировал кластер (SEV-1)

**Симптом:** `kubectl apply` возвращает `Internal error occurred: failed calling webhook`

#### Шаг 1: Диагностика (2 мин)

```bash
# 1. Проверка статуса webhook подов
kubectl get pods -n cert-manager -l app=cert-manager,app.kubernetes.io/component=webhook

# 2. Проверка событий webhook
kubectl get events -n cert-manager --field-selector involvedObject.kind=Pod | tail -10

# 3. Проверка доступности webhook endpoints
kubectl get endpoints -n cert-manager cert-manager-webhook

# 4. Проверка ValidatingWebhookConfiguration
kubectl get validatingwebhookconfigurations cert-manager-webhook -o yaml | grep -A5 failurePolicy
```

#### Шаг 2: Восстановление (3 мин)

```bash
# Вариант A: Перезапуск webhook deployment
kubectl rollout restart deployment cert-manager-webhook -n cert-manager

# Вариант B: Если перезапуск не помогает — временно отключить webhook
kubectl patch validatingwebhookconfigurations cert-manager-webhook \
  --type='json' -p='[{"op": "replace", "path": "/webhooks/0/failurePolicy", "value": "Ignore"}]'

# Вариант C: Крайний случай — удалить и пересоздать webhook
kubectl delete deployment cert-manager-webhook -n cert-manager
helm upgrade cert-manager jetstack/cert-manager --namespace cert-manager --reuse-values
```

#### Шаг 3: Верификация (2 мин)

```bash
# Проверка, что webhook работает
cmctl check api --wait=2m

# Проверка, что ресурсы создаются
kubectl apply -f test-certificate.yaml

# Возврат failurePolicy на Fail (если отключали)
kubectl patch validatingwebhookconfigurations cert-manager-webhook \
  --type='json' -p='[{"op": "replace", "path": "/webhooks/0/failurePolicy", "value": "Fail"}]'
```

### Playbook 2: Все сертификаты истекли (SEV-2)

**Симптом:** Массовые ошибки `x509: certificate has expired`

#### Шаг 1: Оценка (3 мин)

```bash
# 1. Найти все просроченные сертификаты
kubectl get certificate -A -o json | jq -r '.items[] | select(.status.notAfter != null) | select(.status.notAfter < now | todate) | "\(.metadata.namespace)/\(.metadata.name) expired: \(.status.notAfter)"'

# 2. Проверить статус cert-manager
kubectl get pods -n cert-manager
kubectl logs -n cert-manager -l app=cert-manager --tail=50 | grep -i error

# 3. Проверить, есть ли pending сертификаты
kubectl get certificate -A -o json | jq -r '.items[] | select(.status.conditions[] | select(.type=="Ready" and .status=="False")) | "\(.metadata.namespace)/\(.metadata.name)"'
```

#### Шаг 2: Массовое продление (10 мин)

```bash
# Продление всех просроченных сертификатов
cmctl renew --all -A

# Или через kubectl (если cmctl недоступен)
kubectl get certificate -A -o json | jq -r '.items[] | select(.status.conditions[] | select(.type=="Ready" and .status=="False")) | "\(.metadata.name) \(.metadata.namespace)"' | \
while read name ns; do
  echo "Renewing $name in $ns"
  cmctl renew "$name" -n "$ns"
done
```

#### Шаг 3: Верификация (5 мин)

```bash
# Мониторинг прогресса
watch -n 5 'kubectl get certificate -A | grep False'

# Проверка, что сертификаты обновились
kubectl get certificate -A -o json | jq -r '.items[] | select(.status.conditions[] | select(.type=="Ready" and .status=="True")) | "\(.metadata.namespace)/\(.metadata.name)"'
```

### Playbook 3: CA-ключ скомпрометирован (SEV-3)

**Симптом:** Обнаружена утечка приватного ключа CA

#### Шаг 1: Немедленная изоляция (5 мин)

```bash
# 1. Удалить скомпрометированный Secret
kubectl delete secret <ca-secret-name> -n cert-manager

# 2. Создать новый ClusterIssuer с новым CA
kubectl apply -f new-cluster-issuer.yaml

# 3. Удалить старый ClusterIssuer
kubectl delete clusterissuer <old-issuer>
```

#### Шаг 2: Перевыпуск сертификатов (30 мин)

```bash
# Массовый перевыпуск всех сертификатов
cmctl renew --all -A --concurrency=10

# Мониторинг
watch -n 5 'cmctl status certificate --all -A | grep -v True'
```

#### Шаг 3: Распространение нового CA (15 мин)

```yaml
# Обновить trust-manager Bundle с новым CA
apiVersion: trust.cert-manager.io/v1alpha1
kind: Bundle
metadata:
  name: ca-bundle
spec:
  sources:
  - useDefaultCAs: true
  - secret:
      name: new-ca-secret
      key: ca.crt
  target:
    configMap:
      key: "trust-bundle.pem"
    namespaceSelector:
      matchLabels: {}
```

### Playbook 4: cert-manager Controller недоступен (SEV-4)

**Симптом:** Сертификаты не продлеваются, Order'ы застряли в pending

#### Шаг 1: Диагностика (3 мин)

```bash
# 1. Проверка статуса controller
kubectl get pods -n cert-manager -l app=cert-manager,app.kubernetes.io/component=controller

# 2. Проверка логов
kubectl logs -n cert-manager -l app=cert-manager,app.kubernetes.io/component=controller --tail=100

# 3. Проверка ресурсов
kubectl top pods -n cert-manager

# 4. Проверка OOMKilled
kubectl describe pods -n cert-manager -l app=cert-manager,app.kubernetes.io/component=controller | grep -A5 "Last State"
```

#### Шаг 2: Восстановление (5 мин)

```bash
# Вариант A: Перезапуск
kubectl rollout restart deployment cert-manager -n cert-manager

# Вариант B: Если OOMKilled — увеличить лимиты
kubectl patch deployment cert-manager -n cert-manager --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "1Gi"}]'

# Вариант C: Масштабирование
kubectl scale deployment cert-manager -n cert-manager --replicas=3
```

#### Шаг 3: Верификация (5 мин)

```bash
# Проверка, что контроллер работает
cmctl check api --wait=2m

# Проверка, что Order'ы обрабатываются
kubectl get order -A | grep -v Valid
```

### Playbook 5: Rate Limit Let's Encrypt (SEV-5)

**Симптом:** Ошибки `429 rateLimited` в логах cert-manager

#### Шаг 1: Оценка (5 мин)

```bash
# 1. Проверка логов на rate limit
kubectl logs -n cert-manager -l app=cert-manager | grep -i "rate\|429\|rateLimited"

# 2. Проверка текущих лимитов
curl -s "https://acme-v02.api.letsencrypt.org/directory" | jq '.meta'

# 3. Проверка количества сертификатов для домена
curl -s "https://crt.sh/?q=example.com&output=json" | jq 'length'
```

#### Шаг 2: Переключение на Staging (10 мин)

```bash
# 1. Создание Staging ClusterIssuer
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging
spec:
  acme:
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    email: admin@example.com
    privateKeySecretRef:
      name: letsencrypt-staging-account-key
    solvers:
    - http01:
        ingress:
          class: nginx
EOF

# 2. Обновление Certificate на Staging
kubectl patch certificate <cert-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/issuerRef/name", "value": "letsencrypt-staging"}]'
```

#### Шаг 3: Возврат на Production (после сброса лимитов)

```bash
# После сброса лимитов (обычно 1 неделя)
kubectl patch certificate <cert-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/issuerRef/name", "value": "letsencrypt-prod"}]'
```

---

## Дополнительная информация

### Контакты для эскалации

| Уровень | Действие | Время |
| :--- | :--- | :--- |
| **L1** | Self-healing (перезапуск, scale) | 0–5 мин |
| **L2** | Ручное вмешательство (patch, rollout) | 5–15 мин |
| **L3** | Эскалация на platform team | 15–30 мин |
| **L4** | Эскалация на vendor (Let's Encrypt, Vault) | > 30 мин |

### Best practices

1. **Мониторинг:** Настройте алерты на `certmanager_certificate_ready_status`, `certmanager_webhook_request_duration_seconds`
2. **PDB:** Всегда используйте PodDisruptionBudget для webhook (minAvailable: 2)
3. **Бэкапы:** Регулярно бэкапьте CA-секреты и ресурсы cert-manager
4. **Тестирование:** Регулярно проводите game days для отработки playbooks
5. **Документация:** Храните playbooks в Git и обновляйте после каждого инцидента

### Смотрите также

- **[Cert-manager: Диагностика](./troubleshooting.md)** — глубокий анализ ошибок.
- **[Cert-manager: Операции](./operations.md)** — мониторинг и резервное копирование.
- **[Let's Encrypt: Incident Response](../LetsEncrypt/letsencrypt_incident_response.md)** — специфичные для LE инциденты.
- **[Disaster Recovery Runbook](../Private_CA/disaster_recovery_runbook.md)** — восстановление после катастрофических сбоев.
