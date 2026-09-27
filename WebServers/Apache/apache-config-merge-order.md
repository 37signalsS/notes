# Apache: Порядок объединения конфигурационных секций (Merge Order)

---

## Определения

**Merge order (порядок объединения)** — фиксированный порядок, в котором Apache объединяет директивы из разных контейнеров конфигурации (`<Directory>`, `<Location>`, `<Files>`, `<VirtualHost>`, `.htaccess`, `<If>`) при обработке запроса. Результат определяется не порядком строк в файле, а типом и вложенностью секций.

**Прецедентность (precedence)** — правило «позже в порядке объединения — сильнее»: директива из секции более высокого приоритета перекрывает ту же директиву из секции более низкого приоритета.

**Mergeable (сливаемая) директива** — директива, значения которой из родительской секции наследуются и дополняются вложенной (например `Options`), в отличие от директив, которые перекрывают целиком.

**AllowOverride** — директива, управляющая тем, в какой степени `.htaccess` может переопределять директивы основной конфигурации.

---

## Основные концепции

### Фазы обработки запроса

Apache обрабатывает запрос в несколько фаз; секции применяются на разных фазах:

| Фаза | Секции | Ответственность |
|---|---|---|
| Трансляция URL | `<Location>` до `<Directory>`, `Alias`, Redirect | Приведение URL к пути в ФС |
| Сопоставление с ФС | `<Directory>`, `<Files>`, `.htaccess` | Доступ к файлу, права |
| Обработка контента | Handlers (`SetHandler` и др.) | Генерация ответа |

### Полный порядок объединения (Apache 2.4)

1. **Основной конфиг** обрабатывается до секций `<VirtualHost>`; внутри виртуального хоста директивы перекрывают глобальные для того же контекста.
2. **`<Directory>`** (кроме `<Directory />`) и **`.htaccess`** объединяются вместе:
   - секции `<Directory>` обрабатываются от самого короткого пути к самому длинному (наиболее специфичный путь — последним);
   - при нескольких секциях для одного каталога — в порядке появления в конфиге;
   - **`.htaccess` обрабатывается после** всех `<Directory>`-секций (при `AllowOverride`).
3. **`<DirectoryMatch>`** и `<Directory ~>` — после `<Directory>`.
4. **`<Files>`** и `<FilesMatch>` — вместе, в порядке появления в конфиге.
5. **`<Location>`** и `<LocationMatch>` — вместе, в порядке появления (фаза трансляции; применяется до Directory-прав).
6. **`<If>`** и `<IfElse>` — обрабатываются последними (Apache 2.4.4+).
7. Секции `<VirtualHost>` применяются после всех глобальных.

**Итоговое правило:** чем позже секция в этом порядке — тем выше её приоритет. Директива из более поздней секции перекрывает ту же директиву из более ранней.

### Ключевой нюанс

`<Location>` применяется раньше `<Directory>` по фазе, но в merge-порядке идёт после — поэтому при конфликте одного и того же параметра побеждает `<Location>`. Например, `Require all denied` в `<Directory "/var/www">` и `Require all granted` в `<Location "/api">` даст доступ к `/api` независимо от Directory.

### Сливаемые vs перекрывающие директивы

| Тип | Поведение | Примеры |
|---|---|---|
| Mergeable | Наследует значение родителя | `Options` (накапливаются, модификаторы `+`/`-`), `Header` (добавляются) |
| Перекрывающие | Заменяют целиком | `Require`, `ErrorDocument`, `DirectoryIndex`, `AddOutputFilter` |

`Options` — классический пример: если в `<Directory />` задан `Options Indexes FollowSymLinks`, а в `/var/www` — `Options -Indexes`, то `-Indexes` отменяет `Indexes`, остальное наследуется. Для замены всего используется `Options` без модификаторов или `Options none`.

Для `Require` действует «логика первого совпадения» внутри одного контейнера, а между контейнерами — merge-порядок (побеждает самая поздняя секция).

### `.htaccess` и AllowOverride

`.htaccess` — секция, обрабатываемая на уровне каталога после `<Directory>`. Может переопределять только директивы, перечисленные в `AllowOverride` (для 2.4 — группы `All`/`None` или список через `AllowOverrideList`). Вне управления `AllowOverride` — файл игнорируется.

### `<IfModule>` и `<IfDefine>` не влияют на merge-порядок

`<IfModule>`/`<IfDefine>` лишь условно активируют содержимое; сами директивы внутри них участвуют в merge-порядке как обычные, на своих фазах.

---

## Практические сценарии

### 1. `<Location>` перекрывает `<Directory>`

```apacheconf
<Directory "/var/www">
    Require all denied
</Directory>

<Location "/status">
    SetHandler server-status
    Require ip 127.0.0.1
    Require all granted   # <Location> идёт позже — доступ открыт
</Location>
```

### 2. Специфичная Directory перекрывает корневую

```apacheconf
<Directory />
    AllowOverride None
    Require all denied
</Directory>

<Directory "/var/www/html">
    AllowOverride All
    Require all granted
</Directory>
```

### 3. Files поверх Directory для отдельных файлов

```apacheconf
<Directory "/var/www/uploads">
    Require all granted
</Directory>

<FilesMatch "\.(env|sql|bak)$">
    Require all denied
</FilesMatch>
```

`<FilesMatch>` в merge-порядке идёт позже — `.env` закрыт даже внутри разрешённого каталога.

### 4. .htaccess переопределяет Directory

```apacheconf
<Directory "/var/www/html">
    AllowOverride All
    Require all granted
</Directory>
```

```apacheconf
# /var/www/html/.htaccess
Require all denied
Require ip 192.168.1.0/24
```

`.htaccess` обрабатывается после `<Directory>` и отключает доступ вне подсети.

### 5. Диагностика итоговой конфигурации

```bash
apachectl configtest    # → Syntax OK
apachectl -S           # порядок VirtualHost: первый — default
# Проверка того, что конкретная директива применилась (примеры через mod_info)
```

---

## Операции и команды

| Команда/проверка | Назначение |
|---|---|
| `apachectl configtest` | Синтаксическая проверка |
| `apachectl -S` | Порядок VirtualHost (первый совпавший — default) |
| `httpd -M` | Проверка модулей секций (authz_core, info) |
| `curl -I URL` | Проверка фактического кода доступа |

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `403` несмотря на `Require all granted` в `<Directory>` | Внешний `<Directory />`-блок с `Require all denied` обрабатывается раньше/позже неверно или конфликт с `<Location>` | Расставить секции по merge-порядку; проверить, что перекрытие идёт «снизу вверх» |
| Доступ открыт, хотя Directory запрещает | `<Location>`/`<FilesMatch>` с `Require all granted` идёт позже и побеждает | Убрать лишние `Require` или переформулировать секции |
| `Options` ведёт себя «неожиданно» | `Options` в дочернем каталоге накапливается с родительским | Учитывать mergeable-природу; использовать `-` или `Options none` |
| `.htaccess` не работает (директивы игнорируются) | `AllowOverride None` в родительском `<Directory>` | Задать `AllowOverride`/`AllowOverrideList` |
| Пример работает в проде, но не на стенде | Разный порядок секций в файлах (Include) | Следить за `IncludeOptional`-порядком загрузки |

---

## Лучшие практики

1. Не полагаться на merge-магию: держать секции минимально пересекающимися, описывать доступ «сверху вниз» (запрет по умолчанию → точечные разрешения).
2. Запрет по умолчанию (`<Directory />` → `Require all denied`), затем узкие `<Directory>`/`<Location>`-разрешения.
3. Использовать `RequireAny`/`RequireAll`/`RequireNone` для явной логики внутри одной секции.
4. `AllowOverride None` для всех каталогов, кроме реально нужных (см. [Обзор Apache](./apache_overview.md)).
5. При конфликте `<Directory>` и `<Location>` проверять целевую фазу: для авторизации предпочитать `<Directory>`+`<Files>`, для special-handler — `<Location>`.
6. Документировать нестандартные надстройки в комментарии рядом с секцией.

---

## Дополнительная информация

### См. также

*   [Обзор Apache: уровни конфигурации (Scopes)](./apache_overview.md) — контексты `<Directory>`/`<Location>`/`<Files>`/`<VirtualHost>`.
*   [Handlers и типы MIME](./apache-handlers-and-mime.md) — `SetHandler`/`AddHandler`/`ForceType` поверх merge-логики.
*   [Доступ и авторизация (Require)](./apache_authentication.md) — `Require valid-user`, `Require ip`, вложенные контейнеры.