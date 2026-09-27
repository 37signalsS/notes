# Certificate Pinning — практики привязки сертификатов

## Определения

**Certificate Pinning** — механизм привязки клиента к конкретному сертификату или публичному ключу сервера, минуя стандартную проверку цепочки доверия через CA. Клиент «запоминает» ожидаемый сертификат/ключ и при подключении проверяет соответствие.

**HPKP (HTTP Public Key Pinning, RFC 7469)** — механизм привязки через HTTP-заголовок. **Устарел** (убран из Chrome 72, Firefox 72). Заменён на Expect-CT и Certificate Transparency.

**Expect-CT** — HTTP-заголовок, требующий от сервера включения сертификата в CT-логи. Также **устарел** (Chrome 104).

**Subject Alternative Name (SAN) Pinning** — привязка к конкретному DNS-имени в SAN сертификата (самый распространённый тип на 2026).

**Public Key Pinning** — привязка к публичному ключу (SPKI Hash) вместо всего сертификата. Более гибкий: ключ можно сохранить при перевыпуске сертификата.

**CT (Certificate Transparency) Pinning** — требование, чтобы сертификат был в logged в CT-логах. Де-факто стандарт для public CA (требование Chrome).

---

## Теоретический блок

### Зачем нужен Certificate Pinning

1. **Защита от подмены (MITM):** Даже если компрометирован любой CA в цепочке, поддельный сертификат не пройдёт проверку
2. **Защита от corporate proxy:** Предотвращает инспекцию трафика через корпоративные прокси (если клиент пинит сертификат)
3. **Защита от украденных ключей:** Если украден ключ промежуточного CA, пиннинг ограничивает количество подверженных сервисов

### Типы пиннинга

| Тип | Что привязывается | Гибкость | Использование |
| :--- | :--- | :--- | :--- |
| Leaf Certificate | Весь сертификат | Низкая (при перевыпуске — новый пин) | Простые случаи |
| Public Key (SPKI) | SHA-256 хэш публичного ключа | Средняя (перевыпуск с тем же ключом OK) | Рекомендуется |
| CA Certificate | Сертификат CA | Высокая (вся цепочка) | Корпоративные среды |
| CT Log Entry | Наличие в CT-логе | Высокая | Public CA |

### Архитектура пиннинга

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

### Отказоустойчивость (Backup Pins)

**Backup Pin** — дополнительный публичный ключ, который ещё не используется, но будет использоваться при перевыпуске. Обязателен для предотвращения lockout при компрометации ключа.

**Рекомендация:** Минимум 2 пина — текущий + backup. Backup пин должен обновляться каждые 10–14 дней (по мере ротации ключей).

### Сравнение подходов (2026)

| Подход | Статус | Рекомендация |
| :--- | :--- | :--- |
| HPKP (RFC 7469) | Устарел, удалён из браузеров | Не использовать |
| Expect-CT | Устарел | Не использовать |
| CT Log Requirement | Активен (Chrome, Firefox) | Обязателен для public CA |
| Public Key Pinning (mobile/API) | Активен | Рекомендуется для мобильных приложений и API-клиентов |
| Application-level Pinning | Активен | Рекомендуется для кастомных клиентов |

---

## Практический блок

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
            <pin digest="SHA-256">sRHdihwgkaib1P1gN4U+0UK0LMfZLg==</pin>
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

### Python (requests)

```python
import ssl
import hashlib
import base64
import requests

EXPECTED_PINS = [
    "YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=",
    "sRHdihwgkaib1P1gN4U+0UK0LMfZLg=",
]

class PinningAdapter(requests.adapters.HTTPAdapter):
    def send(self, request, **kwargs):
        connection = super().send(request, **kwargs)
        # В реальном проекте проверяем пин через urllib3
        return connection

session = requests.Session()
session.mount("https://", PinningAdapter())
# Для production используйте ssl_context с verify_callback
```

### Извлечение пина из сертификата

```bash
# Извлечение публичного ключа и вычисление SHA-256 пина
openssl s_client -connect api.mycompany.com:443 -servername api.mycompany.com </dev/null 2>/dev/null \
  | openssl x509 -pubkey -noout \
  | openssl pkey -pubin -outform DER \
  | openssl dgst -sha256 -binary \
  | base64
# → YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=
```

---

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `SSL pinning verification failed` | Сертификат сервера не совпадает с пином | Обновите пины при перевыпуске сертификата; добавьте backup pins |
| `SSL peer certificate or SSH remote key was not OK` | Сертификат CA не в trust store | Добавьте CA-сертификат в trust store приложения |
| Lockout после перевыпуска | Не был добавлен backup pin перед ротацией | Всегда добавляйте backup pin минимум за 10 дней до ротации |
| Corporate proxy failure | Прокси подменяет сертификат | Используйте pinning only для внешних сервисов; для корпоративных — отдельный trust store |

---

## Лучшие практики

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
- **[Certificate Transparency](./certificate_transparency.md)** — замена HPKP для публичных CA
- **[Обзор PKI](./pki_overview.md)** — базовые понятия PKI
- **[Nginx TLS](../../WebServers/Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — серверная настройка TLS
- **[mTLS Configuration](../../WebServers/Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)** — взаимная аутентификация
