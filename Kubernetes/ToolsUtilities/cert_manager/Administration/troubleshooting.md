# Диагностика и troubleshooting cert-manager

## Определения

**Troubleshooting cert-manager** — комплексный процесс выявления, анализа и устранения сбоев в работе контроллера, механизмов валидации (webhook) и процессов выпуска или продления сертификатов.

## Основные концепции

### Компоненты и их роль в диагностике

cert-manager состоит из трёх ключевых подов, каждый из которых отвечает за свой участок:
1.  **cert-manager (controller):** Основная логика. Отвечает за мониторинг ресурсов `Certificate`, создание `CertificateRequest` и взаимодействие с Issuer (например, Let's Encrypt через ACME или Vault).
2.  **cert-manager-webhook:** Валидирует корректность манифестов при их создании/изменении и выполняет мутации. Если webhook не работает, вы не сможете создать или обновить ресурсы cert-manager.
3.  **cert-manager-cainjector:** Обеспечивает доверие внутри кластера, подставляя (инжектируя) CA-сертификаты в `MutatingWebhookConfiguration`, `ValidatingWebhookConfiguration` и `CustomResourceDefinition`.

### Жизненный цикл ACME-выпуска

Для эффективной диагностики важно понимать цепочку создания ресурсов:
`Certificate` → `CertificateRequest` → `Order` → `Challenge` → `Secret`.

Сбой на любом из этих этапов блокирует всю цепочку. Статус каждого ресурса (особенно `Challenge`) содержит детальную информацию об ошибке в поле `status.conditions` или `status.reason`.

## Практические сценарии

### Шаг 1: Проверка состояния ресурсов

Диагностику всегда следует начинать с верхнего уровня — ресурса `Certificate`.

```bash
# Посмотреть статус всех сертификатов в кластере
kubectl get certificates --all-namespaces

# Детальный анализ конкретного сертификата (смотрим раздел Events и Conditions)
kubectl describe certificate <name> -n <namespace>
```

Если сертификат не готов (`Ready: False`), спускаемся ниже по цепочке:

```bash
# Проверка запросов на выпуск (CertificateRequest)
kubectl get certificaterequest -n <namespace>
kubectl describe certificaterequest <name-of-request> -n <namespace>

# Проверка заказов ACME (Order)
kubectl get orders -n <namespace>
kubectl describe order <name-of-order> -n <namespace>

# Самый детальный уровень — проверка проверок (Challenge)
kubectl get challenges -n <namespace>
kubectl describe challenge <name-of-challenge> -n <namespace>
```

### Шаг 2: Анализ логов компонентов

Если ресурсы в порядке, но сертификат не выпускается, или если возникают системные ошибки, проверяем логи контроллеров.

```bash
# Логи основного контроллера (фильтруем по ошибкам и ACME-событиям)
kubectl logs -n cert-manager -l app=cert-manager --tail=200 | grep -iE "error|fail|acme"

# Проверка webhook (часто возникают таймауты или ошибки сертификата самого webhook)
kubectl logs -n cert-manager -l app=webhook --tail=100

# Проверка cainjector (если есть проблемы с RBAC или инжекцией сертификатов)
kubectl logs -n cert-manager -l app=cainjector --tail=100
```

### Шаг 3: Частые проблемы и способы решения

#### Сценарий: Certificate в статусе Pending (ACME-проверка)

Это самая частая проблема. Причина обычно кроется в невозможности CA подтвердить владение доменом.

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **HTTP-01 недоступен** | `curl -v http://<domain>/.well-known/acme-challenge/<token>` | Проверить Ingress, Firewall (порт 80 должен быть открыт), настройки Service/Endpoints для `cm-acme-http-solver`. |
| **DNS-01 не прошёл** | `dig TXT _acme-challenge.<domain>` | Проверить права доступа к API DNS-провайдера (Secret), время TTL и распространение записей. |
| **Rate limit (Let's Encrypt)** | Проверить `kubectl describe order` на наличие сообщения об ограничении. | Использовать Let's Encrypt Staging для тестов. Подождать сброса лимита (обычно от 1 часа до 7 дней). |
| **Неверный Issuer** | `kubectl get issuer,clusterissuer` | Убедиться, что `issuerRef` в Certificate указывает на существующий и готовый (Ready: True) ресурс. |

#### Сценарий: Webhook timeout или ошибки валидации

Если при попытке применить манифест вы получаете ошибку `Internal error occurred: failed calling webhook...`:

1.  **Проверка сети:** Убедитесь, что API-сервер может "достучаться" до пода webhook на порту 10250 или через сервис на 443.
2.  **Проверка NetworkPolicies:** Если в кластере используется NetworkPolicy, разрешите трафик из namespace `kube-system` (где обычно живет API-сервер) в namespace `cert-manager`.
3.  **Перезагрузка:** Часто помогает простой рестарт:
    ```bash
    kubectl rollout restart deployment cert-manager-webhook -n cert-manager
    ```

#### Сценарий: Секрет (Secret) не создаётся или содержит старые данные

1.  **Проверка прав (RBAC):** Убедитесь, что у cert-manager есть права на создание секретов в целевом namespace.
    ```bash
    kubectl auth can-i create secrets -n <namespace> --as system:serviceaccount:cert-manager:cert-manager
    ```
2.  **Конфликт OwnerReference:** Если включен Garbage Collection, проверьте, не удаляет ли какой-то другой контроллер (например, ArgoCD с включенным prune) ваш Secret.
3.  **Ручная проверка данных:**
    ```bash
    # Извлечение и проверка срока действия из существующего Secret
    kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates
    ```

#### Сценарий: Ошибка цепочки доверия (Trust Chain)

Приложение выдаёт ошибку `X509: Certificate Signed by Unknown Authority`.

1.  **Проверка CA:** Убедитесь, что в секрете присутствует `ca.crt` (если используется внутренний CA).
2.  **Валидация через openssl:**
    ```bash
    # Сохраняем сертификат и CA для проверки
    kubectl get secret <name> -o jsonpath='{.data.tls\.crt}' | base64 -d > cert.crt
    kubectl get secret <name> -o jsonpath='{.data.ca\.crt}' | base64 -d > ca.crt
    # Проверяем цепочку
    openssl verify -CAfile ca.crt cert.crt
    ```
3.  **Решение:** Если вы используете self-signed или внутренний CA, убедитесь, что корневой сертификат добавлен в доверенное хранилище (Trust Store) вашего приложения или ОС. Используйте **trust-manager** для автоматизации этого процесса.

## Дополнительная информация

### Рекомендации по отладке

- Всегда используйте Let's Encrypt **Staging** окружение для отладки новых конфигураций, чтобы не попасть под жесткие лимиты (Rate Limits) продакшена.
- Если сертификат "завис" в процессе обновления, иногда помогает удаление ресурсов `CertificateRequest`, `Order` и `Challenge` — контроллер создаст их заново.

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Проверка ресурсов | **10** | Фундаментальные механизмы Kubernetes и cert-manager. |
| Логи компонентов | **10** | Стандартный подход к диагностике в K8s. |
| Типовые проблемы | **10** | Основано на многолетнем опыте эксплуатации и официальном troubleshooting guide. |
| Команды OpenSSL | **10** | Стандарт индустрии для работы с сертификатами. |

### Смотрите также

- **[Cert-manager: Администрирование](./index.md)** — управление жизненным циклом и конфигурация.
- **[Cert-manager: Операции](./operations.md)** — мониторинг, алертинг и резервное копирование.
- **[Cert-manager: Установка](../installation.md)** — параметры Helm и развертывание.
