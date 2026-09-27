# Apache: Перенаправления и перезапись URL (mod_rewrite, mod_alias)

---

## Определения

**mod_rewrite** — модуль Apache, позволяющий переписывать URL на основе регулярных выражений. Обеспечивает два механизма: внутреннюю перезапись (internal rewrite — URI меняется для обработчика, клиент не видит изменение) и внешнее перенаправление (redirect — клиент получает `3xx` и повторяет запрос на новый адрес).

**mod_alias** — штатный модуль для простых редиректов (`Redirect`, `RedirectMatch`) и сопоставления URL с путями файловой системы (`Alias`, `AliasMatch`). Выполняет ту же задачу, что и mod_rewrite, но без накладных расходов на регулярные выражения.

**RewriteRule** — директива mod_rewrite, описывающая одно правило перезаписи: проверяемый адрес (regexp) и результат (подстановка или действие).

**RewriteCond** — условие, предшествующее RewriteRule. Правило применяется только если все связанные с ним условия истинны.

**RewriteBase** — директива, задающая префикс URL для относительных замен в контексте `.htaccess`/`<Directory>`.

**mod_setenvif** — модуль условного назначения переменных окружения на основе шаблонов в заголовках запроса. Часто используется совместно с mod_rewrite и mod_headers для управления доступом и установки заголовков.

---

## Основные концепции

### Внутренняя перезапись vs внешнее перенаправление

| Механизм | Клиент | HTTP-статус | Когда использовать |
|---|---|---|---|
| Internal rewrite | Не видит изменения, получает содержимое | 200 | Маршрутизация внутри приложения, alias без смены адреса |
| Redirect (`[R]`) | Получает новый адрес и повторяет запрос | 3xx (301/302/303/307/308) | Смена домена, HTTP→HTTPS, удаление старых URL |

### Синтаксис RewriteRule

```
RewriteRule Pattern Substitution [flags]
```

*   **Pattern** — регулярное выражение (PCRE), применяется к URL-path без строки запроса (в контексте сервера), либо к относительному пути (в `<Directory>`/`.htaccess`).
*   **Substitution** — результат замены. Может быть абсолютным URL, относительным путём или `-` (без изменений, для флагов-действий).
*   **Flags** — управляющие модификаторы, разделяются запятыми.

### Ключевые флаги RewriteRule

| Флаг | Действие |
|---|---|
| `R[=301\|302\|...]` | Внешний редирект. Без кода — 302. `[R=301]` — постоянный (для SEO) |
| `L` | Последнее правило в текущем проходе (внутреннее завершение) |
| `END` | Полное завершение всех последующих итераций перезаписи (Apache 2.4.8+). Защита от rewrite-петель |
| `NC` | Регистронезависимое сравнение |
| `NE` | Не кодировать спецсимволы в подстановке (`%20`, `;`) |
| `QSA` | Дописать исходный query-string к новой подстановке |
| `B` | Экранировать обратные ссылки в подстановке |
| `F` | Вернуть 403 Forbidden, без подстановки |
| `G` | Вернуть 410 Gone |
| `P` | Проксировать запрос (proxy). Предпочтительнее mod_proxy |
| `PT` | Передать URL дальше по конвейеру (часто с `Alias`) |
| `CO` | Установить cookie |
| `E=VAR:VAL` | Установить переменную окружения |
| `H=handler` | Принудительно задать обработчик (например, `H=proxy:fcgi://...`) |

**`[L]` vs `[END]`:** `[L]` завершает текущую итерацию, но перезаписанный URL может снова пройти через правила (до 10 итераций, защита от бесконечного цикла). `[END]` останавливает процесс полностью и не даёт повторной обработки — надёжная защита от rewrite-петель.

### RewriteCond — синтаксис и применение

```
RewriteCond TestString CondPattern [flags]
```

*   Условие предшествует правилу; правило выполняется только если верны **все** его `RewriteCond`.
*   Следующий `RewriteRule` «привязан» к столько RewriteCond, сколько стоит непосредственно над ним.
*   `%N` — обратная ссылка на захват из `RewriteCond`; `$N` — из последнего `RewriteRule`.
*   Флаги: `[NC]`, `[OR]` (логическое «или» между условиями — по умолчанию «и»), `[NOCOOKIE]` и др.

**Примеры TestString:** `%{HTTP_HOST}`, `%{REQUEST_URI}`, `%{HTTPS}` (`on`/`off`), `%{REMOTE_ADDR}`, `%{HTTP_USER_AGENT}`, `%{REQUEST_FILENAME}` (путь в ФС), `%{ENV:VAR}` (переменная окружения).

### Взаимодействие mod_rewrite и mod_alias

`Redirect`, `RedirectMatch`, `Alias`, `AliasMatch` из mod_alias обрабатываются в фазе URL-to-filename так же, как серверный mod_rewrite. Для постоянных редиректов **без** regexp приоритетнее `Redirect` (быстрее, проще в аудите):

*   `Redirect` — простой редирект «путь → URL».
*   `RedirectMatch` — редирект с регулярным выражением (аналог доступнее `RewriteRule ... [R=301,L]`).
*   `Alias` — сопоставление URL-префикса каталогу ФС.
*   `AliasMatch` — то же с regexp.

**Правило:** не смешивать `Alias` и `RewriteRule` для одного и того же пути в одном контексте — результат зависит от порядка и фазы обработки. Выбрать один механизм на ресурс.

### Отладка правил

```apacheconf
# Включить trace-логирование mod_rewrite (только на время отладки!)
LogLevel alert rewrite:trace6
```

Повышенный `LogLevel` в продакшене не оставлять — вернуть `LogLevel warn`.

---

## Практические сценарии

### 1. Форсированный HTTPS (HTTP → HTTPS)

```apacheconf
RewriteEngine On
RewriteCond %{HTTPS} off
RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [R=301,L]
```

`^` совпадает с любым путём; `%{REQUEST_URI}` сохраняет исходный путь вместе с query-string.

**Альтернатива без mod_rewrite:**
```apacheconf
<IfModule mod_ssl.c>
    <VirtualHost *:80>
        ServerName example.com
        Redirect permanent / https://example.com/
    </VirtualHost>
</IfModule>
```

### 2. Канонический домен (варианты www / без www)

```apacheconf
# www → без www
RewriteCond %{HTTP_HOST} ^www\.(.+) [NC]
RewriteRule ^(.*)$ http://%1/$1 [R=301,L]

# без www → www
RewriteCond %{HTTP_HOST} !^www\. [NC]
RewriteCond %{HTTP_HOST} ^(.+)$ [NC]
RewriteRule ^(.*)$ http://www.%1/$1 [R=301,L]
```

### 3. Удаление завершающего слэша (кроме директорий)

```apacheconf
RewriteCond %{REQUEST_FILENAME} !-d
RewriteRule ^(.*)/$ /$1 [R=301,L]
```

### 4. Переезд старых URL на новые пути (SEO)

```apacheconf
RedirectMatch 301 ^/old-section/(.*)$ https://example.com/new-section/$1
Redirect 301 /downloads.html https://example.com/files/download
```

### 5. Смена протокола/домена: сохранение query-string

```apacheconf
RewriteRule ^/shop/?$ https://example.com/store [R=301,QSA,L]
# /shop?variant=x → https://example.com/store?variant=x
```

### 6. Блокировка нежелательных клиентов (403)

По User-Agent через SetEnvIf + RewriteCond:

```apacheconf
SetEnvIf User-Agent "AhrefsBot|SemrushBot|curl|wget" bad_client
RewriteCond %{ENV:bad_client} "=1"
RewriteRule ^ - [F,L]
```

### 7. Защита от hotlinking (встраивание изображений с других сайтов)

```apacheconf
RewriteEngine On
RewriteCond %{HTTP_REFERER} !^$
RewriteCond %{HTTP_REFERER} !^https?://(www\.)?example\.com/ [NC]
RewriteRule \.(jpg|jpeg|png|gif|webp|svg)$ - [F,NC]
```

### 8. Страница технического обслуживания (503)

```apacheconf
RewriteEngine On
RewriteCond %{REMOTE_ADDR} !^203\.0\.113\.50$
RewriteRule ^ /maintenance.html [R=503,L]
ErrorDocument 503 /maintenance.html
```

### 9. Условные переменные окружения (mod_setenvif)

```apacheconf
SetEnvIfNoCase User-Agent "^Googlebot|^Bingbot" search_engine
SetEnvIf Request_URI "\.php$" php_request
Header set X-Request-Tag "php" env=php_request

SetEnvIf Remote_Addr "^127\.0\.0\.1$" internal_monitor
```

Совместно с `Require` (белый список внутренних клиентов):

```apacheconf
SetEnvIf User-Agent "InternalTool" allow_internal
<RequireAll>
    Require all denied
    Require env allow_internal
</RequireAll>
```

### 10. Принудительный обработчик через RewriteRule (FCGI)

```apacheconf
RewriteRule \.php$ - [H=proxy:fcgi://127.0.0.1:9000]
```

---

## Операции и команды

| Команда/проверка | Назначение | Пример вывода |
|---|---|---|
| `httpd -M \| grep rewrite` | Проверка загрузки модуля | `rewrite_module (shared)` |
| `apachectl configtest` | Синтаксическая проверка | `Syntax OK` |
| `curl -I https://example.com/old` | Проверка кода редиректа | `HTTP/1.1 301 Moved Permanently` |
| `curl -s -o /dev/null -w "%{http_code}" URL` | Проверка статуса без тела | `200` |
| `curl -I -L URL` | Проход всех редиректов | `HTTP/1.1 301` → `HTTP/1.1 200` |

**Пример разбора цепочки редиректов:**
```bash
curl -sIL https://example.com/old-path | grep -E "^HTTP|^Location"
# → HTTP/1.1 301 Moved Permanently
# → Location: https://www.example.com/new-path
# → HTTP/1.1 200 OK
```

**Диагностика rewrite-петли:**
```bash
# При LogLevel alert rewrite:trace6 (только на время отладки) воспроизвести запрос
sudo tail -50 /var/log/httpd/error_log | grep -i "looping\|AH03490"
# → [rewrite:trace3] ... AH03482: applying 'QSA' to 'URI'...
# → [rewrite:trace6] ... AH03490: looping ...
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `AH03490: looping...` | Правило зациклено; `[L]` не завершает цепочку | Заменить `[L]` на `[END]` |
| Редирект не срабатывает | Контекст `.htaccess` и `AllowOverride`/`AllowOverrideList` запрещают директивы | Проверить `AllowOverride` и `AllowOverrideList`; `RewriteEngine` в `.htaccess` обязателен |
| `500 Internal Server Error` | Ошибка regexp в RewriteRule; правило в недопустимом контексте | `apachectl configtest`; проверить `error_log` |
| Редирект зацикливается (www↔www) | Противоречивые RewriteCond | Проверить обе ветки условий `[NC]` |
| Query-string теряется | Отсутствует `[QSA]` или подстановка без query | Добавить `[QSA]` или `?` в подстановку |
| `403 Forbidden` для легитимного клиента | Переменная окружения для блока совпадает ложно | Уточнить regexp в SetEnvIf/RewriteCond |
| Спецсимволы `%20`/`;` в URL перекодируются | Подстановочная строка не экранирует | Добавить `[NE]` |

---

## Лучшие практики

1.  `Redirect`/`RedirectMatch` вместо mod_rewrite для статических редиректов — проще, быстрее, читаемее.
2.  Всегда указывать явный код `[R=301]` (или `308` для POST) — поисковики и клиенты запоминают только постоянные редиректы.
3.  Использовать `[END]` вместо `[L]` везде, где правило не должно повторно обрабатываться.
4.  Не смешивать `Alias` и `RewriteRule` на одном пути.
5.  Не оставлять `LogLevel ... rewrite:trace6` в продакшене.
6.  Правила выносить из `.htaccess` в основной конфиг (`AllowOverride None`).
7.  Держать правила под контролем версий (Git/Ansible) как часть конфигурации.

---

## Дополнительная информация

### См. также

*   [Перенаправления и перезапись URI в Nginx](../Nginx/Core/nginx_rewrite_rules_and_try_files.md) — сравнение подходов Nginx (`rewrite`/`return`/`try_files`).
*   [Обзор Apache](./apache_overview.md) — MPM, VirtualHost, модули, контексты конфигурации.
*   [Обзор WAF](../../Security/ApplicationSecurity/waf.md) — защита приложений поверх маршрутизации.