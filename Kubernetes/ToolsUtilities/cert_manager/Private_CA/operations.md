# Операции приватного CA

## Определения

**Операции приватного CA** — комплекс мер по проверке, отладке и обеспечению жизненного цикла внутренних центров сертификации. В отличие от общей диагностики cert-manager ([Administration/troubleshooting.md](../Administration/troubleshooting.md)), данные операции фокусируются на специфике Private CA: управлении цепочкой доверия, ротации корневых сертификатов, валидации форматов ключей (PKCS8) и дистрибуции публичных CA-бандлов.

---

## Основные концепции

### Жизненный цикл приватного CA

Приватный CA требует более активного управления по сравнению с публичными (ACME), так как вся ответственность за доверие лежит на администраторе:

1.  **Первичная настройка** — создание самоподписанного Issuer → выпуск сертификата CA → создание CA Issuer.
2.  **Ротация доверия** — выпуск нового корневого CA до истечения старого.
3.  **Дистрибуция (Trust Distribution)** — автоматическая доставка публичного ключа CA во все приложения кластера (рекомендуется через **trust-manager**).
4.  **Ротация ключей** — принудительное обновление закрытых ключей через `rotationPolicy`.

### Критичность ротации и сроки

Истечение срока действия CA приводит к немедленной невалидности **всех** подписанных им сертификатов.

**Рекомендуемые параметры:**
- **Корневой CA (Root CA):** 2–5 лет.
- **Промежуточный CA (Intermediate):** 1–2 года.
- **Сертификаты сервисов:** 90 дней — 1 год.
- **Окно продления (`renewBefore`):** 30 дней для сервисов, 90 дней для CA.

---

## Практические сценарии

### Использование cmctl для диагностики

Утилита `cmctl` (ранее `kubectl cert-manager`) — основной инструмент оператора для работы с сертификатами.

```bash
# Проверка статуса и связанных ресурсов (Secret, Request)
cmctl status certificate my-service-tls -n default

# Просмотр деталей X.509 без извлечения Secret
cmctl inspect secret my-service-tls -n default

# Ручное принудительное обновление сертификата (до renewBefore)
cmctl renew my-service-tls -n default

# Проверка готовности API cert-manager
cmctl check api
```

### Низкоуровневая проверка через openssl

Используется, если нужно подтвердить соответствие ключа и сертификата или проверить цепочку вручную.

```bash
# Извлечение и проверка срока действия
kubectl get secret my-service-tls -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates

# Проверка цепочки доверия (валидация сертификата через файл CA)
openssl verify -CAfile <(kubectl get secret my-root-ca -o jsonpath='{.data.ca\.crt}' | base64 -d) \
  <(kubectl get secret my-service-tls -o jsonpath='{.data.tls\.crt}' | base64 -d)

# Проверка формата PKCS8 (критично для Java/Spring приложений)
openssl pkey -in <(kubectl get secret my-service-tls -o jsonpath='{.data.tls\.key}' | base64 -d) -noout -text
```

### Дистрибуция доверия через trust-manager

Вместо ручного копирования CA в каждый Namespace или использования `keytool`, используйте аддон **trust-manager**.

```yaml
apiVersion: trust.cert-manager.io/v1alpha1
kind: Bundle
metadata:
  name: my-org-trust
spec:
  sources:
  - useDefaultCAs: true  # Включить системные сертификаты
  - secret:
      name: my-root-ca-secret
      key: ca.crt
  target:
    configMap:
      key: trust-bundle.pem  # Итоговый файл в каждом Namespace
```

### Ротация корневого CA (Zero Downtime)

1.  **Выпуск нового CA:** Создать новый `Certificate` (v2) и дождаться `Ready`.
2.  **Объединение (Bundle):** Добавить оба CA (старый и новый) в `trust-manager` Bundle, чтобы приложения доверяли обеим версиям.
3.  **Переключение Issuer:** Обновить `Issuer/ClusterIssuer`, чтобы он указывал на Secret нового CA.
4.  **Массовое обновление:** Выполнить `cmctl renew --all`, чтобы перевыпустить сертификаты сервисов новым ключом.
5.  **Очистка:** После обновления всех сервисов удалить старый CA из Bundle и кластера.

---

## Дополнительная информация

### Частые ошибки и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `Unknown Authority` | Приложение не знает о CA | Проверить наличие CA в trust-bundle или ConfigMap |
| `Legacy PKCS1` | Java не читает закрытый ключ | Указать `privateKey.encoding: PKCS8` в спецификации Certificate |
| Сертификат не обновляется | `Issuer` в статусе False | Проверить `kubectl describe issuer`, возможно истек CA самого Issuer |
| Цепочка неполная | Secret содержит только TLS, без CA | Убедиться, что в `Certificate` не используется `keystore` без экспорта CA |

### Смотрите также

- **[Приватный CA: Обзор](./index.md)** — архитектура и выбор типа Issuer
- **[Приватный CA: Сценарии](./scenarios.md)** — примеры манифестов для различных систем
- **[Cert-manager: Troubleshooting](../Administration/troubleshooting.md)** — общая диагностика компонентов
