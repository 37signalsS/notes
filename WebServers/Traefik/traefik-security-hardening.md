# Security Hardening Traefik: TLS, DDoS, заголовки, аудит

## Определения

**TLS hardening** — ужесточение параметров TLS-рукопожатия: минимальная версия, cipher suites, SNI strict.

**DDoS protection** — защита от распределенных атак отказом в обслуживании на уровне L7/L4.

**Security headers** — HTTP-заголовки, усиливающие безопасность браузера (HSTS, CSP, X-Frame-Options).

**OWASP Top 10** — список критических рисков веб-приложений (2021).

**Security audit** — систематическая проверка конфигурации на уязвимости.

**GeoIP blocking** — ограничение доступа по географическому расположению IP.

**Connection limit** — ограничение одновременных соединений на entrypoint.

## Базовые концепции

### TLS hardening для compliance

Минимальный production стандарт:
- `minVersion: VersionTLS12` (PCI DSS) или `VersionTLS13` (современный)
- Cipher suites: только PFS (Perfect Forward Secrecy)
- `sniStrict: true` — отклонять соединения без SNI

Пример compliant конфигурации:

```yaml
tls:
  options:
    modern:
      minVersion: VersionTLS13
      sniStrict: true
    default:
      minVersion: VersionTLS12
      cipherSuites:
        - TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256
        - TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384
        - TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256
        - TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384
      curvePreferences:
        - CurveP521
        - CurveP384
```

### DDoS protection layers

Traefik защищает от L7 DDoS, но не от volumetric L3/L4:

| Уровень | Защита в Traefik | Дополнительно |
| :--- | :--- | :--- |
| **L7** | RateLimit, InFlightReq, CircuitBreaker | WAF (CrowdSec), CDN |
| **L4** | Ограничение соединений на entrypoint | External LB, DDoS protection service |
| **Volumetric** | Нет | Cloudflare, AWS Shield, GCP Armor |

### Security headers

Обязательные заголовки:

| Заголовок | Назначение | Значение |
| :--- | :--- | :--- |
| **Strict-Transport-Security** | HSTS — принудительный HTTPS | `max-age=31536000; includeSubDomains; preload` |
| **X-Content-Type-Options** | Запрет MIME-sniffing | `nosniff` |
| **X-Frame-Options** | Защита от clickjacking | `DENY` |
| **Content-Security-Policy** | Ограничение источников контента | `default-src 'self'; frame-ancestors 'none'` |
| **Referrer-Policy** | Контроль Referrer заголовка | `strict-origin-when-cross-origin` |
| **Permissions-Policy** | Отключение ненужных API | `geolocation=(), microphone=()` |

### OWASP Top 10: как Traefik помогает

| Риск | Защита в Traefik |
| :--- | :--- |
| **A01:2021 — Broken Access Control** | IPAllowList, BasicAuth, ForwardAuth |
| **A02:2021 — Cryptographic Failures** | TLS Options, ACME, mTLS |
| **A03:2021 — Injection** | WAF (CrowdSec AppSec), security headers |
| **A04:2021 — Insecure Design** | CircuitBreaker, Retry, RateLimit |
| **A05:2021 — Security Misconfiguration** | `api.insecure: false`, dashboard protection |
| **A06:2021 — Vulnerable Components** | Фиксированные версии образа, плагины |
| **A07:2021 — Auth Failures** | ForwardAuth (OAuth2 Proxy, Authelia) |
| **A08:2021 — Data Integrity Failures** | TLS, HSTS, CSP |
| **A09:2021 — Logging Failures** | Access log, JSON формат, интеграция с SIEM |
| **A10:2021 — SSRF** | Ограничение outbound через NetworkPolicy, firewall |

## Практические сценарии

### Сценарий 1: Полный security headers middleware

```yaml
http:
  middlewares:
    secure-headers:
      headers:
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        browserXssFilter: true
        contentTypeNosniff: true
        forceSTSHeader: true
        customFrameOptionsValue: "DENY"
        contentSecurityPolicy: "default-src 'self'; frame-ancestors 'none'; script-src 'self' 'unsafe-inline'"
        referrerPolicy: "strict-origin-when-cross-origin"
        permissionsPolicy: "geolocation=(), microphone=(), camera=()"
        # accessControlAllowOriginList: ["https://app.example.com"]  # CORS если нужно
```

### Сценарий 2: DDoS protection (RateLimit + InFlightReq + CrowdSec)

```yaml
http:
  middlewares:
    ddos-protection:
      chain:
        middlewares:
          - ip-allow-list
          - rate-limit-global
          - inflight-limit
          - crowdsec-waf
  
  middlewares:
    ip-allow-list:
      ipAllowList:
        sourceRange:
          - "10.0.0.0/8"
          - "192.168.0.0/16"
        rejectStatusCode: 404
    
    rate-limit-global:
      rateLimit:
        average: 100
        period: 1s
        burst: 200
        sourceCriterion:
          ipStrategy:
            depth: 1
    
    inflight-limit:
      inFlightReq:
        amount: 100
        sourceCriterion:
          ipStrategy:
            depth: 1
    
    crowdsec-waf:
      plugin:
        crowdsec-bouncer:
          crowdsecLapiUrl: http://crowdsec:8080
          crowdsecLapiKey: "${CROWDSEC_LAPI_KEY}"
          crowdsecAppsecEnabled: true
```

### Сценарий 3: Connection limiting на entrypoint

```yaml
entryPoints:
  websecure:
    address: ":443"
    transport:
      respondingTimeouts:
        readTimeout: 30s
        writeTimeout: 30s
    http:
      maxHeaderBytes: 4096
      # Ограничение на middleware уровне:
  middlewares:
    connection-limit:
      inFlightReq:
        amount: 500  # максимум 500 одновременных запросов
```

### Сценарий 4: Security audit checklist

```yaml
# Проверка конфигурации
[ ] api.insecure: false
[ ] Dashboard защищен BasicAuth/ForwardAuth
[ ] TLS minVersion >= VersionTLS12
[ ] sniStrict: true (если используется SNI)
[ ] Security headers middleware привязан ко всем роутерам
[ ] RateLimit настроен для публичных endpoints
[ ] IPAllowList для админок
[ ] Включен access log в JSON
[ ] Metrics на отдельном порту, не публичном
[ ] Ограничены порты (80, 443, 8080 dashboard только internal)
[ ] Docker socket через proxy (не прямой монтинг)
[ ] Образ Traefik с фиксированной версией
[ ] Секреты не в логах
[ ] ACME staging использован для тестов
[ ] Плагины только из trusted sources
```

### Сценарий 5: mTLS для internal services

```yaml
tls:
  options:
    mtls-internal:
      minVersion: VersionTLS12
      clientAuth:
        caFiles:
          - /etc/traefik/certs/internal-ca.crt
        clientAuthType: RequireAndVerifyClientCert

http:
  routers:
    internal-api:
      rule: Host(`internal.example.com`)
      service: api-service
      entryPoints: [websecure]
      tls:
        options: mtls-internal
      middlewares:
        - pass-client-cert
```

### Сценарий 6: HSTS preload

```yaml
http:
  middlewares:
    hsts-preload:
      headers:
        stsSeconds: 31536000
        stsIncludeSubdomains: true
        stsPreload: true
        forceSTSHeader: true
```

После добавления: submit на https://hstspreload.org/.

## Операции и команды

```bash
# Проверка TLS конфигурации
curl -sv https://app.example.com/ 2>&1 | grep -i "SSL connection"
# → SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384

# Проверка security headers
curl -sI https://app.example.com/ | grep -i "strict-transport\|content-security\|x-frame"
# → Strict-Transport-Security: max-age=31536000; includeSubDomains
# → X-Frame-Options: DENY

# Проверка cipher suites
nmap --script ssl-enum-ciphers -p 443 app.example.com
# → TLSv1.2: 128 bits (ECDHE-RSA-AES128-GCM-SHA256)

# Проверка HSTS
curl -sI https://app.example.com/ | grep -i "strict-transport"
# → Strict-Transport-Security: max-age=31536000; includeSubDomains; preload

# Проверка mTLS
openssl s_client -connect app.example.com:443 -servername app.example.com </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Старый клиент не может подключиться** | `minVersion: VersionTLS13` | Снизьте до VersionTLS12 или отдельный профиль |
| **HSTS не применяется** | `forceSTSHeader: false` или HTTPS не используется | Включите forceSTSHeader, используйте HTTPS |
| **CSP блокирует контент** | Слишком строгий CSP | Настройте `script-src`, `style-src` под ваши нужды |
| **CrowdSec не блокирует** | `forwardedHeadersTrustedIPs` с `0.0.0.0/0` | Узкий список доверенных IP |
| **mTLS отклоняет клиентов** | `clientAuthType: RequireAndVerifyClientCert` без CA | Добавьте CA в `caFiles` или используйте `VerifyClientCertIfGiven` |
| **Утечка sensitive данных в логи** | Access log не фильтрует заголовки | Настройте `accessLog.fields.headers` с `redact`/`drop` |
| **DDoS проходит через rate limit** | Rate limit только на одном инстансе, нет Redis | Добавьте Redis для distributed rate limit |

## Рекомендации

- TLS: `minVersion: VersionTLS12` минимум; для внутренних сервисов можно `VersionTLS13`
- `sniStrict: true` для production
- Security headers: применяйте globally через entrypoint middleware
- RateLimit + InFlightReq + CrowdSec = layered DDoS protection
- mTLS: только для internal services, с понятным CA management
- Access log: JSON формат, фильтруйте Authorization, Cookie, Set-Cookie
- Мониторинг: алерт на 403 от CrowdSec, 429 от RateLimit, 5xx от CB
- Регулярный security audit: раз в квартал проверяйте конфигурацию

## Дополнительная информация

- [TLS Options и mTLS](./traefik-tls-options.md) — cipher suites, SNI, clientAuth
- [Middleware для безопасности](./traefik-middlewares-security.md) — security headers, CORS, auth
- [Traefik + CrowdSec](./traefik-edge-security-waf.md) — WAF, IP banning, AppSec
- [OWASP Top 10](../../Security/Concepts/owasp_top10.md) — обзор рисков
