# Certificate Pinning — практики привязки сертификатов

**Актуально для:** Certificate Pinning (2026, OpenSSL 3.x, nginx 1.24+, Apache 2.4.60+)

## Определения

**Certificate Pinning** — механизм привязки клиента к конкретному сертификату или публичному ключу сервера, минуя стандартную проверку цепочки доверия через CA. Клиент «запоминает» ожидаемый сертификат/ключ и при подключении проверяет соответствие.

**HPKP (HTTP Public Key Pinning, RFC 7469)** — механизм привязки через HTTP-заголовок. **Устарел** (убран из Chrome 72, Firefox 72). Заменён на Expect-CT и Certificate Transparency.

**Expect-CT** — HTTP-заголовок, требующий от сервера включения сертификата в CT-логи. Также **устарел** (Chrome 104).

**Subject Alternative Name (SAN) Pinning** — привязка к конкретному DNS-имени в SAN сертификата (самый распрострашённый тип на 2026).

**Public Key Pinning** — привязка к публичному ключу (SPKI Hash) вместо всего сертификата. Более гибкий: ключ можно сохранить при перевыпуске сертификата.

**CT (Certificate Transparency) Pinning** — требование, чтобы сертификат был logged в CT-логах. Де-факто стандарт для public CA (требование Chrome).

---

## Концепции и архитектура

### Зачем нужен Certificate Pinning

1. **Защита от подмены (MITM):** Даже если компрометирован любой CA в цепочке, поддельный сертификат не пройдёт проверку
2. **Защита от corporate proxy:** Предотвращает инспекцию трафика через корпоративные прокси (если клиент пинит сертификат)
3. **Защита от украденных ключей:** Если украден ключ промежуточного CA, пиннинг ограничивает количество подверженных сервисов

### Как работает пиннинг

```text
┌─────────────┐                    ┌──────────────┐
│   Клиент    │──── TLS Hello ────▶│   Сервер     │
│             │◀─── Certificate ───│              │
│             │                    └──────────────┘
│  ┌──────────┐
│  │ Pin Store│  ← список ожидаемых публичных ключей
│  │ (локальный│     или сертификатов
│  │  или CDN) │
│  └──────────┘
│       │
│  Сравнение:
│  SHA-256(server_pubkey) == pin ?
│       │
│  ├── ДА  → соединение установлено
│  └── НЕТ → соединение отклонено
```

Клиент извлекает публичный ключ из сертификата сервера, вычисляет SHA-256 хэш в формате SubjectPublicKeyInfo (SPKI) и сравнивает с заранее известными пинами. Если ни один пин не совпадает — соединение разрывается.

### Типы пиннинга

| Тип | Что привязывается | Гибкость | Использование |
| :--- | :--- | :--- | :--- |
| Leaf Certificate | Весь сертификат | Низкая (при перевыпуске — новый пин) | Простые случаи |
| Public Key (SPKI) | SHA-256 хэш публичного ключа | Средняя (перевыпуск с тем же ключом OK) | Рекомендуется |
| CA Certificate | Сертификат CA | Высокая (вся цепочка) | Корпоративные среды |
| CT Log Entry | Наличие в CT-логе | Высокая | Public CA |

---

## Практические сценарии

### Пререквизиты

Перед настройкой пиннинга:

- **TLS-сервер** с валидным сертификатом и цепочкой доверия
- **SPKI-хэш** публичного ключа сервера (извлекается через `openssl`)
- **Backup-ключ** — резервный публичный ключ, ещё не используемый сервером
- **Клиентское приложение**, поддерживающее кастомную проверку сертификатов (OkHttp, URLSession, curl, Go `crypto/tls`, Python `ssl`)
- **График ротации** — backup-пин должен быть готов минимум за 10 дней до смены ключа

### Мобильные приложения (iOS/Android)

#### Android (Network Security Config)

```xml
<!-- res/xml/network_security_config.xml -->
<network-security-config>
    <domain-config>
        <domain includeSubdomains="true">api.mycompany.com</domain>
        <pin-set expiration="2027-01-01">
            <!-- Текущий публичный ключ (SHA-256 base64) -->
            <pin digest="SHA-256">YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=</pin>
            <!-- Backup пин (другой ключ CA или rotation key) -->
            <pin digest="SHA-256">sRHdihwgkaib1P1gN4U+0UK0LMfZLg=</pin>
        </pin-set>
        <!-- Trust anchors: системные CA + пользовательские -->
        <trust-anchors>
            <certificates src="system" />
            <certificates src="user" />
        </trust-anchors>
    </domain-config>
</network-security-config>
```

```java
// Проверка пиннинга в коде (Kotlin)
CertificatePinner certificatePinner = new CertificatePinner.Builder()
    .add("api.mycompany.com",
         "sha256/YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=")
    .add("api.mycompany.com",
         "sha256/sRHdihwgkaib1P1gN4U+0UK0LMfZLg=")
    .build();

OkHttpClient client = new OkHttpClient.Builder()
    .certificatePinner(certificatePinner)
    .build();
```

#### iOS (URLSession)

```swift
// Пиннинг через URLSessionDelegate
func urlSession(_ session: URLSession,
                didReceive challenge: URLAuthenticationChallenge,
                completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {

    guard let serverTrust = challenge.protectionSpace.serverTrust,
          let certificate = SecTrustGetCertificateAtIndex(serverTrust, 0) else {
        completionHandler(.cancelAuthenticationChallenge, nil)
        return
    }

    // Извлечение публичного ключа
    let serverPublicKey = SecCertificateCopyKey(certificate)
    let serverPublicKeyData = SecKeyCopyExternalRepresentation(serverPublicKey!, nil) as Data?

    // Хэширование и сравнение с пином
    let pinHash = sha256Hash(serverPublicKeyData!)
    let expectedPins = [
        "YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=",
        "sRHdihwgkaib1P1gN4U+0UK0LMfZLg="
    ]

    if expectedPins.contains(pinHash) {
        completionHandler(.useCredential, URLCredential(trust: serverTrust))
    } else {
        completionHandler(.cancelAuthenticationChallenge, nil)
    }
}
```

### curl с пиннингом

```bash
# Пиннинг по публичному ключу (SHA-256)
curl --pinnedpubkey 'sha256//YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=' \
  https://api.mycompany.com/health

# Пиннинг по сертификату
curl --pinnedpubkey 'sha256//YhKJg7...' \
  --cert-status \
  https://api.mycompany.com/health
```

### Go (с кастомным TLS)

```go
package main

import (
    "crypto/sha256"
    "crypto/tls"
    "crypto/x509"
    "encoding/base64"
    "fmt"
    "net/http"
)

func main() {
    expectedPins := []string{
        "YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=",
        "sRHdihwgkaib1P1gN4U+0UK0LMfZLg=",
    }

    tlsConfig := &tls.Config{
        VerifyConnection: func(state tls.ConnectionState) error {
            if len(state.PeerCertificates) == 0 {
                return fmt.Errorf("no peer certificates")
            }
            leaf := state.PeerCertificates[0]
            pubKeyBytes, _ := x509.MarshalPKIXPublicKey(leaf.PublicKey)
            pin := sha256.Sum256(pubKeyBytes)
            pinB64 := base64.StdEncoding.EncodeToString(pin[:])

            for _, expected := range expectedPins {
                if pinB64 == expected {
                    return nil
                }
            }
            return fmt.Errorf("pin mismatch: got %s", pinB64)
        },
    }

    client := &http.Client{Transport: &http.Transport{TLSClientConfig: tlsConfig}}
    resp, err := client.Get("https://api.mycompany.com/health")
    if err != nil {
        fmt.Println("Error:", err)
        return
    }
    defer resp.Body.Close()
    fmt.Println("Status:", resp.Status)
}
```

### Python (ssl + cryptography)

```python
import ssl
import socket
import hashlib
import base64

EXPECTED_PINS = [
    "YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=",
    "sRHdihwgkaib1P1gN4U+0UK0LMfZLg=",
]

def verify_pin(hostname: str, port: int = 443) -> bool:
    """
    Verify the server's public key against expected pins.
    Requires: pip install cryptography
    """
    context = ssl.create_default_context()
    with socket.create_connection((hostname, port)) as sock:
        with context.wrap_socket(sock, server_hostname=hostname) as ssock:
            cert_der = ssock.getpeercert(binary_form=True)

    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    cert = x509.load_der_x509_certificate(cert_der)
    public_key = cert.public_key()

    # SubjectPublicKeyInfo в DER формате
    spki_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    # SHA-256 → base64
    pin = base64.b64encode(hashlib.sha256(spki_der).digest()).decode()

    if pin not in EXPECTED_PINS:
        raise ssl.SSLError(
            f"Certificate pinning verification failed: "
            f"expected one of {EXPECTED_PINS}, got {pin}"
        )
    return True

# Usage
try:
    verify_pin("api.mycompany.com")
    print("Pin verified")
except ssl.SSLError as e:
    print(f"Error: {e}")
```

### Серверные веб-серверы (nginx, Apache)

Серверная сторона пиннинга ограничена: **HPKP устарел**, поэтому сервер не отправляет пины клиенту. Вместо этого sysadmin обеспечивает:

- **HSTS** (Strict-Transport-Security) — вынуждает клиент использовать HTTPS
- **OCSP stapling** — ускоряет и обезопасчивает проверку отзечия сертификата
- **Certificate Transparency** — публичное логирование выпуска сертификатов

#### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name api.mycompany.com;

    ssl_certificate     /etc/nginx/ssl/api.mycompany.com.crt;
    ssl_certificate_key /etc/nginx/ssl/api.mycompany.com.key;
    ssl_trusted_certificate /etc/nginx/ssl/ca-chain.crt;

    # OCSP stapling
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 1.1.1.1 valid=300s;
    resolver_timeout 5s;

    # HSTS (NOT HPKP — HPKP is deprecated)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # Certificate Transparency (требует OpenSSL 3.x с CT support;
    # иначе — используйте отдельный CT-мониторинг на уровне CA)
}
```

#### Apache

```apache
<VirtualHost *:443>
    ServerName api.mycompany.com

    SSLEngine on
    SSLCertificateFile      /etc/ssl/certs/api.mycompany.com.crt
    SSLCertificateKeyFile   /etc/ssl/private/api.mycompany.com.key
    SSLCertificateChainFile /etc/ssl/certs/ca-chain.crt

    # OCSP stapling
    SSLUseStapling on
    SSLStaplingCache "shmcb:/var/run/ocsp(128000)"

    # HSTS
    Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
</VirtualHost>
```

---

## Операции и команды

### Извлечение пина из сертификата

```bash
# SPKI-хэш из локального файла сертификата
openssl x509 -in cert.pem -pubkey -noout \
  | openssl pkey -pubin -outform DER \
  | openssl dgst -sha256 -binary \
  | base64
# → YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=
```

```bash
# SPKI-хэш из работающего сервера
openssl s_client -connect api.mycompany.com:443 -servername api.mycompany.com </dev/null 2>/dev/null \
  | openssl x509 -pubkey -noout \
  | openssl pkey -pubin -outform DER \
  | openssl dgst -sha256 -binary \
  | base64
# → YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=
```

```bash
# Извлечение сразу нескольких пинов (текущий + backup)
openssl req -x509 -newkey rsa:2048 -keyout backup.key -out backup.crt \
  -days 365 -nodes -subj "/CN=backup"
cat backup.crt | openssl x509 -pubkey -noout \
  | openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | base64
```

### Тестирование пиннинга

```bash
# Проверка через curl (ожидается успех)
curl --pinnedpubkey 'sha256//YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=' \
  https://api.mycompany.com/health

# Проверка с неверным пином (ожидается ошибка)
curl --pinnedpubkey 'sha256//invalidhash' \
  https://api.mycompany.com/health
# → curl: (60) SSL: no alternative certificate subject name found
```

---

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `SSL pinning verification failed` | Сертификат сервера не совпадает с пином | Обновите пины при перевыпуске сертификата; добавьте backup pins |
| `SSL peer certificate or SSH remote key was not OK` | Сертификат CA не в trust store | Добавьте CA-сертификат в trust store приложения |
| Lockout после перевыпуска | Не был добавлен backup pin перед ротацией | Всегда добавляйте backup pin минимум за 10 дней до ротации |
| Corporate proxy failure | Прокси подменяет сертификат | Используйте pinning только для внешних сервисов; для корпоративных — отдельный trust store |

---

## Лучшие практики

### Ротация сертификатов и пинов

**Чек-лист перед ротацией:**

1. **Подготовьте backup-ключ** — минимум за 10–14 дней до плановой ротации
2. **Добавьте backup-пин в конфигурацию клиента** — оба пина (текущий + backup) должны быть активны
3. **Дождитесь распространения** — подождите, пока все клиентские приложения получат обновлённый конфигурационный файл
4. **Перевыпустите сертификат** с новым ключом (или с тем же ключом, если используется SPKI-пиннинг)
5. **Убедитесь, что backup-пин работает** — проверьте, что трафик идёт через новый сертификат
6. **Через 30 дней уберите старый пин** — если всё работает стабильно

### Мониторинг

- **Логи клиентских приложений:** отслеживайте ошибки SSL pinning verification failed
- **Health check endpoints:** используйте `--pinnedpubkey` в curl для smoke-тестов в CI/CD
- **Алертинг:** настройте алерт на >1% ошибок пиннинга в течение 5-минутного окна
- **CT логи:** используйте `crt.sh` или `GoCT` для мониторинга нелегитимных выпусков сертификатов

### Таблица рекомендаций

| Подход | Статус | Рекомендация |
| :--- | :--- | :--- |
| HPKP (RFC 7469) | Устарел, удалён из браузеров | Не использовать |
| Expect-CT | Устарел | Не использовать |
| CT Log Requirement | Активен (Chrome, Firefox) | Обязателен для public CA |
| Public Key Pinning (mobile/API) | Активен | Рекомендуется для мобильных приложений и API-клиентов |
| Application-level Pinning | Активен | Рекомендуется для кастомных клиентов |

### Общие рекомендации

1. **Используйте пиннинг по публичному ключу (SPKI)**, а не по всему сертификату — это позволяет перевыпускать сертификат без обновления пинов
2. **Всегда добавляйте backup pin** — минимум 2 пина, один из которых ещё не используется
3. **Не пините все домены** — пиньте только критичные эндпоинты (API, аутентификация)
4. **Для веб-сайтов:** используйте CT-требования вместо HPKP (deprecated)
5. **Для мобильных приложений:** пиннинг обязателен — приложение контролирует trust store
6. **Для внутренних API:** пиннинг + internal CA = двойная защита
7. **Мониторинг:** отслеживайте срок действия backup pins; автоматизируйте обновление

---

## Дополнительная информация

- **RFC 7469** — [HPKP (устарел)](https://datatracker.ietf.org/doc/html/rfc7469)
- **RFC 8446 (Section 4.4.2)** — [CertificateRequest в TLS 1.3](https://datatracker.ietf.org/doc/html/rfc8446)
- **RFC 6962** — [Certificate Transparency](https://datatracker.ietf.org/doc/html/rfc6962)
- **[Certificate Transparency](./certificate_transparency.md)** — замена HPKP для публичных CA
- **[Обзор PKI](./pki_overview.md)** — базовые понятия PKI
- **[WebServers — TLS](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — серверная настройка TLS
- **[mTLS Configuration](../../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)** — взаимная аутентификация