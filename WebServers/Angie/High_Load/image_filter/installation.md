# Модуль image_filter в Angie: установка и настройка

## Определения

**Модуль image_filter** — высокопроизводительное динамическое расширение веб-сервера Angie, предназначенное для трансформации изображений (изменение размера, обрезка, поворот) и их конвертации между форматами в режиме реального времени.

**Динамический модуль (Dynamic Module)** — отдельно собираемый `.so`-библиотека, подключаемая к основному процессу Angie через директиву `load_module` без перекомпиляции сервера. Позволяет включать/отключать функциональность по требованию и упрощает обновление отдельных компонентов.

**libgd (GD Graphics Library)** — системная C-библиотека, предоставляющая примитивы для создания и обработки растровой графики. Модуль `image_filter` использует `libgd` как бэкенд для декомпрессии/сжатия изображений и математических операций над пиксельной матрицей. Поддержка современных форматов (AVIF, WebP, HEIC) определяется наличием соответствующих кодеков в собранной версии `libgd`.

## Базовые концепции

В отличие от стандартного Nginx, версия модуля в Angie (начиная с версии 1.11.0, выпущенной в декабре 2025 года) обладает расширенными возможностями:
- **Нативная поддержка современных форматов:** Полноценная поддержка чтения, проверки и записи форматов **AVIF**, **WebP** и **HEIC**.
- **Директива Convert:** Позволяет преобразовывать изображения «на лету» (например, JPEG → AVIF) без изменения их геометрии.
- **Динамическая загрузка:** Модуль поставляется в виде отдельного бинарного пакета и подключается без перекомпиляции основного сервера.
- **Внешние зависимости:** Работа модуля напрямую зависит от системной библиотеки `libgd` и связанных с ней кодеков (`libwebp`, `libavif`, `libheif`).

### Архитектура динамической загрузки

При старте Angie читает глобальный контекст `angie.conf` и инициализирует модули в порядке их объявления через `load_module`. Модуль `image_filter` регистрирует свои директивы в конфигурационном парсере; только после этого директивы `image_filter`, `image_filter_buffer` и т.д. становятся валидными в блоках `http`, `server` и `location`. При отсутствии `load_module` или неверном пути к `.so` файлу парсер возвращает ошибку `unknown directive "image_filter"`.

### Выбор между динамической трансформацией и статической прегенерацией

Динамический `image_filter` оправдан, когда пространство для хранения ограничено, количество вариантов размеров/форматов велико, или изображения пользовательские и непредсказуемые. Статическая прегенерация (на этапе сборки или CI/CD) эффективнее при фиксированном наборе вариантов и прогнозируемом трафике: она исключает нагрузку на CPU во время запроса.

| Критерий | Динамическая трансформация | Статическая прегенерация |
|:---------|:---------------------------|:-------------------------|
| Дисковое место | Минимальное (только оригинал) | Высокое (копии всех размеров) |
| Нагрузка на CPU | Высокая (при заполнении кэша) | Минимальная (только отдача) |
| Гибкость | Любые размеры/форматы из URL | Только предопределенные варианты |
| Сложность инфраструктуры | Требует кэш и защиту от DoS | Требует pipeline генерации |

### Жизненный цикл запроса

1. Клиент отправляет запрос на фронтенд с заголовком `Accept`, указывающим предпочтительный формат.
2. Фронтенд проверяет `proxy_cache`. При MISS проксирует запрос на внутренний сервер с `image_filter`.
3. Внутренний сервер загружает оригинал из хранилища, декомпрессирует его в RAM в объеме `image_filter_buffer`, применяет трансформации.
4. Результат возвращается фронтенду, который записывает его в кэш с ключом, учитывающим формат, и отдает клиенту.
5. Последующие запросы с теми же параметрами обслуживаются из кэша без обращения к `image_filter`.

## Практические сценарии

### Сценарий 1: Установка пакета модуля

Модуль устанавливается из официальных репозиториев Angie. Перед установкой убедитесь, что репозитории настроены согласно основному руководству.

```bash
# Для Debian/Ubuntu
sudo apt update
sudo apt install angie-module-image-filter

# Для RHEL/AlmaLinux/Rocky Linux
sudo dnf install angie-module-image-filter
```

#### Валидация установки

```bash
# Проверка наличия .so файла
ls -lh /usr/lib/angie/modules/ngx_http_image_filter_module.so
# → -rw-r--r-- 1 root root 1.2M ... ngx_http_image_filter_module.so
```

### Сценарий 2: Идемпотентная установка через автоматизацию

Для инфраструктуры как код (Ansible, SaltStack, Puppet) используйте идемпотентный скрипт, который проверяет состояние перед установкой.

```bash
#!/bin/bash
# image-filter-install.sh — идемпотентная установка модуля
set -euo pipefail

MODULE_PKG="angie-module-image-filter"
MODULE_SO="/usr/lib/angie/modules/ngx_http_image_filter_module.so"
CONF="/etc/angie/angie.conf"

if [[ $EUID -ne 0 ]]; then
    echo "Запустите от root или через sudo"
    exit 1
fi

# 1. Проверка: уже установлен?
if [[ -f "$MODULE_SO" ]] && rpm -q "$MODULE_PKG" >/dev/null 2>&1 || dpkg -s "$MODULE_PKG" >/dev/null 2>&1; then
    echo "Модуль $MODULE_PKG уже установлен"
    exit 0
fi

# 2. Установка
if command -v dnf >/dev/null 2>&1; then
    dnf install -y "$MODULE_PKG"
elif command -v apt >/dev/null 2>&1; then
    apt update && apt install -y "$MODULE_PKG"
else
    echo "Не поддерживаемый пакетный менеджер"
    exit 1
fi

# 3. Проверка
if [[ ! -f "$MODULE_SO" ]]; then
    echo "Ошибка: модуль не установлен"
    exit 1
fi

# 4. Активация (если еще не активен)
if ! grep -q "ngx_http_image_filter_module.so" "$CONF" 2>/dev/null; then
    sed -i '/^events {/i load_module modules/ngx_http_image_filter_module.so;' "$CONF"
fi

# 5. Проверка конфигурации
angie -t

echo "Модуль $MODULE_PKG установлен и активирован"
```

### Сценарий 3: Верификация поддержки форматов

Перед использованием убедитесь, что установленная версия Angie и системные библиотеки поддерживают нужные форматы.

1. **Проверка версии и флагов сборки:**
    ```bash
    angie -V 2>&1 | grep -E "1.1[1-9]|image_filter"
    # → Ожидаемый вывод: версия >= 1.11.0 и флаг --with-http_image_filter_module
    ```

2. **Проверка линковки с библиотеками (для HEIC/AVIF):**
    ```bash
    ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so | grep -E "webp|avif|heif"
    # → Должны отображаться пути к соответствующим .so файлам (libavif, libheif, libwebp)
    ```

3. **Проверка поддерживаемых форматов (smoke test):**
    ```bash
    # Создайте тестовые изображения или используйте существующие
    # Проверка поддержки AVIF
    file test.avif
    # → test.avif: ISO Media, AVIF Image Sequence

    # Проверка поддержки HEIC
    file test.heic
    # → test.heic: ISO Media, HEIF image, High Efficiency Image File Format
    ```

### Сценарий 4: Активация модуля в конфигурации

Для активации добавьте директиву `load_module` в глобальный контекст файла `/etc/angie/angie.conf` (вне блоков `http` или `events`).

```nginx
# Загрузка модуля
load_module modules/ngx_http_image_filter_module.so;

events {
    worker_connections 1024;
}

http {
    # Параметры обработки изображений настраиваются в блоках server/location
    include /etc/angie/http.d/*.conf;
}
```

#### Вариант A: Активация через drop-in файл

В системах, где `/etc/angie/angie.conf` управляется пакетом, создайте файл `/etc/angie/conf.d/modules.conf`:

```nginx
load_module modules/ngx_http_image_filter_module.so;
```

Angie включает файлы из `conf.d/` автоматически. Этот подход упрощает обновления пакета, так как основной `angie.conf` не меняется.

### Сценарий 5: Проверка корректности загрузки и перезагрузка

После внесения изменений в конфигурацию всегда выполняйте проверку синтаксиса.

```bash
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Перезагрузка без прерывания текущих соединений
sudo systemctl reload angie
```

#### Валидация через API Angie

```bash
# Проверка загруженных модулей
curl -s http://127.0.0.1:8080/api/6/http/modules | jq '.[] | select(.name | contains("image"))'
# → {"name":"ngx_http_image_filter_module",...}
```

### Сценарий 6: Интеграция с systemd и ресурсные лимиты

Для production-сред настройте systemd-юнит Angie с ограничениями памяти и приоритетом CPU. Создайте drop-in override:

```bash
sudo systemctl edit angie
```

Добавьте в файл:

```ini
[Service]
# Приоритет CPU для тяжелых операций трансформации
CPUSchedulingPolicy=static
CPUSchedulingPriority=50

# Лимит памяти на процесс (увеличить при большом числе параллельных трансформаций)
MemoryMax=4G
MemoryHigh=3G

# Ограничение на открытые файлы (важно при большом числе оригиналов)
LimitNOFILE=65536

# Защита от взаимоблокировок
WatchdogSec=10s
```

Примените и перезапустите:

```bash
sudo systemctl daemon-reload
sudo systemctl restart angie
```

#### Валидация

```bash
systemctl status angie
# → Main PID: 12345 (angie)
# → Memory: 256M (high: 3G, max: 4G)
# → CPU scheduling: static, priority 50

# Проверка активных лимитов
cat /proc/$(pgrep -o angie)/limits | grep "open files"
# → Max open files            65536                65536                files
```

### Сценарий 7: SELinux и AppArmor

В дистрибутивах с включенным SELinux (RHEL, AlmaLinux, Astra Linux) разрешите Angie читать оригиналы изображений и подключаться к Unix-сокетам.

```bash
# Разрешение на сетевые соединения (если backend на TCP)
sudo setsebool -P httpd_can_network_connect 1

# Если используете Unix-сокет, добавьте кастомный тип:
sudo semanage fcontext -a -t httpd_var_run_t "/var/run/angie_img_filter.sock"
sudo restorecon -v /var/run/angie_img_filter.sock
```

В Ubuntu/Debian с AppArmor убедитесь, что профиль `/etc/apparmor.d/usr.sbin.angie` позволяет чтение файлов изображений:

```bash
# Проверка режима AppArmor
sudo aa-status | grep angie
# → angie                 confined

# Если профиль блокирует доступ, добавьте правило:
# /var/www/images/originals/ r,
# /var/www/images/originals/** r,
```

### Сценарий 8: Автоматическая smoke-проверка после деплоя

Скрипт для CI/CD, который проверяет работоспособность модуля после установки или обновления.

```bash
#!/bin/bash
# smoke-test-image-filter.sh
set -euo pipefail

AN_GIE_API="http://127.0.0.1:8080/api/6"
TEST_IMAGE="/var/www/images/originals/smoke-test.jpg"
EXPECTED_FORMATS=("image/jpeg" "image/webp" "image/avif")

# 1. Проверка модуля
if ! curl -sf "$AN_GIE_API/http/modules" | jq -e '.[] | select(.name == "ngx_http_image_filter_module")' >/dev/null; then
    echo "FAIL: модуль image_filter не загружен"
    exit 1
fi

# 2. Проверка преобразования
for fmt in "${EXPECTED_FORMATS[@]}"; do
    status=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Accept: ${fmt}" \
        "https://img.example.com/smoke-test.jpg")
    if [[ "$status" != "200" ]]; then
        echo "FAIL: формат $fmt недоступен (HTTP $status)"
        exit 1
    fi
done

# 3. Проверка кэша
cache_status=$(curl -sI -H "Accept: image/avif" "https://img.example.com/smoke-test.jpg" | grep -i "x-cache-status" | awk '{print $2}' | tr -d '\r')
if [[ "$cache_status" != "HIT" ]]; then
    echo "WARN: кэш не работает (статус: $cache_status)"
fi

echo "PASS: smoke-тест пройден"
```

### Сценарий 9: Обновление и откат

#### Обновление модуля

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install --only-upgrade angie-module-image-filter

# RHEL
sudo dnf update angie-module-image-filter
```

После обновления всегда проверяйте синтаксис и перезагружайте:

```bash
sudo angie -t && sudo systemctl reload angie
```

#### Откат на предыдущую версию

```bash
# Debian/Ubuntu
sudo apt install angie-module-image-filter=1.11.0-1

# RHEL
sudo dnf downgrade angie-module-image-filter-1.11.0-1
```

### Сценарий 10: Многопоточная установка на кластер (Ansible)

Пример задачи Ansible для массовой установки:

```yaml
- name: Install image_filter module
    ansible.builtin.apt:
      name: angie-module-image-filter
      state: present
      update_cache: yes

- name: Activate module in angie.conf
    ansible.builtin.lineinfile:
      path: /etc/angie/angie.conf
      line: load_module modules/ngx_http_image_filter_module.so;
      insertbefore: '^events \{'
      state: present

- name: Validate configuration
    ansible.builtin.command: angie -t
    register: angie_test
    changed_when: false
    failed_when: angie_test.rc != 0

- name: Reload Angie
    ansible.builtin.systemd_service:
      name: angie
      state: reloaded
```

## Операции и команды

```bash
# Установка пакета (Debian/Ubuntu)
sudo apt install angie-module-image-filter

# Проверка, что модуль загружен
angie -M | grep image_filter
# → ngx_http_image_filter_module

# Проверка поддержки форматов (зависит от libgd)
angie -V 2>&1 | grep -i image-filter

# Применение после установки (без полного перезапуска)
sudo angie -t && sudo systemctl reload angie
# → syntax is ok / test is successful
```

## Устранение неисправностей (Troubleshooting)

| Симптом | Причина | Решение |
|:---|:---|:---|
| `unknown directive "image_filter"` | Модуль не подключен | Проверить `load_module modules/ngx_http_image_filter_module.so;` в `angie.conf` и снова `angie -t` |
| Пакет не найден | Нет репозитория Angie | Подключить официальный репозиторий и `apt update` |
| Ошибка `Failed to open file` при трансформации | Права на `/var/cache/angie/images/` и каталог оригиналов | Обеспечить права `www-data` (или `angie`) на запись в кэш и чтение оригиналов |
| Модуль не совпадает с бинарником Angie | Несовместимая версия | Переустановить пакет под текущую версию `angie` |

## Лучшие практики

1.  Устанавливайте модуль тем же менеджером пакетов, что и Angie, чтобы версии совпадали.
2.  На production закрепляйте версию (apt-mark hold / dnf versionlock), чтобы обновления ядра не утащили бинарник на другую версию.
3.  Храните оригиналы и кэш на разных дисках/разделах — кэш быстро вырастает и не должен конкурировать за место с оригиналами.
4.  Проверяйте `angie -M` после каждого обновления — image_filter легко «выпадает» из-за пересборки модулей.

## Дополнительная информация

### Файловая структура и права

| Путь | Назначение | Рекомендуемые права |
|:-----|:-----------|:--------------------|
| `/usr/lib/angie/modules/ngx_http_image_filter_module.so` | Бинарный модуль | `root:root`, `644` |
| `/etc/angie/angie.conf` | Основной конфиг | `root:root`, `644` |
| `/etc/angie/conf.d/` | Drop-in конфиги | `root:root`, `644` |
| `/var/www/images/originals/` | Хранилище оригиналов | `www-data:www-data`, `644` (файлы), `755` (директории) |
| `/var/cache/angie/images/` | Кэш трансформаций | `angie:angie`, `700` |

### Управление обновлениями

Для предотвращения нежелательных обновлений на production-серверах:
- **APT:** `sudo apt-mark hold angie-module-image-filter`
- **DNF:** `sudo dnf versionlock add angie-module-image-filter` (требует `python3-dnf-plugin-versionlock`).

### Docker

В минимальных образах (alpine, slim) могут отсутствовать системные зависимости `libgd`, `libavif`, `libheif`. Используйте официальные образы с суффиксом `-buildinfo` для проверки или устанавливайте зависимости вручную:

```dockerfile
FROM docker.angie.software/angie:alpine

RUN apk add --no-cache \
    libgd \
    libavif \
    libheif \
    angie-module-image-filter

COPY angie.conf /etc/angie/angie.conf
```

### Особенности дистрибутивов

- **Ubuntu 24.04+ / Debian 12+:** Имеют актуальную поддержку AVIF/HEIC "из коробки" в системных репозиториях.
- **RHEL 8/9:** Для установки графических библиотек может потребоваться подключение репозитория EPEL: `sudo dnf install epel-release`.
- **Astra Linux / РЕД ОС:** Используйте инструкции для Debian, подставляя кодовое имя версии. В системах с замкнутой программной средой установите `angie-digsig-key` для верификации.

### Устранение неисправностей

- **Ошибка "unknown directive image_filter":** Указывает на то, что модуль не был загружен через `load_module` или путь к `.so` файлу указан неверно. Проверьте правильность пути в `/usr/lib/angie/modules/`.
- **Ошибка 415 (Unsupported Media Type):**
    - **Недостаточный буфер:** Размер исходного изображения превышает `image_filter_buffer` (по умолчанию 1M). Для современных фото рекомендуется установить `20M`.
    - **Отсутствие кодеков:** Формат файла не поддерживается системной библиотекой `libgd`. Проверьте вывод `ldd` для подтверждения наличия необходимых библиотек.
- **Проблемы в Docker:**
    - В минимальных образах (alpine, slim) могут отсутствовать зависимости. Рекомендуется использовать официальные образы с суффиксом `-buildinfo` для проверки или устанавливать `libgd`, `libavif`, `libheif` вручную.
    - В Dockerfile установка может выглядеть так: `RUN apt-get update && apt-get install -y angie-module-image-filter`.

### См. также

- [Обзор возможностей модуля](./overview.md)
- [Безопасность и защита от DoS](./security.md)
- [Производительность и масштабирование](./performance.md)
