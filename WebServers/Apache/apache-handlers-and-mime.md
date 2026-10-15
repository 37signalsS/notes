# Apache: Handlers, типы MIME, CGI и SSI

**Актуально для:** Apache HTTP Server 2.4.x

---

## Определения

**Handler (обработчик)** — внутренний компонент ядра или модуля Apache HTTP Server, выполняющий фазу генерации контента (content generation hook) в ответ на HTTP-запрос. Обработчик определяет, каким образом формируется тело ответа: прямым чтением файла с диска (`default-handler`), запуском внешнего процесса (`cgi-script`), парсингом серверных вставок (`server-parsed`), выдачей внутренней телеметрии (`server-status`, `server-info`) или проксированием во внешний сервис (`proxy:fcgi://...`).

**MIME-тип (Multipurpose Internet Mail Extensions)** — двухкомпонентный идентификатор формата данных вида `тип/подтип` (например, `text/html`, `application/json`), передаваемый клиенту в заголовке `Content-Type`. Сопоставление расширений файлов, кодировок и типов содержимого выполняется модулем `mod_mime`.

**mod_mime** — базовый модуль Apache, связывающий метаданные запроса (MIME-тип, обработчик, фильтры, язык, кодировку) с расширениями имен запрашиваемых файлов через директивы `AddType`, `AddHandler`, `AddOutputFilter`, `ForceType` и др.

**mod_mime_magic** — модуль определения MIME-типа файла по его внутреннему содержимому (magic numbers), аналогично утилите Unix `file`. Используется как резервный механизм при отсутствии или неизвестном расширении файла.

**mod_cgi и mod_cgid** — модули запуска CGI-скриптов по стандарту RFC 3875 (передача параметров через переменные окружения, передача тела через `stdin`, чтение ответа из `stdout`). `mod_cgi` запускает скрипты прямым вызовом `fork()` из рабочего процесса (применяется только с `mpm_prefork`). `mod_cgid` выносит запуск скриптов в отдельный фоновый процесс-демон через UNIX-сокет (обязателен для многопоточных `mpm_worker` и `mpm_event`).

**mod_include (SSI — Server Side Includes)** — модуль обработки серверных директив вида `<!--#directive parameter="value" -->`, внедренных в текстовые документы. Позволяет динамически включать содержимое файлов, выводить переменные окружения и исполнять условную логику до отправки ответа клиенту.

**mod_actions** — модуль, позволяющий связывать запуск CGI-скриптов с определенными MIME-типами (`Action`) или методами HTTP-запросов (`Script`).

**mod_negotiation** — модуль согласования контента (content negotiation). Предоставляет поддержку карт типов (`type-map`) и механизм `MultiViews`, выбирающий наиболее подходящее представление ресурса на основе заголовков клиента (`Accept`, `Accept-Language`, `Accept-Encoding`).

**suexec (Switch User for Executables)** — бинарный механизм-обертка Apache с битом SUID root, позволяющий выполнять CGI- и SSI-программы от имени непривилегированного пользователя и группы, закрепленных за конкретным виртуальным хостом, а не от системного пользователя веб-сервера (`apache` / `www-data`).

**ScriptAlias** — директива модуля `mod_alias`, транслирующая URL-префикс в каталог файловой системы и автоматически назначающая всем находящимся в нем файлам флаг исполнения CGI (`Options +ExecCGI`) и обработчик `cgi-script`.

---

## Основные концепции

### Конвейер обработки запроса и фаза Handler

Жизненный цикл обработки запроса в Apache 2.4 разбит на строго упорядоченные фазы (hooks). Обработчики и модуль `mod_mime` функционируют на ключевых этапах генерации ответа:

```
Клиентский HTTP-запрос
         │
         ▼
[ URI Translation ] ──> mod_alias / mod_rewrite (сопоставление URL с каталогом ФС)
         │
         ▼
[ Access / AuthNZ ] ──> mod_authz_core, mod_authn_* (проверка авторизации и доступа)
         │
         ▼
[ Type Checking ]   ──> mod_mime (анализ расширений: MIME, Charset, Handler, Filter)
         │              mod_mime_magic (резервный анализ содержимого при необходимости)
         ▼
[ Fixups ]          ──> mod_env, mod_headers (подготовка переменных окружения и заголовков)
         │
         ▼
[ Content Generation] ──> Handler (default-handler, cgi-script, proxy:fcgi, server-status)
         │
         ▼
[ Output Filters ]  ──> mod_deflate, mod_include (сжатие, разбор SSI-тегов)
         │
         ▼
Финальный HTTP-ответ клиенту
```

Если обработчик не задан явно, ядро назначает `default-handler`, который считывает статический файл с диска и отправляет его клиенту через системный вызов ядра (`sendfile` или `read`/`write`).

---

### Таблица стандартных обработчиков Apache

| Обработчик (Handler) | Модуль | Описание и назначение |
|---|---|---|
| `default-handler` | `core` | Отдача статических файлов из файловой системы по умолчанию. |
| `send-as-is` | `mod_asis` | Отдача файла клиенту «как есть», включая сырые HTTP-заголовки из тела файла. |
| `cgi-script` | `mod_cgi` / `mod_cgid` | Запуск файла как независимой CGI-программы. |
| `server-parsed` | `mod_include` | Обработка файла модулем SSI (Server Side Includes). |
| `server-status` | `mod_status` | Генерация страницы текущего состояния и метрик веб-сервера. |
| `server-info` | `mod_info` | Вывод скомпилированных настроек и конфигурации сервера. |
| `balancer-manager` | `mod_proxy_balancer` | Веб-интерфейс динамического управления балансировкой бэкендов. |
| `ldap-status` | `mod_authnz_ldap` | Вывод состояния пула подключений к серверам LDAP. |
| `type-map` | `mod_negotiation` | Чтение файла карты типов для согласования контента. |
| `proxy:fcgi://...` | `mod_proxy_fcgi` | Проксирование запроса во внешний FastCGI-сервер (например, PHP-FPM). |

---

### Различие директив SetHandler, AddHandler, AddType, ForceType и Action

Разграничение этих директив критично для стабильности и безопасности веб-сервера:

| Директива | Область действия | Что делает | Типичный пример |
|---|---|---|---|
| `SetHandler` | Контейнер (`<Location>`, `<Directory>`, `<FilesMatch>`) | Принудительно устанавливает обработчик для **всех** подходящих запросов, независимо от расширений. | `SetHandler "proxy:fcgi://127.0.0.1:9000"` |
| `AddHandler` | По расширению файла | Привязывает расширение файла к конкретному **обработчику** (handler). | `AddHandler cgi-script .cgi .pl` |
| `AddType` | По расширению файла | Связывает расширение файла с **MIME-типом** (генерирует `Content-Type`). | `AddType application/wasm .wasm` |
| `ForceType` | Контейнер (`<Location>`, `<Directory>`, `<FilesMatch>`) | Принудительно задает **MIME-тип** для всех ресурсов контейнера, игнорируя расширения. | `ForceType application/octet-stream` |
| `Action` | По MIME-типу или HTTP-методу (`mod_actions`) | Вызывает указанный CGI-скрипт при обращении к заданному MIME-типу или методу. | `Action image/svg+xml /cgi-bin/svg-processor` |

> [!IMPORTANT]
> Директива `AddType` **не выполняет** код! Если для файла PHP указать только `AddType application/x-httpd-php .php`, Apache лишь выставит заголовок `Content-Type: application/x-httpd-php`, и браузер скачает исходный PHP-файл как вложение. Для выполнения кода необходим обработчик (`SetHandler` на сокет FastCGI или `AddHandler`).

#### Сброс обработчика и MIME-типа

Для отмены ранее унаследованных обработчиков и типов в дочерних контекстах используются значения `None`:
```apacheconf
# Сброс кастомного обработчика к стандартной отдаче файлов:
SetHandler None

# Сброс принудительного MIME-типа к стандартному определению по расширению:
ForceType None
```

---

### Архитектура mod_mime и ловушка множественных расширений (Multiple Extensions Trap)

В Apache HTTP Server файл может иметь несколько расширений, разделенных точками (например, `archive.tar.gz`, `document.ru.html`, `script.php.en`). Модуль `mod_mime` анализирует **все** суффиксы имени файла независимо от их позиции:

- Расширение `.gz` сопоставляется с `AddEncoding x-gzip .gz`.
- Расширение `.ru` сопоставляется с `AddLanguage ru .ru`.
- Расширение `.html` сопоставляется с `AddType text/html .html`.

#### Вектор уязвимости конфигурации с AddHandler / AddType

Если в конфигурации используется:
```apacheconf
# ОПАСНО в каталогах с пользовательской загрузкой файлов
AddHandler cgi-script .cgi
# или устаревшая привязка PHP:
AddHandler php-script .php
```
Злоумышленник, загрузивший файл с именем `payload.php.jpg` или `avatar.cgi.png`, обходит валидацию расширения в веб-приложении (проверяющем только правый суффикс `.jpg`), но Apache находит суффикс `.php` в середине имени и передает файл обработчику скриптов.

#### Безопасная альтернатива в Apache 2.4

Вместо `AddHandler` привязка обработчиков выполняется через строгий регулярный якорь конца строки в `<FilesMatch>`:
```apacheconf
<FilesMatch "\.php$">
    SetHandler "proxy:unix:/run/php-fpm/www.sock|fcgi://localhost"
</FilesMatch>
```

#### Файл mime.types и удаление DefaultType в Apache 2.4

Файл глобальных сопоставлений задается директивой `TypesConfig`:
- В RHEL / Rocky Linux: `/etc/mime.types` (или `conf/mime.types` в ServerRoot).
- В Debian / Ubuntu: `/etc/mime.types` (подключается через `/etc/apache2/mods-available/mime.conf`).

> [!WARNING]
> Директива `DefaultType` (применявшаяся в Apache 2.2 для задания типа при отсутствии сопоставления, например `DefaultType text/plain`) **полностью удалена в Apache 2.4**. Ее наличие в конфигурации приводит к ошибке синтаксиса при старте:
> `AH00526: Syntax error ... Invalid directive 'DefaultType'`.
> В Apache 2.4 для файлов с неизвестным расширением тип не выставляется, либо задается принудительно через `ForceType`. Кодировка по умолчанию для текстовых файлов задается директивой `AddDefaultCharset UTF-8`.

---

### Архитектура CGI: mod_cgi vs mod_cgid в многопоточных MPM

Стандарт Common Gateway Interface (CGI) порождает новый системный процесс на каждый входящий HTTP-запрос. В контексте DevOps/SRE выбор между `mod_cgi` и `mod_cgid` строго привязан к используемому MPM (Multi-Processing Module):

```
       [ mpm_event / mpm_worker ] (Многопоточный процесс)
                   │
                   │ (Передача метаданных через UNIX-сокет ScriptSock)
                   ▼
         [ cgid daemon ] (Выделенный однопоточный процесс-супервизор)
                   │
                   │ fork() + execve()
                   ▼
         [ /var/www/cgi-bin/script.py ] (Исполняемый процесс скрипта)
```

1. **`mod_cgi` (только для `mpm_prefork`):**
   - Вызывает `fork()` и `execve()` непосредственно из рабочего процесса Apache.
   - В многопоточных процессах (`worker`, `event`) системный вызов `fork()` дублирует дескрипторы сокетов всех потоков, вызывает проблемы синхронизации в библиотеках ядра и приводит к деградации производительности. Поэтому `mod_cgi` несовместим с многопоточными MPM.

2. **`mod_cgid` (обязателен для `mpm_worker` и `mpm_event`):**
   - При запуске Apache стартует выделенный процесс-демон `cgid`.
   - Рабочие потоки MPM передают дескрипторы клиентских соединений и переменные окружения демону `cgid` через UNIX-сокет, задаваемый директивой `ScriptSock`.
   - Демон `cgid` изолированно выполняет `fork()` и `execve()`, возвращая результат потокам Apache.

#### Ограничение ресурсов и защита от атак типа «отказ в обслуживании» (DoS)

Процессы CGI уязвимы к утечкам памяти и зависаниям. Для изоляции на уровне ядра используются директивы Apache:
- `CGIDScriptTimeout 30` — максимальное время ожидания ответа от процесса CGI модулем `mod_cgid` (по умолчанию 60 секунд).
- `RLimitCPU 10 20` — лимит процессорного времени (soft 10с, hard 20с per process).
- `RLimitMEM 67108864 104857600` — лимит оперативной памяти (soft 64MB, hard 100MB per process).
- `RLimitNPROC 16 32` — максимальное количество параллельных дочерних процессов.

---

### SSI (Server Side Includes) и разграничение прав (IncludesNOEXEC)

Модуль `mod_include` с обработчиком `server-parsed` предоставляет теги динамической генерации:
- Вставка файлов: `<!--#include virtual="/fragments/header.html" -->`
- Переменные: `<!--#echo var="REMOTE_ADDR" -->`, `<!--#echo var="DATE_LOCAL" -->`
- Условные блоки: `<!--#if expr="..." --> ... <!--#endif -->`
- Выполнение команд операционной системы: `<!--#exec cmd="uptime" -->` или `<!--#exec cgi="/cgi-bin/stats.cgi" -->`

> [!CAUTION]
> Тег `<!--#exec cmd="..." -->` предоставляет любому пользователю, имеющему право редактировать `.shtml` файлы, возможность исполнения произвольного кода (RCE) на сервере с привилегиями веб-сервера.
> В продакшене разрешается использовать исключительно `Options +IncludesNOEXEC` — эта опция оставляет доступными включения `#include` и переменные `#echo`, но полностью блокирует директиву `#exec`.

---

### Согласование контента (mod_negotiation) и риски MultiViews

Опция `Options +MultiViews` включает неявный поиск ресурса. Если клиент запрашивает `/reports/monthly`, а файла с таким именем нет, Apache сканирует каталог `/reports/`, находит все файлы с префиксом `monthly.*` (`monthly.html`, `monthly.pdf`, `monthly.json`) и выбирает лучший вариант, сравнивая заголовки клиента `Accept`, `Accept-Language` и `Accept-Encoding` с метаданными из `mod_mime`.

**SRE и Security-риски MultiViews:**
1. **Дисковый I/O Overhead:** на каждый запрос к несуществующему файлу сервер вызывает системный вызов `readdir()` для всего каталога.
2. **Неконтролируемая утечка данных:** если администратор сохранил резервную копию `config.php.bak` или `monthly.pdf.old`, `MultiViews` может отдать резервный файл клиенту при определенных заголовках `Accept`.
3. **Стандарт:** в продакшене `MultiViews` отключается директивой `Options -MultiViews`.

---

## Практические сценарии

### Сценарий 1: Настройка изолированного каталога CGI с mod_cgid

Развертывание CGI-скрипта на Debian/Ubuntu и RHEL с использованием MPM `event` и защитой прав.

1. Конфигурация виртуального хоста:

```apacheconf
# /etc/apache2/conf-available/cgid-isolated.conf
# (для RHEL: /etc/httpd/conf.d/cgid-isolated.conf)

<IfModule cgid_module>
    # Расположение сокета связи с демоном cgid
    ScriptSock /run/apache2/cgisock
    # Таймаут исполнения скрипта (30 секунд)
    CGIDScriptTimeout 30
</IfModule>

# Трансляция URL в выделенный каталог вне DocumentRoot
ScriptAlias /cgi-bin/ "/var/www/cgi-bin/"

<Directory "/var/www/cgi-bin">
    AllowOverride None
    Options +ExecCGI -Indexes -Includes
    Require all granted

    # Ограничение ресурсов процесса для предотвращения исчерпания памяти/CPU
    RLimitCPU 15 30
    RLimitMEM 67108864 134217728
</Directory>
```

2. Создание каталога и тестового Python-скрипта:

```bash
sudo mkdir -p /var/www/cgi-bin
sudo chown root:root /var/www/cgi-bin
sudo chmod 755 /var/www/cgi-bin

cat <<'EOF' | sudo tee /var/www/cgi-bin/status.py
#!/usr/bin/env python3
import os
import sys
import json
import datetime

response_data = {
    "status": "healthy",
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "remote_addr": os.environ.get("REMOTE_ADDR", "unknown"),
    "request_method": os.environ.get("REQUEST_METHOD", "GET"),
    "server_protocol": os.environ.get("SERVER_PROTOCOL", "HTTP/1.1")
}

sys.stdout.write("Content-Type: application/json\r\n")
sys.stdout.write("Cache-Control: no-cache, no-store\r\n\r\n")
sys.stdout.write(json.dumps(response_data, indent=2) + "\n")
EOF

sudo chmod 755 /var/www/cgi-bin/status.py
```

3. Проверка доступности:

```bash
curl -sI http://localhost/cgi-bin/status.py
# → HTTP/1.1 200 OK
# → Content-Type: application/json
# → Cache-Control: no-cache, no-store

curl -s http://localhost/cgi-bin/status.py
# → {
# →   "status": "healthy",
# →   "timestamp": "2026-10-14T15:42:10.123456+00:00",
# →   "remote_addr": "127.0.0.1",
# →   "request_method": "GET",
# →   "server_protocol": "HTTP/1.1"
# → }
```

---

### Сценарий 2: Защита каталогов загрузок (Upload Hardening)

Полная изоляция каталога пользовательских файлов от исполнения любых обработчиков и скриптов.

```apacheconf
# /etc/httpd/conf.d/secure-uploads.conf или /etc/apache2/conf-available/secure-uploads.conf
<Directory "/var/www/html/uploads">
    # Запрет выполнения скриптов, серверных вставок и листинга
    Options -ExecCGI -Includes -Indexes -FollowSymLinks
    AllowOverride None

    # Принудительно отдавать всё содержимое только через базовый файловый обработчик
    SetHandler default-handler

    # Предотвращение передачи скриптов в PHP-FPM или CGI
    <FilesMatch "\.(php|phtml|php3|php4|php5|php7|php8|phps|cgi|pl|py|sh|bash)$">
        Require all denied
    </FilesMatch>

    # Защита от исполнения HTML с XSS: принудительная отдача как бинарный поток или текст
    <FilesMatch "\.(html|htm|svg|xml)$">
        ForceType application/octet-stream
        Header set Content-Disposition "attachment"
    </FilesMatch>
</Directory>
```

Проверка защиты загруженного php-файла:

```bash
curl -sI http://localhost/uploads/test.php
# → HTTP/1.1 403 Forbidden
```

---

### Сценарий 3: Безопасный SSI без риска RCE (IncludesNOEXEC)

Включение сборки HTML-страниц из шаблонов с блокировкой системных вызовов.

```apacheconf
# Включение модуля mod_include
# Debian/Ubuntu: sudo a2enmod include
# RHEL: LoadModule include_module modules/mod_include.so

<Directory "/var/www/html/site">
    # Разрешить SSI, но строго ЗАПРЕТИТЬ выполнение команд через <!--#exec -->
    Options +IncludesNOEXEC -ExecCGI
    AllowOverride None

    # Назначение обработчика SSI по расширению
    AddType text/html .shtml
    AddOutputFilter INCLUDES .shtml

    Require all granted
</Directory>
```

Файл `/var/www/html/site/index.shtml`:
```html
<!DOCTYPE html>
<html lang="ru">
<head><title>SSI Page</title></head>
<body>
    <!-- Безопасные директивы: работают штатно -->
    <!--#echo var="DATE_LOCAL" -->
    <!--#include virtual="/fragments/footer.html" -->

    <!-- Опасная директива exec cmd: заблокирована на уровне Apache -->
    <!--#exec cmd="cat /etc/passwd" -->
</body>
</html>
```

Проверка результата:
```bash
curl -s http://localhost/site/index.shtml | grep -E "passwd|error"
# → [an error occurred while processing this directive]
```
В журнал ошибок `error_log` будет записано:
```
[include:error] [pid 1234] [client 127.0.0.1:45678] AH01374: exec used but not allowed in /var/www/html/site/index.shtml
```

---

### Сценарий 4: Кастомные MIME-типы, WebAssembly, современные шрифты и принудительное скачивание

Регистрация типов для современного статического фронтенда и закрытие утечек секретов.

```apacheconf
# Регистрация типов для SPA и WebAssembly
AddType application/wasm .wasm
AddType font/woff2 .woff2
AddType application/manifest+json .webmanifest
AddType text/markdown .md

# UTF-8 кодировка для всех текстовых ответов
AddCharset UTF-8 .html .css .js .json .xml .md

# Защита от случайной утечки приватных ключей, сертификатов и дампов баз данных:
<FilesMatch "\.(pem|key|crt|csr|p12|sql|dump|env|ini)$">
    # Принудительно выставить тип бинарного потока
    ForceType application/octet-stream
    # Указать браузеру скачивать файл, а не отображать его содержимое
    Header set Content-Disposition "attachment"
    # Запретить кеширование конфиденциальных объектов
    Header set Cache-Control "no-store, no-cache, must-revalidate"
</FilesMatch>
```

Проверка заголовков ответа:
```bash
curl -sI http://localhost/app/engine.wasm
# → HTTP/1.1 200 OK
# → Content-Type: application/wasm

curl -sI http://localhost/certs/public.crt
# → HTTP/1.1 200 OK
# → Content-Type: application/octet-stream
# → Content-Disposition: attachment
```

---

### Сценарий 5: mod_actions — вызов кастомного конвертера по типу файла

Использование директивы `Action` для автоматической обработки определенных форматов файлов внешним обработчиком:

```apacheconf
# Требуется: mod_actions, mod_alias, mod_cgid
<IfModule actions_module>
    # Регистрация MIME-типа для документов Markdown
    AddType text/x-markdown .md

    # Привязка типа к виртуальному обработчику-скрипту
    Action text/x-markdown /cgi-bin/md-renderer.py
</IfModule>
```

При обращении к `http://localhost/docs/readme.md` Apache автоматически передает путь к файлу в переменную `PATH_TRANSLATED` скрипта `/var/www/cgi-bin/md-renderer.py`, который генерирует готовый HTML.

---

### Сценарий 6: SRE-телеметрия — логирование Handler и Content-Type

Для диагностики маршрутизации запросов в `LogFormat` добавляются директивы логирования имени назначенного обработчика (`%{handler}n`) и итогового типа (`%{Content-Type}o`):

```apacheconf
# /etc/apache2/conf-available/debug-log.conf или /etc/httpd/conf.d/debug-log.conf
LogFormat "%h %l %u %t \"%r\" %>s %b \"handler:%{handler}n\" \"type:%{Content-Type}o\" %D" handler_debug

CustomLog ${APACHE_LOG_DIR}/handler_access.log handler_debug
```

Пример вывода в логе:
```
127.0.0.1 - - [14/Oct/2026:15:45:01 +0000] "GET /index.html HTTP/1.1" 200 1024 "handler:default-handler" "type:text/html; charset=UTF-8" 450
127.0.0.1 - - [14/Oct/2026:15:45:05 +0000] "GET /api/index.php HTTP/1.1" 200 458 "handler:proxy:fcgi://localhost:9000" "type:application/json" 12400
127.0.0.1 - - [14/Oct/2026:15:45:10 +0000] "GET /cgi-bin/status.py HTTP/1.1" 200 230 "handler:cgi-script" "type:application/json" 8300
```

---

## Операции и команды

### 1. Инспекция загруженных модулей обработчиков

```bash
# Проверка наличия модулей cgi, cgid, mime, include, actions
apachectl -M | grep -iE "cgi|mime|include|actions|negotiation"
# → actions_module (shared)
# → cgid_module (shared)
# → include_module (shared)
# → mime_module (shared)
# → negotiation_module (shared)
```

### 2. Проверка состояния управляющего сокета cgid

В многопоточных MPM демон `cgid` взаимодействует с рабочими процессами через сокет:

```bash
# Поиск сокета в системе (Debian: /run/apache2/, RHEL: /run/httpd/)
ls -la /run/apache2/cgisock* /run/httpd/cgisock* 2>/dev/null
# → srwx------ 1 www-data www-data 0 Oct 14 15:30 /run/apache2/cgisock.1234
```

Если сокет отсутствует или права не позволяют процессам Apache писать в него, выполнение CGI завершится ошибкой 503 или 500.

### 3. Проверка параметров suexec

```bash
# Вывод скомпилированных путей и ограничений suexec
/usr/lib/apache2/suexec -V 2>/dev/null || /usr/sbin/suexec -V
# → -D AP_DOC_ROOT="/var/www"
# → -D AP_GID_MIN=100
# → -D AP_HTTPD_USER="www-data"
# → -D AP_LOG_EXEC="/var/log/apache2/suexec.log"
# → -D AP_SAFE_PATH="/usr/local/bin:/usr/bin:/bin"
# → -D AP_UID_MIN=100
```

### 4. Включение детальной трассировки обработчиков (Debug Logging)

Для отладки выбора MIME-типов и обработчиков без перезапуска сервера с перекомпиляцией:

```apacheconf
# В контексте конкретного VirtualHost или каталога:
LogLevel mime:trace4 negotiation:trace4 include:trace4 cgid:trace4
```

Просмотр лога в реальном времени:
```bash
tail -f /var/log/apache2/error.log | grep -E "mod_mime|mod_cgid"
# → [mime:trace4] mod_mime.c(982): [client 127.0.0.1:51234] mod_mime: matched extension '.wasm' to type 'application/wasm'
# → [cgid:trace3] mod_cgid.c(450): [client 127.0.0.1:51234] sending script to cgid daemon
```

---

## Устранение неполадок

| Симптом | Первопричина | Метод диагностики | Способ устранения |
|---|---|---|---|
| Файл скрипта (`.php`, `.py`, `.cgi`) скачивается как файл вместо выполнения | Файл привязан только через `AddType`, а не `SetHandler`/`AddHandler`, либо не задана опция `Options +ExecCGI` | `curl -sI http://localhost/test.php` (возвращает `Content-Type: application/x-httpd-php` вместо выполнения) | Задать `SetHandler "proxy:fcgi://..."` для PHP или `SetHandler cgi-script` + `Options +ExecCGI` для CGI. |
| `500 Internal Server Error: End of script output before headers` | 1. Скрипт не вывел заголовок `Content-Type:` с последующей пустой строкой `\n\n`.<br>2. Ошибки синтаксиса скрипта или неверный шебанг `#!/...`.<br>3. Переносы строк Windows CRLF (`\r\n`) в файле скрипта. | `tail -n 20 /var/log/apache2/error.log`<br>Ручной запуск скрипта в терминале: `./script.cgi` | 1. Добавить `echo "Content-Type: text/plain\n\n"`.<br>2. Исправить шебанг на `#!/bin/sh` или `#!/usr/bin/env python3`.<br>3. `dos2unix script.cgi`. |
| `403 Forbidden: Options ExecCGI is off in this directory` | В конфигурации каталога отсутствует `Options +ExecCGI`, либо глобально перекрыто `Options None` | Проверить слияние конфигурации: `apachectl -S` и директивы `<Directory>` | Добавить `Options +ExecCGI` в блок `<Directory>` для целевого пути. |
| `AH01215: (13)Permission denied: exec of '/var/www/cgi-bin/app.cgi' failed` | Отсутствует бит исполнения (`chmod +x`) на файле, либо блокировка SELinux / AppArmor | `ls -l /var/www/cgi-bin/app.cgi`<br>`ls -Z /var/www/cgi-bin/` (для SELinux) | 1. `chmod 755 /var/www/cgi-bin/app.cgi`<br>2. SELinux: `restorecon -Rv /var/www/cgi-bin/` или `chcon -t httpd_sys_script_exec_t /var/www/cgi-bin/app.cgi`. |
| `AH01257: couldn't connect to cgid daemon after multiple attempts` | Не создан сокет `cgid`, либо права на каталог сокета (`/run/apache2/` или `/run/httpd/`) не позволяют запись процессу Apache | `ls -la /run/apache2/cgisock*`<br>Проверка журналов `systemd` | Проверить директиву `ScriptSock` в конфигурации; перезапустить службу (`systemctl restart apache2`). |
| `500 Script timed out` | Скрипт превысил таймаут выполнения (по умолчанию 60 сек или `CGIDScriptTimeout`) | В `error_log`: `Script timed out: /var/www/cgi-bin/heavy.py` | Оптимизировать скрипт или увеличить лимит: `CGIDScriptTimeout 120`. |
| Теги SSI (`<!--#include ... -->`) выводятся в браузер открытым текстом | Файл не прошел через фильтр `INCLUDES` или не назначен обработчик `server-parsed` | `curl -s http://localhost/test.shtml` показывает сырые комментарии | Включить `AddOutputFilter INCLUDES .shtml` и добавить `Options +Includes` (или `+IncludesNOEXEC`). |
| Ошибка синтаксиса при старте: `Invalid directive 'DefaultType'` | Директива `DefaultType` удалена в Apache 2.4 | `apachectl configtest` указывает номер строки в `.conf` | Удалить `DefaultType`. Использовать `ForceType` в нужной секции или `AddDefaultCharset UTF-8`. |
| Уязвимость: файл `image.php.jpg` выполняется как скрипт | Использование небезопасного `AddHandler` или `AddType` при обработке множественных расширений | Попытка запроса файла `test.php.jpg` | Заменить `AddHandler` на строгий блок `<FilesMatch "\.php$">` с директивой `SetHandler`. |
| `MultiViews` отдает неактуальный или неверный файл | Включен `Options +MultiViews`, алгоритм `mod_negotiation` подобрал вариант по заголовку `Accept` | Отключить заголовок `Accept` в запросе: `curl -H "Accept: */*" ...` | Отключить опцию: `Options -MultiViews`. |

---

## Лучшие практики

1. **Строгая привязка обработчиков по концу строки:**
   Никогда не использовать `AddHandler` или `AddType` для динамических скриптов (`.php`, `.cgi`) на публичных веб-ресурсах. Назначать обработчики только через `<FilesMatch "\.php$">` с директивой `SetHandler`.

2. **Защита каталогов загрузок (Zero-Execution Uploads):**
   Во всех каталогах загрузки пользовательского контента явно отключать исполнение:
   ```apacheconf
   <Directory "/var/www/html/storage">
       AllowOverride None
       Options -ExecCGI -Includes -Indexes
       SetHandler default-handler
       Header set X-Content-Type-Options "nosniff"
   </Directory>
   ```

3. **Изоляция CGI от DocumentRoot:**
   Размещать исполняемые CGI-скрипты строго вне корневой папки сайта (`DocumentRoot`). Использовать выделенный `ScriptAlias /cgi-bin/ "/var/www/cgi-bin/"` с закрытым доступом через `.htaccess` (`AllowOverride None`).

4. **Ограничение SSI через IncludesNOEXEC:**
   Если в архитектуре требуется поддержка SSI, использовать флаг `Options +IncludesNOEXEC`, предотвращающий выполнение произвольных команд через тег `<!--#exec -->`.

5. **Обязательное использование mod_cgid в mpm_worker и mpm_event:**
   Не пытаться загружать `mod_cgi` в многопоточных MPM. На серверах с `worker` или `event` использовать только `mod_cgid` с контролем расположения `ScriptSock` в `tmpfs` (`/run/`).

6. **Ограничение ресурсов внешних процессов:**
   Для CGI-скриптов обязательно выставлять квоты ядра `RLimitCPU`, `RLimitMEM`, `RLimitNPROC` и таймаут `CGIDScriptTimeout` для предотвращения истощения пула процессов Apache.

7. **Отключение непредсказуемых модулей в продакшене:**
   Всегда выставлять `Options -MultiViews` и отключать неиспользуемые модули генерации контента (`mod_asis`, `mod_info`, `mod_status` вне мониторинга).

---

## Дополнительная информация

### См. также

*   [Обзор Apache: архитектура и жизненный цикл](./apache_overview.md) — фазы конвейера хуков, настройка `SetHandler proxy:fcgi` для PHP-FPM.
*   [Порядок объединения конфигурационных секций](./apache-config-merge-order.md) — приоритеты и правила слияния директив `SetHandler` в секциях `<Directory>`, `<FilesMatch>` и `<Location>`.
*   [Безопасность и hardening Apache](./apache_hardening.md) — блокировка опасных обработчиков, защита каталогов загрузок и изоляция корневой файловой системы.
*   [Настройка производительности Apache](./apache_performance_tuning.md) — тюнинг MPM `event`/`worker`, сокетов и буферов FastCGI.
*   [Аутентификация и авторизация в Apache](./apache_authentication.md) — ограничение доступа к служебным обработчикам (`server-status`, `balancer-manager`).