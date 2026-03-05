# Web Application Firewall (WAF)

## Определения

**WAF (Web Application Firewall)** — это межсетевой экран прикладного уровня (L7), который фильтрует, мониторит и блокирует HTTP/HTTPS-трафик на основе набора правил, защищая веб-приложения от уязвимостей.

## Основные концепции

### Функции WAF

1. **Защита от OWASP Top 10:**
    * SQL Injection
    * XSS (Cross-Site Scripting)
    * CSRF (Cross-Site Request Forgery)
    * LFI/RFI (Local/Remote File Inclusion)
    * Command Injection
2. **Фильтрация трафика:**
    * Проверка HTTP-заголовков.
    * Валидация параметров запроса.
    * Блокировка вредоносных payloads.
3. **Virtual Patching:**
    * Быстрая защита от известных уязвимостей без изменения кода приложения.
4. **Защита от DDoS атак уровня L7**.

### Типы WAF

* **Network-based WAF (Hardware):** Физические устройства в ЦОД. Высокая производительность, высокая стоимость.
* **Host-based WAF (Software):** Устанавливается как модуль на веб-сервер (например, ModSecurity для Apache/Nginx/Angie).
* **Cloud WAF:** SaaS-решения, предлагаемые провайдерами (CloudFlare WAF, Yandex Cloud WAF).

## Практические сценарии

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
# Пример правила для защиты от SQL Injection
SecRule REQUEST_COOKIES|ARGS|XML:/* \
    "@rx (?i:(?:select\s*\*\s*from|(?:delete|drop|truncate)\s+table|union(?:\s+all)?\s*select))" \
    "id:942100,phase:2,deny,status:403,msg:'SQL Injection Attack Detected'"

# Пример правила для защиты от XSS
SecRule REQUEST_COOKIES|ARGS|XML:/* \
    "@rx (?i:<script|javascript:|on\w+\s*=)" \
    "id:941100,phase:2,deny,status:403,msg:'XSS Attack Detected'"
```

### Пример правил для Yandex Cloud WAF

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

## Дополнительная информация

* [ModSecurity Core Rule Set (CRS)](https://coreruleset.org/)
* [OWASP WAF](https://owasp.org/www-community/Web_Application_Firewall)
* [Yandex Cloud WAF Documentation](https://yandex.cloud/ru/docs/waf/)
* Связанный файл: [DDoS (Distributed Denial of Service)](./ddos.md)
