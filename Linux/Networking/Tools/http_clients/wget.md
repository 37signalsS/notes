# Wget: Надежное скачивание и зеркалирование

## Определения

**GNU Wget** — утилита командной строки для надежного скачивания файлов и создания локальных зеркал веб-сайтов. Поддерживает протоколы HTTP, HTTPS, FTP. Отличается устойчивостью к разрывам соединения и возможностью работы в фоне.

## Базовые концепции

### 1. Структура команды

```bash
wget [опции] [URL]
```

**Основные группы опций:**

- **Загрузка:** `-O`, `-o`, `-c`, `-b`
- **Рекурсия:** `-r`, `-l`, `-k`, `-p`
- **Аутентификация:** `--user`, `--password`, `--load-cookies`
- **Отладка:** `--debug`, `-v`

### 2. wget vs wget2

| Характеристика | wget | wget2 |
| :--- | :--- | :--- |
| **Многопоточность** | Нет | Да |
| **HTTP/2** | Нет | Да |
| **Поведение при 4xx/5xx** | Возвращает ошибку | Возвращает ошибку (надёжнее) |
| **Статус** | Стабильная версия | Новая версия (развивается) |

> **Примечание:** wget2 — новая версия с поддержкой многопоточности и HTTP/2, но пока менее распространена.

---

## Практические сценарии

### Сценарий 1: Базовая загрузка файла

```bash
# Простая загрузка
wget https://example.com/file.zip

# Загрузка с указанием имени файла
wget -O myfile.zip https://example.com/file.zip

# Продолжение прерванной загрузки
wget -c https://example.com/large-file.zip

# Фоновая загрузка
wget -b https://example.com/large-file.zip
```

### Сценарий 2: Зеркалирование сайта

```bash
# Полное зеркало для офлайн-просмотра
wget -r -l inf -k -p --adjust-extension https://example.com

# С ограничением глубины (3 уровня)
wget -r -l 3 -k -p https://example.com

# С ограничением скорости (100 КБ/с)
wget -r -l inf --limit-rate=100k https://example.com

# Только файлы определённого типа
wget -r -l inf -A.pdf https://example.com
```

**Опции зеркалирования:**

| Опция | Описание |
| :--- | :--- |
| `-r`, `--recursive` | Рекурсивная загрузка |
| `-l <depth>`, `--level=<depth>` | Глубина рекурсии (`inf` — бесконечно) |
| `-k`, `--convert-links` | Преобразовать ссылки для локального просмотра |
| `-p`, `--page-requisites` | Загрузить все ресурсы страницы (CSS, JS, изображения) |
| `--adjust-extension` | Добавлять расширения (.html, .css) к файлам |
| `--limit-rate=<rate>` | Ограничить скорость загрузки |
| `-A <ext>`, `--accept=<ext>` | Загружать только файлы с указанными расширениями |
| `-R <ext>`, `--reject=<ext>` | Исключить файлы с указанными расширениями |

### Сценарий 3: Массовая загрузка файлов

```bash
# Загрузка из списка URL (каждый URL с новой строки)
wget -i urls.txt

# Загрузка с продолжением прерванных файлов
wget -c -i urls.txt

# Загрузка в фоновом режиме
wget -b -i urls.txt
```

### Сценарий 4: Работа с cookies и аутентификацией

```bash
# Basic auth
wget --user=admin --password=secret https://example.com/protected

# Сохранить cookies
wget --save-cookies cookies.txt https://example.com/login

# Загрузить cookies
wget --load-cookies cookies.txt https://example.com/profile

# Использование .netrc (файл ~/.netrc)
# machine example.com login user password pass
wget --netrc https://example.com/protected
```

### Сценарий 5: wget как простой API-клиент

```bash
# GET-запрос с заголовками
wget --header='Accept: application/json' \
     https://api.example.com/users

# POST с данными формы
wget --post-data='name=John&age=30' \
     https://api.example.com/users

# POST с JSON (вручную указываем Content-Type)
wget --header='Content-Type: application/json' \
     --post-data='{"name":"John","age":30}' \
     https://api.example.com/users

# Вывод ответа в stdout
wget -q -O - https://api.example.com/users
```

> **Примечание:** wget менее удобен для API по сравнению с curl и httpie — нет встроенной поддержки multipart/form-data, JSON сериализуется вручную.

### Сценарий 6: Отладка и диагностика

```bash
# Подробный вывод
wget -v https://example.com

# Максимально подробный вывод (debug)
wget --debug https://example.com

# Только проверка доступности (без загрузки)
wget --spider https://example.com/file.zip

# С таймаутом
wget --timeout=10 https://example.com
```

### Сценарий 7: Обход ограничений

```bash
# Подмена User-Agent
wget --user-agent='Mozilla/5.0' https://example.com

# Игнорирование SSL-сертификатов
wget --no-check-certificate https://self-signed.example.com

# Принудительное использование IPv4
wget -4 https://example.com

# Принудительное использование IPv6
wget -6 https://example.com
```

### Сценарий 8: Роботы и этичное скачивание

```bash
# Соблюдать robots.txt (по умолчанию включено)
wget -e robots=on https://example.com

# Игнорировать robots.txt (использовать с осторожностью!)
wget -e robots=off https://example.com

# Задержка между запросами (в секундах)
wget -r --wait=2 https://example.com

# Случайная задержка (от 1 до 3 секунд)
wget -r --random-wait https://example.com
```

---

## Дополнительная информация

### 1. Коды возврата

| Код | Описание |
| :--- | :--- |
| **0** | Успех |
| **1** | Общая ошибка |
| **2** | Ошибка парсинга |
| **3** | Ошибка ввода-вывода |
| **4** | Ошибка сети |
| **5** | Ошибка SSL |
| **6** | Ошибка аутентификации |
| **7** | Ошибка протокола |
| **8** | Сервер вернул ошибку (4xx/5xx) |

### 2. Вывод в stdout

Для передачи вывода wget в конвейер (pipe) используйте `-O -`:

```bash
wget -q -O - https://api.example.com/data | jq .
```

### 3. Скачивание файла с именем `-`

Если файл называется `-`, используйте `./-`:

```bash
wget https://example.com/-
# или
wget https://example.com/./-
```

### 4. Metalink и цифровые подписи

wget поддерживает Metalink-файлы для автоматического выбора зеркал и проверки целостности:

```bash
wget --metalink=file.metalink https://example.com/file.iso
```

### 5. Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie
- **[Инструменты диагностики сети](../network_diagnostics_tools.md)**
