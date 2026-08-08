# Диагностика и устранение неисправностей cert-manager

## Определения

**Troubleshooting cert-manager** — комплексный процесс выявления и устранения сбоев в жизненном цикле сертификатов, работе Admission Webhooks и интеграции с внешними API центров сертификации (CA).

**cmctl** — основная CLI-утилита для диагностики, заменяющая устаревшие методы ручного осмотра ресурсов. С версии v2.0 полностью поддерживает ARI и Gateway API.

**Resource Archaeology (Археология ресурсов)** — методология отладки путем последовательного анализа иерархии объектов от высокоуровневого `Certificate` до низкоуровневых `Challenge`.

**ARI (ACME Renewal Information)** — механизм, позволяющий CA рекомендовать конкретное время для продления. Ошибки в работе ARI могут приводить к преждевременному или неудачному обновлению.

---

## Основные концепции

### Иерархия диагностики ресурсов

Для эффективного поиска ошибок необходимо двигаться "вниз" по цепочке ресурсов. Ошибка почти всегда транслируется снизу вверх:

1.  **Certificate:** Отражает общее состояние готовности (`Ready`).
2.  **CertificateRequest:** Содержит статус формирования CSR и взаимодействия с Issuer.
3.  **Order (для ACME):** Отражает состояние заказа в API центра сертификации.
4.  **Challenge (для ACME):** Содержит детальную причину сбоя проверки владения доменом (DNS-01/HTTP-01).

### Ключевые компоненты и их индикаторы сбоев

| Компонент | Роль | Признак сбоя |
| :--- | :--- | :--- |
| **cert-manager** | Основная логика | Статус ресурсов не обновляется, ошибки в логах ACME. |
| **webhook** | Валидация API | Ошибки `Internal error occurred: failed calling webhook` при `kubectl apply`. |
| **cainjector** | Доверие в кластере | CRD или Webhook конфигурации не имеют валидных CA-сертификатов. |
| **trust-manager** | Дистрибуция CA | Ресурсы `Bundle` не синхронизируются в ConfigMap целевых namespace. |

---

## Практические сценарии

### Шаг 1: Экспресс-диагностика через cmctl

В 2026 году использование `cmctl` является обязательным стандартом для SRE.

```bash
# 1. Проверка работоспособности API и вебхуков
cmctl check api --wait=2m

# 2. Визуализация всей цепочки ресурсов для проблемного сертификата
cmctl status certificate <name> -n <namespace>

# 3. Инспекция состава секрета (SAN, сроки, алгоритм)
cmctl inspect secret <secret-name> -n <namespace>
```

### Шаг 2: Глубокий анализ ACME и ARI

Если сертификат застрял в процессе обновления или выдает ошибки 400 Malformed:

1.  **Проверка статуса ARI:**
    ```bash
    kubectl get certificate <name> -o jsonpath='{.status.acme.ari}'
    ```
2.  **Принудительное продление (если ARI заблокировал заказ):**
    ```bash
    cmctl renew <name> --force
    ```
3.  **Отладка HTTP-01:** Убедитесь, что временный под `cm-acme-http-solver` доступен извне.
    ```bash
    kubectl get pods -l acme.cert-manager.io/http-domain -A
    ```

### Шаг 3: Частые проблемы и методы их решения (2025–2026)

#### Сценарий: Ошибки Gateway API (ReferenceGrant)

**Симптом:** Gateway не видит сертификат, или cert-manager не создает Certificate для Gateway.
1.  **Проверка ReferenceGrant:** Если Secret в другом namespace, создайте `ReferenceGrant` в namespace секрета.
2.  **ParentRef Fallback:** Если используется только 443 порт, убедитесь в наличии аннотации `acme.cert-manager.io/http01-parentreffallback: "true"`.

#### Сценарий: Ошибки RBAC в версии 1.21+

**Симптом:** Ошибки `permission denied` при работе с Route53 или Vault.
*   **Причина:** Удаление прав на создание ServiceAccount токенов из стандартного чарта.
*   **Решение:** Вручную добавьте права `serviceaccounts/token: create` в ClusterRole контроллера или используйте IRSA (для AWS).

#### Сценарий: Webhook Timeout

**Симптом:** Блокировка любых операций с ресурсами cert-manager.
1.  **Сеть:** Проверьте доступность порта 10250 на подах webhook.
2.  **NetworkPolicy:** Разрешите трафик из namespace `kube-system` (API-сервер) в namespace `cert-manager`.
3.  **Перезагрузка:** `kubectl rollout restart deployment cert-manager-webhook -n cert-manager`.

#### Сценарий: trust-manager Bundle не обновляется

1.  **Namespace Selector:** Убедитесь, что целевые namespace имеют метки, соответствующие `namespaceSelector` в ресурсе `Bundle`.
2.  **Метки по умолчанию:** В новых версиях пустой селектор **не** означает "все namespace".

---

## Дополнительная информация

### Рекомендации по логированию

Для глубокой отладки ACME-взаимодействия повысьте уровень логирования контроллера:
```bash
# Установка уровня 6 для детального вывода JWS-сообщений
kubectl patch deployment cert-manager -n cert-manager --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/args/-", "value": "--v=6"}]'
```

### Смотрите также

- **[Cert-manager: Администрирование](./index.md)** — HA, ресурсы и ротация ключей.
- **[Cert-manager: Операции](./operations.md)** — мониторинг, алертинг и резервное копирование.
- **[Let's Encrypt: Диагностика](../LetsEncrypt/letsencrypt_advanced.md)** — решение специфичных проблем ACME.
