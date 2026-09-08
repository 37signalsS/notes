# Cert-manager: Интеграция с Ingress

## Предварительные требования (Prerequisites)

Для работы интеграции cert-manager с Ingress необходимо выполнить несколько условий. Отсутствие любого из компонентов приведет к тому, что аннотации будут проигнорированы, а сертификаты не будут выпущены.

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Kubernetes** | 1.25+ | Поддержка `networking.k8s.io/v1` для Ingress и современных CRD. |
| **cert-manager** | 1.21.0+ | Поддержка ARI, Ed25519 и стандартов 2026 года. |
| **Ingress-контроллер** | NGINX 1.10+, Traefik 3.0+, HAProxy 0.13+, или аналог | Без контроллера объект `Ingress` не функционирует. |
| **DNS-запись** | A или CNAME | Должна указывать на внешний IP Ingress-контроллера. |
| **Доступ к порту 80** | HTTP-01 | Требуется для прохождения ACME-проверки Let's Encrypt. |
| **cmctl** | 1.21+ | CLI-утилита для диагностики (не обязательна, но рекомендуется). |
| **ClusterIssuer / Issuer** | — | Должен быть создан и активен в кластере (см. [](../definitions.md)). |

**Проверка готовности кластера перед началом:**

```bash
# 1. Проверка установки cert-manager
kubectl get pods -n cert-manager
# → cert-manager-...       1/1 Running
# → cert-manager-webhook-... 1/1 Running
# → cert-manager-cainjector-... 1/1 Running

# 2. Проверка доступности CRD
kubectl api-resources | grep cert-manager
# → certificates.cert-manager.io
# → clusterissuers.cert-manager.io
# → issuers.cert-manager.io

# 3. Проверка наличия активного ClusterIssuer
kubectl get clusterissuer
# → NAME              READY   REASON
# → letsencrypt-prod  True    ResourceIsAlwaysReconciled

# 4. Проверка Ingress-контроллера (пример для NGINX)
kubectl get pods -n ingress-nginx -l app.kubernetes.io/name=ingress-nginx
# → ingress-nginx-controller-...  1/1 Running
```

## Определения

**Ingress-интеграция cert-manager** — функциональность автоматизированного управления жизненным циклом TLS-сертификатов для ресурсов Ingress. Позволяет делегировать выпуск и продление сертификатов контроллеру cert-manager без необходимости ручного создания объектов `Certificate`.

**ingress-shim** — вспомогательный контроллер в составе основного бинарного файла cert-manager. Он отслеживает объекты Ingress и, основываясь на наличии специфических аннотаций, автоматически генерирует и поддерживает соответствующие ресурсы `Certificate`.

**Преимущества подхода:**
- **Декларативность:** Конфигурация TLS описывается непосредственно в объекте Ingress.
- **Автоматизация:** Полный цикл — от заказа сертификата у CA (Let's Encrypt, Vault и др.) до его ротации в Secret.
- **Универсальность:** Поддержка всех популярных Ingress-контроллеров (NGINX, Traefik, HAProxy, AWS ALB, GCE).

> **См. также:** [Cert-manager: Определения и основные понятия](../definitions.md) — обзор CRD, типов Issuer и архитектуры.

---

## Основные концепции

### Механизм работы ingress-shim

Контроллер `ingress-shim` реализует реактивную модель управления:

1. **Наблюдение:** Контроллер мониторит API-сервер на предмет событий `create` и `update` для ресурсов Ingress. Он использует informer-кеш, что позволяет работать без постоянного опроса и уменьшает нагрузку на API-сервер.
2. **Фильтрация:** Проверяется наличие аннотаций выбора Issuer (например, `cert-manager.io/cluster-issuer`). Если аннотаций нет, Ingress игнорируется. Приоритет аннотаций: `cert-manager.io/cluster-issuer` > `cert-manager.io/issuer` > `kubernetes.io/tls-acme: "true"`.
3. **Генерация Certificate:**
   - Создается ресурс `Certificate` в том же Namespace, что и Ingress.
   - Имя ресурса по умолчанию формируется как `name-of-ingress-tls-name` или задается аннотацией `cert-manager.io/certificate-name`.
   - Поля `dnsNames` заполняются из `spec.tls[].hosts`.
   - Поле `secretName` берется из `spec.tls[].secretName`.
4. **Установка OwnerReference:** Созданный `Certificate` получает `ownerReference`, указывающий на родительский Ingress. При удалении Ingress ресурс `Certificate` будет удален автоматически (Garbage Collection).

**Полный цикл жизненного цикла:**

`Ingress (с аннотациями) → ingress-shim → Certificate → Issuer/ClusterIssuer → CertificateRequest → Order → Challenge → Secret (TLS)`

```text
┌─────────────────────────────────────────────────────┐
│                    Ingress                          │
│  annotations: cert-manager.io/cluster-issuer      │
│  spec.tls[].hosts → *.example.com                   │
│  spec.tls[].secretName → myapp-tls-secret           │
└───────────────┬─────────────────────────────────────┘
                │ ingress-shim читает аннотации
                │ и генерирует Certificate
                ▼
┌─────────────────────────────────────────────────────┐
│                 Certificate                         │
│  dnsNames: [*.example.com]                          │
│  secretName: myapp-tls-secret                       │
│  issuerRef: {name: letsencrypt-prod, kind: ClusterIssuer}│
│  ownerRef: {Ingress/my-app-ingress}                 │
└───────────────┬─────────────────────────────────────┘
                │ cert-manager controller
                │ читает Certificate и Issuer
                ▼
┌─────────────────────────────────────────────────────┐
│                   Issuer/ClusterIssuer              │
│  ACME solver: HTTP-01 / DNS-01                      │
│  server: https://acme-v02.api.letsencrypt.org       │
└───────────────┬─────────────────────────────────────┘
                │ Создание Order и Challenge
                ▼
┌─────────────────────────────────────────────────────┐
│           Order → Challenge → CertificateRequest    │
│  Проверка владения доменом через ACME               │
└───────────────┬─────────────────────────────────────┘
                │ Выпуск сертификата
                ▼
┌─────────────────────────────────────────────────────┐
│            Kubernetes Secret (TLS)                  │
│  tls.crt: <сертификат>                             │
│  tls.key: <приватный ключ>                         │
│  Ingress-контроллер подхватывает Secret             │
└─────────────────────────────────────────────────────┘
```

**Важно:** `ingress-shim` не участвует в процессе выпуска сертификата напрямую. Он лишь создает и поддерживает ресурс `Certificate` в актуальном состоянии. Сам процесс выпуска, проверки и продления осуществляется основной логикой cert-manager через Issuer/ClusterIssuer.

**Разграничение Issuer и ClusterIssuer в контексте Ingress:**

| Тип | Описание | Применимость для Ingress |
| :--- | :--- | :--- |
| **Issuer** | Ресурс в пределах одного Namespace. `ingress-shim` ищет его в том же Namespace, где находится Ingress. | Подходит для локальных CA, внутренних сертификатов. Требует создания Issuer в каждом Namespace. |
| **ClusterIssuer** | Глобальный ресурс кластера. Работает с Ingress в любом Namespace. | Стандарт для публичных CA (Let's Encrypt). Не требует дублирования конфигурации. |

**Аннотация `cert-manager.io/issuer-kind`** позволяет явно указать тип Issuer (`Issuer` или `ClusterIssuer`), что полезно при использовании кастомных Issuer из сторонних CRD или при отладке неоднозначностей.

### Взаимодействие с IngressClass

cert-manager может фильтровать Ingress по классам. При использовании ACME (HTTP-01) важно, чтобы `ingressClassName` в Ingress совпадал с конфигурацией Solver в Issuer. Аннотация `acme.cert-manager.io/http01-ingress-class` позволяет переопределить класс для временных Ingress, создаваемых в процессе проверки.

### Специфика 2026 года

- **ARI (ACME Renewal Information):** Поддержка протокола, позволяющего CA динамически определять оптимальное время продления сертификата.
- **Алгоритмы:** Полный переход на **Ed25519** и **ECDSA (P-256/384)** как стандарты безопасности по умолчанию.
- **Короткие сертификаты:** Let's Encrypt и другие CA перешли на 45-дневные циклы (вместо 90), что делает автоматизацию через cert-manager критически важной.

---

## Аннотации cert-manager для Ingress

### Выбор и настройка Issuer

| Аннотация | Описание | Значение |
| :--- | :--- | :--- |
| `cert-manager.io/issuer` | Использовать Issuer в том же Namespace | `имя-issuer` |
| `cert-manager.io/cluster-issuer` | Использовать общекластерный ClusterIssuer | `имя-cluster-issuer` |
| `kubernetes.io/tls-acme: "true"` | Использовать Issuer по умолчанию (флаги `--default-issuer-*`) | `"true"` |
| `cert-manager.io/issuer-kind` | Явное указание типа (если не Issuer) | `ClusterIssuer`, `Issuer` |
| `cert-manager.io/issuer-group` | Группа API для Issuer | `cert-manager.io` (по умолчанию) |

### Параметры выпуска Certificate

| Аннотация | Описание | Значение по умолчанию / Пример |
| :--- | :--- | :--- |
| `cert-manager.io/certificate-name` | Явное имя для ресурса Certificate | `my-custom-cert-name` |
| `cert-manager.io/common-name` | Установка Common Name (CN) сертификата | `example.com` |
| `cert-manager.io/duration` | Срок действия сертификата | `1080h` (45 дней) |
| `cert-manager.io/renew-before` | За сколько до окончания начать продление | `168h` (7 дней) |
| `cert-manager.io/usages` | Key Usages (через запятую) | `server auth, client auth` |
| `cert-manager.io/issue-temporary-certificate` | Выпуск временного сертификата до ACME | `"true"` |

### Безопасность и приватные ключи

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `cert-manager.io/private-key-algorithm` | Алгоритм генерации ключа | `ECDSA`, `Ed25519`, `RSA` |
| `cert-manager.io/private-key-size` | Размер ключа (для RSA/ECDSA) | `256`, `384`, `4096` |
| `cert-manager.io/private-key-rotation-policy` | Ротация ключа при каждом обновлении | `Always` (рекомендуется) |

### Специфичные для ACME (HTTP-01)

| Аннотация | Описание | Применение |
| :--- | :--- | :--- |
| `acme.cert-manager.io/http01-edit-in-place` | Не создавать новый Ingress для проверки | AWS ALB, GCE Ingress, Cloudflare |
| `acme.cert-manager.io/http01-ingress-class` | Класс Ingress для временных ресурсов | Если отличается от основного |

---

## Практические сценарии

### Сценарий 1: Базовая конфигурация (Standard 2026)

Для большинства случаев достаточно указать ClusterIssuer и политику ротации ключей.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp-ingress
  annotations:
    # 1. Выбор выпускающего органа
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    # 2. Современный стандарт безопасности
    cert-manager.io/private-key-algorithm: "ECDSA"
    cert-manager.io/private-key-rotation-policy: "Always"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - myapp.example.com
    secretName: myapp-tls-secret
  rules:
  - host: myapp.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: myapp-svc
            port:
              number: 80
```

#### Пошаговое применение и проверка

**1. Применение конфигурации:**

```bash
# Применение манифеста
kubectl apply -f myapp-ingress.yaml -n my-namespace
```

**2. Проверка создания Certificate (ingress-shim):**

```bash
# Через 5-10 секунд после применения Ingress
kubectl get certificate -n my-namespace
# → NAME                         READY   SECRET               AGE
# → myapp-ingress-myapp-example-com  False   myapp-tls-secret   5s

# Должен появиться ресурс Certificate с именем по шаблону <ingress-name>-<tls-name>
# (или с именем из аннотации cert-manager.io/certificate-name)
```

**3. Проверка статуса сертификата:**

```bash
# Подробный статус через cmctl
cmctl status certificate myapp-ingress-myapp-example-com -n my-namespace

# Или через kubectl
kubectl describe certificate myapp-ingress-myapp-example-com -n my-namespace
# → Status:
# →   Ready: True
# →   Not After: 2026-12-01T12:00:00Z
```

**4. Проверка выпущенного Secret:**

```bash
# Проверка наличия Secret с TLS-ключами
kubectl get secret myapp-tls-secret -n my-namespace
# → NAME              TYPE                DATA   AGE
# → myapp-tls-secret  kubernetes.io/tls   2      2m

# Просмотр содержимого сертификата
kubectl get secret myapp-tls-secret -n my-namespace -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | head -20
# → Certificate:
# →     Data:
# →         Version: 3 (0x2)
# →         Serial Number: ...
# →         Signature Algorithm: ecdsa-with-SHA256
# →         Issuer: C=US, O=Let's Encrypt, CN=R11
# →         Subject: CN=myapp.example.com
# →         X509v3 Subject Alternative Name:
# →             DNS:myapp.example.com
```

### Сценарий 2: Явное имя Certificate и переопределение Common Name

Иногда требуется задать собственное имя для ресурса Certificate или установить определенный Common Name.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-ingress
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    cert-manager.io/certificate-name: "app-custom-cert"
    cert-manager.io/common-name: "app.example.com"
    cert-manager.io/usages: "server auth"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - app.example.com
    secretName: app-tls-secret
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: app-service
            port:
              number: 80
```

**Проверка:**

```bash
# Certificate должен иметь именно заданное имя
kubectl get certificate app-custom-cert -n my-namespace
# → NAME            READY   SECRET            AGE
# → app-custom-cert True    app-tls-secret    2m

# Проверка Common Name в сертификате
kubectl get secret app-tls-secret -n my-namespace -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | grep "Subject:"
# → Subject: CN=app.example.com
```

### Сценарий 3: Использование namespace-scoped Issuer

Если Issuer создан в том же Namespace, что и Ingress, используйте аннотацию `cert-manager.io/issuer` вместо `cert-manager.io/cluster-issuer`.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: internal-ingress
  namespace: team-alpha
  annotations:
    cert-manager.io/issuer: "internal-ca"
    cert-manager.io/private-key-algorithm: "ECDSA"
    cert-manager.io/private-key-size: "256"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - app.internal.local
    secretName: internal-tls-secret
  rules:
  - host: app.internal.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: internal-service
            port:
              number: 80
```

**Проверка:**

```bash
# Проверка, что Certificate привязан к Issuer, а не ClusterIssuer
kubectl get certificate -n team-alpha -o wide
# → NAME                             READY   SECRET               ISSUER        AGE
# → internal-ingress-app-internal-local True   internal-tls-secret  internal-ca   1m

# Проверка статуса Issuer
cmctl status certificate internal-ingress-app-internal-local -n team-alpha
```

> **Детальные примеры:** [Сценарии интеграции](./scenarios.md) — разбор случаев с Wildcard, SAN, несколькими TLS-секретами и временными сертификатами.

---

## Лучшие практики (Best Practices)

### Безопасность

1. **Всегда используйте `ClusterIssuer`** для публичных сертификатов (Let's Encrypt). `Issuer` локализован в Namespace и требует дублирования конфигурации.
2. **Ротация ключей:** Устанавливайте `cert-manager.io/private-key-rotation-policy: "Always"`. Это обеспечивает Perfect Forward Secrecy (PFS) — даже при компрометации одного ключа другие сертификаты остаются защищенными.
3. **Алгоритмы ключей:** Используйте ECDSA (P-256) или Ed25519 вместо RSA. Они быстрее, меньше по размеру и соответствуют стандартам 2026 года. RSA использовать только для легаси-совместимости.
4. **Не храните приватные ключи в Git:** Secret с TLS-ключами помечайте для шифрования через `sealed-secrets`, `external-secrets` или SOPS.
5. **Ограничьте права Issuer:** Используйте Kyverno или OPA для принудительства использования только ECDSA и минимального срока действия сертификатов (см. [](../Administration/index.md)).

### Надежность и производительность

1. **Staging-first:** Всегда тестируйте новую конфигурацию сертификата через Let's Encrypt Staging, прежде чем применять в Production.
2. **Мониторинг истечения:** Настраивайте алерты на метрику `certmanager_certificate_expiration_timestamp_seconds` (см. [](../Administration/operations.md)).
3. **Размер SAN-списка:** Не включайте в один сертификат более 50 доменов. Это увеличивает время выпуска и риск отклонения провайдером.
4. **Edit-in-place для облаков:** При использовании AWS ALB, GCE Ingress или Cloudflare всегда указывайте `acme.cert-manager.io/http01-edit-in-place: "true"` для избежания создания дублирующих балансировщиков.
5. **Отдельные Secret на хост:** Для изоляции используйте отдельный `secretName` для каждого хоста, а не один Secret на всех.

### GitOps и CI/CD

1. **Исключайте временные ресурсы:** `Certificate`, `Order`, `Challenge` и `CertificateRequest` управляются cert-manager автоматически. Экспортировать их в Git не нужно — достаточо Ingress и Issuer.
2. **Управляйте Secret отдельно:** Если используете ArgoCD или Flux, настраютте игнорирование изменений в `tls.secretName` через `ignoreDifferences` или аналогичную функцию.

## Граничные случаи и ограничения

### Ограничения HTTP-01

- **Не работает с Wildcard:** HTTP-01 не может подтвердить владение `*.example.com`. Для wildcard-сертификатов обязательно используйте DNS-01.
- **Конфликт редиректа HTTP→HTTPS:** Если Ingress-контроллер принудительно редиректит все запросы на `/.well-known/acme-challenge/` с 80 на 443, проверка провалится. Исключайте этот путь из редиректов.
- **Проблемы с NAT Loopback:** Кластер, находящийся за NAT, не может достучаться до своего внешнего IP для self-check. Используйте DNS-01 или локальную проброску портов.

### Ограничения Ingress API

- **Один Secret на несколько TLS-секций:** Если несколько секций `tls` в Ingress используют один и тот же `secretName`, cert-manager выпустит один сертификат для объединенного списка хостов.
- **Изменение `ingressClassName` после выпуска:** При смене класса Ingress может потребоваться ручной delete Certificate для принудительного пересоздания.
- **Аннотации vs IngressClass:** Если Ingress содержит `ingressClassName`, но аннотация `acme.cert-manager.io/http01-ingress-class` указывает другой класс, временный Ingress для HTTP-01 будет создан с классом из аннотации.

### Поведение при изменениях

| Действие | Поведение cert-manager |
| :--- | :--- |
| **Добавление хоста в `tls`** | Certificate обновляется, инициируется перевыпуск. |
| **Удаление хоста из `tls`** | Certificate обновляется, старый хост удаляется из SAN. |
| **Смена `secretName`** | Создается новый Secret, старый остается (не удаляется). |
| **Смена Issuer** | Certificate обновляется с новым Issuer, старый сертификат не аннулируется автоматически. |
| **Удаление Ingress** | Certificate удаляется через OwnerReference, Secret остается. |

## Дополнительная информация

### Управление ресурсами и очистка

- **Удаление:** Когда вы удаляете Ingress, `ingress-shim` удаляет созданный им `Certificate`. Однако **Secret с сертификатом остается в кластере** для предотвращения случайной потери данных. Очистка секретов выполняется администратором или внешними инструментами.
- **Изменение hosts:** При добавлении или удалении хостов в секции `tls` объекта Ingress, cert-manager автоматически обновит ресурс `Certificate` и инициирует перевыпуск.
- **Очистка неиспользуемых Secret:** После удаления Ingress можно найти и удалить осиротевшие Secret вручную:
  ```bash
  # Поиск Secret без связанного Certificate
  kubectl get secret -n <namespace> -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' | while read secret; do
    kubectl get certificate -n <namespace> -o jsonpath '{range .items[*]}{.spec.secretName}{"\n"}{end}' | grep -q "^${secret}$" || echo "ORPHAN: $secret"
  done
  ```

### Диагностика и Troubleshooting

Основным инструментом диагностики является утилита `cmctl` и анализ событий Kubernetes.

#### 1. Использование cmctl для диагностики Ingress

```bash
# 1. Проверка доступности API и вебхуков cert-manager
cmctl check api --wait=2m

# 2. Полный статус цепочки выпуска (Certificate -> Request -> Order -> Challenge)
cmctl status certificate myapp-tls-secret -n <namespace>

# 3. Проверка валидности Issuer
cmctl check api

# 4. Инспекция секрета (проверка срока, SAN, эмитента)
cmctl inspect secret myapp-tls-secret -n <namespace>
```

#### 2. Автоматическая диагностика (cmctl diagnose)

Начиная с v1.20, `cmctl diagnose` автоматически анализирует конфигурацию и выявляет распространенные проблемы:

```bash
# Диагностика конкретного Ingress
cmctl diagnose ingress myapp-ingress -n <namespace>

# Диагностика всего Namespace
cmctl diagnose ingress --namespace <namespace> --all
```

Утилита проверяет:
- Наличие и корректность аннотаций cert-manager
- Доступность указанного Issuer/ClusterIssuer
- Совпадение `ingressClassName` с конфигурацией Solver
- Доступность DNS для указанных хостов
- Открытые порты для HTTP-01 проверки

#### 3. Ручная диагностика через kubectl

Если `cmctl` недоступен, используйте пошаговую диагностику по иерархии ресурсов:

```bash
# 1. Проверка созданного Certificate (ingress-shim)
kubectl get certificate -n <namespace> -o wide
# → NAME                          READY   SECRET              ISSUER                 AGE
# → myapp-ingress-myapp-ex-com     False   myapp-tls-secret     letsencrypt-prod       5s

# 2. Детальный статус Certificate (ищите сообщения об ошибках в status.conditions)
kubectl describe certificate myapp-ingress-myapp-example-com -n <namespace>

# 3. Просмотр событий (Events) Ingress
kubectl describe ingress myapp-ingress -n <namespace>
# → Events:
# →   Warning  cert-manager-ingress-controller  10s   cert-manager  ...

# 4. Просмотр событий Certificate
kubectl describe certificate myapp-ingress-myapp-example-com -n <namespace>
# → Events:
# →   Warning  IssuerNotReady  ...
# →   Normal   Generated  ...
```

#### 4. Глубокая диагностика цепочки ACME

Для отладки проблем с выпуском сертификата по цепочке ресурсов:

```bash
# 1. Поиск всех связанных ресурсов
kubectl get certificate,certificaterequest,order,challenge -n <namespace>
# → NAME                                              READY   RESOURCE                                     AGE
# → certificate.cert-manager.io/myapp-tls             False   myapp-tls-xxxxx                              5m
# → certificaterequest.cert-manager.io/myapp-tls-...  False   myapp-tls-...                                5m
# → order.acme.cert-manager.io/myapp-tls-...          False   myapp-tls-...                                5m
# → challenge.acme.cert-manager.io/myapp-tls-...-...  False   myapp-tls-...                              5m

# 2. Осмотр Challenge (самый информативный уровень)
kubectl describe challenge <challenge-name> -n <namespace>
# → Status:
# →   State: pending
# →   Reason: Error
# →   FailureTime: 2026-09-04T05:00:00Z

# 3. Чтение логов контроллера
kubectl logs -n cert-manager -l app.kubernetes.io/instance=cert-manager | grep "myapp.example.com"
# → E ... failed to solve challenge: ...
```

#### 5. Проверка выпущенного сертификата

```bash
# Проверка содержимого Secret
kubectl get secret myapp-tls-secret -n <namespace> -o yaml
# → apiVersion: v1
# → kind: Secret
# → type: kubernetes.io/tls
# → data:
# →   tls.crt: <base64>
# →   tls.key: <base64>

# Декодирование и проверка сертификата
kubectl get secret myapp-tls-secret -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout

# Проверка цепочки доверия
kubectl get secret myapp-tls-secret -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl verify -CAfile /path/to/ca-chain.pem
```

#### 6. Частые проблемы и решения

| Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Certificate` не создается | Отсутствует аннотация или опечатка в имени Issuer | Проверьте `metadata.annotations`, используйте `cmctl diagnose` |
| `Challenge` висит в `Pending` | Порт 80 закрыт или DNS не указывает на кластер | Проверить внешнюю доступность для HTTP-01, использовать `sslip.io` для тестов |
| `Issuer not found` | Namespace Issuer не совпадает с Ingress | Используйте `ClusterIssuer` для кросс-namespace работы |
| `Error: Secret was not found` | `secretName` в `spec.tls` не совпадает с именем в `Certificate.spec.secretName` | Убедитесь, что имена совпадают |
| Ошибка `Forbidden` в AWS ALB | Не включен `http01-edit-in-place` | Добавьте аннотацию `acme.cert-manager.io/http01-edit-in-place: "true"` |
| `Certificate` stuck в `Pending` после смены Issuer | Старый `CertificateRequest` не пересоздан | Удалите `CertificateRequest` вручную: `kubectl delete certificaterequest <name>` |
| `Failed to solve` в Challenge | Проблемы с доступом к временному поду `cm-acme-http-solver` | Проверьте NetworkPolicy для порта 8089, статус пода и сервис |

### Связанные документы

- **[Cert-manager: Определения](../definitions.md)** — база знаний по CRD и архитектуре.
- **[Gateway API: TLS](../gateway_api/definitions_and_concepts.md)** — современная альтернатива Ingress-интеграции.
- **[Let's Encrypt](../LetsEncrypt/index.md)** — настройка ACME-проверок и лимиты.
- **[Administration](../Administration/index.md)** — тюнинг контроллера и мониторинг.
- **[Ingress: Обзор](../../../Networking/Ingress/overview.md)** — сетевая архитектура в Kubernetes.
