# Apache: Handlers, типы MIME, CGI и SSI

---

## Определения

**Handler (обработчик)** — внутренний компонент Apache, выполняющий запрос и генерирующий ответ: отдача файла (`default-handler`), CGI (`cgi-script`), SSI (`server-parsed`), проксирование (`proxy:...`), `server-status`, `server-info`, `balancer-manager`.

**MIME-тип** — идентификатор `type/subtype` (например `text/html`), управляющий тем, как клиент интерпретирует ответ (`Content-Type`). Сопоставление расширений файлов и MIME-типов выполняет `mod_mime`.

**mod_mime** — модуль, определяющий, какие директивы (`AddType`, `AddHandler`, `AddOutputFilter`, `ForceType` и др.) привязывают расширения к типам/обработчикам/фильтрам.

**mod_cgi** — модуль исполнения CGI-скриптов (протокол CGI: переменные окружения + stdin/stdout).

**mod_include (SSI)** — модуль, разбирающий серверные включения (`<!--#include ... -->`) в HTML-файлах.

**ScriptAlias** — директива `mod_alias`, сопоставляющая URL-префикс каталогу, в котором все файлы исполняются как CGI.

---

## Основные концепции

### Конвейер обработки запроса

```
Запрос → MIME/Handler mapping (mod_mime) → Фильтры (mod_deflate и др.) → Handler → Ответ
```

Сначала Apache определяет, каким обработчиком обрабатывать запрос (`SetHandler` / `AddHandler` / `AddType`), затем применяет фильтры и вызывает обработчик.

### Различие AddType / AddHandler / SetHandler / ForceType

Классическая путаница на собеседованиях:

| Директива | Что делает | Пример |
|---|---|---|
| `AddType` | Привязывает расширение к **MIME-типу**, создавая Content-Type на выходе | `AddType application/x-javascript .mjs` |
| `AddHandler` | Привязывает расширение к **обработчику** (handler) | `AddHandler cgi-script .cgi` |
| `SetHandler` | Устанавливает обработчик для **всего контейнера** (стандарт Apache 2.4, лучше AddHandler) | `SetHandler proxy:fcgi://127.0.0.1:9000` |
| `ForceType` | Принудительно задаёт MIME-тип для контейнера (полностью переопределяет) | `ForceType application/json` |

`AddType` **не** делает обработчик исполняемым — он лишь меняет `Content-Type`. Отсюда классическая ошибка «файл скачивается вместо исполнения» при попытке обслужить PHP через `AddType application/x-httpd-php .php` без handler.

### Группы директив mod_mime

| Группа | Расширения→ | Пример |
|---|---|---|
| `AddType` | MIME-тип | `AddType text/markdown .md` |
| `AddHandler` | Handler | `AddHandler server-parsed .shtml` |
| `AddOutputFilter` | Фильтр | `AddOutputFilter DEFLATE .html` |
| `AddInputFilter` | Входной фильтр | `AddInputFilter INCLUDE .shtml` |
| `AddCharset` | Кодировка | `AddCharset utf-8 .html .php` |
| `AddDefaultCharset` | Кодировка по умолчанию | `AddDefaultCharset UTF-8` |
| `RemoveType`/`RemoveHandler` | Отмена привязки | `RemoveHandler .php` |

### Multiviews и mod_negotiation

`Options +Multiviews` включает content-negotiation: для запроса `/README` Apache выберет один из файлов `/README.html`, `/README.txt`, `/README.md`, используя заголовки `Accept` клиента. Может выдавать «неожиданные» файлы — в продакшене обычно отключают.

### CGI: модель исполнения

- Скрипт выполняется в отдельном процессе с переменными окружения запроса (`QUERY_STRING`, `CONTENT_TYPE`, `REMOTE_ADDR` и др.).
- Доступ к CGI возможен только через `ScriptAlias`-каталог или при `Options +ExecCGI` в `<Directory>` + привязке `AddHandler cgi-script`.
- Вывод: заголовки, пустая строка, тело. Шаблон `#!/bin/sh`/`#!/usr/bin/env python3` обязателен.

### SSI (Server Side Includes)

HTML-файлы `.shtml` с директивами вида:

```html
<!--#include virtual="/header.html" -->
<!--#echo var="DATE_LOCAL" -->
```

Легковесная замена шаблонизаторам; в современных проектах почти не используется, но сохраняется в legacy-системах. Управляется `mod_include` и `AddHandler server-parsed .shtml`.

---

## Практические сценарии

### 1. Исполнение CGI-скриптов (ScriptAlias)

```apacheconf
LoadModule cgi_module modules/mod_cgi.so
LoadModule alias_module modules/mod_alias.so

ScriptAlias /cgi-bin/ "/var/www/cgi-bin/"
<Directory "/var/www/cgi-bin">
    Options +ExecCGI
    AllowOverride None
    Require all granted
</Directory>
```

```bash
cat > /var/www/cgi-bin/hello.cgi <<'EOF'
#!/bin/sh
echo "Content-Type: text/plain"
echo
echo "Hello CGI"
EOF
chmod +x /var/www/cgi-bin/hello.cgi
```

Проверка:
```bash
curl -i http://localhost/cgi-bin/hello.cgi
# → HTTP/1.1 200 OK
# → Content-Type: text/plain
# → Hello CGI
```

Debian/Ubuntu: `sudo a2enmod cgi`.

### 2. CGI вне ScriptAlias (через AddHandler)

```apacheconf
<Directory "/var/www/html/tools">
    Options +ExecCGI
    AddHandler cgi-script .cgi .pl
    Require all granted
</Directory>
```

### 3. SSI (server-parsed)

```apacheconf
LoadModule include_module modules/mod_include.so
<Directory "/var/www/html">
    Options +Includes
    AddHandler server-parsed .shtml
    Require all granted
</Directory>
```

### 4. Переопределение MIME-типа (AddType)

```apacheconf
AddType text/markdown .md
AddType application/x-javascript .mjs

# JSON-ответ для всего каталога:
<Directory "/var/www/json">
    ForceType application/json
</Directory>
```

### 5. Принудительное скачивание файлов

```apacheconf
# .pem/.key не открывать в браузере, а отдавать вложением
<FilesMatch "\.(pem|key|env)$">
    ForceType application/octet-stream
    Header set Content-Disposition "attachment"
</FilesMatch>
```

### 6. Отключение исполнения в опасных каталогах

```apacheconf
<Directory "/var/www/uploads">
    Options -ExecCGI -Includes -Indexes
    RemoveHandler .cgi .php
    RemoveType .php
    AllowOverride None
    Require all granted
</Directory>
```

---

## Операции и команды

```bash
apache2ctl -M | grep -iE "cgi|include|mime"
# → cgi_module (shared), include_module (shared), mime_module (shared)

# Обработчик текущего файла (модуль обязательно загружен)
curl -I http://localhost/cgi-bin/hello.cgi | grep -iE "Content-Type|HTTP"
# → HTTP/1.1 200 OK ; Content-Type: text/plain

# Проверка фактического Content-Type статики
curl -sI http://localhost/file.md | grep -i content-type
# → Content-Type: text/markdown
```

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| Файл скачивается вместо исполнения (PHP/CGI) | Расширение привязано `AddType`, а не `AddHandler`/`SetHandler`; нет `+ExecCGI` | Использовать `AddHandler`/`SetHandler`; включить `ExecCGI` |
| `500 malformed header from script` | Скрипт не выводит `Content-Type` или выводит до пустой строки | Проверить шаблон `#!/...`, вывод заголовков |
| `403 Forbidden` для CGI | Нет `+ExecCGI` или файл вне ScriptAlias-каталога, нет прав `x` | `Options +ExecCGI`, `chmod +x`, проверка прав владельца |
| `SSI`-директивы выводятся текстом | Расширение не привязано к `server-parsed` | `AddHandler server-parsed .shtml` + `Options +Includes` |
| Неверный `Content-Type` для `.js`/`.mjs` | Отсутствует `AddType`/`ForceType` | `AddType application/javascript .js` |
| `Multiviews` отдаёт «не тот» файл | Content-negotiation подобрал вариант по `Accept` | Отключить `Options -Multiviews` |

---

## Лучшие практики

1. Для PHP в 2.4+ использовать `SetHandler "proxy:fcgi://..."` (см. [Обзор Apache](./apache_overview.md)), а не `AddType`/`AddHandler`.
2. CGI/SSI по умолчанию отключать (`Options -ExecCGI -Includes`), включать точечно для конкретных каталогов.
3. CGI-каталоги выносить за пределы DocumentRoot (`ScriptAlias` в `/var/www/cgi-bin`), закрывать `AllowOverride None`.
4. В каталогах загрузок снимать привязки исполнителей (`RemoveHandler`, `RemoveType`) — защита от webshell.
5. `Multiviews` и `ServerSignature` — отключать в продакшене (непредсказуемый контент, утечка версий).
6. MIME-карту держать в одном месте (например `conf.d/mime.conf`) и покрывать тестами (`curl -I` по типовым путям).

---

## Дополнительная информация

### См. также

*   [Обзор Apache: PHP-FPM и обработчики](./apache_overview.md) — `SetHandler proxy:fcgi`, примеры vhost.
*   [Порядок объединения секций](./apache-config-merge-order.md) — как `<FilesMatch>`/`<Location>` взаимодействуют с handlers.
*   [WebDAV (модули настройки)](../../Linux/Networking/Services/webdav/webdav_overview.md) — пример защищённого HTTP-метода каталога.