# Web Application Firewall (WAF)

## Definitions

**WAF (Web Application Firewall)** — межсетевой экран прикладного уровня (L7), который фильтрует, мониторит и блокирует HTTP/HTTPS-трафик на основе набора правил, защищая веб-приложения от уязвимостей. Работает на уровне приложения модели OSI, анализируя содержимое запросов и ответов.

См. также обзор [DDoS-атак и многоуровневой защиты](./ddos_overview.md), где WAF выступает одним из слоёв обороны.

## Basic Concepts

### Функции WAF

- **Защита от OWASP Top 10** — SQL Injection ([подробнее](./sql_injection.md)), XSS ([подробнее](./xss_and_csp.md)), CSRF, LFI/RFI, Command Injection.
- **Фильтрация трафика** — проверка HTTP-заголовков, валидация параметров запроса, блокировка вредоносных payloads.
- **Virtual Patching** — быстрая защита от известных уязвимостей без изменения кода приложения. WAF не устраняет уязвимость, но обеспечивает временную защиту до исправления кода.
- **Защита от L7 DDoS** — фильтрация HTTP-флуда, Slowloris и других атак на уровне приложения.

### Типы WAF

| Тип | Развёртывание | Преимущества | Недостатки |
|---|---|---|---|
| **Network-based (Hardware)** | Физические устройства в ЦОД | Высокая производительность | Высокая стоимость, сложность обслуживания |
| **Host-based (Software)** | Модуль на веб-сервере (ModSecurity для Apache/Nginx/Angie) | Гибкость, контроль, низкая стоимость | Нагрузка на сервер, требует настройки |
| **Cloud WAF** | SaaS-решения (CloudFlare WAF, Yandex Cloud WAF, AWS WAF) | Быстрое развёртывание, глобальная защита | Зависимость от провайдера, стоимость |

### Режимы работы

- **Block** — блокировка вредоносных запросов (403 Forbidden).
- **Detect/Log** — логирование без блокировки (для тестирования правил).
- **Challenge** — CAPTCHA, JS-challenge для подозрительных запросов (защита от ботов).

### Архитектура правил ModSecurity (CRS)

Правила CRS организованы по фазам обработки запроса и имеют структуру:

```
SecRule <TARGET> "<OPERATOR> <PATTERN>" "id:<ID>,phase:<PHASE>,<ACTION>,msg:'<MESSAGE>'"
```

- **TARGET** — `REQUEST_COOKIES`, `ARGS`, `REQUEST_BODY`, `RESPONSE_BODY` и др.
- **PHASE** — 1 (request headers), 2 (request body), 3 (response headers), 4 (response body), 5 (logging).
- **ACTION** — `deny`, `pass`, `drop`, `allow`, `redirect`.

## Practical Scenarios

### Kubernetes Ingress с ModSecurity

```yaml
# Включение WAF на уровне Ingress-контроллера
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: protected-app
  annotations:
    nginx.ingress.kubernetes.io/enable-modsecurity: "true"
    nginx.ingress.kubernetes.io/enable-owasp-core-rules: "true"
spec:
  rules:
  - host: app.example.com
    http:
      paths:
      - path: /
        backend:
          service:
            name: app-service
            port:
              number: 80
```

### Правила ModSecurity (CRS)

```apache
# Защита от SQL Injection
SecRule REQUEST_COOKIES|ARGS|XML:/* \
    "@rx (?i:(?:select\s*\*\s*from|(?:delete|drop|truncate)\s+table|union(?:\s+all)?\s*select))" \
    "id:942100,phase:2,deny,status:403,msg:'SQL Injection Attack Detected'"

# Защита от XSS
SecRule REQUEST_COOKIES|ARGS|XML:/* \
    "@rx (?i:<script|javascript:|on\w+\s*=)" \
    "id:941100,phase:2,deny,status:403,msg:'XSS Attack Detected'"
```

### Yandex Cloud WAF — правило блокировки SQLi

```json
{
  "Name": "SQLInjectionProtection",
  "Priority": 1,
  "Statement": {
    "SqliMatchStatement": {
      "FieldToMatch": {
        "Body": {}
      },
      "TextTransformations": [
        {
          "Priority": 0,
          "Type": "URL_DECODE"
        }
      ]
    }
  },
  "Action": {
    "Block": {}
  },
  "VisibilityConfig": {
    "SampledRequestsEnabled": true,
    "CloudWatchMetricsEnabled": true,
    "MetricName": "SQLInjectionRule"
  }
}
```

### Виртуальный патчинг для известной уязвимости

WAF используется как временная мера до исправления кода:

```apache
# Блокировка эксплуатации CVE-202X-XXXX в конкретном endpoint
SecRule REQUEST_URI "@streq /api/vulnerable-endpoint" \
    "id:1000001,phase:1,pass,nolog"
SecRule ARGS "@rx exploit_pattern|cmd_exec" \
    "id:1000002,phase:2,deny,status:403,msg:'Virtual Patch: CVE-202X-XXXX'"
```

Подробные примеры применения WAF как виртуального патча: [SQL Injection](./sql_injection.md#waf-как-виртуальный-патч), [XSS](./xss_and_csp.md#waf-как-виртуальный-патч).

## Additional Information

### Связанные файлы

- [DDoS Overview](./ddos_overview.md) — WAF как слой защиты от L7 DDoS-атак
- [SQL Injection](./sql_injection.md) — защита от SQLi, WAF как виртуальный патч
- [XSS and CSP](./xss_and_csp.md) — защита от XSS, ограничения WAF против DOM-based XSS
- [DoS/DDoS Overview](../../Networking/Concepts/dos_ddos_overview.md) — CDN/WAF для анализа и фильтрации трафика
- [ModSecurity Core Rule Set (CRS)](https://coreruleset.org/)
- [OWASP WAF](https://owasp.org/www-community/Web_Application_Firewall)
- [Yandex Cloud WAF Documentation](https://yandex.cloud/ru/docs/waf/)
