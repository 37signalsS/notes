# Web Application Firewall (WAF)

## Функции WAF

1. **Защита от OWASP Top 10:**
   - SQL Injection
   - XSS (Cross-Site Scripting)
   - CSRF (Cross-Site Request Forgery)
   - LFI/RFI (Local/Remote File Inclusion)
   - Command Injection

2. **Фильтрация трафика:**
   - Проверка HTTP-заголовков
   - Валидация параметров запроса
   - Блокировка вредоносных payloads

3. **Virtual Patching:**
   - Быстрая защита от известных уязвимостей
   - Без изменения кода приложения

## Типы WAF

**1. Network-based WAF (Hardware):**
- Физические устройства в ЦОД
- Высокая производительность
- Высокая стоимость

**2. Host-based WAF (Software):**
- Установка на сервере
- ModSecurity для Apache/Nginx
- Бесплатные и коммерческие решения

**3. Cloud WAF:**
- SaaS-решения
- CloudFlare WAF
- AWS WAF
- Azure Application Gateway WAF

## Примеры WAF правил

### ModSecurity (CRS - Core Rule Set)

```apache
# Защита от SQL Injection
SecRule REQUEST_COOKIES|REQUEST_COOKIES_NAMES|REQUEST_FILENAME|ARGS_NAMES|ARGS|XML:/* \
    "@rx (?i:(?:select\s*\*\s*from|(?:delete|drop|truncate)\s+table|union(?:\s+all)?\s*select|insert\s+into\s+.+?values))" \
    "id:942100,phase:2,deny,status:403,msg:'SQL Injection Attack Detected'"

# Защита от XSS
SecRule REQUEST_COOKIES|REQUEST_COOKIES_NAMES|REQUEST_FILENAME|ARGS_NAMES|ARGS|XML:/* \
    "@rx (?i:<script|javascript:|on\w+\s*=)" \
    "id:941100,phase:2,deny,status:403,msg:'XSS Attack Detected'"
```

### AWS WAF Rules

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
    "MetricName": "SQLInjectionProtection"
  }
}
```
