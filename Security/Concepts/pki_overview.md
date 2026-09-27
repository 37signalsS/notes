# PKI — инфраструктура открытых ключей

## Определения

**PKI (Public Key Infrastructure)** — совокупность технологий, стандартов, политик и процедур, необходимых для создания, управления, распределения, использования, хранения и отзыва цифровых сертификатов. Основная цель — обеспечить доверенную среду для обмена данными и идентификации субъектов через асимметричную криптографию.

**CA (Certificate Authority / Удостоверяющий центр)** — доверенная третья сторона, ответственная за выпуск, подписание и проверку статуса цифровых сертификатов. Является «якорем доверия» (Trust Anchor) в системе.

**RA (Registration Authority / Регистратор)** — компонент, отвечающий за проверку личности заявителя перед тем, как направить подтверждённый запрос (CSR) в CA.

**X.509** — стандарт ITU-T, определяющий формат цифровых сертификатов. Современная версия v3 поддерживает расширения (Extensions), такие как SAN или Key Usage.

**CSR (Certificate Signing Request)** — запрос на подпись сертификата, содержащий открытый ключ заявителя и его идентификационные данные, подписанные приватным ключом заявителя.

**PKCS (Public-Key Cryptography Standards)** — группа стандартов для обмена криптографической информацией:
- **PKCS#10:** Стандарт формата CSR.
- **PKCS#12 (.p12, .pfx):** Защищенный контейнер для хранения пары «ключ + сертификат».
- **PKCS#7 / CMS:** Стандарт для подписи и шифрования (используется в P7B и цепочках).

**CT (Certificate Transparency)** — система открытых логов, куда CA обязаны записывать каждый выпущенный публичный сертификат. Позволяет владельцам доменов обнаруживать нелегитимные выпуски.

## Основные концепции

### Иерархия доверия

Для обеспечения безопасности и масштабируемости PKI строится в виде дерева:
- **Root CA (Корневой CA):** Вершина иерархии. Хранится в изолированной среде (offline/air-gapped). Его сертификат является самоподписанным и имеет длительный срок действия (10–25 лет).
- **Intermediate CA (Промежуточный CA):** Подписывается корневым узлом. Используется для повседневных операций. В случае компрометации отзывается только этот узел, сохраняя доверие к корню. Срок действия: 5–10 лет.
- **End-Entity Certificates (Конечные сертификаты):** Сертификаты серверов, пользователей или подписи кода. Срок действия в 2026 году — от 24 часов (внутри кластеров) до 398 дней (в вебе).

### Цепочка доверия (Chain of Trust)

Процесс валидации от клиента к корню:
1. **End-Entity** → проверяется подписью Intermediate CA.
2. **Intermediate CA** → проверяется подписью Root CA.
3. **Root CA** → должен находиться в локальном доверенном хранилище ОС или браузера (Trust Store).

### Публичный и приватный PKI

- **Публичный PKI (Global Trust):** Доверие встроено в браузеры (Let's Encrypt, ZeroSSL). Ограничен стандартами CA/Browser Forum.
- **Приватный PKI (Internal Trust):** Используется внутри организаций (HashiCorp Vault, Active Directory CS, step-ca). Позволяет выпускать сертификаты для внутренних доменов (например, `.internal`) и с произвольными политиками.

### Алгоритмы и криптография 2026

- **RSA:** Рекомендуемая длина ключа — 3072 или 4096 бит.
- **ECDSA:** Использование эллиптических кривых (P-256, P-384). Эффективнее RSA при меньшем размере ключа.
- **EdDSA (Ed25519):** Рекомендуемый стандарт благодаря высокой производительности и устойчивости к атакам по сторонним каналам.
- **PQC (Post-Quantum Cryptography):** Внедрение квантово-устойчивых алгоритмов (ML-DSA / FIPS 203) в гибридных схемах для защиты от угроз будущих квантовых компьютеров.

### Форматы файлов и стандарты

| Расширение | Тип | Описание |
| :--- | :--- | :--- |
| **.key / .pem** | Приватный ключ | Должен храниться в секрете (права `600` или HSM/TPM). |
| **.crt / .cer** | Сертификат | Публичный документ формата X.509. |
| **.csr** | Запрос (PKCS#10) | Временный файл для отправки в CA. |
| **.p12 / .pfx** | PKCS#12 | Контейнер «ключ + сертификат», защищенный паролем. |
| **fullchain.pem** | Цепочка | Объединяет сертификат сервера и все промежуточные CA. |

### Стандартные расширения X.509 v3

Современный сертификат X.509 v3 содержит критические расширения, определяющие его назначение и ограничения:

- **Basic Constraints:** Указывает, является ли сертификат CA (`CA:true`) и максимальную длину пути (`pathlen`). Для конечных сертификатов — `CA:FALSE`.
- **Key Usage:** Ограничивает криптографические операции: `digitalSignature`, `keyEncipherment`, `keyCertSign`, `cRLSign`.
- **Extended Key Usage (EKU):** Точно определяет назначение: `serverAuth`, `clientAuth`, `codeSigning`, `emailProtection`.
- **Subject Alternative Name (SAN):** Перечень DNS-имён, IP-адресов и URI. В 2026 году CN устарел в пользу SAN.
- **Name Constraints:** Запрет на выпуск сертификатов для определённых доменов или IP-диапазонов (применяется в промежуточных CA).
- **CRL Distribution Points:** URL-адреса, по которым клиенты могут получить список отзыва (CRL).
- **Authority Information Access (AIA):** Содержит URL OCSP-сервиса и адрес CA.
- **Authority Key Identifier (AKI) / Subject Key Identifier (SKI):** Связывают сертификат с издателем и ключом в цепочке.
- **Certificate Policies:** Идентификаторы политик выдачи (OID), используемые для валидации на стороне клиента.
- **Policy Constraints / Inhibit AnyPolicy:** Ограничивают распространение политик в иерархии.

## Механизмы отзыва и проверки статуса

1. **CRL (Certificate Revocation List):** Список серийных номеров отозванных сертификатов. Требует загрузки всего файла клиентом. Подходит для внутренних систем с ограниченным числом отзывов.
2. **OCSP (Online Certificate Status Protocol):** Протокол проверки статуса конкретного сертификата в реальном времени. Снижает нагрузку по сравнению с CRL, но требует доступности OCSP-responder.
3. **OCSP Stapling:** Сервер сам получает ответ от OCSP-сервера CA и передает его клиенту в процессе TLS-handshake. Это ускоряет соединение и повышает приватность пользователя. В 2026 году для публичных сертификатов всё чаще требуется **OCSP Must-Staple** (RFC 7633).
4. **Короткоживущие сертификаты (Short-Lived Certs):** Вместо механизма отзыва используются сертификаты с TTL от нескольких минут до 24 часов. Подход эффективен для внутренних mTLS-сред (Service Mesh, Kubernetes), где отзыв через CRL/OCSP сложно обеспечить.

## Практические сценарии

### Жизненный цикл и типы сертификатов

1. **Генерация и запрос:** Создание пары ключей и CSR.
2. **Валидация (DV, OV, EV):**
   - **DV (Domain Validation):** Проверка владения доменом (автоматически через ACME).
   - **OV/EV:** Ручная проверка юридического лица (Organization/Extended Validation).
3. **Выпуск и SAN:** Современные сертификаты используют **SAN (Subject Alternative Name)** для указания списка доменов вместо устаревшего поля Common Name (CN).
4. **Автоматизация (ACME ARI):** Использование протокола ACME с расширением ARI (Renewal Information) позволяет CA уведомлять клиента (например, cert-manager) о необходимости досрочного обновления.

### Работа с OpenSSL в CLI

**Генерация Ed25519 ключа и CSR с SAN:**
```bash
# Генерация ключа
openssl genpkey -algorithm ed25519 -out server.key

# Генерация CSR с указанием SAN
openssl req -new -key server.key -out server.csr \
    -subj "/C=RU/O=MyOrg/CN=example.com" \
    -addext "subjectAltName = DNS:example.com, DNS:www.example.com"
```

**Проверка соответствия ключа и сертификата (RSA):**
```bash
openssl rsa -noout -modulus -in server.key | openssl md5
openssl x509 -noout -modulus -in server.crt | openssl md5
```

**Проверка цепочки доверия:**
```bash
openssl verify -CAfile root-ca.crt -untrusted intermediate-ca.crt server.crt
```

**Просмотр расширений и отпечатков сертификата:**
```bash
# Полный вывод метаданных (SAN, EKU, Key Usage, AIA)
openssl x509 -in server.crt -noout -text

# Отпечаток SHA-256 для сверки с CT-логами
openssl x509 -in server.crt -noout -fingerprint -sha256
```

**Инспекция CSR перед отправкой в CA:**
```bash
openssl req -in server.csr -noout -text
```

**Просмотр CRL:**
```bash
openssl crl -in intermediate-ca/crl/crl.pem -noout -text
```

Для детальных сценариев развертывания CA на OpenSSL (одноуровневый и двухуровневый) и управления сертификатами сервисов см. [обзор одноуровневого CA](../../Security/Tools/openssl_ca/single_tier/overview.md) и [двухуровневого CA](../../Security/Tools/openssl_ca/two_tier/overview.md).

### Управление доверенными хранилищами (Trust Store)

Серверы и рабочие станции должны иметь актуальный набор корневых и промежуточных сертификатов.

**Debian/Ubuntu:**
```bash
# Копирование CA в системное хранилище
cp internal-ca.crt /usr/local/share/ca-certificates/
update-ca-certificates
# → Updating certificates in /etc/ssl/certs...
# → 1 added, 0 removed; done.
```

**RHEL/CentOS/Fedora:**
```bash
cp internal-ca.crt /etc/pki/ca-trust/source/anchors/
update-ca-trust extract
# → p11-kit: ... done
```

**OpenSSL (применение к конкретному приложению без системного хранилища):**
```bash
export SSL_CERT_FILE=/etc/ssl/certs/ca-bundle.crt
```

**Windows Server:**
```powershell
certutil -addstore -f "Root" .\internal-ca.crt
```

**macOS:**
```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain internal-ca.crt
```

### Мониторинг и оповещение об истечении

**Bash-скрипт для проверки срока действия удалённого сертификата:**
```bash
#!/usr/bin/env bash
HOST="$1"
PORT="${2:-443}"
DAYS_WARN="${3:-30}"

EXP_DATE=$(echo | openssl s_client -connect "$HOST:$PORT" -servername "$HOST" 2>/dev/null \
  | openssl x509 -noout -enddate 2>/dev/null \
  | cut -d= -f2)

if [ -z "$EXP_DATE" ]; then
  echo "FAIL: $HOST не отвечает или не предоставляет сертификат"
  exit 1
fi

EXP_EPOCH=$(date -j -f "%b %d %H:%M:%S %Y %Z" "$EXP_DATE" +%s 2>/dev/null || \
            date -d "$EXP_DATE" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( (EXP_EPOCH - NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -lt 0 ]; then
  echo "CRITICAL: $HOST сертификат истёк $(( -DAYS_LEFT )) дней назад"
elif [ "$DAYS_LEFT" -lt "$DAYS_WARN" ]; then
  echo "WARNING: $HOST сертификат истекает через $DAYS_LEFT дней"
else
  echo "OK: $HOST сертификат действителен ещё $DAYS_LEFT дней"
fi
```

**Интеграция с Prometheus Blackbox Exporter:**
```yaml
modules:
  tls_connect:
    prober: tcp
    timeout: 5s
    tcp:
      tls: true
      tls_config:
        server_name: "example.com"
```

Алерт в Prometheus/Mimir:
```yaml
- alert: TLSCertExpiringSoon
  expr: probe_ssl_earliest_cert_expiry - time() < 86400 * 30
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: "TLS сертификат {{ $labels.instance }} истекает менее чем через 30 дней"
```

Для организации централизованного ротации сертификатов в Kubernetes см. [управление сертификатами в Kubernetes](../../Kubernetes/Operations/certificate_management.md).

### mTLS: архитектурные паттерны

mTLS (Mutual TLS) требует сертификатов у обеих сторон. Практические паттерны внедрения:

- **Service Mesh (Istio/Linkerd):** Автоматическая выдача сертификатов через собственный Intermediate CA. Корневые сертификаты Mesh распределяются через ConfigMap или trust-manager.
- **Внутренние API:** Клиентские сертификаты выписываются на сотрудников/сервисы с EKU `clientAuth`. Проверка осуществляется на уровне прокси (Nginx/HAProxy) или приложения.
- **Базы данных:** PostgreSQL, MySQL поддерживают `REQUIRE X509` с матчингом по `SUBJECT`/`ISSUER`. Пример: `REQUIRE SUBJECT '/CN=app-node1/O=Corp' AND ISSUER '/CN=mysql-ca'`.

При использовании Docker API через TLS требуется включение `dockerd --tlsverify` и размещение сертификатов в `~/.docker/`.

### Air-gapped CA: процедура ротации

В полностью изолированных сетях процедура ротации корневого CA:
1. Подготовить новый Root CA на физически отдельном носителе.
2. Выпустить новый Intermediate CA и распространить его через доверенные каналы.
3. Обновить `trust-manager` Bundle или развернуть новый CA вручную на всех узлах.
4. Перевыпустить конечные сертификаты через новый Intermediate CA.
5. Отозвать старые корневые и промежуточные сертификаты (CRL + смена доверенных хранилищ).

### DNS CAA (Certificate Authority Authorization)

Запись CAA в DNS позволяет указать, какие CA имеют право выпускать сертификаты для домена:
```dns
example.com.  IN  CAA 0 issue "letsencrypt.org"
example.com.  IN  CAA 0 issuewild ";"
```
Это снижает риск нелегитимного выпуска даже при компрометации аккаунта на публичном CA.

### Дистрибуция доверия (Trust Distribution)

- **trust-manager (Kubernetes):** Аддон для cert-manager, автоматически распространяющий `Bundle` корневых сертификатов во все Namespaces.
- **Системные хранилища:** Обновление через `update-ca-certificates` (Debian/Ubuntu) или `update-ca-trust` (RHEL/CentOS).
- **Ansible автоматизация:** Для массового распространения CA в гетерогенной среде используйте плейбуки из [Certificate Automation](../../Ansible/ansible_certificate_management.md).

## Дополнительная информация

### Инструменты управления (2026)

- **cert-manager:** Основной оператор для Kubernetes (поддержка ACME, Vault, Venafi). Детали конфигурации — в соответствующем разделе документации Kubernetes.
- **HashiCorp Vault PKI:** Идеален для динамической выдачи короткоживущих сертификатов (TTL < 24ч).
- **step-ca:** Легкое решение для частных сетей с поддержкой ACME и SSH-сертификатов.
- **OpenSSL CA:** Для развертывания собственного CA на Linux-хостах используйте готовые сценарии [одноуровневого](../../Security/Tools/openssl_ca/single_tier/overview.md) и [двухуровневого](../../Security/Tools/openssl_ca/two_tier/overview.md) CA.
- **Аппаратная защита:** Использование **HSM** (Hardware Security Module) или **TPM 2.0** для защиты корневых ключей. HSM доступны через стандартные интерфейсы PKCS#11 и KMIP.

### Безопасность хранения ключей

- **Права доступа:** Приватные ключи должны иметь права `600` и принадлежать пользователю, под которым работает сервис.
- **В памяти:** Используйте `mlock()` или аналоги, чтобы предотвратить своппинг ключей в swap-раздел.
- **Внешние хранилища:** HSM, TPM, YubiKey. Для интеграции с приложениями используйте PKCS#11.
- **Резервное копирование:** Зашифрованные бэкапы ключей хранятся отдельно от сертификатов, с использованием отдельного пароля или шифрования GPG.

### Автоматизация выдачи и ротации

- **ACME клиенты:** certbot, lego, step client. В Kubernetes preferred — cert-manager с ARI.
- **Ansible:** Плейбуки для массовой выдачи и ротации сертификатов через Vault или step-ca описаны в [Certificate Automation](../../Ansible/ansible_certificate_management.md).
- **CI/CD:** Интеграция с GitLab CI/CD и GitHub Actions через `step certificate` или Vault PKI secrets engine.

### Миграция на постквантовую криптографию (PQC)

Переход на PQC должен быть поэтапным:
1. Инвентаризация текущих алгоритмов (CBOM).
2. Внедрение гибридных схем:ECDSA/Ed25519 + ML-DSA.
3. Обновление библиотек (OpenSSL 3.5+ поддерживает гибридные ключи).
4. Тестирование совместимости с клиентами и промежуточными узлами.

Детали миграции и PQC-алгоритмы описаны в [Supply Chain Security overview](../../Security/Supply_Chain_Security/overview.md).

### Типовые ошибки и диагностика

| Ошибка / Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `unable to verify the first certificate` | Сервер не отправляет Intermediate CA. | Установить `fullchain.pem`. |
| `unable to get local issuer certificate` | В trust store клиента нет корневого CA. | Добавить CA через `update-ca-certificates` или `certutil`. |
| `Self-signed certificate` | Сертификат подписан самим собой. | Использовать доверенный CA или добавить в trust store. |
| `Certificate expired` | Срок действия истёк. | Перевыпустить и обновить на сервере. |
| `Hostname mismatch` | CN или SAN не совпадают с доменом. | Выпустить с корректным SAN. |
| `Name Constraints Violation` | Домен запрещён политикой вышестоящего CA. | Проверить `permittedDNSdomains` в промежуточном CA. |
| `Key Usage Violation` | Сертификат используется не по назначению (например, серверный для подписи кода). | Проверить `keyUsage` и `extendedKeyUsage`. |
| `Incomplete Chain` | Клиент не знает Intermediate CA. | Передать полную цепочку или включить `ssl_trusted_certificate` в Nginx. |
| `OCSP response: no response sent` | OCSP Stapling не настроен или сертификат не содержит AIA. | Проверить `ssl_stapling` и наличие `Authority Information Access`. |
| `certificate signed by unknown authority` | CA отсутствует в trust store или подпись невалидна. | Добавить CA или перевыпустить сертификат. |

### Связанные темы

- [Протокол TLS/SSL](../../Networking/Protocols/tls.md) — транспортная безопасность.
- [Диагностика SSL/TLS сертификатов](../Tools/ssl_certificate_diagnostics.md) — отладка цепочек и ошибок.
- [HashiCorp Vault: концепции](../../Vault/concepts.md) — динамическая генерация сертификатов.
- [Certificate Pinning](./certificate_pinning.md) — привязка клиентов к сертификатам/ключам.
- [Certificate Transparency](./certificate_transparency.md) — публичное логирование сертификатов.
- [Key Escrow Policy](./key_escrow_policy.md) — политика хранения копий ключей.
- [OCSP Responder](../Tools/openssl_ca/ocsp_responder.md) — настройка OCSP-резолвера.
- [CRL Distribution Points](../Tools/openssl_ca/crl_distribution_points.md) — настройка HTTP-сервера для CRL.
- [ГОСТ-криптография](../Tools/gost_cryptography.md) — реализация ГОСТ-алгоритмов в OpenSSL.
