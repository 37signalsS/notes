# Disaster Recovery Runbook: Private CA

## Определения

**Disaster Recovery (DR) Runbook** — пошаговая инструкция по восстановлению PKI-инфраструктуры после катастрофических сбоев: потеря CA-ключей, компрометация Root CA, полная потеря namespace cert-manager или кластера.

**RTO (Recovery Time Objective)** — максимальное допустимое время восстановления. Для PKI-инфраструктуры: < 1 часа для Intermediate CA, < 24 часов для Root CA.

**RPO (Recovery Point Objective)** — максимальная допустимая потеря данных. Для PKI: 0 (потеря приватного ключа CA необратима без бэкапа).

**Blast Radius** — зона поражения при инциденте. Компрометация Root CA → все сертификаты в кластере. Компрометация Intermediate CA → только сертификаты, подписанные этим Intermediate.

---

## Основные концепции

### Классификация инцидентов

| Уровень | Описание | RTO | Восстановление |
| :--- | :--- | :--- | :--- |
| **SEV-1** | Потеря Root CA key | 24 часа | Полная реинициализация PKI |
| **SEV-2** | Компрометация Intermediate CA | 1 час | Ротация Intermediate + перевыпуск |
| **SEV-3** | Потеря namespace cert-manager | 30 минут | Восстановление из бэкапа |
| **SEV-4** | Недоступность cert-manager (Pod crash) | 15 минут | Перезапуск deployment |
| **SEV-5** | Просроченный сертификат | 5 минут | `cmctl renew` |

### Автоматическое vs Ручное восстановление

| Тип данных | Восстановление | Зависимость |
| :--- | :--- | :--- |
| Certificate ресурсы | Автоматическое (cert-manager перевыпустит) | Доступность CA Issuer |
| Issuer/ClusterIssuer | Ручное (восстановление из YAML) | Нет |
| CA Secrets (приватные ключи) | Ручное (восстановление из бэкапа) | Бэкап должен существовать |
| trust-manager Bundle | Автоматическое (после восстановления Secret) | Secret作为источник |
| RBAC | Ручное (восстановление из YAML) | Нет |

---

## Практические сценарии

### Runbook 1: Полная потеря namespace cert-manager

**Триггер:** `kubectl delete namespace cert-manager` или потеря узла с etcd.

#### Шаг 1: Оценка ущерба (5 мин)

```bash
# 1. Проверка наличия namespace
kubectl get namespace cert-manager
# → Если NotFound: namespace удален

# 2. Проверка CA-секретов (самое важное)
kubectl get secrets -n cert-manager 2>/dev/null
# → Если пусто: потеряны CA-ключи

# 3. Проверка ресурсов cert-manager
kubectl get issuers,clusterissuers,certificates -A 2>/dev/null
```

#### Шаг 2: Установка cert-manager (10 мин)

```bash
# Установка cert-manager
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm install cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --create-namespace \
  --version v1.21.0 \
  --set installCRDs=true
```

#### Шаг 3: Восстановление CA-секретов (10 мин)

```bash
# Если есть бэкап CA-секретов:
kubectl apply -f ca-secrets-backup.yaml

# Если бэкапа нет, но есть Root CA key:
kubectl create secret tls hub-root-ca-secret \
  --cert=root-ca.crt \
  --key=root-ca.key \
  -n cert-manager
```

#### Шаг 4: Восстановление Issuer и Certificate ресурсов (5 мин)

```bash
# Восстановление всех ресурсов cert-manager
kubectl apply -f cert-manager-resources-backup.yaml

# Восстановление trust-manager Bundle
kubectl apply -f trust-manager-bundles-backup.yaml
```

#### Шаг 5: Верификация (5 мин)

```bash
# Проверка статуса всех сертификатов
cmctl check api
kubectl get certificate -A
# Все сертификаты должны быть Ready: True

# Проверка trust-manager Bundle
kubectl get bundles -A
```

---

### Runbook 2: Компрометация Intermediate CA

**Триггер:** Обнаружена утечка приватного ключа Intermediate CA.

#### Шаг 1: Немедленная изоляция (2 мин)

```bash
# 1. Удалить скомпрометированный Issuer
kubectl delete clusterissuer intermediate-ca-issuer

# 2. Проверить, не используется ли ключ где-либо ещё
kubectl get secrets -A -o json | jq '.items[] | select(.data["tls.key"] | @base64d | length > 0)'
```

#### Шаг 2: Создание нового Intermediate CA (5 мин)

```yaml
# Новый Intermediate CA, подписанный тем же Root CA
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: intermediate-ca-v2
  namespace: cert-manager
spec:
  isCA: true
  commonName: intermediate-ca-v2
  secretName: intermediate-ca-v2-secret
  duration: 8760h
  renewBefore: 720h
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  issuerRef:
    name: root-ca-issuer
    kind: ClusterIssuer
```

#### Шаг 3: Переключение Issuer (2 мин)

```bash
# Обновить ClusterIssuer на новый Secret
kubectl patch clusterissuer intermediate-ca-issuer --type=merge \
  -p '{"spec":{"ca":{"secretName":"intermediate-ca-v2-secret"}}}'

# Или создать новый Issuer
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: intermediate-ca-issuer-v2
spec:
  ca:
    secretName: intermediate-ca-v2-secret
EOF
```

#### Шаг 4: Принудительный перевыпуск всех сертификатов (10 мин)

```bash
# Перевыпуск всех сертификатов, подписанных скомпрометированным CA
cmctl renew --all -A

# Мониторинг прогресса
watch -n 5 'kubectl get certificate -A | grep -v True'
```

#### Шаг 5: Обновление trust-manager Bundle (2 мин)

```yaml
apiVersion: trust.cert-manager.io/v1alpha2
kind: Bundle
metadata:
  name: internal-trust-bundle
spec:
  sources:
  - secret:
      name: intermediate-ca-v2-secret
      key: ca.crt
  target:
    configMap:
      key: "ca-certificates.crt"
```

#### Шаг 6: Очистка (5 мин)

```bash
# Удалить старый скомпрометированный Secret
kubectl delete secret intermediate-ca-secret -n cert-manager

# Проверить, что все сертификаты перевыпущены
kubectl get certificate -A | grep False
# → Должно быть пусто
```

---

### Runbook 3: Потеря Root CA

**Триггер:** Утерян или скомпрометирован приватный ключ Root CA.

#### Важно

Потеря Root CA — наиболее серьёзный инцидент. Без бэкапа приватного ключа восстановление невозможно без полной реинициализации PKI.

#### Шаг 1: Оценка (5 мин)

```bash
# Есть ли бэкап Root CA key?
ls -la root-ca-backup.key
# → Если нет: реинициализация
# → Если да: восстановление
```

#### Вариант A: Бэкап существует

```bash
# 1. Восстановить Root CA Secret
kubectl create secret tls root-ca-secret \
  --cert=root-ca.crt \
  --key=root-ca.key \
  -n cert-manager \
  --dry-run=client -o yaml | kubectl apply -f -

# 2. Перевыпустить все Intermediate CA
cmctl renew --all -A

# 3. Обновить trust-manager Bundle
# (см. Runbook 2, Шаг 5)
```

#### Вариант B: Бэкапа нет (Полная реинициализация)

```bash
# 1. Создать новый Root CA
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: new-root-selfsigned
spec:
  selfSigned: {}
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: new-root-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: new-root-ca
  secretName: new-root-ca-secret
  duration: 87600h
  privateKey:
    algorithm: ECDSA
    size: 384
  issuerRef:
    name: new-root-selfshared
    kind: ClusterIssuer
EOF

# 2. Создать новый Intermediate CA
kubectl apply -f - <<EOF
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: new-intermediate-ca
  namespace: cert-manager
spec:
  isCA: true
  commonName: new-intermediate-ca
  secretName: new-intermediate-ca-secret
  duration: 8760h
  issuerRef:
    name: new-root-ca-issuer
    kind: ClusterIssuer
EOF

# 3. Обновить все Issuer на новый CA
kubectl patch clusterissuer intermediate-ca-issuer --type=merge \
  -p '{"spec":{"ca":{"secretName":"new-intermediate-ca-secret"}}}'

# 4. Перевыпустить ВСЕ сертификаты
cmctl renew --all -A

# 5. Обновить trust-manager Bundle
kubectl patch bundle internal-trust-bundle --type=merge \
  -p '{"spec":{"sources":[{"secret":{"name":"new-root-ca-secret","key":"ca.crt"}},{"secret":{"name":"new-intermediate-ca-secret","key":"ca.crt"}}]}}'

# 6. Развернуть новый Root CA на Hub (если мультикластер)
# Повторить шаги 1-5 на каждом spoke-кластере
```

---

### Runbook 4: cert-manager Webhook недоступен

**Триггер:** `kubectl apply` возвращает `Internal error occurred: failed calling webhook`.

#### Шаг 1: Диагностика (3 мин)

```bash
# 1. Проверка подов webhook
kubectl get pods -n cert-manager -l app.kubernetes.io/component=webhook

# 2. Проверка логов
kubectl logs -n cert-manager -l app=cert-manager-webhook --tail=50

# 3. Проверка событий
kubectl get events -n cert-manager --field-selector involvedObject.kind=Pod
```

#### Шаг 2: Восстановление (5 мин)

```bash
# 1. Перезапуск deployment
kubectl rollout restart deployment cert-manager-webhook -n cert-manager

# 2. Ожидание готовности
kubectl rollout status deployment cert-manager-webhook -n cert-manager --timeout=120s

# 3. Проверка доступности
kubectl get endpoints -n cert-manager cert-manager-webhook
```

#### Шаг 3: Если перезапуск не помогает (5 мин)

```bash
# 1. Проверить CABundle в ValidatingWebhookConfiguration
kubectl get validatingwebhookconfigurations cert-manager-webhook -o yaml | grep caBundle

# 2. Пересоздать webhook с нуля
helm uninstall cert-manager-webhook -n cert-manager
helm install cert-manager-webhook jetstack/cert-manager-webhook \
  --namespace cert-manager \
  --version v1.21.0
```

---

## Дополнительная информация

### Чеклист бэкапа (выполнять еженедельно)

```bash
#!/bin/bash
# backup-cert-manager.sh

BACKUP_DIR="/backup/cert-manager/$(date +%Y-%m-%d)"
mkdir -p "$BACKUP_DIR"

# 1. CA Secrets (критически важно)
kubectl get secret root-ca-secret intermediate-ca-secret \
  -n cert-manager -o yaml > "$BACKUP_DIR/ca-secrets.yaml"

# 2. Все ресурсы cert-manager
kubectl get issuers,clusterissuers,certificates,certificaterequests \
  -A -o yaml > "$BACKUP_DIR/cert-manager-resources.yaml"

# 3. trust-manager Bundle
kubectl get bundles -A -o yaml > "$BACKUP_DIR/trust-manager-bundles.yaml"

# 4. RBAC
kubectl get roles,rolebindings,clusterroles,clusterrolebindings \
  -l cert-manager.io/issuer=allowed -A -o yaml > "$BACKUP_DIR/cert-manager-rbac.yaml"

# 5. ACME аккаунты (если используются)
kubectl get secret letsencrypt-prod-account-key \
  -n cert-manager -o yaml > "$BACKUP_DIR/acme-account.yaml" 2>/dev/null

echo "Backup завершен: $BACKUP_DIR"
```

### Чеклист ежеквартальной проверки DR

```bash
# 1. Восстановление в тестовом namespace
kubectl create namespace ca-restore-test
kubectl apply -f ca-secrets-backup.yaml -n ca-restore-test

# 2. Создание тестового Issuer
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

# 3. Выпуск тестового сертификата
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

# 4. Проверка
cmctl status certificate test-cert -n ca-restore-test
# → Ready: True

# 5. Очистка
kubectl delete namespace ca-restore-test
```

### Смотрите также

- **[Приватный CA: Операции](./operations.md)** — backup и ротация
- **[Приватный CA: Обзор](./index.md)** — архитектура иерархий
- **[cert-manager: Troubleshooting](../Administration/troubleshooting.md)** — диагностика
- **[Disaster Recovery (общий)](../../../../Concepts/disaster_recovery.md)** — паттерны DR
