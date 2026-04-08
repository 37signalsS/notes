# Методы расшифровки TLS-трафика

## Определения

**Расшифровка TLS-трафика** — процесс получения доступа к содержимому зашифрованного TLS-соединения с использованием ключей сессии или промежуточных значений, полученных на этапе handshake.

**SSLKEYLOGFILE** — стандартный формат файла для записи TLS-ключей. Поддерживается Chromium, Firefox, Electron-приложениями, Mitmproxy. Формат записи: `LABEL <ClientRandom> <Secret>`.

**SSL Pinning** — механизм безопасности, при котором приложение проверяет не только валидность сертификата, но и его соответствие заранее заданным значениям (хеш, публичный ключ). Блокирует MITM-прокси.

**SChannel (Secure Channel)** — криптографическая подсистема Windows, управляющая TLS-соединениями через интерфейс SSPI. Хранит ключи в защищённой памяти `lsass.exe`.

## Основные концепции

### Ключевое для расшифровки: TLS 1.2 vs TLS 1.3

Полное описание handshake-процесса: **[Протокол TLS](../../Protocols/tls.md#процесс-рукопожатия-tls-handshake)**.

Различия, критичные для расшифровки:

| Аспект | TLS 1.2 | TLS 1.3 |
|---|---|---|
| **Генерация ключей** | Последовательная: premaster → master → session keys | Из множества промежуточных значений, «разбросаны» по handshake |
| **RSA-шифры** | Поддерживаются — можно расшифровать из приватного ключа сервера | Удалены — только ECDHE (PFS) |
| **Явные секреты в памяти** | premaster secret, master secret | Нет явных premaster/master — ключи выводятся на лету |
| **SSLKEYLOGFILE** | `CLIENT_RANDOM` (master secret) | Множество записей: `CLIENT_HANDSHAKE_TRAFFIC_SECRET`, `CLIENT_TRAFFIC_SECRET`, `SERVER_TRAFFIC_SECRET` |
| **Извлечение из памяти ОС** | Возможно при дампе lsass.exe/memory | Затруднено — ключи кратковременны |

### Perfect Forward Secrecy (PFS)

Кратко: каждая TLS-сессия использует уникальные эфемерные ключи (ECDHE). Подробности: **[PFS в TLS](../../Protocols/tls.md#perfect-forward-secrecy-pfs)**.

**Влияние на анализ:**

- Ключи действительны **только** для сессий, установленных **после** начала записи `SSLKEYLOGFILE`
- Старые сессии расшифровать невозможно
- Файл ключей должен записываться **непрерывно** во время захвата трафика

### Архитектура хранения ключей в ОС

| ОС | Подсистема | Процесс хранения | Метод доступа |
|---|---|---|---|
| **Windows** | SChannel / SSPI | `lsass.exe` | Ядерная отладка, специализированные скрипты |
| **Linux** | OpenSSL, GnuTLS | Процесс приложения | `SSLKEYLOGFILE`, LD_PRELOAD, eBPF |
| **macOS** | Secure Transport / Security Framework | Системные процессы | Keychain access, dtrace |

## Практические сценарии

### Сценарий 1: Расшифровка трафика браузера (SSLKEYLOGFILE)

**Применимость:** Chromium (Chrome, Edge, Яндекс), Firefox, Electron-приложения (Slack, Discord, VS Code).

**Шаги:**

1. Создание файла для ключей:
   ```bash
   export SSLKEYLOGFILE=~/tls-keys.log
   ```

2. Запуск браузера:
   ```bash
   chromium --ssl-key-log-file=~/tls-keys.log
   # или Firefox
   firefox --ssl-key-log-file=~/tls-keys.log
   ```

3. Настройка Wireshark:
   - `Edit → Preferences → Protocols → TLS`
   - Поле `(Pre)-Master-Secret log filename` → `~/tls-keys.log`

4. Захват трафика → в Wireshark появятся `Decrypted TLS`, `HTTP2`.

5. Анализ: `Follow → TCP Stream`, фильтр `http2` или `tls`.

**Ограничения:**
- Не работает с продакшен-версиями некоторых браузеров без флагов
- Ключи действительны только для текущей сессии
- После перезапуска браузера — новые ключи

**tshark:** `tshark -r capture.pcapng -o tls.keylog_file:/path/to/tls-keys.log`

### Сценарий 2: Использование MITM-прокси (Mitmproxy)

**Применимость:** Отладка мобильных приложений, десктопных клиентов **без SSL Pinning**.

**Шаги:**

1. Установка и запуск:
   ```bash
   pip install mitmproxy
   mitmproxy --listen-host 127.0.0.1 --listen-port 8080
   ```

2. Настройка клиента:
   - Прокси: `127.0.0.1:8080`
   - Для мобильных: Wi-Fi → прокси на IP хоста

3. Установка сертификата:
   - Посетите `http://mitm.it` через прокси
   - Скачайте и установите сертификат для вашей ОС
   - Android 7+: требуется root или модификация приложения

4. Запись ключей для Wireshark:
   ```bash
   mitmproxy --set sslkeylogfile=~/tls-keys.log
   ```

5. Анализ в Mitmproxy: просмотр запросов/ответов, модификация на лету, экспорт.

**Ограничения:**
- **Не работает с SSL Pinning**
- Firefox использует собственное хранилище сертификатов (нужен `--cert TrustStore`)

### Сценарий 3: Обход SSL Pinning

**Применимость:** Мобильные приложения (Android/iOS), десктопные клиенты с повышенными требованиями к безопасности.

| Метод | Платформа | Описание |
|---|---|---|
| **Frida** | Все | Динамическое внедрение JS для перехвата функций проверки сертификата |
| **Xposed Module** | Android | JustTrustMe, SSLUnpinning — хуки системных вызовов |
| **Патчинг** | Android/iOS | Дизассемблирование (IDA Pro, Ghidra) → модификация байт-кода |
| **Отключение на уровне ОС** | Android 7+ | Рут, переподпись приложения с разрешением user-сертификатов |

**Пример Frida:**
```bash
frida -U -f com.example.app --no-pause -l ssl-unpinning.js
```

**Инструменты:**
- **Frida** + **Objection** — фреймворк для исследования мобильных приложений
- **MobSF** — автоматизированный статический и динамический анализ

### Сценарий 4: Расшифровка трафика Windows (SChannel)

**Применимость:** Анализ трафика системных процессов, приложений Windows.

**Метод:** Ядерная отладка между двумя ВМ.

**Требования:**
- Две виртуальные машины Windows
- Kernel debugging через COM/Named Pipe/Network
- Инструменты: WinDbg, специализированные скрипты

**Шаги:**

1. Настройка отладки на целевой ВМ:
   ```cmd
   bcdedit /debug on
   bcdedit /dbgsettings serial debugport:1 baudrate:115200
   ```

2. Подключение WinDbg с хоста, установка breakpoints на функции SChannel.

3. Дамп памяти `lsass.exe` в момент TLS handshake → извлечение ключей из структур данных.

4. Конвертация в формат Wireshark:
   - Формат: `CLIENT_RANDOM <random> <secret>`
   - Специализированные скрипты (например, [tls-key-extractor](https://github.com/JamesForshaw/Keylogger))

**Ограничения:** Сложная настройка, требует глубокое знание Windows Internals, не все версии Windows поддерживаются.

### Сценарий 5: Приватный ключ сервера

**Применимость:** Когда у вас есть контроль над сервером.

**Шаги:**

1. Получение приватного ключа:
   - Файл `.key` или `.pem` с сервера
   - Обычно位於 `/etc/ssl/private/` или `/etc/nginx/ssl/`

2. Настройка Wireshark:
   - `Edit → Preferences → Protocols → TLS → RSA keys list`
   - Запись: `<IP>,<Port>,<Protocol>,<Keyfile>`
   - Пример: `192.168.1.100,443,http,/path/to/server.key`

3. Анализ: Wireshark автоматически расшифрует трафик.

**Ограничения:**
- **Не работает с ECDHE/DHE** (алгоритмы с PFS)
- Требует доступа к серверу
- Не применимо для сторонних сервисов

## Дополнительная информация

### Формат SSLKEYLOGFILE

```
# SSL/TLS secrets log file
# Format: LABEL <ClientRandom> <Secret>
CLIENT_RANDOM <hex-random> <hex-secret>
CLIENT_HANDSHAKE_TRAFFIC_SECRET <hex-random> <hex-secret>
CLIENT_TRAFFIC_SECRET <hex-random> <hex-secret>
SERVER_TRAFFIC_SECRET <hex-random> <hex-secret>
```

| Тип секрета | Версия TLS | Описание |
|---|---|---|
| `CLIENT_RANDOM` | TLS 1.2 | Master secret для расшифровки всей сессии |
| `CLIENT_EARLY_TRAFFIC_SECRET` | TLS 1.3 | 0-RTT ключи (ранние данные) |
| `CLIENT_HANDSHAKE_TRAFFIC_SECRET` | TLS 1.3 | Ключи handshake-фазы (клиент) |
| `SERVER_HANDSHAKE_TRAFFIC_SECRET` | TLS 1.3 | Ключи handshake-фазы (сервер) |
| `CLIENT_TRAFFIC_SECRET` | TLS 1.3 | Ключи трафика клиента (application data) |
| `SERVER_TRAFFIC_SECRET` | TLS 1.3 | Ключи трафика сервера (application data) |

### Инструменты для расшифровки

| Инструмент | Назначение | Платформа |
|---|---|---|
| **Wireshark** | Визуализация и расшифровка через SSLKEYLOGFILE / RSA keys | Все |
| **tshark** | Консольная расшифровка (`-o tls.keylog_file:...`) | Все |
| **Mitmproxy** | MITM-прокси с инспекцией и записью ключей | Все |
| **Frida** | Динамический перехват вызовов (обход SSL Pinning) | Все |
| **Objection** | Фреймворк для исследования мобильных приложений | Android/iOS |
| **Burp Suite** | Профессиональный MITM-прокси с GUI | Все |

### Связанные документы

- **[Протокол TLS](../../Protocols/tls.md)** — handshake, шифрование, PFS, Session Resumption
- **[Определения Wireshark](./definitions.md)** — инструменты захвата, форматы файлов, проблемы TLS
- **[Дополнительные возможности Wireshark](./advanced_features.md)** — coloring rules, flow graph, комментарии
- **[Практические сценарии](./practical_scenarios.md)** — установка, анализ протоколов
- **[tcpdump](../../../Linux/Diagnostics/Networking/tcpdump.md)** — консольный захват для последующей расшифровки
