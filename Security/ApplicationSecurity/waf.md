# Межсетевой экран веб-приложений (WAF)

**Reliability Score: 10** (SSoT, проверено по актуальным стандартам OWASP и документации вендоров)

## Определение

**WAF (Web Application Firewall)** — специализированный межсетевой экран прикладного уровня (L7), предназначенный для защиты веб-приложений путем фильтрации, мониторинга и блокировки вредоносного HTTP/HTTPS-трафика. В отличие от традиционных файрволов, работающих на уровнях L3/L4, WAF анализирует содержимое пакетов (DPI — Deep Packet Inspection) и понимает логику протокола HTTP.

См. также обзор [DDoS-атак и многоуровневой защиты](./ddos_overview.md), где WAF выступает критическим слоем защиты от атак на бизнес-логику и L7 DDoS.

## Архитектура и принципы работы

### Основные функции

- **Защита от OWASP Top 10** — противодействие наиболее критичным рискам: SQL Injection ([подробнее](./sql_injection.md)), XSS ([подробнее](./xss_and_csp.md)), CSRF, Broken Access Control и другим.
- **Виртуальный патчинг (Virtual Patching)** — оперативное закрытие уязвимостей на уровне WAF до того, как будет исправлен исходный код приложения. Это критично при обнаружении Zero-day уязвимостей.
- **Инспекция SSL/TLS** — дешифрование трафика для анализа полезной нагрузки (payload) и последующее шифрование перед отправкой на бэкенд.
- **Защита от ботов** — идентификация и блокировка вредоносных ботов (сканеры уязвимостей, парсеры контента) при сохранении доступа для легитимных ботов (поисковые системы).
- **Поведенческий анализ** — выявление аномалий в поведении пользователей, которые могут указывать на попытки взлома или мошенничества.

### Модели безопасности

1.  **Отрицательная модель (Negative Security)** — блокирует только то, что явно считается вредоносным (на основе сигнатур). Это стандартный подход для ModSecurity CRS.
    - *Плюсы:* Легкость настройки, меньше ложных срабатываний.
    - *Минусы:* Не защищает от новых, неизвестных атак.
2.  **Положительная модель (Positive Security)** — разрешает только то, что явно описано как легитимное (белые списки, строгая валидация схем JSON/XML).
    - *Плюсы:* Высокий уровень защиты от Zero-day.
    - *Минусы:* Требует глубокого понимания логики приложения и частого обновления правил.

### Типы развертывания

| Тип | Описание | Особенности |
| :--- | :--- | :--- |
| **Cloud WAF (SaaS)** | Облачные решения (CloudFlare, Yandex Cloud WAF, AWS WAF, Akamai) | Быстрый запуск, автоматическое обновление сигнатур, защита от волюметрических DDoS-атак. |
| **Host-based (Software)** | Устанавливается непосредственно на веб-сервер (ModSecurity для Apache/Nginx, Coraza для Caddy) | Минимальная задержка (latency), полный контроль над данными, но нагружает CPU сервера. |
| **Network-based (Hardware)** | Физические или виртуальные устройства (F5 BIG-IP, Citrix ADC) | Высочайшая производительность за счет аппаратного ускорения, высокая стоимость. |
| **Service Mesh / Sidecar** | Интеграция в Kubernetes через Sidecar-контейнеры (Coraza Wasm для Envoy/Istio) | Идеально для микросервисной архитектуры, обеспечивает защиту внутри кластера (East-West traffic). |

## Режимы работы

- **Детектирование (Detection/Log only)** — WAF только логирует подозрительные запросы, не прерывая их. Используется для отладки правил.
- **Блокировка (Prevention/Blocking)** — WAF блокирует запросы (обычно код 403 Forbidden), соответствующие правилам.
- **Интерактивная проверка (Challenge)** — предъявление пользователю CAPTCHA или выполнение JS-скрипта в браузере для подтверждения, что запрос сделан человеком.

## Практические сценарии и конфигурация

### Использование ModSecurity в Kubernetes

ModSecurity остается стандартом де-факто для open-source WAF. В Kubernetes он часто интегрируется через NGINX Ingress Controller.

```yaml
# Фрагмент манифеста Ingress с включенным WAF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: secured-app
  annotations:
    # Включение ModSecurity
    nginx.ingress.kubernetes.io/enable-modsecurity: "true"
    # Использование OWASP Core Rule Set (CRS)
    nginx.ingress.kubernetes.io/enable-owasp-core-rules: "true"
    # Настройка режима работы: DetectionOnly или On (Blocking)
    nginx.ingress.kubernetes.io/modsecurity-snippet: |
      SecRuleEngine On
      SecDefaultAction "phase:1,deny,log,status:403"
spec:
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /
        backend:
          service:
            name: api-service
            port:
              number: 80
```

### Пример правила ModSecurity (CRS)

Структура правила:
`SecRule TARGET "OPERATOR PATTERN" "id:ID,phase:PHASE,ACTION,msg:'MESSAGE'"`

```apache
# Защита от SQL Injection в аргументах и куках
SecRule REQUEST_COOKIES|ARGS|XML:/* \
    "@rx (?i:(?:select\s*\*\s*from|(?:delete|drop|truncate)\s+table|union(?:\s+all)?\s*select))" \
    "id:942100,phase:2,deny,status:403,msg:'SQL Injection Attack Detected'"

# Виртуальный патчинг конкретной уязвимости (например, блокировка Log4Shell)
SecRule REQUEST_LINE|ARGS|REQUEST_HEADERS \
    "@rx \$\{jndi:(?:ldap|rmi|dns|nis|iiop|corba|lds|http):" \
    "id:1000001,phase:2,deny,status:403,msg:'CVE-2021-44228 Log4Shell Attempt'"
```

### Современная альтернатива: Coraza WAF

[Coraza](https://coraza.io/) — это современный WAF на языке Go, совместимый с правилами ModSecurity, но оптимизированный для Cloud Native окружений. Он может работать как библиотека, автономный прокси или Wasm-плагин для Envoy/Istio.

## Ограничения и обход WAF

WAF не является "серебряной пулей". Существуют методы обхода (Evasion Techniques):
- **Кодирование и обфускация:** Использование двойного URL-кодирования, Base64 или специфических кодировок (например, UTF-16).
- **Разделение нагрузки:** Разбиение вредоносного запроса на несколько частей (Chunked transfer encoding), которые WAF может не собрать для анализа.
- **Логические ошибки:** WAF может не понимать контекст приложения, пропуская атаки на бизнес-логику (например, изменение ID заказа в URL).
- **DOM-based XSS:** Атаки, происходящие на стороне клиента, которые серверный WAF не видит.

**Рекомендация:** Используйте WAF как один из уровней защиты в рамках стратегии **Defense-in-Depth**, дополняя его безопасной разработкой (Secure SDLC) и регулярными пентестами.

## Дополнительные материалы

### Внутренние ссылки
- [SQL Injection](./sql_injection.md) — детализация атак и примеры правил.
- [XSS and CSP](./xss_and_csp.md) — защита фронтенда и ограничения WAF.
- [DDoS Overview](./ddos_overview.md) — место WAF в иерархии защиты от DDoS.
- [Firewall Concepts](../../Networking/Concepts/firewall_concepts.md) — сравнение WAF с L3/L4 файрволами и NGFW.

### Внешние ресурсы
- [OWASP ModSecurity Core Rule Set (CRS)](https://coreruleset.org/) — официальный набор правил.
- [OWASP WAF Guide](https://owasp.org/www-community/Web_Application_Firewall) — фундаментальное руководство.
- [Coraza WAF Documentation](https://coraza.io/docs/) — современный подход к WAF.
