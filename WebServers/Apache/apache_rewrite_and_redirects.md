# Apache: Перенаправления и перезапись URL (mod_rewrite, mod_alias)

**Актуально для:** Apache HTTP Server 2.4.x (включая 2.4.58+)

---

## Определения

**mod_rewrite** — модуль веб-сервера Apache, реализующий механизм синтаксического разбора и динамической трансформации входящих URL на основе регулярных выражений PCRE (Perl Compatible Regular Expressions). Поддерживает как внутреннюю перезапись (internal rewrite — изменение URI внутри конвейера обработки без уведомления клиента), так и внешнее перенаправление (redirect — отправка клиенту HTTP-статуса `3xx` с новым адресом в заголовке `Location`).

**mod_alias** — штатный легковесный модуль Apache для сопоставления URL с файловой системой (`Alias`, `AliasMatch`) и выполнения базовых перенаправлений (`Redirect`, `RedirectMatch`). Работает на ранней фазе трансляции URL-to-filename без инициализации механизма правил `mod_rewrite`, обладая минимальными накладными расходами по CPU и памяти.

**RewriteRule** — фундаментальная директива `mod_rewrite`, задающая шаблон проверки URL (`Pattern`), строку или действие замены (`Substitution`) и управляющие модификаторы (`flags`).

**RewriteCond** — директива предварительного условия, привязанная к последующему `RewriteRule`. Правило исполняется только при истинности всех (или группы по `[OR]`) предшествующих условий.

**RewriteBase** — директива контекста каталога (`<Directory>`, `.htaccess`), явно задающая базовый URL-префикс для относительных подстановок при внутренней перезаписи.

**RewriteMap** — высокопроизводительный механизм внешних таблиц подстановок (хэш-таблицы DBM, текстовые файлы, внешние скрипты-демоны, внутренние функции Apache), обеспечивающий поиск соответствий со сложностью $O(1)$ для тысяч URL без разрастания списка правил.

**FallbackResource** — директива модуля `mod_dir`, задающая единую точку входа (Front Controller) для несуществующих URI. В Apache 2.4 выступает более производительной и стабильной заменой типовых правил `mod_rewrite` для Single Page Applications (SPA).

**RewriteOptions** — директива конфигурации глобального поведения движка перезаписи (например, наследование правил между контекстами VirtualHost через `Inherit` или `InheritBefore`).

**mod_setenvif** — модуль условного выставления переменных окружения (`SetEnvIf`, `SetEnvIfNoCase`) на основе заголовков и атрибутов запроса, часто используемый совместно с `mod_rewrite` для списков блокировки и гибкой маршрутизации.

---

## Архитектура и основные концепции

### Внутренняя перезапись vs внешнее перенаправление

Apache разделяет преобразование адресов на два принципиально разных типа:

| Характеристика | Внутренняя перезапись (Internal Rewrite) | Внешнее перенаправление (External Redirect) |
|---|---|---|
| **Видимость клиентом** | Прозрачно: URL в строке браузера не меняется | Заметно: браузер получает заголовок `Location` и обновляет адрес |
| **HTTP-статус ответа** | Статус ответа обработчика (`200 OK`, `404 Not Found` и др.) | Статус семейства `3xx` (`301`, `302`, `307`, `308`) |
| **Сетевые накладные расходы** | Нулевые (обработка в рамках одного TCP/TLS соединения) | Дополнительный round-trip клиента к серверу |
| **Флаг `mod_rewrite`** | По умолчанию (без флага `[R]`) | Флаг `[R]` или `[R=code]` |
| **Типовое применение** | Маршрутизация на Front Controller, сокрытие структуры backend | Смена домена, миграция на HTTPS, канонизация URL |

#### Различия статус-кодов HTTP при внешнем редиректе

*   `301 Moved Permanently` — постоянный редирект с агрессивным кэшированием браузерами. Согласно историческому поведению, POST-запросы могут трансформироваться браузером в GET.
*   `302 Found` — временный редирект без постоянного кэширования (поведение POST → GET аналогично 301).
*   `307 Temporary Redirect` — временный редирект по стандарту HTTP/1.1+, **гарантирующий сохранение исходного HTTP-метода** (POST остается POST) и тела запроса.
*   `308 Permanent Redirect` — постоянный редирект по стандарту RFC 7538, кэшируемый клиентами, с **гарантированным сохранением метода** (POST/PUT). Рекомендуется для API.

### Фазы обработки и контексты: Server vs Per-Directory

Поведение `mod_rewrite` критически зависит от контекста директив:

```
+---------------------------------------------------------------------------------+
| Фаза URL-to-filename (translate_name hook)                                      |
| Контекст: Server Config, <VirtualHost>                                          |
|                                                                                 |
| 1. Входной URI: полный путь от корня сайта (начинается со слэша: /blog/item)    |
| 2. Сопоставление с RewriteRule                                                  |
| 3. Подстановка формирует путь файловой системы или новый URI                    |
+---------------------------------------------------------------------------------+
                                      |
                                      v
+---------------------------------------------------------------------------------+
| Фаза Per-Directory Fixups (fixups hook)                                         |
| Контекст: <Directory "/var/www/site">, .htaccess                               |
|                                                                                 |
| 1. Префикс директории СРЕЗАЕТСЯ: сопоставление идет по относительному пути!     |
|    Пример: URI /blog/item в каталоге /var/www/site/blog сопоставляется как item |
| 2. Требуется Options FollowSymLinks или SymLinksIfOwnerMatch                    |
| 3. После подстановки префикс директории возвращается обратно                    |
| 4. Запускается ВНУТРЕННИЙ ПОДЗАПРОС (Internal Subrequest / Loop)                |
+---------------------------------------------------------------------------------+
```

> [!WARNING]
> Для работы `mod_rewrite` в контексте `<Directory>` или `.htaccess` директива `Options` обязана содержать `FollowSymLinks` либо `SymLinksIfOwnerMatch`. Если опция выключена, Apache блокирует работу модуля и возвращает клиенту ошибку `403 Forbidden` (`AH00670`).

### Цикл итераций в Per-Directory контексте: `[L]` vs `[END]`

В контексте директорий (`<Directory>`, `.htaccess`) после применения правил `mod_rewrite` Apache перезапускает конвейер обработки запроса с новым URI (внутренний подзапрос).

*   **Флаг `[L]` (Last):** останавливает текущий проход по набору правил. Однако при изменении URI ядро Apache инициирует **новый цикл обработки** (Internal Redirect), и весь набор правил вызывается повторно для нового URI. Если правила составлены некорректно, возникает зацикливание, пока не сработает лимит ядра (`LimitInternalRecursion`, по умолчанию 10), возвращая ошибку `500 Internal Server Error` (`AH00124` / `AH03490`).
*   **Флаг `[END]` (появился в Apache 2.4.8):** полностью завершает не только текущий проход, но и **блокирует любые последующие итерации перезаписи** в контексте директории. Является надежным средством предотвращения rewrite-петель при маршрутизации.

### Синтаксис и структура RewriteRule

```apacheconf
RewriteRule Pattern Substitution [flags]
```

*   **Pattern** — регулярное выражение PCRE. В контексте сервера сопоставляется с абсолютным URL-path (начиная со слэша, без строки запроса `?query`). В контексте каталога сопоставляется с относительным путем (без ведущего слэша).
*   **Substitution** — целевой результат:
    *   Абсолютный путь в файловой системе (`/var/www/html/index.php`).
    *   Относительный или абсолютный URL (`/app/index.php`, `https://example.com/target`).
    *   Дефис `-` — означает отсутствие изменения URI (применяется для модификации заголовков, переменных окружения, проксирования или возврата ошибок).
*   **Flags** — модификаторы выполнения (задаются через запятую в квадратных скобках).

### Справочник ключевых флагов RewriteRule

| Флаг | Полное имя | Назначение |
|---|---|---|
| `[R=code]` | Redirect | Внешний редирект клиенту с кодом `301`, `302` (по умолчанию), `307`, `308`. |
| `[L]` | Last | Прекратить выполнение текущего набора правил в данном цикле. |
| `[END]` | End | Завершить процесс перезаписи полностью, предотвратив внутренние перезапуски цикла (Apache 2.4.8+). |
| `[NC]` | No Case | Регистронезависимое сопоставление регулярного выражения. |
| `[QSA]` | Query String Append | Дописать исходную строку запроса (Query String) к новому URI, а не перезаписать ее. |
| `[QSD]` | Query String Discard | Отбросить входящую строку запроса (Apache 2.4.29+). Более явный аналог подстановки со знаком `?` на конце. |
| `[NE]` | No Escape | Не производить автоматическое экранирование спецсимволов (`%20`, `&` и др.) в строке подстановки. |
| `[B]` | Escape Backreferences | Экранировать спецсимволы в обратных ссылках (`$1`, `%1`) перед подстановкой. В Apache 2.4.56+ расширен флагами `[BNE]` (исключение символов) и `[BCTLS]` (экранирование только управляющих символов и пробелов) для защиты от уязвимостей path traversal. |
| `[F]` | Forbidden | Немедленно вернуть HTTP-ответ `403 Forbidden`. |
| `[G]` | Gone | Немедленно вернуть HTTP-ответ `410 Gone` (ресурс удален навсегда). |
| `[P]` | Proxy | Передать запрос через модуль `mod_proxy` на указанный backend URL. |
| `[PT]` | Pass Through | Передать полученный URI дальше по цепочке обработчиков ядра (например, модулям `mod_alias`, `mod_vhost_alias`). |
| `[H=handler]` | Set Handler | Принудительно назначить обработчик запроса (например, `H=proxy:fcgi://127.0.0.1:9000`). |
| `[T=mime-type]`| Set MIME Type | Принудительно установить MIME-тип ответа. |
| `[E=VAR:VAL]` | Set Env | Выставить переменную окружения Apache (`REDIRECT_VAR` в последующих фазах). |
| `[CO=...]` | Set Cookie | Установить HTTP-cookie в заголовке ответа клиенту. |

### RewriteCond: синтаксис и логические операторы

```apacheconf
RewriteCond TestString CondPattern [flags]
```

Директива `RewriteCond` проверяет условие `CondPattern` над переменной `TestString`. Правило `RewriteRule`, находящееся непосредственно под группой `RewriteCond`, выполняется только тогда, когда соблюдены условия.

*   По умолчанию несколько `RewriteCond` объединяются логическим оператором **AND**.
*   Флаг `[OR]` задает оператор **ИЛИ** для следующего условия.
*   Флаг `[NC]` делает проверку `CondPattern` регистронезависимой.
*   Флаг `[NV]` (No Vary) запрещает добавление имени заголовка в заголовок ответа `Vary`.

#### Обратные ссылки (Backreferences)
*   `$1` ... `$9` — захваченные группы круглых скобок из шаблона текущей директивы `RewriteRule`.
*   `%1` ... `%9` — захваченные группы круглых скобок из последнего успешно сработавшего `RewriteCond`.

#### Основные переменные `TestString`
*   `%{HTTP_HOST}` — доменное имя из заголовка `Host`.
*   `%{REQUEST_URI}` — запрашиваемый путь без строки аргументов (например, `/index.html`).
*   `%{QUERY_STRING}` — строка параметров после знака `?`.
*   `%{THE_REQUEST}` — исходная строка HTTP-запроса от клиента целиком (например, `GET /index.html?id=1 HTTP/1.1`). Не декодируется Apache, что критично для фильтрации атак.
*   `%{HTTPS}` — строка `on`, если запрос пришел по TLS/SSL, или `off`.
*   `%{REMOTE_ADDR}` — IP-адрес клиента (или прокси, если не используется `mod_remoteip`).
*   `%{HTTP:Header-Name}` — значение произвольного HTTP-заголовка запроса (например, `%{HTTP:X-Forwarded-Proto}`).
*   `%{REQUEST_FILENAME}` — полный путь к целевому файлу в файловой системе сервера.
*   `%{ENV:variable}` — значение внутренней переменной окружения Apache.

#### Специальные операторы `CondPattern`
*   `-f` — проверяет, что `TestString` существует на диске и является регулярным файлом (`!-f` — не является файлом).
*   `-d` — проверяет, что `TestString` является существующей директорией (`!-d` — не является директорией).
*   `-s` — проверяет, что файл существует и его размер больше нуля.
*   `-l` — проверяет, что объект является символической ссылкой.
*   `-U` — проверяет доступность URL через внутренний тестовый подзапрос (subrequest).
*   `<CondPattern`, `>CondPattern`, `=CondPattern` — лексикографическое сравнение строк.
*   `-eq`, `-ne`, `-lt`, `-le`, `-gt`, `-ge` — целочисленное сравнение.

### Архитектура RewriteMap

При наличии сотен или тысяч статических редиректов (например, после миграции e-commerce или ребрендинга) использование отдельных директив `RewriteRule` недопустимо: каждое правило компилируется в регулярное выражение и последовательно выполняется для каждого запроса, вызывая деградацию производительности CPU по закону $O(N)$.

Директива `RewriteMap` выносит таблицу соответствий во внешнее хранилище с доступом за $O(1)$:

```apacheconf
# Объявляется ТОЛЬКО в контексте сервера или <VirtualHost> (запрещено в .htaccess)
RewriteMap MapName MapType:MapSource
```

#### Типы карт подстановок (`MapType`)
1.  `dbm` — скомпилированная бинарная база данных DBM (Berkeley DB, GDBM или sdbm). Максимально производительный вариант в продакшене. Создается утилитой `httxt2dbm`.
2.  `txt` — плоский текстовый файл с парами `key value`. Apache кэширует его в памяти и автоматически перечитывает при изменении mtime файла, но для больших объемов уступает DBM.
3.  `rnd` — текстовый файл, где значения разделены символом `|`. Позволяет случайно выбирать один из вариантов (балансировка статики, зеркала).
4.  `prg` — внешний демон-процесс (скрипт на Python, Bash, Perl), запущенный от пользователя Apache при старте сервера. Общается через STDIN/STDOUT.
5.  `int` — встроенные внутренние функции ядра: `tolower` (перевод в нижний регистр), `toupper`, `escape` (URL-encode), `unescape`.

### Сравнение mod_alias и mod_rewrite

| Критерий | mod_alias (`Redirect`, `Alias`) | mod_rewrite (`RewriteRule`) |
|---|---|---|
| **Сложность движка** | Минимальная, прямое сопоставление префиксов | Высокая, конечный автомат регулярных выражений |
| **Накладные расходы CPU** | Практически нулевые | Умеренные/высокие при сложных цепочках правил |
| **Условия применения** | Только URL (или regexp в `RedirectMatch`) | Любые параметры HTTP (заголовки, IP, query, cookie) |
| **Внутренние циклы** | Нет (однократная трансляция пути) | Возможны в Per-Directory контексте |
| **Рекомендация SRE** | **Предпочтительно** для типовых перенаправлений | Использовать только при необходимости сложной логики |

> [!IMPORTANT]
> Запрещается смешивать `Alias` и `RewriteRule` для одного и того же URI в пределах одного виртуального хоста. `mod_alias` и `mod_rewrite` выполняются на разных хуках трансляции путей, и порядок их применения может приводить к труднодиагностируемым ошибкам 404.

### Диагностика и логирование в Apache 2.4

В Apache 2.4 директивы `RewriteLog` и `RewriteLogLevel` **полностью удалены**. Трассировка правил осуществляется штатной системой логирования ядра через директиву `LogLevel`:

```apacheconf
# Включается только временно в контексте конкретного VirtualHost!
LogLevel warn rewrite:trace3

# Уровни детализации:
# trace1 — только финальные результаты применения правил
# trace2 — отображение промежуточных шагов разбора и флагов
# trace3 — детальное сопоставление RewriteCond и условий
# trace8 — максимальная детализация, включая состояние PCRE движка
```

---

## Практические сценарии конфигурации

### Подготовка окружения (активация модулей)

Перед применением правил необходимо убедиться, что требуемые модули загружены:

```bash
# Для Debian / Ubuntu:
sudo a2enmod rewrite alias headers setenvif
sudo systemctl reload apache2

# Для RHEL / Rocky Linux / AlmaLinux (проверка в /etc/httpd/conf.modules.d/):
httpd -M | grep -E 'rewrite|alias|headers|setenvif'
# → rewrite_module (shared)
# → alias_module (shared)
# → headers_module (shared)
# → setenvif_module (shared)
```

### Сценарий 1: Канонический редирект HTTP → HTTPS

#### Вариант А: Рекомендуемый эталонный метод через `mod_alias` (Edge/Origin)

Если Apache самостоятельно принимает открытый трафик на порту 80, использование `mod_rewrite` избыточно:

```apacheconf
<VirtualHost *:80>
    ServerName example.com
    ServerAlias www.example.com
    
    # 301 редирект всего входящего трафика на HTTPS с сохранением пути и параметров
    Redirect permanent / https://example.com/
</VirtualHost>

<VirtualHost *:443>
    ServerName example.com
    ServerAlias www.example.com
    
    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/example.com.crt
    SSLCertificateKeyFile /etc/ssl/private/example.com.key
    DocumentRoot /var/www/example.com/html
</VirtualHost>
```

#### Вариант Б: Редирект за Reverse Proxy / Load Balancer (SSL Offloading)

Когда SSL/TLS терминируется на внешнем балансировщике (HAProxy, Nginx, аппаратный шлюз), балансировщик передает трафик на Apache по HTTP (порт 80), добавляя заголовок `X-Forwarded-Proto`:

```apacheconf
<VirtualHost *:80>
    ServerName example.com
    DocumentRoot /var/www/example.com/html

    RewriteEngine On
    # Проверяем протокол, переданный балансировщиком
    RewriteCond %{HTTP:X-Forwarded-Proto} =http [NC]
    RewriteRule ^ https://%{HTTP_HOST}%{REQUEST_URI} [R=301,L]
</VirtualHost>
```

> [!CAUTION]
> Использование проверки `RewriteCond %{HTTPS} off` за балансировщиком с SSL Offloading приведет к **бесконечному циклу редиректов (ERR_TOO_MANY_REDIRECTS)**, так как соединение между балансировщиком и Apache всегда открыто без SSL!

### Сценарий 2: Нормализация домена (Канонизация Host: non-www → www или наоборот)

#### Приведение к виду без www (Canonical Apex Domain)

```apacheconf
<VirtualHost *:443>
    ServerName example.com
    ServerAlias www.example.com
    DocumentRoot /var/www/example.com/html

    RewriteEngine On
    # Если в начале Host присутствует www., перенаправляем на чистый домен
    RewriteCond %{HTTP_HOST} ^www\.(.+)$ [NC]
    RewriteRule ^ https://%1%{REQUEST_URI} [R=301,L]
</VirtualHost>
```

#### Приведение к виду с www

```apacheconf
<VirtualHost *:443>
    ServerName example.com
    ServerAlias www.example.com
    DocumentRoot /var/www/example.com/html

    RewriteEngine On
    RewriteCond %{HTTP_HOST} !^www\. [NC]
    RewriteCond %{HTTP_HOST} ^(.+)$ [NC]
    RewriteRule ^ https://www.%1%{REQUEST_URI} [R=301,L]
</VirtualHost>
```

### Сценарий 3: Маршрутизация для SPA (Single Page Applications: React, Vue, Angular)

В SPA реальных HTML-файлов на диске нет, кроме `/index.html`. Все маршруты приложения (`/dashboard`, `/profile/settings`) должны отдавать `/index.html`, сохраняя при этом прямую отдачу статических ассетов (`.js`, `.css`, картинок).

#### Метод 1: Современный и наиболее производительный (через `FallbackResource`)

```apacheconf
<VirtualHost *:443>
    ServerName app.example.com
    DocumentRoot /var/www/app/dist

    <Directory "/var/www/app/dist">
        Options FollowSymLinks
        AllowOverride None
        Require all granted

        # Если запрошенный URI физически не существует на диске,
        # mod_dir передает управление указанному ресурсу без накладных расходов mod_rewrite
        FallbackResource /index.html
    </Directory>
</VirtualHost>
```

#### Метод 2: Классический подход через `mod_rewrite`

```apacheconf
<Directory "/var/www/app/dist">
    Options FollowSymLinks
    AllowOverride None
    Require all granted

    RewriteEngine On
    RewriteBase /

    # Если запрос указывает на реальный существующий файл — отдаем его напрямую
    RewriteCond %{REQUEST_FILENAME} -f [OR]
    RewriteCond %{REQUEST_FILENAME} -d
    RewriteRule ^ - [L]

    # Все остальные запросы направляем на index.html
    # Флаг [END] предотвращает повторный цикл обработки запроса
    RewriteRule ^ index.html [END]
</Directory>
```

### Сценарий 4: Высокопроизводительные массовые редиректы через `RewriteMap` (DBM)

Сценарий необходим при слиянии сайтов, смене структуры каталогов интернет-магазина или сохранении сотен/тысяч старых адресов для SEO.

#### Шаг 1. Формирование исходного файла соответствий (`/etc/apache2/maps/redirects.txt`)

```text
# Исходный относительный путь <пробел> Целевой абсолютный URL
/old-catalog/item-101.html    https://example.com/products/sensors/temp-101
/old-catalog/item-102.html    https://example.com/products/sensors/temp-102
/about-company.html           https://example.com/company/about
/legacy-pricing               https://example.com/pricing
```

#### Шаг 2. Компиляция в бинарную базу данных DBM

```bash
# Создание бинарного файла хеш-таблицы redirects.map
sudo httxt2dbm -i /etc/apache2/maps/redirects.txt -o /etc/apache2/maps/redirects.map -t dbm

# Проверка корректности прав (пользователь apache/www-data должен иметь право на чтение)
sudo chown root:www-data /etc/apache2/maps/redirects.map
sudo chmod 0640 /etc/apache2/maps/redirects.map
```

#### Шаг 3. Подключение карты в VirtualHost

```apacheconf
# Объявление карты внутри виртуального хоста
RewriteMap urlmap "dbm:/etc/apache2/maps/redirects.map"

<VirtualHost *:443>
    ServerName example.com
    DocumentRoot /var/www/example.com/html

    RewriteEngine On

    # Ищем запрашиваемый URI в карте DBM
    RewriteCond ${urlmap:%{REQUEST_URI}} !=""
    RewriteRule ^ ${urlmap:%{REQUEST_URI}} [R=301,L]
</VirtualHost>
```

### Сценарий 5: Режим технического обслуживания (Maintenance Mode 503)

Сценарий вывода сервиса на регламентные работы с корректным HTTP-кодом `503 Service Unavailable`, заголовком `Retry-After` и исключением для IP-адресов инженеров DevOps/SRE:

```apacheconf
<VirtualHost *:443>
    ServerName app.example.com
    DocumentRoot /var/www/app/public

    RewriteEngine On

    # 1. Проверяем наличие триггерного файла maintenance.enable на диске
    RewriteCond /var/www/app/maintenance.enable -f
    # 2. Исключаем белый список IP инженеров (офис / VPN)
    RewriteCond %{REMOTE_ADDR} !^(198\.51\.100\.25|203\.0\.113\.50)$
    # 3. Исключаем саму страницу техобслуживания и ее статические стили
    RewriteCond %{REQUEST_URI} !\.(css|png|jpg|svg|ico)$ [NC]
    RewriteCond %{REQUEST_URI} !^/maintenance\.html$
    # 4. Возвращаем 503 статус
    RewriteRule ^ - [R=503,L]

    # Обработчик ошибки 503 и заголовок повторной попытки через 5 минут
    ErrorDocument 503 /maintenance.html
    Header always set Retry-After "300" env=REDIRECT_STATUS
</VirtualHost>
```

Включение и выключение режима обслуживания:
```bash
# Включение режима обслуживания:
sudo touch /var/www/app/maintenance.enable

# Выключение режима обслуживания:
sudo rm -f /var/www/app/maintenance.enable
```

### Сценарий 6: Проксирование и маршрутизация API (`mod_proxy` + `mod_rewrite`)

В микросервисной архитектуре `mod_rewrite` с флагом `[P]` позволяет динамически маршрутизировать трафик на внутренние сервисы с модификацией пути:

```apacheconf
<VirtualHost *:443>
    ServerName api.example.com

    RewriteEngine On

    # Проксирование v1 API с удалением префикса /api/v1/ и передачей параметров
    # Запрос /api/v1/users?id=5 -> http://user-service.internal:8080/users?id=5
    RewriteRule ^/api/v1/(.*)$ http://user-service.internal:8080/$1 [P,L]

    # Проксирование сокетов на внутренний FastCGI демон
    RewriteRule ^/legacy-app/(.*\.php)$ - [H=proxy:fcgi://127.0.0.1:9000/var/www/legacy/$1,L]

    # Защита от раскрытия внутренних путей в заголовках ответов
    ProxyPassReverse /api/v1/ http://user-service.internal:8080/
</VirtualHost>
```

### Сценарий 7: Безопасность и защита от атак

#### Предотвращение Open Redirect (уязвимость открытого перенаправления)

Уязвимая конфигурация, позволяющая злоумышленнику использовать сервер для фишинга (`https://example.com/goto?url=https://evil.com`):
```apacheconf
# УЯЗВИМО:
RewriteCond %{QUERY_STRING} url=(.+)
RewriteRule ^/goto$ %1 [R=301,L]
```

Защищенная конфигурация с валидацией только доверенных доменов:
```apacheconf
# БЕЗОПАСНО: разрешаем редиректы только на доверенные внутренние поддомены
RewriteCond %{QUERY_STRING} (?:^|&)url=(https?://([a-zA-Z0-9-]+\.)?example\.com(?:/.*)?) [NC]
RewriteRule ^/goto$ %1 [R=301,QSD,L]

# Если параметр не прошел валидацию — блокируем доступ
RewriteCond %{QUERY_STRING} (?:^|&)url=
RewriteRule ^/goto$ - [F,L]
```

#### Блокировка попыток сканирования и служебных файлов

```apacheconf
RewriteEngine On

# 1. Защита от утечки каталогов систем контроля версий и файлов конфигурации
RewriteRule "(^|/)\.(git|svn|env|aws|ssh)" - [F,L,NC]

# 2. Блокировка попыток Path Traversal и инъекций нулевого байта (%00) через THE_REQUEST
RewriteCond %{THE_REQUEST} "(\.\./|%2e%2e/|%00)" [NC]
RewriteRule ^ - [F,L]

# 3. Блокировка агрессивных уязвимостных сканеров по User-Agent
RewriteCond %{HTTP_USER_AGENT} (sqlmap|nikto|wpscan|acunetix|masscan|nuclei) [NC]
RewriteRule ^ - [F,L]
```

#### Защита от хотлинкинга (Hotlinking Protection)

Защита трафика и предотвращение встраивания медиа-файлов сторонними веб-сайтами:

```apacheconf
RewriteEngine On
RewriteCond %{HTTP_REFERER} !^$
RewriteCond %{HTTP_REFERER} !^https?://([a-zA-Z0-9-]+\.)?example\.com [NC]
RewriteRule \.(jpe?g|png|gif|webp|svg|mp4)$ - [F,NC,L]
```

### Сценарий 8: Манипуляция строкой запроса (Query String)

#### Очистка отслеживающих меток (UTM, Facebook Click ID) с флагом `[QSD]`

```apacheconf
RewriteEngine On

# Если URL содержит fbclid, удаляем строку запроса целиком и отдаем чистый 301
RewriteCond %{QUERY_STRING} (?:^|&)fbclid= [NC]
RewriteRule ^(.*)$ /$1 [R=301,QSD,L]
```

#### Добавление параметров к запросу с флагом `[QSA]`

```apacheconf
# Запрос /search/phones преобразуется в /find.php?type=phones&sort=popular,
# сохраняя при этом любые параметры клиента (например, &page=2)
RewriteRule ^/search/([^/]+)$ /find.php?type=$1&sort=popular [QSA,L]
```

---

## Операции и команды

### Валидация синтаксиса и проверка загрузки модулей

```bash
# 1. Проверка синтаксиса конфигурационных файлов перед перезагрузкой сервиса
sudo apachectl configtest
# → Syntax OK

# Альтернативная команда для RHEL-систем:
sudo httpd -t
# → Syntax OK

# 2. Проверка активности модулей перенаправления
sudo apachectl -M | grep -E 'rewrite|alias'
# → alias_module (shared)
# → rewrite_module (shared)
```

### Применение изменений без разрыва соединений (Zero-Downtime Reload)

```bash
# Грациозная перезагрузка рабочих процессов:
sudo apachectl graceful

# Либо через systemd:
sudo systemctl reload apache2   # Debian/Ubuntu
sudo systemctl reload httpd     # RHEL/Rocky Linux
```

### Тестирование и инспекция цепочек редиректов через cURL

```bash
# 1. Проверка заголовков ответа и кода состояния:
curl -sI https://example.com/old-page | grep -E '^HTTP/|^Location:'
# → HTTP/1.1 301 Moved Permanently
# → Location: https://example.com/new-page

# 2. Трассировка полной цепочки перенаправлений с финальным статусом:
curl -sIL -o /dev/null -w "Chain:\nStatus: %{http_code}\nEffective URL: %{url_effective}\nRedirect Count: %{num_redirects}\n" https://example.com/old-page
# → Chain:
# → Status: 200
# → Effective URL: https://example.com/new-page
# → Redirect Count: 1

# 3. Тестирование с имитацией внешнего SSL-терминатора (X-Forwarded-Proto):
curl -sI -H "X-Forwarded-Proto: http" http://example.com/test | grep Location
# → Location: https://example.com/test
```

### Сборка и обслуживание файлов `RewriteMap`

```bash
# Компиляция текстового файла в формат DBM (sdbm / gdbm):
sudo httxt2dbm -i /etc/apache2/maps/redirects.txt -o /etc/apache2/maps/redirects.map -t dbm

# Проверка создания бинарного файла базы данных:
ls -lh /etc/apache2/maps/redirects.map*
# → -rw-r----- 1 root www-data 4.2M Oct 14 16:50 /etc/apache2/maps/redirects.map.dir
# → -rw-r----- 1 root www-data 8.1M Oct 14 16:50 /etc/apache2/maps/redirects.map.pag
```

### Мониторинг и динамическая отладка правил

```bash
# 1. Временное включение детальной трассировки в VirtualHost (без перезапуска всего сервера):
# Добавить в блок <VirtualHost>: LogLevel warn rewrite:trace4
sudo apachectl graceful

# 2. Просмотр журнала в реальном времени с фильтрацией шагов mod_rewrite:
sudo tail -f /var/log/apache2/error.log | grep -E '\[rewrite:trace[1-8]\]'
# → [rewrite:trace3] [pid 14210] mod_rewrite.c(480): [client 192.0.2.1:41202] applying pattern '^/old/(.*)$' to uri '/old/catalog'
# → [rewrite:trace2] [pid 14210] mod_rewrite.c(480): [client 192.0.2.1:41202] rewrite '/old/catalog' -> '/new/catalog'
# → [rewrite:trace2] [pid 14210] mod_rewrite.c(480): [client 192.0.2.1:41202] explicitly forcing redirect with https://example.com/new/catalog

# 3. Не забудьте вернуть уровень логирования обратно после завершения диагностики!
```

---

## Типичные ошибки и диагностика

| Код ошибки / Симптом | Причина возникновения | Практическое решение |
|---|---|---|
| `AH00124: Request exceeded the limit of 10 internal redirects due to probable configuration error` | Зацикливание правил в контексте `<Directory>` или `.htaccess`. Флаг `[L]` не предотвращает повторный цикл перенаправления. | Заменить флаг `[L]` на `[END]`. Добавить проверки `RewriteCond %{REQUEST_FILENAME} !-f` и `RewriteCond %{ENV:REDIRECT_STATUS} ^$` перед правилом. |
| `AH00670: Options FollowSymLinks or SymLinksIfOwnerMatch is off which implies that RewriteRule directive is forbidden` | В секции `<Directory>` отсутствует обязательная опция безопасности `FollowSymLinks`. Сервер возвращает клиенту ошибку `403 Forbidden`. | Добавить `Options +FollowSymLinks` (или `SymLinksIfOwnerMatch`) в соответствующую секцию `<Directory>`. |
| Бесконечный цикл редиректов браузера: `ERR_TOO_MANY_REDIRECTS` (код 301/302) | Неправильная проверка протокола за Reverse Proxy / Load Balancer. Сервер постоянно шлет редирект на HTTPS, получая от балансировщика запросы по HTTP. | Использовать `RewriteCond %{HTTP:X-Forwarded-Proto} =http [NC]` вместо `RewriteCond %{HTTPS} off`. |
| Изменения в `.htaccess` не дают эффекта | В родительской секции `<Directory>` установлена директива `AllowOverride None`. | Разрешить использование директив перезаписи: `AllowOverride FileInfo Options=FollowSymLinks` (или `AllowOverride All`). |
| Ошибка `404 Not Found` после внутренней перезаписи в подкаталоге | Не задана директива `RewriteBase` в контексте `.htaccess` или `<Directory>`, в результате чего Apache подставляет путь от корня сервера. | Явно указать `RewriteBase /catalog/` перед правилами `RewriteRule`. |
| Клиент получает `500 Internal Server Error` при обращении к `RewriteMap` | Файл карты DBM не существует, поврежден либо у процесса веб-сервера (`www-data`/`apache`) нет прав на чтение файла. | Пересобрать карту через `httxt2dbm` и проверить права доступа (`chmod 0640`, владение группой веб-сервера). |
| Потеря параметров URL (`?param=value`) при перенаправлении | В строке `Substitution` не указан флаг `[QSA]`, а новое правило перезаписывает query-часть. | Добавить флаг `[QSA]` в квадратные скобки `RewriteRule`. |
| Появление артефактов экранирования (`%252F` вместо `/`, `%2520`) | Двойное URL-экранирование подстановки движком `mod_rewrite`. | Использовать флаг `[NE]` (No Escape) в целевом правиле. |

---

## Лучшие практики

### 1. Архитектура и контексты применения
*   **Отказ от `.htaccess` в продакшене:** Выносить все правила перезаписи в конфигурационные файлы виртуальных хостов (`/etc/apache2/sites-available/` или `/etc/httpd/conf.d/`) с обязательной установкой `AllowOverride None`. Это устраняет лишние операции `stat()` на файловой системе для каждого уровня каталогов при каждом запросе.
*   **Использование `mod_alias` вместо `mod_rewrite`:** Если перенаправление является статическим (префикс URL → целевой URL) и не требует анализа параметров или заголовков, всегда использовать `Redirect` или `RedirectMatch`.
*   **`FallbackResource` для SPA:** Использовать директиву `FallbackResource /index.html` вместо громоздких правил `RewriteCond %{REQUEST_FILENAME} !-f ...` для снижения накладных расходов.

### 2. Надежность и производительность
*   **Приоритет флага `[END]` над `[L]`:** В контексте каталогов всегда предпочитать `[END]`, если правило формирует окончательный адрес и не должно участвовать в последующих циклах перезаписи.
*   **Использование `RewriteMap` для больших таблиц:** При наличии более 30-50 статических редиректов компилировать их в бинарный DBM-формат через `httxt2dbm`.
*   **Защита от утечек отладочной информации:** Никогда не оставлять уровни трассировки `LogLevel rewrite:trace1..8` в продакшене. Стандартный рабочий уровень — `LogLevel warn`.

### 3. Безопасность
*   **Защита от Open Redirect:** Никогда не подставлять невалидированные входные параметры из строки запроса (`%{QUERY_STRING}`) или пути (`$1`) напрямую в заголовок `Location` редиректа без проверки регулярным выражением белого списка доменов.
*   **Использование безопасных обратных ссылок `[B]`:** При подстановке пользовательского ввода в пути файловой системы экранировать спецсимволы флагом `[B]` для предотвращения атак обхода каталогов (Path Traversal).
*   **Явное указание кодов статуса:** Всегда явно задавать HTTP-код в правилах перенаправления: `[R=301]` для постоянных изменений структуры сайта, `[R=308]` для API-интерфейсов, сохраняющих методы POST/PUT.

### 4. Автоматизация и управление конфигурацией (IaC)
*   **Контроль версий:** Хранить конфигурации Apache и исходные файлы `RewriteMap` в репозиториях Git.
*   **Автоматизированный pre-reload синтаксический тест:** В скриптах CI/CD и плейбуках Ansible перед вызовом перезагрузки (`systemctl reload`) обязательно выполнять `apachectl configtest`.

---

## Дополнительная информация

### См. также
*   [Обзор веб-сервера Apache](./apache_overview.md) — общая архитектура, MPM, контексты конфигурации и хуки жизненного цикла.
*   [Порядок объединения конфигурационных секций](./apache-config-merge-order.md) — правила наследования и приоритета директив (`<Directory>`, `<Location>`, `<VirtualHost>`).
*   [Продвинутое обратное проксирование Apache](./apache-reverse-proxy-advanced.md) — настройка `mod_proxy`, `ProxyPass`, `ProxyPassReverse` и балансировка.
*   [Тюнинг производительности Apache](./apache_performance_tuning.md) — оптимизация MPM event, KeepAlive и параметров ввода-вывода.
*   [Харденинг веб-сервера Apache](./apache_hardening.md) — комплексные меры безопасности, защита заголовков и изоляция прав.
*   [Перенаправления и перезапись URI в Nginx](../Nginx/Core/nginx_rewrite_rules_and_try_files.md) — сравнительный анализ директив `rewrite`, `return` и `try_files` в Nginx.
*   [Межсетевой экран веб-приложений (WAF)](../../Security/ApplicationSecurity/waf.md) — фильтрация вредоносного трафика на уровне L7.