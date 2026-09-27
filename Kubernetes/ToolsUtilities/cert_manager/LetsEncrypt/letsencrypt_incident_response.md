# Let's Encrypt: Реагирование на инциденты (Incident Response)

## Определения

**Incident Response (IR)** — организованный процесс обнаружения, анализа, смягчения и устранения инцидентов, связанных с TLS-сертификатами. В контексте Let's Encrypt инцидентами являются: истечение срока действия сертификата, компрометация приватного ключа, блокировка ACME-аккаунта, массовая невалидация сертификатов и нарушение работы cert-manager.

**MTTA (Mean Time To Acknowledge)** — среднее время от момента срабатывания алерта до начала действий по устранению. Для критических сертификатов (Production, публичные домены): MTTA < 5 минут.

**MTTR (Mean Time To Resolve)** — среднее время от обнаружения инцидента до полного восстановления. Для сертификатов: MTTR < 30 минут для продления, < 2 часов для перевыпуска.

**Blast Radius** — зона поражения при инциденте. Просроченный wildcard-сертификат влияет на все сервисы за этим wildcard. Просроченный single-domain — только на один сервис.

**Runbook** — пошаговая инструкция по реагированию на конкретный тип инцидента. Содержит команды, контакты, критерии эскалации и критерии восстановления.

---

## Основные концепции

### Классификация инцидентов с сертификатами

| Уровень | Тип инцидента | Влияние | MTTA | MTTR |
| :--- | :--- | :--- | :--- | :--- |
| **SEV-1** | Сертификат просрочен + сервис недоступен | Полная потеря доступности | 1 мин | 5 мин |
| **SEV-2** | Сертификат истекает < 24 часов | Риск потери доступности | 5 мин | 15 мин |
| **SEV-3** | ACME-аккаунт заблокирован (rate limit) | Невозможность продления | 15 мин | 1–7 дней |
| **SEV-4** | cert-manager Controller недоступен | Сертификаты не продлеваются | 15 мин | 30 мин |
| **SEV-5** | Компрометация приватного ключа | Риск MITM-атаки | 1 мин | 30 мин |
| **SEV-6** | Challenge не проходит (DNS/Firewall) | Сертификат не выпущен | 30 мин | 1–2 часа |

### Триггеры алертов

| Алерт | Источник | Критичность | Действие |
| :--- | :--- | :--- | :--- |
| `LetEncryptCertificateExpired` | Prometheus | SEV-1 | Немедленное продление |
| `LetEncryptCertificateExpiringSoon` (< 7 дней) | Prometheus | SEV-2 | Плановое продление |
| `certmanager_order_ready_status=False` | Prometheus | SEV-3 | Диагностика ACME |
| `cert-manager pod not running` | Kubernetes | SEV-4 | Перезапуск Pod |
| `ACME rateLimited (429)` | cert-manager logs | SEV-3 | Смена стейджинга |
| `ACME unauthorized (401/403)` | cert-manager logs | SEV-5 | Пересоздание Issuer |

### Быстрая диагностика (First 5 Minutes)

```bash
# 1. Проверка просроченных сертификатов (самое критичное)
kubectl get certificate -A -o json | jq -r '.items[] | select(.status.notAfter != null) | select(.status.notAfter < (now + 7*24*3600 | todate)) | "\(.metadata.namespace)/\(.metadata.name) expires: \(.status.notAfter)"'

# 2. Проверка статуса cert-manager
kubectl get pods -n cert-manager
kubectl get events -n cert-manager --sort-by='.lastTimestamp' | tail -10

# 3. Проверка ACME-заказов в ошибке
kubectl get order -A -o json | jq -r '.items[] | select(.status.state == "invalid" or .status.state == "pending") | "\(.metadata.namespace)/\(.metadata.name) state: \(.status.state)"'

# 4. Проверка webhook
kubectl get endpoints -n cert-manager cert-manager-webhook

# 5. Быстрое продление (если сертификат просрочен)
cmctl renew <cert-name> -n <namespace>
```

---

## Практические сценарии

### Runbook 1: Сертификат просрочен (SEV-1)

**Симптом:** Браузер показывает "Your connection is not private", API-клиенты получают `x509: certificate has expired`.

**Шаг 1: Оценка (1 мин)**
```bash
# Определение каких сервисов коснулся инцидент
kubectl get certificate -A -o json | jq -r '.items[] | select(.status.conditions[] | select(.type=="Ready" and .status=="False")) | "\(.metadata.namespace)/\(.metadata.name)"'

# Проверка, какой сервис использует просроченный сертификат
kubectl get ingress -A -o json | jq -r '.items[] | select(.spec.tls[]?.secretName == "<expired-secret>") | "\(.metadata.namespace)/\(.metadata.name) host: \(.spec.tls[0].hosts[0])"'
```

**Шаг 2: Немедленное продление (5 мин)**
```bash
# Вариант A: Через cmctl
cmctl renew <cert-name> -n <namespace>

# Вариант B: Удаление Secret для принудительного перевыпуска
kubectl delete secret <secret-name> -n <namespace>
# cert-manager автоматически создаст новый Order

# Вариант C: Удаление Certificate + Secret (крайний случай)
kubectl delete certificate <cert-name> -n <namespace>
kubectl delete secret <secret-name> -n <namespace>
# Примените Certificate заново
kubectl apply -f certificate.yaml
```

**Шаг 3: Верификация (2 мин)**
```bash
# Мониторинг нового Order
kubectl get order -n <namespace> -w

# Проверка статуса
cmctl status certificate <cert-name> -n <namespace>

# Проверка нового сертификата
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
```

**Шаг 4: Проверка доступности (1 мин)**
```bash
# Проверка TLS через curl
curl -vI https://app.example.com 2>&1 | grep -E "expire|subject|issuer"

# Проверка через openssl
openssl s_client -connect app.example.com:443 2>/dev/null | openssl x509 -noout -dates
```

### Runbook 2: Компрометация приватного ключа (SEV-5)

**Симптом:** Обнаружена утечка ключа (leaked secret, скомпрометированный под, небезопасное хранилище).

**Шаг 1: Немедленный отзыв (1 мин)**
```bash
# Через ACME API (если ключ аккаунта тоже скомпрометирован — см. Runbook 3)
cmctl renew <cert-name> -n <namespace> --force

# Или через openssl + ACME revokeCert
# Извлечение сертификата
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d > /tmp/leaked.crt

# Отзыв через certbot (если установлен)
certbot revoke --cert-path /tmp/leaked.crt --reason keycompromise
```

**Шаг 2: Перевыпуск с новым ключом (5 мин)**
```bash
# Удаление старого Secret и Certificate
kubectl delete secret <secret-name> -n <namespace>
kubectl delete certificate <cert-name> -n <namespace>

# Применение нового Certificate с ECDSA ключом
kubectl apply -f certificate-ecdsa.yaml
```

**Шаг 3: Расследование (30 мин)**
```bash
# Проверка, как ключ мог быть скомпрометирован
kubectl logs -n cert-manager -l app=cert-manager | grep "<cert-name>"

# Проверка RBAC — кто имел доступ к Secret
kubectl auth can-i get secret <secret-name> -n <namespace> --as=system:serviceaccount:cert-manager:cert-manager
```

### Runbook 3: ACME-аккаунт заблокирован (SEV-3)

**Симптом:** Ошибка `urn:ietf:params:acme:error:rateLimited` или `unauthorized`.

**Шаг 1: Диагностика (5 мин)**
```bash
# Проверка количества Order
kubectl get order -A -o json | jq '.items | length'

# Проверка последних ошибок
kubectl logs -n cert-manager -l app=cert-manager | grep -i "rate\|limit\|429\|unauthorized"

# Проверка статуса Issuer
kubectl describe clusterissuer letsencrypt-prod
```

**Шаг 2: Временное решение (10 мин)**
```bash
# Переключение на Staging (если это не Production-сертификат)
kubectl patch clusterissuer letsencrypt-prod --type=merge \
  -p '{"spec":{"acme":{"server":"https://acme-staging-v02.api.letsencrypt.org/directory"}}}'

# Для Production: ожидание сброса лимитов (от 1 часа до 7 дней)
# В это время — ручное создание сертификата через certbot на внешнем сервере
```

**Шаг 3: Долгосрочное решение**
```bash
# 1. Проверка лимитов через API Let's Encrypt
curl -s https://acme-v02.api.letsencrypt.org/directory | jq '.meta'

# 2. Создание нового ACME-аккаунта (если старый заблокирован)
kubectl delete secret cert-manager-issuer-account-letsencrypt-prod -n cert-manager
kubectl apply -f issuer-new-account.yaml

# 3. Разделение Issuer для разных доменов
# Каждый домен — отдельный ClusterIssuer с отдельным аккаунтом
```

### Runbook 4: cert-manager Controller недоступен (SEV-4)

**Симптом:** Под cert-manager处于 CrashLoopBackOff или Terminating.

**Шаг 1: Оценка (2 мин)**
```bash
# Статус подов
kubectl get pods -n cert-manager -o wide

# Логи контроллера
kubectl logs -n cert-manager -l app=cert-manager --tail=50

# Проверка ресурсов (CPU, Memory)
kubectl top pods -n cert-manager
```

**Шаг 2: Восстановление (10 мин)**
```bash
# Вариант A: Перезапуск
kubectl rollout restart deployment cert-manager -n cert-manager

# Вариант B: Если webhook недоступен
kubectl rollout restart deployment cert-manager-webhook -n cert-manager

# Вариант C: Если поды не стартуют из-за OOM
kubectl patch deployment cert-manager -n cert-manager --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/resources/limits/memory","value":"512Mi"}]'

# Вариант D: Helm upgrade
helm upgrade cert-manager jetstack/cert-manager \
  --namespace cert-manager \
  --version v1.21.0 \
  --set installCRDs=true \
  --reuse-values
```

**Шаг 3: Верификация (3 мин)**
```bash
# Проверка доступности webhook
cmctl check api

# Проверка, что сертификаты снова продлеваются
kubectl get certificate -A -o custom-columns=\
  NAME:.metadata.name,\
  NAMESPACE:.metadata.namespace,\
  READY:.status.conditions[?(@.type=="Ready")].status
```

### Runbook 5: Массовая невалидация сертификатов (SEV-2)

**Симптом:** Let's Encrypt через ARI инициировал массовое продление (например, из-за уязвимости в цепочке доверия).

**Шаг 1: Мониторинг (5 мин)**
```bash
# Проверка ARI-событий
kubectl logs -n cert-manager -l app=cert-manager | grep -i "ari\|renewal-info"

# Проверка количества активных Order
kubectl get order -A -o json | jq '.items | group_by(.status.state) | map({state: .[0].status.state, count: length})'

# Проверка Rate Limits
kubectl logs -n cert-manager -l app=cert-manager | grep -i "rate\|limit"
```

**Шаг 2: Управление продлением (30 мин)**
```bash
# Ограничение параллельных продлений (если rate limit угрожает)
# cert-manager автоматически шардирует Order, но при массовой ротации
# может потребоваться ручное управление

# Просмотр всех сертификатов, требующих продления
kubectl get certificate -A -o json | jq -r '.items[] | select(.status.conditions[] | select(.type=="Ready" and .status=="False")) | "\(.metadata.namespace)/\(.metadata.name)"'

# Поочерёдное продление (если лимиты критичны)
for cert in $(kubectl get certificate -n prod -o name); do
  cmctl renew $cert -n prod
  sleep 10  # Задержка для соблюдения rate limits
done
```

**Шаг 3: Верификация (15 мин)**
```bash
# Проверка CT-логов (сертификаты должны содержать SCT)
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -text | grep -A 5 "CT Precertificate SCTs"

# Проверка через crt.sh
curl -s "https://crt.sh/?q=example.com&output=json" | jq '.[] | {name: .name_value, issuer: .issuer_name, not_after: .not_after}'
```

---

## Дополнительная информация

### Чек-лист перед инцидентом (Proactive Measures)

1. **Мониторинг**: Настройте Prometheus-алерты на `certmanager_certificate_expiration_timestamp_seconds` с порогами 30/14/7/1 дней.
2. **Staging-first**: Всегда тестируйте изменения через Staging.
3. **Разделение Issuer**: Отдельные ClusterIssuer для каждого домена/команды.
4. **ECDSA**: Используйте ECDSA P-256 для ускорения TLS-handshake.
5. **ARI**: Убедитесь, что cert-manager v1.15+ использует ARI.
6. **Backup**: Регулярно бэкапите CA-ключи и ресурсы cert-manager.

### Контакты и эскалация

| Уровень | Контакт | Время ответа |
| :--- | :--- | :--- |
| **L1** | On-call SRE | 5 мин |
| **L2** | Platform Team Lead | 15 мин |
| **L3** | Let's Encrypt Community / Support | 1–24 часа |

### Смотрите также

- **[Let's Encrypt: Диагностика](./letsencrypt_advanced.md)** — решение проблем с ACME-заказами
- **[Disaster Recovery: Private CA](../Private_CA/disaster_recovery_runbook.md)** — DR для внутренних CA
- **[Kubernetes Incident Response](../../../../Kubernetes/Security/incident_response.md)** — IR для Kubernetes-безопасности
- **[SRE Incident Management](../../../../CI-CD/Core_Concepts/incident_response_sre.md)** — общие принципы IR
- **[Let's Encrypt: Обзор](./index.md)** — лимиты и мониторинг
