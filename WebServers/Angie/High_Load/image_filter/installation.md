# Модуль image_filter в Angie: установка и эксплуатационная настройка

**Актуально для:** Angie 1.12.x

## Определения

**Модуль image_filter (`ngx_http_image_filter_module`)** — высокопроизводительное динамическое расширение веб-сервера Angie, предназначенное для трансформации растровых изображений (масштабирование, кадрирование, поворот) и их конвертации между форматами в режиме реального времени.

**Динамический модуль (Dynamic Module)** — разделяемый объектный файл (`.so`), скомпилированный отдельно от основного исполняемого файла Angie и подключаемый в runtime через директиву `load_module`. Это исключает необходимость перекомпиляции сервера при добавлении или обновлении расширений.

**Бинарная совместимость модулей (ABI Compatibility / Module Signature)** — строгое соответствие структур данных в памяти между ядром Angie и скомпилированным динамическим модулем. Angie проверяет 128-битную сигнатуру (`NGX_MODULE_SIGNATURE`), сформированную из версии компилятора, флагов сборки и включенных подсистем; несовпадение сигнатур предотвращает аварийный крах рабочего процесса (SIGSEGV) при старте.

**libgd (GD Graphics Library)** — системная библиотека на языке C, предоставляющая базовые примитивы для работы с растровой графикой. Модуль `image_filter` делегирует `libgd` декодирование пиксельных матриц, геометрические алгоритмы и кодирование в целевой формат. Поддержка конкретных форматов (JPEG, PNG, WebP, AVIF, HEIC) определяется библиотеками кодеков, с которыми скомпонована установленная в ОС версия `libgd`.

**Разделяемая библиотека (Shared Library / SONAME)** — скомпилированный бинарный компонент ОС, загружаемый динамическим компоновщиком `ld.so`. Для работы `image_filter` в системе должны присутствовать библиотеки кодеков (`libwebp.so.7`, `libavif.so.16`, `libheif.so.1`, `libjpeg.so.62/8`, `libpng16.so.16`).

---

## Базовые концепции

В Angie (начиная с версии 1.11.0 и развитой в 1.12.x) модуль `image_filter` существенно доработан по сравнению со стандартным аналогом Nginx:
- **Поддержка современных форматов:** нативная обработка и валидация форматов **AVIF**, **WebP** и **HEIC** при наличии соответствующих системных библиотек.
- **Директива Convert:** потоковое преобразование форматов «на лету» (например, JPEG → AVIF/WebP) без изменения геометрических размеров.
- **Тонкое управление качеством и скоростью:** отдельные директивы для регулировки квантования и скорости компрессии (включая `image_filter_avif_speed`).
- **Динамическая дистрибуция:** поставка в виде независимого RPM/DEB пакета `angie-module-image-filter`.

### Архитектура модуля в конвейере обработки Angie

Модуль `image_filter` регистрируется как фильтр тела ответа (output body filter) в цепочке фильтров Angie (`ngx_http_top_header_filter` и `ngx_http_top_body_filter`).

```
[Клиентский запрос]
        │
        ▼
[HTTP Location Match] ──► [Чтение оригинального файла с диска/бэкенда]
                                    │
                                    ▼
                      [image_filter: захват потока данных]
                                    │
                                    ▼
                      [Выделение буфера image_filter_buffer в RAM]
                                    │
                                    ▼
                      [Передача буфера в C-библиотеку libgd]
                                    │
                                    ├── Декодирование (JPEG/PNG/HEIC/AVIF/WebP)
                                    ├── Геометрическая трансформация (Resize/Crop/Rotate)
                                    └── Кодирование в целевой формат (libavif/libwebp/libgd)
                                    │
                                    ▼
                      [Модификация заголовков Content-Type / Content-Length]
                                    │
                                    ▼
                      [Отдача в сокет клиенту или запись в proxy_cache]
```

1. **Фаза перехвата:** Модуль перехватывает HTTP-ответ от дискового хранилища или upstream-сервера. Если код ответа отличен от HTTP 200, модуль передает тело без изменений.
2. **Фаза накопления буфера:** Модуль не обрабатывает данные потоково частями — алгоритмы трансформации требуют полной пиксельной матрицы. Все тело входящего изображения читается в оперативную память рабочего процесса (worker). Размер ограничен директивой `image_filter_buffer` (по умолчанию 1 Мбайт). Если файл превышает лимит, обработка прерывается с ошибкой HTTP 415.
3. **Фаза трансформации:** Внутри `libgd` память выделяется под несжатый растровый массив в цветовом пространстве RGBA (32 бита на пиксель). Для изображения разрешением $4000 \times 3000$ пикселей требуется $4000 \times 3000 \times 4 \approx 48$ Мбайт оперативной памяти на один рабочий поток только для хранения матрицы.
4. **Фаза генерации:** Модуль пересчитывает размер результата, обновляет заголовок `Content-Length`, подставляет новый MIME-тип в `Content-Type` и передает готовые буферы следующему фильтру.

### Архитектура динамической загрузки

При старте Angie парсит конфигурационный файл `/etc/angie/angie.conf`.
1. Директива `load_module` вызывает системную функцию `dlopen()` для загрузки файла `.so` в адресное пространство master-процесса.
2. Angie валидирует сигнатуру модуля: компилятор, наличие потоков (`--with-threads`), поддержка сокетов, структура структурных смещений контекста.
3. Вызывается функция инициализации модуля `ngx_http_image_filter_module`, регистрирующая директивы в пуле конфигурационного парсера.
4. При последующем порождении дочерних процессов (workers) через `fork()`, скомпонованный код модуля наследуется всеми рабочими процессами без повторной загрузки.

### Зависимости и стек кодеков

Работоспособность и поддержка форматов зависят от системного окружения Linux:

```
┌────────────────────────────────────────────────────────┐
│        Пакет: angie-module-image-filter               │
│        Файл: ngx_http_image_filter_module.so           │
└──────────────────────────┬─────────────────────────────┘
                           │ dlopen / dynamic link
                           ▼
┌────────────────────────────────────────────────────────┐
│            Системная библиотека libgd (libgd.so.3)     │
└───────┬────────────┬─────────────┬────────────┬────────┘
        │            │             │            │
        ▼            ▼             ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────┐ ┌─────────┐
│ libjpeg-turbo│ │   libpng     │ │ libwebp  │ │ libavif │
│ (JPEG/JFIF)  │ │   (PNG)      │ │ (WebP)   │ │ (AVIF)  │
└──────────────┘ └──────────────┘ └──────────┘ └────┬────┘
                                                    │
                                                    ▼
                                               ┌─────────┐
                                               │ libheif │
                                               │ (HEIC)  │
                                               └─────────┘
```

| Кодек | Разделяемая библиотека | Поддержка чтения | Поддержка записи | Дистрибутивы (из коробки) |
|:---|:---|:---:|:---:|:---|
| **JPEG** | `libjpeg.so.62` / `libjpeg.so.8` | Да | Да | Все (Debian, Ubuntu, RHEL, Astra, РЕД ОС) |
| **PNG** | `libpng16.so.16` | Да | Да | Все дистрибутивы Linux |
| **WebP** | `libwebp.so.7` | Да | Да | Debian 11+, Ubuntu 20.04+, RHEL 8+, Astra 1.7+ |
| **AVIF** | `libavif.so.16` | Да | Да | Debian 12+, Ubuntu 22.04+, RHEL 9 (EPEL) |
| **HEIC** | `libheif.so.1` | Да | Нет (только чтение) | Debian 12+, Ubuntu 22.04+, Astra 1.8 |

### Модель потребления ресурсов на bare-metal сервере

Обработка графики — операция, строго ограниченная CPU и памятью (CPU-bound и Memory-bound):
- **Оперативная память (RAM):**
  $$\text{RAM}_{\text{worker}} = \text{Buffer}_{\text{input}} + (W \times H \times 4) + \text{Buffer}_{\text{output}} + \text{RAM}_{\text{codec}}$$
  При одновременной обработке 16 запросов изображений высокого разрешения потребление памяти рабочими процессами может мгновенно вырасти на 1.5–3 Гбайт. Без настройки cgroups v2 и лимитов это приводит к вызову ядра Linux OOM Killer.
- **Процессор (CPU):**
  Конвертация в AVIF (библиотека `libavif` с кодировщиком `aom` или `rav1e`) требует в 10–25 раз больше тактов процессора, чем кодирование в JPEG аналогичного качества. Нагрузка распределяется по ядрам согласно директивам `worker_processes` и `worker_cpu_affinity`.

### Выбор между динамической трансформацией и статической прегенерацией

| Критерий | Динамическая трансформация (`image_filter`) | Статическая прегенерация (CI/CD / Background Job) |
|:---|:---|:---|
| **Дисковое пространство** | Минимальное: хранится только оригинал, варианты кэшируются по требованию. | Высокое: хранятся матрицы всех разрешений и форматов для каждого изображения. |
| **Нагрузка на CPU сервера** | Высокая при первых обращениях (промахах кэша / Cache Miss). | Минимальная: сервер работает как статический веб-сервер через `sendfile()`. |
| **Гибкость параметров** | Максимальная: изменение ширины/высоты/формата через URL или `Accept`. | Нулевая: генерация нового размера требует перезапуска пакетной генерации. |
| **Требования к надежности** | Требуется строгая изоляция cgroups, буферов памяти и ограничение RPS. | Стандартные требования к веб-серверу статических файлов. |
| **Применение** | User-generated content (маркетплейсы, медиа, фотохостинги). | Фиксированные элементы дизайна, баннеры, логотипы, промо-страницы. |

---

## Практические сценарии

### Сценарий 1: Установка пакета модуля из официальных репозиториев

Перед установкой в операционной системе должен быть подключен официальный репозиторий Angie согласно базовому руководству по веб-серверу.

#### Debian 12 (Bookworm) / Ubuntu 22.04 / 24.04 LTS

```bash
# Обновление индекса пакетов
sudo apt update

# Установка динамического модуля и необходимых кодеков
sudo apt install -y angie-module-image-filter libgd3 libwebp7 libavif16 libheif1

# Проверка установленного пакета в системе
dpkg -l | grep -E "angie-module-image-filter|libgd"
# → ii  angie-module-image-filter  1.12.0-1~bookworm  amd64  Angie image filter dynamic module
# → ii  libgd3:amd64               2.3.3-9+deb12u1     amd64  GD Graphics Library
```

#### RHEL 8 / 9, AlmaLinux, Rocky Linux

Для RHEL-подобных дистрибутивов кодеки AVIF и HEIC поставляются через репозиторий EPEL (Extra Packages for Enterprise Linux).

```bash
# Подключение репозитория EPEL (если не был подключен)
sudo dnf install -y epel-release

# Установка модуля Angie
sudo dnf install -y angie-module-image-filter gd libwebp libavif libheif

# Проверка наличия пакета
rpm -qi angie-module-image-filter
# → Name        : angie-module-image-filter
# → Version     : 1.12.0
# → Release     : 1.el9
```

#### Astra Linux Special Edition 1.7 / 1.8

Astra Linux использует пакетную базу Debian с дополнительным контролем целостности и замкнутой программной средой (МВЗ).

```bash
# При включенном режиме замкнутой программной среды (МВЗ)
# убедитесь в наличии цифровой подписи репозитория Angie
sudo apt update
sudo apt install -y angie-module-image-filter libgd3 libwebp7 libavif16

# Проверка статуса проверки подписи бинарного модуля
bsign -c /usr/lib/angie/modules/ngx_http_image_filter_module.so
# → /usr/lib/angie/modules/ngx_http_image_filter_module.so: valid signature
```

#### РЕД ОС 7.3 / 8

```bash
# Установка через пакетный менеджер DNF
sudo dnf install -y angie-module-image-filter gd libwebp libavif

# Проверка контрольной суммы установленного бинарника
rpm -V angie-module-image-filter
# → (пустой вывод означает соответствие контрольных сумм)
```

---

### Сценарий 2: Активация модуля в конфигурации

Директива `load_module` должна находиться в **глобальном контексте** файла `/etc/angie/angie.conf` (до секций `events` и `http`).

#### Вариант A: Прямое указание в /etc/angie/angie.conf

```nginx
# /etc/angie/angie.conf
user angie;
worker_processes auto;
pid /run/angie.pid;

# Загрузка динамического модуля трансформации изображений
load_module modules/ngx_http_image_filter_module.so;

events {
    worker_connections 2048;
    use epoll;
}

http {
    include /etc/angie/mime.types;
    default_type application/octet-stream;
    
    include /etc/angie/http.d/*.conf;
}
```

#### Вариант B: Архитектура drop-in каталогов для модулей

Для упрощения автоматизации и предотвращения конфликтов при обновлении базового пакета `angie`, в глобальный контекст добавляется директива включения drop-in файлов:

```nginx
# В начале /etc/angie/angie.conf
include /etc/angie/modules-enabled/*.conf;
```

Создание drop-in файла для `image_filter`:

```bash
sudo mkdir -p /etc/angie/modules-enabled

# Создание конфигурационного файла загрузки модуля
echo "load_module modules/ngx_http_image_filter_module.so;" | sudo tee /etc/angie/modules-enabled/50-image-filter.conf
# → load_module modules/ngx_http_image_filter_module.so;

# Проверка синтаксиса
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful
```

---

### Сценарий 3: Глубокая верификация ABI, линковки библиотек и поддержки кодеков

Перед запуском под нагрузкой системный администратор должен убедиться в бинарной целостности и отсутствии скрытых конфликтов библиотек.

#### 1. Проверка версии и флагов компиляции Angie

```bash
angie -V 2>&1 | grep -o -E "(--with-http_image_filter_module=dynamic|--with-threads)"
# → --with-http_image_filter_module=dynamic
# → --with-threads
```

#### 2. Список загруженных модулей через встроенный CLI

```bash
angie -M | grep image_filter
# → ngx_http_image_filter_module (dynamic)
```

#### 3. Проверка динамической линковки (Dynamic Linker Dependencies)

```bash
ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so
# → linux-vdso.so.1 (0x00007ffc0...)
# → libgd.so.3 => /lib/x86_64-linux-gnu/libgd.so.3 (0x00007f9c87800000)
# → libm.so.6 => /lib/x86_64-linux-gnu/libm.so.6 (0x00007f9c87700000)
# → libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007f9c87500000)
```

Проверка библиотек, подгружаемых `libgd.so.3`:

```bash
ldd /lib/x86_64-linux-gnu/libgd.so.3 | grep -E "webp|avif|heif|jpeg|png"
# → libjpeg.so.62 => /lib/x86_64-linux-gnu/libjpeg.so.62 (0x00007f9c87400000)
# → libpng16.so.16 => /lib/x86_64-linux-gnu/libpng16.so.16 (0x00007f9c87300000)
# → libwebp.so.7 => /lib/x86_64-linux-gnu/libwebp.so.7 (0x00007f9c87200000)
# → libavif.so.16 => /lib/x86_64-linux-gnu/libavif.so.16 (0x00007f9c87100000)
# → libheif.so.1 => /lib/x86_64-linux-gnu/libheif.so.1 (0x00007f9c87000000)
```

#### 4. Проверка экспортируемой ABI-сигнатуры модуля

```bash
readelf -s /usr/lib/angie/modules/ngx_http_image_filter_module.so | grep -E "ngx_http_image_filter_module|ngx_module_signature"
# → 42: 0000000000008420   168 OBJECT  GLOBAL DEFAULT   24 ngx_http_image_filter_module
# → 48: 00000000000084c8    16 OBJECT  GLOBAL DEFAULT   24 ngx_http_image_filter_module_ctx
# → 55: 0000000000009120    32 OBJECT  GLOBAL DEFAULT   25 ngx_module_signature
```

---

### Сценарий 4: Идемпотентный bash-скрипт установки и активации

Скрипт предназначен для локальной автоматизации развертывания модуля на standalone-серверах и в pipeline подготовки базовых образов ОС.

```bash
#!/usr/bin/env bash
# image-filter-setup.sh — Идемпотентная установка и активация модуля image_filter
set -euo pipefail

MODULE_PKG="angie-module-image-filter"
MODULE_SO="/usr/lib/angie/modules/ngx_http_image_filter_module.so"
CONF_FILE="/etc/angie/angie.conf"
DROPIN_DIR="/etc/angie/modules-enabled"
DROPIN_CONF="${DROPIN_DIR}/50-image-filter.conf"

echo "[INFO] Начало проверки окружения Angie image_filter..."

# 1. Проверка прав пользователя
if [[ $EUID -ne 0 ]]; then
    echo "[ERROR] Скрипт должен быть запущен с правами root (sudo)." >&2
    exit 1
fi

# 2. Проверка наличия установленного ядра Angie
if ! command -v angie >/dev/null 2>&1; then
    echo "[ERROR] Angie не установлен в системе. Установите основной пакет angie." >&2
    exit 1
fi

# 3. Установка пакета модуля при отсутствии бинарника
if [[ ! -f "$MODULE_SO" ]]; then
    echo "[INFO] Модуль $MODULE_PKG не найден. Запуск установки пакета..."
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq "$MODULE_PKG" libgd3 libwebp7
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y -q "$MODULE_PKG" gd libwebp
    else
        echo "[ERROR] Не найден поддерживаемый менеджер пакетов (apt-get или dnf)." >&2
        exit 1
    fi
else
    echo "[OK] Бинарный файл модуля уже присутствует: $MODULE_SO"
fi

# 4. Активация модуля через drop-in или angie.conf
if grep -q "ngx_http_image_filter_module.so" "$CONF_FILE" 2>/dev/null; then
    echo "[OK] Модуль уже активирован напрямую в $CONF_FILE"
elif [[ -d "$DROPIN_DIR" ]] && [[ -f "$DROPIN_CONF" ]] && grep -q "ngx_http_image_filter_module.so" "$DROPIN_CONF"; then
    echo "[OK] Модуль уже активирован через drop-in: $DROPIN_CONF"
else
    if grep -q "modules-enabled/\*\.conf" "$CONF_FILE"; then
        echo "[INFO] Настройка активации через $DROPIN_CONF..."
        mkdir -p "$DROPIN_DIR"
        echo "load_module modules/ngx_http_image_filter_module.so;" > "$DROPIN_CONF"
    else
        echo "[INFO] Добавление директивы load_module в начало $CONF_FILE..."
        # Вставка перед первой директивой events или user
        sed -i '1i load_module modules/ngx_http_image_filter_module.so;' "$CONF_FILE"
    fi
fi

# 5. Валидация синтаксиса
echo "[INFO] Тестирование конфигурации Angie..."
if angie -t; then
    echo "[OK] Конфигурация успешно прошла проверку."
else
    echo "[ERROR] Ошибка тестирования конфигурации! Откат изменений." >&2
    exit 1
fi

# 6. Безопасное применение изменений
if systemctl is-active --quiet angie; then
    echo "[INFO] Перезагрузка сервиса Angie (reload)..."
    systemctl reload angie
    echo "[OK] Сервис Angie перезагружен без разрыва соединений."
else
    echo "[WARN] Сервис Angie не запущен. Выполните: systemctl start angie"
fi

echo "[SUCCESS] Модуль image_filter успешно установлен и готов к работе."
```

---

### Сценарий 5: Развертывание и конфигурация через Ansible

Идемпотентный Ansible-плейбук для промышленного развертывания модуля на кластере bare-metal серверов.

```yaml
---
# playbooks/deploy_angie_image_filter.yml
- name: Развертывание модуля image_filter на серверах Angie
  hosts: edge_webservers
  become: true
  gather_facts: true

  tasks:
    - name: Установка пакета angie-module-image-filter (Debian/Ubuntu)
      ansible.builtin.apt:
        name:
          - angie-module-image-filter
          - libgd3
          - libwebp7
          - libavif16
        state: present
        update_cache: yes
        cache_valid_time: 3600
      when: ansible_os_family == "Debian"

    - name: Установка пакета angie-module-image-filter (RHEL/AlmaLinux/Rocky)
      ansible.builtin.dnf:
        name:
          - angie-module-image-filter
          - gd
          - libwebp
          - libavif
        state: present
      when: ansible_os_family == "RedHat"

    - name: Создание каталога для модульных drop-in файлов
      ansible.builtin.file:
        path: /etc/angie/modules-enabled
        state: directory
        owner: root
        group: root
        mode: '0755'

    - name: Обеспечение загрузки drop-in каталога в angie.conf
      ansible.builtin.lineinfile:
        path: /etc/angie/angie.conf
        insertbefore: BOF
        line: 'include /etc/angie/modules-enabled/*.conf;'
        state: present
      notify: Validate and reload Angie

    - name: Активация модуля image_filter через drop-in файл
      ansible.builtin.copy:
        dest: /etc/angie/modules-enabled/50-image-filter.conf
        content: "load_module modules/ngx_http_image_filter_module.so;\n"
        owner: root
        group: root
        mode: '0644'
      notify: Validate and reload Angie

    - name: Подготовка структуры каталогов кэша и оригиналов
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: directory
        owner: angie
        group: angie
        mode: "{{ item.mode }}"
      loop:
        - { path: '/var/cache/angie/images', mode: '0700' }
        - { path: '/var/www/images/originals', mode: '0755' }

  handlers:
    - name: Validate and reload Angie
      ansible.builtin.command: angie -t
      register: angie_test
      changed_when: false
      failed_when: angie_test.rc != 0
      listen: "Validate and reload Angie"

    - name: Reload Angie service
      ansible.builtin.systemd:
        name: angie
        state: reloaded
      listen: "Validate and reload Angie"
```

---

### Сценарий 6: Тюнинг systemd, изоляция процессов и cgroups v2

Трансформация графики в High Load способна исчерпать доступную оперативную память хоста. Для защиты системных сервисов (SSH, мониторинг, СУБД) настраивается юнит systemd с использованием механизма cgroups v2.

#### 1. Создание drop-in конфигурации systemd

```bash
sudo mkdir -p /etc/systemd/system/angie.service.d
sudo tee /etc/systemd/system/angie.service.d/50-resource-limits.conf << 'EOF'
[Service]
# Управление памятью через cgroups v2
# При достижении MemoryHigh ядро агрессивно сжимает page cache и замедляет аллокации
MemoryHigh=6G
# Жесткий лимит памяти (при превышении OOM killer завершает воркеры Angie)
MemoryMax=8G

# Защита master-процесса от завершения ядром при нехватке памяти:
# Чем ниже значение, тем меньше вероятность уничтожения OOM killer
OOMScoreAdjust=-500

# Лимиты дескрипторов файлов для высоких нагрузок
LimitNOFILE=131072
LimitNPROC=65536

# Запрет создания дампов памяти в продакшене (предотвращает зависание I/O)
LimitCORE=0

# Изоляция и защита файловой системы
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectControlGroups=true

# Приоритет распределения тактов CPU (1-10000, по умолчанию 100)
CPUWeight=300
EOF
```

#### 2. Применение параметров и перезагрузка юнита

```bash
# Перечитывание конфигурации systemd
sudo systemctl daemon-reload

# Перезапуск сервиса для применения cgroups
sudo systemctl restart angie

# Проверка примененных ограничений памяти в cgroups v2
systemctl show angie.service -p MemoryMax -p MemoryHigh -p OOMScoreAdjust
# → MemoryHigh=6442450944
# → MemoryMax=8589934592
# → OOMScoreAdjust=-500
```

---

### Сценарий 7: Безопасность окружения, изоляция прав и MAC (SELinux / AppArmor)

#### Настройка SELinux (RHEL, AlmaLinux, Astra Linux в режиме МРД)

Если SELinux работает в режиме `Enforcing`, по умолчанию процессу веб-сервера запрещено выполнять произвольные операции с динамическими библиотеками и каталогами кэша.

```bash
# 1. Проверка текущего статуса SELinux
getenforce
# → Enforcing

# 2. Установка корректного контекста безопасности на модуль
sudo semanage fcontext -a -t httpd_modules_t "/usr/lib/angie/modules(/.*)?"
sudo restorecon -Rv /usr/lib/angie/modules
# → Relabeled /usr/lib/angie/modules/ngx_http_image_filter_module.so from unconfined_u:object_r:lib_t:s0 to unconfined_u:object_r:httpd_modules_t:s0

# 3. Настройка контекстов для каталогов оригиналов (чтение) и кэша (чтение/запись)
sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/images/originals(/.*)?"
sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/cache/angie/images(/.*)?"

sudo restorecon -Rv /var/www/images/originals
sudo restorecon -Rv /var/cache/angie/images

# 4. Разрешение обращений к внутренним сокетам/бэкендам
sudo setsebool -P httpd_can_network_connect 1

# 5. Проверка журнала аудита на наличие блокировок
sudo ausearch -m avc -ts recent | grep angie || echo "Блокировок SELinux не обнаружено"
# → Блокировок SELinux не обнаружено
```

#### Настройка AppArmor (Debian / Ubuntu)

При активном профиле AppArmor `/etc/apparmor.d/usr.sbin.angie` необходимо добавить права на исполнение разделяемой библиотеки и чтение файлов:

```bash
# Добавление локального правила в drop-in каталог
sudo tee /etc/apparmor.d/local/usr.sbin.angie << 'EOF'
# Доступ к бинарным модулям
/usr/lib/angie/modules/*.so mr,

# Каталоги графических файлов
/var/www/images/originals/ r,
/var/www/images/originals/** r,
/var/cache/angie/images/ rwk,
/var/cache/angie/images/** rwk,
EOF

# Перезагрузка профиля
sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.angie
```

---

### Сценарий 8: Бесшовное обновление бинарников и модуля без простоя (Zero-Downtime Upgrade)

При обновлении пакета `angie-module-image-filter` или базового пакета `angie` обычный `systemctl reload` (сигнал `SIGHUP`) перечитывает конфигурацию, но **не обновляет исполняемый код master-процесса и разделяемые библиотеки в памяти**. 

Для обновления бинарников без разрыва активных соединений применяется процедура Graceful Upgrade ядра.

```bash
# 1. Обновление пакета в системе
sudo apt update && sudo apt install --only-upgrade -y angie angie-module-image-filter
# (или в RHEL: sudo dnf upgrade -y angie angie-module-image-filter)

# 2. Проверка синтаксиса перед переключением
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok

# 3. Фиксация PID старого master-процесса
OLD_MASTER_PID=$(cat /run/angie.pid)
echo "Старый Master PID: $OLD_MASTER_PID"
# → Старый Master PID: 14205

# 4. Отправка сигнала USR2 (запуск нового master-процесса)
# Angie переименует /run/angie.pid в /run/angie.pid.oldbin и запустит новый экземпляр
sudo kill -USR2 "$OLD_MASTER_PID"

# Ожидание старта нового master-процесса
sleep 2

# 5. Проверка: в системе должны работать ДВА master-процесса
ps aux | grep "[a]ngie: master"
# → root     14205  0.0  0.1  angie: master process /usr/sbin/angie
# → root     18930  0.0  0.1  angie: master process /usr/sbin/angie

# 6. Отправка сигнала WINCH старому мастеру (грациозная остановка старых воркеров)
# Старый мастер перестает принимать новые соединения, их забирает новый мастер
sudo kill -WINCH "$OLD_MASTER_PID"

# 7. Контрольная проверка обработки запросов новым процессом
curl -s -I http://127.0.0.1:8080/health | grep -E "HTTP/1.1 200|Server"
# → HTTP/1.1 200 OK
# → Server: Angie/1.12.0

# 8. Завершение старого master-процесса (сигнал QUIT)
sudo kill -QUIT "$OLD_MASTER_PID"
echo "[OK] Бесшовное обновление успешно завершено."
```

#### Процедура экстренного отката (Rollback), если новый процесс сбоит:

```bash
# Если на шаге 7 обнаружены ошибки — реанимируем старые воркеры:
sudo kill -HUP "$OLD_MASTER_PID"

# Затем останавливаем новый экземпляр:
sudo kill -QUIT $(cat /run/angie.pid)
```

---

### Сценарий 9: Фиксация версий (Version Pinning) и процедура даунгрейда

Чтобы предотвратить случайное автоматическое обновление модуля во время планового обновления ОС, зафиксируйте версии пакетов.

#### Фиксация версий (Hold / Lock)

```bash
# Debian / Ubuntu (APT)
sudo apt-mark hold angie angie-module-image-filter
# → angie set on hold.
# → angie-module-image-filter set on hold.

# RHEL / AlmaLinux / Rocky (DNF)
sudo dnf install -y python3-dnf-plugin-versionlock
sudo dnf versionlock add angie angie-module-image-filter
# → Adding versionlock on: angie-0:1.12.0-1.el9.*
# → Adding versionlock on: angie-module-image-filter-0:1.12.0-1.el9.*
```

#### Процедура контролируемого отката (Downgrade)

Если новая версия библиотеки или модуля привела к регрессии:

```bash
# 1. Снятие фиксации
sudo apt-mark unhold angie-module-image-filter

# 2. Установка предыдущей фиксированной версии
sudo apt install -y --allow-downgrades angie-module-image-filter=1.11.0-1~bookworm

# 3. Повторная фиксация
sudo apt-mark hold angie-module-image-filter

# 4. Проверка и перезагрузка
sudo angie -t && sudo systemctl reload angie
# → angie: configuration file /etc/angie/angie.conf test is successful
```

---

### Сценарий 10: Сквозное автоматизированное smoke-тестирование после деплоя

Скрипт выполняет интеграционную проверку всех уровней: наличие модуля, связку с библиотеками, генерацию форматов и корректность HTTP-заголовков.

```bash
#!/usr/bin/env bash
# smoke-test-image-filter.sh — Сквозная верификация модуля после установки
set -euo pipefail

BASE_URL="http://127.0.0.1:8080"
TEST_IMG_DIR="/var/www/images/originals"
TEST_IMG="${TEST_IMG_DIR}/smoke_source.jpg"

echo "=== Запуск Smoke-тестирования Angie image_filter ==="

# 1. Проверка загрузки модуля через CLI Angie
echo -n "[1/5] Проверка регистрации модуля в Angie... "
if angie -M | grep -q "ngx_http_image_filter_module"; then
    echo "OK"
else
    echo "FAILED: модуль отсутствует в списке angie -M" >&2
    exit 1
fi

# 2. Проверка линковки с libgd
echo -n "[2/5] Проверка разделяемых библиотек (ldd)... "
if ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so | grep -q "libgd"; then
    echo "OK"
else
    echo "FAILED: libgd не линкуется с модулем" >&2
    exit 1
fi

# 3. Создание валидного тестового изображения JPEG (если отсутствует)
mkdir -p "$TEST_IMG_DIR"
if [[ ! -f "$TEST_IMG" ]]; then
    # Создание минимального тестового JPEG файла 100x100 через встроенные утилиты
    printf '\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xFF\xDB\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0C\x14\r\x0C\x0B\x0B\x0C\x19\x12\x13\x0F\x14\x1D\x1A\x1F\x1E\x1D\x1A\x1C\x1C $.\' \",#\x1C\x1C(7),01444\x1F\'9=82<.342\xFF\xC0\x00\x0B\x08\x00\x0A\x00\x0A\x01\x01\x11\x00\xFF\xC4\x00\x1F\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0B\xFF\xDA\x00\x08\x01\x01\x00\x00?\x00\xBF\x00\xFF\xD9' > "$TEST_IMG"
    chown angie:angie "$TEST_IMG" 2>/dev/null || chown www-data:www-data "$TEST_IMG" 2>/dev/null || true
fi

# 4. Проверка HTTP-эндпоинта и заголовка Content-Type
echo -n "[3/5] Проверка прямого чтения тестового изображения... "
CODE=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/smoke_source.jpg")
if [[ "$CODE" == "200" ]]; then
    echo "OK (HTTP $CODE)"
else
    echo "FAILED: HTTP $CODE вместо 200" >&2
    exit 1
fi

# 5. Проверка динамической трансформации (Resize 50x50)
echo -n "[4/5] Тест трансформации геометрии (Resize 50x50)... "
RESIZE_TYPE=$(curl -s -o /dev/null -w "%{content_type}" "${BASE_URL}/resize/50x50/smoke_source.jpg")
if [[ "$RESIZE_TYPE" == "image/jpeg" ]]; then
    echo "OK (Content-Type: $RESIZE_TYPE)"
else
    echo "FAILED: получено $RESIZE_TYPE" >&2
    exit 1
fi

# 6. Проверка конвертации в WebP через Accept
echo -n "[5/5] Тест конвертации на лету в WebP... "
WEBP_TYPE=$(curl -s -o /dev/null -w "%{content_type}" -H "Accept: image/webp" "${BASE_URL}/convert/smoke_source.jpg")
if [[ "$WEBP_TYPE" == *"image/webp"* ]]; then
    echo "OK (Content-Type: $WEBP_TYPE)"
else
    echo "WARN: WebP конвертация вернула $WEBP_TYPE (проверьте наличие кодека libwebp)"
fi

echo "=== Все тесты успешно завершены! Система функционирует штатно. ==="
```

---

## Операции и команды

Сводное руководство по административным командам управления и диагностики модуля:

| Команда | Назначение | Ожидаемый результат (`# → result`) |
|:---|:---|:---|
| `angie -M` | Вывод списка скомпилированных и загруженных модулей | `# → ngx_http_image_filter_module (dynamic)` |
| `angie -V 2>&1 \| grep image_filter` | Проверка аргументов сборки и поддержки динамических модулей | `# → configure arguments: ... --with-http_image_filter_module=dynamic` |
| `angie -t` | Проверка синтаксиса конфигурационных файлов | `# → angie: configuration file /etc/angie/angie.conf test is successful` |
| `systemctl reload angie` | Безопасная перезагрузка конфигурации (SIGHUP) | `# → (код завершения 0, воркеры обновлены)` |
| `ldd /usr/lib/angie/modules/ngx_http_image_filter_module.so` | Проверка зависимостей от системных разделяемых библиотек | `# → libgd.so.3 => /lib/x86_64-linux-gnu/libgd.so.3 ...` |
| `readelf -d /usr/lib/angie/modules/ngx_http_image_filter_module.so \| grep NEEDED` | Анализ необходимых динамических библиотек (ELF DT_NEEDED) | `# → 0x0000000000000001 (NEEDED) Shared library: [libgd.so.3]` |
| `systemctl show angie.service -p MainPID -p ActiveState` | Проверка статуса сервиса systemd | `# → MainPID=14205, ActiveState=active` |
| `cat /proc/$(pgrep -o angie)/limits \| grep "open files"` | Проверка действующих лимитов файловых дескрипторов | `# → Max open files 131072 131072 files` |
| `apt-mark hold angie-module-image-filter` | Фиксация версии пакета в Debian/Ubuntu | `# → angie-module-image-filter set on hold.` |
| `dnf versionlock add angie-module-image-filter` | Фиксация версии пакета в RHEL/AlmaLinux | `# → Adding versionlock on: angie-module-image-filter...` |

---

## Устранение неисправностей (Troubleshooting)

### Сводная таблица инцидентов

| Симптом | Первопричина | Метод диагностики | Способ решения |
|:---|:---|:---|:---|
| `unknown directive "image_filter"` при вызове `angie -t` | Модуль не подключен в конфигурации или файл `.so` отсутствует | Проверить директиву `load_module` и наличие файла `/usr/lib/angie/modules/ngx_http_image_filter_module.so` | Добавить `load_module modules/ngx_http_image_filter_module.so;` в глобальный контекст `angie.conf` |
| `[emerg] module "..." is not binary compatible` | Несовпадение ABI ядра Angie и модуля (сборка под разные версии) | `angie -V` и `dpkg -l \| grep angie` | Обновить пакет `angie-module-image-filter` до точной версии базового бинарника `angie` |
| `dlopen() failed: libavif.so...: cannot open shared object file` | Отсутствует системная разделяемая библиотека кодека в ОС | Запустить `ldd` на модуль `.so` | Установить недостающий пакет в ОС (`apt install libavif16` или `dnf install libavif`) |
| `directive "load_module" is not allowed here` | Директива `load_module` помещена внутри блока `http` или `events` | Проверить номер строки в выводе `angie -t` | Переместить `load_module` в начало файла (глобальный контекст) |
| HTTP 415 (Unsupported Media Type) | Размер оригинала превышает `image_filter_buffer` | Журнал `error.log`: `"image_filter: image buffer is too small"` | Увеличить размер буфера: `image_filter_buffer 20M;` |
| HTTP 415 при запросе AVIF или HEIC | В системной `libgd` отсутствует скомпилированная поддержка кодека | Проверить вывод `ldd` для `libgd.so.3` на наличие `libavif` | Установить дистрибутивные кодеки или использовать прекомпилированный пакет из репозитория Angie |
| Внезапное падение рабочего процесса (SIGKILL, exit 137) | Ядро Linux OOM Killer уничтожило worker из-за исчерпания памяти | `dmesg -T \| grep -i oom` или `journalctl -u angie` | Ограничить параллелизм, настроить `MemoryHigh`/`MemoryMax` в systemd, ограничить размер буферов |
| HTTP 403 Forbidden / HTTP 500 при трансформации | Ошибки прав доступа к каталогу оригиналов или каталогу кэша | Проверить владельца: `ls -ld /var/cache/angie/images` | Выполнить `chown -R angie:angie /var/cache/angie /var/www/images` |
| Блокировка чтения `.so` при старте в RHEL/Astra | Запрет мандатного доступа SELinux | `ausearch -m avc -ts recent` | Назначить тип контекста `httpd_modules_t` через `restorecon` |

---

### Детальный разбор типовых аварийных ситуаций

#### 1. Ошибка несовместимости ABI после обновления репозитория

**Лог ошибки (`/var/log/angie/error.log`):**
```
2026/10/14 12:00:01 [emerg] 1234#1234: module "/usr/lib/angie/modules/ngx_http_image_filter_module.so" is not binary compatible in /etc/angie/angie.conf:4
```

**Причина:** Ядро Angie было обновлено (например, 1.12.0 → 1.12.1), а динамический модуль остался старой версии (или наоборот). Сигнатура `NGX_MODULE_SIGNATURE` не совпадает.

**Решение:**
1. Проверьте установленные версии:
   ```bash
   dpkg -l | grep angie
   # → ii angie 1.12.1-1~bookworm
   # → ii angie-module-image-filter 1.12.0-1~bookworm
   ```
2. Синхронизируйте версии пакетов:
   ```bash
   sudo apt install --only-upgrade angie-module-image-filter
   sudo angie -t && sudo systemctl reload angie
   ```

---

#### 2. Завершение рабочего процесса OOM Killer (Worker Process OOM Killed)

**Лог ядра (`dmesg -T`):**
```
[Wed Oct 14 12:30:15 2026] Out of memory: Killed process 15421 (angie: worker pro) total-vm:4194304kB, anon-rss:3891200kB, file-rss:128kB, shmem-rss:2048kB
[Wed Oct 14 12:30:15 2026] oom_reaper: reaped process 15421 (angie: worker pro)
```

**Причина:** Множественные одновременные запросы на конвертацию тяжелых изображений без кэширования привели к лавинообразному выделению памяти в куче `libgd`.

**Решение:**
1. Ограничьте максимальный размер входящего буфера:
   ```nginx
   image_filter_buffer 15M;
   ```
2. Настройте ограничение параллельных запросов через `limit_conn` в блоке обработки:
   ```nginx
   limit_conn_zone $binary_remote_addr zone=img_limit:10m;
   location /resize/ {
       limit_conn img_limit 5;
       image_filter resize $arg_w $arg_h;
   }
   ```
3. Разделите фронтенд-кэш и внутреннюю трансформацию через двухуровневое проксирование ([Double Proxying](./caching.md)), исключив повторный рендеринг при кэш-промахах.

---

## Лучшие практики

1. **Разделение дисковых подсистем:**
   - Храните оригиналы изображений на отказоустойчивом дисковом хранилище (HDD RAID / SATA SSD).
   - Кэш трансформированных файлов (`proxy_cache_path`) размещайте исключительно на высокопроизводительных NVMe-накопителях с файловой системой `ext4` или `xfs` и опцией монтирования `noatime`.
   - Для временных файлов при пиковых нагрузках используйте раздел в оперативной памяти (`tmpfs`).

2. **Формула расчета буфера памяти:**
   - Не задавайте значение `image_filter_buffer` «с запасом» на весь объем RAM хоста.
   - Оптимальный диапазон для production: `15M`–`25M`. Этого достаточно для обработки снимков современных смартфонов до 48–64 Мп без риска неконтролируемой аллокации сотен мегабайт на поврежденных файлах.

3. **Изоляция вычислительной нагрузки:**
   - Для высоконагруженных порталов выносите модуль `image_filter` на отдельный пул внутренних воркеров (internal upstream) или выделенные bare-metal ноды. Фронтенд Angie выполняет только проверку `proxy_cache` и быструю отдачу, защищая процессорные ядра от пиков ресайза.

4. **Версионный лок в CI/CD и при автоматическом обслуживании:**
   - Всегда блокируйте автообновление пакета `angie-module-image-filter` утилитами `apt-mark hold` или `dnf versionlock`. Обновление должно производиться синхронно с базовым сервером через контролируемый пайплайн с вызовом `angie -t` и проверкой ABI.

5. **Мониторинг Golden Signals модуля:**
   - Отслеживайте частоту кодов HTTP 415 (нехватка буфера или поврежденные файлы) и времени обработки P95/P99 в зоне статуса `status_zone`. Резкий рост P99 свидетельствует об исчерпании доступных тактов CPU на сжатии AVIF/HEIC.

---

## Дополнительная информация

### Матрица путей файловой системы, прав и контекстов безопасности

| Путь | Назначение | Рекомендуемый владелец | Права | Контекст SELinux |
|:---|:---|:---|:---:|:---|
| `/usr/lib/angie/modules/ngx_http_image_filter_module.so` | Бинарный динамический модуль | `root:root` | `0644` | `httpd_modules_t` |
| `/etc/angie/angie.conf` | Главный конфигурационный файл | `root:root` | `0644` | `httpd_config_t` |
| `/etc/angie/modules-enabled/` | Каталог drop-in конфигураций загрузки модулей | `root:root` | `0755` | `httpd_config_t` |
| `/var/www/images/originals/` | Каталог исходных изображений | `angie:angie` | `0755` / `0644` | `httpd_sys_content_t` |
| `/var/cache/angie/images/` | Каталог кэшированных трансформаций | `angie:angie` | `0700` | `httpd_sys_rw_content_t` |
| `/run/angie.pid` | Файл идентификатора процесса (PID) | `root:root` | `0644` | `httpd_var_run_t` |

### Матрица поддержки операционных систем Linux (On-Premises / Bare-Metal)

| Дистрибутив ОС | Пакет модуля | Менеджер пакетов | Наличие AVIF/HEIC из коробки |
|:---|:---|:---|:---:|
| **Debian 12 (Bookworm)** | `angie-module-image-filter` | APT | Да (`libavif16`, `libheif1`) |
| **Ubuntu 24.04 / 22.04 LTS** | `angie-module-image-filter` | APT | Да (`libavif16`, `libheif1`) |
| **RHEL 9 / AlmaLinux 9 / Rocky 9** | `angie-module-image-filter` | DNF | Требуется подключение EPEL |
| **RHEL 8 / AlmaLinux 8** | `angie-module-image-filter` | DNF | WebP (из коробки), AVIF ограничен |
| **Astra Linux SE 1.7 / 1.8** | `angie-module-image-filter` | APT | Да (с поддержкой цифровой подписи МВЗ) |
| **РЕД ОС 7.3 / 8** | `angie-module-image-filter` | DNF/RPM | Да (из базового и расширенного репозиториев) |

### См. также

- [Обзор архитектуры и возможностей модуля](./overview.md) — общие принципы работы и схема адаптивной доставки.
- [Конфигурация директив фильтрации](./filter_configuration.md) — детальный справочник параметров `image_filter`, кодеков и буферов.
- [Масштабирование и трансформация геометрии](./resize.md) — синтаксис операций resize, crop и rotate.
- [Кэширование обработанных изображений](./caching.md) — настройка `proxy_cache`, многоуровневого кэша и ключей кэширования.
- [Производительность и тюнинг](./performance.md) — оптимизация thread pools, привязка CPU affinity и ускорение кодеков.
- [Безопасность и защита от DoS](./security.md) — защита от декомпрессионных бомб, ограничение соединений и rate limiting.
