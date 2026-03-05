# Операции приватного CA

## Определения

**Операции приватного CA** — проверка, отладка и устранение проблем при работе с внутренними центрами сертификации.

> **Навигация:** [Главная Private CA](./index.md) | [Сценарии](./scenarios.md)

---

## Practical Scenarios

### Проверка сертификатов

```bash
# Получить сертификат из Secret
kubectl get secret my-service-tls -n default -o jsonpath='{.data.tls\.crt}' | base64 -d > cert.crt

# Просмотр информации
openssl x509 -in cert.crt -noout -text

# Проверка цепочки доверия
openssl verify -CAfile <(kubectl get secret my-root-ca-secret -n default -o jsonpath='{.data.ca\.crt}' | base64 -d) cert.crt
```

---

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `encoding: PKCS1` по умолчанию | Java не читает ключ | Явно указать `encoding: PKCS8` |
| Certificate в статусе `Pending` | Issuer не найден | Проверить `issuerRef.kind` (Issuer vs ClusterIssuer) |
| Ошибка цепочки доверия | Secret с CA удалён | Не удалять CA-сертификат до перевыпуска всех зависимых |

---

## Additional Information

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Self-signed CA | **10** | Официальная документация cert-manager.io |
| PKCS8 encoding | **10** | Требуется для Java (OpenSearch, Elasticsearch) |
| ClusterIssuer | **10** | Стандартный паттерн cert-manager |

### Связанные темы

- [Administration](../Administration/) — администрирование cert-manager
- [LetsEncrypt](../LetsEncrypt/) — практические сценарии с Let's Encrypt
- [Installation](../install.md) — установка cert-manager
