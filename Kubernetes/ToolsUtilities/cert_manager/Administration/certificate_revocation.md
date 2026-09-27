# Отзыв сертификатов в cert-manager

## Определения

**Certificate Revocation (Отзыв сертификата)** — процесс аннулирования сертификата до истечения срока его действия. В cert-manager отзыв реализуется через удаление ресурса `Certificate`, но это не гарантирует отклонение подключений с использованием уже выпущенного сертификата. Для надёжного отзыва необходим внешний механизм (CRL/OCSP) или короткие TTL.

**CRL (Certificate Revocation List)** — список серийных номеров отозванных сертификатов, подписанный CA. Клиенты загружают CRL и проверяют, входит ли сертификат в список отозванных. Недостаток: задержка обновления (до 24 часов) и растущий размер файла.

**OCSP (Online Certificate Status Protocol)** — протокол проверки статуса конкретного сертификата в реальном времени. Клиент запрашивает статус у OCSP-резольвера CA и получает ответ: good, revoked или unknown. Преимущество: мгновенный отзыв. Недостаток: задержка запроса, проблемы приватности.

**OCSP Stapling** — механизм, при котором сервер сам запрашивает OCSP-ответ и передаёт его клиенту в процессе TLS-рукопожатия. Устраняет необходимость прямого обращения клиента к OCSP-резольверу, ускоряя соединение и повышая приватность.

**Short-lived Certificates (Короткоживущие сертификаты)** — сертификаты с очень коротким сроком жизни (часы-дни). Минимизируют необходимость CRL/OCSP, так как просроченный сертификат автоматически недействителен. Рекомендация 2026 года: ≤90 дней для публичных, ≤30 дней для внутренних.

---

## Основные концепции

### Как cert-manager обрабатывает отзыв

cert-manager **не реализует** нативный CRL/OCSP-сервер. Его подход к отзыву:

| Механизм | Как работает | Ограничение |
| :--- | :--- | :--- |
| **Удаление Certificate** | Удаляет Secret с сертификатом. Новые подключения не смогут использовать сертификат. | Уже установленные соединения продолжают работать до истечения TLS-сессии |
| **Удаление Secret** | Аналогично удалению Certificate — cert-manager перевыпустит при наличии Issuer | Не влияет на уже установленные соединения |
| **Короткие TTL** | Сертификат автоматически становится недействителен через heures/дни | Не мгновенный отзыв |
| **Внешний CRL/OCSP** | CA (Vault, Step-CA) поддерживает CRL/OCSP независимо от cert-manager | Требует настройки CA и интеграции с клиентами |

### Стратегии отзыва в production

| Стратегия | Время отзыва | Сложность | Когда использовать |
| :--- | :--- | :--- | :--- |
| **Удаление Certificate + Secret** | ~минуты (до перевыпуска) | Низкая | Инцидент-менеджмент, компрометация ключа |
| **Короткие TTL (≤24ч)** | До 24 часов (автоматический) | Низкая | Internal mTLS, API-сервисы |
| **Vault PKI + CRL** | Мгновенно (через CRL) | Средняя | Enterprise, compliance |
| **Step-CA + OCSP** | Мгновенно (через OCSP) | Средняя | Высокие требования к отзыву |
| **Kubernetes Audit Log** | Аудит (не отзыв) | Низкая | Расследование инцидентов |

### Когда НЕ помогает удаление Certificate

```
Клиент establishing TLS → Получает сертификат из Secret → TLS handshake завершен
                                                            ↓
                                            Удаление Secret не разрывает соединение
                                                            ↓
                                            Клиент продолжает использовать сертификат
                                            до истечения TLS-сессии или реконнекта
```

**Вывод:** Для мгновенного отзыва необходим CRL/OCSP на уровне CA, а не cert-manager.

---

## Практические сценарии

### Сценарий 1: Отзыв через удаление (быстрый способ)

```bash
# 1. Определение просроченного/скомпрометированного сертификата
kubectl get certificate -A -o json | jq -r '.items[] | select(.status.conditions[] | select(.type=="Ready" and .status=="False")) | "\(.metadata.namespace)/\(.metadata.name)"'

# 2. Удаление Certificate и Secret
kubectl delete certificate <cert-name> -n <namespace>
kubectl delete secret <secret-name> -n <namespace>

# 3. Применение нового Certificate (если нужен немедленный перевыпуск)
kubectl apply -f new-certificate.yaml

# 4. Верификация
cmctl status certificate <cert-name> -n <namespace>
```

### Сценарий 2: Отзыв с компрометацией ключа (SEV-5)

```bash
# 1. Немедленное удаление скомпрометированного Secret
kubectl delete secret <secret-name> -n <namespace>

# 2. Отзыв через ACME API (если Let's Encrypt)
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64-d > /tmp/leaked.crt
certbot revoke --cert-path /tmp/leaked.crt --reason keycompromise

# 3. Перевыпуск с новым ключом
kubectl apply -f certificate-ecdsa.yaml

# 4. Расследование: как ключ мог быть скомпрометирован
kubectl logs -n cert-manager -l app=cert-manager | grep "<cert-name>"
kubectl auth can-i get secret <secret-name> -n <namespace> --all
```

### Сценарий 3: Настройка CRL через Vault PKI

```bash
# 1. Включение CRL в Vault PKI
vault write pki/config/urls \
  crl_distribution_points="https://vault.internal:8200/v1/pki/crl" \
  ocsp_servers="https://vault.internal:8200/v1/pki/ocsp"

# 2. Отзыв сертификата через Vault
vault write pki/revoke serial_number=<serial_number>

# 3. Генерация обновленного CRL
vault read pki/crl

# 4. Проверка CRL
curl -s https://vault.internal:8200/v1/pki/crl | base64 -d | openssl crl -inform DER -text -noout
```

### Сценарий 4: Настройка OCSP через Step-CA

```bash
# 1. Включение OCSP в Step-CA
step ca provisioner update acme \
  --enable-SSH=false \
  --ocsp-responder-url=http://step-ca.step-ca.svc.cluster.local:9000/1.0/ocsp

# 2. Проверка OCSP-ответа
openssl ocsp -issuer intermediate.pem \
  -cert leaf.pem \
  -url http://step-ca.step-ca.svc.cluster.local:9000/1.0/ocsp \
  -resp_text

# 3. Отзыв сертификата в Step-CA
step ca revoke --cert leaf.pem --key leaf-key.pem
```

### Сценарий 5: Короткоживущие сертификаты (замена CRL)

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: short-lived-api
  namespace: production
spec:
  secretName: short-lived-api-tls
  issuerRef:
    name: vault-issuer
    kind: Issuer
  dnsNames:
  - api.internal.example.com
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  duration: 24h      # 24 часа — сертификат автоматически "отзывается" через сутки
  renewBefore: 6h    # Продление за 6 часов до истечения
  usages:
  - server auth
  - client auth
```

**Преимущество:** Не нужен CRL/OCSP — просроченный сертификат автоматически недействителен.

---

## Дополнительная информация

### Сравнение CRL vs OCSP vs Short-lived

| Критерий | CRL | OCSP | Short-lived |
| :--- | :--- | :--- | :--- |
| **Время отзыва** | До 24 часов | Мгновенно | До TTL (часы-дни) |
| **Нагрузка на сеть** | Низкая (загрузка файла) | Средняя (запрос на каждый сертификат) | Минимальная |
| **Приватность** | Средняя (CRL раскрывает запрашиваемые сертификаты) | Низкая (OCSP-резольвер видит все запросы) | Высокая |
| **Offline support** | Да (кэшированный CRL) | Нет (требует сеть) | Да (сертификат уже проверен) |
| **Сложность** | Низкая | Средняя | Низкая |
| **Рекомендация 2026** | Устаревает | Для публичных сервисов | Для internal mTLS |

### Best practices

1. **Для internal mTLS:** Используйте короткие TTL (≤24ч) вместо CRL/OCSP
2. **Для публичных сертификатов:** Настройте OCSP Stapling на Ingress-контроллере
3. **Для compliance (PCI DSS):** Используйте Vault PKI с CRL для аудита
4. **При компрометации:** Удаляйте Secret немедленно + перевыпускайте через новый Issuer
5. **Мониторинг:** Настройте алерт на `certmanager_certificate_ready_status=False`

### Смотрите также

- **[Cert-manager: Операции](./operations.md)** — мониторинг и резервное копирование.
- **[Cert-manager: Диагностика](./troubleshooting.md)** — troubleshooting инцидентов.
- **[Vault PKI Integration](../Private_CA/vault_integration.md)** — настройка Vault как CA с CRL/OCSP.
- **[Step-CA Integration](../Private_CA/step_ca_integration.md)** — настройка Step-CA с OCSP.
