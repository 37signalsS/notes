# Cert-manager: Определения и основные понятия

## Определения

**Cert-manager** — специализированный контроллер для Kubernetes, предназначенный для автоматизации управления жизненным циклом сертификатов X.509 (TLS). Он обеспечивает получение, продление и отзыв сертификатов из различных доверенных источников, минимизируя ручное вмешательство и риск сбоев из-за истечения срока действия.

**Ключевые возможности:**

| Возможность | Описание |
| :--- | :--- |
| **Автоматизация получения** | Интеграция с Let's Encrypt (ACME), HashiCorp Vault, Venafi, локальными CA и внешними провайдерами через Webhook. |
| **Автопродление (ARI)** | Поддержка протокола ACME Renewal Information (ARI) для интеллектуального продления на основе рекомендаций CA. |
| **Интеграция с Ingress** | Автоматическое управление TLS для ресурсов Ingress через аннотации. |
| **Поддержка Gateway API** | Полная совместимость с современным стандартом маршрутизации трафика в Kubernetes. |
| **Управление ключами** | Гибкая ротация приватных ключей (`rotationPolicy: Always`) и поддержка алгоритмов RSA и ECDSA. |

**Архитектура и принципы работы**

Cert-manager реализует классическую архитектуру контроллера Kubernetes на базе `controller-manager`. Система состоит из трех основных компонентов:

1. **cert-manager-controller** — основной компонент, содержащий набор reconciler'ов (контроллеров приведения к желаемому состоянию). Каждый reconciler отслеживает определенный тип ресурса (`Certificate`, `Issuer`, `CertificateRequest`, `Order`, `Challenge`) через механизм Informer и добавляет задачи в собственную очередь (work queue) для последовательной обработки. Reconciler'ы работают асинхронно и идемпотентно: при каждой итерации сравнивают текущее состояние ресурса с желаемым и выполняют минимальный набор действий для устранения расхождений.

2. **cert-manager-webhook** — валидарующий и мутирующий вебхук, внедряемый в путь API-сервера. Выполняет проверку корректности полей ресурсов cert-manager (например, допустимости алгоритмов ключей, сроков действия) при создании и изменении объектов. Отказ webhook'а (`Internal error occurred: failed calling webhook`) блокирует применение манифестов.

3. **cert-manager-cainjector** — наблюдатель за ресурсами кластера, автоматически внедряющий CA-сертификаты в конфигурации, требующие доверия (например, `APIService`, `MutatingWebhookConfiguration`, `ValidatingWebhookConfiguration`). Это обеспечивает корректную работу агрегированных API и Admission Webhooks без ручного управления CA-бандлами.

Дополнительно в состав дистрибутива входят аддоны:
- **trust-manager** — распределение корневых и промежуточных CA-сертификатов между Namespaces через ресурс `ClusterBundle`.
- **cert-manager-csi-driver** — интерфейс CSI для подачи сертификатов в поды без сохранения приватных ключей в etcd.

Принцип работы конвейера:
- При создании ресурса `Certificate` соответствующий reconciler генерирует объект `CertificateRequest` с CSR (Certificate Signing Request), подписанным временным приватным ключом.
- Для ACME-провайдеров создается цепочка `Order` → `Challenge`(s), где Challenge содержит конкретную задачу проверки владения доменом (HTTP-01, DNS-01 или TLS-ALPN-01).
- После успешной проверки CA возвращает подписанный сертификат, который сохраняется в Kubernetes Secret с именами `tls.crt` и `tls.key`.
- Фоновый процесс мониторинга отслеживает срок действия и инициирует продление за `renewBefore` (или по рекомендации ARI), повторяя конвейер.

**Связанные темы:**

- **[Установка и настройка](./installation.md)** — методы развертывания и базовая конфигурация.
- **[Let's Encrypt и ACME](./LetsEncrypt/index.md)** — работа с публичными удостоверяющими центрами.
- **[Интеграция с Ingress](./ingress/overview.md)** — использование cert-manager с Ingress-контроллерами.
- **[Gateway API и TLS](./gateway_api/definitions_and_concepts.md)** — настройка сертификатов для ресурсов Gateway.
- **[Приватный CA (Private PKI)](./Private_CA/index.md)** — управление внутренними иерархиями доверия.
- **[Администрирование и диагностика](./Administration/troubleshooting.md)** — отладка и эксплуатация системы.
- **[Операции: мониторинг и бэкап](./Administration/operations.md)** — эксплуатация в Production.
- **[Предотвращение истечения SSL-сертификатов](../Operations/ssl_expiration_prevention.md)** — стратегия ротации на всех эшелонах кластера.

---

## Основные концепции

### Пользовательские ресурсы (CRD)

Cert-manager расширяет API Kubernetes через Custom Resource Definitions, которые позволяют декларативно описывать требования к сертификатам.

#### Источники сертификатов (Issuers)

- **`Issuer`**: Ресурс, привязанный к конкретному пространству имен (Namespace). Выпускает сертификаты только для объектов в том же Namespace.
- **`ClusterIssuer`**: Глобальный ресурс кластера. Позволяет выпускать сертификаты для любого Namespace, что удобно для общих центров сертификации (например, Let's Encrypt Production).

#### Ресурс Certificate

**`Certificate`** — это высокоуровневый ресурс, представляющий желаемое состояние TLS-сертификата.
- На основе этого ресурса cert-manager создает и поддерживает в актуальном состоянии Kubernetes Secret с полями `tls.crt` и `tls.key`.
- Контроллер автоматически отслеживает срок действия и инициирует процесс продления.

#### Внутренние ресурсы процесса выпуска

Эти ресурсы обычно управляются контроллером автоматически, но важны для диагностики:

- **`CertificateRequest`**: Содержит закодированный запрос на подпись (CSR). Это связующее звено между ресурсом `Certificate` и `Issuer`.
- **`Order`**: (Только для ACME) Представляет процесс заказа сертификата у ACME-сервера.
- **`Challenge`**: (Только для ACME) Конкретная задача по проверке владения доменом (HTTP-01 или DNS-01), создаваемая в рамках `Order`.

#### Reconciler-конвейер и наблюдатели (Informers)

Внутренняя обработка cert-manager построена на наборе независимых reconciler'ов, каждый из которых использует Informer для наблюдения за определенным ресурсом:

- **CertificateReconciler**: Следит за ресурсами `Certificate`. При создании или изменении объекта генерирует `CertificateRequest` и отслеживает его статус.
- **IssuerReconciler**: Валидирует доступность и готовность `Issuer`/`ClusterIssuer`. Проверяет наличие учетных данных (ключей, токенов) в referenced Secrets.
- **OrderReconciler**: Управляет жизненным циклом `Order` для ACME-провайдеров, синхронизируя статус заказа с внешним CA API.
- **ChallengeReconciler**: Создает и контролирует выполнение задач проверки владения доменом. Для HTTP-01 запускает временные поды в кластере; для DNS-01 модифицирует DNS-записи через API провайдера.
- **CertificateRequestReconciler**: Устанавливает связь между `CertificateRequest` и `Issuer`, передавая CSR и получая подписанный сертификат.

Все reconciler'ы используют единый паттерн:
1. Получение события из Informer (add/update/delete).
2. Добавление ключа ресурса в work queue.
3. Обработка элемента очереди с повторными попытками (exponential backoff).
4. Обновление статуса ресурса и запись событий (Events) для последующего отладки.

### Дополнительные компоненты экосистемы

#### trust-manager

Аддон для cert-manager, решающий проблему дистрибуции доверия.
- **Назначение**: Автоматическое распространение (дистрибуция) CA-бандлов или корневых сертификатов во все пространства имен кластера.
- **Механизм**: Использует ресурс `ClusterBundle` для создания ConfigMap с сертификатами в целевых Namespaces, что позволяет подам автоматически доверять внутренним или корпоративным CA.

#### cert-manager-csi-driver

CSI-драйвер, позволяющий монтировать сертификаты напрямую в файловую систему пода.
- **Преимущество**: Секреты (приватные ключи) не сохраняются в базе данных etcd как Kubernetes Secrets, а генерируются "на лету" и существуют только в памяти узла, где запущен под.
- **Сценарий**: Высокие требования к безопасности и предотвращение утечки ключей при компрометации etcd.

---

## Протокол ACME и ARI

### Жизненный цикл выпуска

Логическая цепочка создания сертификата через ACME:
`Certificate` → `Order` → `Challenge(s)` → `CertificateRequest` → `Secret`

Для не-ACME провайдеров (например, Vault или self-signed CA) конвейер сокращается:
`Certificate` → `CertificateRequest` → `Secret`

### ACME Renewal Information (ARI)

В 2026 году использование ARI является стандартом де-факто для работы с публичными CA (например, Let's Encrypt).
- **Суть**: Вместо жестко заданного параметра `renewBefore` (например, за 30 дней до конца), cert-manager опрашивает ACME-сервер на предмет "окна продления".
- **Зачем это нужно**: Позволяет CA плавно распределять нагрузку на свою инфраструктуру или форсировать продление всех сертификатов в случае обнаружения уязвимости или массового отзыва ключей.

### Дополнительные концепции ACME

- **Authorization**: ACME-объект, описывающий права на управление конкретным доменом. Содержит статус (`valid`, `invalid`, `deactivated`) и список разрешенных методов проверки.
- **Account**: Учетная запись cert-manager на стороне ACME-сервера, связанная с ключом аккаунта (account key). Привязка через External Account Binding (EAB) используется для коммерческих CA.
- **JWS (JSON Web Signature)**: Формат подписи запросов к ACME API. cert-manager автоматически формирует JWS-пэйлоады для `Order`, `Challenge` и `CertificateRequest`.

---

## Структура ресурса Certificate

Манифест `Certificate` определяет технические параметры выпуска:

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: web-app-tls
  namespace: production
spec:
  # Название Secret для хранения ключей
  secretName: web-app-tls-secret

  # Жизненный цикл
  duration: 2160h          # 90 дней
  renewBefore: 360h        # Продлить за 15 дней (игнорируется при наличии ARI)

  # Параметры субъекта
  dnsNames:
    - app.example.com
  
  # Ссылка на Issuer
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
    group: cert-manager.io

  # Параметры приватного ключа (Стандарты 2026)
  privateKey:
    algorithm: ECDSA       # Рекомендуется: быстрее и безопаснее RSA
    size: 256
    rotationPolicy: Always # Ротация ключа при каждом обновлении (Best Practice)
    encoding: PKCS8        # Совместимость с современными фреймворками
```

---

## Методы проверки (Solvers)

| Метод | Описание | Поддержка Wildcard | Требования |
| :--- | :--- | :--- | :--- |
| **HTTP-01** | Размещение файла в `.well-known/acme-challenge/` | Нет | Доступ к кластеру по 80 порту из интернета. |
| **DNS-01** | Создание временной TXT-записи в DNS | **Да** | Интеграция с API DNS-провайдера (Cloudflare, AWS Route53 и др.). |
| **TLS-ALPN-01** | Проверка через TLS-рукопожатие на 443 порту | Нет | Прямой L4-доступ к Ingress-контроллеру. |

---

## Версии и совместимость

| Версия cert-manager | Мин. версия Kubernetes | Статус (на июль 2026) |
| :--- | :--- | :--- |
| **1.21.x** | 1.25 | **Текущая (Stable)** |
| 1.20.x | 1.25 | Поддерживается |
| 1.19.x | 1.24 | Ограниченная поддержка (EOL) |
| <1.18 | <1.24 | Устарели (End of Life) |

---

## Практические сценарии для DevOps/SRE/SysAdmin

### Быстрая диагностика через cmctl

В 2026 году использование `cmctl` является обязательным стандартом для SRE. Утилита позволяет визуализировать цепочку ресурсов и проверять статус API без ручного осмотра множества объектов.

```bash
# 1. Проверка работоспособности API и вебхуков
cmctl check api --wait=2m

# 2. Визуализация всей цепочки ресурсов для проблемного сертификата
cmctl status certificate <name> -n <namespace>

# 3. Инспекция состава секрета (SAN, сроки, алгоритм)
cmctl inspect secret <secret-name> -n <namespace>
```

Ожидаемый результат успешной проверки:
- `cmctl check api` выводит `All checks passed`.
- `cmctl status certificate` показывает цепочку `Certificate → CertificateRequest → Order → Challenge → Secret` с зелеными статусами.
- `cmctl inspect secret` отображает детали сертификата: Subject Alternative Names, Not Before/After, Signature Algorithm.

Для полного troubleshooting см. **[Администрирование и диагностика](./Administration/troubleshooting.md)**.

### Проверка статуса цепочки ACME

При проблемах с выпуском или продлением сертификата последовательность диагностики:

```bash
# 1. Статус Certificate
kubectl get certificate <name> -n <namespace>

# 2. Детали CertificateRequest (признак проблем с CSR)
kubectl describe certificaterequest <name> -n <namespace>

# 3. Для ACME: статус Order
kubectl get order -n <namespace>

# 4. Для ACME: статус Challenge
kubectl get challenge -n <namespace>

# 5. Проверка ARI (ACME Renewal Information)
kubectl get certificate <name> -o jsonpath='{.status.acme.ari}'
```

### Очистка старых ресурсов

cert-manager не удаляет `CertificateRequest`, `Order` и `Challenge` при успешном выпуске сертификата. В больших кластерах это приводит к накоплению "мертвых" объектов. Рекомендуется периодическая очистка:

```bash
# Просмотр устаревших CertificateRequest (старше 30 дней)
kubectl get certificaterequest -A --field-selector status.conditions[?(@.type=="Ready")].status="True"

# Принудительное удаление старых ресурсов (если Certificate удален)
kubectl delete certificaterequest,order,challenge -l app=cert-manager --all-namespaces
```

### Мониторинг и алертинг

Для Production сред критично отслеживать:
- Количество сертификатов, приближающихся к истечению срока.
- Ошибки вебхука (`Failed calling webhook`).
- Доступность Issuer (статус `Ready`).

Пример PrometheusRule для Alertmanager:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: cert-manager-rules
  namespace: cert-manager
spec:
  groups:
  - name: cert-manager
    rules:
    - alert: cert-managerCertExpiringSoon
      expr: |
        (time() - certmanager_certificate_expiration_timestamp_seconds) < 604800
      for: 1h
      labels:
        severity: warning
      annotations:
        summary: "Certificate {{ $labels.name }} expires in less than 7 days"
    - alert: cert-managerWebhookErrors
      expr: rate(certmanager_webhook_errors_total[5m]) > 0
      for: 5m
      labels:
        severity: critical
      annotations:
        summary: "cert-manager webhook errors detected"
```

Подробнее о мониторинге см. **[Администрирование: Операции](./Administration/operations.md)**.

### Работа в air-gapped средах

В полностью изолированных средах cert-manager не может достучаться до публичных ACME-серверов. Рекомендуемые подходы:
- **Внутренний ACME-сервер**: Pebble (тестирование) или Step CA / Smallstep (Production).
- **Локальный Vault**: Использование HashiCorp Vault как промежуточного CA с интеграцией через вебхук.
- **Self-signed / Intermediate CA**: Выпуск сертификатов через `ca`-issuer с предварительно размещенным корневым сертификатом в trust-manager.

### Резервное копирование и восстановление

Для восстановления кластера после сбоя критично сохранить:
- Secrets с приватными ключами CA (например, `letsencrypt-prod-account-key`).
- Ресурсы `Issuer` и `ClusterIssuer` (всегда в YAML/Helm-чартах).
- trust-manager `ClusterBundle` ресурсы.

Бэкап Secrets:
```bash
kubectl get secret -n cert-manager -l app=cert-manager -o yaml > cert-manager-secrets-backup.yaml
kubectl get secret -A -l cert-manager.io/ca-from-secret -o yaml > ca-secrets-backup.yaml
```

Подробнее о стратегиях бэкапа см. **[Стратегии резервного копирования](../../Operations/backup-strategies.md)**.

---

## Операционная информация

### Rate limits и квоты Let's Encrypt

Публичные CA накладывают ограничения на количество запросов. Для Let's Encrypt (Staging) лимиты существенно выше, чем для Production. cert-manager минимизирует количество запросов через ARI и кэширование промежуточных состояний.

Рекомендации:
- Используйте Staging-окружение для разработки и тестирования.
- Для wildcard-сертификатов применяйте DNS-01 метод (HTTP-01 не поддерживает wildcard).
- Мониторьте заголовки ответов ACME (`Retry-After`, `RateLimit-*`) в событиях `Challenge`.

### Масштабирование компонентов

Для отказоустойчивых кластеров (HA):
- **cert-manager-controller**: Минимум 2 реплики (`--set controller.replicaCount=2`).
- **cert-manager-webhook**: Минимум 2 реплики с `failurePolicy: Fail` для предотвращения выпуска некорректных сертификатов при простое вебхука.
- **cert-manager-cainjector**: 1 реплика достаточна для большинства сред; 2+ реплики требуются при высокой нагрузке на API-сервер.

### Зависимости от внешних систем

cert-manager должен иметь сетевой доступ к:
- API-серверу Kubernetes (`6443/tcp`) — всегда.
- ACME-серверу (`443/tcp`) — для публичных CA.
- API DNS-провайдера (`443/tcp`) — для DNS-01.
- Хранилищу секретов (Vault, AWS Secrets Manager и др.) — при соответствующем конфигурации.

В air-gapped средах доступ ограничивается внутренними сервисами; см. раздел "Практические сценарии".

---

## Ограничения и известные проблемы

### Ограничения архитектуры

- **Зависимость от etcd**: Приватные ключи сертификатов по умолчанию хранятся в Kubernetes Secrets, которые записываются в etcd. При компрометации etcd ключи становятся доступными злоумышленнику. Используйте `cert-manager-csi-driver` или внешние vault'ы для критичных workloads.
- **Один Issuer на Secret**: Один Secret с учетными данными CA может использоваться только одним `Issuer`/`ClusterIssuer`. Повторное использование требует создания отдельных ресурсов.
- **Гонка при удалении Certificate**: При удалении ресурса `Certificate` связанные `CertificateRequest`, `Order`, `Challenge` и `Secret` удаляются каскадно. Однако сам `Issuer`/`ClusterIssuer` и Secrets с ключами аккаунтов CA остаются в кластере.
- **Gateway API и ReferenceGrant**: Для сертификатов, хранящихся в другом namespace, требуется явный `ReferenceGrant`. Без него Gateway не увидит Secret и не сможет использовать сертификат.

### Известные проблемы (2026)

- **Версия 1.19.x и EOL**: Поддержка завершена. Не получает исправлений безопасности. Обязателен апгрейд на 1.21.x.
- **Ротация ключей и DNS-01**: При использовании `rotationPolicy: Always` cert-manager генерирует новый ключ при каждом обновлении сертификата. Для DNS-01 это означает повторное создание TXT-записей, что может вызывать всплеск запросов к API DNS-провайдера.
- **Совместимость с Ingress-контроллерами**: Некоторые контроллеры (устаревшие версии NGINX Ingress < 1.10) не поддерживают динамическое обновление TLS-секретов без перезапуска. Требуется проверка конфигурации Ingress-контроллера.

---

## Best practices и безопасность

### Рекомендации для Production

1. **Используйте ClusterIssuer для общих CA**: Это централизует управление учетными данными и снижает риск утечки ключей из-за множества Issuer'ов в разных Namespaces.
2. **Предпочитайте ECDSA/Ed25519**: Алгоритм `ECDSA-P256` обеспечивает более высокую производительность и эквивалентную безопасность по сравнению с RSA-2048. `Ed25519` поддерживается начиная с cert-manager v1.21.
3. **Обязательно включите ARI**: Параметр `useClassicDNSChallenge: false` (по умолчанию в v1.21+) активирует ARI для ACME-провайдеров, поддерживающих протокол.
4. **Ротация ключей**: Установите `rotationPolicy: Always` для прикладных сертификатов. Для CA-ключей используйте `cert-manager` вместе с `trust-manager` для автоматического распространения новых корневых сертификатов.
5. **Изоляция Namespaces**: Храните `ClusterIssuer` в выделенном namespace (например, `cert-manager` или `security`). Ограничьте доступ к нему через RBAC.
6. **Сетевые политики**: Разрешите исходящий доступ только из подов cert-manager к ACME-серверам и API DNS-провайдеров. Запретите все другие исходящие соединения.
7. **Бэкап CA-ключей**: Храните резервные копии Secrets с приватными ключами промежуточных CA в защищенном хранилище (Vault, AWS Secrets Manager) вне кластера.
8. **Мониторинг сроков действия**: Настройте алерты за 7 и 30 дней до истечения. Дополнительно мониторьте ошибки вебхука и недоступность Issuer.
9. **Валидация CT-логов**: Для критичных доменов проверяйте наличие сертификатов в Certificate Transparency логах (CT Log). cert-manager автоматически включает CT поддержку для Let's Encrypt.
10. **Обновление версий**: Следуйте политике поддержки Jetstack. Версии < 1.19.x не получают исправлений безопасности.

### Безопасность

- **Приватные ключи в etcd**: По умолчанию Kubernetes Secrets шифруются только при наличии EncryptionConfiguration. Для дополнительной защиты используйте CSI-драйвер cert-manager, который генерирует ключи в памяти узла.
- **Webhook TLS**: cert-manager-webhook использует автоматически ротируемые сертификаты. Не отключайте валидацию webhook (`--set webhook.enabled=false`) в Production.
- **RBAC**: Сервисный аккаунт `cert-manager` должен иметь минимально необходимые права. Избегайте использования привилегированных аккаунтов (cluster-admin) для подов cert-manager без необходимости.
- **Доверие (Trust)**: Не добавляйте публичные CA (например, DST Root CA X3) в trust-manager `ClusterBundle` для внутренних сервисов. Это расширяет поверхность атаки.

---

## См. также

- **[Установка cert-manager](./installation.md)**
- **[Let's Encrypt и ACME](./LetsEncrypt/index.md)**
- **[Интеграция с Ingress](./ingress/overview.md)**
- **[Gateway API и TLS](./gateway_api/definitions_and_concepts.md)**
- **[Приватный CA (Private PKI)](./Private_CA/index.md)**
- **[Администрирование и диагностика](./Administration/troubleshooting.md)**
