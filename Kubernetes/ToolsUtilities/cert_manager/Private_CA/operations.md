# Операции приватного CA

## Definitions

**Операции приватного CA** — проверка, отладка и устранение проблем при работе с внутренними центрами сертификации. Отличается от общего troubleshooting cert-manager ([Administration/troubleshooting.md](../Administration/troubleshooting.md)) фокусом на специфичные для приватного CA операции: проверка цепочки доверия, ротация корневого CA, валидация PKCS8.

---

## Basic Concepts

### Жизненный цикл приватного CA

Приватный CA требует дополнительных операций по сравнению с внешними CA (Let's Encrypt):

1. **Первичная настройка** — создание self-signed Issuer → CA Certificate → CA Issuer
2. **Регулярная ротация** — перевыпуск корневого CA до истечения срока (обычно 2–5 лет)
3. **Перевыпуск зависимых** — все сертификаты, подписанные старым CA, требуют обновления
4. **Распространение CA.crt** — добавление корневого сертификата в trust store каждого приложения

### Критичность ротации CA

В отличие от Let's Encrypt (автоматическое продление), приватный CA требует ручного планирования ротации. При истечении срока действия CA все зависимые сертификаты становятся невалидными одновременно.

**Рекомендуемые сроки:**

- Корневой CA: 2–5 лет
- Сертификаты сервисов: 1 год
- Окно продления (`renewBefore`): 30 дней для сервисов, 90 дней для CA

---

## Practical Scenarios

### Проверка сертификатов

```bash
# Получить сертификат из Secret
kubectl get secret my-service-tls -n default -o jsonpath='{.data.tls\.crt}' | base64 -d > cert.crt

# Просмотр информации (срок действия, CN, SAN)
openssl x509 -in cert.crt -noout -text

# Проверка цепочки доверия
openssl verify -CAfile <(kubectl get secret my-root-ca-secret -n default -o jsonpath='{.data.ca\.crt}' | base64 -d) cert.crt

# Проверка кодировки ключа (PKCS8)
openssl pkey -in <(kubectl get secret my-service-tls -n default -o jsonpath='{.data.tls\.key}' | base64 -d) -noout -text
```

---

### Ротация корневого CA

**Шаг 1: Создание нового CA-сертификата**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-root-ca-v2
  namespace: default
spec:
  isCA: true
  commonName: "my-root-ca-v2"
  secretName: my-root-ca-secret-v2
  duration: 17520h  # 2 года
  renewBefore: 2160h  # 90 дней
  privateKey:
    algorithm: ECDSA
    size: 256
    encoding: PKCS8
  issuerRef:
    name: selfsigned-ca-issuer
    kind: Issuer
    group: cert-manager.io
```

**Шаг 2: Создание нового CA Issuer**

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: my-ca-issuer-v2
  namespace: default
spec:
  ca:
    secretName: my-root-ca-secret-v2
```

**Шаг 3: Обновление сертификатов сервисов**

Перевыпустить все сертификаты сервисов, указав новый `issuerRef`:

```yaml
spec:
  issuerRef:
    name: my-ca-issuer-v2  # обновлённый Issuer
    kind: Issuer
```

**Шаг 4: Распространение нового CA.crt**

Обновить trust store в приложениях. Для Java:

```bash
keytool -import -alias my-root-ca-v2 -file ca-v2.crt -keystore $JAVA_HOME/lib/security/cacerts
```

**Шаг 5: Удаление старого CA**

После подтверждения работы всех сервисов с новым CA:

```bash
kubectl delete certificate my-root-ca -n default
kubectl delete issuer my-ca-issuer -n default
```

---

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `encoding: PKCS1` по умолчанию | Java не читает ключ | Явно указать `encoding: PKCS8` в Certificate |
| Ошибка цепочки доверия | Secret с CA удалён или CA истёк | Не удалять CA-сертификат до перевыпуска всех зависимых |
| Сервис не принимает новый CA | Trust store не обновлён | Импортировать CA.crt в приложение |
| cert-manager не продлевает CA | `renewBefore` слишком мал или Issuer недоступен | Проверить `kubectl describe certificate` |

Общий troubleshooting cert-manager (Pending-статусы, webhook timeout, RBAC) — в [Administration/troubleshooting.md](../Administration/troubleshooting.md).

---

## Additional Information

Данные о надёжности информации — в [index.md](./index.md).
